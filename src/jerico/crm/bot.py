"""Núcleo del bot: identidad, deduplicación, enrutado y bucle de *long polling* (plan §7).

Requisitos: VCRM-001, 002, 007, 008, 012, 016, 017, 079, 086, 089. Efecto, marca del `update_id`
y *offset* van en la misma transacción; las respuestas se envían tras el *commit*
y no se reintentan.
"""

import asyncio
import logging
import re
import sqlite3
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime

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
from jerico.crm.parsing import parse_callback
from jerico.crm.permissions import Action, authorize
from jerico.crm.ports import DownloadResult, FileStore, InlineButton, TelegramPort, Update
from jerico.crm.telegram import TelegramApiError

logger = logging.getLogger(__name__)

GENERIC_ERROR = "No se pudo procesar tu solicitud. Por favor, intenta de nuevo en unos momentos."
UNKNOWN_COMMAND = "Orden no reconocida. Revisa que el comando esté bien escrito."
INVALID_BUTTON = "Botón no válido o caducado."
ALREADY_PROCESSED = "Esta confirmación ya fue procesada."
CANCELLED = "Operación cancelada."
ALERT_ATTENDED = "Alerta marcada «atendida por otro medio»."
ALERT_ALREADY = "La alerta ya estaba atendida o no existe."
OFFSET_KEY = "telegram_offset"
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
    ) -> None:
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
        self._commands: dict[str, CommandHandler] = {
            "alta": team.add_user,
            "baja_usuario": team.deactivate_user,
            "reasignar": team.reassign_command,
            "nuevo": self._register,
            "nota": leads.add_note,
            "editar": self._edit,
            "lista": leads.list_command,
            "ver": leads.view_lead,
            "retractar": leads.retract_command,
            "autorizacion": compliance.authorization_command,
            "baja": self._opt_out,
            "suprimir": self._suppress,
            "exportar": self._export,
            "solicitud": self._request,
            "solicitudes": compliance.requests_command,
            "atendida": compliance.attended_command,
        }
        self._callbacks: dict[str, CallbackHandler] = {
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
        }
        self._pending: dict[str, PendingHandler] = {
            leads.REJECT_TEXT_KIND: leads.answer_reject_text,
            leads.RETRACT_TEXT_KIND: leads.answer_retract_text,
        }
        self._confirmations: dict[str, ConfirmationHandler] = {
            leads.AUTH_QUESTION_KIND: leads.answer_authorization,
            leads.ACCEPT_KIND: leads.confirm_accept,
            leads.RETRACT_KIND: leads.confirm_retract,
        }

    # --- Registro de handlers -----------------------------------------------------------

    def defer(self, job: DeferredJob) -> None:
        """Encola un trabajo asíncrono que corre tras el *commit*, fuera de la transacción."""
        self._deferred.append(job)

    def register_file_pending(self, kind: str, handler: FilePendingHandler) -> None:
        """Entrada pendiente que espera un archivo (el contrato del abogado, spec 004)."""
        self._file_pending[kind] = handler

    def register_command(self, name: str, handler: CommandHandler) -> None:
        self._commands[name] = handler

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
                if not repo.mark_update_processed(tx, u.update_id, now):
                    return  # VCRM-079
                repo.set_meta(tx, OFFSET_KEY, str(u.update_id + 1))
                user = None if u.user_id is None else repo.active_user_by_telegram(tx, u.user_id)
                if user is None:  # VCRM-001/002: silencio y auditoría
                    repo.audit(
                        tx,
                        actor=f"tg:{u.user_id or 0}",
                        action=AuditAction.ACCESS_DENIED,
                        outcome=AuditOutcome.DENIED,
                        at=now,
                        detail=detail,
                    )
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
                repo.mark_update_processed(tx, u.update_id, now)
                repo.set_meta(tx, OFFSET_KEY, str(u.update_id + 1))
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
            raw = repo.get_meta(conn, OFFSET_KEY)
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
