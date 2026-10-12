"""Autorización de tratamiento de datos por correo (F2-T19 y T20; VCRM-068, 119, 121, 141..143,
148, 149; plan-f2 §5.6).

La autorización es lo que habilita TODO el contacto comercial, así que aquí nada se registra solo:
- la solicitud al titular pasa por el mismo gate ✅/❌ que cualquier otro mensaje (P-09) y no se
  prepara si falta el aviso de privacidad, su versión o los encargados (VCRM-149);
- la respuesta del titular NO se interpreta automáticamente: se propone al comercial del lead, que
  la confirma con ✅ o la descarta con ❌ (decisión N-04). Cada propuesta se resuelve una sola vez.
"""

import re
import sqlite3
from collections.abc import Sequence
from datetime import datetime

from jerico.crm import compliance, config, delivery, followup, gate, repo
from jerico.crm.config import CrmSettings
from jerico.crm.followup_text import auth_request_body
from jerico.crm.leads import deny_lead
from jerico.crm.model import (
    AuditAction,
    AuditOutcome,
    AuthStatus,
    EventKind,
    InboundClassification,
    InboundDecision,
    Lead,
    LeadState,
    Outgoing,
    ProposalKind,
    User,
)
from jerico.crm.permissions import Action, authorize, commercial_recipients
from jerico.crm.render import short_id

REQUEST_SUBJECT = "Autorización para el tratamiento de sus datos personales — Kaisen AI"
CONFIRMED_MEDIUM = "respuesta al correo confirmada por el comercial"
AUTH_PURPOSES = (
    "Finalidades del aviso de privacidad: seguimiento comercial, contrato, cumplimiento legal "
    "y prueba de la autorización"
)
REPLY_EVENT_FIELD = "authorization_reply"
ALREADY_PROCESSED = "Esta propuesta ya fue procesada."
_VERSION_RE = re.compile(r"versión\s+([\w.\-]+)", re.IGNORECASE)


def _text(user: User, text: str) -> list[Outgoing]:
    return [Outgoing(user.telegram_id, text)]


def _approver(conn: sqlite3.Connection, lead: Lead) -> User | None:
    pool = commercial_recipients(lead, repo.active_users(conn))
    return pool[0] if pool else None


def _audit(conn: sqlite3.Connection, actor: User, lead_id: int, now: datetime) -> None:
    repo.audit(
        conn,
        actor=f"user:{actor.id}",
        action=AuditAction.LEAD_UPDATED,
        outcome=AuditOutcome.OK,
        at=now,
        lead_id=lead_id,
    )


def _missing_notice_config(settings: CrmSettings) -> list[str]:
    missing: list[str] = []
    if config.load_privacy_notice(settings) is None:
        missing.append("JERICO_CRM_PRIVACY_NOTICE_FILE")
    if not settings.privacy_notice_version.strip():
        missing.append("JERICO_CRM_PRIVACY_NOTICE_VERSION")
    if not config.processors(settings):
        missing.append("JERICO_CRM_DATA_PROCESSORS")
    return missing


