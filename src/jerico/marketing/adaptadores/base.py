"""Clase base y contratos para los adaptadores de difusión multicanal de Jericó."""

import hashlib
import os
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from jerico.schemas.marketing import CampanaMarketing, CanalMarketing


class ResultadoDespacho(BaseModel):
    """Resultado estructurado de un intento de despacho por un adaptador."""

    exitoso: bool
    campana_id: str
    canal: CanalMarketing
    destinatario: str
    idempotency_key: str
    dry_run: bool
    mensaje: str
    detalles: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AdaptadorCanalBase(ABC):
    """Clase base abstracta para cualquier adaptador de canal de marketing."""

    def __init__(self, dry_run: bool | None = None) -> None:
        if dry_run is not None:
            self.dry_run = dry_run
        else:
            env_val = os.getenv("JERICO_EXTERNAL_COMMS_DRY_RUN", "true").lower()
            self.dry_run = env_val in ("true", "1", "yes")

    def calcular_idempotency_key(
        self,
        campana_id: str,
        destinatario: str,
        contenido_hash: str,
    ) -> str:
        """Calcula una llave determinista SHA-256 para prevenir envíos duplicados."""
        semilla = f"{campana_id}:{destinatario}:{contenido_hash}"
        return hashlib.sha256(semilla.encode("utf-8")).hexdigest()

    @abstractmethod
    def despachar(
        self,
        campana: CampanaMarketing,
        destinatario: str,
        **kwargs: Any,
    ) -> ResultadoDespacho:
        """Ejecuta el despacho al destinatario para la campaña indicada."""
