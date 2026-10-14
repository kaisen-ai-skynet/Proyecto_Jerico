"""Núcleo del bot: identidad, deduplicación, enrutado y bucle de *long polling* (plan §7).

Requisitos: VCRM-001, 002, 007, 008, 012, 016, 017, 079, 086, 089. Efecto, marca del `update_id`
y *offset* van en la misma transacción; las respuestas se envían tras el *commit*
y no se reintentan.
"""

import asyncio
import logging
import re
import sqlite3
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from jerico.crm import compliance, leads, repo, team
from jerico.crm.config import Params, default_params
from jerico.crm.db import CrmDatabase
from jerico.crm.files import MAX_ATTACHMENT_BYTES
from jerico.crm.model import (
    AuditAction,
    AuditDetail,
    AuditOutcome,
    Confirmation,
    LeadState,
    Outgoing,
    PendingInput,
    Role,
    User,
)
from jerico.crm.parsing import build_callback, normalize_email, parse_callback
from jerico.crm.permissions import Action, authorize
from jerico.crm.ports import DownloadResult, FileStore, InlineButton, TelegramPort, Update
from jerico.crm.telegram import TelegramApiError
from jerico.crm.timeutil import from_iso, to_iso

logger = logging.getLogger(__name__)

GENERIC_ERROR = "No se pudo procesar tu solicitud. Por favor, intenta de nuevo en unos momentos."
START_REPLY = (
    "Tu ID de Telegram es {id}. Envíaselo al CTO de Kaisen AI para que te dé acceso a este bot."
)
UNKNOWN_COMMAND = "Orden no reconocida. Revisa que el comando esté bien escrito."
INVALID_BUTTON = "Botón no válido o caducado."
ALREADY_PROCESSED = "Esta confirmación ya fue procesada."
CANCELLED = "Operación cancelada."
ALERT_ATTENDED = "Alerta marcada «atendida por otro medio»."
ALERT_ALREADY = "La alerta ya estaba atendida o no existe."
OFFSET_KEY = "telegram_offset"
UPDATE_NAMESPACE_SPAN = 10**13  # separa los ids de update de cada bot en la tabla de repetidos
POLL_TIMEOUT_S = 25
ERROR_BACKOFF_S = 5.0
_COMMAND_RE = re.compile(r"^/([A-Za-z_]+)(?:@\w+)?(?:\s|$)")

DeferredJob = Callable[[], Awaitable[list[Outgoing]]]
CommandHandler = Callable[[sqlite3.Connection, User, str, datetime], list[Outgoing]]
CallbackHandler = Callable[
    [sqlite3.Connection, User, tuple[str, ...], datetime], list[Outgoing] | None
]
PendingHandler = Callable[
    [sqlite3.Connection, User, PendingInput, Update, datetime], list[Outgoing]
]
FilePendingHandler = Callable[
    [sqlite3.Connection, User, PendingInput, Update, "leads.Prefetched | None", datetime],
    list[Outgoing],
]
ConfirmationHandler = Callable[
    [sqlite3.Connection, User, Confirmation, bool, datetime], list[Outgoing]
]
UserMenuSync = Callable[[int, Role, bool], Awaitable[None]]


