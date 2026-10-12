"""Cumplimiento: autorización con evidencia, baja y guarda de contacto comercial (plan §8.3).

Requisitos: VCRM-065, 070, 071, 073, 074, 075, 094, 095, 138, 139, 154, 164, 165, 166.
"""

import re
import sqlite3
import zipfile
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import PurePosixPath

from jerico.crm import repo
from jerico.crm.config import Params
from jerico.crm.fingerprint import fingerprint
from jerico.crm.leads import (
    AUTH_EVIDENCE_KIND,
    Prefetched,
    _assignee,
    _deny,
    _invalid_transition_text,
    _sha256,
    deny_lead,
)
from jerico.crm.model import (
    Attachment,
    AuditAction,
    AuditDetail,
    AuditOutcome,
    AuthStatus,
    Channel,
    EventKind,
    Lead,
    LeadState,
    Outgoing,
    PendingInput,
    RequestStatus,
    RequestType,
    Role,
    TitularRequest,
    User,
)
from jerico.crm.outbox import SUPPRESSION_KIND, enqueue_critical, suppression_key
from jerico.crm.parsing import parse_short_id
from jerico.crm.permissions import Action, authorize
from jerico.crm.ports import FileStore, TelegramPort, Update
from jerico.crm.render import NO_VALUE, render_lead_card, short_id
from jerico.crm.states import check_transition
from jerico.crm.timeutil import (
    add_business_days,
    business_days_between,
    format_local,
    from_iso,
    local_date,
    to_iso,
)

AUTH_MEDIUM = "documento_o_captura"  # medio (b) de la decisión N-04
EVIDENCE_KINDS = frozenset({"photo", "document"})
NOT_REGISTERED = "No se registró la autorización; el estado del lead no cambió."
VALID_MEDIA = (
    "Medios válidos: documento firmado o captura (foto o documento) adjuntada por el comercial "
    "con /autorizacion L-n; o respuesta del titular al correo, confirmada por el comercial."
)
EXAMPLE_AUTH = "/autorizacion L-0042"
EXAMPLE_OPT_OUT = "/baja L-0042; llamada telefónica"
_AUTH_RE = re.compile(r"^/autorizacion(?:@\w+)?\s+(\S+)\s*$")
_OPT_OUT_RE = re.compile(r"^/baja(?:@\w+)?\s+([^;\s]+)\s*;\s*(\S.*?)\s*$")


def _lead_or_error(
    conn: sqlite3.Connection, actor: User, lead_id: int, action: Action, now: datetime
) -> Lead | list[Outgoing]:
    lead = repo.get_lead(conn, lead_id)
    if lead is None:
        return [Outgoing(actor.telegram_id, f"El lead {short_id(lead_id)} no existe.")]
    decision = authorize(actor, action, lead)
    if not decision.allowed:
        return deny_lead(conn, actor, decision, lead.id, now)
    return lead


# --- Autorización (VCRM-065, 138, 139) -------------------------------------------------------


def authorization_command(
    conn: sqlite3.Connection, actor: User, text: str, now: datetime
) -> list[Outgoing]:
    """`/autorizacion L-n`: abre la entrada pendiente de la evidencia (VCRM-138)."""
    match = _AUTH_RE.match(text.strip())
    lead_id = parse_short_id(match.group(1)) if match else None
    if lead_id is None:
        return [Outgoing(actor.telegram_id, f"Formato no válido. Ejemplo: {EXAMPLE_AUTH}")]
    found = _lead_or_error(conn, actor, lead_id, Action.REGISTER_AUTH, now)
    if isinstance(found, list):
        return found
    repo.set_pending_input(
        conn, user_id=actor.id, kind=AUTH_EVIDENCE_KIND, now=now, lead_id=found.id
    )
    text = (
        "Adjunte ahora el documento firmado o la captura (foto o documento) "
        f"para {short_id(found.id)}."
    )
    return [Outgoing(actor.telegram_id, text)]


