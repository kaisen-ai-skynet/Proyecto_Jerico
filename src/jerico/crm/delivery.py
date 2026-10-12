"""Programación y entrega de mensajes al cliente final (F2-T15; plan-f2 §5.3 `guard` y §5.4).

Requisitos: VCRM-029, 036, 037, 038, 072, 076, 100 y 101.

Es el ÚLTIMO control antes de contactar al titular. Nada sale sin que, en el instante del envío:
- exista una aprobación ✅ cuyo contenido coincida exactamente con lo que se envía (hash, VCRM-036);
- el lead siga cumpliendo las condiciones de contacto (VCRM-037), re-evaluadas en CADA intento;
- se esté dentro de la franja legal y del cupo semanal (VCRM-072, 076), sin intentos fuera de ella;
- se respete el calendario de 3 intentos a los 0, 1 y 5 minutos (VCRM-038).

El envío por red se hace sin transacción abierta: (1) se prepara y reserva el intento, (2) se envía,
(3) se registra el resultado. Si el proceso muere entre (2) y (3) el intento ya consta como hecho y
el siguiente sigue el calendario: el riesgo es un duplicado puntual, nunca un envío sin registro.
"""

import hashlib
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from urllib.parse import quote

from jerico.crm import compliance, repo
from jerico.crm.config import Params
from jerico.crm.db import CrmDatabase
from jerico.crm.inbound import make_unsub_token
from jerico.crm.model import (
    Lead,
    LeadState,
    Outgoing,
    Proposal,
    ProposalKind,
    ProposalStatus,
    ProposalVersion,
    Send,
    SendStatus,
)
from jerico.crm.outbox import next_attempt_at
from jerico.crm.parsing import build_callback
from jerico.crm.permissions import commercial_recipients
from jerico.crm.ports import EmailSender
from jerico.crm.render import short_id
from jerico.crm.sendwindow import allowed, next_slot, schedule, week_start
from jerico.crm.timeutil import BOGOTA, format_local, from_iso, to_iso

WEEKLY_LIMIT = 1  # un contacto por lead y semana calendario (VCRM-076; tope legal, J-11)
RETRY_CALLBACK = "freint"
CANCEL_CALLBACK = "fcancel"
_WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")

StepHook = Callable[[sqlite3.Connection, int, str, datetime, datetime | None], list[Outgoing]]
Deferral = Literal["window", "weekly"]


@dataclass(frozen=True)
class Scheduled:
    send_id: int
    slot: datetime  # hora de Bogotá
    deferred_by: Deferral | None  # por qué no sale ahora; None = dentro de franja y de cupo


def content_hash(subject: str, body: str) -> str:
    """Huella de lo aprobado (VCRM-036). Se antepone la longitud del asunto para que dos pares
    distintos nunca den la misma huella aunque el asunto contenga saltos de línea."""
    raw_subject = subject.encode()
    digest = hashlib.sha256()
    digest.update(len(raw_subject).to_bytes(8, "big"))
    digest.update(raw_subject)
    digest.update(body.encode())
    return digest.hexdigest()


def guard(conn: sqlite3.Connection, lead: Lead, proposal: Proposal, keys: Sequence[str]) -> bool:
    """¿Sigue siendo lícito contactar? Seguimiento: «en nutrición», autorización vigente y sin
    bloqueos; solicitud de autorización: solo sin baja, bloqueo ni supresión (VCRM-037, 067)."""
    if proposal.kind == ProposalKind.AUTH_REQUEST:
        return compliance.may_request_authorization(conn, lead, keys)
    return lead.state == LeadState.NURTURING and compliance.may_contact_commercially(
        conn, lead, keys
    )


def deferral_text(scheduled: Scheduled) -> str:
    """Aviso al aprobador cuando el envío no sale ahora (VCRM-100, 101)."""
    slot = scheduled.slot.astimezone(BOGOTA)
    when = f"{_WEEKDAYS[slot.weekday()]} {format_local(slot)}"
    reason = (
        "por estar fuera de la franja permitida"
        if scheduled.deferred_by == "window"
        else "porque el lead ya alcanzó el límite de contactos de la semana"
    )
    return f"El envío quedó programado para el {when} (hora de Bogotá), {reason}."


