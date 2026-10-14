"""Botones y comandos de la fase 2 en el bot (F2-T21 y T24; plan-f2 §4, §5.3, §5.6, §5.9).

Se registran en `CrmBot` por sus puntos de extensión (`register_callback`, `register_command`,
`register_pending`): el núcleo del bot no cambia y, sin este registro, F1 se comporta igual.

Cada manejador solo traduce el botón a la función de servicio correspondiente: las reglas (quién
puede decidir, estados válidos, una sola resolución) viven en `gate`, `delivery`, `authreq`,
`replies` y `followup`. Un botón con argumentos inválidos devuelve `None` (el bot responde
«botón no válido»).
"""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from jerico.crm import authreq, delivery, followup, followup_view, gate, leads, replies, repo
from jerico.crm.bot import CallbackHandler, CommandHandler, CrmBot
from jerico.crm.config import CrmSettings, Params
from jerico.crm.model import (
    AuditAction,
    AuditOutcome,
    LeadState,
    Outgoing,
    PendingInput,
    RequestType,
    SendStatus,
    User,
)
from jerico.crm.parsing import parse_short_id
from jerico.crm.ports import Update

PAUSE_CALLBACK = "cpausar"
RESUME_CALLBACK = "creanudar"
WEEKLY_CALLBACK = "cfrec7"
MONTHLY_CALLBACK = "cfrec30"
LOST_CALLBACK = "cperdido"
REACTIVATE_CALLBACK = "creactivar"
REQUEST_AUTH_COMMAND = "pedirautorizacion"
EXAMPLE_REQUEST_AUTH = "/pedirautorizacion L-0042"


@dataclass(frozen=True)
class F2Context:
    """Lo que necesitan los manejadores y que el bot no guarda."""

    keys: tuple[str, ...]
    params: Params
    settings: CrmSettings
    sender_name: str
    # Pide un primer intento de envío en línea tras un ✅ dentro de franja y cupo (D-3).
    kick_delivery: Callable[[], None] | None = None


def _ints(args: tuple[str, ...], count: int) -> list[int] | None:
    if len(args) != count or not all(a.isdigit() for a in args):
        return None
    return [int(a) for a in args]