def answer_evidence(
    conn: sqlite3.Connection,
    actor: User,
    pending: PendingInput,
    update: Update,
    file: Prefetched | None,
    store: FileStore | None,
    now: datetime,
) -> list[Outgoing]:
    """Evidencia tras «Sí» o `/autorizacion`: solo foto o documento la cumplen (VCRM-138, 139)."""
    chat = actor.telegram_id
    if file is None or store is None or file.kind not in EVIDENCE_KINDS:
        return [Outgoing(chat, f"{NOT_REGISTERED} {VALID_MEDIA}")]
    if not file.result.ok:
        if file.result.error == "too_large":
            return [Outgoing(chat, f"El archivo supera el límite de 20 MB. {NOT_REGISTERED}")]
        return [Outgoing(chat, f"No se pudo descargar el archivo. {NOT_REGISTERED}")]
    found = _lead_or_error(conn, actor, pending.lead_id or 0, Action.REGISTER_AUTH, now)
    if isinstance(found, list):
        return found
    digest = _sha256(file.path)
    key = store.save_atomic(found.id, file.path)
    try:
        attachment_id = repo.insert_attachment(
            conn,
            lead_id=found.id,
            kind="authorization",
            author_user_id=actor.id,
            at=now,
            storage_key=key,
            size_bytes=file.result.size,
            sha256=digest,
        )
        repo.insert_consent(
            conn,
            lead_id=found.id,
            status=AuthStatus.AUTHORIZED,
            medium=AUTH_MEDIUM,
            at=now,
            actor_user_id=actor.id,
            attachment_id=attachment_id,
        )
        repo.update_lead(conn, found.id, {"auth_status": AuthStatus.AUTHORIZED.value}, now=now)
        _audit(conn, actor, found.id, now)
    except Exception:
        store.delete(key)  # sin adjunto parcial
        raise
    text = (
        f"Autorización de {short_id(found.id)} registrada como «autorizada» "
        f"(documento o captura) por {actor.email} el {format_local(now)}."
    )
    return [Outgoing(chat, text)]


# --- Baja (VCRM-070, 095, 164) ------------------------------------------------------------


def opt_out_command(
    conn: sqlite3.Connection, actor: User, text: str, now: datetime, keys: Sequence[str]
) -> list[Outgoing]:
    """`/baja L-n; medio`: aplica la baja en el momento (VCRM-070)."""
    match = _OPT_OUT_RE.match(text.strip())
    lead_id = parse_short_id(match.group(1)) if match else None
    if match is None or lead_id is None:
        return [Outgoing(actor.telegram_id, f"Formato no válido. Ejemplo: {EXAMPLE_OPT_OUT}")]
    medium = match.group(2)
    found = _lead_or_error(conn, actor, lead_id, Action.REGISTER_OPT_OUT, now)
    if isinstance(found, list):
        return found
    src = LeadState(found.state)
    check = check_transition(src, LeadState.OPTED_OUT)
    if not check.ok:
        return [
            Outgoing(actor.telegram_id, _invalid_transition_text(src, LeadState.OPTED_OUT, check))
        ]
    if not keys:
        raise ValueError("fingerprint keys required to register an opt-out")
    for contact in (found.phone_e164, found.email):
        if contact is not None:  # solo la huella, nunca el contacto (VCRM-095)
            repo.add_suppression(conn, fingerprint(keys[0], contact), at=now, medium=medium)
    repo.update_lead(
        conn,
        found.id,
        {
            "state": LeadState.OPTED_OUT.value,
            "final_state_at": to_iso(now),
            "auth_status": AuthStatus.REVOKED.value,
        },
        now=now,
    )
    repo.cancel_pending_confirmations(conn, found.id, now)
    repo.clear_lead_pending_inputs(conn, found.id)
    # Revocatoria como fila nueva: la evidencia previa queda intacta (VCRM-164).
    repo.insert_consent(
        conn,
        lead_id=found.id,
        status=AuthStatus.REVOKED,
        medium=medium,
        at=now,
        actor_user_id=actor.id,
    )
    repo.add_event(
        conn,
        lead_id=found.id,
        kind=EventKind.STATE,
        actor_user_id=actor.id,
        at=now,
        old_value=src.value,
        new_value=LeadState.OPTED_OUT.value,
        reason_text=medium,
    )
    _audit(conn, actor, found.id, now)
    text = (
        f"{short_id(found.id)}: estado «{src}» → «baja» (medio: {medium}). "
        "El contacto queda en la lista de supresión."
    )
    return [Outgoing(actor.telegram_id, text)]


# --- Guardas de contacto comercial (VCRM-067, 071) ------------------------------------------


def _contact_blocked(conn: sqlite3.Connection, lead: Lead, keys: Sequence[str]) -> bool:
    """Baja, bloqueo, supresión o huella en la lista de supresión (VCRM-071)."""
    if lead.state == LeadState.OPTED_OUT or lead.commercial_block or lead.suppressed_at is not None:
        return True
    contacts = [c for c in (lead.phone_e164, lead.email) if c is not None]
    fps = [fingerprint(key, contact) for contact in contacts for key in keys]
    return repo.any_suppressed(conn, fps)


def _authorization_current(conn: sqlite3.Connection, lead: Lead) -> bool:
    """Autorización vigente: el lead consta «autorizada» y lo último registrado la respalda."""
    if lead.auth_status != AuthStatus.AUTHORIZED:
        return False
    consents = repo.lead_consents(conn, lead.id)
    return bool(consents) and consents[-1]["status"] == AuthStatus.AUTHORIZED.value


def may_request_authorization(conn: sqlite3.Connection, lead: Lead, keys: Sequence[str]) -> bool:
    """¿Se puede pedir autorización? No si está bloqueado (VCRM-071) ni si ya la revocó."""
    if _contact_blocked(conn, lead, keys) or lead.auth_status == AuthStatus.REVOKED:
        return False
    consents = repo.lead_consents(conn, lead.id)
    return not (consents and consents[-1]["status"] == AuthStatus.REVOKED.value)


