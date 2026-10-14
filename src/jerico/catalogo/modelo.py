"""Modelo Pydantic para el catálogo versionado de precios (Spec 006, C1)."""

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SEMVER_REGEX = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

# R9: Lista de nombres y apellidos de personas con honorarios individuales o miembros del equipo
# que no deben figurar bajo ninguna circunstancia en el catálogo de precios comercial.
_NOMBRES_PROHIBIDOS = (
    "santiago gonzález",
    "santiago jaimes",
    "nicolás david",
    "esteban",
    "lucas",
    "juan pablo",
    "daniel byron",
    "santiago segura",
    "duván",
    "juan josé",
)


def _contiene_nombre_prohibido(texto: str) -> str | None:
    t_lower = texto.lower()
    for nombre in _NOMBRES_PROHIBIDOS:
        patron = rf"\b{re.escape(nombre)}\b"
        if re.search(patron, t_lower):
            return nombre
    return None


class FuenteCatalogo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archivo: str = Field(min_length=1)
    sha256: str = Field(min_length=64, max_length=64)
    extraido: str = Field(min_length=1)
    estado_modelo: str | None = None


class ReglaMensualidad(BaseModel):
    model_config = ConfigDict(extra="forbid")

    porcentaje_de_implementacion_por_mes: float = Field(gt=0, le=100)


class PlanInterno(BaseModel):
    model_config = ConfigDict(extra="forbid")

    margen_real_pct: float | None = None


class PlanPrecio(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=50)
    nombre: str = Field(min_length=1, max_length=100)
    precio_propuesta: int = Field(ge=0)
    precio_formula: int = Field(ge=0)
    margen_objetivo_pct: float = Field(ge=0, le=100)
    interno: PlanInterno | None = None


class InternoCatalogo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    costo_directo_por_implementacion: int | None = Field(default=None, ge=0)
    capacidad_implementaciones_anio: int | None = Field(default=None, ge=0)


class CatalogoPrecios(BaseModel):
    """Catálogo inmutable de precios de Kaizen estructurado según el modelo financiero."""

    model_config = ConfigDict(extra="forbid")

    version: str
    estado: Literal["borrador", "vigente", "retirada"]
    moneda: Literal["COP"]
    iva: Literal["excluido"] = "excluido"
    vigencia_desde: str | None = None
    fuente: FuenteCatalogo
    regla_mensualidad: ReglaMensualidad
    planes: list[PlanPrecio] = Field(min_length=1)
    interno: InternoCatalogo | None = None
    advertencias: list[str] = Field(default_factory=list)

    @field_validator("version")
    @classmethod
    def _validar_semver(cls, v: str) -> str:
        if not _SEMVER_REGEX.match(v):
            raise ValueError(f"la versión '{v}' no cumple el formato semver (MAJOR.MINOR.PATCH)")
        return v

    @model_validator(mode="after")
    def _validar_invariantes(self) -> "CatalogoPrecios":
        # 1. Unicidad de los planes
        vistos: set[str] = set()
        for plan in self.planes:
            if plan.id in vistos:
                raise ValueError(f"id de plan duplicado: '{plan.id}'")
            vistos.add(plan.id)

        # 2. Regla R9: prohíbe nombres de personas en advertencias y textos
        def _inspeccionar_texto(valor: Any, ruta: str) -> None:
            if isinstance(valor, str):
                nombre_encontrado = _contiene_nombre_prohibido(valor)
                if nombre_encontrado:
                    msg = (
                        f"violación de privacidad R9: el campo '{ruta}' "
                        f"contiene el nombre prohibido '{nombre_encontrado}'"
                    )
                    raise ValueError(msg)
            elif isinstance(valor, list):
                for idx, item in enumerate(valor):
                    _inspeccionar_texto(item, f"{ruta}[{idx}]")
            elif isinstance(valor, dict):
                for k, item in valor.items():
                    _inspeccionar_texto(item, f"{ruta}.{k}")

        _inspeccionar_texto(self.advertencias, "advertencias")
        for idx, plan in enumerate(self.planes):
            _inspeccionar_texto(plan.nombre, f"planes[{idx}].nombre")
            _inspeccionar_texto(plan.id, f"planes[{idx}].id")

        return self
