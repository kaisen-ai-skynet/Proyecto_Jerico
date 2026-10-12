"""Gate ✅/❌ antes de cada mensaje al cliente final (F2-T14; P-09, OBJ-2; plan-f2 §5.3, D-6..D-8).

Ningún mensaje al titular sale sin que el aprobador pulse ✅ sobre una versión concreta del texto
(VCRM-036). Aquí viven las decisiones del aprobador: aprobar, rechazar, cancelar, reescribir y la
expiración a las 48 h. El envío en sí (franja, cupo, reintentos, hash) lo hace `delivery`.

Las funciones reciben `conn` dentro de una transacción del llamador y devuelven los `Outgoing` a
enviar después de confirmarla. Quién puede decidir: el aprobador asignado a la propuesta (el
comercial del lead o, si no hay, el CTO) y siempre el CTO (decisión P-16); nadie más (VCRM-035).
"""

import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from jerico.crm import delivery, repo
from jerico.crm.followup_text import footer
from jerico.crm.model import (
    AuditAction,
    AuditOutcome,
    Lead,
    Outgoing,
    PendingInput,
    Proposal,
    ProposalKind,
    ProposalStatus,
    Role,
    User,
)
from jerico.crm.parsing import build_callback
from jerico.crm.render import short_id, split_message
from jerico.crm.timeutil import format_local, from_iso

GATE_DEADLINE = timedelta(hours=48)  # plazo del gate (4.6, decisión P-17)
MAX_REWRITE_CHARS = 3000
REWRITE_KIND = "rewrite"
APPROVE_CALLBACK = "gok"
REJECT_CALLBACK = "gno"
CANCEL_CALLBACK = "gcan"
REWRITE_CALLBACK = "grew"

ALREADY_PROCESSED = "Esta propuesta ya fue procesada."
NO_PERMISSION = "No tiene permiso para decidir sobre esta propuesta."


@dataclass(frozen=True)
class GateOutcome:
    out: list[Outgoing]
    deliver_now: bool = False  # el llamador debe intentar el envío ya (dentro de franja y cupo)


def _text(user: User, text: str) -> list[Outgoing]:
    return [Outgoing(user.telegram_id, text)]


def _label(proposal: Proposal) -> str:
    return (
        "Solicitud de autorización" if proposal.kind == ProposalKind.AUTH_REQUEST else "Seguimiento"
    )


def _audit(
    conn: sqlite3.Connection, actor: User, proposal: Proposal, now: datetime, action: AuditAction
) -> None:
    repo.audit(
        conn,
        actor=f"user:{actor.id}",
        action=action,
        outcome=AuditOutcome.DENIED if action == AuditAction.PERMISSION_DENIED else AuditOutcome.OK,
        at=now,
        lead_id=proposal.lead_id,
    )


def may_decide(actor: User, proposal: Proposal) -> bool:
    """¿Puede esta persona decidir sobre la propuesta? Su aprobador y, siempre, el CTO."""
    if not actor.active or actor.role == Role.LAWYER:
        return False
    return actor.role == Role.CTO or actor.id == proposal.approver_user_id


def _load(
    conn: sqlite3.Connection, actor: User, proposal_id: int, now: datetime
) -> tuple[Proposal, Lead] | list[Outgoing]:
    """Propuesta y lead si el actor puede decidir; si no, la respuesta que corresponde."""
    proposal = repo.get_proposal(conn, proposal_id)
    if proposal is None:
        return _text(actor, f"La propuesta {proposal_id} no existe.")
    if not may_decide(actor, proposal):
        _audit(conn, actor, proposal, now, AuditAction.PERMISSION_DENIED)
        return _text(actor, NO_PERMISSION)
    lead = repo.get_lead(conn, proposal.lead_id)
    if lead is None:  # pragma: no cover - la clave foránea lo impide
        return _text(actor, f"La propuesta {proposal_id} no existe.")
    return proposal, lead