def may_contact_commercially(conn: sqlite3.Connection, lead: Lead, keys: Sequence[str]) -> bool:
    """Contacto comercial solo con autorización vigente y sin bloqueos (VCRM-067, 071; Q-4)."""
    return not _contact_blocked(conn, lead, keys) and _authorization_current(conn, lead)


# --- Supresión ordenada por el CTO (VCRM-073, 094, 154, 165) -------------------------------

ORDER_CAUSE = "orden_cto"
EXAMPLE_SUPPRESS = (
    "/suprimir L-0042 o /suprimir L-0042; conservar: nombre, documento; "
    "fundamento: contrato vigente"
)
_SUPPRESS_RE = re.compile(
    r"^/suprimir(?:@\w+)?\s+([^;\s]+)\s*"
    r"(?:;\s*conservar:\s*([^;]+?)\s*;\s*fundamento:\s*(\S.*?))?\s*$",
    re.DOTALL,
)
# Columnas con datos del titular que la supresión anula (ficha, handoff y motivo).
PERSONAL_COLUMNS: tuple[str, ...] = (
    "name",
    "phone_e164",
    "email",
    "company",
    "client_type",
    "doc_type",
    "doc_number",
    "legal_rep",
    "service",
    "agreed_value",
    "start_term",
    "reject_text",
)
# Campo de «conservar» (nombres de /editar) → columnas del lead (VCRM-094).
KEEP_FIELDS: dict[str, tuple[str, ...]] = {
    "nombre": ("name",),
    "telefono": ("phone_e164",),
    "correo": ("email",),
    "empresa": ("company",),
    "tipo": ("client_type",),
    "documento": ("doc_type", "doc_number"),
    "representante": ("legal_rep",),
    "servicio": ("service",),
    "valor": ("agreed_value",),
    "plazo": ("start_term",),
}
HOLD_STATES = frozenset({LeadState.ACCEPTED, LeadState.WON})


class SuppressionFailed(RuntimeError):
    """No se pudo borrar un archivo; ningún lead se marcó como suprimido."""


@dataclass(frozen=True)
class SuppressionPlan:
    lead_id: int
    null_columns: tuple[str, ...]
    files: tuple[Attachment, ...]
    evidence_files: tuple[Attachment, ...]


def plan_suppression(
    lead: Lead,
    attachments: Sequence[Attachment],
    *,
    cause: str,
    keep_fields: Collection[str] = frozenset(),
    keep_attachments_of_won: bool = False,
) -> SuppressionPlan:
    """Qué anular y qué archivos borrar (pura). La evidencia solo se reduce por orden del CTO
    (VCRM-165); por plazo se conserva íntegra (VCRM-164)."""
    live = [a for a in attachments if a.deleted_at is None]
    keep_won = keep_attachments_of_won and (lead.state == LeadState.WON or lead.won_at is not None)
    files = tuple(a for a in live if a.kind != "authorization" and not keep_won)
    evidence = tuple(a for a in live if a.kind == "authorization") if cause == ORDER_CAUSE else ()
    nulls = tuple(c for c in PERSONAL_COLUMNS if c not in keep_fields)
    return SuppressionPlan(lead.id, nulls, files, evidence)


def titular_leads(conn: sqlite3.Connection, lead: Lead) -> list[Lead]:
    """Leads del mismo titular (4.5): coincidencia exacta, sin cierre transitivo (K-3)."""
    return repo.titular_leads(conn, lead)


