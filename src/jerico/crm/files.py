"""Almacén local de adjuntos (plan §6.3; VCRM-008): escritura atómica y borrado idempotente."""

import os
import uuid
from pathlib import Path
from typing import BinaryIO

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 20 MB (decisión P-12)


class AttachmentTooLarge(ValueError):
    """El adjunto supera el límite; no se guarda nada."""


class LocalFileStore:
    def __init__(self, base_dir: Path, max_bytes: int = MAX_ATTACHMENT_BYTES) -> None:
        self.base_dir = base_dir
        self.max_bytes = max_bytes

    def new_tmp_path(self, suffix: str = "") -> Path:
        """Ruta temporal en el mismo volumen que el destino (renombrado atómico)."""
        tmp_dir = self.base_dir / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        return tmp_dir / f"{uuid.uuid4().hex}{suffix}"

    def save_atomic(self, lead_id: int, tmp_path: Path) -> str:
        if tmp_path.stat().st_size > self.max_bytes:
            tmp_path.unlink(missing_ok=True)
            raise AttachmentTooLarge(f"adjunto supera {self.max_bytes} bytes")
        key = f"{lead_id}/{uuid.uuid4().hex}{tmp_path.suffix}"
        dest = self._resolve(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp_path, dest)
        return key

    def delete(self, storage_key: str) -> None:
        """Archivo ausente = éxito (reintentos idempotentes)."""
        self._resolve(storage_key).unlink(missing_ok=True)

    def open(self, storage_key: str) -> BinaryIO:
        return self._resolve(storage_key).open("rb")

    def _resolve(self, storage_key: str) -> Path:
        base = self.base_dir.resolve()
        path = (base / storage_key).resolve()
        if not path.is_relative_to(base) or path == base:
            raise ValueError("clave de almacenamiento fuera del directorio base")
        return path