def schedule_send(
    conn: sqlite3.Connection,
    *,
    proposal: Proposal,
    version: ProposalVersion,
    lead: Lead,
    approved_by: int,
    now: datetime,
    extra_holidays: frozenset[date] = frozenset(),
    weekly_limit: int = WEEKLY_LIMIT,
) -> Scheduled:
    """Registra el envío aprobado en el primer instante con franja y cupo libres (VCRM-100, 101)."""
    slot = schedule(
        now,
        lambda week: repo.count_sends_in_week(conn, lead.id, week),
        weekly_limit,
        extra_holidays,
    )
    first_open = next_slot(now, extra_holidays)
    deferred: Deferral | None = None
    if slot > first_open:
        deferred = "weekly"
    elif first_open > now:
        deferred = "window"
    send_id = repo.insert_send(
        conn,
        proposal_id=proposal.id,
        version=version.version,
        approved_hash=version.content_hash,
        approved_by=approved_by,
        approved_at=now,
        scheduled_at=slot,
        lead_id=lead.id,
        week_start=week_start(slot),
        next_attempt_at=slot,
    )
    repo.update_proposal(conn, proposal.id, status=ProposalStatus.APPROVED)
    return Scheduled(send_id, slot.astimezone(BOGOTA), deferred)


# --- Avisos ---------------------------------------------------------------------------------


def recipients(conn: sqlite3.Connection, proposal: Proposal, lead: Lead) -> list[int]:
    """Telegram del aprobador; si ya no está activo, el comercial del lead o el CTO."""
    approver = repo.get_user(conn, proposal.approver_user_id)
    if approver is not None and approver.active:
        return [approver.telegram_id]
    return [u.telegram_id for u in commercial_recipients(lead, repo.active_users(conn))]


def _notice(conn: sqlite3.Connection, proposal: Proposal, lead: Lead, text: str) -> list[Outgoing]:
    return [Outgoing(chat, text) for chat in recipients(conn, proposal, lead)]


def _failure_buttons(proposal_id: int) -> tuple[tuple[tuple[str, str], ...], ...]:
    return (
        (
            ("Reintentar", build_callback(RETRY_CALLBACK, str(proposal_id))),
            ("Cancelar", build_callback(CANCEL_CALLBACK, str(proposal_id))),
        ),
    )


def _failed_notice(
    conn: sqlite3.Connection, proposal: Proposal, lead: Lead, reason: str
) -> list[Outgoing]:
    text = (
        f"No se pudo enviar el mensaje de {short_id(lead.id)}: {reason}. "
        "La cadencia no avanza hasta que decida reintentar o cancelar."
    )
    return [
        Outgoing(chat, text, _failure_buttons(proposal.id))
        for chat in recipients(conn, proposal, lead)
    ]


# --- Entrega --------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Ready:
    send: Send
    proposal: Proposal
    lead: Lead
    to: str
    subject: str
    body: str


def _others_in_week(conn: sqlite3.Connection, send: Send, week: datetime) -> int:
    """Contactos del lead en esa semana sin contar este mismo envío (que ya figura programado)."""
    own = 1 if send.week_start == to_iso(week) else 0
    return repo.count_sends_in_week(conn, send.lead_id, week) - own