def execute_suppression(
    conn: sqlite3.Connection,
    store: FileStore | None,
    leads: Sequence[Lead],
    *,
    cause: str,
    now: datetime,
    actor: str,
    keys: Sequence[str] = (),
    add_fingerprint: bool,
    keep_fields: Collection[str] = frozenset(),
    basis: str | None = None,
    keep_attachments_of_won: bool = False,
) -> list[int]:
    """Suprime los leads indicados: archivos primero (un fallo → nada se marca) y luego la base
    en la transacción del llamante; encola los avisos de supresión de copias (VCRM-154)."""
    plans: list[tuple[Lead, SuppressionPlan, bool]] = []
    for lead in leads:
        hold = bool(keep_fields) and lead.state in HOLD_STATES  # VCRM-094
        attachments = repo.lead_attachments(conn, lead.id)
        plan = plan_suppression(
            lead,
            attachments,
            cause=cause,
            keep_fields=keep_fields if hold else frozenset(),
            keep_attachments_of_won=keep_attachments_of_won,
        )
        plans.append((lead, plan, hold))
    doomed = [a for _, p, _ in plans for a in (*p.files, *p.evidence_files)]
    if add_fingerprint and not keys:
        raise ValueError("fingerprint keys required to suppress a titular")
    for attachment in doomed:
        if store is None:
            raise SuppressionFailed("no file store configured")
        try:
            store.delete(attachment.storage_key)
        except Exception as exc:  # noqa: BLE001 - cualquier fallo deja todo sin marcar
            raise SuppressionFailed(str(exc)) from exc
    detail = AuditDetail(cause) if cause in AuditDetail._value2member_map_ else None
    for lead, plan, hold in plans:
        if add_fingerprint:  # solo la huella del contacto (VCRM-095)
            for contact in (lead.phone_e164, lead.email):
                if contact is not None:
                    repo.add_suppression(conn, fingerprint(keys[0], contact), at=now, medium=cause)
        changes: dict[str, object] = {c: None for c in plan.null_columns}
        changes.update(suppressed_at=to_iso(now), suppression_cause=cause)
        if hold:
            changes.update(legal_hold_basis=basis, commercial_block=1)
        repo.update_lead(conn, lead.id, changes, now=now)
        repo.purge_lead_records(
            conn,
            lead.id,
            attachment_ids=[a.id for a in (*plan.files, *plan.evidence_files)],
            now=now,
        )
        repo.audit(
            conn,
            actor=actor,
            action=AuditAction.LEAD_SUPPRESSED,
            outcome=AuditOutcome.OK,
            at=now,
            lead_id=lead.id,
            detail=detail,
        )
    _enqueue_suppression_notices(conn, leads, now)
    return [lead.id for lead in leads]


def _enqueue_suppression_notices(
    conn: sqlite3.Connection, leads: Sequence[Lead], now: datetime
) -> None:
    """Una crítica por destinatario y canal, solo con identificadores (VCRM-154)."""
    all_ids = [lead.id for lead in leads]
    accepted = [lead.id for lead in leads if lead.ever_accepted]
    targets: list[tuple[User, Channel, list[int]]] = [
        (u, Channel.TELEGRAM, all_ids) for u in repo.active_users(conn, Role.CTO)
    ]
    if accepted:
        for lawyer in repo.active_users(conn, Role.LAWYER):
            targets += [(lawyer, Channel.TELEGRAM, accepted), (lawyer, Channel.EMAIL, accepted)]
    for user, channel, ids in targets:
        listed = ", ".join(short_id(i) for i in ids)
        body = (
            f"Supresión de datos personales del {format_local(now)}.\n"
            f"Leads: {listed}.\n"
            "Suprima las copias recibidas de estos leads (mensajes, correos y documentos)."
        )
        enqueue_critical(
            conn,
            kind=SUPPRESSION_KIND,
            channel=channel,
            recipient_user_id=user.id,
            lead_id=ids[0],
            subject=f"Supresión de copias: {listed}" if channel == Channel.EMAIL else None,
            body=body,
            key=suppression_key(now, user.id, channel, ids),
            now=now,
        )


def _parse_keep(raw: str) -> frozenset[str] | None:
    names = [n.strip().lower() for n in raw.split(",") if n.strip()]
    if not names or any(n not in KEEP_FIELDS for n in names):
        return None
    return frozenset(c for n in names for c in KEEP_FIELDS[n])


def suppress_command(
    conn: sqlite3.Connection,
    actor: User,
    text: str,
    now: datetime,
    store: FileStore | None,
    keys: Sequence[str],
) -> list[Outgoing]:
    """`/suprimir L-n[; conservar: campos; fundamento: texto]` (solo CTO; VCRM-073, 094)."""
    chat = actor.telegram_id
    invalid = [Outgoing(chat, f"Formato no válido. Ejemplo: {EXAMPLE_SUPPRESS}")]
    match = _SUPPRESS_RE.match(text.strip())
    lead_id = parse_short_id(match.group(1)) if match else None
    if match is None or lead_id is None:
        return invalid
    keep: frozenset[str] = frozenset()
    basis = match.group(3)
    if match.group(2) is not None:
        parsed = _parse_keep(match.group(2))
        if parsed is None:
            return invalid
        keep = parsed
    found = _lead_or_error(conn, actor, lead_id, Action.SUPPRESS, now)
    if isinstance(found, list):
        return found
    if found.suppressed_at is not None:
        return [Outgoing(chat, f"El lead {short_id(found.id)} ya fue suprimido.")]
    group = titular_leads(conn, found)
    holders = [lead.id for lead in group if lead.state in HOLD_STATES]
    if keep and not holders:  # un retractado está en «rechazado»: sin excepción (VCRM-094)
        return [
            Outgoing(
                chat,
                "La conservación por deber legal o contractual solo se admite si algún lead "
                "del titular está en «aceptado» o «ganado». No se suprimió nada.",
            )
        ]
    try:
        ids = execute_suppression(
            conn,
            store,
            group,
            cause=ORDER_CAUSE,
            now=now,
            actor=f"user:{actor.id}",
            keys=keys,
            add_fingerprint=True,
            keep_fields=keep,
            basis=basis,
        )
    except SuppressionFailed:
        return [
            Outgoing(
                chat,
                "No se pudo borrar un archivo; no se suprimió ningún lead. Intente de nuevo.",
            )
        ]
    listed = ", ".join(short_id(i) for i in ids)
    reply = (
        f"Supresión aplicada a {listed} (orden del CTO). Se envió el aviso de supresión "
        "de las copias."
    )
    if keep:
        kept = ", ".join(short_id(i) for i in holders)
        reply += (
            f" Conservados por deber legal en {kept}: {', '.join(sorted(keep))}; "
            f"fundamento: {basis}. Bloqueados para todo uso comercial."
        )
    return [Outgoing(chat, reply)]


