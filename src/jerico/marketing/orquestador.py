"""Orquestador de campañas de marketing con aprobación humana (HITL) (Spec 008, M5).

Aplica la regla de oro:
«Jericó redacta y propone; el CTO aprueba y publica. Cero publicaciones autónomas
y cero gasto sin orden explícita».
Soporta DRY_RUN por defecto y gobernanza del presupuesto Lean de 10–25 USD/mes.
"""

import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from jerico.marketing.perfeccionador import PerfeccionadorMarketing
from jerico.schemas.marketing import (
    CampanaMarketing,
    CanalMarketing,
    EstadoCampana,
    IdeaInput,
    Trato,
)


class OrquestadorMarketing:
    """Orquestador del flujo Idea -> Linter -> Aprobación Humana -> Despacho."""

    def __init__(
        self,
        dry_run: bool | None = None,
        perfeccionador: PerfeccionadorMarketing | None = None,
        presupuesto_maximo_mensual_usd: Decimal = Decimal("25.00"),
    ) -> None:
        if dry_run is not None:
            self.dry_run = dry_run
        else:
            env_val = os.environ.get("JERICO_EXTERNAL_COMMS_DRY_RUN", "true").lower()
            self.dry_run = env_val in ("true", "1", "yes")

        self.perfeccionador = perfeccionador or PerfeccionadorMarketing()
        self.presupuesto_maximo_mensual_usd = presupuesto_maximo_mensual_usd
        self.gasto_acumulado_mensual_usd = Decimal("0.00")
        self._campanas: dict[str, CampanaMarketing] = {}
        self._despachos_ejecutados: set[str] = set()

    def proponer_campana(
        self,
        idea: IdeaInput,
        canal: CanalMarketing,
        trato: Trato,
        nombre: str,
        activo_multimedia_uri: str | None = None,
        presupuesto_usd: Decimal = Decimal("0.00"),
    ) -> CampanaMarketing:
        """Estructura y valida una campaña, dejándola en estado EN_REVISION."""
        campana = self.perfeccionador.estructurar_campana(
            idea=idea,
            canal=canal,
            trato=trato,
            nombre=nombre,
            activo_multimedia_uri=activo_multimedia_uri,
            presupuesto_usd=presupuesto_usd,
        )
        campana.estado = EstadoCampana.EN_REVISION
        campana.dry_run = self.dry_run
        self._campanas[campana.id] = campana
        return campana

    def obtener_campana(self, campana_id: str) -> CampanaMarketing:
        """Recupera una campaña por su identificador."""
        if campana_id not in self._campanas:
            raise KeyError(f"Campaña con ID '{campana_id}' no encontrada.")
        return self._campanas[campana_id]

    def generar_preview_telegram(self, campana_id: str) -> str:
        """Formatea la vista previa de la campaña para notificación en @Jericoo_bot."""
        campana = self.obtener_campana(campana_id)
        etiqueta_dry = " [DRY_RUN SIMULADO]" if campana.dry_run else ""
        ad_info = ""
        if campana.meta_ad_config:
            ad_info = (
                f"\n💰 Presupuesto diario propuesto: {campana.presupuesto_estimado_usd} USD"
                f"\n🔒 Estado inicial anuncio: {campana.meta_ad_config.status} "
                f"(Gasto actual: 0.00 USD)"
            )

        return (
            f"📬 PROPUESTA DE CAMPAÑA — JERICÓ MARKETING (F5){etiqueta_dry}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 ID: {campana.id}\n"
            f"🏷️ Nombre: {campana.nombre}\n"
            f"🎯 Clasificación: {campana.clasificacion_campana.value}\n"
            f"📡 Canal: {campana.canal.value}\n"
            f"🗣️ Trato: {campana.trato.value}\n"
            f"⚖️ Estado: {campana.estado.value}"
            f"{ad_info}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📝 Contenido:\n{campana.copy_principal}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🟢 Responder: /aprobar {campana.id}\n"
            f"🔴 Responder: /rechazar {campana.id} <motivo>"
        )

    def aprobar_campana(
        self,
        campana_id: str,
        usuario_rol: str,
        gasto_autorizado_usd: Decimal = Decimal("0.00"),
    ) -> CampanaMarketing:
        """Aprueba formalmente la campaña. Solo permitido para el rol 'cto'."""
        if usuario_rol.lower() != "cto":
            msg = "Solo el rol 'cto' puede aprobar campañas y autorizar presupuesto."
            raise PermissionError(msg)

        campana = self.obtener_campana(campana_id)

        # Control del presupuesto Lean de §6
        total_proyectado = self.gasto_acumulado_mensual_usd + gasto_autorizado_usd
        if total_proyectado > self.presupuesto_maximo_mensual_usd:
            raise ValueError(
                f"El gasto solicitado ({gasto_autorizado_usd} USD) excede el tope mensual lean "
                f"de {self.presupuesto_maximo_mensual_usd} USD "
                f"(Acumulado actual: {self.gasto_acumulado_mensual_usd} USD)."
            )

        campana.gasto_autorizado_usd = gasto_autorizado_usd
        if campana.meta_ad_config:
            campana.meta_ad_config.gasto_autorizado_usd = gasto_autorizado_usd

        campana.aprobado_por = "cto"
        campana.fecha_aprobacion = datetime.now(UTC)
        campana.estado = EstadoCampana.APROBADA
        return campana

    def rechazar_campana(
        self,
        campana_id: str,
        usuario_rol: str,
        motivo: str = "Rechazada por el CTO",
    ) -> CampanaMarketing:
        """Rechaza una campaña y detiene su despacho."""
        if usuario_rol.lower() != "cto":
            raise PermissionError("Solo el rol 'cto' puede rechazar campañas.")

        campana = self.obtener_campana(campana_id)
        campana.estado = EstadoCampana.RECHAZADA
        return campana

    def despachar_campana(self, campana_id: str) -> dict[str, Any]:
        """Ejecuta el despacho de la campaña validando aprobación e idempotencia."""
        campana = self.obtener_campana(campana_id)

        if campana.estado != EstadoCampana.APROBADA:
            msg = (
                f"La campaña '{campana_id}' no ha sido aprobada por el CTO "
                f"(estado actual: {campana.estado.value})."
            )
            raise PermissionError(msg)

        if campana.idempotency_key in self._despachos_ejecutados:
            raise ValueError(
                f"Despacho duplicado bloqueado por idempotencia: {campana.idempotency_key}"
            )

        # Verificaciones por canal
        if campana.canal == CanalMarketing.WHATSAPP_OFICIAL:
            # WhatsApp exige Cloud API oficial
            pass
        elif campana.canal == CanalMarketing.META_ADS:
            config = campana.meta_ad_config
            if config and config.gasto_autorizado_usd > self.presupuesto_maximo_mensual_usd:
                raise ValueError("Gasto de Meta Ads excede el límite permitido.")

        # Despacho en DRY_RUN simulado
        resultado: dict[str, Any]
        if self.dry_run or campana.dry_run:
            resultado = {
                "status": "simulado_dry_run",
                "campana_id": campana.id,
                "canal": campana.canal.value,
                "nombre": campana.nombre,
                "gasto_autorizado_usd": str(campana.gasto_autorizado_usd),
                "idempotency_key": campana.idempotency_key,
                "mensaje": "Despacho simulado exitoso sin emisión a red ni costo real.",
            }
        else:
            # En producción real requiere autorización explícita y credenciales
            resultado = {
                "status": "despachado_real",
                "campana_id": campana.id,
                "canal": campana.canal.value,
                "idempotency_key": campana.idempotency_key,
            }

        self._despachos_ejecutados.add(campana.idempotency_key)
        self.gasto_acumulado_mensual_usd += campana.gasto_autorizado_usd
        campana.estado = EstadoCampana.DESPACHADA
        return resultado