def _prepare(
    conn: sqlite3.Connection,
    send_id: int,
    now: datetime,
    keys: Sequence[str],
    extra: frozenset[date],
) -> _Ready | list[Outgoing]:
    """Decide qué hacer con un envío vencido. Devuelve el intento listo o los avisos si terminó."""
    send = repo.get_send(conn, send_id)
    if send is None or send.status != SendStatus.SCHEDULED:
        return []
    proposal = repo.get_proposal(conn, send.proposal_id)
    lead = repo.get_lead(conn, send.lead_id)
    version = repo.get_proposal_version(conn, send.proposal_id, send.version)
    if proposal is None or lead is None or version is None:
        repo.update_send(conn, send.id, status=SendStatus.FAILED, last_error="missing_data")
        return []
    if proposal.status != ProposalStatus.APPROVED:  # se canceló, pausó o expiró tras el ✅
        repo.update_send(conn, send.id, status=SendStatus.CANCELLED)
        return []
    if not allowed(now, extra):  # sin intentos fuera de franja (VCRM-072)
        repo.update_send(conn, send.id, next_attempt_at=next_slot(now, extra))
        return []
    week = week_start(now)
    if send.attempts == 0 and _others_in_week(conn, send, week) >= WEEKLY_LIMIT:
        slot = schedule(now, lambda w: _others_in_week(conn, send, w), WEEKLY_LIMIT, extra)
        repo.update_send(
            conn,
            send.id,
            scheduled_at=slot,
            next_attempt_at=slot,
            week_start=week_start(slot),
        )
        return []
    if not guard(conn, lead, proposal, keys):  # en CADA intento (VCRM-037)
        repo.update_send(conn, send.id, status=SendStatus.CANCELLED)
        repo.update_proposal(conn, proposal.id, status=ProposalStatus.BLOCKED, resolved_at=now)
        return _notice(
            conn,
            proposal,
            lead,
            f"Envío cancelado por estado: {short_id(lead.id)} ya no cumple las condiciones "
            "para contactarlo (en nutrición, autorización vigente y sin supresión).",
        )
    if content_hash(version.subject, version.body) != send.approved_hash:  # VCRM-036
        return _fail(
            conn,
            send,
            proposal,
            lead,
            now,
            "content_mismatch",
            "el texto no coincide con el que se aprobó; por seguridad no se envió",
        )
    if not lead.email:
        return _fail(
            conn, send, proposal, lead, now, "no_email", "el lead no tiene correo registrado"
        )
    repo.update_send(
        conn,
        send.id,
        attempts=send.attempts + 1,
        first_attempt_at=send.first_attempt_at or now,
        next_attempt_at=None,
    )
    return _Ready(send, proposal, lead, lead.email, version.subject, version.body)


def _fail(
    conn: sqlite3.Connection,
    send: Send,
    proposal: Proposal,
    lead: Lead,
    now: datetime,
    code: str,
    reason: str,
) -> list[Outgoing]:
    repo.update_send(conn, send.id, status=SendStatus.FAILED, last_error=code, next_attempt_at=None)
    repo.update_proposal(conn, proposal.id, status=ProposalStatus.FAILED, resolved_at=now)
    return _failed_notice(conn, proposal, lead, reason)


def _record(
    conn: sqlite3.Connection,
    ready: _Ready,
    result_ok: bool,
    message_id: str | None,
    error: str | None,
    permanent: bool,
    now: datetime,
    extra: frozenset[date],
    hook: StepHook | None,
) -> list[Outgoing]:
    send = repo.get_send(conn, ready.send.id) or ready.send
    proposal, lead = ready.proposal, ready.lead
    if result_ok:
        repo.update_send(
            conn,
            send.id,
            status=SendStatus.SENT,
            rfc_message_id=message_id,
            sent_at=now,
            last_error=None,
        )
        repo.update_proposal(conn, proposal.id, status=ProposalStatus.SENT, resolved_at=now)
        out: list[Outgoing] = []
        if proposal.kind == ProposalKind.FOLLOWUP and hook is not None:
            out += hook(conn, lead.id, "sent", now, now)
        what = (
            "Solicitud de autorización"
            if proposal.kind == ProposalKind.AUTH_REQUEST
            else "Seguimiento"
        )
        out += _notice(conn, proposal, lead, f"{what} enviado: {short_id(lead.id)}.")
        return out
    first = from_iso(send.first_attempt_at) if send.first_attempt_at else now
    following = next_attempt_at(first, send.attempts)
    if permanent:
        reason = "el canal de correo no está disponible o no está configurado"
    elif following is None:
        reason = f"falló tras {send.attempts} intentos"
    elif not allowed(following, extra):
        reason = "el siguiente intento caería fuera de la franja permitida"
    else:
        repo.update_send(conn, send.id, next_attempt_at=following, last_error=error)
        return []
    repo.update_send(
        conn, send.id, status=SendStatus.FAILED, last_error=error, next_attempt_at=None
    )
    repo.update_proposal(conn, proposal.id, status=ProposalStatus.FAILED, resolved_at=now)
    return _failed_notice(conn, proposal, lead, reason)


