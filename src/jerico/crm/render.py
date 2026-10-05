"""Textos del bot y de notificaciones (VCRM-011, 048, 090, 092, 104, 112, 156). Puro, sin E/S."""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from jerico.crm.handoff import (
    HANDOFF_LABELS,
    HandoffValueError,
    missing_handoff_fields,
    name_or_company,
)
from jerico.crm.model import Alert, AlertKind, Attachment, AuthStatus, Lead, Note
from jerico.crm.parsing import build_callback
from jerico.crm.timeutil import format_local, from_iso

PAGE_SIZE = 10  # PR-08
TELEGRAM_LIMIT = 4096
NO_VALUE = "(sin valor)"
UNASSIGNED = "sin comercial asignado"  # VCRM-092
ALERT_MARK = "alerta activa"  # VCRM-087
ATTENDED_LABEL = "Atendida por otro medio"  # VCRM-087

_AUTH_LABELS: dict[str, str] = {
    AuthStatus.SIN_AUTORIZACION: "sin autorización",
    AuthStatus.AUTORIZADA: "autorizada",
    AuthStatus.REVOCADA: "revocada",
}


def short_id(lead_id: int) -> str:
    return f"L-{lead_id:04d}"


def auth_label(status: str) -> str:
    return _AUTH_LABELS.get(status, status)


def handoff_rows(lead: Lead) -> tuple[tuple[str, str], ...]:
    """Los campos del handoff (§4.3) con su valor, en orden; vacíos como «(sin valor)»."""
    document = " ".join(v for v in (lead.doc_type, lead.doc_number) if v) or None
    rep = "no aplica" if lead.client_type == "persona natural" else lead.legal_rep
    values = (
        lead.client_type,
        name_or_company(lead),
        document,
        rep,
        lead.phone_e164,
        lead.email,
        lead.service,
        lead.agreed_value,
        lead.start_term,
    )
    return tuple(
        (label, value or NO_VALUE) for label, value in zip(HANDOFF_LABELS, values, strict=True)
    )


@dataclass(frozen=True)
class LawyerView:
    """Único insumo de los textos al abogado: sin notas, adjuntos ni historial (VCRM-156)."""

    short_id: str
    name_or_company: str
    commercial: str
    accepted_at: str
    auth_status: str
    handoff: tuple[tuple[str, str], ...]
    missing: tuple[str, ...]


def lawyer_view(lead: Lead, *, commercial: str, accepted_at: str) -> LawyerView:
    return LawyerView(
        short_id=short_id(lead.id),
        name_or_company=name_or_company(lead) or NO_VALUE,
        commercial=commercial,
        accepted_at=accepted_at,
        auth_status=auth_label(lead.auth_status),
        handoff=handoff_rows(lead),
        missing=missing_handoff_fields(lead),
    )


@dataclass(frozen=True)
class EmailText:
    subject: str
    body: str


def _missing_line(missing: Sequence[str]) -> str:
    return "Faltantes: " + (", ".join(missing) if missing else "ninguno")


def _rows_text(rows: Sequence[tuple[str, str]]) -> list[str]:
    return [f"- {label}: {value}" for label, value in rows]


def acceptance_for_cto(
    lead: Lead, *, commercial: str, accepted_at: str, notes: Sequence[str]
) -> str:
    """Notificación de aceptación al CTO (VCRM-048)."""
    lines = [
        f"Lead aceptado {short_id(lead.id)}",
        f"Comercial: {commercial}",
        f"Aceptado: {accepted_at}",
        f"Autorización de datos: {auth_label(lead.auth_status)}",
        "Handoff:",
        *_rows_text(handoff_rows(lead)),
        _missing_line(missing_handoff_fields(lead)),
    ]
    if notes:
        lines += ["Notas:", *(f"- {note}" for note in notes)]
    else:
        lines.append("Notas: ninguna")
    return "\n".join(lines)


def acceptance_alert_for_lawyer(view: LawyerView) -> str:
    """Alerta de aceptación por Telegram al abogado (VCRM-104)."""
    return "\n".join(
        [
            f"Lead aceptado {view.short_id}: {view.name_or_company}",
            f"Comercial: {view.commercial}",
            f"Aceptado: {view.accepted_at}",
            "La ficha completa se envió por correo.",
            *([f"Faltan campos del handoff: {', '.join(view.missing)}"] if view.missing else []),
        ]
    )


