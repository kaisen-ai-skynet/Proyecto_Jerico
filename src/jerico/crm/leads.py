"""Casos de uso de leads: registro, notas, adjuntos y edición con historial (plan §8.2).

Requisitos: VCRM-003, 004, 006, 007, 008, 009, 010, 011, 066, 080–083, 088, 090, 092, 109, 110,
112, 135, 136, 137.
Cada función recibe la conexión de `CrmDatabase.tx()` y `now`, y devuelve los mensajes de
respuesta (`Outgoing`).
"""

import hashlib
import re
import sqlite3
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jerico.crm import repo, team
from jerico.crm.fingerprint import fingerprint
from jerico.crm.handoff import (
    HANDOFF_EDIT_FIELDS,
    LABEL_DOC,
    LABEL_EMAIL,
    LABEL_NAME,
    LABEL_PHONE,
    LABEL_REP,
    LABEL_SERVICE,
    LABEL_TERM,
    LABEL_TYPE,
    LABEL_VALUE,
    REP_IF_COMPANY,
    HandoffValueError,
    missing_handoff_fields,
    name_or_company,
    validate_handoff_value,
)
from jerico.crm.model import (
    Alert,
    AlertKind,
    AuditAction,
    AuditDetail,
    AuditOutcome,
    Channel,
    Confirmation,
    EventKind,
    Lead,
    LeadState,
    Outgoing,
    PendingInput,
    Role,
    User,
)
from jerico.crm.outbox import enqueue_critical
from jerico.crm.parsing import (
    EDITABLE,
    EXAMPLE_EDIT,
    EditCommand,
    ParseError,
    build_callback,
    parse_edit,
    parse_register,
    parse_short_id,
)
from jerico.crm.permissions import Action, Decision, authorize, commercial_recipients, is_visible
from jerico.crm.ports import DownloadResult, FileKind, FileStore, Update
from jerico.crm.render import (
    ATTENDED_LABEL,
    NO_VALUE,
    EmailText,
    RetractionView,
    acceptance_alert_for_lawyer,
    acceptance_email_for_lawyer,
    acceptance_for_cto,
    handoff_error_text,
    handoff_rows,
    handoff_update_email,
    handoff_update_text,
    lawyer_view,
    render_lead_card,
    render_list_page,
    retraction_email,
    retraction_text,
    short_id,
    split_message,
    state_label,
)
from jerico.crm.states import TransitionCheck, check_transition
from jerico.crm.timeutil import format_local, to_iso

AUTH_QUESTION_KIND = "authorization_question"
AUTH_EVIDENCE_KIND = "authorization_evidence"
SUPPRESSED = "Ese contacto solicitó no ser contactado. No se registró el lead."
HIDDEN_DUPLICATE = "El contacto ya está registrado en el sistema; se avisó al CTO."
AUTH_QUESTION = (
    "¿Cuenta con un documento firmado o una captura que pruebe la autorización del titular?"
)
NO_ACCESS = "No tiene permiso para esta acción: no tiene acceso a ese lead."  # VCRM-109
EXAMPLE_NOTE = "/nota L-0042; Llamar el martes para enviar la propuesta"
NOT_SAVED = "No se guardó el archivo."
NOT_MODIFIED = "No se modificó el lead."
EXAMPLE_LIST = "/lista 2"
EXAMPLE_VIEW = "/ver L-0042"
_LIST_RE = re.compile(r"^/lista(?:@\w+)?(?:\s+(\S+))?\s*$")
_VIEW_RE = re.compile(r"^/ver(?:@\w+)?(?:\s+(.*))?$", re.DOTALL)
_NOTE_RE = re.compile(r"^/nota(?:@\w+)?(?:\s+(.*))?$", re.DOTALL)
_FILE_LABELS: dict[str, str] = {"photo": "foto", "document": "documento", "voice": "nota de voz"}
_BASIC_COLUMNS: dict[str, str] = {
    "nombre": "name",
    "telefono": "phone_e164",
    "correo": "email",
    "empresa": "company",
}
_PARSE_MESSAGES = {
    "missing": "Falta el dato: {field}.",
    "invalid": "Dato inválido: {field}.",
}


def _deny(conn: sqlite3.Connection, actor: User, now: datetime) -> list[Outgoing]:
    repo.audit(
        conn,
        actor=f"user:{actor.id}",
        action=AuditAction.PERMISSION_DENIED,
        outcome=AuditOutcome.DENIED,
        at=now,
    )
    return [Outgoing(actor.telegram_id, team.DENIED)]


def deny_lead(
    conn: sqlite3.Connection, actor: User, decision: Decision, lead_id: int, now: datetime
) -> list[Outgoing]:
    """Denegación sobre un lead: si es ajeno, «no tiene acceso» sin datos + auditoría (VCRM-109)."""
    if decision.denial != "foreign_lead":
        return _deny(conn, actor, now)
    repo.audit(
        conn,
        actor=f"user:{actor.id}",
        action=AuditAction.PERMISSION_DENIED,
        outcome=AuditOutcome.DENIED,
        at=now,
        lead_id=lead_id,
        detail=AuditDetail.FOREIGN_LEAD,
    )
    return [Outgoing(actor.telegram_id, NO_ACCESS)]


def _parse_error_text(error: ParseError) -> str:
    template = _PARSE_MESSAGES.get(error.code, "Formato no válido.")
    return f"{template.format(field=error.field)} Ejemplo: {error.example}"


def _assignee(conn: sqlite3.Connection, lead: Lead) -> str:
    user = None if lead.assigned_user_id is None else repo.get_user(conn, lead.assigned_user_id)
    return team.assignee_label(user)


def _visible_duplicate(conn: sqlite3.Connection, actor: User, lead: Lead) -> Outgoing:
    """VCRM-006: id, estado y comercial del existente con «Abrir» y «Cancelar»."""
    text = (
        f"El contacto ya está registrado: {short_id(lead.id)} · estado {state_label(lead.state)} · "
        f"{_assignee(conn, lead)}."
    )
    buttons = (
        (
            ("Abrir lead existente", build_callback("abrir", str(lead.id))),
            ("Cancelar", build_callback("cancelar", str(lead.id))),
        ),
    )
    return Outgoing(actor.telegram_id, text, buttons)


