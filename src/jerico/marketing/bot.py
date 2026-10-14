"""Comandos de Telegram para @Jericoo_bot del subsistema de marketing (Spec 008, M6).

Conecta las herramientas de marketing y gestión de plantillas como comandos reales
del bot vía bot.register_command, con restricción estricta al rol CTO para aprobación/despacho
y acceso para comerciales a consulta y creación de plantillas bajo linter.

Comandos registrados:
- /campana <idea>: propone una nueva campaña de marketing estructurada y revisada.
- /campanas: lista las campañas pendientes de visto bueno.
- /aprobarcampana <id> [monto]: aprueba formalmente la campaña y autoriza su presupuesto.
- /rechazarcampana <id> <motivo>: rechaza la campaña deteniendo su despacho.
- /despachar <id> [destinatario]: despacha la campaña aprobada (DRY_RUN por defecto).
- /plantillas: lista las plantillas de marca disponibles y pendientes.
- /plantilla nueva <nombre> | <canal> | <trato> | <contenido>: crea una plantilla.
- /aprobarplantilla <id>: aprueba formalmente una plantilla (exclusivo CTO).
- /rechazarplantilla <id> <motivo>: rechaza una plantilla (exclusivo CTO).
"""

import re
import sqlite3
import time
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation

from jerico.crm.bot import CrmBot, deny
from jerico.crm.model import Outgoing, Role, User
from jerico.marketing.orquestador import (
    OrquestadorMarketing,
    obtener_orquestador_global,
)
from jerico.marketing.plantillas import (
    EstadoPlantilla,
    GestorPlantillasMarca,
    TipoPlantilla,
    obtener_gestor_plantillas,
)
from jerico.schemas.marketing import (
    CanalMarketing,
    EstadoCampana,
    IdeaInput,
    Trato,
)

MARKETING_COMMAND_DESCRIPTIONS: dict[str, str] = {
    "campana": "Propone una nueva campaña de marketing a partir de una idea (exclusivo CTO).",
    "campanas": "Lista las campañas de marketing pendientes de visto bueno (exclusivo CTO).",
    "aprobarcampana": "Aprueba formalmente una campaña y autoriza su presupuesto (exclusivo CTO).",
    "rechazarcampana": "Rechaza una propuesta de campaña indicando el motivo (exclusivo CTO).",
    "despachar": "Despacha una campaña aprobada respetando DRY_RUN e idempotencia (exclusivo CTO).",
    "plantillas": "Consulta las plantillas de marca y cotización disponibles.",
    "plantilla": "Crea una nueva plantilla de marca validada con linter.",
    "aprobarplantilla": "Aprueba formalmente una plantilla de comunicación (exclusivo CTO).",
    "rechazarplantilla": "Rechaza una plantilla de comunicación con motivo (exclusivo CTO).",
}


def _extract_args(text: str) -> str:
    return re.sub(r"^/\w+(?:@\w+)?", "", text.strip()).strip()


# ---------------------------------------------------------------------------
# 1. Handlers de Campañas de Marketing (exclusivos CTO)
# ---------------------------------------------------------------------------


def _campana_handler(
    orquestador: OrquestadorMarketing,
) -> Callable[[sqlite3.Connection, User, str, datetime], list[Outgoing]]:
    def handler(conn: sqlite3.Connection, actor: User, text: str, now: datetime) -> list[Outgoing]:
        if actor.role != Role.CTO:
            return deny(conn, actor, now)
        args = _extract_args(text)
        if not args:
            return [Outgoing(actor.telegram_id, "Uso: /campana <descripción de la idea>")]
        nombre_campana = f"Propuesta {time.strftime('%Y%m%d_%H%M')}"
        idea = IdeaInput(
            id=f"IDEA-{int(time.time())}",
            texto=args,
            autor=f"telegram:{actor.telegram_id}",
            origen="telegram",
        )
        try:
            campana = orquestador.proponer_campana(
                idea=idea,
                canal=CanalMarketing.CORREO,
                trato=Trato.USTED,
                nombre=nombre_campana,
            )
            vista_previa = orquestador.formatear_vista_previa_telegram(campana.id)
            return [Outgoing(actor.telegram_id, vista_previa)]
        except Exception as exc:
            return [Outgoing(actor.telegram_id, f"⚠️ Error al estructurar campaña: {exc}")]

    return handler


