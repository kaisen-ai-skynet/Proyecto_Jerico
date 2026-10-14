"""Herramientas de bot para gestión y gobernanza de marketing (Spec 008, M6).

Expone comandos para @Jericoo_bot y herramientas de agente con verificación
estricta de rol para el CTO:
- /proponer_campana
- /aprobar <id> [monto]
- /rechazar <id> <motivo>
- /listar_campanas
- /despachar <id> [destinatario]
"""

import re
import time
from decimal import Decimal
from typing import Any

from jerico.marketing.orquestador import OrquestadorMarketing
from jerico.schemas.marketing import (
    CanalMarketing,
    EstadoCampana,
    IdeaInput,
    Trato,
)
from jerico.tools.base import BaseTool

_GLOBAL_ORQUESTADOR: OrquestadorMarketing | None = None


def obtener_orquestador_global() -> OrquestadorMarketing:
    """Devuelve o inicializa la instancia singleton en memoria del orquestador."""
    global _GLOBAL_ORQUESTADOR
    if _GLOBAL_ORQUESTADOR is None:
        _GLOBAL_ORQUESTADOR = OrquestadorMarketing()
    return _GLOBAL_ORQUESTADOR


# ---------------------------------------------------------------------------
# 1. Herramientas BaseTool para el registro de agentes
# ---------------------------------------------------------------------------


class MarketingProponerCampanaTool(BaseTool):
    """Herramienta read-only para generar y estructurar una propuesta de campaña."""

    name: str = "marketing_proponer_campana"
    description: str = (
        "Estructura una propuesta de campaña a partir de una idea y genera "
        "vista previa para el bot de Telegram. Read-only."
    )
    readonly: bool = True

    def _execute(  # type: ignore[override]
        self,
        texto_idea: str,
        canal: str = "correo",
        trato: str = "usted",
        nombre: str = "",
    ) -> dict[str, Any]:
        orq = obtener_orquestador_global()
        return comando_proponer_campana(
            orquestador=orq,
            usuario_rol="agente",
            texto_idea=texto_idea,
            canal=canal,
            trato=trato,
            nombre=nombre,
        )


class MarketingAprobarCampanaTool(BaseTool):
    """Herramienta de escritura para aprobar formalmente una campaña."""

    name: str = "marketing_aprobar_campana"
    description: str = (
        "Aprueba formalmente una campaña y autoriza su presupuesto. "
        "ESCRITURA: exige rol 'cto' y confirm=True."
    )
    readonly: bool = False

    def _execute(  # type: ignore[override]
        self,
        campana_id: str,
        gasto_usd: str = "0.00",
        usuario_rol: str = "cto",
    ) -> dict[str, Any]:
        orq = obtener_orquestador_global()
        return comando_aprobar_campana(
            orquestador=orq,
            usuario_rol=usuario_rol,
            campana_id=campana_id,
            gasto_usd=Decimal(gasto_usd),
        )


class MarketingRechazarCampanaTool(BaseTool):
    """Herramienta de escritura para rechazar una campaña."""

    name: str = "marketing_rechazar_campana"
    description: str = (
        "Rechaza una campaña y detiene su emisión. ESCRITURA: exige rol 'cto' y confirm=True."
    )
    readonly: bool = False

    def _execute(  # type: ignore[override]
        self,
        campana_id: str,
        motivo: str = "Rechazada por el CTO",
        usuario_rol: str = "cto",
    ) -> dict[str, Any]:
        orq = obtener_orquestador_global()
        return comando_rechazar_campana(
            orquestador=orq,
            usuario_rol=usuario_rol,
            campana_id=campana_id,
            motivo=motivo,
        )


class MarketingListarPendientesTool(BaseTool):
    """Herramienta read-only para listar campañas pendientes de aprobación."""

    name: str = "marketing_listar_pendientes"
    description: str = "Lista campañas en estado EN_REVISION pendientes de visto bueno. Read-only."
    readonly: bool = True

    def _execute(  # type: ignore[override]
        self,
        usuario_rol: str = "cto",
    ) -> dict[str, Any]:
        orq = obtener_orquestador_global()
        return comando_listar_campanas_pendientes(orquestador=orq, usuario_rol=usuario_rol)


class MarketingDespacharCampanaTool(BaseTool):
    """Herramienta de escritura para ejecutar el despacho de una campaña aprobada."""

    name: str = "marketing_despachar_campana"
    description: str = (
        "Despacha una campaña aprobada (DRY_RUN por defecto). "
        "ESCRITURA: exige confirm=True y aprobación previa."
    )
    readonly: bool = False

    def _execute(  # type: ignore[override]
        self,
        campana_id: str,
        destinatario: str = "",
        usuario_rol: str = "cto",
    ) -> dict[str, Any]:
        orq = obtener_orquestador_global()
        return comando_despachar_campana(
            orquestador=orq,
            usuario_rol=usuario_rol,
            campana_id=campana_id,
            destinatario=destinatario or None,
        )