def _cto_notices(
    conn: sqlite3.Connection, actor: User, leads: Sequence[Lead], now: datetime
) -> list[Outgoing]:
    """VCRM-137: aviso no crítico al CTO con botón «Reasignar»."""
    out: list[Outgoing] = []
    for cto in repo.active_users(conn, Role.CTO):
        for lead in leads:
            text = (
                f"Registro duplicado rechazado: {short_id(lead.id)} ({_assignee(conn, lead)}). "
                f"Intentó registrarlo: {team.assignee_label(actor)}. "
                f"Fecha: {format_local(now)}."
            )
            button = (("Reasignar", build_callback("reasignar", str(lead.id))),)
            out.append(Outgoing(cto.telegram_id, text, (button,)))
    return out


def _fingerprints(contacts: Sequence[str], keys: Sequence[str]) -> list[str]:
    return [fingerprint(key, contact) for contact in contacts for key in keys]


def register(
    conn: sqlite3.Connection, actor: User, text: str, now: datetime, keys: Sequence[str]
) -> list[Outgoing]:
    """Orden `/nuevo` (VCRM-003, 004, 006, 066, 088, 110, 135, 137)."""
    if not authorize(actor, Action.REGISTER, None).allowed:
        return _deny(conn, actor, now)
    cmd = parse_register(text)
    if isinstance(cmd, ParseError):
        return [Outgoing(actor.telegram_id, _parse_error_text(cmd))]
    contacts = [c for c in (cmd.phone, cmd.email) if c is not None]
    if repo.any_suppressed(conn, _fingerprints(contacts, keys)):  # VCRM-088 (prevalece)
        return [Outgoing(actor.telegram_id, SUPPRESSED)]
    matches = repo.contact_matches(conn, phone=cmd.phone, email=cmd.email)
    if matches:
        visible = [lead for lead in matches if is_visible(actor, lead)]
        if visible:
            return [_visible_duplicate(conn, actor, lead) for lead in visible]
        return [
            Outgoing(actor.telegram_id, HIDDEN_DUPLICATE),
            *_cto_notices(conn, actor, matches, now),
        ]
    lead_id = repo.insert_lead(
        conn,
        assigned_user_id=actor.id,
        state=LeadState.NEW,
        now=now,
        fields={
            "name": cmd.name,
            "phone_e164": cmd.phone,
            "email": cmd.email,
            "company": cmd.company,
        },
    )
    repo.add_event(
        conn,
        lead_id=lead_id,
        kind=EventKind.STATE,
        actor_user_id=actor.id,
        at=now,
        new_value=LeadState.NEW.value,
    )
    if cmd.note is not None:
        repo.insert_note(conn, lead_id=lead_id, author_user_id=actor.id, body=cmd.note, at=now)
    repo.audit(
        conn,
        actor=f"user:{actor.id}",
        action=AuditAction.LEAD_CREATED,
        outcome=AuditOutcome.OK,
        at=now,
        lead_id=lead_id,
    )
    conf_id = repo.create_confirmation(
        conn, kind=AUTH_QUESTION_KIND, lead_id=lead_id, user_id=actor.id, now=now
    )
    lines = [
        f"Lead {short_id(lead_id)} registrado (estado {LeadState.NEW.value}).",
        f"Nombre: {cmd.name}",
        f"Teléfono: {cmd.phone or NO_VALUE}",
        f"Correo: {cmd.email or NO_VALUE}",
        f"Empresa: {cmd.company or NO_VALUE}",
        f"Nota: {cmd.note or NO_VALUE}",
        AUTH_QUESTION,
    ]
    buttons = (
        (
            ("Sí", build_callback("conf", str(conf_id), "si")),
            ("No", build_callback("conf", str(conf_id), "no")),
        ),
    )
    return [Outgoing(actor.telegram_id, "\n".join(lines), buttons)]


def answer_authorization(
    conn: sqlite3.Connection, actor: User, conf: Confirmation, yes: bool, now: datetime
) -> list[Outgoing]:
    """Respuesta a la pregunta de autorización (VCRM-066); «No» deja «sin autorización»."""
    sid = short_id(conf.lead_id)
    if not yes:
        return [Outgoing(actor.telegram_id, f"{sid} queda «sin autorización».")]
    lead = repo.get_lead(conn, conf.lead_id)
    if lead is None or not authorize(actor, Action.REGISTER_AUTH, lead).allowed:
        return _deny(conn, actor, now)
    repo.set_pending_input(
        conn, user_id=actor.id, kind=AUTH_EVIDENCE_KIND, now=now, lead_id=lead.id
    )
    text = f"Adjunte ahora el documento firmado o la captura (foto o documento) para {sid}."
    return [Outgoing(actor.telegram_id, text)]


def open_existing(
    conn: sqlite3.Connection, actor: User, lead_id: int, now: datetime
) -> list[Outgoing]:
    """Botón «Abrir lead existente» (VCRM-006): resumen del lead si es visible."""
    lead = repo.get_lead(conn, lead_id)
    if lead is None:
        return [Outgoing(actor.telegram_id, f"El lead {short_id(lead_id)} no existe.")]
    decision = authorize(actor, Action.VIEW, lead)
    if not decision.allowed:
        return deny_lead(conn, actor, decision, lead.id, now)
    lines = [
        f"{short_id(lead.id)} · {lead.name or NO_VALUE} · estado {lead.state}",
        f"Comercial: {_assignee(conn, lead)}",
        f"Teléfono: {lead.phone_e164 or NO_VALUE}",
        f"Correo: {lead.email or NO_VALUE}",
    ]
    return [Outgoing(actor.telegram_id, "\n".join(lines))]


# --- Notas (VCRM-009) -------------------------------------------------------------------


def _audit_update(conn: sqlite3.Connection, actor: User, lead_id: int, now: datetime) -> None:
    repo.audit(
        conn,
        actor=f"user:{actor.id}",
        action=AuditAction.LEAD_UPDATED,
        outcome=AuditOutcome.OK,
        at=now,
        lead_id=lead_id,
    )