DEFAULT_COMMAND_META: dict[str, tuple[str, tuple[Role, ...]]] = {
    # Comandos comerciales (y CTO)
    "nuevo": ("Registrar un nuevo lead", (Role.COMMERCIAL, Role.CTO)),
    "lista": ("Listar leads", (Role.COMMERCIAL, Role.CTO)),
    "ver": ("Ver ficha de un lead", (Role.COMMERCIAL, Role.CTO)),
    "nota": ("Añadir nota a un lead", (Role.COMMERCIAL, Role.CTO)),
    "editar": ("Editar datos de un lead", (Role.COMMERCIAL, Role.CTO)),
    "seguimiento": ("Ver estado de seguimiento", (Role.COMMERCIAL, Role.CTO)),
    "pedirautorizacion": ("Solicitar autorización a un lead", (Role.COMMERCIAL, Role.CTO)),
    "solicitar_autorizacion": ("Solicitar autorización a un lead", (Role.COMMERCIAL, Role.CTO)),
    "autorizacion": ("Registrar consentimiento de un lead", (Role.COMMERCIAL, Role.CTO)),
    "oferta": ("Crear o consultar oferta para un lead", (Role.COMMERCIAL, Role.CTO)),
    "firma": ("Enviar contrato a firma electrónica", (Role.COMMERCIAL, Role.CTO)),
    "retractar": ("Retractar un lead", (Role.COMMERCIAL, Role.CTO)),
    "baja": ("Registrar baja voluntaria de un lead", (Role.COMMERCIAL, Role.CTO)),
    "buzon": ("Consultar estado de tu buzón de correo", (Role.COMMERCIAL, Role.CTO)),
    "candidatos": ("Listar correos candidatos a lead", (Role.COMMERCIAL, Role.CTO)),
    "asistente": ("Consultar al asistente comercial", (Role.COMMERCIAL, Role.CTO)),
    # Comandos exclusivos de CTO
    "alta": ("Dar de alta a un usuario", (Role.CTO,)),
    "baja_usuario": ("Dar de baja a un usuario", (Role.CTO,)),
    "reasignar": ("Reasignar leads de un comercial", (Role.CTO,)),
    "suprimir": ("Suprimir datos de un lead", (Role.CTO,)),
    "exportar": ("Exportar datos de un lead", (Role.CTO,)),
    "solicitud": ("Registrar solicitud de titular", (Role.CTO,)),
    "solicitudes": ("Listar solicitudes de titulares", (Role.CTO,)),
    "atendida": ("Marcar alerta como atendida", (Role.CTO,)),
    "buzones": ("Listar todos los buzones configurados", (Role.CTO,)),
    "casos": ("Listar casos para contrato", (Role.CTO,)),
    "paquete": ("Consultar paquete de contrato", (Role.COMMERCIAL, Role.CTO)),
    "basejuridica": ("Confirmar base legal de un contrato", (Role.CTO,)),
    "subircontrato": ("Subir contrato en PDF o DOCX", (Role.CTO,)),
    "devolver": ("Devolver paquete con observaciones", (Role.CTO,)),
    "formaespecial": ("Marcar contrato con forma especial", (Role.CTO,)),
    "firmaprueba": ("Simular firma en modo prueba", (Role.CTO,)),
    # Comandos generales
    "start": ("Iniciar y ver bienvenida", (Role.COMMERCIAL, Role.LAWYER, Role.CTO)),
    "ayuda": ("Ver comandos disponibles", (Role.COMMERCIAL, Role.LAWYER, Role.CTO)),
    "descargar": ("Descargar paquete como archivo", (Role.LAWYER, Role.CTO)),
    # Catálogo de precios (spec 006)
    "catalogo": ("Ver el catálogo de servicios y precios", (Role.COMMERCIAL, Role.CTO)),
    "cotizar": ("Generar una cotización con precios del catálogo", (Role.COMMERCIAL, Role.CTO)),
    "catalogo_actualizar": ("Actualizar precios del catálogo (borrador)", (Role.CTO,)),
    "catalogo_activar": ("Activar una versión del catálogo", (Role.CTO,)),
    "catalogo_verificar": ("Verificar el catálogo contra el modelo financiero", (Role.CTO,)),
    # Marketing y plantillas de marca (spec 008)
    "campana": ("Proponer una campaña a partir de una idea", (Role.CTO,)),
    "campanas": ("Ver campañas pendientes de aprobación", (Role.CTO,)),
    "aprobarcampana": ("Aprobar una campaña", (Role.CTO,)),
    "rechazarcampana": ("Rechazar una campaña con motivo", (Role.CTO,)),
    "despachar": ("Enviar una campaña aprobada (respeta el modo prueba)", (Role.CTO,)),
    "plantillas": ("Ver plantillas de marca disponibles", (Role.COMMERCIAL, Role.CTO)),
    "plantilla": ("Crear o usar una plantilla de marca", (Role.COMMERCIAL, Role.CTO)),
    "aprobarplantilla": ("Aprobar una plantilla nueva", (Role.CTO,)),
    "rechazarplantilla": ("Rechazar una plantilla nueva", (Role.CTO,)),
}


@dataclass(frozen=True)
class CommandEntry:
    name: str
    handler: CommandHandler
    description: str = ""
    roles: tuple[Role, ...] = ()

    def __call__(
        self, conn: sqlite3.Connection, actor: User, text: str, now: datetime
    ) -> list[Outgoing]:
        return self.handler(conn, actor, text, now)


def deny(conn: sqlite3.Connection, actor: User, now: datetime) -> list[Outgoing]:
    """Acción no permitida al rol: respuesta y auditoría (VCRM-086)."""
    repo.audit(
        conn,
        actor=f"user:{actor.id}",
        action=AuditAction.PERMISSION_DENIED,
        outcome=AuditOutcome.DENIED,
        at=now,
    )
    return [Outgoing(actor.telegram_id, team.DENIED)]


def _ints(args: tuple[str, ...], count: int) -> list[int] | None:
    if len(args) != count or not all(a.isdigit() for a in args):
        return None
    return [int(a) for a in args]


