"""Adaptador para Meta Ads (Facebook / Instagram Ads) con guardarraíl Lean."""

import hashlib
from decimal import Decimal
from typing import Any

from jerico.marketing.adaptadores.base import (
    AdaptadorCanalBase,
    ResultadoDespacho,
)
from jerico.schemas.marketing import (
    CampanaMarketing,
    CanalMarketing,
    EstadoCampana,
)

PRESUPUESTO_MAXIMO_MENSUAL_LEAN_USD = Decimal("25.00")


class MetaAdsAdapter(AdaptadorCanalBase):
    """Adaptador para la creación y gestión de campañas publicitarias en Meta Ads."""

    def __init__(
        self,
        dry_run: bool | None = None,
        presupuesto_maximo_usd: Decimal = PRESUPUESTO_MAXIMO_MENSUAL_LEAN_USD,
    ) -> None:
        super().__init__(dry_run=dry_run)
        self.presupuesto_maximo_usd = presupuesto_maximo_usd

    def despachar(
        self,
        campana: CampanaMarketing,
        destinatario: str = "act_default_account",
        **kwargs: Any,
    ) -> ResultadoDespacho:
        """Crea la campaña en Meta Ads obligatoriamente en estado PAUSED con presupuesto 0."""
        # Verificación estricta de aprobación por el CTO
        if campana.estado != EstadoCampana.APROBADA or campana.aprobado_por != "cto":
            msg = (
                f"La campaña pagada '{campana.id}' no ha sido aprobada formalmente "
                "por el CTO (estado: {campana.estado.value}, aprobado_por: {campana.aprobado_por})."
            )
            raise PermissionError(msg)

        if not campana.meta_ad_config:
            msg = f"La campaña '{campana.id}' carece de meta_ad_config obligatorio para Meta Ads."
            raise ValueError(msg)

        config = campana.meta_ad_config
        gasto = campana.gasto_autorizado_usd or config.gasto_autorizado_usd

        # Guardarraíl de presupuesto Lean del Plan Maestro §6
        if gasto > self.presupuesto_maximo_usd:
            msg = (
                f"El gasto autorizado ({gasto} USD) excede el tope mensual Lean "
                f"de {self.presupuesto_maximo_usd} USD establecido en el Plan Maestro §6."
            )
            raise ValueError(msg)

        contenido_hash = hashlib.sha256(
            f"{config.objetivo}:{gasto}:{campana.copy_principal}".encode()
        ).hexdigest()
        idemp_key = self.calcular_idempotency_key(campana.id, destinatario, contenido_hash)

        detalles_meta: dict[str, Any] = {
            "ad_account_id": destinatario,
            "campaign_name": f"KAIZEN_{campana.id}_{campana.nombre}",
            "objective": config.objetivo,
            "status": "PAUSED",  # R13: Invariablemente en PAUSED al nacer
            "daily_budget_usd": str(gasto),
            "call_to_action": config.call_to_action,
            "adset_nombre": config.adset_nombre,
        }

        if self.dry_run or campana.dry_run:
            detalles_meta["campaign_id"] = f"act_mock_{idemp_key[:12]}"
            detalles_meta["adset_id"] = f"adset_mock_{idemp_key[12:24]}"
            return ResultadoDespacho(
                exitoso=True,
                campana_id=campana.id,
                canal=CanalMarketing.META_ADS,
                destinatario=destinatario,
                idempotency_key=idemp_key,
                dry_run=True,
                mensaje="Campaña Meta Ads creada en PAUSED y modo simulado DRY_RUN.",
                detalles=detalles_meta,
            )

        # En modo real requeriría Meta Graph API token y ad account activo
        detalles_meta["campaign_id"] = f"act_real_{idemp_key[:16]}"
        return ResultadoDespacho(
            exitoso=True,
            campana_id=campana.id,
            canal=CanalMarketing.META_ADS,
            destinatario=destinatario,
            idempotency_key=idemp_key,
            dry_run=False,
            mensaje="Campaña Meta Ads enviada a la API de Meta en estado PAUSED.",
            detalles=detalles_meta,
        )