def add_note(conn: sqlite3.Connection, actor: User, text: str, now: datetime) -> list[Outgoing]:
    """Orden `/nota L-n; texto`: nota con autor y fecha en el historial (VCRM-009, 109)."""
    if not authorize(actor, Action.NOTE_ATTACH, None).allowed:
        return _deny(conn, actor, now)
    match = _NOTE_RE.match(text.strip())
    parts = (match.group(1) or "").split(";", 1) if match else []
    lead_id = parse_short_id(parts[0]) if parts else None
    body = parts[1].strip() if len(parts) == 2 else ""
    if lead_id is None or not body:
        return [Outgoing(actor.telegram_id, f"Formato no válido. Ejemplo: {EXAMPLE_NOTE}")]
    lead = repo.get_lead(conn, lead_id)
    if lead is None:
        return [Outgoing(actor.telegram_id, f"El lead {short_id(lead_id)} no existe.")]
    decision = authorize(actor, Action.NOTE_ATTACH, lead)
    if not decision.allowed:
        return deny_lead(conn, actor, decision, lead.id, now)
    repo.insert_note(conn, lead_id=lead.id, author_user_id=actor.id, body=body, at=now)
    repo.update_lead(conn, lead.id, {}, now=now)  # última interacción
    _audit_update(conn, actor, lead.id, now)
    text_out = f"Nota agregada a {short_id(lead.id)} por {actor.email} el {format_local(now)}."
    return [Outgoing(actor.telegram_id, text_out)]


# --- Adjuntos (VCRM-007, 008) -----------------------------------------------------------


@dataclass(frozen=True)
class Prefetched:
    """Archivo descargado a un temporal antes de la transacción (plan §7)."""

    kind: FileKind
    path: Path
    result: DownloadResult


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add_attachment(
    conn: sqlite3.Connection,
    actor: User,
    caption: str | None,
    file: Prefetched,
    store: FileStore,
    now: datetime,
) -> list[Outgoing]:
    """Foto, documento o voz con `L-n` en el pie; nunca deja un adjunto parcial (VCRM-007, 008)."""
    chat = actor.telegram_id
    if not authorize(actor, Action.NOTE_ATTACH, None).allowed:
        return _deny(conn, actor, now)
    tokens = (caption or "").split()
    lead_id = parse_short_id(tokens[0]) if tokens else None
    if lead_id is None:
        text = f"Indique el lead en el pie del archivo (por ejemplo, L-0042). {NOT_SAVED}"
        return [Outgoing(chat, text)]
    lead = repo.get_lead(conn, lead_id)
    if lead is None:
        return [Outgoing(chat, f"El lead {short_id(lead_id)} no existe. {NOT_SAVED}")]
    if not file.result.ok:
        if file.result.error == "too_large":
            return [Outgoing(chat, f"El archivo supera el límite de 20 MB. {NOT_SAVED}")]
        return [Outgoing(chat, f"No se pudo descargar el archivo. {NOT_SAVED} Intente de nuevo.")]
    decision = authorize(actor, Action.NOTE_ATTACH, lead)
    if not decision.allowed:
        return deny_lead(conn, actor, decision, lead.id, now)
    digest = _sha256(file.path)
    key = store.save_atomic(lead.id, file.path)
    try:
        repo.insert_attachment(
            conn,
            lead_id=lead.id,
            kind=file.kind,
            author_user_id=actor.id,
            at=now,
            storage_key=key,
            size_bytes=file.result.size,
            sha256=digest,
        )
        _audit_update(conn, actor, lead.id, now)
    except Exception:
        store.delete(key)  # sin adjunto parcial
        raise
    label = _FILE_LABELS.get(file.kind, file.kind)
    text = (
        f"Adjunto ({label}) asociado a {short_id(lead.id)} por {actor.email} "
        f"el {format_local(now)}."
    )
    return [Outgoing(chat, text)]


# --- Edición con historial (VCRM-080 a 083, 112) ----------------------------------------


def _editable_line() -> str:
    return "Campos editables: " + ", ".join(EDITABLE) + "."


