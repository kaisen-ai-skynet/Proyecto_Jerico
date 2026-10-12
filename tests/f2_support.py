"""Datos de prueba compartidos por los tests de la fase 2 (leads, propuestas, calendario)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from jerico.crm import delivery, repo
from jerico.crm.db import CrmDatabase
from jerico.crm.model import AuthStatus, LeadState, ProposalKind, User
from jerico.crm.ports import InboundMessage
from jerico.crm.sendwindow import week_start
from jerico.crm.timeutil import BOGOTA

KEYS = ("clave-huella-no-real",)
UNSUB_ADDR = "buzon@kaisen.test"
CTO_TG, COM_TG = 1000, 2000
EMAIL = "ana@cliente.test"
SUBJECT = "Retomo nuestra conversación"
BODY = "Hola Ana,\n\nMe interesa retomar.\n\nKaisen AI\nResponda BAJA para no recibir más mensajes."
# Miércoles 14/10/2026 10:00 en Bogotá (15:00 UTC); el lunes 12 es festivo.
NOW = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)


def bog(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=BOGOTA)


def make_lead(
    db: CrmDatabase, user: User, *, state: LeadState = LeadState.NURTURING, **fields: Any
) -> int:
    base = {"name": "Ana Pérez", "phone_e164": "+573001112233", "email": EMAIL}
    base.update(fields)
    with db.tx() as tx:
        lead_id = repo.insert_lead(tx, assigned_user_id=user.id, state=state, now=NOW, fields=base)
        repo.update_lead(tx, lead_id, {"auth_status": "authorized"}, now=NOW)
        repo.insert_consent(
            tx,
            lead_id=lead_id,
            status=AuthStatus.AUTHORIZED,
            medium="correo",
            at=NOW,
            actor_user_id=user.id,
        )
    return lead_id


def make_proposal(
    db: CrmDatabase,
    lead_id: int,
    approver: User,
    *,
    kind: ProposalKind = ProposalKind.FOLLOWUP,
    step: int | None = 1,
    subject: str = SUBJECT,
    body: str = BODY,
) -> int:
    with db.tx() as tx:
        proposal_id = repo.insert_proposal(
            tx,
            lead_id=lead_id,
            kind=kind,
            step=step,
            approver_user_id=approver.id,
            expires_at=NOW + timedelta(hours=48),
            created_at=NOW,
        )
        assert proposal_id is not None
        repo.add_proposal_version(
            tx,
            proposal_id=proposal_id,
            version=1,
            subject=subject,
            body=body,
            content_hash=delivery.content_hash(subject, body),
            author_user_id=approver.id,
            created_at=NOW,
        )
    return proposal_id


def make_sent(
    db: CrmDatabase,
    lead_id: int,
    user: User,
    rfc_message_id: str,
    *,
    kind: ProposalKind = ProposalKind.FOLLOWUP,
    step: int | None = 1,
    body: str = BODY,
) -> int:
    """Propuesta ya enviada (con su `Message-ID`), para probar la asociación de respuestas."""
    proposal_id = make_proposal(db, lead_id, user, kind=kind, step=step, body=body)
    with db.tx() as tx:
        version = repo.get_proposal_version(tx, proposal_id, 1)
        assert version is not None
        send_id = repo.insert_send(
            tx,
            proposal_id=proposal_id,
            version=1,
            approved_hash=version.content_hash,
            approved_by=user.id,
            approved_at=NOW,
            scheduled_at=NOW,
            lead_id=lead_id,
            week_start=week_start(NOW),
            next_attempt_at=None,
        )
        repo.update_send(
            tx, send_id, status="sent", rfc_message_id=rfc_message_id, sent_at=NOW, attempts=1
        )
        repo.update_proposal(tx, proposal_id, status="sent", resolved_at=NOW)
    return send_id


def make_inbound(
    uid: int,
    text: str,
    *,
    sender: str = EMAIL,
    in_reply_to: str | None = None,
    subject: str = "Re: Retomo nuestra conversación",
    message_id: str | None = None,
    when: datetime = NOW,
) -> InboundMessage:
    return InboundMessage(
        uid=uid,
        rfc_message_id=message_id or f"<in{uid}@cliente.test>",
        in_reply_to=in_reply_to,
        references=(in_reply_to,) if in_reply_to else (),
        from_addr=sender,
        subject=subject,
        body_text=text,
        date=when,
        truncated=False,
    )
