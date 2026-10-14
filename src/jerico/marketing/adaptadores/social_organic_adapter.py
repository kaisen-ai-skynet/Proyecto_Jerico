"""Adaptador orgánico para redes sociales (Instagram / Facebook) y guiones 9:16."""

import hashlib
from typing import Any

from jerico.marketing.adaptadores.base import (
    AdaptadorCanalBase,
    ResultadoDespacho,
)
from jerico.schemas.marketing import CampanaMarketing


class SocialOrganicAdapter(AdaptadorCanalBase):
    """Adaptador para publicaciones orgánicas y estructuración de guiones audiovisuales."""

    HASHTAGS_OFICIALES = [
        "#Kaizen",
        "#Operaciones",
        "#EficienciaOperativa",
        "#EmpresasColombia",
        "#SoftwareSeguro",
    ]

    def despachar(
        self,
        campana: CampanaMarketing,
        destinatario: str = "@kaizen_oficial",
        **kwargs: Any,
    ) -> ResultadoDespacho:
        """Formatea y prepara la publicación orgánica para redes sociales en DRY_RUN."""
        post_text = self._formatear_post(campana)
        contenido_hash = hashlib.sha256(post_text.encode("utf-8")).hexdigest()
        idemp_key = self.calcular_idempotency_key(campana.id, destinatario, contenido_hash)

        detalles: dict[str, Any] = {
            "canal": campana.canal.value,
            "destinatario": destinatario,
            "post_text": post_text,
            "multimedia_asset": campana.activo_multimedia_uri or "assets/post_cuadrado_kaizen.png",
            "hashtags": self.HASHTAGS_OFICIALES,
        }

        if campana.activo_multimedia_uri and "video" in campana.activo_multimedia_uri.lower():
            detalles["guion_tecnico_9x16"] = self.generar_guion_tecnico_9x16(campana)

        return ResultadoDespacho(
            exitoso=True,
            campana_id=campana.id,
            canal=campana.canal,
            destinatario=destinatario,
            idempotency_key=idemp_key,
            dry_run=self.dry_run or campana.dry_run,
            mensaje="Publicación orgánica estructurada y simulada en DRY_RUN.",
            detalles=detalles,
        )

    def _formatear_post(self, campana: CampanaMarketing) -> str:
        """Genera el texto de publicación con hashtags y llamado a la acción."""
        tags = " ".join(self.HASHTAGS_OFICIALES)
        cta = "Enlace en biografía para agendar su diagnóstico operativo."
        return f"{campana.copy_principal}\n\n{cta}\n\n{tags}"

    def generar_guion_tecnico_9x16(self, campana: CampanaMarketing) -> dict[str, Any]:
        """Estructura un guion técnico audiovisual 9:16 (duración 25-45s) según Spec 008 R11."""
        return {
            "formato": "9:16 vertical (Reels / TikTok / Shorts)",
            "duracion_estimada_segundos": "35s",
            "hook": {
                "tiempo": "0–5s",
                "descripcion_visual": "Plano medio, vocero mirando a cámara o alerta en pantalla.",
                "texto": f"Atención: {campana.nombre}.",
            },
            "desarrollo": {
                "tiempo": "5–25s",
                "descripcion_visual": "Cortes dinámicos mostrando el flujo operativo.",
                "texto": campana.copy_principal,
            },
            "llamado_al_metodo": {
                "tiempo": "25–35s",
                "descripcion_visual": "Primer plano del vocero con texto de contacto.",
                "texto": "Primero diagnosticamos. Luego construimos.",
            },
            "outro": {
                "asset": "outro_9x16.png",
                "tagline": "Da el paso. Nosotros respondemos.",
                "web": "kaizen.com.co",
            },
        }
