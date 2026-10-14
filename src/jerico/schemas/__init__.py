"""Esquemas compartidos entre F2 (CRM), F4 (asistente) y F6 (precios): Plan Maestro §4.

Un único contrato Pydantic/JSON Schema para `Lead`, `Cotizacion` y `PaqueteContrato`. Los importes
son enteros en la unidad menor de la moneda; el total lo calcula el código y **nunca** un modelo
de lenguaje (los precios finales salen de la herramienta determinista de F6)."""

import json
import re
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

_CURRENCY = re.compile(r"[A-Z]{3}")


class Lead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    state: str
    name: str | None = None
    company: str | None = None
    client_type: str | None = None
    doc_type: str | None = None
    doc_number: str | None = None
    legal_rep: str | None = None
    phone_e164: str | None = None
    email: str | None = None
    service: str | None = None
    agreed_value: str | None = None
    start_term: str | None = None


class CotizacionLinea(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=300)
    quantity: int = Field(gt=0)
    unit_price: int = Field(ge=0)


class Cotizacion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str
    lines: list[CotizacionLinea] = Field(min_length=1)
    payment_terms: str = Field(min_length=1, max_length=300)
    valid_until: date | None = None
    special_conditions: str | None = Field(default=None, max_length=1000)

    @field_validator("currency")
    @classmethod
    def _iso_currency(cls, value: str) -> str:
        if not _CURRENCY.fullmatch(value):
            raise ValueError("la moneda debe ser un código ISO 4217 de 3 letras mayúsculas")
        return value

    @property
    def total(self) -> int:
        return sum(line.quantity * line.unit_price for line in self.lines)


class PaqueteContrato(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead: Lead
    cotizacion: Cotizacion
    version: int = Field(gt=0)
    legal_basis: str
    generated_at: datetime


_MODELS: dict[str, type[BaseModel]] = {
    "lead": Lead,
    "cotizacion": Cotizacion,
    "paquete_contrato": PaqueteContrato,
}


def export_json_schemas(directory: str | Path) -> None:
    """Escribe `<nombre>.schema.json` para cada modelo (formato estable, claves ordenadas)."""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    for name, model in _MODELS.items():
        text = json.dumps(model.model_json_schema(), indent=2, sort_keys=True, ensure_ascii=False)
        (target / f"{name}.schema.json").write_text(text + "\n", encoding="utf-8")


__all__ = [
    "Cotizacion",
    "CotizacionLinea",
    "Lead",
    "PaqueteContrato",
    "export_json_schemas",
]
