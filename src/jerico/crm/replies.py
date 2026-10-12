"""Respuestas del titular al correo comercial (F2-T18; VCRM-102, 103, 119, 120, 122, 124, 153,
169, 170; plan-f2 §5.7).

Una respuesta puede dar de baja al titular de inmediato y sin confirmación humana (J-06), o no debe
hacerlo nunca por error. Por eso:
- el texto evaluado es solo el redactado por el remitente (`extract_new_text`), sin citas ni las
  líneas de nuestro propio mensaje;
- la asociación a un lead exige un hilo inequívoco, un token de baja firmado o un único lead con
  ese correo; lo que no se pueda asociar NO cambia a nadie y va a revisión humana (VCRM-122);
- un token de baja inválido jamás aplica nada, aunque el remitente y el hilo coincidan (VCRM-124);
- cada mensaje se procesa una sola vez (`Message-ID` único) y un lote se confirma completo o nada.
"""

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from jerico.crm import compliance, repo
from jerico.crm.config import Params
from jerico.crm.db import CrmDatabase
from jerico.crm.fingerprint import fingerprint
from jerico.crm.inbound import (
    extract_new_text,
    has_stop_keyword,
    parse_unsub_subject,
    plain_excerpt,
    verify_unsub_token,
)
from jerico.crm.model import (
    SYSTEM_USER_ID,
    AuditAction,
    AuditOutcome,
    AuthStatus,
    EventKind,
    InboundAssociation,
    InboundClassification,
    InboundDecision,
    Lead,
    LeadState,
    Outgoing,
    ProposalKind,
    RequestStatus,
    RequestType,
    Role,
    SendStatus,
    TitularRequest,
    User,
)
from jerico.crm.parsing import build_callback
from jerico.crm.permissions import commercial_recipients
from jerico.crm.ports import InboundMessage, InboxError, InboxPort
from jerico.crm.render import short_id
from jerico.crm.timeutil import format_local, from_iso, local_date, to_iso

MEDIUM_REPLY = "respuesta al correo"
MEDIUM_HEADER = "cabecera de baja del correo"
MEDIUM_CONFIRMED = "respuesta al correo confirmada por un usuario"
BAJA_CALLBACK = "rbaja"
CLASSIFY_CALLBACK = "rclas"
NO_REQUEST_CALLBACK = "rsin"
CONSULT_CALLBACK = "rcon"
CLAIM_CALLBACK = "rrec"
AUTH_OK_CALLBACK = "aok"
AUTH_NO_CALLBACK = "ano"

_HOW = {
    InboundAssociation.THREAD: "la referencia de hilo del correo",
    InboundAssociation.SENDER: "la huella del remitente (único lead con ese correo)",
    InboundAssociation.TOKEN: "la cabecera de baja del correo",
    InboundAssociation.NONE: "ninguna (no se pudo asociar a un lead)",
}


@dataclass(frozen=True)
class Association:
    lead_id: int | None
    how: InboundAssociation
    send_id: int | None = None


_NONE = Association(None, InboundAssociation.NONE)


def associate(conn: sqlite3.Connection, msg: InboundMessage, keys: Sequence[str]) -> Association:
    """Lead al que pertenece la respuesta. Orden: token de baja, hilo y, por último, remitente."""
    token = parse_unsub_subject(msg.subject)
    if token is not None:
        send_id = verify_unsub_token(token, keys)
        send = repo.get_send(conn, send_id) if send_id is not None else None
        # Un token inválido o desconocido NO recurre al hilo ni al remitente (VCRM-124).
        return (
            _NONE if send is None else Association(send.lead_id, InboundAssociation.TOKEN, send.id)
        )
    references = dict.fromkeys(r for r in (msg.in_reply_to, *msg.references) if r)
    sends = [s for ref in references if (s := repo.get_send_by_message_id(conn, ref)) is not None]
    lead_ids = {s.lead_id for s in sends}
    if len(lead_ids) > 1:  # el hilo apunta a leads distintos: ambiguo, a revisión
        return _NONE
    if sends:
        latest = max(sends, key=lambda s: s.id)
        return Association(latest.lead_id, InboundAssociation.THREAD, latest.id)
    if msg.from_addr:
        leads = repo.leads_by_email(conn, msg.from_addr)
        if len(leads) == 1:
            return Association(leads[0].id, InboundAssociation.SENDER)
    return _NONE