def _requested_field(text: str) -> str | None:
    parts = text.split(";", 2)
    if len(parts) < 2:
        return None
    decomposed = unicodedata.normalize("NFKD", parts[1].strip().lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _edit_error_text(text: str, error: ParseError) -> str:
    if error.code == "missing":
        field = _requested_field(text)
        if field in HANDOFF_EDIT_FIELDS:
            empty = validate_handoff_value(field, "")
            if isinstance(empty, HandoffValueError):
                return handoff_error_text(empty)
        return f"Falta el dato: valor. {NOT_MODIFIED} Ejemplo: {EXAMPLE_EDIT}"
    if error.code == "invalid":
        return f"Dato inválido: {error.field}. {NOT_MODIFIED} Ejemplo: {EXAMPLE_EDIT}"
    if error.code == "field_not_editable":
        cause = f"El campo «{error.field}» no es editable."
    else:
        cause = "Indique el lead (L-n), el campo y el valor."
    return f"{cause} {NOT_MODIFIED} {_editable_line()} Ejemplo: {EXAMPLE_EDIT}"


def _contact_conflict(
    conn: sqlite3.Connection, actor: User, lead: Lead, cmd: EditCommand, keys: Sequence[str]
) -> str | None:
    """Huella suprimida o duplicado no «perdido» (id solo si es visible) (VCRM-083)."""
    if cmd.field not in ("telefono", "correo"):
        return None
    if repo.any_suppressed(conn, _fingerprints([cmd.value], keys)):
        return f"Ese contacto solicitó no ser contactado. {NOT_MODIFIED}"
    phone = cmd.value if cmd.field == "telefono" else None
    email = cmd.value if cmd.field == "correo" else None
    others = [m for m in repo.contact_matches(conn, phone=phone, email=email) if m.id != lead.id]
    if not others:
        return None
    visible = [short_id(m.id) for m in others if is_visible(actor, m)]
    target = f"el lead {', '.join(visible)}" if visible else "otro lead registrado"
    return f"El valor de «{cmd.field}» coincide con {target}. {NOT_MODIFIED}"


def _joined(values: Iterable[str | None]) -> str | None:
    present = [v for v in values if v]
    return " ".join(present) if present else None


def edit(
    conn: sqlite3.Connection, actor: User, text: str, now: datetime, keys: Sequence[str]
) -> list[Outgoing]:
    """Orden `/editar L-n; campo; valor` con evento de historial (VCRM-080–083, 109, 112)."""
    chat = actor.telegram_id
    if not authorize(actor, Action.EDIT, None).allowed:
        return _deny(conn, actor, now)
    cmd = parse_edit(text)
    if isinstance(cmd, ParseError):
        return [Outgoing(chat, _edit_error_text(text, cmd))]
    lead = repo.get_lead(conn, cmd.short_id)
    if lead is None:
        sid = short_id(cmd.short_id)
        return [Outgoing(chat, f"El lead {sid} no existe. {NOT_MODIFIED} {_editable_line()}")]
    decision = authorize(actor, Action.EDIT, lead)
    if not decision.allowed:
        return deny_lead(conn, actor, decision, lead.id, now)
    changes: dict[str, str]
    if cmd.field in HANDOFF_EDIT_FIELDS:
        checked = validate_handoff_value(cmd.field, cmd.value)
        if isinstance(checked, HandoffValueError):
            return [Outgoing(chat, handoff_error_text(checked))]
        changes = checked
    else:
        changes = {_BASIC_COLUMNS[cmd.field]: cmd.value}
        conflict = _contact_conflict(conn, actor, lead, cmd, keys)
        if conflict is not None:
            return [Outgoing(chat, conflict)]
    old = _joined(getattr(lead, column) for column in changes)
    new = _joined(changes.values())
    repo.update_lead(conn, lead.id, changes, now=now)
    event_id = repo.add_event(
        conn,
        lead_id=lead.id,
        kind=EventKind.FIELD,
        actor_user_id=actor.id,
        at=now,
        field=cmd.field,
        old_value=old,
        new_value=new,
    )
    _audit_update(conn, actor, lead.id, now)
    text_out = (
        f"{short_id(lead.id)}: campo «{cmd.field}» actualizado. "
        f"Anterior: {old or NO_VALUE}. Nuevo: {new}."
    )
    if _notify_handoff_update(conn, lead, cmd.field, event_id, now):  # VCRM-084
        text_out += " Se notificó al CTO y al abogado."
    return [Outgoing(chat, text_out)]


# --- Lista y ficha (VCRM-010, 011, 090, 092, 136) ---------------------------------------


def visible_leads(
    conn: sqlite3.Connection, actor: User, *, include_suppressed: bool = False
) -> list[Lead]:
    """Leads visibles para el rol, por última interacción descendente (VCRM-010).

    Por defecto excluye los leads suprimidos del listado (VCRM-073; observación d).
    """
    return [
        lead
        for lead in repo.all_leads(conn, exclude_suppressed=not include_suppressed)
        if (include_suppressed or lead.suppressed_at is None) and is_visible(actor, lead)
    ]


def list_page(conn: sqlite3.Connection, actor: User, page: int, now: datetime) -> list[Outgoing]:
    """Página de la lista; al CTO le marca los leads «sin comercial asignado» (VCRM-090, 092).

    Todos los roles pueden listar (matriz §4.4); `visible_leads` aplica el alcance."""
    listed = visible_leads(conn, actor)
    unassigned: set[int] = set()
    alerted: set[int] = set()
    if actor.role == Role.CTO:
        alerted = {a.lead_id for a in repo.open_alerts(conn) if a.lead_id is not None}  # 087
        users: dict[int, User | None] = {}
        for lead in listed:
            uid = lead.assigned_user_id
            if uid is not None and uid not in users:
                users[uid] = repo.get_user(conn, uid)
            if team.assignee_label(None if uid is None else users[uid]) == team.UNASSIGNED:
                unassigned.add(lead.id)
    rendered = render_list_page(listed, page, unassigned=unassigned, alerted=alerted)
    buttons = (rendered.buttons,) if rendered.buttons else ()
    return [Outgoing(actor.telegram_id, rendered.text, buttons)]


def _suppression_alert_details(conn: sqlite3.Connection, alerts: list[Alert]) -> dict[int, str]:
    """Destinatario y canal del aviso de supresión fallido (VCRM-155)."""
    details: dict[int, str] = {}
    for alert in alerts:
        if alert.kind != AlertKind.SUPPRESSION_NOTICE_FAILED or alert.outbox_id is None:
            continue
        item = repo.get_outbox(conn, alert.outbox_id)
        if item is None:
            continue
        user = repo.get_user(conn, item.recipient_user_id)
        who = user.email if user is not None else f"usuario {item.recipient_user_id}"
        details[alert.id] = f"destinatario: {who} · canal: {item.channel}"
    return details


def list_command(conn: sqlite3.Connection, actor: User, text: str, now: datetime) -> list[Outgoing]:
    """Orden `/lista [página]`."""
    match = _LIST_RE.match(text.strip())
    raw = match.group(1) if match else ""
    if raw is not None and not raw.isdigit():
        return [Outgoing(actor.telegram_id, f"Formato no válido. Ejemplo: {EXAMPLE_LIST}")]
    return list_page(conn, actor, 1 if raw is None else int(raw), now)


def view_lead(conn: sqlite3.Connection, actor: User, text: str, now: datetime) -> list[Outgoing]:
    """Orden `/ver L-n`: ficha completa si el lead es visible; si no, «no tiene acceso»."""
    match = _VIEW_RE.match(text.strip())
    lead_id = parse_short_id(match.group(1) or "") if match else None
    if lead_id is None:
        return [Outgoing(actor.telegram_id, f"Formato no válido. Ejemplo: {EXAMPLE_VIEW}")]
    lead = repo.get_lead(conn, lead_id)
    if lead is None:
        return [Outgoing(actor.telegram_id, f"El lead {short_id(lead_id)} no existe.")]
    decision = authorize(actor, Action.VIEW, lead)
    if not decision.allowed:
        return deny_lead(conn, actor, decision, lead.id, now)
    notes = repo.lead_notes(conn, lead.id)
    attachments = repo.lead_attachments(conn, lead.id)
    authors: dict[int, str] = {}
    for uid in {n.author_user_id for n in notes} | {a.author_user_id for a in attachments}:
        user = repo.get_user(conn, uid)
        if user is not None:
            authors[uid] = user.email
    alerts = repo.open_alerts(conn, lead_id=lead.id)
    card = render_lead_card(
        lead,
        commercial=_assignee(conn, lead),
        notes=notes,
        attachments=attachments,
        alerts=alerts,
        authors=authors,
        alert_details=_suppression_alert_details(conn, alerts),
    )
    buttons = state_buttons(actor, lead)
    if actor.role == Role.CTO:  # VCRM-087: «Atendida por otro medio», solo CTO
        buttons += tuple(
            ((f"{ATTENDED_LABEL} ({n})", build_callback("atendida", str(a.id))),)
            for n, a in enumerate(alerts, start=1)
        )
    chunks = split_message(card)
    out = [Outgoing(actor.telegram_id, chunk) for chunk in chunks[:-1]]
    return [*out, Outgoing(actor.telegram_id, chunks[-1], buttons)]


# --- Transiciones (VCRM-014–017, 089, 115–118, 132–134) ---------------------------------

REJECT_REASONS: dict[str, str] = {  # matriz de motivos (PR-13)
    "precio": "Precio o presupuesto",
    "momento": "Momento no oportuno",
    "proveedor": "Ya tiene proveedor",
    "no_interesado": "No interesado",
    "otro": "Otro",
}
REJECT_TEXT_KIND = "reject_other"
OTHER_REASON = "otro"
WON_RESERVED = "No se aplicó: marcar «ganado» corresponde al CTO o al abogado."  # VCRM-134
USE_RETRACTION = "No se aplicó: un lead «aceptado» sale de ese estado con la retractación."
RETRACT_LABEL = "Retractar"  # botón de la ficha (VCRM-163)
# Botón de la ficha: operación → (etiqueta, destino).
STATE_OPS: dict[str, tuple[str, LeadState]] = {
    "contacto": ("Registrar contacto", LeadState.CONTACTED),
    "aceptar": ("Aceptar", LeadState.ACCEPTED),  # pide confirmación ✅/❌ (VCRM-046)
    "rechazo": ("Rechazar", LeadState.REJECTED),
    "ganado": ("Ganado", LeadState.WON),
    "perdido": ("Perdido", LeadState.LOST),
}
_TARGET_ACTIONS: dict[LeadState, Action] = {
    LeadState.CONTACTED: Action.CONTACT_REJECT,
    LeadState.REJECTED: Action.CONTACT_REJECT,
    LeadState.ACCEPTED: Action.ACCEPT,
    LeadState.WON: Action.MARK_WON,
    LeadState.LOST: Action.MARK_LOST,
    LeadState.OPTED_OUT: Action.REGISTER_OPT_OUT,
}


def state_buttons(actor: User, lead: Lead) -> tuple[tuple[tuple[str, str], ...], ...]:
    """Botones de estado de la ficha: solo transiciones válidas y permitidas al usuario."""
    row = tuple(
        (label, build_callback("estado", op, str(lead.id)))
        for op, (label, dst) in STATE_OPS.items()
        if check_transition(LeadState(lead.state), dst).ok
        and not (lead.state == LeadState.ACCEPTED and dst is LeadState.REJECTED)
        and authorize(actor, _TARGET_ACTIONS[dst], lead).allowed
    )
    if lead.state == LeadState.ACCEPTED and authorize(actor, Action.RETRACT, lead).allowed:
        row += ((RETRACT_LABEL, build_callback("retractar", str(lead.id))),)  # VCRM-163
    return (row,) if row else ()


def _reason_prompt(actor: User, lead_id: int) -> Outgoing:
    row = tuple(
        (label, build_callback("motivo", str(lead_id), code))
        for code, label in REJECT_REASONS.items()
    )
    return Outgoing(
        actor.telegram_id, f"Elija el motivo de rechazo de {short_id(lead_id)}:", (row,)
    )


def _ask_other_text(conn: sqlite3.Connection, actor: User, lead_id: int, now: datetime) -> Outgoing:
    repo.set_pending_input(conn, user_id=actor.id, kind=REJECT_TEXT_KIND, now=now, lead_id=lead_id)
    return Outgoing(actor.telegram_id, f"Escriba el motivo de rechazo de {short_id(lead_id)}.")


def _invalid_transition_text(src: LeadState, dst: LeadState, check: TransitionCheck) -> str:
    valid = ", ".join(state_label(s) for s in check.valid_targets) or "ninguna"
    src_l, dst_l = state_label(src), state_label(dst)
    return (
        f"No se aplicó la transición: desde «{src_l}» no se puede pasar a «{dst_l}». "
        f"Transiciones válidas: {valid}."
    )


def transition(
    conn: sqlite3.Connection,
    actor: User,
    lead_id: int,
    dst: LeadState,
    now: datetime,
    *,
    reason: str | None = None,
    reason_text: str | None = None,
) -> list[Outgoing]:
    """Aplica una transición con permiso, validez y motivo; la registra en el historial."""
    lead = repo.get_lead(conn, lead_id)
    if lead is None:
        return [Outgoing(actor.telegram_id, f"El lead {short_id(lead_id)} no existe.")]
    decision = authorize(actor, _TARGET_ACTIONS[dst], lead)
    if not decision.allowed:
        if dst is LeadState.WON and actor.role == Role.COMMERCIAL:  # VCRM-134
            repo.audit(
                conn,
                actor=f"user:{actor.id}",
                action=AuditAction.PERMISSION_DENIED,
                outcome=AuditOutcome.DENIED,
                at=now,
                lead_id=lead.id,
            )
            return [Outgoing(actor.telegram_id, WON_RESERVED)]
        return deny_lead(conn, actor, decision, lead.id, now)
    src = LeadState(lead.state)
    check = check_transition(src, dst)
    if check.error_code == "requires_retraction":  # VCRM-133
        text = f"No se aplicó: primero debe registrarse la retractación de {short_id(lead.id)}."
        return [Outgoing(actor.telegram_id, text)]
    if not check.ok:  # VCRM-014, 117
        return [Outgoing(actor.telegram_id, _invalid_transition_text(src, dst, check))]
    changes: dict[str, str | None] = {"state": dst.value}
    if dst is LeadState.REJECTED:
        if src is LeadState.ACCEPTED:
            return [Outgoing(actor.telegram_id, USE_RETRACTION)]
        if reason not in REJECT_REASONS:  # VCRM-016
            return [_reason_prompt(actor, lead.id)]
        reason_text = (reason_text or "").strip() or None
        if reason == OTHER_REASON and reason_text is None:  # VCRM-017
            return [_ask_other_text(conn, actor, lead.id, now)]
        changes |= {"reject_reason": reason, "reject_text": reason_text}
    else:
        reason = reason_text = None
    if dst is LeadState.WON:
        changes["won_at"] = to_iso(now)
    if dst is LeadState.LOST:
        changes["final_state_at"] = to_iso(now)
        repo.cancel_pending_confirmations(conn, lead.id, now)  # VCRM-116
    repo.update_lead(conn, lead.id, changes, now=now)
    repo.add_event(  # VCRM-015; sin próxima acción en F1 (VCRM-118)
        conn,
        lead_id=lead.id,
        kind=EventKind.STATE,
        actor_user_id=actor.id,
        at=now,
        old_value=src.value,
        new_value=dst.value,
        reason=reason,
        reason_text=reason_text,
    )
    _audit_update(conn, actor, lead.id, now)
    detail = f" (motivo: {reason})" if reason else ""
    text = f"{short_id(lead.id)}: estado «{state_label(src)}» → «{state_label(dst)}»{detail}."
    out = [Outgoing(actor.telegram_id, text)]
    if dst is LeadState.REJECTED:
        from jerico.crm import followup

        if followup.f2_active(conn):
            up_lead = repo.get_lead(conn, lead.id)
            if up_lead is not None:
                out.extend(followup.start_cadence(conn, up_lead, now))
    return out


def answer_reject_text(
    conn: sqlite3.Connection, actor: User, pending: PendingInput, update: Update, now: datetime
) -> list[Outgoing]:
    """Texto del motivo «otro» (VCRM-017); vacío → no transiciona y lo vuelve a pedir."""
    if pending.lead_id is None:  # pragma: no cover - siempre se guarda con lead
        return []
    text = (update.text or update.caption or "").strip()
    return transition(
        conn,
        actor,
        pending.lead_id,
        LeadState.REJECTED,
        now,
        reason=OTHER_REASON,
        reason_text=text,
    )


# --- Aceptación con confirmación y handoff (VCRM-046–048, 051, 052, 104, 111, 156) -----------

ACCEPT_KIND = "accept"
ACCEPT_NOTICE_KIND = "aceptacion"


def _already_accepted(actor: User, lead_id: int) -> list[Outgoing]:
    text = f"El lead {short_id(lead_id)} ya estaba aceptado; no se repitieron las notificaciones."
    return [Outgoing(actor.telegram_id, text)]


def _commercial(conn: sqlite3.Connection, lead: Lead) -> str:
    user = None if lead.assigned_user_id is None else repo.get_user(conn, lead.assigned_user_id)
    return user.email if user is not None and user.active else team.UNASSIGNED


def request_accept(
    conn: sqlite3.Connection, actor: User, lead_id: int, now: datetime
) -> list[Outgoing]:
    """Muestra el resumen del lead y pide confirmación ✅/❌; no transiciona (VCRM-046)."""
    lead = repo.get_lead(conn, lead_id)
    if lead is None:
        return [Outgoing(actor.telegram_id, f"El lead {short_id(lead_id)} no existe.")]
    decision = authorize(actor, Action.ACCEPT, lead)
    if not decision.allowed:
        return deny_lead(conn, actor, decision, lead.id, now)
    src = LeadState(lead.state)
    if src is LeadState.ACCEPTED:  # VCRM-051
        return _already_accepted(actor, lead.id)
    check = check_transition(src, LeadState.ACCEPTED)
    if not check.ok:
        text = _invalid_transition_text(src, LeadState.ACCEPTED, check)
        return [Outgoing(actor.telegram_id, text)]
    conf_id = repo.create_confirmation(
        conn, kind=ACCEPT_KIND, lead_id=lead.id, user_id=actor.id, now=now
    )
    missing = missing_handoff_fields(lead)
    lines = [
        f"¿Confirma la aceptación de {short_id(lead.id)}?",
        f"Nombre o razón social: {name_or_company(lead) or lead.name or NO_VALUE}",
        f"Comercial: {_commercial(conn, lead)}",
        f"Estado actual: {src}",
        "Handoff:",
        *(f"- {label}: {value}" for label, value in handoff_rows(lead)),
        "Faltantes: " + (", ".join(missing) if missing else "ninguno"),
    ]
    buttons = (
        (
            ("✅", build_callback("conf", str(conf_id), "si")),
            ("❌", build_callback("conf", str(conf_id), "no")),
        ),
    )
    return [Outgoing(actor.telegram_id, "\n".join(lines), buttons)]


def repeated_accept(
    conn: sqlite3.Connection, actor: User, conf: Confirmation
) -> list[Outgoing] | None:
    """✅ repetido sobre una confirmación resuelta: «ya estaba aceptado» si lo está (VCRM-051)."""
    lead = repo.get_lead(conn, conf.lead_id)
    if lead is None or lead.state != LeadState.ACCEPTED:
        return None
    return _already_accepted(actor, lead.id)


def confirm_accept(
    conn: sqlite3.Connection, actor: User, conf: Confirmation, yes: bool, now: datetime
) -> list[Outgoing]:
    """✅ transiciona, marca `ever_accepted` y encola las 3 críticas; ❌ no aplica nada."""
    sid = short_id(conf.lead_id)
    if not yes:
        return [Outgoing(actor.telegram_id, f"No se aplicó la aceptación de {sid}.")]
    lead = repo.get_lead(conn, conf.lead_id)
    if lead is None:
        return [Outgoing(actor.telegram_id, f"El lead {sid} no existe.")]
    if lead.state == LeadState.ACCEPTED:  # VCRM-051
        return _already_accepted(actor, lead.id)
    out = transition(conn, actor, lead.id, LeadState.ACCEPTED, now)
    accepted = repo.get_lead(conn, lead.id)
    if accepted is None or accepted.state != LeadState.ACCEPTED:
        return out
    repo.update_lead(conn, lead.id, {"ever_accepted": 1}, now=now)
    event_id = repo.lead_events(conn, lead.id)[-1].id
    commercial = _commercial(conn, accepted)
    accepted_at = format_local(now)
    notes = [note.body for note in repo.lead_notes(conn, lead.id)]
    view = lawyer_view(accepted, commercial=commercial, accepted_at=accepted_at)
    email = acceptance_email_for_lawyer(view)
    messages: list[tuple[User, Channel, str | None, str]] = [
        (
            cto,
            Channel.TELEGRAM,
            None,
            acceptance_for_cto(
                accepted, commercial=commercial, accepted_at=accepted_at, notes=notes
            ),
        )
        for cto in repo.active_users(conn, Role.CTO)
    ]
    for lawyer in repo.active_users(conn, Role.LAWYER):  # VCRM-156: solo LawyerView
        messages.append((lawyer, Channel.TELEGRAM, None, acceptance_alert_for_lawyer(view)))
        messages.append((lawyer, Channel.EMAIL, email.subject, email.body))
    for user, channel, subject, body in messages:  # VCRM-047
        enqueue_critical(
            conn,
            kind=ACCEPT_NOTICE_KIND,
            channel=channel,
            recipient_user_id=user.id,
            lead_id=lead.id,
            subject=subject,
            body=body,
            key=f"accept:{lead.id}:{event_id}:{channel}:{user.id}",
            now=now,
        )
    out = [Outgoing(o.chat_id, f"{o.text} Se notificó al CTO y al abogado.") for o in out]
    if view.missing:  # VCRM-052: petición no crítica al comercial del lead (o al CTO)
        text = (
            f"Faltan campos del handoff de {sid}: {', '.join(view.missing)}. "
            "Complételos con /editar."
        )
        for user in commercial_recipients(accepted, repo.active_users(conn)):
            out.append(Outgoing(user.telegram_id, text))
    return out


# --- Retractación y actualización del handoff (VCRM-084, 113, 114, 131, 156) ---------------

RETRACT_KIND = "retract"
RETRACT_TEXT_KIND = "retract_other"
RETRACT_NOTICE_KIND = "retractacion"
HANDOFF_NOTICE_KIND = "handoff"
EXAMPLE_RETRACT = "/retractar L-0042"
_RETRACT_RE = re.compile(r"^/retractar(?:@\w+)?(?:\s+(.*))?$", re.DOTALL)
# Campo de «/editar» → etiqueta del handoff que completa (§4.3).
_FIELD_LABELS: dict[str, str] = {
    "nombre": LABEL_NAME,
    "empresa": LABEL_NAME,
    "tipo": LABEL_TYPE,
    "documento": LABEL_DOC,
    "representante": LABEL_REP,
    "telefono": LABEL_PHONE,
    "correo": LABEL_EMAIL,
    "servicio": LABEL_SERVICE,
    "valor": LABEL_VALUE,
    "plazo": LABEL_TERM,
}


def _enqueue_for_cto_and_lawyers(
    conn: sqlite3.Connection,
    *,
    kind: str,
    key_prefix: str,
    lead_id: int,
    event_id: int,
    text: str,
    email: EmailText,
    now: datetime,
) -> None:
    """Críticas por los canales de la aceptación: CTO/telegram, abogado/telegram y correo."""
    messages: list[tuple[User, Channel, str | None, str]] = [
        (cto, Channel.TELEGRAM, None, text) for cto in repo.active_users(conn, Role.CTO)
    ]
    for lawyer in repo.active_users(conn, Role.LAWYER):
        messages.append((lawyer, Channel.TELEGRAM, None, text))
        messages.append((lawyer, Channel.EMAIL, email.subject, email.body))
    for user, channel, subject, body in messages:
        enqueue_critical(
            conn,
            kind=kind,
            channel=channel,
            recipient_user_id=user.id,
            lead_id=lead_id,
            subject=subject,
            body=body,
            key=f"{key_prefix}:{lead_id}:{event_id}:{channel}:{user.id}",
            now=now,
        )


def _missing_labels(lead: Lead) -> set[str]:
    return {LABEL_REP if m == REP_IF_COMPANY else m for m in missing_handoff_fields(lead)}


def _notify_handoff_update(
    conn: sqlite3.Connection, before: Lead, field: str, event_id: int, now: datetime
) -> bool:
    """Si se completó un campo faltante de un «aceptado», encola las críticas (VCRM-084)."""
    label = _FIELD_LABELS[field]
    after = repo.get_lead(conn, before.id)
    if (
        after is None
        or before.state != LeadState.ACCEPTED
        or label not in _missing_labels(before)
        or label in _missing_labels(after)
    ):
        return False
    view = lawyer_view(after, commercial=_commercial(conn, after), accepted_at=NO_VALUE)
    _enqueue_for_cto_and_lawyers(  # VCRM-156: solo campos del handoff
        conn,
        kind=HANDOFF_NOTICE_KIND,
        key_prefix=HANDOFF_NOTICE_KIND,
        lead_id=after.id,
        event_id=event_id,
        text=handoff_update_text(view, (label,)),
        email=handoff_update_email(view, (label,)),
        now=now,
    )
    return True


def _retract_reason_prompt(actor: User, lead_id: int) -> Outgoing:
    row = tuple(
        (label, build_callback("rmotivo", str(lead_id), code))
        for code, label in REJECT_REASONS.items()
    )
    text = f"Elija el motivo de la retractación de {short_id(lead_id)}:"
    return Outgoing(actor.telegram_id, text, (row,))


def _reason_label(reason: str, reason_text: str | None) -> str:
    label = REJECT_REASONS.get(reason, reason)
    return f"{label}: {reason_text}" if reason_text else label


def request_retract(
    conn: sqlite3.Connection,
    actor: User,
    lead_id: int,
    now: datetime,
    *,
    reason: str | None = None,
    reason_text: str | None = None,
) -> list[Outgoing]:
    """Pide motivo por botones y luego confirmación ✅/❌; no transiciona (VCRM-131, 114)."""
    chat = actor.telegram_id
    lead = repo.get_lead(conn, lead_id)
    if lead is None:
        return [Outgoing(chat, f"El lead {short_id(lead_id)} no existe.")]
    decision = authorize(actor, Action.RETRACT, lead)
    if not decision.allowed:
        return deny_lead(conn, actor, decision, lead.id, now)
    sid = short_id(lead.id)
    if lead.state != LeadState.ACCEPTED:
        text = f"No se aplicó: solo un lead «aceptado» admite retractación ({sid})."
        return [Outgoing(chat, text)]
    if reason not in REJECT_REASONS:  # VCRM-114
        return [_retract_reason_prompt(actor, lead.id)]
    reason_text = (reason_text or "").strip() or None
    if reason == OTHER_REASON and reason_text is None:  # VCRM-114
        repo.set_pending_input(
            conn, user_id=actor.id, kind=RETRACT_TEXT_KIND, now=now, lead_id=lead.id
        )
        return [Outgoing(chat, f"Escriba el motivo de la retractación de {sid}.")]
    conf_id = repo.create_confirmation(
        conn,
        kind=RETRACT_KIND,
        lead_id=lead.id,
        user_id=actor.id,
        now=now,
        reason=reason,
        reason_text=reason_text,
    )
    lines = [
        f"¿Confirma la retractación de {sid}?",
        f"Nombre o razón social: {name_or_company(lead) or lead.name or NO_VALUE}",
        f"Motivo: {_reason_label(reason, reason_text)}",
    ]
    buttons = (
        (
            ("✅", build_callback("conf", str(conf_id), "si")),
            ("❌", build_callback("conf", str(conf_id), "no")),
        ),
    )
    return [Outgoing(chat, "\n".join(lines), buttons)]


def retract_command(
    conn: sqlite3.Connection, actor: User, text: str, now: datetime
) -> list[Outgoing]:
    """Orden `/retractar L-n` (VCRM-131)."""
    match = _RETRACT_RE.match(text.strip())
    lead_id = parse_short_id(match.group(1) or "") if match else None
    if lead_id is None:
        return [Outgoing(actor.telegram_id, f"Formato no válido. Ejemplo: {EXAMPLE_RETRACT}")]
    return request_retract(conn, actor, lead_id, now)


def answer_retract_text(
    conn: sqlite3.Connection, actor: User, pending: PendingInput, update: Update, now: datetime
) -> list[Outgoing]:
    """Texto del motivo «otro» de la retractación; vacío → lo vuelve a pedir (VCRM-114)."""
    if pending.lead_id is None:  # pragma: no cover - siempre se guarda con lead
        return []
    text = (update.text or update.caption or "").strip()
    return request_retract(conn, actor, pending.lead_id, now, reason=OTHER_REASON, reason_text=text)


def confirm_retract(
    conn: sqlite3.Connection, actor: User, conf: Confirmation, yes: bool, now: datetime
) -> list[Outgoing]:
    """✅ «aceptado» → «rechazado» como retractación y 3 críticas; ❌ nada (VCRM-113, 131)."""
    chat = actor.telegram_id
    sid = short_id(conf.lead_id)
    if not yes:
        return [Outgoing(chat, f"No se aplicó la retractación de {sid}.")]
    lead = repo.get_lead(conn, conf.lead_id)
    if lead is None:
        return [Outgoing(chat, f"El lead {sid} no existe.")]
    decision = authorize(actor, Action.RETRACT, lead)
    if not decision.allowed:
        return deny_lead(conn, actor, decision, lead.id, now)
    if lead.state != LeadState.ACCEPTED:
        return [Outgoing(chat, f"No se aplicó: {sid} no está «aceptado».")]
    reason = conf.reason or OTHER_REASON
    changes: dict[str, str | int | None] = {
        "state": LeadState.REJECTED.value,
        "reject_reason": reason,
        "reject_text": conf.reason_text,
        "rejection_is_retraction": 1,
        "accepted_exit_at": to_iso(now),
    }
    repo.update_lead(conn, lead.id, changes, now=now)
    event_id = repo.add_event(
        conn,
        lead_id=lead.id,
        kind=EventKind.STATE,
        actor_user_id=actor.id,
        at=now,
        old_value=LeadState.ACCEPTED.value,
        new_value=LeadState.REJECTED.value,
        reason=reason,
        reason_text=conf.reason_text,
    )
    _audit_update(conn, actor, lead.id, now)
    label = _reason_label(reason, conf.reason_text)
    view = RetractionView(
        short_id=sid,
        name_or_company=name_or_company(lead) or lead.name or NO_VALUE,
        reason=label,
        author=actor.email,
        at=format_local(now),
    )
    _enqueue_for_cto_and_lawyers(  # VCRM-113, 156: sin notas ni historial
        conn,
        kind=RETRACT_NOTICE_KIND,
        key_prefix=RETRACT_KIND,
        lead_id=lead.id,
        event_id=event_id,
        text=retraction_text(view),
        email=retraction_email(view),
        now=now,
    )
    text = (
        f"{sid}: retractación registrada, estado «aceptado» → «rechazado» (motivo: {label}). "
        "Se notificó al CTO y al abogado."
    )
    out = [Outgoing(chat, text)]
    from jerico.crm import followup

    if followup.f2_active(conn):
        up_lead = repo.get_lead(conn, lead.id)
        if up_lead is not None:
            out.extend(followup.start_cadence(conn, up_lead, now))
    return out