def _campanas_handler(
    orquestador: OrquestadorMarketing,
) -> Callable[[sqlite3.Connection, User, str, datetime], list[Outgoing]]:
    def handler(conn: sqlite3.Connection, actor: User, text: str, now: datetime) -> list[Outgoing]:
        if actor.role != Role.CTO:
            return deny(conn, actor, now)
        pendientes = [
            c for c in orquestador._campanas.values() if c.estado == EstadoCampana.EN_REVISION
        ]
        if not pendientes:
            return [Outgoing(actor.telegram_id, "No hay campañas pendientes de aprobación.")]

        lineas = [
            f"📋 Campañas Pendientes de Aprobación (CTO) ({len(pendientes)}):",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ]
        for p in pendientes:
            lineas.append(
                f"• ID: {p.id} | Canal: {p.canal.value}\n"
                f"  Presupuesto: {p.presupuesto_estimado_usd} USD | Nombre: {p.nombre}"
            )
        lineas.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lineas.append("Para actuar: /aprobarcampana <id> [monto] o /rechazarcampana <id> <motivo>")
        return [Outgoing(actor.telegram_id, "\n".join(lineas))]

    return handler


def _aprobarcampana_handler(
    orquestador: OrquestadorMarketing,
) -> Callable[[sqlite3.Connection, User, str, datetime], list[Outgoing]]:
    def handler(conn: sqlite3.Connection, actor: User, text: str, now: datetime) -> list[Outgoing]:
        if actor.role != Role.CTO:
            return deny(conn, actor, now)
        args = _extract_args(text)
        if not args:
            return [Outgoing(actor.telegram_id, "Uso: /aprobarcampana <id> [monto_usd]")]
        parts = args.split(maxsplit=1)
        campana_id = parts[0]
        monto = Decimal("0.00")
        if len(parts) > 1:
            try:
                monto = Decimal(parts[1])
            except InvalidOperation:
                return [Outgoing(actor.telegram_id, f"⚠️ Monto inválido: '{parts[1]}'")]

        try:
            campana = orquestador.aprobar_campana(
                campana_id=campana_id,
                usuario_rol="cto",
                gasto_autorizado_usd=monto,
            )
            return [
                Outgoing(
                    actor.telegram_id,
                    f"✅ Campaña '{campana.id}' aprobada formalmente. "
                    f"Presupuesto autorizado: {campana.gasto_autorizado_usd} USD.",
                )
            ]
        except Exception as exc:
            return [Outgoing(actor.telegram_id, f"⚠️ Error al aprobar: {exc}")]

    return handler


def _rechazarcampana_handler(
    orquestador: OrquestadorMarketing,
) -> Callable[[sqlite3.Connection, User, str, datetime], list[Outgoing]]:
    def handler(conn: sqlite3.Connection, actor: User, text: str, now: datetime) -> list[Outgoing]:
        if actor.role != Role.CTO:
            return deny(conn, actor, now)
        args = _extract_args(text)
        if not args:
            return [Outgoing(actor.telegram_id, "Uso: /rechazarcampana <id> <motivo>")]
        parts = args.split(maxsplit=1)
        campana_id = parts[0]
        motivo = parts[1].strip() if len(parts) > 1 else "Rechazada por el CTO"
        try:
            campana = orquestador.rechazar_campana(
                campana_id=campana_id,
                usuario_rol="cto",
                motivo=motivo,
            )
            return [
                Outgoing(
                    actor.telegram_id,
                    f"🛑 Campaña '{campana.id}' rechazada. Motivo: {motivo}.",
                )
            ]
        except Exception as exc:
            return [Outgoing(actor.telegram_id, f"⚠️ Error al rechazar: {exc}")]

    return handler