def _closed_reply(actor: User, proposal: Proposal) -> list[Outgoing] | None:
    """Respuesta si la propuesta ya no admite decisiones (VCRM-030, 034); None si sigue abierta."""
    if proposal.status == ProposalStatus.EXPIRED:
        return _text(actor, "La propuesta expiró y no se envió. No se puede aprobar ya.")
    if proposal.status != ProposalStatus.PENDING:
        return _text(actor, ALREADY_PROCESSED)
    return None


def _expire(
    conn: sqlite3.Connection,
    proposal: Proposal,
    lead: Lead,
    now: datetime,
    on_step_consumed: delivery.StepHook | None,
) -> list[Outgoing]:
    repo.update_proposal(conn, proposal.id, status=ProposalStatus.EXPIRED, resolved_at=now)
    text = (
        f"{_label(proposal)} de {short_id(lead.id)} expiró sin respuesta y no se envió "
        "(el gate dura 48 horas)."
    )
    out = [Outgoing(chat, text) for chat in delivery.recipients(conn, proposal, lead)]
    if proposal.kind == ProposalKind.FOLLOWUP and on_step_consumed is not None:
        out += on_step_consumed(conn, lead.id, "expired", now, None)
    return out


def _is_due(proposal: Proposal, now: datetime) -> bool:
    return from_iso(proposal.expires_at) <= now


def present(conn: sqlite3.Connection, proposal_id: int) -> list[Outgoing]:
    """Mensaje al aprobador con el texto EXACTO de la versión vigente y los botones ✅/❌."""
    proposal = repo.get_proposal(conn, proposal_id)
    if proposal is None:
        return []
    lead = repo.get_lead(conn, proposal.lead_id)
    version = repo.get_proposal_version(conn, proposal_id, proposal.current_version)
    if lead is None or version is None:  # pragma: no cover - integridad referencial
        return []
    step = f", paso {proposal.step}" if proposal.step is not None else ""
    head = (
        f"{_label(proposal)} para {short_id(lead.id)}{step} · versión {version.version}\n"
        f"Vence: {format_local(from_iso(proposal.expires_at))}\n\n"
        f"Asunto: {version.subject}\n\n"
    )
    buttons = (
        (
            ("✅", build_callback(APPROVE_CALLBACK, str(proposal_id), str(version.version))),
            ("❌", build_callback(REJECT_CALLBACK, str(proposal_id), str(version.version))),
        ),
    )
    pieces = split_message(head + version.body)
    chats = delivery.recipients(conn, proposal, lead)
    out: list[Outgoing] = []
    for chat in chats:
        for i, piece in enumerate(pieces):
            last = i == len(pieces) - 1
            out.append(Outgoing(chat, piece, buttons if last else ()))
    return out


def approve(
    conn: sqlite3.Connection,
    actor: User,
    proposal_id: int,
    version: int,
    now: datetime,
    keys: tuple[str, ...] | list[str],
    *,
    extra_holidays: frozenset[date] = frozenset(),
    on_step_consumed: delivery.StepHook | None = None,
) -> GateOutcome:
    """✅ sobre la versión `version`: programa el envío (franja y cupo) si todo sigue vigente."""
    loaded = _load(conn, actor, proposal_id, now)
    if isinstance(loaded, list):
        return GateOutcome(loaded)
    proposal, lead = loaded
    closed = _closed_reply(actor, proposal)
    if closed is not None:
        return GateOutcome(closed)
    if _is_due(proposal, now):  # ✅ tardío: no revive la propuesta (D-7)
        _expire(conn, proposal, lead, now, on_step_consumed)
        return GateOutcome(
            _text(actor, "La propuesta expiró y no se envió. No se puede aprobar ya.")
        )
    if version != proposal.current_version:  # VCRM-099
        return GateOutcome(
            _text(
                actor,
                f"Esa versión fue reemplazada por una reescritura (versión vigente: "
                f"{proposal.current_version}). Revise la nueva y apruébela.",
            )
        )
    current = repo.get_proposal_version(conn, proposal_id, proposal.current_version)
    if current is None:  # pragma: no cover - integridad referencial
        return GateOutcome(_text(actor, ALREADY_PROCESSED))
    if not delivery.guard(conn, lead, proposal, keys):
        repo.update_proposal(
            conn, proposal_id, status=ProposalStatus.BLOCKED, resolved_at=now, resolved_by=actor.id
        )
        text = (
            f"Envío cancelado por estado: {short_id(lead.id)} ya no cumple las condiciones "
            "para contactarlo."
        )
        return GateOutcome(_text(actor, text))
    scheduled = delivery.schedule_send(
        conn,
        proposal=proposal,
        version=current,
        lead=lead,
        approved_by=actor.id,
        now=now,
        extra_holidays=extra_holidays,
    )
    repo.update_proposal(conn, proposal_id, resolved_by=actor.id)
    _audit(conn, actor, proposal, now, AuditAction.LEAD_UPDATED)
    if scheduled.deferred_by is None:
        return GateOutcome(_text(actor, "Aprobado. Se envía ahora."), deliver_now=True)
    return GateOutcome(_text(actor, f"Aprobado. {delivery.deferral_text(scheduled)}"))


