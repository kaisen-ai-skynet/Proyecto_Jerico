"""Subsistema de Marketing y Automatización de Marca (Spec 008, Frente F5)."""

from jerico.marketing.activos import GestorActivosKaizen
from jerico.marketing.linter import LinterMarcaKaizen
from jerico.marketing.orquestador import OrquestadorMarketing
from jerico.marketing.perfeccionador import PerfeccionadorMarketing

__all__ = [
    "GestorActivosKaizen",
    "LinterMarcaKaizen",
    "OrquestadorMarketing",
    "PerfeccionadorMarketing",
]