def acceptance_email_for_lawyer(view: LawyerView) -> EmailText:
    """Correo de aceptación al abogado: solo campos del handoff (VCRM-048, 156)."""
    body = "\n".join(
        [
            f"Lead aceptado {view.short_id}",
            f"Comercial: {view.commercial}",
            f"Aceptado: {view.accepted_at}",
            f"Autorización de datos: {view.auth_status}",
            "Campos del handoff:",
            *_rows_text(view.handoff),
            _missing_line(view.missing),
            "",
            "Solicitud: por favor, preparar el contrato y la autorización de tratamiento de datos.",
        ]
    )
    subject = f"Aceptación {view.short_id}: preparar contrato y autorización de datos"
    return EmailText(subject=subject, body=body)


@dataclass(frozen=True)
class RetractionView:
    """Datos de la notificación de retractación: sin notas ni historial (VCRM-113, 156)."""

    short_id: str
    name_or_company: str
    reason: str
    author: str
    at: str


def retraction_text(view: RetractionView) -> str:
    """Notificación de retractación por Telegram al CTO y al abogado (VCRM-113)."""
    return "\n".join(
        [
            f"Retractación del lead {view.short_id}: {view.name_or_company}",
            f"Motivo: {view.reason}",
            f"Registrada por: {view.author}",
            f"Fecha: {view.at}",
        ]
    )


def retraction_email(view: RetractionView) -> EmailText:
    """Correo de retractación al abogado (VCRM-113, 156)."""
    subject = f"Retractación {view.short_id}: el lead deja de estar aceptado"
    return EmailText(subject=subject, body=retraction_text(view))


def handoff_update_text(view: LawyerView, completed: Sequence[str]) -> str:
    """Actualización del handoff de un «aceptado»: campo completado y faltantes (VCRM-084, 156)."""
    rows = [(label, value) for label, value in view.handoff if label in completed]
    return "\n".join(
        [
            f"Actualización del handoff {view.short_id}: {view.name_or_company}",
            "Campo completado:",
            *_rows_text(rows),
            _missing_line(view.missing),
        ]
    )


def handoff_update_email(view: LawyerView, completed: Sequence[str]) -> EmailText:
    subject = f"Actualización del handoff {view.short_id}"
    return EmailText(subject=subject, body=handoff_update_text(view, completed))


def handoff_error_text(error: HandoffValueError) -> str:
    """Respuesta a un valor de handoff no admitido: campo y valores admitidos (VCRM-112)."""
    if error.code == "empty":
        return f"El campo «{error.field}» no puede quedar vacío. No se modificó el lead."
    allowed = ", ".join(f"«{v}»" for v in error.allowed)
    suffix = " seguido del número" if error.field == "documento" else ""
    return (
        f"Valor no admitido para «{error.field}». Valores admitidos: {allowed}{suffix}. "
        "No se modificó el lead."
    )


@dataclass(frozen=True)
class ListPage:
    text: str
    buttons: tuple[tuple[str, str], ...]  # (etiqueta, callback_data)


def _local(iso: str) -> str:
    return format_local(from_iso(iso))


def _list_line(
    lead: Lead, unassigned: Collection[int], alerted: Collection[int] = frozenset()
) -> str:
    """Identificador, nombre, estado y última interacción (VCRM-010); marcas VCRM-092 y 087."""
    line = (
        f"{short_id(lead.id)} · {lead.name or NO_VALUE} · {lead.state} · "
        f"{_local(lead.last_interaction_at)}"
    )
    line = f"{line} · {UNASSIGNED}" if lead.id in unassigned else line
    return f"{line} · {ALERT_MARK}" if lead.id in alerted else line