def _sent_body(conn: sqlite3.Connection, send_id: int | None) -> str | None:
    """Texto que le enviamos, para no confundir lo que cita con lo que escribe (VCRM-102)."""
    send = repo.get_send(conn, send_id) if send_id is not None else None
    if send is None:
        return None
    version = repo.get_proposal_version(conn, send.proposal_id, send.version)
    return None if version is None else version.body


def _auth_request_sent(conn: sqlite3.Connection, lead_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM crm_sends s JOIN crm_proposals p ON p.id = s.proposal_id "
        "WHERE s.lead_id = ? AND p.kind = ? AND s.status = ? LIMIT 1",
        (lead_id, ProposalKind.AUTH_REQUEST.value, SendStatus.SENT.value),
    ).fetchone()
    return row is not None


def _chats_for(conn: sqlite3.Connection, lead: Lead | None) -> list[int]:
    users = repo.active_users(conn)
    if lead is not None:
        return [u.telegram_id for u in commercial_recipients(lead, users)]
    return [u.telegram_id for u in users if u.role == Role.CTO]


def _classify(
    conn: sqlite3.Connection, lead: Lead | None, assoc: Association, new_text: str
) -> InboundClassification:
    if lead is None:
        return InboundClassification.UNASSOCIATED
    if assoc.how == InboundAssociation.TOKEN:
        return InboundClassification.STOP_HEADER
    if has_stop_keyword(new_text):  # prevalece sobre cualquier otra lectura (VCRM-120)
        return InboundClassification.STOP_KEYWORD
    if lead.auth_status != AuthStatus.AUTHORIZED and _auth_request_sent(conn, lead.id):
        return InboundClassification.AUTH_CANDIDATE
    return InboundClassification.REVIEW


def _opt_out(
    conn: sqlite3.Connection, lead: Lead, medium: str, now: datetime, keys: Sequence[str]
) -> list[Outgoing]:
    """Baja inmediata, sin acuse al titular (Q-5)."""
    chats = _chats_for(conn, lead)
    if lead.state == LeadState.OPTED_OUT:
        text = f"Respuesta de baja de {short_id(lead.id)}: ya estaba en baja."
    else:
        compliance.apply_opt_out(
            conn,
            lead,
            medium=medium,
            now=now,
            keys=keys,
            actor_user_id=SYSTEM_USER_ID,
            audit_actor="system",
        )
        text = (
            f"Baja aplicada: {short_id(lead.id)} (medio: {medium}). "
            "El contacto queda en la lista de supresión."
        )
    return [Outgoing(chat, text) for chat in chats]


def _body_of_notice(
    lead: Lead | None, assoc: Association, received_at: datetime, new_text: str
) -> str:
    who = short_id(lead.id) if lead is not None else compliance.NO_LEAD_LABEL
    shown = plain_excerpt(new_text) or "(sin texto nuevo)"
    return (
        f"Respuesta de un titular ({who}) · asociada por {_HOW[assoc.how]} · "
        f"recibida {format_local(received_at)}\n\n«{shown}»"
    )


