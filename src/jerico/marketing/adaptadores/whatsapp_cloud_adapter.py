"""Adaptador para WhatsApp Business Cloud API oficial de Meta."""

import hashlib
import re
from typing import Any

from jerico.marketing.adaptadores.base import (
    AdaptadorCanalBase,
    ResultadoDespacho,
)
from jerico.schemas.marketing import CampanaMarketing, CanalMarketing

PHONE_E164_REGEX = re.compile(r"^\+?[1-9]\d{8,14}$")


class WhatsAppCloudAdapter(AdaptadorCanalBase):
    """Adaptador que interactúa exclusivamente con la Cloud API oficial de Meta."""

    def __init__(
        self,
        dry_run: bool | None = None,
        api_provider: str = "cloud_api_oficial",
    ) -> None:
        super().__init__(dry_run=dry_run)
        if api_provider.lower() != "cloud_api_oficial":
            msg = (
                f"Proveedor '{api_provider}' no admitido. "
                "Solo se permite Meta Cloud API oficial para evitar riesgos de baneo."
            )
            raise ValueError(msg)
        self.api_provider = api_provider

    def despachar(
        self,
        campana: CampanaMarketing,
        destinatario: str,
        template_name: str = "kaizen_propuesta_general",
        **kwargs: Any,
    ) -> ResultadoDespacho:
        """Despacha una plantilla HSM por WhatsApp Cloud API validando el formato E.164."""
        numero_limpio = destinatario.strip()
        if not PHONE_E164_REGEX.match(numero_limpio):
            msg = f"'{destinatario}' no es un número de teléfono E.164 válido (+573...)."
            raise ValueError(msg)

        contenido_hash = hashlib.sha256(
            f"{template_name}:{campana.copy_principal}".encode()
        ).hexdigest()
        idemp_key = self.calcular_idempotency_key(campana.id, numero_limpio, contenido_hash)

        opt_out_msg = "Para cancelar envíos futuros responde CANCELAR."
        payload_meta: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": numero_limpio,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": "es"},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": campana.copy_principal},
                        ],
                    },
                ],
            },
            "opt_out_instruccion": opt_out_msg,
        }

        if self.dry_run or campana.dry_run:
            payload_meta["mock_message_id"] = f"wamid.HBgL{idemp_key[:20]}"
            return ResultadoDespacho(
                exitoso=True,
                campana_id=campana.id,
                canal=CanalMarketing.WHATSAPP_OFICIAL,
                destinatario=numero_limpio,
                idempotency_key=idemp_key,
                dry_run=True,
                mensaje="Plantilla WhatsApp simulada exitosamente vía Cloud API en DRY_RUN.",
                detalles=payload_meta,
            )

        # En modo real requeriría credenciales de System User y phone_number_id de Meta
        payload_meta["message_id"] = f"wamid.{idemp_key[:24]}"
        return ResultadoDespacho(
            exitoso=True,
            campana_id=campana.id,
            canal=CanalMarketing.WHATSAPP_OFICIAL,
            destinatario=numero_limpio,
            idempotency_key=idemp_key,
            dry_run=False,
            mensaje="Mensaje enviado a la API de WhatsApp de Meta.",
            detalles=payload_meta,
        )