def render_list_page(
    leads: Sequence[Lead],
    page: int,
    size: int = PAGE_SIZE,
    *,
    unassigned: Collection[int] = frozenset(),
    alerted: Collection[int] = frozenset(),
) -> ListPage:
    """Página de la lista con «Anterior»/«Siguiente» y «página X de Y» (VCRM-090)."""
    total = max(1, -(-len(leads) // size))
    page = min(max(page, 1), total)
    chunk = leads[(page - 1) * size : page * size]
    lines = ["Leads:"]
    lines += [_list_line(lead, unassigned, alerted) for lead in chunk]
    if not chunk:
        lines.append("No hay leads.")
    lines.append(f"página {page} de {total}")
    buttons: list[tuple[str, str]] = []
    if page > 1:
        buttons.append(("Anterior", build_callback("lista", str(page - 1))))
    if page < total:
        buttons.append(("Siguiente", build_callback("lista", str(page + 1))))
    return ListPage(text="\n".join(lines), buttons=tuple(buttons))


_ATTACHMENT_LABELS: dict[str, str] = {
    "photo": "foto",
    "document": "documento",
    "voice": "nota de voz",
    "authorization": "evidencia de autorización",
}
_ALERT_LABELS: dict[str, str] = {
    AlertKind.NOTIFICATION_FAILED: "notificación fallida",
    AlertKind.SUPPRESSION_NOTICE_FAILED: "aviso de supresión fallido",
    AlertKind.REQUEST_OVERDUE: "solicitud del titular vencida",
}


def render_lead_card(
    lead: Lead,
    *,
    commercial: str,
    notes: Sequence[Note],
    attachments: Sequence[Attachment],
    alerts: Sequence[Alert],
    authors: Mapping[int, str],
    alert_details: Mapping[int, str] | None = None,
) -> str:
    """Ficha del lead (VCRM-011): contacto, estado, comercial, handoff, notas, adjuntos, motivo,
    autorización, próxima acción y alertas activas. `authors`: id de usuario → correo."""
    lines = [
        f"Ficha {short_id(lead.id)}",
        f"Nombre: {lead.name or NO_VALUE}",
        f"Teléfono: {lead.phone_e164 or NO_VALUE}",
        f"Correo: {lead.email or NO_VALUE}",
        f"Empresa: {lead.company or NO_VALUE}",
        f"Estado: {lead.state}",
        f"Comercial: {commercial}",
        "Handoff:",
        *_rows_text(handoff_rows(lead)),
    ]
    if notes:
        lines.append("Notas:")
        lines += [
            f"- {_local(n.at)} · {authors.get(n.author_user_id, NO_VALUE)}: {n.body}" for n in notes
        ]
    else:
        lines.append("Notas: ninguna")
    if attachments:
        lines.append("Adjuntos:")
        lines += [
            f"- {_ATTACHMENT_LABELS.get(a.kind, a.kind)} · {_local(a.at)} · "
            f"{authors.get(a.author_user_id, NO_VALUE)}"
            for a in attachments
        ]
    else:
        lines.append("Adjuntos: ninguno")
    if lead.reject_reason:
        detail = f" ({lead.reject_text})" if lead.reject_text else ""
        lines.append(f"Motivo de rechazo: {lead.reject_reason}{detail}")
    lines.append(f"Autorización de datos: {auth_label(lead.auth_status)}")
    lines.append("Próxima acción: no aplica en F1")
    if alerts:
        lines.append("Alertas activas:")
        details = alert_details or {}
        lines += [
            f"- {_ALERT_LABELS.get(a.kind, a.kind)} · {_local(a.created_at)}"
            + (f" · {details[a.id]}" if a.id in details else "")
            for a in alerts
        ]
    else:
        lines.append("Alertas activas: ninguna")
    return "\n".join(lines)


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Trozos ≤ `limit`, cortando por saltos de línea (o en duro si una línea excede)."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    pieces: list[str] = []
    for line in text.split("\n"):
        while len(line) > limit:
            pieces.append(line[:limit])
            line = line[limit:]
        pieces.append(line)
    chunks: list[str] = []
    current: str | None = None
    for piece in pieces:
        if current is None:
            current = piece
        elif len(current) + 1 + len(piece) <= limit:
            current += "\n" + piece
        else:
            chunks.append(current)
            current = piece
    if current is not None:
        chunks.append(current)
    return chunks