def reject(
    conn: sqlite3.Connection,
    actor: User,
    proposal_id: int,
    version: int,
    now: datetime,
    *,
    on_step_consumed: delivery.StepHook | None = None,
) -> list[Outgoing]:
    """❌: no resuelve nada todavía; ofrece «Cancelar envío» y, si procede, «Reescribir»."""
    loaded = _load(conn, actor, proposal_id, now)
    if isinstance(loaded, list):
        return loaded
    proposal, lead = loaded
    closed = _closed_reply(actor, proposal)
    if closed is not None:
        return closed
    if _is_due(proposal, now):
        _expire(conn, proposal, lead, now, on_step_consumed)
        return _text(actor, "La propuesta expiró y no se envió.")
    if version != proposal.current_version:
        return _text(
            actor,
            f"Esa versión fue reemplazada (versión vigente: {proposal.current_version}).",
        )
    options = [("Cancelar envío", build_callback(CANCEL_CALLBACK, str(proposal_id)))]
    if proposal.kind == ProposalKind.FOLLOWUP:  # el texto de una solicitud de autorización es legal
        options.append(("Reescribir", build_callback(REWRITE_CALLBACK, str(proposal_id))))
    return [Outgoing(actor.telegram_id, "¿Qué desea hacer con el mensaje?", (tuple(options),))]


def cancel(
    conn: sqlite3.Connection,
    actor: User,
    proposal_id: int,
    now: datetime,
    *,
    on_step_consumed: delivery.StepHook | None,
) -> list[Outgoing]:
    """«Cancelar envío»: no se envía y la cadencia salta al paso siguiente (VCRM-032)."""
    loaded = _load(conn, actor, proposal_id, now)
    if isinstance(loaded, list):
        return loaded
    proposal, lead = loaded
    closed = _closed_reply(actor, proposal)
    if closed is not None:
        return closed
    repo.update_proposal(
        conn, proposal_id, status=ProposalStatus.CANCELLED, resolved_at=now, resolved_by=actor.id
    )
    _audit(conn, actor, proposal, now, AuditAction.LEAD_UPDATED)
    out = _text(actor, f"Envío cancelado: {_label(proposal).lower()} de {short_id(lead.id)}.")
    if proposal.kind == ProposalKind.FOLLOWUP and on_step_consumed is not None:
        out += on_step_consumed(conn, lead.id, "cancelled", now, None)
    return out


def start_rewrite(
    conn: sqlite3.Connection, actor: User, proposal_id: int, now: datetime
) -> list[Outgoing]:
    """«Reescribir»: el siguiente mensaje de texto del aprobador será la nueva versión."""
    loaded = _load(conn, actor, proposal_id, now)
    if isinstance(loaded, list):
        return loaded
    proposal, _lead = loaded
    closed = _closed_reply(actor, proposal)
    if closed is not None:
        return closed
    if proposal.kind != ProposalKind.FOLLOWUP:
        return _text(actor, "El texto de una solicitud de autorización no se puede reescribir.")
    repo.set_pending_input(
        conn,
        user_id=actor.id,
        kind=REWRITE_KIND,
        now=now,
        lead_id=proposal.lead_id,
        data=str(proposal_id),
    )
    return _text(
        actor,
        f"Envíe ahora el texto nuevo del mensaje (hasta {MAX_REWRITE_CHARS} caracteres). "
        "El pie con la opción de baja se añade solo.",
    )