def request_authorization(
    conn: sqlite3.Connection,
    actor: User,
    lead_id: int,
    now: datetime,
    keys: Sequence[str],
    settings: CrmSettings,
    sender_name: str,
) -> list[Outgoing]:
    """Prepara la solicitud de autorización al titular y la presenta al aprobador (VCRM-068)."""
    lead = repo.get_lead(conn, lead_id)
    if lead is None:
        return _text(actor, f"El lead {short_id(lead_id)} no existe.")
    decision = authorize(actor, Action.REGISTER_AUTH, lead)
    if not decision.allowed:
        return deny_lead(conn, actor, decision, lead.id, now)
    sid = short_id(lead.id)
    if not followup.f2_active(conn):
        return _text(
            actor,
            "El seguimiento (fase 2) aún no está activo: no se pueden pedir autorizaciones "
            "por correo.",
        )
    if not compliance.may_request_authorization(conn, lead, keys):
        return _text(
            actor,
            f"No se puede pedir autorización a {sid}: está en baja, bloqueado, suprimido "
            "o ya revocó la autorización.",
        )
    if lead.auth_status == AuthStatus.AUTHORIZED:
        return _text(actor, f"{sid} ya cuenta con autorización vigente.")
    if not lead.email:
        return _text(actor, f"{sid} no tiene correo registrado: no se puede enviar la solicitud.")
    missing = _missing_notice_config(settings)
    if missing:  # VCRM-149
        return _text(
            actor,
            "Falta la configuración del aviso de privacidad ("
            + ", ".join(missing)
            + "): no se preparó la solicitud.",
        )
    approver = _approver(conn, lead)
    if approver is None:
        return _text(actor, "No hay un aprobador activo (comercial del lead o CTO).")
    proposal_id = repo.insert_proposal(
        conn,
        lead_id=lead.id,
        kind=ProposalKind.AUTH_REQUEST,
        step=None,
        approver_user_id=approver.id,
        expires_at=now + gate.GATE_DEADLINE,
        created_at=now,
    )
    if proposal_id is None:
        return _text(actor, f"Ya hay una solicitud de autorización abierta para {sid}.")
    notice = config.load_privacy_notice(settings) or ""
    body = auth_request_body(
        notice, settings.privacy_notice_version, config.processors(settings), sender_name
    )
    repo.add_proposal_version(
        conn,
        proposal_id=proposal_id,
        version=1,
        subject=REQUEST_SUBJECT,
        body=body,
        content_hash=delivery.content_hash(REQUEST_SUBJECT, body),
        author_user_id=actor.id,
        created_at=now,
    )
    _audit(conn, actor, lead.id, now)
    out = gate.present(conn, proposal_id)
    if actor.telegram_id not in {o.chat_id for o in out}:
        out += _text(
            actor, f"Solicitud de autorización de {sid} preparada: la decide el aprobador."
        )
    return out


# --- T20: confirmación de la respuesta como autorización ---------------------------------------


def _sent_notice_version(conn: sqlite3.Connection, lead_id: int) -> str | None:
    """Versión del aviso que se ENVIÓ en la última solicitud (puede diferir de la actual)."""
    row = conn.execute(
        "SELECT v.body FROM crm_sends s "
        "JOIN crm_proposals p ON p.id = s.proposal_id "
        "JOIN crm_proposal_versions v ON v.proposal_id = s.proposal_id AND v.version = s.version "
        "WHERE s.lead_id = ? AND p.kind = ? AND s.status = 'sent' ORDER BY s.id DESC LIMIT 1",
        (lead_id, ProposalKind.AUTH_REQUEST.value),
    ).fetchone()
    match = _VERSION_RE.search(row["body"]) if row is not None else None
    return match.group(1) if match else None


def _load_candidate(
    conn: sqlite3.Connection, actor: User, inbound_id: int, now: datetime
) -> tuple[object, Lead] | list[Outgoing]:
    inbound = repo.get_inbound(conn, inbound_id)
    if inbound is None:
        return _text(actor, f"La respuesta {inbound_id} no existe.")
    lead = repo.get_lead(conn, inbound.lead_id) if inbound.lead_id is not None else None
    if lead is None:
        return _text(actor, "Esa respuesta no está asociada a ningún lead.")
    deciders = {u.id for u in commercial_recipients(lead, repo.active_users(conn))}
    if actor.id not in deciders:  # solo el comercial del lead (o el CTO si no tiene) — VCRM-141
        repo.audit(
            conn,
            actor=f"user:{actor.id}",
            action=AuditAction.PERMISSION_DENIED,
            outcome=AuditOutcome.DENIED,
            at=now,
            lead_id=lead.id,
        )
        return _text(actor, "No tiene permiso para decidir sobre esta respuesta.")
    if inbound.classification != InboundClassification.AUTH_CANDIDATE:
        return _text(actor, "Esa respuesta no es una respuesta propuesta como autorización.")
    if inbound.decision != InboundDecision.PENDING:  # VCRM-143
        return _text(actor, ALREADY_PROCESSED)
    return inbound, lead