# --- Exportación de datos del titular (VCRM-074, 075, 165, 166; decisión K-5) ---------------

TELEGRAM_UPLOAD_LIMIT = 50 * 1024 * 1024  # límite de subida de documentos de la Bot API
PART_MARGIN = 1024 * 1024  # cabeceras ZIP y del multipart
EXPORT_DOC = "ficha.txt"
EXAMPLE_EXPORT = "/exportar L-0042"
NO_STORE = "No hay almacén de archivos configurado; no se puede exportar."
_EXPORT_RE = re.compile(r"^/exportar(?:@\w+)?\s+(\S+)\s*$")

ExportItem = int | str  # id de adjunto o EXPORT_DOC


def plan_export_parts(
    doc_size: int,
    attachments: Sequence[tuple[int, int]],
    limit: int,
    margin: int = PART_MARGIN,
) -> list[list[ExportItem]]:
    """Reparto *first-fit* secuencial por tamaño sin comprimir (pura, determinista; D-13).

    La ficha va en la parte 1; cada adjunto, completo, en una sola parte, en orden de id."""
    cap = limit - margin
    parts: list[list[ExportItem]] = [[EXPORT_DOC]]
    size = doc_size
    for att_id, att_size in sorted(attachments):
        if size + att_size > cap:
            parts.append([])
            size = 0
        parts[-1].append(att_id)
        size += att_size
    return parts


@dataclass(frozen=True)
class ExportJob:
    """Exportación preparada en la transacción; los ZIP se arman y envían tras el *commit*."""

    chat_id: int
    lead_id: int
    document: str
    parts: tuple[tuple[ExportItem, ...], ...]
    members: Mapping[int, tuple[str, str]]  # id de adjunto → (nombre en el ZIP, clave)


def _member_name(attachment: Attachment) -> str:
    suffix = PurePosixPath(attachment.storage_key).suffix
    return f"adjuntos/{attachment.id}_{attachment.kind}{suffix}"


def _local(iso: str) -> str:
    return format_local(from_iso(iso))


def _export_document(
    conn: sqlite3.Connection,
    lead: Lead,
    attachments: Sequence[Attachment],
    now: datetime,
    placement: Mapping[int, str],
) -> str:
    """Documento legible: ficha, handoff, historial, autorizaciones e índice de adjuntos."""
    notes = repo.lead_notes(conn, lead.id)
    events = repo.lead_events(conn, lead.id)
    consents = repo.lead_consents(conn, lead.id)
    reduced = repo.lead_reduced_evidence(conn, lead.id)
    user_ids = {n.author_user_id for n in notes} | {a.author_user_id for a in attachments}
    user_ids |= {e.actor_user_id for e in events} | {int(c["actor_user_id"]) for c in consents}
    authors: dict[int, str] = {}
    for uid in user_ids:
        user = repo.get_user(conn, uid)
        if user is not None:
            authors[uid] = user.email
    card = render_lead_card(
        lead,
        commercial=_assignee(conn, lead),
        notes=notes,
        attachments=attachments,
        alerts=repo.open_alerts(conn, lead_id=lead.id),
        authors=authors,
    )
    lines = [f"Exportación de datos de {short_id(lead.id)} · {format_local(now)}", "", card, ""]
    lines.append("Historial:" if events else "Historial: sin eventos")
    for e in events:
        change = f"{e.field or ''} {e.old_value or NO_VALUE} → {e.new_value or NO_VALUE}".strip()
        extra = "".join(f" · {v}" for v in (e.reason, e.reason_text) if v)
        lines.append(
            f"- {_local(e.at)} · {authors.get(e.actor_user_id, NO_VALUE)} · {e.kind}: "
            f"{change}{extra}"
        )
    lines.append("Autorizaciones:" if consents else "Autorizaciones: ninguna")
    for c in consents:
        evidence = f" · evidencia #{c['attachment_id']}" if c["attachment_id"] else ""
        lines.append(
            f"- {_local(c['at'])} · {c['status']} · medio: {c['medium']} · "
            f"{authors.get(int(c['actor_user_id']), NO_VALUE)}{evidence}"
        )
    for a in reduced:  # VCRM-165: el archivo ya no existe; solo su huella mínima
        lines.append(
            f"- evidencia #{a.id} (huella mínima) · {a.kind} · {_local(a.at)} · "
            f"{a.size_bytes} bytes · SHA-256 {a.sha256}"
        )
    lines.append("Adjuntos incluidos:" if attachments else "Adjuntos incluidos: ninguno")
    for a in attachments:
        where = placement.get(a.id, "")
        lines.append(
            f"- {_member_name(a)}{where} · {_local(a.at)} · {a.size_bytes} bytes · "
            f"SHA-256 {a.sha256}"
        )
    return "\n".join(lines) + "\n"


