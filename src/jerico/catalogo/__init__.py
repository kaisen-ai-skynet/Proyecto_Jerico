"""Módulo de catálogo de precios de Jericó (Spec 006)."""

from jerico.catalogo.cotizar import (
    PlanNoEncontradoError,
    calcular_mensualidad,
    calcular_total_anual,
    cotizar_plan,
)
from jerico.catalogo.modelo import (
    CatalogoPrecios,
    FuenteCatalogo,
    InternoCatalogo,
    PlanInterno,
    PlanPrecio,
    ReglaMensualidad,
)
from jerico.catalogo.repositorio import (
    CatalogoError,
    CatalogoInmutableError,
    CatalogoSinVersionVigenteError,
    RepositorioCatalogo,
    VersionCatalogoNoEncontradaError,
)
from jerico.catalogo.vista import (
    PlanComercial,
    PlanCTO,
    VistaComercial,
    VistaCTO,
    obtener_vista,
)

__all__ = [
    "CatalogoError",
    "CatalogoInmutableError",
    "CatalogoPrecios",
    "CatalogoSinVersionVigenteError",
    "FuenteCatalogo",
    "InternoCatalogo",
    "PlanComercial",
    "PlanCTO",
    "PlanInterno",
    "PlanNoEncontradoError",
    "PlanPrecio",
    "ReglaMensualidad",
    "RepositorioCatalogo",
    "VersionCatalogoNoEncontradaError",
    "VistaComercial",
    "VistaCTO",
    "calcular_mensualidad",
    "calcular_total_anual",
    "cotizar_plan",
    "obtener_vista",
]
