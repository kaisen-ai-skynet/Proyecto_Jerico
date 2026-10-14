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
from jerico.marketing.plantillas import (
    EstadoPlantilla,
    GestorPlantillasMarca,
    PlantillaMarca,
    TipoPlantilla,
    formatear_ficha_lead_marca,
    formatear_mensaje_bot_marca,
    obtener_gestor_plantillas,
    renderizar_plantilla_cotizacion,
)

__all__ = [
    "AdaptadorCanalBase",
    "EmailAdapter",
    "EstadoPlantilla",
    "GestorActivosKaizen",
    "GestorPlantillasMarca",
    "LinterMarcaKaizen",
    "MARKETING_COMMAND_DESCRIPTIONS",
    "MetaAdsAdapter",
    "OrquestadorMarketing",
    "PerfeccionadorMarketing",
    "PlantillaMarca",
    "ResultadoDespacho",
    "SocialOrganicAdapter",
    "TipoPlantilla",
    "WhatsAppCloudAdapter",
    "formatear_ficha_lead_marca",
    "formatear_mensaje_bot_marca",
    "obtener_gestor_plantillas",
    "register_marketing_commands",
    "renderizar_plantilla_cotizacion",
]