def _reassign_cb(
    conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
) -> list[Outgoing] | None:
    one, two = _ints(args, 1), _ints(args, 2)
    if one is not None:
        return team.reassign_keyboard(conn, user, one[0], now)
    if two is not None:
        return team.reassign(conn, user, two[0], two[1], now)
    return None


def _orphans_cb(
    conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
) -> list[Outgoing] | None:
    values = _ints(args, 2)
    if values is None:
        return None
    if not authorize(user, Action.MANAGE_USERS, None).allowed:
        return deny(conn, user, now)
    return [team.orphan_leads_message(conn, user.telegram_id, values[0], values[1])]


def _open_cb(
    conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
) -> list[Outgoing] | None:
    values = _ints(args, 1)
    return None if values is None else leads.open_existing(conn, user, values[0], now)


def _list_cb(
    conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
) -> list[Outgoing] | None:
    values = _ints(args, 1)
    return None if values is None else leads.list_page(conn, user, values[0], now)


def _cancel_cb(
    conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
) -> list[Outgoing] | None:
    return [Outgoing(user.telegram_id, CANCELLED)]


def _state_cb(
    conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
) -> list[Outgoing] | None:
    """Botón de estado de la ficha: `estado:<operación>:<lead>` (VCRM-089, 115, 116)."""
    if len(args) != 2 or args[0] not in leads.STATE_OPS or not args[1].isdigit():
        return None
    _, dst = leads.STATE_OPS[args[0]]
    if dst is LeadState.ACCEPTED:  # toda aceptación pasa por la confirmación ✅/❌ (VCRM-046)
        return leads.request_accept(conn, user, int(args[1]), now)
    return leads.transition(conn, user, int(args[1]), dst, now)


def _reason_cb(
    conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
) -> list[Outgoing] | None:
    """Botón de motivo de rechazo: `motivo:<lead>:<código>` (VCRM-016, 017)."""
    if len(args) != 2 or not args[0].isdigit() or args[1] not in leads.REJECT_REASONS:
        return None
    return leads.transition(conn, user, int(args[0]), LeadState.REJECTED, now, reason=args[1])


def _retract_reason_cb(
    conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
) -> list[Outgoing] | None:
    """Botón de motivo de retractación: `rmotivo:<lead>:<código>` (VCRM-131, 114)."""
    if len(args) != 2 or not args[0].isdigit() or args[1] not in leads.REJECT_REASONS:
        return None
    return leads.request_retract(conn, user, int(args[0]), now, reason=args[1])


def _retract_cb(
    conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
) -> list[Outgoing] | None:
    """Botón «Retractar» de la ficha: `retractar:<lead>`, mismo flujo que la orden (VCRM-163)."""
    if len(args) != 1 or not args[0].isdigit():
        return None
    return leads.request_retract(conn, user, int(args[0]), now)


def _attended_cb(
    conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
) -> list[Outgoing] | None:
    """Botón «Atendida por otro medio»: `atendida:<alerta>`; solo CTO, con autor y fecha (087)."""
    values = _ints(args, 1)
    if values is None:
        return None
    if user.role != Role.CTO:
        return deny(conn, user, now)
    done = repo.resolve_alert(conn, values[0], resolved_by=user.id, now=now)
    return [Outgoing(user.telegram_id, ALERT_ATTENDED if done else ALERT_ALREADY)]


def _buttons(out: Outgoing) -> list[list[InlineButton]] | None:
    rows = [[InlineButton(text, data) for text, data in row] for row in out.buttons]
    return rows or None