async def deliver_due(
    db: CrmDatabase,
    email: EmailSender,
    now: datetime,
    params: Params,
    keys: Sequence[str],
    *,
    unsub_address: str,
    on_step_consumed: StepHook | None = None,
) -> list[Outgoing]:
    """Entrega los envíos vencidos; devuelve los avisos para el aprobador (VCRM-029, 036..038)."""
    extra = params.extra_holidays
    with db.read() as conn:
        due = [s.id for s in repo.due_sends(conn, now)]
    notices: list[Outgoing] = []
    for send_id in due:
        with db.tx() as tx:
            prepared = _prepare(tx, send_id, now, keys, extra)
        if not isinstance(prepared, _Ready):
            notices += prepared
            continue
        token = make_unsub_token(prepared.send.id, keys[0])
        headers = {
            "List-Unsubscribe": f"<mailto:{unsub_address}?subject={quote('BAJA ' + token)}>",
            "Auto-Submitted": "no",
        }
        result = await email.send(prepared.to, prepared.subject, prepared.body, headers)
        with db.tx() as tx:
            notices += _record(
                tx,
                prepared,
                bool(result.delivered and result.message_id),
                result.message_id,
                result.error,
                result.permanent,
                now,
                extra,
                on_step_consumed,
            )
    return notices


def retry_failed(conn: sqlite3.Connection, proposal_id: int, now: datetime) -> bool:
    """«Reintentar»: nuevo calendario de 3 intentos desde ahora; solo sobre un envío fallido."""
    send = repo.get_send_by_proposal(conn, proposal_id)
    proposal = repo.get_proposal(conn, proposal_id)
    if (
        send is None
        or proposal is None
        or send.status != SendStatus.FAILED
        or proposal.status != ProposalStatus.FAILED
    ):
        return False
    repo.update_send(
        conn,
        send.id,
        status=SendStatus.SCHEDULED,
        attempts=0,
        first_attempt_at=None,
        next_attempt_at=now,
        last_error=None,
    )
    repo.update_proposal(conn, proposal_id, status=ProposalStatus.APPROVED, resolved_at=None)
    return True


def cancel_failed(
    conn: sqlite3.Connection,
    proposal_id: int,
    now: datetime,
    *,
    on_step_consumed: StepHook | None,
) -> list[Outgoing]:
    """«Cancelar» un envío fallido: consume el paso de la cadencia (VCRM-038, 032)."""
    send = repo.get_send_by_proposal(conn, proposal_id)
    proposal = repo.get_proposal(conn, proposal_id)
    if (
        send is None
        or proposal is None
        or send.status != SendStatus.FAILED
        or proposal.status != ProposalStatus.FAILED
    ):
        return []
    repo.update_send(conn, send.id, status=SendStatus.CANCELLED)
    repo.update_proposal(conn, proposal_id, status=ProposalStatus.CANCELLED, resolved_at=now)
    if proposal.kind == ProposalKind.FOLLOWUP and on_step_consumed is not None:
        return on_step_consumed(conn, proposal.lead_id, "cancelled", now, None)
    return []


__all__ = [
    "CANCEL_CALLBACK",
    "RETRY_CALLBACK",
    "WEEKLY_LIMIT",
    "Scheduled",
    "StepHook",
    "cancel_failed",
    "content_hash",
    "deferral_text",
    "deliver_due",
    "guard",
    "retry_failed",
    "schedule_send",
]