def _review(
    conn: sqlite3.Connection,
    lead: Lead | None,
    assoc: Association,
    received_at: datetime,
    new_text: str,
    inbound_id: int,
    now: datetime,
    params: Params,
) -> list[Outgoing]:
    """Registra la solicitud «por clasificar» (15 días hábiles) y la presenta (VCRM-103, 122)."""
    received = local_date(received_at)
    due = compliance.request_due_on(RequestType.UNCLASSIFIED, received, params)
    request_id = repo.insert_titular_request(
        conn,
        lead_id=lead.id if lead is not None else None,
        kind=RequestType.UNCLASSIFIED,
        medium=MEDIUM_REPLY,
        received_on=received.isoformat(),
        due_on=due.isoformat(),
        registered_by=SYSTEM_USER_ID,
        now=now,
        inbound_id=inbound_id,
    )
    if lead is not None:  # queda en el historial del lead (VCRM-103)
        repo.add_event(
            conn,
            lead_id=lead.id,
            kind=EventKind.TITULAR_REQUEST,
            actor_user_id=SYSTEM_USER_ID,
            at=now,
            new_value=RequestType.UNCLASSIFIED.value,
            reason_text=MEDIUM_REPLY,
        )
    text = (
        _body_of_notice(lead, assoc, received_at, new_text)
        + f"\n\nSolicitud {compliance.request_short_id(request_id)} por clasificar; "
        f"fecha límite {_date_text(due)}."
    )
    buttons: tuple[tuple[tuple[str, str], ...], ...]
    if lead is None:  # sin lead no hay baja ni clasificación posibles: solo cerrarla o gestionarla
        text += (
            "\nSi corresponde a un lead, regístrela con /solicitud o aplique /baja desde su ficha."
        )
        buttons = ((("Sin solicitud", build_callback(NO_REQUEST_CALLBACK, str(request_id))),),)
    else:
        buttons = (
            (
                ("Aplicar baja", build_callback(BAJA_CALLBACK, str(request_id))),
                (
                    "Registrar consulta o reclamo",
                    build_callback(CLASSIFY_CALLBACK, str(request_id)),
                ),
                ("Sin solicitud", build_callback(NO_REQUEST_CALLBACK, str(request_id))),
            ),
        )
    return [Outgoing(chat, text, buttons) for chat in _chats_for(conn, lead)]


def _date_text(day: date) -> str:
    return day.strftime("%d/%m/%Y")


def _candidate(
    conn: sqlite3.Connection,
    lead: Lead,
    assoc: Association,
    received_at: datetime,
    new_text: str,
    inbound_id: int,
) -> list[Outgoing]:
    """La respuesta a una solicitud de autorización se PROPONE al comercial; no se registra aún."""
    text = (
        _body_of_notice(lead, assoc, received_at, new_text)
        + "\n\n¿Esta respuesta autoriza el tratamiento de datos?"
    )
    buttons = (
        (
            ("✅", build_callback(AUTH_OK_CALLBACK, str(inbound_id))),
            ("❌", build_callback(AUTH_NO_CALLBACK, str(inbound_id))),
        ),
    )
    return [Outgoing(chat, text, buttons) for chat in _chats_for(conn, lead)]


def process_message(
    conn: sqlite3.Connection,
    msg: InboundMessage,
    now: datetime,
    params: Params,
    keys: Sequence[str],
) -> list[Outgoing]:
    """Procesa UNA respuesta: la registra, la clasifica y actúa. Devuelve los avisos a enviar."""
    assoc = associate(conn, msg, keys)
    lead = repo.get_lead(conn, assoc.lead_id) if assoc.lead_id is not None else None
    new_text = extract_new_text(msg.body_text, _sent_body(conn, assoc.send_id))
    kind = _classify(conn, lead, assoc, new_text)
    received_at = msg.date or now
    inbound_id = repo.insert_inbound(
        conn,
        rfc_message_id=msg.rfc_message_id,
        uid=msg.uid,
        received_at=received_at,
        sender_fp=fingerprint(keys[0], msg.from_addr) if msg.from_addr and keys else "",
        lead_id=lead.id if lead is not None else None,
        association=assoc.how,
        classification=kind,
        new_text=new_text,
    )
    if inbound_id is None:  # ya procesado: una sola vez aunque se repita el sondeo (VCRM-169)
        return []
    if lead is not None and kind in (
        InboundClassification.STOP_KEYWORD,
        InboundClassification.STOP_HEADER,
    ):
        repo.update_inbound(conn, inbound_id, decision=InboundDecision.NOT_APPLICABLE)
        medium = MEDIUM_HEADER if kind == InboundClassification.STOP_HEADER else MEDIUM_REPLY
        return _opt_out(conn, lead, medium, now, keys)
    if lead is not None and kind == InboundClassification.AUTH_CANDIDATE:
        return _candidate(conn, lead, assoc, received_at, new_text, inbound_id)
    return _review(conn, lead, assoc, received_at, new_text, inbound_id, now, params)


# --- Decisiones sobre una respuesta «por clasificar» (VCRM-153) ----------------------------------

_OPEN_REQUEST = (RequestStatus.OPEN.value, RequestStatus.OVERDUE.value)
ALREADY_PROCESSED = "Esta solicitud ya fue procesada."
NO_PERMISSION = "No tiene permiso para decidir sobre esta respuesta."