def _despachar_handler(
    orquestador: OrquestadorMarketing,
) -> Callable[[sqlite3.Connection, User, str, datetime], list[Outgoing]]:
    def handler(conn: sqlite3.Connection, actor: User, text: str, now: datetime) -> list[Outgoing]:
        if actor.role != Role.CTO:
            return deny(conn, actor, now)
        args = _extract_args(text)
        if not args:
            return [Outgoing(actor.telegram_id, "Uso: /despachar <id> [destinatario]")]
        parts = args.split(maxsplit=1)
        campana_id = parts[0]
        destinatario = parts[1].strip() if len(parts) > 1 else None

        try:
            res_obj = orquestador.despachar_campana(
                campana_id=campana_id,
                destinatario=destinatario,
            )
            msg = (
                f"🚀 Campaña '{campana_id}' despachada exitosamente ({res_obj.get('status')}).\n"
                f"Canal: {res_obj.get('canal')}\n"
                f"Destinatario: {res_obj.get('destinatario')}\n"
                f"Idempotency Key: {res_obj.get('idempotency_key')}"
            )
            return [Outgoing(actor.telegram_id, msg)]
        except Exception as exc:
            return [Outgoing(actor.telegram_id, f"⚠️ Error al despachar: {exc}")]

    return handler


# ---------------------------------------------------------------------------
# 2. Handlers de Plantillas de Marca (Comercial y CTO)
# ---------------------------------------------------------------------------


def _plantillas_handler(
    gestor: GestorPlantillasMarca,
) -> Callable[[sqlite3.Connection, User, str, datetime], list[Outgoing]]:
    def handler(conn: sqlite3.Connection, actor: User, text: str, now: datetime) -> list[Outgoing]:
        del conn, text, now
        role_str = getattr(actor.role, "value", actor.role)
        plantillas = gestor.listar_plantillas(usuario_rol=str(role_str))
        if not plantillas:
            return [Outgoing(actor.telegram_id, "No hay plantillas de marca registradas.")]

        lineas = [
            "📋 Plantillas de Marca Kaizen Disponibles:",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ]
        for p in plantillas:
            estado_txt = (
                "Aprobada" if p.estado == EstadoPlantilla.APROBADA else "Pendiente de aprobación"
            )
            lineas.append(
                f"• ID: {p.id} | Canal: {p.canal.value} | Trato: {p.trato.value}\n"
                f"  Nombre: {p.nombre} ({estado_txt})"
            )
        lineas.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        if actor.role == Role.CTO:
            lineas.append(
                "Aprobar: /aprobarplantilla <id> | Rechazar: /rechazarplantilla <id> <motivo>"
            )
        else:
            lineas.append(
                "Para crear nueva: /plantilla nueva <nombre> | <canal> | <trato> | <texto>"
            )
        return [Outgoing(actor.telegram_id, "\n".join(lineas))]

    return handler


def _plantilla_handler(
    gestor: GestorPlantillasMarca,
) -> Callable[[sqlite3.Connection, User, str, datetime], list[Outgoing]]:
    def handler(conn: sqlite3.Connection, actor: User, text: str, now: datetime) -> list[Outgoing]:
        del conn, now
        args = _extract_args(text)
        if not args or not args.startswith("nueva"):
            uso = (
                "Uso para crear plantilla:\n"
                "/plantilla nueva <nombre> | <canal: correo/whatsapp> | <trato: tu/usted> | "
                "<contenido>"
            )
            return [Outgoing(actor.telegram_id, uso)]

        payload = args[len("nueva") :].strip()
        parts = [p.strip() for p in payload.split("|")]
        if len(parts) < 4:
            return [
                Outgoing(
                    actor.telegram_id,
                    "⚠️ Faltan campos. Formato: /plantilla nueva <nombre> | <canal> | <trato> | "
                    "<contenido>",
                )
            ]

        nombre = parts[0]
        canal_str = parts[1]
        trato_str = parts[2]
        contenido = "|".join(parts[3:]).strip()

        try:
            canal = CanalMarketing(canal_str.lower())
        except ValueError:
            canal = CanalMarketing.CORREO

        try:
            trato = Trato(trato_str.lower())
        except ValueError:
            trato = Trato.USTED

        tipo = (
            TipoPlantilla.CORREO_CLIENTE
            if canal == CanalMarketing.CORREO
            else TipoPlantilla.WHATSAPP_CLIENTE
        )

        try:
            plantilla = gestor.crear_plantilla(
                nombre=nombre,
                tipo=tipo,
                canal=canal,
                trato=trato,
                contenido=contenido,
                creado_por=actor.email or f"user:{actor.id}",
            )
            estado_desc = (
                "aprobada inmediatamente (rol CTO)"
                if plantilla.estado == EstadoPlantilla.APROBADA
                else "pendiente de aprobación por el CTO"
            )
            resp = (
                f"✅ Plantilla '{plantilla.nombre}' creada exitosamente.\n"
                f"ID: {plantilla.id}\n"
                f"Estado: {estado_desc}\n"
                f"Canal: {plantilla.canal.value} | Trato: {plantilla.trato.value}"
            )
            return [Outgoing(actor.telegram_id, resp)]
        except ValueError as exc:
            return [Outgoing(actor.telegram_id, f"⚠️ Error de validación: {exc}")]
        except Exception as exc:
            return [Outgoing(actor.telegram_id, f"⚠️ Error al crear plantilla: {exc}")]

    return handler