def register_f2(bot: CrmBot, ctx: F2Context) -> None:
    """Registra los callbacks, el comando y el texto pendiente de la fase 2."""
    consumed = followup.on_step_consumed

    # --- Gate ✅/❌ ---------------------------------------------------------------------
    def approve(
        conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
    ) -> list[Outgoing] | None:
        values = _ints(args, 2)
        if values is None:
            return None
        outcome = gate.approve(
            conn,
            user,
            values[0],
            values[1],
            now,
            ctx.keys,
            extra_holidays=ctx.params.extra_holidays,
            on_step_consumed=consumed,
        )
        if outcome.deliver_now and ctx.kick_delivery is not None:
            ctx.kick_delivery()
        return outcome.out

    def reject(
        conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
    ) -> list[Outgoing] | None:
        values = _ints(args, 2)
        if values is None:
            return None
        return gate.reject(conn, user, values[0], values[1], now, on_step_consumed=consumed)

    def cancel(
        conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
    ) -> list[Outgoing] | None:
        values = _ints(args, 1)
        if values is None:
            return None
        return gate.cancel(conn, user, values[0], now, on_step_consumed=consumed)

    def rewrite(
        conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
    ) -> list[Outgoing] | None:
        values = _ints(args, 1)
        if values is None:
            return None
        return gate.start_rewrite(conn, user, values[0], now)

    def rewrite_text(
        conn: sqlite3.Connection, user: User, pending: PendingInput, u: Update, now: datetime
    ) -> list[Outgoing]:
        return gate.submit_rewrite(
            conn,
            user,
            u.text or u.caption or "",
            now,
            sender_name=ctx.sender_name,
            on_step_consumed=consumed,
            pending=pending,
        )

    # --- Envío fallido: Reintentar / Cancelar --------------------------------------------
    def _failed_send(
        conn: sqlite3.Connection, user: User, proposal_id: int, now: datetime
    ) -> list[Outgoing] | None:
        """None si puede decidir; si no, la denegación auditada. [] si la propuesta no existe."""
        proposal = repo.get_proposal(conn, proposal_id)
        if proposal is None:
            return []
        if gate.may_decide(user, proposal):
            return None
        repo.audit(
            conn,
            actor=f"user:{user.id}",
            action=AuditAction.PERMISSION_DENIED,
            outcome=AuditOutcome.DENIED,
            at=now,
            lead_id=proposal.lead_id,
        )
        return [Outgoing(user.telegram_id, gate.NO_PERMISSION)]

    def retry(
        conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
    ) -> list[Outgoing] | None:
        values = _ints(args, 1)
        if values is None:
            return None
        denied = _failed_send(conn, user, values[0], now)
        if denied is not None:
            return denied or None
        if not delivery.retry_failed(conn, values[0], now):
            return [Outgoing(user.telegram_id, gate.ALREADY_PROCESSED)]
        if ctx.kick_delivery is not None:
            ctx.kick_delivery()
        return [
            Outgoing(
                user.telegram_id,
                "Reintento programado con éxito: se enviará en el próximo ciclo de envíos.",
            )
        ]

    def cancel_failed(
        conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
    ) -> list[Outgoing] | None:
        values = _ints(args, 1)
        if values is None:
            return None
        denied = _failed_send(conn, user, values[0], now)
        if denied is not None:
            return denied or None
        send = repo.get_send_by_proposal(conn, values[0])
        if send is None or send.status != SendStatus.FAILED:
            return [Outgoing(user.telegram_id, gate.ALREADY_PROCESSED)]
        follow_up = delivery.cancel_failed(conn, values[0], now, on_step_consumed=consumed)
        return [Outgoing(user.telegram_id, "Envío cancelado."), *follow_up]

    # --- Autorización por correo ----------------------------------------------------------
    def auth_ok(
        conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
    ) -> list[Outgoing] | None:
        values = _ints(args, 1)
        return None if values is None else authreq.confirm(conn, user, values[0], now, ctx.keys)

    def auth_no(
        conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
    ) -> list[Outgoing] | None:
        values = _ints(args, 1)
        return None if values is None else authreq.decline(conn, user, values[0], now)

    def request_auth(
        conn: sqlite3.Connection, user: User, text: str, now: datetime
    ) -> list[Outgoing]:
        parts = text.split(maxsplit=1)
        lead_id = parse_short_id(parts[1]) if len(parts) == 2 else None
        if lead_id is None:
            return [
                Outgoing(
                    user.telegram_id,
                    f"Formato no válido: debes indicar el lead para pedir la autorización. "
                    f"Ejemplo: {EXAMPLE_REQUEST_AUTH}",
                )
            ]
        return authreq.request_authorization(
            conn, user, lead_id, now, ctx.keys, ctx.settings, ctx.sender_name
        )

    # --- Respuestas «por clasificar» ------------------------------------------------------
    def review_baja(
        conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
    ) -> list[Outgoing] | None:
        values = _ints(args, 1)
        if values is None:
            return None
        return replies.apply_review_baja(conn, user, values[0], now, ctx.keys)

    def review_options(
        conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
    ) -> list[Outgoing] | None:
        values = _ints(args, 1)
        return None if values is None else replies.classify_options(conn, user, values[0], now)

    def review_as(kind: RequestType) -> CallbackHandler:
        def handler(
            conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
        ) -> list[Outgoing] | None:
            values = _ints(args, 1)
            if values is None:
                return None
            return replies.classify_review(conn, user, values[0], kind, now, ctx.params)

        return handler

    def review_none(
        conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
    ) -> list[Outgoing] | None:
        values = _ints(args, 1)
        return None if values is None else replies.close_review(conn, user, values[0], now)

    # --- Cadencia desde la ficha o el aviso de cadencia completada -------------------------
    def lead_action(
        action: Callable[[sqlite3.Connection, User, int, datetime], list[Outgoing]],
    ) -> CallbackHandler:
        def handler(
            conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
        ) -> list[Outgoing] | None:
            values = _ints(args, 1)
            return None if values is None else action(conn, user, values[0], now)

        return handler

    def mark_lost(
        conn: sqlite3.Connection, user: User, lead_id: int, now: datetime
    ) -> list[Outgoing]:
        return leads.transition(conn, user, lead_id, LeadState.LOST, now)

    callbacks: dict[str, CallbackHandler] = {
        gate.APPROVE_CALLBACK: approve,
        gate.REJECT_CALLBACK: reject,
        gate.CANCEL_CALLBACK: cancel,
        gate.REWRITE_CALLBACK: rewrite,
        delivery.RETRY_CALLBACK: retry,
        delivery.CANCEL_CALLBACK: cancel_failed,
        replies.AUTH_OK_CALLBACK: auth_ok,
        replies.AUTH_NO_CALLBACK: auth_no,
        replies.BAJA_CALLBACK: review_baja,
        replies.CLASSIFY_CALLBACK: review_options,
        replies.CONSULT_CALLBACK: review_as(RequestType.INQUIRY),
        replies.CLAIM_CALLBACK: review_as(RequestType.CLAIM),
        replies.NO_REQUEST_CALLBACK: review_none,
        PAUSE_CALLBACK: lead_action(followup.pause),
        RESUME_CALLBACK: lead_action(followup.resume),
        WEEKLY_CALLBACK: lead_action(
            lambda conn, user, lead_id, now: followup.set_frequency(
                conn, user, lead_id, "weekly", now
            )
        ),
        MONTHLY_CALLBACK: lead_action(
            lambda conn, user, lead_id, now: followup.set_frequency(
                conn, user, lead_id, "monthly", now
            )
        ),
        LOST_CALLBACK: lead_action(mark_lost),
        REACTIVATE_CALLBACK: lead_action(followup.reactivate),
    }
    for action_name, handler in callbacks.items():
        bot.register_callback(action_name, handler)
    command: CommandHandler = request_auth
    bot.register_command(REQUEST_AUTH_COMMAND, command)
    bot.register_command("seguimiento", followup_view.following_command)
    bot.register_pending(gate.REWRITE_KIND, rewrite_text)


__all__ = [
    "EXAMPLE_REQUEST_AUTH",
    "LOST_CALLBACK",
    "MONTHLY_CALLBACK",
    "PAUSE_CALLBACK",
    "REACTIVATE_CALLBACK",
    "REQUEST_AUTH_COMMAND",
    "RESUME_CALLBACK",
    "WEEKLY_CALLBACK",
    "F2Context",
    "register_f2",
]
