"""Registro de decisiones en archivos JSONL diarios (spec 007, VJT-040 a 046)."""

import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DecisionRecorder:
    """Escritor solo por anexión para registrar decisiones y aplicar retención (VJT-040)."""

    def __init__(
        self,
        dir_path: Path | str,
        retention_days: int = 90,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.dir_path = Path(dir_path)
        self.retention_days = retention_days
        self._clock = clock if clock is not None else time.time
        self._recorded_events: set[str] = set()
        self._lock = threading.Lock()

    def record(self, evento: dict[str, Any]) -> None:
        """Registra una decisión de forma determinista y sin lanzar excepciones (VJT-030)."""
        try:
            event_id = str(evento.get("event_id", ""))
            with self._lock:
                if event_id and event_id in self._recorded_events:
                    return  # Ya registrado, no duplicar (VJT-041)

            now_epoch = self._clock()
            now_dt = datetime.fromtimestamp(now_epoch, tz=UTC)
            date_str = now_dt.strftime("%Y-%m-%d")

            payload = dict(evento)
            if "timestamp" not in payload:
                payload["timestamp"] = now_dt.isoformat()
            if "cost_usd" not in payload:
                payload["cost_usd"] = "no calculado"  # VJT-045, Q2

            line = json.dumps(payload, ensure_ascii=False) + "\n"

            with self._lock:
                self.dir_path.mkdir(parents=True, exist_ok=True)
                file_path = self.dir_path / f"decision-{date_str}.jsonl"
                with file_path.open("a", encoding="utf-8") as f:
                    f.write(line)

                if event_id:
                    self._recorded_events.add(event_id)

        except Exception as exc:  # noqa: BLE001
            # Nunca lanza ante fallos de disco o registro (VJT-030)
            logger.warning("Fallo al registrar decisión en disco: %s", exc)

    def prune_retention(self) -> None:
        """Elimina archivos de registro que superen la retención configurada (VJT-043)."""
        try:
            now_epoch = self._clock()
            limit_epoch = now_epoch - (self.retention_days * 86400)

            if not self.dir_path.exists():
                return

            for file_path in self.dir_path.glob("decision-*.jsonl"):
                stat = file_path.stat()
                if stat.st_mtime < limit_epoch:
                    try:
                        file_path.unlink()
                    except OSError:
                        pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fallo en poda de retención: %s", exc)