def _aprobarplantilla_handler(
    gestor: GestorPlantillasMarca,
) -> Callable[[sqlite3.Connection, User, str, datetime], list[Outgoing]]:
    def handler(conn: sqlite3.Connection, actor: User, text: str, now: datetime) -> list[Outgoing]:
        if actor.role != Role.CTO:
            return deny(conn, actor, now)
        args = _extract_args(text)
        if not args:
            return [Outgoing(actor.telegram_id, "Uso: /aprobarplantilla <id>")]

        pid = args.split()[0].strip()
        try:
            plantilla = gestor.aprobar_plantilla(pid, usuario_rol="cto")
            return [
                Outgoing(
                    actor.telegram_id,
                    f"✅ Plantilla '{plantilla.id}' ({plantilla.nombre}) aprobada exitosamente "
                    "para el equipo comercial.",
                )
            ]
        except Exception as exc:
            return [Outgoing(actor.telegram_id, f"⚠️ Error al aprobar plantilla: {exc}")]

    return handler


def _rechazarplantilla_handler(
    gestor: GestorPlantillasMarca,
) -> Callable[[sqlite3.Connection, User, str, datetime], list[Outgoing]]:
    def handler(conn: sqlite3.Connection, actor: User, text: str, now: datetime) -> list[Outgoing]:
        if actor.role != Role.CTO:
            return deny(conn, actor, now)
        args = _extract_args(text)
        if not args:
            return [Outgoing(actor.telegram_id, "Uso: /rechazarplantilla <id> <motivo>")]

        parts = args.split(maxsplit=1)
        pid = parts[0].strip()
        motivo = parts[1].strip() if len(parts) > 1 else "Rechazada por el CTO"
        try:
            plantilla = gestor.rechazar_plantilla(pid, usuario_rol="cto", motivo=motivo)
            return [
                Outgoing(
                    actor.telegram_id, f"🛑 Plantilla '{plantilla.id}' rechazada. Motivo: {motivo}."
                )
            ]
        except Exception as exc:
            return [Outgoing(actor.telegram_id, f"⚠️ Error al rechazar plantilla: {exc}")]

    return handler


# ---------------------------------------------------------------------------
# 3. Registro en CrmBot
# ---------------------------------------------------------------------------


def register_marketing_commands(
    bot: CrmBot,
    orquestador: OrquestadorMarketing | None = None,
    gestor_plantillas: GestorPlantillasMarca | None = None,
) -> None:
    """Registra los comandos de marketing y plantillas en el CrmBot."""
    orq = orquestador or obtener_orquestador_global()
    g_plant = gestor_plantillas or obtener_gestor_plantillas()

    # Comandos de campañas de marketing (exclusivos CTO)
    bot.register_command("campana", _campana_handler(orq))
    bot.register_command("campanas", _campanas_handler(orq))
    bot.register_command("aprobarcampana", _aprobarcampana_handler(orq))
    bot.register_command("rechazarcampana", _rechazarcampana_handler(orq))
    bot.register_command("despachar", _despachar_handler(orq))

    # Comandos de plantillas de marca (comercial + CTO)
    bot.register_command("plantillas", _plantillas_handler(g_plant))
    bot.register_command("plantilla", _plantilla_handler(g_plant))
    bot.register_command("aprobarplantilla", _aprobarplantilla_handler(g_plant))
    bot.register_command("rechazarplantilla", _rechazarplantilla_handler(g_plant))