MARKETING_TOOLS: list[BaseTool] = [
    MarketingProponerCampanaTool(),
    MarketingAprobarCampanaTool(),
    MarketingRechazarCampanaTool(),
    MarketingListarPendientesTool(),
    MarketingDespacharCampanaTool(),
]


# ---------------------------------------------------------------------------
# 2. Funciones funcionales de comandos para el bot
# ---------------------------------------------------------------------------


def comando_proponer_campana(
    orquestador: OrquestadorMarketing,
    usuario_rol: str,
    texto_idea: str,
    canal: str = "correo",
    trato: str = "usted",
    nombre: str = "",
) -> dict[str, Any]:
    """Genera una propuesta de campaña, valida linter y genera preview Telegram."""
    del usuario_rol
    try:
        canal_enum = CanalMarketing(canal.lower())
    except ValueError:
        canal_enum = CanalMarketing.CORREO

    try:
        trato_enum = Trato(trato.lower())
    except ValueError:
        trato_enum = Trato.USTED

    nombre_campana = nombre.strip() or f"Propuesta {time.strftime('%Y%m%d_%H%M')}"
    idea = IdeaInput(
        id=f"IDEA-{int(time.time())}",
        texto=texto_idea.strip(),
        autor="telegram_user",
        origen="telegram",
    )

    try:
        campana = orquestador.proponer_campana(
            idea=idea,
            canal=canal_enum,
            trato=trato_enum,
            nombre=nombre_campana,
        )
        vista_previa = orquestador.formatear_vista_previa_telegram(campana.id)
        return {
            "ok": True,
            "campana_id": campana.id,
            "nombre": campana.nombre,
            "clasificacion": campana.clasificacion_campana.value,
            "estado": campana.estado.value,
            "vista_previa": vista_previa,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def comando_aprobar_campana(
    orquestador: OrquestadorMarketing,
    usuario_rol: str,
    campana_id: str,
    gasto_usd: Decimal = Decimal("0.00"),
) -> dict[str, Any]:
    """Aprueba una campaña autorizando presupuesto. Exclusivo para rol 'cto' (R17)."""
    try:
        campana = orquestador.aprobar_campana(
            campana_id=campana_id.strip(),
            usuario_rol=usuario_rol.strip(),
            gasto_autorizado_usd=gasto_usd,
        )
        return {
            "ok": True,
            "campana_id": campana.id,
            "estado": campana.estado.value,
            "gasto_autorizado_usd": str(campana.gasto_autorizado_usd),
            "aprobado_por": campana.aprobado_por,
            "mensaje": (
                f"✅ Campaña '{campana.id}' aprobada formalmente. "
                f"Presupuesto autorizado: {campana.gasto_autorizado_usd} USD."
            ),
        }
    except PermissionError as exc:
        return {"ok": False, "error": str(exc), "codigo": "PERMISO_DENEGADO"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def comando_rechazar_campana(
    orquestador: OrquestadorMarketing,
    usuario_rol: str,
    campana_id: str,
    motivo: str = "Rechazada por el CTO",
) -> dict[str, Any]:
    """Rechaza una campaña deteniendo su despacho. Exclusivo para rol 'cto'."""
    try:
        campana = orquestador.rechazar_campana(
            campana_id=campana_id.strip(),
            usuario_rol=usuario_rol.strip(),
            motivo=motivo.strip(),
        )
        return {
            "ok": True,
            "campana_id": campana.id,
            "estado": campana.estado.value,
            "motivo": motivo,
            "mensaje": f"🛑 Campaña '{campana.id}' rechazada. Motivo: {motivo}.",
        }
    except PermissionError as exc:
        return {"ok": False, "error": str(exc), "codigo": "PERMISO_DENEGADO"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def comando_listar_campanas_pendientes(
    orquestador: OrquestadorMarketing,
    usuario_rol: str,
) -> dict[str, Any]:
    """Lista las campañas en estado EN_REVISION pendientes de aprobación."""
    del usuario_rol
    pendientes = [
        {
            "id": c.id,
            "nombre": c.nombre,
            "canal": c.canal.value,
            "clasificacion": c.clasificacion_campana.value,
            "presupuesto_estimado_usd": str(c.presupuesto_estimado_usd),
        }
        for c in orquestador._campanas.values()
        if c.estado == EstadoCampana.EN_REVISION
    ]
    return {
        "ok": True,
        "total": len(pendientes),
        "pendientes": pendientes,
    }


def comando_despachar_campana(
    orquestador: OrquestadorMarketing,
    usuario_rol: str,
    campana_id: str,
    destinatario: str | None = None,
) -> dict[str, Any]:
    """Ejecuta el despacho de la campaña a través de sus adaptadores en DRY_RUN."""
    del usuario_rol
    try:
        res = orquestador.despachar_campana(
            campana_id=campana_id.strip(),
            destinatario=destinatario.strip() if destinatario else None,
        )
        return {"ok": True, "resultado": res}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# 3. Router de texto para mensajes de Telegram
# ---------------------------------------------------------------------------

_CMD_REGEX = re.compile(r"^/([a-zA-Z0-9_]+)(?:@\w+)?(?:\s+(.*))?$", re.DOTALL)


def despachar_comando_telegram(
    texto_comando: str,
    usuario_rol: str = "cto",
    orquestador: OrquestadorMarketing | None = None,
) -> str:
    """Interpreta un comando de texto tipo Telegram y retorna una respuesta formateada."""
    orq = orquestador or obtener_orquestador_global()
    match = _CMD_REGEX.match(texto_comando.strip())
    if not match:
        return (
            "⚠️ Formato de comando inválido. Use /proponer_campana, /aprobar, /rechazar o /listar."
        )

    cmd = match.group(1).lower()
    args_str = (match.group(2) or "").strip()

    if cmd == "proponer_campana":
        if not args_str:
            return "⚠️ Uso: `/proponer_campana <descripción de la idea>`"
        res = comando_proponer_campana(
            orquestador=orq,
            usuario_rol=usuario_rol,
            texto_idea=args_str,
        )
        if res.get("ok"):
            return str(res.get("vista_previa", "Campaña propuesta exitosamente."))
        return f"❌ Error al proponer campaña: {res.get('error')}"

    if cmd == "aprobar":
        partes = args_str.split()
        if not partes:
            return "⚠️ Uso: `/aprobar <id_campaña> [monto_usd]`"
        campana_id = partes[0]
        monto = Decimal(partes[1]) if len(partes) > 1 else Decimal("0.00")
        res = comando_aprobar_campana(
            orquestador=orq,
            usuario_rol=usuario_rol,
            campana_id=campana_id,
            gasto_usd=monto,
        )
        if res.get("ok"):
            return str(res.get("mensaje"))
        return f"❌ Error al aprobar: {res.get('error')}"

    if cmd == "rechazar":
        partes = args_str.split(maxsplit=1)
        if not partes:
            return "⚠️ Uso: `/rechazar <id_campaña> [motivo]`"
        campana_id = partes[0]
        motivo = partes[1] if len(partes) > 1 else "Rechazada por el CTO"
        res = comando_rechazar_campana(
            orquestador=orq,
            usuario_rol=usuario_rol,
            campana_id=campana_id,
            motivo=motivo,
        )
        if res.get("ok"):
            return str(res.get("mensaje"))
        return f"❌ Error al rechazar: {res.get('error')}"

    if cmd in ("listar_campanas", "listar_pendientes"):
        res = comando_listar_campanas_pendientes(orquestador=orq, usuario_rol=usuario_rol)
        total = res.get("total", 0)
        if total == 0:
            return "ℹ️ No hay campañas pendientes de aprobación."
        items = [
            f"• `{p['id']}` | {p['nombre']} | Canal: {p['canal']} | "
            f"Presupuesto: {p['presupuesto_estimado_usd']} USD"
            for p in res.get("pendientes", [])
        ]
        return f"📋 *Campañas Pendientes de Aprobación ({total}):*\n\n" + "\n".join(items)

    if cmd == "despachar":
        partes = args_str.split(maxsplit=1)
        if not partes:
            return "⚠️ Uso: `/despachar <id_campaña> [destinatario]`"
        campana_id = partes[0]
        destinatario = partes[1] if len(partes) > 1 else None
        res = comando_despachar_campana(
            orquestador=orq,
            usuario_rol=usuario_rol,
            campana_id=campana_id,
            destinatario=destinatario,
        )
        if res.get("ok"):
            resultado = res.get("resultado", {})
            return (
                f"🚀 *Despacho ejecutado:*\n"
                f"• ID: `{resultado.get('campana_id')}`\n"
                f"• Estado: `{resultado.get('status')}`\n"
                f"• Canal: `{resultado.get('canal')}`\n"
                f"• Destinatario: `{resultado.get('destinatario')}`\n"
                f"• Idempotency: `{resultado.get('idempotency_key', '')[:16]}...`"
            )
        return f"❌ Error al despachar: {res.get('error')}"

    return (
        f"⚠️ Comando de marketing no reconocido: '/{cmd}'. "
        "Disponibles: /proponer_campana, /aprobar, /rechazar, /listar_campanas, /despachar."
    )
