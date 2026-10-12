"""Barrido diario del CRM (plan §8.4): idempotente; se ejecuta al arrancar y por cron.

Cubre J-14 (VCRM-158, 159), conservación y supresión por estado final (VCRM-145, 146, 147)
y las solicitudes de titulares (VCRM-151, 152).
"""

import sqlite3
from collections.abc import Sequence
from datetime import date, datetime, timedelta

from jerico.crm import repo
from jerico.crm.compliance import SuppressionFailed, execute_suppression, request_notice
from jerico.crm.config import Params
from jerico.crm.db import CrmDatabase
from jerico.crm.model import (
    AlertKind,
    AuditAction,
    AuditDetail,
    AuditOutcome,
    AuthStatus,
    Lead,
    LeadState,
    Outgoing,
    RequestStatus,
    Role,
    User,
)
from jerico.crm.permissions import commercial_recipients
from jerico.crm.ports import FileStore, TelegramPort
from jerico.crm.render import short_id
from jerico.crm.timeutil import (
    add_business_days,
    add_months,
    add_years,
    format_local,
    from_iso,
    is_business_day,
    local_date,
)

NOTICE_KIND = "aviso_solicitud"
TERM_CAUSE = AuditDetail.VENCIMIENTO_PLAZO.value
_CLOCK_STOPPED = frozenset({LeadState.ACCEPTED, LeadState.WON})
_FINAL_STATES = frozenset({LeadState.LOST, LeadState.OPTED_OUT})