def export_lead(
    conn: sqlite3.Connection,
    actor: User,
    lead: Lead,
    now: datetime,
    *,
    limit: int = TELEGRAM_UPLOAD_LIMIT,
    margin: int = PART_MARGIN,
) -> ExportJob:
    """Reúne los datos del lead, reparte en partes y audita la exportación (VCRM-074, 075)."""
    attachments = repo.lead_attachments(conn, lead.id)
    draft = _export_document(conn, lead, attachments, now, {})
    sizes = [(a.id, a.size_bytes) for a in attachments]
    parts = plan_export_parts(len(draft.encode("utf-8")), sizes, limit, margin)
    n = len(parts)
    placement: dict[int, str] = {}
    if n > 1:  # índice de qué adjunto va en qué parte (el margen cubre la diferencia)
        for k, part in enumerate(parts, start=1):
            placement.update({int(i): f" · parte {k} de {n}" for i in part if i != EXPORT_DOC})
    document = _export_document(conn, lead, attachments, now, placement) if n > 1 else draft
    repo.audit(
        conn,
        actor=f"user:{actor.id}",
        action=AuditAction.LEAD_EXPORTED,
        outcome=AuditOutcome.OK,
        at=now,
        lead_id=lead.id,
    )
    return ExportJob(
        chat_id=actor.telegram_id,
        lead_id=lead.id,
        document=document,
        parts=tuple(tuple(p) for p in parts),
        members={a.id: (_member_name(a), a.storage_key) for a in attachments},
    )


def export_command(
    conn: sqlite3.Connection,
    actor: User,
    text: str,
    now: datetime,
    store: FileStore | None,
    *,
    limit: int = TELEGRAM_UPLOAD_LIMIT,
    margin: int = PART_MARGIN,
) -> list[Outgoing] | ExportJob:
    """`/exportar L-n` (solo CTO; VCRM-074)."""
    match = _EXPORT_RE.match(text.strip())
    lead_id = parse_short_id(match.group(1)) if match else None
    if lead_id is None:
        return [Outgoing(actor.telegram_id, f"Formato no válido. Ejemplo: {EXAMPLE_EXPORT}")]
    found = _lead_or_error(conn, actor, lead_id, Action.EXPORT, now)
    if isinstance(found, list):
        return found
    if store is None:
        return [Outgoing(actor.telegram_id, NO_STORE)]
    return export_lead(conn, actor, found, now, limit=limit, margin=margin)


def _write_part(job: ExportJob, part: Sequence[ExportItem], path: str, store: FileStore) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in part:
            if item == EXPORT_DOC:
                archive.writestr(EXPORT_DOC, job.document)
                continue
            name, key = job.members[int(item)]
            with store.open(key) as src, archive.open(name, "w") as dst:
                while chunk := src.read(1024 * 1024):
                    dst.write(chunk)


async def deliver_export(
    job: ExportJob, telegram: TelegramPort, store: FileStore
) -> list[Outgoing]:
    """Arma y envía cada parte en orden; un fallo no detiene las siguientes y los temporales
    se borran siempre. Devuelve el aviso al CTO con las partes no entregadas (VCRM-166)."""
    n = len(job.parts)
    sid = short_id(job.lead_id)
    failed: list[int] = []
    for k, part in enumerate(job.parts, start=1):
        name = f"export_{sid}.zip" if n == 1 else f"export_{sid}_parte_{k}_de_{n}.zip"
        caption = f"Exportación de {sid}" + ("" if n == 1 else f" · Parte {k} de {n}")
        folder = store.new_tmp_path()
        path = folder / name
        try:
            folder.mkdir(parents=True)
            _write_part(job, part, str(path), store)
            result = await telegram.send_document(job.chat_id, path, caption)
            delivered = result.delivered
        except Exception:  # noqa: BLE001 - una parte fallida no detiene las demás
            delivered = False
        finally:
            path.unlink(missing_ok=True)
            if folder.exists():
                folder.rmdir()
        if not delivered:
            failed.append(k)
    if not failed:
        return []
    listed = ", ".join(str(k) for k in failed[:-1])
    listed = f"{listed} y {failed[-1]}" if listed else str(failed[-1])
    return [
        Outgoing(
            job.chat_id,
            f"Exportación de {sid}: No se entregaron: {listed} de {n}. "
            f"Repita /exportar {sid} para obtenerla de nuevo.",
        )
    ]