class CrmBot:
    """Procesa actualizaciones de Telegram de forma idempotente."""

    def __init__(
        self,
        db: CrmDatabase,
        telegram: TelegramPort,
        clock: Callable[[], datetime],
        *,
        kick: Callable[[], None] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        fingerprint_keys: Sequence[str] = (),
        files: FileStore | None = None,
        export_limit: int = compliance.TELEGRAM_UPLOAD_LIMIT,
        export_margin: int = compliance.PART_MARGIN,
        params: Params | None = None,
        offset_key: str = OFFSET_KEY,
        update_namespace: int = 0,
        minimal: bool = False,
        allowed_ids: frozenset[int] | None = None,
        anonymous_start: bool = False,
    ) -> None:
        """Los cinco últimos parámetros permiten un segundo bot (el del abogado, spec 004).

        `offset_key` y `update_namespace` separan su avance y sus ids de los del bot principal;
        `minimal` no registra los comandos de ventas; `allowed_ids` añade una lista blanca de
        identidades de Telegram además de la tabla de usuarios; `anonymous_start` responde a
        `/start` de un desconocido solo con su propio ID (para que el CTO lo autorice)."""
        self._offset_key = offset_key
        self._id_base = update_namespace * UPDATE_NAMESPACE_SPAN
        self._allowed_ids = allowed_ids
        self._anonymous_start = anonymous_start
        self._db = db
        self._telegram = telegram
        self._clock = clock
        self._kick = kick
        self._sleep = sleep
        self._fingerprint_keys = tuple(fingerprint_keys)  # clave actual primero, luego previas
        self._files = files
        self._export_limit = export_limit
        self._export_margin = export_margin
        self._params = params or default_params()
        self._export_jobs: list[compliance.ExportJob] = []  # se envían tras el *commit*
        self._file_pending: dict[str, FilePendingHandler] = {}
        self._deferred: list[DeferredJob] = []  # trabajos de red tras el *commit* (asistente)
        self._on_user_menu_sync: UserMenuSync | None = None
        self._commands: dict[str, CommandEntry] = {}
        if not minimal:
            self._register_default_commands()
        self._callbacks: dict[str, CallbackHandler] = (
            {}
            if minimal
            else {
                "reasignar": _reassign_cb,
                "baja_leads": _orphans_cb,
                "conf": self._confirmation_cb,
                "abrir": _open_cb,
                "cancelar": _cancel_cb,
                "lista": _list_cb,
                "estado": _state_cb,
                "motivo": _reason_cb,
                "rmotivo": _retract_reason_cb,
                "retractar": _retract_cb,
                "atendida": _attended_cb,
                "altareq": self._handle_alta_req_cb,
            }
        )
        self._pending: dict[str, PendingHandler] = (
            {}
            if minimal
            else {
                leads.REJECT_TEXT_KIND: leads.answer_reject_text,
                leads.RETRACT_TEXT_KIND: leads.answer_retract_text,
                "alta_guiada": self._handle_alta_guiada_pending,
            }
        )
        self._confirmations: dict[str, ConfirmationHandler] = (
            {}
            if minimal
            else {
                leads.AUTH_QUESTION_KIND: leads.answer_authorization,
                leads.ACCEPT_KIND: leads.confirm_accept,
                leads.RETRACT_KIND: leads.confirm_retract,
            }
        )

    # --- Registro de handlers -----------------------------------------------------------

    def defer(self, job: DeferredJob) -> None:
        """Encola un trabajo asíncrono que corre tras el *commit*, fuera de la transacción."""
        self._deferred.append(job)

    def register_file_pending(self, kind: str, handler: FilePendingHandler) -> None:
        """Entrada pendiente que espera un archivo (el contrato del abogado, spec 004)."""
        self._file_pending[kind] = handler

    def _register_default_commands(self) -> None:
        self.register_command("start", self._start_cmd)
        self.register_command("ayuda", self._help_cmd)
        self.register_command("alta", self._add_user_cmd)
        self.register_command("baja_usuario", self._deactivate_user_cmd)
        self.register_command("reasignar", team.reassign_command)
        self.register_command("nuevo", self._register)
        self.register_command("nota", leads.add_note)
        self.register_command("editar", self._edit)
        self.register_command("lista", leads.list_command)
        self.register_command("ver", leads.view_lead)
        self.register_command("retractar", leads.retract_command)
        self.register_command("autorizacion", compliance.authorization_command)
        self.register_command("baja", self._opt_out)
        self.register_command("suprimir", self._suppress)
        self.register_command("exportar", self._export)
        self.register_command("solicitud", self._request)
        self.register_command("solicitudes", compliance.requests_command)
        self.register_command("atendida", compliance.attended_command)

    def _start_cmd(
        self, conn: sqlite3.Connection, actor: User, text: str, now: datetime
    ) -> list[Outgoing]:
        msg = (
            f"Bienvenido a Jericó CRM, {actor.email}.\n"
            "Usa /ayuda para ver los comandos disponibles."
        )
        return [Outgoing(actor.telegram_id, msg)]

    def _help_cmd(
        self, conn: sqlite3.Connection, actor: User, text: str, now: datetime
    ) -> list[Outgoing]:
        role = Role(actor.role)
        cmds = self.commands_for_role(role)
        lines = ["Comandos disponibles:"]
        for c in cmds:
            lines.append(f"• /{c['command']} — {c['description']}")
        return [Outgoing(actor.telegram_id, "\n".join(lines))]

    def _handle_alta_req_cb(
        self, conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
    ) -> list[Outgoing] | None:
        if user.role != Role.CTO:
            return deny(conn, user, now)
        if not args or len(args) < 2:
            return None
        action, target_tg_str = args[0], args[1]
        if action == "ign":
            return [Outgoing(user.telegram_id, "Solicitud de acceso ignorada.")]
        if action in ("com", "law"):
            target_role = "comercial" if action == "com" else "abogado"
            repo.set_pending_input(
                conn,
                user_id=user.id,
                kind="alta_guiada",
                data=f"{target_role}:{target_tg_str}",
                now=now,
            )
            return [
                Outgoing(
                    user.telegram_id,
                    f"Por favor ingresa el correo electrónico para el nuevo {target_role}:",
                )
            ]
        return None

    def _handle_alta_guiada_pending(
        self,
        conn: sqlite3.Connection,
        user: User,
        pending: PendingInput,
        u: Update,
        now: datetime,
    ) -> list[Outgoing]:
        if not pending.data or ":" not in pending.data:
            return [Outgoing(user.telegram_id, "Error en la solicitud de alta guiada.")]
        role_str, target_tg_str = pending.data.split(":", 1)
        email = (u.text or "").strip()
        email_clean = normalize_email(email)
        if email_clean is None:
            repo.set_pending_input(
                conn,
                user_id=user.id,
                kind="alta_guiada",
                data=pending.data,
                now=now,
            )
            return [
                Outgoing(
                    user.telegram_id,
                    "Correo inválido. Por favor ingresa un correo electrónico válido:",
                )
            ]
        out = self._add_user_cmd(
            conn, user, f"/alta {role_str}; {target_tg_str}; {email_clean}", now
        )
        return out

    def _add_user_cmd(
        self, conn: sqlite3.Connection, actor: User, text: str, now: datetime
    ) -> list[Outgoing]:
        out = team.add_user(conn, actor, text, now)
        if out and "Alta registrada:" in out[0].text:
            body = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else ""
            parts = [p.strip() for p in body.split(";")]
            if len(parts) >= 2:
                role = team._ROLE_WORDS.get(parts[0].lower())
                tg_id = team._parse_tg(parts[1])
                if role == Role.LAWYER and tg_id is not None:
                    repo.set_meta(conn, f"legal_allowed:{tg_id}", "1")
                if role is not None and tg_id is not None and self._on_user_menu_sync is not None:
                    sync_fn = self._on_user_menu_sync
                    self.defer(lambda: self._sync_deferred(sync_fn, tg_id, role, True))
        return out

    def _deactivate_user_cmd(
        self, conn: sqlite3.Connection, actor: User, text: str, now: datetime
    ) -> list[Outgoing]:
        body = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else ""
        tg_id = team._parse_tg(body)
        target = None if tg_id is None else repo.active_user_by_telegram(conn, tg_id)
        out = team.deactivate_user(conn, actor, text, now)
        if out and "Baja registrada:" in out[0].text:
            if target is not None:
                target_role = Role(target.role)
                if target_role == Role.LAWYER:
                    repo.set_meta(conn, f"legal_allowed:{target.telegram_id}", "0")
                if self._on_user_menu_sync is not None:
                    sync_fn = self._on_user_menu_sync
                    self.defer(
                        lambda: self._sync_deferred(sync_fn, target.telegram_id, target_role, False)
                    )
        return out

    async def _sync_deferred(
        self,
        sync_fn: UserMenuSync,
        tg_id: int,
        role: Role,
        active: bool,
    ) -> list[Outgoing]:
        try:
            await sync_fn(tg_id, role, active)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error sincronizando menú de usuario %s: %s", tg_id, exc)
        return []

    def register_command(
        self,
        name: str,
        handler: CommandHandler,
        description: str = "",
        roles: Sequence[Role] = (),
    ) -> None:
        if not description and name in DEFAULT_COMMAND_META:
            description = DEFAULT_COMMAND_META[name][0]
        if not roles and name in DEFAULT_COMMAND_META:
            roles = DEFAULT_COMMAND_META[name][1]
        self._commands[name] = CommandEntry(
            name=name,
            handler=handler,
            description=description,
            roles=tuple(roles),
        )

    @property
    def commands(self) -> Mapping[str, CommandEntry]:
        return self._commands

    @property
    def on_user_menu_sync(self) -> UserMenuSync | None:
        return self._on_user_menu_sync

    @on_user_menu_sync.setter
    def on_user_menu_sync(self, fn: UserMenuSync | None) -> None:
        self._on_user_menu_sync = fn

    def commands_for_role(self, role: Role) -> list[dict[str, str]]:
        """Devuelve los comandos para setMyCommands según el rol."""
        res: list[dict[str, str]] = []
        for entry in self._commands.values():
            if not entry.description:
                continue
            if role == Role.CTO or role in entry.roles:
                res.append({"command": entry.name, "description": entry.description})
        return res

    async def set_my_commands_for_role(
        self,
        role: Role,
        scope: Mapping[str, Any] | None = None,
    ) -> bool:
        cmds = self.commands_for_role(role)
        try:
            return await self._telegram.set_my_commands(cmds, scope=scope)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fallo en setMyCommands para rol %s (scope=%s): %s", role, scope, exc)
            return False

    async def delete_my_commands(
        self,
        scope: Mapping[str, Any] | None = None,
    ) -> bool:
        try:
            return await self._telegram.delete_my_commands(scope=scope)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fallo en deleteMyCommands (scope=%s): %s", scope, exc)
            return False

    async def set_chat_menu_button(
        self,
        chat_id: int | None = None,
        menu_button: Mapping[str, Any] | None = None,
    ) -> bool:
        try:
            return await self._telegram.set_chat_menu_button(
                chat_id=chat_id, menu_button=menu_button
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fallo en setChatMenuButton (chat_id=%s): %s", chat_id, exc)
            return False

    def register_callback(self, action: str, handler: CallbackHandler) -> None:
        self._callbacks[action] = handler

    def register_pending(self, kind: str, handler: PendingHandler) -> None:
        self._pending[kind] = handler

    def register_confirmation(self, kind: str, handler: ConfirmationHandler) -> None:
        self._confirmations[kind] = handler

    # --- Enrutado ------------------------------------------------------------------------

    def _register(
        self, conn: sqlite3.Connection, user: User, text: str, now: datetime
    ) -> list[Outgoing]:
        return leads.register(conn, user, text, now, self._fingerprint_keys)

    def _edit(
        self, conn: sqlite3.Connection, user: User, text: str, now: datetime
    ) -> list[Outgoing]:
        return leads.edit(conn, user, text, now, self._fingerprint_keys)

    def _opt_out(
        self, conn: sqlite3.Connection, user: User, text: str, now: datetime
    ) -> list[Outgoing]:
        return compliance.opt_out_command(conn, user, text, now, self._fingerprint_keys)

    def _suppress(
        self, conn: sqlite3.Connection, user: User, text: str, now: datetime
    ) -> list[Outgoing]:
        return compliance.suppress_command(
            conn, user, text, now, self._files, self._fingerprint_keys
        )

    def _request(
        self, conn: sqlite3.Connection, user: User, text: str, now: datetime
    ) -> list[Outgoing]:
        return compliance.request_command(conn, user, text, now, self._params)

    def _export(
        self, conn: sqlite3.Connection, user: User, text: str, now: datetime
    ) -> list[Outgoing]:
        result = compliance.export_command(
            conn,
            user,
            text,
            now,
            self._files,
            limit=self._export_limit,
            margin=self._export_margin,
        )
        if isinstance(result, compliance.ExportJob):
            self._export_jobs.append(result)
            return []
        return result

    def _confirmation_cb(
        self, conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
    ) -> list[Outgoing] | None:
        if len(args) != 2 or not args[0].isdigit() or args[1] not in ("si", "no"):
            return None
        conf = repo.get_confirmation(conn, int(args[0]))
        if conf is None:
            return None
        if conf.user_id != user.id:
            return deny(conn, user, now)
        yes = args[1] == "si"
        if not repo.resolve_confirmation(conn, conf.id, "confirmed" if yes else "cancelled", now):
            if yes and conf.kind == leads.ACCEPT_KIND:  # VCRM-051
                again = leads.repeated_accept(conn, user, conf)
                if again is not None:
                    return again
            return [Outgoing(user.telegram_id, ALREADY_PROCESSED)]
        handler = self._confirmations.get(conf.kind)
        if handler is None:
            return [Outgoing(user.telegram_id, CANCELLED)] if not yes else []
        return handler(conn, user, conf, yes, now)

    def _route(
        self,
        conn: sqlite3.Connection,
        user: User,
        u: Update,
        now: datetime,
        prefetch: leads.Prefetched | None = None,
    ) -> list[Outgoing]:
        if u.callback_data is not None:
            data = parse_callback(u.callback_data)
            handler = None if data is None else self._callbacks.get(data.action)
            out = None if data is None or handler is None else handler(conn, user, data.args, now)
            return [Outgoing(user.telegram_id, INVALID_BUTTON)] if out is None else out
        text = (u.text or u.caption or "").strip()
        match = _COMMAND_RE.match(text)
        if match:
            repo.clear_pending_input(conn, user.id)  # una orden nueva sustituye la pendiente
            command = self._commands.get(match.group(1).lower())
            if command is not None:
                return command(conn, user, text, now)
        else:
            pending = repo.get_pending_input(conn, user.id, now)
            repo.clear_pending_input(conn, user.id)
            if pending is not None and pending.kind == leads.AUTH_EVIDENCE_KIND:  # VCRM-138/139
                return compliance.answer_evidence(
                    conn, user, pending, u, prefetch, self._files, now
                )
            file_handler = None if pending is None else self._file_pending.get(pending.kind)
            if pending is not None and file_handler is not None:
                return file_handler(conn, user, pending, u, prefetch, now)
            pending_handler = None if pending is None else self._pending.get(pending.kind)
            if pending is not None and pending_handler is not None:
                return pending_handler(conn, user, pending, u, now)
            if prefetch is not None and self._files is not None:
                return leads.add_attachment(conn, user, u.caption, prefetch, self._files, now)
        return [Outgoing(user.telegram_id, UNKNOWN_COMMAND)]

    # --- Procesamiento ------------------------------------------------------------------

    async def _prefetch(self, u: Update) -> leads.Prefetched | None:
        """Descarga previa a la transacción, solo para usuarios activos en chat privado."""
        if u.file is None or self._files is None or u.user_id is None:
            return None
        if u.chat_type != "private":
            return None
        with self._db.read() as conn:
            if repo.active_user_by_telegram(conn, u.user_id) is None:
                return None
            if not self._is_allowed(u.user_id, conn):
                return None
        path = self._files.new_tmp_path()
        if u.file.size is not None and u.file.size > MAX_ATTACHMENT_BYTES:
            result = DownloadResult(ok=False, size=u.file.size, error="too_large")
        else:
            result = await self._telegram.download_file(u.file.file_id, path, MAX_ATTACHMENT_BYTES)
        return leads.Prefetched(kind=u.file.kind, path=path, result=result)

    async def process_update(self, u: Update) -> None:
        prefetch = await self._prefetch(u)
        now = self._clock()
        detail = AuditDetail.CALLBACK if u.callback_data is not None else AuditDetail.MESSAGE
        user: User | None = None
        routed = False
        out: list[Outgoing] = []
        self._export_jobs = []
        self._deferred = []
        try:
            with self._db.tx() as tx:
                if not repo.mark_update_processed(tx, self._id_base + u.update_id, now):
                    return  # VCRM-079
                repo.set_meta(tx, self._offset_key, str(u.update_id + 1))
                user = None if u.user_id is None else repo.active_user_by_telegram(tx, u.user_id)
                if user is not None and not self._is_allowed(u.user_id, tx):
                    user = None  # lista blanca del segundo bot: silencio y auditoría
                if user is None:  # VCRM-001/002: silencio y auditoría
                    repo.audit(
                        tx,
                        actor=f"tg:{u.user_id or 0}",
                        action=AuditAction.ACCESS_DENIED,
                        outcome=AuditOutcome.DENIED,
                        at=now,
                        detail=detail,
                    )
                    if self._wants_id(u):
                        out = [Outgoing(u.chat_id or 0, START_REPLY.format(id=u.user_id))]
                    elif not self._anonymous_start and self._is_start_cmd(u):
                        last_req_raw = repo.get_meta(tx, f"alta_req:{u.user_id}")
                        is_rate_limited = False
                        if last_req_raw:
                            try:
                                if now - from_iso(last_req_raw) < timedelta(hours=24):
                                    is_rate_limited = True
                            except Exception as exc:  # noqa: BLE001
                                logger.debug("Error parseando fecha de alta_req: %s", exc)
                        if not is_rate_limited:
                            repo.set_meta(tx, f"alta_req:{u.user_id}", to_iso(now))
                            reply_unknown = Outgoing(
                                u.chat_id or 0,
                                "Hola, tu solicitud de acceso fue enviada al administrador.",
                            )
                            ctos = repo.active_users(tx, Role.CTO)
                            name_str = u.user_name or "Desconocido"
                            uname_str = f"@{u.username}" if u.username else "sin @usuario"
                            cto_text = (
                                f"Solicitud de acceso:\n"
                                f"• Nombre: {name_str}\n"
                                f"• Usuario: {uname_str}\n"
                                f"• ID: {u.user_id}"
                            )
                            buttons = (
                                (
                                    (
                                        "Alta comercial",
                                        build_callback("altareq", "com", str(u.user_id)),
                                    ),
                                    (
                                        "Alta abogado",
                                        build_callback("altareq", "law", str(u.user_id)),
                                    ),
                                ),
                                (("Ignorar", build_callback("altareq", "ign", str(u.user_id))),),
                            )
                            cto_msgs = [
                                Outgoing(cto.telegram_id, cto_text, buttons=buttons) for cto in ctos
                            ]
                            out = [reply_unknown, *cto_msgs]
                elif u.chat_type != "private":
                    repo.audit(
                        tx,
                        actor=f"user:{user.id}",
                        action=AuditAction.ACCESS_DENIED,
                        outcome=AuditOutcome.DENIED,
                        at=now,
                        detail=AuditDetail.NON_PRIVATE_CHAT,
                    )
                else:
                    out = self._route(tx, user, u, now, prefetch)
                    routed = True
        except Exception as exc:  # noqa: BLE001 - regla O1: ningún error detiene el bucle
            self._export_jobs = []  # *rollback*: no se entrega nada de lo preparado
            self._deferred = []
            out = self._record_handler_error(u, user, exc, now)
        finally:
            if prefetch is not None:  # temporal no consumido: nunca queda un archivo parcial
                prefetch.path.unlink(missing_ok=True)
        await self._deliver(out, user, now)
        jobs, self._export_jobs = self._export_jobs, []
        for job in jobs:  # VCRM-074/166: documentos tras el *commit*
            if self._files is not None:
                notice = await compliance.deliver_export(job, self._telegram, self._files)
                await self._deliver(notice, user, now)
        deferred, self._deferred = self._deferred, []
        if user is not None:  # VCRM-A36: la red del asistente va fuera de la transacción
            for later in deferred:
                await self._deliver(await self._run_deferred(later, user.telegram_id), user, now)
        if u.callback_id is not None:
            await self._telegram.answer_callback(u.callback_id)
        if routed and self._kick is not None:
            self._kick()

    def _record_handler_error(
        self, u: Update, user: User | None, exc: Exception, now: datetime
    ) -> list[Outgoing]:
        """Tras el *rollback*: marca el update y audita `handler_error` en otra transacción."""
        logger.error("crm handler error: %s", type(exc).__name__)
        try:
            with self._db.tx() as tx:
                repo.mark_update_processed(tx, self._id_base + u.update_id, now)
                repo.set_meta(tx, self._offset_key, str(u.update_id + 1))
                repo.audit(
                    tx,
                    actor="system" if user is None else f"user:{user.id}",
                    action=AuditAction.HANDLER_ERROR,
                    outcome=AuditOutcome.ERROR,
                    at=now,
                )
        except Exception as second:  # noqa: BLE001
            logger.error("crm handler_error not recorded: %s", type(second).__name__)
        if user is None:
            return []
        return [Outgoing(user.telegram_id, GENERIC_ERROR)]

    def _wants_id(self, u: Update) -> bool:
        text = (u.text or "").strip().lower()
        return (
            self._anonymous_start
            and u.chat_type == "private"
            and u.user_id is not None
            and u.chat_id is not None
            and (text == "/start" or text.startswith("/start "))
        )

    def _is_start_cmd(self, u: Update) -> bool:
        text = (u.text or "").strip().lower()
        return (
            u.chat_type == "private"
            and u.user_id is not None
            and u.chat_id is not None
            and (text == "/start" or text.startswith("/start "))
        )

    def _is_allowed(self, telegram_id: int | None, conn: sqlite3.Connection | None = None) -> bool:
        if self._allowed_ids is None:
            return True
        if telegram_id in self._allowed_ids:
            return True
        if conn is not None and telegram_id is not None:
            if repo.get_meta(conn, f"legal_allowed:{telegram_id}") == "1":
                return True
            u = repo.active_user_by_telegram(conn, telegram_id)
            if u is not None and u.role == Role.CTO:
                return True
        return False

    async def _run_deferred(self, job: DeferredJob, chat_id: int) -> list[Outgoing]:
        try:
            return await job()
        except Exception as exc:  # noqa: BLE001 - regla O1: ningún error detiene el bucle
            logger.error("trabajo diferido falló: %s", type(exc).__name__)
            return [Outgoing(chat_id, GENERIC_ERROR)]

    async def _deliver(self, out: list[Outgoing], actor: User | None, now: datetime) -> None:
        """Envío único; si no consta entregado → fila `fallida` sin cuerpo (VCRM-012)."""
        for item in out:
            result = await self._telegram.send_message(item.chat_id, item.text, _buttons(item))
            if result.delivered:
                continue
            with self._db.tx() as tx:
                recipient = repo.active_user_by_telegram(tx, item.chat_id) or actor
                if recipient is None:  # pragma: no cover - solo se responde a usuarios activos
                    continue
                repo.record_failed_noncritical(
                    tx, recipient_user_id=recipient.id, kind="reply", error=result.error, now=now
                )

    # --- Bucle ----------------------------------------------------------------------------

    async def run_polling(
        self, stop: asyncio.Event, heartbeat: Callable[[], None] | None = None
    ) -> None:
        with self._db.read() as conn:
            raw = repo.get_meta(conn, self._offset_key)
        offset = None if raw is None else int(raw)
        while not stop.is_set():
            try:
                updates = await self._telegram.get_updates(offset, POLL_TIMEOUT_S)
            except TelegramApiError:
                await self._sleep(ERROR_BACKOFF_S)
                continue
            for u in updates:
                await self.process_update(u)
                offset = u.update_id + 1
            if heartbeat is not None:
                heartbeat()