def confirm(
    conn: sqlite3.Connection,
    actor: User,
    inbound_id: int,
    now: datetime,
    keys: Sequence[str],
) -> list[Outgoing]:
    """✅: registra la autorización con su evidencia (VCRM-141) y, si el lead estaba rechazado,
    inicia la cadencia (VCRM-121)."""
    loaded = _load_candidate(conn, actor, inbound_id, now)
    if isinstance(loaded, list):
        return loaded
    inbound, lead = loaded
    sid = short_id(lead.id)
    if lead.state == LeadState.OPTED_OUT or not compliance.may_request_authorization(
        conn, lead, keys
    ):
        repo.update_inbound(
            conn,
            inbound_id,
            decision=InboundDecision.REJECTED,
            decided_by=actor.id,
            decided_at=now,
        )
        return _text(
            actor,
            f"No se registró la autorización de {sid}: el lead está en baja, suprimido o "
            "ya revocó la autorización.",
        )
    repo.insert_consent(
        conn,
        lead_id=lead.id,
        status=AuthStatus.AUTHORIZED,
        medium=CONFIRMED_MEDIUM,
        at=now,
        actor_user_id=actor.id,
        notice_version=_sent_notice_version(conn, lead.id),
        purposes=AUTH_PURPOSES,
        evidence_inbound_id=inbound_id,
    )
    repo.update_lead(conn, lead.id, {"auth_status": AuthStatus.AUTHORIZED.value}, now=now)
    repo.update_inbound(
        conn,
        inbound_id,
        decision=InboundDecision.CONFIRMED,
        decided_by=actor.id,
        decided_at=now,
    )
    repo.add_event(
        conn,
        lead_id=lead.id,
        kind=EventKind.FIELD,
        actor_user_id=actor.id,
        at=now,
        field=REPLY_EVENT_FIELD,
        new_value="confirmed",
        reason_text=f"respuesta {inbound_id}",
    )
    _audit(conn, actor, lead.id, now)
    out = _text(actor, f"Autorización registrada para {sid} (medio: {CONFIRMED_MEDIUM}).")
    if lead.state == LeadState.REJECTED:  # VCRM-121
        updated = repo.get_lead(conn, lead.id)
        if updated is not None:
            out += followup.start_cadence(conn, updated, now, keys)
    return out


def decline(
    conn: sqlite3.Connection, actor: User, inbound_id: int, now: datetime
) -> list[Outgoing]:
    """❌: no registra nada; deja la decisión, el autor y la hora en el historial (VCRM-142)."""
    loaded = _load_candidate(conn, actor, inbound_id, now)
    if isinstance(loaded, list):
        return loaded
    _inbound, lead = loaded
    repo.update_inbound(
        conn,
        inbound_id,
        decision=InboundDecision.REJECTED,
        decided_by=actor.id,
        decided_at=now,
    )
    repo.add_event(
        conn,
        lead_id=lead.id,
        kind=EventKind.FIELD,
        actor_user_id=actor.id,
        at=now,
        field=REPLY_EVENT_FIELD,
        new_value="rejected",
        reason_text=f"respuesta {inbound_id}",
    )
    _audit(conn, actor, lead.id, now)
    return _text(
        actor,
        f"La respuesta no se tomó como autorización: no se registró nada y {short_id(lead.id)} "
        "sigue sin autorización.",
    )


__all__ = [
    "ALREADY_PROCESSED",
    "AUTH_PURPOSES",
    "CONFIRMED_MEDIUM",
    "REQUEST_SUBJECT",
    "confirm",
    "decline",
    "request_authorization",
]