# --- Solicitudes de titulares (VCRM-150, 151, 152; J-05, J-06) ----------------------------

EXAMPLE_REQUEST = "/solicitud L-0042; consulta|reclamo; AAAA-MM-DD; medio"
EXAMPLE_ATTENDED = "/atendida S-0001"
NO_REQUESTS = "No hay solicitudes de titulares abiertas ni vencidas."
REQUEST_ALREADY_ATTENDED = "La solicitud ya estaba marcada «atendida»."
FUTURE_RECEPTION = "La fecha de recepción no puede ser futura."
_REQUEST_RE = re.compile(
    r"^/solicitud(?:@\w+)?\s+([^;\s]+)\s*;\s*(\w+)\s*;\s*(\d{4}-\d{2}-\d{2})\s*;\s*(\S.*?)\s*$"
)
_ATTENDED_RE = re.compile(r"^/atendida(?:@\w+)?\s+[Ss]-(\d+)\s*$")


def request_short_id(request_id: int) -> str:
    return f"S-{request_id:04d}"


def request_due_on(kind: RequestType, received_on: date, params: Params) -> date:
    """Fecha límite en días hábiles desde el día hábil siguiente a la recepción (VCRM-150).

    Los plazos de `params` ya vienen acotados a su tope legal por `effective_params`."""
    days = (
        params.query_deadline_business_days
        if kind is RequestType.INQUIRY
        else params.claim_deadline_business_days
    )
    return add_business_days(received_on, days, params.extra_holidays)


def _date_text(iso_day: str) -> str:
    return date.fromisoformat(iso_day).strftime("%d/%m/%Y")


_REQUEST_TYPE_LABELS: dict[str, str] = {
    RequestType.INQUIRY.value: "consulta",
    RequestType.CLAIM.value: "reclamo",
    RequestType.UNCLASSIFIED.value: "sin clasificar",
}
_REQUEST_STATUS_LABELS: dict[str, str] = {
    RequestStatus.OPEN.value: "abierta",
    RequestStatus.OVERDUE.value: "vencida",
    RequestStatus.ATTENDED.value: "atendida",
}
_REQUEST_TYPE_MAP: dict[str, RequestType] = {
    "consulta": RequestType.INQUIRY,
    "reclamo": RequestType.CLAIM,
    RequestType.INQUIRY.value: RequestType.INQUIRY,
    RequestType.CLAIM.value: RequestType.CLAIM,
}


def request_summary(req: TitularRequest) -> str:
    type_str = _REQUEST_TYPE_LABELS.get(req.type, str(req.type))
    status_str = _REQUEST_STATUS_LABELS.get(req.status, str(req.status))
    return (
        f"{request_short_id(req.id)} · {short_id(req.lead_id)} · {type_str} · "
        f"medio: {req.medium} · "
        f"recibida {_date_text(req.received_on)} · fecha límite {_date_text(req.due_on)} · "
        f"{status_str}"
    )


def _parse_request(text: str) -> tuple[int, RequestType, date, str] | None:
    match = _REQUEST_RE.match(text.strip())
    if match is None:
        return None
    lead_id = parse_short_id(match.group(1))
    try:
        raw_kind = match.group(2).lower()
        if raw_kind not in _REQUEST_TYPE_MAP:
            return None
        kind = _REQUEST_TYPE_MAP[raw_kind]
        received = date.fromisoformat(match.group(3))
    except ValueError:
        return None
    return None if lead_id is None else (lead_id, kind, received, match.group(4))


def request_command(
    conn: sqlite3.Connection, actor: User, text: str, now: datetime, params: Params
) -> list[Outgoing]:
    """`/solicitud L-n; tipo; fecha de recepción; medio` (VCRM-150)."""
    parsed = _parse_request(text)
    if parsed is None:
        return [Outgoing(actor.telegram_id, f"Formato no válido. Ejemplo: {EXAMPLE_REQUEST}")]
    lead_id, kind, received, medium = parsed
    found = _lead_or_error(conn, actor, lead_id, Action.REGISTER_REQUEST, now)
    if isinstance(found, list):
        return found
    if received > local_date(now):
        return [Outgoing(actor.telegram_id, FUTURE_RECEPTION)]
    due = request_due_on(kind, received, params)
    request_id = repo.insert_titular_request(
        conn,
        lead_id=found.id,
        kind=kind,
        medium=medium,
        received_on=received.isoformat(),
        due_on=due.isoformat(),
        registered_by=actor.id,
        now=now,
    )
    repo.add_event(
        conn,
        lead_id=found.id,
        kind=EventKind.TITULAR_REQUEST,
        actor_user_id=actor.id,
        at=now,
        new_value=kind.value,
        reason_text=medium,
    )
    _audit(conn, actor, found.id, now)
    req = repo.get_titular_request(conn, request_id)
    if req is None:  # pragma: no cover - recién insertada en la misma transacción
        raise RuntimeError("titular request not found after insert")
    out = [Outgoing(actor.telegram_id, f"Solicitud registrada: {request_summary(req)}.")]
    if actor.role != Role.CTO:  # se muestra al CTO (no crítica)
        out += [
            Outgoing(cto.telegram_id, f"Nueva solicitud de un titular: {request_summary(req)}.")
            for cto in repo.active_users(conn, Role.CTO)
        ]
    return out