def _text(user: User, text: str) -> list[Outgoing]:
    return [Outgoing(user.telegram_id, text)]


def _review_target(
    conn: sqlite3.Connection, actor: User, request_id: int, now: datetime
) -> tuple[TitularRequest, Lead | None] | list[Outgoing]:
    """Solicitud «por clasificar» abierta si el actor puede decidir; si no, la respuesta."""
    request = repo.get_titular_request(conn, request_id)
    if request is None:
        return _text(actor, f"La solicitud {compliance.request_short_id(request_id)} no existe.")
    lead = repo.get_lead(conn, request.lead_id) if request.lead_id is not None else None
    deciders = {u.id for u in repo.active_users(conn, Role.CTO)}  # el CTO siempre puede
    if lead is not None:
        deciders |= {u.id for u in commercial_recipients(lead, repo.active_users(conn))}
    if actor.id not in deciders:
        repo.audit(
            conn,
            actor=f"user:{actor.id}",
            action=AuditAction.PERMISSION_DENIED,
            outcome=AuditOutcome.DENIED,
            at=now,
            lead_id=request.lead_id,
        )
        return _text(actor, NO_PERMISSION)
    if request.type != RequestType.UNCLASSIFIED.value or request.status not in _OPEN_REQUEST:
        return _text(actor, ALREADY_PROCESSED)
    return request, lead


def _settle(
    conn: sqlite3.Connection,
    request: TitularRequest,
    actor: User,
    now: datetime,
    decision: InboundDecision,
    *,
    attended: bool,
) -> None:
    if attended:
        repo.update_titular_request(
            conn,
            request.id,
            {
                "status": RequestStatus.ATTENDED.value,
                "attended_by": actor.id,
                "attended_at": to_iso(now),
            },
        )
        repo.resolve_request_alerts(conn, request.id, resolved_by=actor.id, now=now)
    if request.inbound_id is not None:
        repo.update_inbound(
            conn, request.inbound_id, decision=decision, decided_by=actor.id, decided_at=now
        )


def classify_options(
    conn: sqlite3.Connection, actor: User, request_id: int, now: datetime
) -> list[Outgoing]:
    """«Registrar consulta o reclamo»: pregunta cuál de las dos (VCRM-153)."""
    target = _review_target(conn, actor, request_id, now)
    if isinstance(target, list):
        return target
    buttons = (
        (
            ("Consulta", build_callback(CONSULT_CALLBACK, str(request_id))),
            ("Reclamo", build_callback(CLAIM_CALLBACK, str(request_id))),
        ),
    )
    return [Outgoing(actor.telegram_id, "¿Qué tipo de solicitud es?", buttons)]


def classify_review(
    conn: sqlite3.Connection,
    actor: User,
    request_id: int,
    kind: RequestType,
    now: datetime,
    params: Params,
) -> list[Outgoing]:
    """La reclasifica como consulta o reclamo con su plazo (VCRM-150, 153). Sigue abierta."""
    target = _review_target(conn, actor, request_id, now)
    if isinstance(target, list):
        return target
    request, lead = target
    due = compliance.request_due_on(kind, date.fromisoformat(request.received_on), params)
    repo.update_titular_request(conn, request.id, {"type": kind.value, "due_on": due.isoformat()})
    _settle(conn, request, actor, now, InboundDecision.CONFIRMED, attended=False)
    if lead is not None:
        repo.add_event(
            conn,
            lead_id=lead.id,
            kind=EventKind.TITULAR_REQUEST,
            actor_user_id=actor.id,
            at=now,
            new_value=kind.value,
            reason_text=MEDIUM_REPLY,
        )
    label = "consulta" if kind is RequestType.INQUIRY else "reclamo"
    return _text(
        actor,
        f"Solicitud {compliance.request_short_id(request.id)} registrada como {label}; "
        f"fecha límite {_date_text(due)}.",
    )


def close_review(
    conn: sqlite3.Connection, actor: User, request_id: int, now: datetime
) -> list[Outgoing]:
    """«Sin solicitud»: la respuesta no contenía ninguna; se cierra con autor y hora."""
    target = _review_target(conn, actor, request_id, now)
    if isinstance(target, list):
        return target
    request, _lead = target
    _settle(conn, request, actor, now, InboundDecision.REJECTED, attended=True)
    return _text(
        actor, f"Solicitud {compliance.request_short_id(request.id)} cerrada: sin solicitud."
    )


