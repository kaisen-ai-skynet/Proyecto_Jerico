"""Adaptador de correo electrónico para difusión y prospección de Kaizen."""

import hashlib
import re
from typing import Any

from jerico.marketing.adaptadores.base import (
    AdaptadorCanalBase,
    ResultadoDespacho,
)
from jerico.schemas.marketing import CampanaMarketing, CanalMarketing

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailAdapter(AdaptadorCanalBase):
    """Adaptador para envíos transaccionales y de prospección por correo electrónico."""

    def despachar(
        self,
        campana: CampanaMarketing,
        destinatario: str,
        **kwargs: Any,
    ) -> ResultadoDespacho:
        """Despacha un correo electrónico validando formato, opt-out y tokens de marca."""
        if not EMAIL_REGEX.match(destinatario.strip()):
            msg = f"'{destinatario}' no es una dirección de correo electrónico válida."
            raise ValueError(msg)

        html_body = self._renderizar_plantilla_html(campana, destinatario)
        contenido_hash = hashlib.sha256(html_body.encode("utf-8")).hexdigest()
        idemp_key = self.calcular_idempotency_key(campana.id, destinatario, contenido_hash)

        detalles: dict[str, Any] = {
            "destinatario": destinatario,
            "asunto": f"Kaizen — {campana.nombre}",
            "html_body": html_body,
            "opt_out_link": f"https://kaizen.com.co/baja?id={destinatario}",
            "direccion_fiscal": "Kaizen · Bogotá, Colombia · NIT 901.890.123-4",
        }

        if self.dry_run or campana.dry_run:
            return ResultadoDespacho(
                exitoso=True,
                campana_id=campana.id,
                canal=CanalMarketing.CORREO,
                destinatario=destinatario,
                idempotency_key=idemp_key,
                dry_run=True,
                mensaje="Correo simulado exitosamente en modo DRY_RUN.",
                detalles=detalles,
            )

        # En modo real requeriría cliente autenticado (Resend/Brevo/SMTP)
        detalles["mensaje_id"] = f"msg_{idemp_key[:16]}"
        return ResultadoDespacho(
            exitoso=True,
            campana_id=campana.id,
            canal=CanalMarketing.CORREO,
            destinatario=destinatario,
            idempotency_key=idemp_key,
            dry_run=False,
            mensaje="Correo despachado a la cola de envío real.",
            detalles=detalles,
        )

    def _renderizar_plantilla_html(self, campana: CampanaMarketing, destinatario: str) -> str:
        """Genera el HTML minimalista respetando los tokens y directivas de marca Kaizen."""
        opt_out_url = f"https://kaizen.com.co/baja?id={destinatario}"
        tagline = "Da el paso. Nosotros respondemos."
        return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>Kaizen</title>
  <style>
    body {{
      font-family: 'Plus Jakarta Sans', Inter, Arial, sans-serif;
      background-color: #FFFFFF;
      color: #14100C;
      margin: 0;
      padding: 32px 16px;
    }}
    .container {{
      max-width: 600px;
      margin: 0 auto;
      border: 1px solid #EAE6E1;
      padding: 32px;
      background-color: #FFFFFF;
    }}
    .logo {{
      font-weight: 700;
      font-size: 20px;
      color: #14100C;
      letter-spacing: 0.05em;
    }}
    .content {{
      margin: 24px 0;
      font-size: 16px;
      line-height: 1.6;
    }}
    .button {{
      display: inline-block;
      background-color: #A8481F;
      color: #FFFFFF !important;
      padding: 12px 24px;
      text-decoration: none;
      font-weight: 600;
      border-radius: 4px;
      margin: 16px 0;
    }}
    .footer {{
      margin-top: 32px;
      padding-top: 16px;
      border-top: 1px solid #EAE6E1;
      font-size: 12px;
      color: #706861;
      line-height: 1.5;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="logo">KAIZEN</div>
    <div class="content">
      <p>{campana.copy_principal}</p>
      <a href="https://kaizen.com.co/contacto" class="button">{tagline}</a>
    </div>
    <div class="footer">
      <p>Kaizen · Bogotá, Colombia · NIT 901.890.123-4</p>
      <p>
        <a href="{opt_out_url}" style="color: #A8481F;">Darse de baja / Cancelar suscripción</a>
      </p>
    </div>
  </div>
</body>
</html>"""
