"""Escritor de archivos diarios JSONL con retención y reescritura atómica (VJC-020 a 023)."""

import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

# Colombia no usa horario de verano desde 1993: UTC-5 fijo es respaldo exacto.
_BOGOTA_FIXED = timezone(timedelta(hours=-5), "America/Bogota")


def _load_bogota() -> tzinfo:
    try:
        return ZoneInfo("America/Bogota")
    except ZoneInfoNotFoundError:
        return _BOGOTA_FIXED


BOGOTA_TZ = _load_bogota()


class DailyJsonlWriter:
    """Escritor y gestor concurrente de archivos diarios JSONL con garantía de atomicidad."""

    def __init__(
        self,
        dir_path: Path | str,
        *,
        prefix: str = "",
        tz: tzinfo = BOGOTA_TZ,
        clock: Callable[[], float] | None = None,
        retention_days: int = 90,
        max_record_bytes: int = 4096,
    ) -> None:
        self.dir_path = Path(dir_path)
        self.prefix = prefix
        self.tz = tz
        self._clock = clock if clock is not None else time.time
        self.retention_days = retention_days
        self.max_record_bytes = max_record_bytes
        self._lock = threading.Lock()

    def _get_date_str(self, epoch: float | None = None) -> str:
        t = epoch if epoch is not None else self._clock()
        dt = datetime.fromtimestamp(t, tz=self.tz)
        return dt.strftime("%Y-%m-%d")

    def _file_path(self, date_str: str) -> Path:
        return self.dir_path / f"{self.prefix}{date_str}.jsonl"

    def append(self, record: dict[str, Any], date_str: str | None = None) -> None:
        """Escribe un registro en una línea JSON al archivo del día (VJC-020)."""
        line_str = json.dumps(record, ensure_ascii=False)
        line_bytes = (line_str + "\n").encode("utf-8")
        if len(line_bytes) > self.max_record_bytes:
            raise ValueError(f"Registro excede los {self.max_record_bytes} bytes (4 KB)")

        d_str = date_str if date_str is not None else self._get_date_str()
        target_file = self._file_path(d_str)

        with self._lock:
            self.dir_path.mkdir(parents=True, exist_ok=True)
            if target_file.exists() and target_file.stat().st_size > 0:
                with target_file.open("rb+") as f:
                    f.seek(-1, 2)
                    last_byte = f.read(1)
                    if last_byte != b"\n":
                        f.seek(0, 2)
                        f.write(b"\n")
            with target_file.open("ab") as f:
                f.write(line_bytes)

    def read_day(self, date_str: str) -> list[dict[str, Any]]:
        """Lee y parsea las líneas JSON del día, descartando líneas parciales o corruptas."""
        target_file = self._file_path(date_str)
        if not target_file.exists():
            return []

        results: list[dict[str, Any]] = []
        with self._lock, target_file.open("r", encoding="utf-8") as f:
            for raw_line in f:
                stripped = raw_line.strip()
                if not stripped:
                    continue
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, dict):
                        results.append(parsed)
                except Exception:  # noqa: S112
                    # Descartar línea parcial o ilegible (VJC-004, VJC-020)
                    continue
        return results

    def _is_matching_file(self, file_path: Path) -> bool:
        stem = file_path.stem
        if self.prefix:
            return stem.startswith(self.prefix)
        return not stem.startswith("retiros-")

    def purge(self, retention_days: int | None = None) -> int:
        """Elimina archivos con fecha anterior al número de días de retención (VJC-021)."""
        retention = retention_days if retention_days is not None else self.retention_days
        now_dt = datetime.fromtimestamp(self._clock(), tz=self.tz)
        cutoff_date = (now_dt - timedelta(days=retention)).date()

        purged_count = 0
        with self._lock:
            if not self.dir_path.exists():
                return 0

            for file_path in self.dir_path.glob("*.jsonl"):
                if not self._is_matching_file(file_path):
                    continue
                stem = file_path.stem
                if self.prefix and stem.startswith(self.prefix):
                    date_part = stem[len(self.prefix) :]
                else:
                    date_part = stem
                try:
                    file_date = datetime.strptime(date_part, "%Y-%m-%d").date()
                except ValueError:
                    continue

                if file_date < cutoff_date:
                    try:
                        file_path.unlink()
                        purged_count += 1
                    except OSError as exc:
                        logger.warning("Fallo al purgar archivo %s: %s", file_path, exc)
        return purged_count

    def rewrite_without(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        date_str: str | None = None,
    ) -> list[dict[str, Any]]:
        """Elimina líneas que cumplan el predicado de forma atómica (VJC-022, VJC-023).

        Si un archivo no puede reescribirse, lo elimina por completo e informa.
        Devuelve la lista de registros retirados.
        """
        with self._lock:
            if not self.dir_path.exists():
                return []

            if date_str is not None:
                files = [self._file_path(date_str)]
                files = [f for f in files if f.exists()]
            else:
                files = [f for f in self.dir_path.glob("*.jsonl") if self._is_matching_file(f)]

            all_removed: list[dict[str, Any]] = []

            for file_path in files:
                valid_kept: list[dict[str, Any]] = []
                file_removed: list[dict[str, Any]] = []
                has_corrupt_lines = False

                try:
                    with file_path.open("r", encoding="utf-8") as f:
                        for raw_line in f:
                            stripped = raw_line.strip()
                            if not stripped:
                                continue
                            try:
                                record = json.loads(stripped)
                                if isinstance(record, dict):
                                    if predicate(record):
                                        file_removed.append(record)
                                    else:
                                        valid_kept.append(record)
                                else:
                                    has_corrupt_lines = True
                            except Exception:
                                has_corrupt_lines = True

                    if not file_removed and not has_corrupt_lines:
                        # Nada que cambiar
                        continue

                    # Escritura atómica mediante archivo temporal
                    tmp_file = file_path.with_suffix(".tmp")
                    with tmp_file.open("w", encoding="utf-8") as tf:
                        for record in valid_kept:
                            tf.write(json.dumps(record, ensure_ascii=False) + "\n")

                    tmp_file.replace(file_path)
                    all_removed.extend(file_removed)

                except Exception as exc:
                    # VJC-023: Si no puede reescribir, elimina el archivo completo y avisa
                    logger.warning(
                        "No se pudo reescribir %s; eliminando archivo completo: %s",
                        file_path.name,
                        exc,
                    )
                    try:
                        if file_path.exists():
                            file_path.unlink()
                    except OSError:
                        pass
                    # También limpiar temporal si quedó
                    tmp_candidate = file_path.with_suffix(".tmp")
                    if tmp_candidate.exists():
                        try:
                            tmp_candidate.unlink()
                        except OSError:
                            pass

            return all_removed