class _Ctx:
    """Datos comunes de un barrido de conservación."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        now: datetime,
        params: Params,
        store: FileStore | None,
        keys: Sequence[str],
    ) -> None:
        self.conn, self.now, self.params, self.store, self.keys = conn, now, params, store, keys
        self.users = repo.active_users(conn)
        self.ctos = [u for u in self.users if u.role == Role.CTO]
        self.today = local_date(now).isoformat()

    def send(self, users: Sequence[User], text: str) -> list[Outgoing]:
        seen: dict[int, User] = {u.id: u for u in users}
        return [Outgoing(u.telegram_id, text) for u in seen.values()]

    def failure(self, lead: Lead, kind: str, cause: str) -> list[Outgoing]:
        """VCRM-147: aviso al CTO (una vez por día y tipo); el barrido siguiente reintenta."""
        if not repo.add_retention_notice(self.conn, lead.id, self.today, kind, now=self.now):
            return []
        text = (
            f"Falló la supresión o eliminación por vencimiento de plazo del lead "
            f"{short_id(lead.id)}. Causa: {cause}. Se reintentará en el próximo barrido diario."
        )
        return self.send(self.ctos, text)


def _suppress(ctx: _Ctx, lead: Lead, *, add_fingerprint: bool, keep_won: bool) -> bool | str:
    try:
        execute_suppression(
            ctx.conn,
            ctx.store,
            [lead],
            cause=TERM_CAUSE,
            now=ctx.now,
            actor="system",
            keys=ctx.keys,
            add_fingerprint=add_fingerprint,
            keep_attachments_of_won=keep_won,
        )
    except (SuppressionFailed, ValueError) as exc:
        return str(exc)
    return True


def _sweep_unauthorized(ctx: _Ctx, lead: Lead) -> list[Outgoing] | None:
    """J-14 (VCRM-158, 159); None si el lead no está sujeto al reloj."""
    if lead.state in _CLOCK_STOPPED or lead.auth_status != AuthStatus.UNAUTHORIZED:
        return None
    start = from_iso(lead.registered_at)
    if lead.accepted_exit_at is not None:
        start = max(start, from_iso(lead.accepted_exit_at))
    deadline = start + timedelta(days=ctx.params.unauthorized_max_days)
    sid = short_id(lead.id)
    if ctx.now >= deadline:
        result = _suppress(ctx, lead, add_fingerprint=False, keep_won=False)
        if result is not True:
            return ctx.failure(lead, "fail", str(result))
        text = (
            f"El lead {sid} se suprimió por vencimiento del plazo: "
            f"{ctx.params.unauthorized_max_days} días sin autorización de datos."
        )
        return ctx.send([*commercial_recipients(lead, ctx.users), *ctx.ctos], text)
    warn_at = start + timedelta(days=ctx.params.unauthorized_warning_days)
    if ctx.now >= warn_at and repo.add_retention_notice(
        ctx.conn, lead.id, lead.accepted_exit_at or lead.registered_at, "warn", now=ctx.now
    ):
        text = (
            f"El lead {sid} ({lead.name}) sigue sin autorización de datos. "
            f"Se suprimirá el {format_local(deadline)[:10]} si no se registra la autorización."
        )
        return ctx.send(commercial_recipients(lead, ctx.users), text)
    return []


def _sweep_final_state(ctx: _Ctx, lead: Lead) -> list[Outgoing]:
    """VCRM-146 (con VCRM-145 prevaleciendo sobre los adjuntos de ganado)."""
    if lead.state not in _FINAL_STATES or lead.final_state_at is None:
        return []
    if ctx.now < add_months(
        from_iso(lead.final_state_at), ctx.params.final_state_suppression_months
    ):
        return []
    keep_won = lead.won_at is not None and ctx.now < add_years(
        from_iso(lead.won_at), ctx.params.won_attachments_retention_years
    )
    result = _suppress(
        ctx, lead, add_fingerprint=lead.state == LeadState.OPTED_OUT, keep_won=keep_won
    )
    return [] if result is True else ctx.failure(lead, "fail", str(result))


def _expire_attachments(ctx: _Ctx, lead: Lead) -> list[Outgoing]:
    """VCRM-145: adjuntos de ganado eliminados a los N años (salvo la evidencia, VCRM-164)."""
    if lead.won_at is None or ctx.now < add_years(
        from_iso(lead.won_at), ctx.params.won_attachments_retention_years
    ):
        return []
    for attachment in repo.lead_attachments(ctx.conn, lead.id):
        if attachment.kind == "authorization":
            continue
        try:
            if ctx.store is None:
                raise SuppressionFailed("no file store configured")
            ctx.store.delete(attachment.storage_key)
        except Exception as exc:  # noqa: BLE001 - cualquier fallo se avisa y se reintenta
            return ctx.failure(lead, "fail_att", str(exc))
        repo.mark_attachment_deleted(ctx.conn, attachment.id, now=ctx.now)
        repo.audit(
            ctx.conn,
            actor="system",
            action=AuditAction.ATTACHMENT_EXPIRED,
            outcome=AuditOutcome.OK,
            at=ctx.now,
            lead_id=lead.id,
        )
    return []


def sweep_retention(
    conn: sqlite3.Connection,
    now: datetime,
    params: Params,
    store: FileStore | None,
    keys: Sequence[str],
) -> list[Outgoing]:
    """J-14 y conservación (VCRM-145–147, 158, 159); idempotente."""
    ctx = _Ctx(conn, now, params, store, keys)
    out: list[Outgoing] = []
    for lead in repo.all_leads(conn):
        if lead.suppressed_at is None:
            # J-14 (≤ 30 días) vence siempre antes que el plazo de estado final (12 meses).
            j14 = _sweep_unauthorized(ctx, lead)
            out += _sweep_final_state(ctx, lead) if j14 is None else j14
        out += _expire_attachments(ctx, lead)
    return out


def sweep_requests(conn: sqlite3.Connection, now: datetime, params: Params) -> list[Outgoing]:
    """Vencimiento (152) y escalado diario al CTO (151); no repite en el mismo día."""
    today = local_date(now)
    extra = params.extra_holidays
    ctos = repo.active_users(conn, Role.CTO)
    out: list[Outgoing] = []
    for req in repo.titular_requests(conn, (RequestStatus.OPEN, RequestStatus.OVERDUE)):
        if req.status == RequestStatus.OPEN and today >= date.fromisoformat(req.due_on):
            repo.update_titular_request(conn, req.id, {"status": RequestStatus.OVERDUE.value})
            repo.create_alert(
                conn,
                kind=AlertKind.REQUEST_OVERDUE,
                now=now,
                lead_id=req.lead_id,
                request_id=req.id,
            )
            req = repo.get_titular_request(conn, req.id) or req
        received = date.fromisoformat(req.received_on)
        escalate_from = add_business_days(received, params.escalation_business_days, extra)
        if (
            is_business_day(today, extra)
            and today >= escalate_from
            and req.last_escalation_on != today.isoformat()
        ):
            repo.update_titular_request(conn, req.id, {"last_escalation_on": today.isoformat()})
            text = request_notice(req, today, params)
            out += [Outgoing(cto.telegram_id, text) for cto in ctos]
    return out


async def daily_sweep(
    db: CrmDatabase,
    telegram: TelegramPort,
    now: datetime,
    params: Params,
    *,
    store: FileStore | None = None,
    keys: Sequence[str] = (),
) -> None:
    """Aplica el barrido en una transacción y envía los avisos no críticos (VCRM-012)."""
    with db.tx() as tx:
        out = sweep_retention(tx, now, params, store, keys)
        out += sweep_requests(tx, now, params)
    for item in out:
        result = await telegram.send_message(item.chat_id, item.text, None)
        if result.delivered:
            continue
        with db.tx() as tx:
            recipient = repo.active_user_by_telegram(tx, item.chat_id)
            if recipient is not None:
                repo.record_failed_noncritical(
                    tx,
                    recipient_user_id=recipient.id,
                    kind=NOTICE_KIND,
                    error=result.error,
                    now=now,
                )


__all__ = ["NOTICE_KIND", "TERM_CAUSE", "daily_sweep", "sweep_requests", "sweep_retention"]