def apply_review_baja(
    conn: sqlite3.Connection,
    actor: User,
    request_id: int,
    now: datetime,
    keys: Sequence[str],
) -> list[Outgoing]:
    """«Aplicar baja»: la persona confirma que la respuesta era una baja (VCRM-153, 070)."""
    target = _review_target(conn, actor, request_id, now)
    if isinstance(target, list):
        return target
    request, lead = target
    if lead is None:
        return _text(
            actor,
            "La respuesta no está asociada a ningún lead: sin lead no se puede aplicar la baja. "
            "Use /baja desde la ficha del lead.",
        )
    if lead.state == LeadState.OPTED_OUT:
        out = _text(actor, f"{short_id(lead.id)} ya estaba en baja.")
    else:
        compliance.apply_opt_out(
            conn,
            lead,
            medium=MEDIUM_CONFIRMED,
            now=now,
            keys=keys,
            actor_user_id=actor.id,
            audit_actor=f"user:{actor.id}",
        )
        out = _text(
            actor,
            f"Baja aplicada: {short_id(lead.id)} (medio: {MEDIUM_CONFIRMED}). "
            "El contacto queda en la lista de supresión.",
        )
    _settle(conn, request, actor, now, InboundDecision.CONFIRMED, attended=True)
    return out


# --- Sondeo del buzón (VCRM-169, 170) -----------------------------------------------------------


async def poll_and_process(
    db: CrmDatabase,
    inbox: InboxPort,
    now: datetime,
    params: Params,
    keys: Sequence[str],
) -> list[Outgoing]:
    """Consulta el buzón si toca, procesa el lote en UNA transacción y avanza el UID al final.

    Si el lote falla a medias nada queda a medio hacer y se reintenta completo. Un fallo del buzón
    avisa al CTO una sola vez por episodio; al recuperarse se procesa todo lo recibido."""
    with db.read() as conn:
        last_poll = repo.get_meta(conn, "imap_last_poll_at")
        stored_validity = repo.get_meta(conn, "imap_uidvalidity")
        last_uid = int(repo.get_meta(conn, "imap_last_uid") or 0)
        failing = repo.get_meta(conn, "imap_failing") == "1"
    if (
        last_poll is not None
        and from_iso(last_poll) + timedelta(minutes=params.inbox_poll_minutes) > now
    ):
        return []
    try:
        batch = await inbox.fetch_new(int(stored_validity) if stored_validity else None, last_uid)
    except InboxError as exc:
        out: list[Outgoing] = []
        with db.tx() as tx:
            repo.set_meta(tx, "imap_last_poll_at", to_iso(now))
            if not failing:
                repo.set_meta(tx, "imap_failing", "1")
                text = (
                    f"No se pudo leer el buzón de respuestas ({exc}). Mientras tanto no se "
                    "aplican las bajas por correo; se reintenta en la siguiente consulta."
                )
                out = [Outgoing(chat, text) for chat in _chats_for(tx, None)]
        return out
    out = []
    with db.tx() as tx:
        for msg in batch.messages:
            out += process_message(tx, msg, now, params, keys)
        same = stored_validity is not None and int(stored_validity) == batch.uidvalidity
        newest = max((m.uid for m in batch.messages), default=last_uid if same else 0)
        repo.set_meta(tx, "imap_uidvalidity", str(batch.uidvalidity))
        repo.set_meta(tx, "imap_last_uid", str(newest))
        repo.set_meta(tx, "imap_failing", "0")
        repo.set_meta(tx, "imap_last_poll_at", to_iso(now))
    return out


__all__ = [
    "AUTH_NO_CALLBACK",
    "AUTH_OK_CALLBACK",
    "BAJA_CALLBACK",
    "CLAIM_CALLBACK",
    "CLASSIFY_CALLBACK",
    "CONSULT_CALLBACK",
    "MEDIUM_CONFIRMED",
    "MEDIUM_HEADER",
    "MEDIUM_REPLY",
    "NO_REQUEST_CALLBACK",
    "Association",
    "apply_review_baja",
    "associate",
    "classify_options",
    "classify_review",
    "close_review",
    "poll_and_process",
    "process_message",
]
