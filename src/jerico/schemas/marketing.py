"""Esquemas de datos para el subsistema de Marketing y Marca (Spec 008, Frente F5).

Modelos Pydantic para ingesta de ideas, campañas multicanal, configuración de Meta Ads
y resultados de auditoría de linter de marca.
"""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CanalMarketing(StrEnum):
    CORREO = "correo"
    WHATSAPP_OFICIAL = "whatsapp_oficial"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    META_ADS = "meta_ads"


class EstadoCampana(StrEnum):
    BORRADOR = "borrador"
    EN_REVISION = "en_revision"
    APROBADA = "aprobada"
    RECHAZADA = "rechazada"
    DESPACHADA = "despachada"


class ClasificacionCampana(StrEnum):
    C1 = "C1"  # Primero entendemos (Diagnóstico operativo / Solución)
    C2 = "C2"  # Del papel al sistema (Evolución / Radar de Vencimientos)
    C3 = "C3"  # Alguien responde (Integridad / Responsabilidad humana)
    C4 = "C4"  # Tus datos, bajo llave (Seguridad / Privacidad Ley 1581)
    C5 = "C5"  # Aquí crece quien construye (Mérito / Cultura y equipo)


class Trato(StrEnum):
    TU = "tu"
    USTED = "usted"


class IdeaInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=3, max_length=100)
    texto: str = Field(min_length=1)
    origen: str = Field(default="telegram", max_length=50)
    autor: str = Field(default="cto", max_length=50)
    creado_en: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LinterViolation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regla: str
    mensaje: str
    severidad: str = "error"


class LinterResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valido: bool
    errores: list[LinterViolation] = Field(default_factory=list)
    advertencias: list[LinterViolation] = Field(default_factory=list)
    nombre_valido: bool = True
    trato_detectado: str | None = None
    tagline_valido: bool = True
    tokens_validos: bool = True


class MetaAdConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objetivo: str = Field(default="MESSAGES", max_length=50)
    presupuesto_diario_usd: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    gasto_autorizado_usd: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    status: str = Field(default="PAUSED", max_length=20)
    call_to_action: str = Field(default="WHATSAPP_MESSAGE", max_length=50)
    adset_nombre: str = Field(default="Intereses PYME Colombia", max_length=100)

    @field_validator("status")
    @classmethod
    def _validate_status_paused(cls, value: str) -> str:
        if value != "PAUSED":
            raise ValueError("status inicial debe ser 'PAUSED' para evitar cargos involuntarios")
        return value


class CampanaMarketing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=3, max_length=100)
    nombre: str = Field(min_length=1, max_length=200)
    clasificacion_campana: ClasificacionCampana
    canal: CanalMarketing
    trato: Trato
    copy_principal: str = Field(min_length=1)
    activo_multimedia_uri: str | None = None
    meta_ad_config: MetaAdConfig | None = None
    presupuesto_estimado_usd: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    gasto_autorizado_usd: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    estado: EstadoCampana = EstadoCampana.BORRADOR
    idempotency_key: str = Field(min_length=8)
    aprobado_por: str | None = None
    fecha_aprobacion: datetime | None = None
    dry_run: bool = True


def generar_idempotency_key(
    campana_id: str,
    canal: CanalMarketing | str,
    destino: str,
    payload: str,
) -> str:
    """Genera una llave determinista SHA-256 para prevenir despachos o cobros duplicados."""
    canal_val = canal.value if isinstance(canal, CanalMarketing) else str(canal)
    raw = f"{campana_id}:{canal_val}:{destino}:{payload}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


_MARKETING_MODELS: dict[str, type[BaseModel]] = {
    "idea_input": IdeaInput,
    "campana_marketing": CampanaMarketing,
    "meta_ad_config": MetaAdConfig,
    "linter_result": LinterResult,
}


def export_marketing_json_schemas(directory: str | Path) -> None:
    """Escribe `<nombre>.schema.json` para cada modelo de marketing."""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    for name, model in _MARKETING_MODELS.items():
        text = json.dumps(model.model_json_schema(), indent=2, sort_keys=True, ensure_ascii=False)
        (target / f"{name}.schema.json").write_text(text + "\n", encoding="utf-8")


__all__ = [
    "CampanaMarketing",
    "CanalMarketing",
    "ClasificacionCampana",
    "EstadoCampana",
    "IdeaInput",
    "LinterResult",
    "LinterViolation",
    "MetaAdConfig",
    "Trato",
    "export_marketing_json_schemas",
    "generar_idempotency_key",
]