def _clean(text: str) -> str:
    kept = "".join(
        c
        for c in text.replace("\r\n", "\n").replace("\r", "\n")
        if c in "\n\t" or unicodedata.category(c) not in ("Cc", "Cf")
    )
    return kept.strip()


def submit_rewrite(
    conn: sqlite3.Connection,
    actor: User,
    text: str,
    now: datetime,
    *,
    sender_name: str,
    on_step_consumed: delivery.StepHook | None = None,
    pending: PendingInput | None = None,
) -> list[Outgoing]:
    """Texto recibido tras «Reescribir»: nueva versión, plazo reiniciado y a ✅/❌ otra vez.

    `pending` es la entrada que el bot ya consumió; si no se pasa se busca en la base. Devuelve
    `[]` si el actor no tenía una reescritura pendiente (el texto no es para el gate).
    """
    pending = pending or repo.get_pending_input(conn, actor.id, now)
    if pending is None or pending.kind != REWRITE_KIND or pending.data is None:
        return []
    loaded = _load(conn, actor, int(pending.data), now)
    if isinstance(loaded, list):
        repo.clear_pending_input(conn, actor.id)
        return loaded
    proposal, lead = loaded
    closed = _closed_reply(actor, proposal)
    if closed is not None:
        repo.clear_pending_input(conn, actor.id)
        return closed
    if _is_due(proposal, now):
        repo.clear_pending_input(conn, actor.id)
        _expire(conn, proposal, lead, now, on_step_consumed)
        return _text(actor, "La propuesta expiró y no se envió.")
    cleaned = _clean(text)
    if not cleaned or len(cleaned) > MAX_REWRITE_CHARS:
        repo.set_pending_input(  # sigue esperando el texto (el bot ya había borrado la entrada)
            conn,
            user_id=actor.id,
            kind=REWRITE_KIND,
            now=now,
            lead_id=pending.lead_id,
            data=pending.data,
        )
        return _text(
            actor,
            f"Texto no válido: debe tener entre 1 y {MAX_REWRITE_CHARS} caracteres. "
            "Envíelo de nuevo.",
        )
    previous = repo.get_proposal_version(conn, proposal.id, proposal.current_version)
    if previous is None:  # pragma: no cover - integridad referencial
        repo.clear_pending_input(conn, actor.id)
        return _text(actor, ALREADY_PROCESSED)
    body = f"{cleaned}\n\n{footer(sender_name)}"
    number = proposal.current_version + 1
    repo.add_proposal_version(
        conn,
        proposal_id=proposal.id,
        version=number,
        subject=previous.subject,
        body=body,
        content_hash=delivery.content_hash(previous.subject, body),
        author_user_id=actor.id,
        created_at=now,
    )
    repo.update_proposal(conn, proposal.id, current_version=number, expires_at=now + GATE_DEADLINE)
    repo.clear_pending_input(conn, actor.id)
    _audit(conn, actor, proposal, now, AuditAction.LEAD_UPDATED)
    return present(conn, proposal.id)


def expire_due(
    conn: sqlite3.Connection, now: datetime, *, on_step_consumed: delivery.StepHook | None
) -> list[Outgoing]:
    """Expira las propuestas sin respuesta pasado el plazo; el seguimiento consume su paso (D-7)."""
    out: list[Outgoing] = []
    for proposal in repo.pending_proposals(conn, now):
        lead = repo.get_lead(conn, proposal.lead_id)
        if lead is not None:
            out += _expire(conn, proposal, lead, now, on_step_consumed)
    return out


__all__ = [
    "ALREADY_PROCESSED",
    "APPROVE_CALLBACK",
    "CANCEL_CALLBACK",
    "GATE_DEADLINE",
    "NO_PERMISSION",
    "REJECT_CALLBACK",
    "REWRITE_CALLBACK",
    "REWRITE_KIND",
    "GateOutcome",
    "approve",
    "cancel",
    "may_decide",
    "expire_due",
    "present",
    "reject",
    "start_rewrite",
    "submit_rewrite",
]
