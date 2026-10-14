"""Subsistema de Marketing y Automatización de Marca (Spec 008, Frente F5)."""

from jerico.marketing.activos import GestorActivosKaizen
from jerico.marketing.adaptadores import (
    AdaptadorCanalBase,
    EmailAdapter,
    MetaAdsAdapter,
    ResultadoDespacho,
    SocialOrganicAdapter,
    WhatsAppCloudAdapter,
)
from jerico.marketing.bot import (
    MARKETING_COMMAND_DESCRIPTIONS,
    register_marketing_commands,
)
from jerico.marketing.linter import LinterMarcaKaizen
from jerico.marketing.orquestador import OrquestadorMarketing
from jerico.marketing.perfeccionador import PerfeccionadorMarketing

__all__ = [
    "AdaptadorCanalBase",
    "EmailAdapter",
    "GestorActivosKaizen",
    "LinterMarcaKaizen",
    "MARKETING_COMMAND_DESCRIPTIONS",
    "MetaAdsAdapter",
    "OrquestadorMarketing",
    "PerfeccionadorMarketing",
    "ResultadoDespacho",
    "SocialOrganicAdapter",
    "WhatsAppCloudAdapter",
    "register_marketing_commands",
]
