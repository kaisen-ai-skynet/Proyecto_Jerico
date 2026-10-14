"""Vistas por rol para el catálogo de precios (Spec 006, C4).

Garantiza aislamiento estricto por privilegios (R7, R8, R9, R12):
- Comercial: solo planes, precios propuestos, mensualidad y advertencias comerciales.
  Excluye tajantemente costos directos, márgenes, precios de fórmula, honorarios y caja.
- CTO: visión financiera integral con costos directos, márgenes y capacidades.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jerico.catalogo.cotizar import calcular_mensualidad
from jerico.catalogo.modelo import (
    CatalogoPrecios,
    InternoCatalogo,
    PlanInterno,
    ReglaMensualidad,
)

# Palabras clave que revelan estructura de costos internos o rentabilidad confidencial
_PATRONES_SENSIBLES_COMERCIAL = (
    r"costo\s+directo",
    r"costo_directo",
    r"margen",
    r"honorario",
    r"caja",
    r"cap\s*table",
    r"capacidad",
)


class PlanComercial(BaseModel):
    """Representación de un plan para comerciales y clientes externos."""

    model_config = ConfigDict(extra="forbid")

    id: str
    nombre: str
    precio_propuesta: int
    mensualidad: int


class VistaComercial(BaseModel):
    """Vista pública/comercial del catálogo. Sin datos de costos ni márgenes (R7)."""

    model_config = ConfigDict(extra="forbid")

    rol: Literal["comercial"] = "comercial"
    version: str
    estado: str
    moneda: str
    iva: str
    vigencia_desde: str | None = None
    regla_mensualidad: ReglaMensualidad
    planes: list[PlanComercial] = Field(min_length=1)
    advertencias: list[str] = Field(default_factory=list)
    aviso: str | None = None


class PlanCTO(BaseModel):
    """Representación de un plan para el CTO con desglose financiero completo (R8)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    nombre: str
    precio_propuesta: int
    precio_formula: int
    margen_objetivo_pct: float
    mensualidad: int
    interno: PlanInterno | None = None


class VistaCTO(BaseModel):
    """Vista confidencial del catálogo para la dirección técnica y financiera (R8)."""

    model_config = ConfigDict(extra="forbid")

    rol: Literal["cto"] = "cto"
    version: str
    estado: str
    moneda: str
    iva: str
    vigencia_desde: str | None = None
    regla_mensualidad: ReglaMensualidad
    planes: list[PlanCTO] = Field(min_length=1)
    interno: InternoCatalogo | None = None
    advertencias: list[str] = Field(default_factory=list)
    aviso: str | None = None


def _es_advertencia_comercial(texto: str) -> bool:
    t_lower = texto.lower()
    for patron in _PATRONES_SENSIBLES_COMERCIAL:
        if re.search(patron, t_lower):
            return False
    return True


def obtener_vista(
    catalogo: CatalogoPrecios,
    rol: str,
) -> VistaComercial | VistaCTO:
    """Genera la proyección del catálogo adecuada al rol del usuario solicitante (R7, R8).

    Aplica el principio de menor privilegio: ante cualquier rol que no sea 'cto',
    devuelve la VistaComercial filtrada.
    """
    aviso_borrador = "BORRADOR — no cotizar" if catalogo.estado != "vigente" else None
    rol_normalizado = rol.strip().lower()

    if rol_normalizado == "cto":
        planes_cto = [
            PlanCTO(
                id=p.id,
                nombre=p.nombre,
                precio_propuesta=p.precio_propuesta,
                precio_formula=p.precio_formula,
                margen_objetivo_pct=p.margen_objetivo_pct,
                mensualidad=int(calcular_mensualidad(catalogo, p.id)),
                interno=p.interno,
            )
            for p in catalogo.planes
        ]
        return VistaCTO(
            version=catalogo.version,
            estado=catalogo.estado,
            moneda=catalogo.moneda,
            iva=catalogo.iva,
            vigencia_desde=catalogo.vigencia_desde,
            regla_mensualidad=catalogo.regla_mensualidad,
            planes=planes_cto,
            interno=catalogo.interno,
            advertencias=list(catalogo.advertencias),
            aviso=aviso_borrador,
        )

    # Vista comercial recortada (R7)
    planes_comerciales = [
        PlanComercial(
            id=p.id,
            nombre=p.nombre,
            precio_propuesta=p.precio_propuesta,
            mensualidad=int(calcular_mensualidad(catalogo, p.id)),
        )
        for p in catalogo.planes
    ]
    advertencias_filtradas = [
        adv for adv in catalogo.advertencias if _es_advertencia_comercial(adv)
    ]

    return VistaComercial(
        version=catalogo.version,
        estado=catalogo.estado,
        moneda=catalogo.moneda,
        iva=catalogo.iva,
        vigencia_desde=catalogo.vigencia_desde,
        regla_mensualidad=catalogo.regla_mensualidad,
        planes=planes_comerciales,
        advertencias=advertencias_filtradas,
        aviso=aviso_borrador,
    )