def requests_command(
    conn: sqlite3.Connection, actor: User, text: str, now: datetime
) -> list[Outgoing]:
    """`/solicitudes`: abiertas y vencidas, solo para el CTO."""
    if not authorize(actor, Action.ATTEND_REQUEST, None).allowed:
        return _deny(conn, actor, now)
    pending = repo.titular_requests(conn, (RequestStatus.OPEN, RequestStatus.OVERDUE))
    if not pending:
        return [Outgoing(actor.telegram_id, NO_REQUESTS)]
    lines = ["Solicitudes de titulares:"] + [request_summary(r) for r in pending]
    return [Outgoing(actor.telegram_id, "\n".join(lines))]


def attended_command(
    conn: sqlite3.Connection, actor: User, text: str, now: datetime
) -> list[Outgoing]:
    """`/atendida S-n`: solo CTO; registra autor y fecha y cierra la alerta (VCRM-151, 152)."""
    if not authorize(actor, Action.ATTEND_REQUEST, None).allowed:
        return _deny(conn, actor, now)
    match = _ATTENDED_RE.match(text.strip())
    if match is None:
        return [Outgoing(actor.telegram_id, f"Formato no válido. Ejemplo: {EXAMPLE_ATTENDED}")]
    req = repo.get_titular_request(conn, int(match.group(1)))
    if req is None:
        sid = request_short_id(int(match.group(1)))
        return [Outgoing(actor.telegram_id, f"La solicitud {sid} no existe.")]
    if req.status == RequestStatus.ATTENDED:
        return [Outgoing(actor.telegram_id, REQUEST_ALREADY_ATTENDED)]
    repo.update_titular_request(
        conn,
        req.id,
        {
            "status": RequestStatus.ATTENDED.value,
            "attended_by": actor.id,
            "attended_at": to_iso(now),
        },
    )
    repo.resolve_request_alerts(conn, req.id, resolved_by=actor.id, now=now)
    _audit(conn, actor, req.lead_id, now)
    text = f"{request_short_id(req.id)} ({short_id(req.lead_id)}) marcada «atendida»."
    return [Outgoing(actor.telegram_id, text)]


def request_notice(req: TitularRequest, today: date, params: Params) -> str:
    """Aviso diario al CTO (VCRM-151, 152): id, lead, tipo, recepción y días restantes."""
    remaining = business_days_between(today, date.fromisoformat(req.due_on), params.extra_holidays)
    head = (
        "Solicitud de titular vencida"
        if req.status == RequestStatus.OVERDUE
        else ("Solicitud de titular sin atender")
    )
    type_str = _REQUEST_TYPE_LABELS.get(req.type, str(req.type))
    return (
        f"{head}: {request_short_id(req.id)} · {short_id(req.lead_id)} · {type_str} · "
        f"recibida {_date_text(req.received_on)} · días hábiles restantes: {remaining}. "
        f"Márquela con {EXAMPLE_ATTENDED.split()[0]} {request_short_id(req.id)}."
    )


def _audit(conn: sqlite3.Connection, actor: User, lead_id: int, now: datetime) -> None:
    repo.audit(
        conn,
        actor=f"user:{actor.id}",
        action=AuditAction.LEAD_UPDATED,
        outcome=AuditOutcome.OK,
        at=now,
        lead_id=lead_id,
    )


__all__ = [
    "AUTH_MEDIUM",
    "EXAMPLE_ATTENDED",
    "EXAMPLE_REQUEST",
    "NO_REQUESTS",
    "REQUEST_ALREADY_ATTENDED",
    "EXPORT_DOC",
    "PART_MARGIN",
    "TELEGRAM_UPLOAD_LIMIT",
    "ExportJob",
    "NOT_REGISTERED",
    "ORDER_CAUSE",
    "VALID_MEDIA",
    "SuppressionFailed",
    "SuppressionPlan",
    "answer_evidence",
    "attended_command",
    "authorization_command",
    "deliver_export",
    "execute_suppression",
    "export_command",
    "export_lead",
    "may_contact_commercially",
    "may_request_authorization",
    "opt_out_command",
    "plan_export_parts",
    "plan_suppression",
    "request_command",
    "request_due_on",
    "request_notice",
    "request_short_id",
    "requests_command",
    "suppress_command",
    "titular_leads",
]
