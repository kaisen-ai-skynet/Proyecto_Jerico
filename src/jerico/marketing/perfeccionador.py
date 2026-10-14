"""Perfeccionador y generador de campañas de marketing Kaizen (Spec 008, M3).

Convierte ideas sin procesar del CTO en campañas estructuradas por canal,
alineadas con la Guía de Marca Kaizen v1.0 y validadas por el linter.
"""

import uuid
from decimal import Decimal

from jerico.marketing.linter import LinterMarcaKaizen
from jerico.schemas.marketing import (
    CampanaMarketing,
    CanalMarketing,
    ClasificacionCampana,
    EstadoCampana,
    IdeaInput,
    MetaAdConfig,
    Trato,
    generar_idempotency_key,
)

TAGLINE = "Da el paso. Nosotros respondemos."


class PerfeccionadorMarketing:
    """Motor de clasificación y perfeccionamiento de contenido para Kaizen."""

    def __init__(self, linter: LinterMarcaKaizen | None = None) -> None:
        self.linter = linter or LinterMarcaKaizen()

    def clasificar_campana(self, idea: IdeaInput) -> ClasificacionCampana:
        """Determina a cuál de las cinco campañas canónicas pertenece la idea."""
        texto = idea.texto.lower()

        c4_keywords = ["seguridad", "privacidad", "ley 1581", "cifrado", "llave", "respaldo"]
        if any(k in texto for k in c4_keywords):
            return ClasificacionCampana.C4

        c5_keywords = ["equipo", "mérito", "merito", "cultura", "crece quien construye"]
        if any(k in texto for k in c5_keywords):
            return ClasificacionCampana.C5

        c3_keywords = [
            "responsabilidad", "quién responde", "quien responde", "alguien responde", "firma"
        ]
        if any(k in texto for k in c3_keywords):
            return ClasificacionCampana.C3

        c2_keywords = [
            "radar", "vencimiento", "evolución", "evolucion", "versión", "del papel al sistema"
        ]
        if any(k in texto for k in c2_keywords):
            return ClasificacionCampana.C2

        # Por defecto la puerta de entrada: C1 Primero entendemos
        return ClasificacionCampana.C1

    def estructurar_campana(
        self,
        idea: IdeaInput,
        canal: CanalMarketing,
        trato: Trato,
        nombre: str,
        activo_multimedia_uri: str | None = None,
        presupuesto_usd: Decimal = Decimal("0.00"),
    ) -> CampanaMarketing:
        """Genera una propuesta de campaña estructurada y validada por el linter."""
        clasificacion = self.clasificar_campana(idea)
        copy = self._generar_copy_base(
            idea=idea,
            clasificacion=clasificacion,
            canal=canal,
            trato=trato,
        )

        # Validación algorítmica previa mediante el linter
        lint_res = self.linter.validar(copy=copy, canal=canal, trato=trato)
        if not lint_res.valido:
            errores_str = "; ".join(err.mensaje for err in lint_res.errores)
            raise ValueError(f"El copy generado no supera el linter de marca: {errores_str}")

        # Configuración específica para Meta Ads
        meta_cfg = None
        if canal == CanalMarketing.META_ADS:
            meta_cfg = MetaAdConfig(
                presupuesto_diario_usd=presupuesto_usd,
                gasto_autorizado_usd=Decimal("0.00"),
                status="PAUSED",
            )

        campana_id = f"CAMP-{uuid.uuid4().hex[:8].upper()}"
        idempotency_key = generar_idempotency_key(
            campana_id=campana_id,
            canal=canal,
            destino=nombre,
            payload=copy,
        )

        return CampanaMarketing(
            id=campana_id,
            nombre=nombre,
            clasificacion_campana=clasificacion,
            canal=canal,
            trato=trato,
            copy_principal=copy,
            activo_multimedia_uri=activo_multimedia_uri,
            meta_ad_config=meta_cfg,
            presupuesto_estimado_usd=presupuesto_usd,
            gasto_autorizado_usd=Decimal("0.00"),
            estado=EstadoCampana.BORRADOR,
            idempotency_key=idempotency_key,
            dry_run=True,
        )

    def _generar_copy_base(
        self,
        idea: IdeaInput,
        clasificacion: ClasificacionCampana,
        canal: CanalMarketing,
        trato: Trato,
    ) -> str:
        """Sintetiza la idea con la estructura y tono oficial del canal."""
        texto_limpio = idea.texto.strip()

        if trato == Trato.USTED:
            if canal == CanalMarketing.CORREO:
                linea1 = (
                    "En Kaizen sabemos que antes de programar, "
                    "lo primero es entender su operación."
                )
                linea2 = (
                    "No implementamos herramientas por moda; "
                    "construimos sistemas que su equipo realmente adopte."
                )
                return (
                    f"Estimado/a cliente:\n\n"
                    f"{linea1}\n\n"
                    f"{texto_limpio}\n\n"
                    f"{linea2}\n\n"
                    f"{TAGLINE}"
                )
            # LinkedIn u otros formales
            linea_lk = (
                "En Kaizen diseñamos sistemas por etapas "
                "donde un equipo con nombre propio responde."
            )
            return (
                f"El primer paso no es la tecnología: es entender el proceso.\n\n"
                f"{texto_limpio}\n\n"
                f"{linea_lk}\n\n"
                f"Primero entendemos. Después construimos.\n"
                f"{TAGLINE}"
            )
        else:
            # Trato en Tú (WhatsApp, Instagram, Meta Ads)
            if canal == CanalMarketing.WHATSAPP_OFICIAL:
                return (
                    f"Hola, ¿cómo va tu operación?\n\n"
                    f"En Kaizen te ayudamos a dar el paso del papel a un sistema claro:\n"
                    f"{texto_limpio}\n\n"
                    f"Cuéntame cómo llevas tus pedidos y vemos por dónde empezar.\n\n"
                    f"{TAGLINE}"
                )
            if canal == CanalMarketing.META_ADS:
                return (
                    f"¿Tu negocio sigue atrapado en cuadernos y chats?\n\n"
                    f"En Kaizen ordenamos tu operación con el Método Kaizen:\n"
                    f"{texto_limpio}\n\n"
                    f"Menos operación a pulso. Más control real.\n\n"
                    f"{TAGLINE}"
                )
            # Instagram / Redes orgánicas
            return (
                f"¿Sientes que crecer solo significa más desorden manual?\n\n"
                f"{texto_limpio}\n\n"
                f"En Kaizen primero entendemos. Después construimos.\n\n"
                f"{TAGLINE}"
            )
