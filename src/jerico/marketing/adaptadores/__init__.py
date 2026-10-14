"""Adaptadores para difusión y marketing multicanal de Kaizen."""

from jerico.marketing.adaptadores.base import (
    AdaptadorCanalBase,
    ResultadoDespacho,
)
from jerico.marketing.adaptadores.email_adapter import EmailAdapter
from jerico.marketing.adaptadores.meta_ads_adapter import MetaAdsAdapter
from jerico.marketing.adaptadores.social_organic_adapter import SocialOrganicAdapter
from jerico.marketing.adaptadores.whatsapp_cloud_adapter import WhatsAppCloudAdapter

__all__ = [
    "AdaptadorCanalBase",
    "EmailAdapter",
    "MetaAdsAdapter",
    "ResultadoDespacho",
    "SocialOrganicAdapter",
    "WhatsAppCloudAdapter",
]
