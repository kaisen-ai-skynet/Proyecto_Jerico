"""Consultas SQL del CRM (SQL ANSI, portable a PostgreSQL 16; plan §1.4 y §3).

Cada función recibe la conexión de `CrmDatabase.tx()` o `CrmDatabase.read()`.
"""

import re
import sqlite3
import uuid
from collections.abc import Collection, Mapping
from datetime import datetime, timedelta
from typing import Any

from jerico.crm.model import (
    Alert,
    AlertKind,
    Attachment,
    AuditAction,
    AuditDetail,
    AuditOutcome,
    AuthStatus,
    Confirmation,
    EventKind,
    Lead,
    LeadEvent,
    LeadState,
    Note,
    OutboxItem,
    OutboxStatus,
    PendingInput,
    RequestStatus,
    RequestType,
    Role,
    TitularRequest,
    User,
)
from jerico.crm.timeutil import from_iso, to_iso

_LEAD_INSERT_FIELDS = frozenset(
    {
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
    }
)
_LEAD_UPDATE_FIELDS = frozenset(Lead.__dataclass_fields__) - {"id", "registered_at"}
PENDING_INPUT_TTL = timedelta(minutes=30)
_ACTOR = re.compile(r"(user:\d+|tg:\d+|system)")


def _check_columns(columns: Mapping[str, Any], allowed: frozenset[str]) -> None:
    unknown = sorted(set(columns) - allowed)
    if unknown:
        raise ValueError(f"columna no permitida: {unknown}")


def _require_enum(value: object, enum: type, name: str) -> None:
    if not isinstance(value, enum):
        raise TypeError(f"{name} debe ser {enum.__name__}")


# --- Metadatos -------------------------------------------------------------------------


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM crm_meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO crm_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


# --- Usuarios --------------------------------------------------------------------------


def insert_user(
    conn: sqlite3.Connection, *, telegram_id: int, role: Role, email: str, now: datetime
) -> User:
    row = conn.execute(
        "INSERT INTO crm_users (telegram_id, role, email, active, created_at) "
        "VALUES (?, ?, ?, 1, ?) RETURNING *",
        (telegram_id, role.value, email, to_iso(now)),
    ).fetchone()
    return User(**dict(row))


def get_user(conn: sqlite3.Connection, user_id: int) -> User | None:
    row = conn.execute("SELECT * FROM crm_users WHERE id = ?", (user_id,)).fetchone()
    return None if row is None else User(**dict(row))


def active_user_by_telegram(conn: sqlite3.Connection, telegram_id: int) -> User | None:
    row = conn.execute(
        "SELECT * FROM crm_users WHERE telegram_id = ? AND active = 1", (telegram_id,)
    ).fetchone()
    return None if row is None else User(**dict(row))


def active_users(conn: sqlite3.Connection, role: Role | None = None) -> list[User]:
    if role is None:
        rows = conn.execute("SELECT * FROM crm_users WHERE active = 1 ORDER BY id").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM crm_users WHERE active = 1 AND role = ? ORDER BY id", (role.value,)
        ).fetchall()
    return [User(**dict(r)) for r in rows]


def deactivate_user(conn: sqlite3.Connection, user_id: int, *, now: datetime) -> bool:
    cursor = conn.execute(
        "UPDATE crm_users SET active = 0, deactivated_at = ? WHERE id = ? AND active = 1",
        (to_iso(now), user_id),
    )
    return cursor.rowcount == 1


# --- Leads y eventos -------------------------------------------------------------------


def insert_lead(
    conn: sqlite3.Connection,
    *,
    assigned_user_id: int | None,
    state: LeadState,
    now: datetime,
    fields: Mapping[str, str | None],
) -> int:
    _check_columns(fields, _LEAD_INSERT_FIELDS)
    columns = ["assigned_user_id", "state", "registered_at", "last_interaction_at", *fields]
    values = [assigned_user_id, state.value, to_iso(now), to_iso(now), *fields.values()]
    placeholders = ", ".join("?" for _ in columns)
    row = conn.execute(
        # Columnas validadas contra la lista blanca `_LEAD_INSERT_FIELDS`.
        f"INSERT INTO crm_leads ({', '.join(columns)}) VALUES ({placeholders}) RETURNING id",  # noqa: S608
        values,
    ).fetchone()
    return int(row["id"])


def get_lead(conn: sqlite3.Connection, lead_id: int) -> Lead | None:
    row = conn.execute("SELECT * FROM crm_leads WHERE id = ?", (lead_id,)).fetchone()
    return None if row is None else Lead(**dict(row))


def leads_of_user(conn: sqlite3.Connection, user_id: int) -> list[Lead]:
    """Leads asignados a un usuario en cualquier estado salvo «baja» (VCRM-091)."""
    rows = conn.execute(
        "SELECT * FROM crm_leads WHERE assigned_user_id = ? AND state <> ? ORDER BY id",
        (user_id, LeadState.OPTED_OUT.value),
    ).fetchall()
    return [Lead(**dict(r)) for r in rows]


def all_leads(conn: sqlite3.Connection) -> list[Lead]:
    """Todos los leads por última interacción descendente y, a igualdad, id descendente."""
    rows = conn.execute(
        "SELECT * FROM crm_leads ORDER BY last_interaction_at DESC, id DESC"
    ).fetchall()
    return [Lead(**dict(r)) for r in rows]


def contact_matches(
    conn: sqlite3.Connection, *, phone: str | None, email: str | None
) -> list[Lead]:
    """Leads no suprimidos ni «perdido» con el mismo teléfono o correo (VCRM-006, 110, 135)."""
    rows = conn.execute(
        "SELECT * FROM crm_leads WHERE state <> ? AND suppressed_at IS NULL "
        "AND ((? IS NOT NULL AND phone_e164 = ?) OR (? IS NOT NULL AND email = ?)) ORDER BY id",
        (LeadState.LOST.value, phone, phone, email, email),
    ).fetchall()
    return [Lead(**dict(r)) for r in rows]


def titular_leads(conn: sqlite3.Connection, lead: Lead) -> list[Lead]:
    """El lead y los no suprimidos con su mismo teléfono o correo, sin encadenar (K-3)."""
    rows = conn.execute(
        "SELECT * FROM crm_leads WHERE id = ? OR (suppressed_at IS NULL "
        "AND ((? IS NOT NULL AND phone_e164 = ?) OR (? IS NOT NULL AND email = ?))) ORDER BY id",
        (lead.id, lead.phone_e164, lead.phone_e164, lead.email, lead.email),
    ).fetchall()
    return [Lead(**dict(r)) for r in rows]


def purge_lead_records(
    conn: sqlite3.Connection, lead_id: int, *, attachment_ids: Collection[int], now: datetime
) -> None:
    """Borra notas, eventos de datos, motivos, cuerpos del outbox y pendientes (VCRM-073)."""
    conn.execute("DELETE FROM crm_notes WHERE lead_id = ?", (lead_id,))
    conn.executemany(
        "UPDATE crm_attachments SET deleted_at = ? WHERE id = ? AND lead_id = ?",
        [(to_iso(now), att_id, lead_id) for att_id in attachment_ids],
    )
    conn.execute(
        "DELETE FROM crm_lead_events WHERE lead_id = ? AND kind = ?",
        (lead_id, EventKind.FIELD.value),
    )
    conn.execute("UPDATE crm_lead_events SET reason_text = NULL WHERE lead_id = ?", (lead_id,))
    conn.execute("UPDATE crm_outbox SET subject = NULL, body = NULL WHERE lead_id = ?", (lead_id,))
    conn.execute("DELETE FROM crm_confirmations WHERE lead_id = ?", (lead_id,))
    clear_lead_pending_inputs(conn, lead_id)


def insert_note(
    conn: sqlite3.Connection, *, lead_id: int, author_user_id: int, body: str, at: datetime
) -> int:
    row = conn.execute(
        "INSERT INTO crm_notes (lead_id, author_user_id, body, at) VALUES (?, ?, ?, ?) "
        "RETURNING id",
        (lead_id, author_user_id, body, to_iso(at)),
    ).fetchone()
    return int(row["id"])


def lead_notes(conn: sqlite3.Connection, lead_id: int) -> list[Note]:
    rows = conn.execute(
        "SELECT * FROM crm_notes WHERE lead_id = ? ORDER BY at, id", (lead_id,)
    ).fetchall()
    return [Note(**dict(r)) for r in rows]


def lead_attachments(conn: sqlite3.Connection, lead_id: int) -> list[Attachment]:
    """Adjuntos vigentes (no eliminados) del lead."""
    rows = conn.execute(
        "SELECT * FROM crm_attachments WHERE lead_id = ? AND deleted_at IS NULL ORDER BY at, id",
        (lead_id,),
    ).fetchall()
    return [Attachment(**dict(r)) for r in rows]


def mark_attachment_deleted(conn: sqlite3.Connection, attachment_id: int, *, now: datetime) -> None:
    """Marca un adjunto como eliminado del almacén (VCRM-145)."""
    conn.execute(
        "UPDATE crm_attachments SET deleted_at = ? WHERE id = ?", (to_iso(now), attachment_id)
    )


def add_retention_notice(
    conn: sqlite3.Connection, lead_id: int, clock_start: str, kind: str, *, now: datetime
) -> bool:
    """Registra un aviso del barrido una sola vez por (lead, reloj, tipo); True si es nuevo."""
    cur = conn.execute(
        "INSERT INTO crm_retention_notices (lead_id, clock_start, kind, sent_at) "
        "VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
        (lead_id, clock_start, kind, to_iso(now)),
    )
    return cur.rowcount == 1


def lead_reduced_evidence(conn: sqlite3.Connection, lead_id: int) -> list[Attachment]:
    """Evidencias de autorización cuyo archivo ya se eliminó: solo queda su huella (VCRM-165)."""
    rows = conn.execute(
        "SELECT * FROM crm_attachments WHERE lead_id = ? AND kind = 'authorization' "
        "AND deleted_at IS NOT NULL ORDER BY at, id",
        (lead_id,),
    ).fetchall()
    return [Attachment(**dict(r)) for r in rows]


def lead_consents(conn: sqlite3.Connection, lead_id: int) -> list[dict[str, Any]]:
    """Autorizaciones y revocatorias del lead, en orden (VCRM-074)."""
    rows = conn.execute(
        "SELECT * FROM crm_consents WHERE lead_id = ? ORDER BY at, id", (lead_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def insert_attachment(
    conn: sqlite3.Connection,
    *,
    lead_id: int,
    kind: str,
    author_user_id: int,
    at: datetime,
    storage_key: str,
    size_bytes: int,
    sha256: str,
) -> int:
    """Fila de adjunto con tipo, autor y fecha (VCRM-007)."""
    row = conn.execute(
        "INSERT INTO crm_attachments (lead_id, kind, author_user_id, at, storage_key, size_bytes, "
        "sha256) VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
        (lead_id, kind, author_user_id, to_iso(at), storage_key, size_bytes, sha256),
    ).fetchone()
    return int(row["id"])


def set_assignee(conn: sqlite3.Connection, lead_id: int, user_id: int) -> None:
    """Cambia el asignado sin tocar la última interacción (VCRM-093)."""
    conn.execute("UPDATE crm_leads SET assigned_user_id = ? WHERE id = ?", (user_id, lead_id))


def update_lead(
    conn: sqlite3.Connection, lead_id: int, changes: Mapping[str, Any], *, now: datetime
) -> None:
    """Actualiza columnas permitidas y la última interacción."""
    _check_columns(changes, _LEAD_UPDATE_FIELDS)
    values = {**changes, "last_interaction_at": to_iso(now)}
    assignments = ", ".join(f"{column} = ?" for column in values)
    # Columnas validadas contra la lista blanca `_LEAD_UPDATE_FIELDS`.
    sql = f"UPDATE crm_leads SET {assignments} WHERE id = ?"  # noqa: S608
    conn.execute(sql, [*values.values(), lead_id])


def add_event(
    conn: sqlite3.Connection,
    *,
    lead_id: int,
    kind: EventKind,
    actor_user_id: int,
    at: datetime,
    field: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
    reason: str | None = None,
    reason_text: str | None = None,
) -> int:
    row = conn.execute(
        "INSERT INTO crm_lead_events (lead_id, kind, field, old_value, new_value, reason, "
        "reason_text, actor_user_id, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
        (
            lead_id,
            kind.value,
            field,
            old_value,
            new_value,
            reason,
            reason_text,
            actor_user_id,
            to_iso(at),
        ),
    ).fetchone()
    return int(row["id"])


def lead_events(conn: sqlite3.Connection, lead_id: int) -> list[LeadEvent]:
    rows = conn.execute(
        "SELECT * FROM crm_lead_events WHERE lead_id = ? ORDER BY id", (lead_id,)
    ).fetchall()
    return [LeadEvent(**dict(r)) for r in rows]


# --- Bitácora de auditoría (VCRM-075, VCRM-096) ------------------------------------------


def audit(
    conn: sqlite3.Connection,
    *,
    actor: str,
    action: AuditAction,
    outcome: AuditOutcome,
    at: datetime,
    lead_id: int | None = None,
    detail: AuditDetail | None = None,
) -> None:
    """Registra una entrada solo con códigos cerrados; no admite texto libre (VCRM-096)."""
    _require_enum(action, AuditAction, "action")
    _require_enum(outcome, AuditOutcome, "outcome")
    if detail is not None:
        _require_enum(detail, AuditDetail, "detail")
    if not _ACTOR.fullmatch(actor):
        raise ValueError("actor debe ser 'user:<id>', 'tg:<id>' o 'system'")
    conn.execute(
        "INSERT INTO crm_audit (at, actor, action, lead_id, outcome, detail_code) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            to_iso(at),
            actor,
            action.value,
            lead_id,
            outcome.value,
            None if detail is None else detail.value,
        ),
    )


def audit_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM crm_audit ORDER BY id").fetchall()]


# --- Alertas persistentes (VCRM-087, 152, 155) -------------------------------------------


def create_alert(
    conn: sqlite3.Connection,
    *,
    kind: AlertKind,
    now: datetime,
    lead_id: int | None = None,
    outbox_id: int | None = None,
    request_id: int | None = None,
) -> int:
    _require_enum(kind, AlertKind, "kind")
    row = conn.execute(
        "INSERT INTO crm_alerts (lead_id, kind, outbox_id, request_id, created_at) "
        "VALUES (?, ?, ?, ?, ?) RETURNING id",
        (lead_id, kind.value, outbox_id, request_id, to_iso(now)),
    ).fetchone()
    return int(row["id"])


def open_alerts(conn: sqlite3.Connection, *, lead_id: int | None = None) -> list[Alert]:
    """Alertas sin resolver: de un lead (ficha) o todas (lista del CTO)."""
    if lead_id is None:
        rows = conn.execute(
            "SELECT * FROM crm_alerts WHERE resolved_at IS NULL ORDER BY id"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM crm_alerts WHERE resolved_at IS NULL AND lead_id = ? ORDER BY id",
            (lead_id,),
        ).fetchall()
    return [Alert(**dict(r)) for r in rows]


def resolve_alert(
    conn: sqlite3.Connection, alert_id: int, *, resolved_by: int, now: datetime
) -> bool:
    """Marca la alerta «atendida»; devuelve False si no existe o ya estaba resuelta."""
    cursor = conn.execute(
        "UPDATE crm_alerts SET resolved_by = ?, resolved_at = ? "
        "WHERE id = ? AND resolved_at IS NULL",
        (resolved_by, to_iso(now), alert_id),
    )
    return cursor.rowcount == 1


def resolve_request_alerts(
    conn: sqlite3.Connection, request_id: int, *, resolved_by: int, now: datetime
) -> int:
    """Cierra las alertas abiertas de una solicitud de titular (VCRM-152)."""
    cursor = conn.execute(
        "UPDATE crm_alerts SET resolved_by = ?, resolved_at = ? "
        "WHERE request_id = ? AND resolved_at IS NULL",
        (resolved_by, to_iso(now), request_id),
    )
    return cursor.rowcount


# --- Solicitudes de titulares (VCRM-150-152) ----------------------------------------------

_REQUEST_UPDATE_FIELDS = frozenset({"status", "last_escalation_on", "attended_by", "attended_at"})


def insert_titular_request(
    conn: sqlite3.Connection,
    *,
    lead_id: int,
    kind: RequestType,
    medium: str,
    received_on: str,
    due_on: str,
    registered_by: int,
    now: datetime,
) -> int:
    _require_enum(kind, RequestType, "kind")
    row = conn.execute(
        "INSERT INTO crm_titular_requests (lead_id, type, medium, received_on, due_on, "
        "registered_by, registered_at) VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
        (lead_id, kind.value, medium, received_on, due_on, registered_by, to_iso(now)),
    ).fetchone()
    return int(row["id"])


def get_titular_request(conn: sqlite3.Connection, request_id: int) -> TitularRequest | None:
    row = conn.execute("SELECT * FROM crm_titular_requests WHERE id = ?", (request_id,)).fetchone()
    return None if row is None else TitularRequest(**dict(row))


def titular_requests(
    conn: sqlite3.Connection, statuses: Collection[RequestStatus] | None = None
) -> list[TitularRequest]:
    """Todas las solicitudes o las de los estados indicados, por id."""
    rows = conn.execute("SELECT * FROM crm_titular_requests ORDER BY id").fetchall()
    found = [TitularRequest(**dict(r)) for r in rows]
    if statuses is None:
        return found
    wanted = {s.value for s in statuses}
    return [r for r in found if r.status in wanted]


def update_titular_request(
    conn: sqlite3.Connection, request_id: int, columns: Mapping[str, Any]
) -> None:
    _check_columns(columns, _REQUEST_UPDATE_FIELDS)
    assignments = ", ".join(f"{name} = ?" for name in columns)
    conn.execute(
        f"UPDATE crm_titular_requests SET {assignments} WHERE id = ?",  # noqa: S608
        (*columns.values(), request_id),
    )


# --- Eventos procesados del canal (VCRM-079) ----------------------------------------------


def mark_update_processed(conn: sqlite3.Connection, update_id: int, now: datetime) -> bool:
    """Registra el `update_id`; False si ya estaba procesado."""
    cursor = conn.execute(
        "INSERT INTO crm_processed_updates (update_id, processed_at) VALUES (?, ?) "
        "ON CONFLICT (update_id) DO NOTHING",
        (update_id, to_iso(now)),
    )
    return cursor.rowcount == 1


# --- Lista de supresión (VCRM-088, 095) ----------------------------------------------------


def any_suppressed(conn: sqlite3.Connection, fingerprints: Collection[str]) -> bool:
    """True si alguna huella figura en la lista de supresión."""
    if not fingerprints:
        return False
    placeholders = ", ".join("?" for _ in fingerprints)
    row = conn.execute(
        # Solo marcadores de posición generados; los valores van parametrizados.
        f"SELECT 1 FROM crm_suppression WHERE fingerprint IN ({placeholders}) LIMIT 1",  # noqa: S608
        list(fingerprints),
    ).fetchone()
    return row is not None


def add_suppression(conn: sqlite3.Connection, fp: str, *, at: datetime, medium: str) -> None:
    """Añade una huella a la lista de supresión (solo huella, fecha y medio; VCRM-095)."""
    conn.execute(
        "INSERT INTO crm_suppression (fingerprint, at, medium) VALUES (?, ?, ?) "
        "ON CONFLICT (fingerprint) DO NOTHING",
        (fp, to_iso(at), medium),
    )


# --- Consentimientos (VCRM-065, 138, 164) --------------------------------------------------


def insert_consent(
    conn: sqlite3.Connection,
    *,
    lead_id: int,
    status: AuthStatus,
    medium: str,
    at: datetime,
    actor_user_id: int,
    attachment_id: int | None = None,
) -> int:
    """Fila de autorización o revocatoria; nunca se modifica ni se borra (VCRM-164)."""
    _require_enum(status, AuthStatus, "status")
    row = conn.execute(
        "INSERT INTO crm_consents (lead_id, status, medium, at, actor_user_id, attachment_id) "
        "VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
        (lead_id, status.value, medium, to_iso(at), actor_user_id, attachment_id),
    ).fetchone()
    return int(row["id"])


# --- Respuestas y no críticas fallidas (VCRM-012) ---------------------------------------


def record_failed_noncritical(
    conn: sqlite3.Connection,
    *,
    recipient_user_id: int,
    kind: str,
    error: str | None,
    now: datetime,
    lead_id: int | None = None,
    channel: str = "telegram",
) -> int:
    """Fila `fallida` sin cuerpo ni reintento (no altera el lead)."""
    row = conn.execute(
        "INSERT INTO crm_outbox (idempotency_key, kind, critical, channel, recipient_user_id, "
        "lead_id, status, attempts, first_attempt_at, last_error, created_at) "
        "VALUES (?, ?, 0, ?, ?, ?, 'failed', 1, ?, ?, ?) RETURNING id",
        (
            f"noncritical:{uuid.uuid4().hex}",
            kind,
            channel,
            recipient_user_id,
            lead_id,
            to_iso(now),
            error,
            to_iso(now),
        ),
    ).fetchone()
    return int(row["id"])


# --- Outbox de notificaciones críticas (VCRM-049, 127) -------------------------------------


def insert_outbox(
    conn: sqlite3.Connection,
    *,
    key: str,
    kind: str,
    channel: str,
    recipient_user_id: int,
    lead_id: int | None,
    subject: str | None,
    body: str | None,
    now: datetime,
    origin_outbox_id: int | None = None,
) -> int:
    """Inserta una crítica `pending` debida en `now`; con la clave ya usada devuelve esa fila."""
    conn.execute(
        "INSERT INTO crm_outbox (idempotency_key, kind, critical, channel, recipient_user_id, "
        "lead_id, origin_outbox_id, subject, body, status, attempts, next_attempt_at, created_at) "
        "VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?) "
        "ON CONFLICT (idempotency_key) DO NOTHING",
        (
            key,
            kind,
            channel,
            recipient_user_id,
            lead_id,
            origin_outbox_id,
            subject,
            body,
            to_iso(now),
            to_iso(now),
        ),
    )
    row = conn.execute("SELECT id FROM crm_outbox WHERE idempotency_key = ?", (key,)).fetchone()
    return int(row["id"])


def get_outbox(conn: sqlite3.Connection, outbox_id: int) -> OutboxItem | None:
    row = conn.execute("SELECT * FROM crm_outbox WHERE id = ?", (outbox_id,)).fetchone()
    return OutboxItem(**dict(row)) if row else None


def due_outbox(conn: sqlite3.Connection, now: datetime) -> list[OutboxItem]:
    """Pendientes con `next_attempt_at <= now`, en orden de id (comparación en UTC, no textual)."""
    rows = conn.execute(
        "SELECT * FROM crm_outbox WHERE status = 'pending' AND next_attempt_at IS NOT NULL "
        "ORDER BY id"
    ).fetchall()
    return [OutboxItem(**dict(r)) for r in rows if from_iso(r["next_attempt_at"]) <= now]


def update_outbox_attempt(
    conn: sqlite3.Connection,
    outbox_id: int,
    *,
    status: OutboxStatus,
    attempts: int,
    first_attempt_at: datetime,
    next_attempt_at: datetime | None,
    error: str | None = None,
    message_id: str | None = None,
) -> None:
    _require_enum(status, OutboxStatus, "status")
    conn.execute(
        "UPDATE crm_outbox SET status = ?, attempts = ?, first_attempt_at = ?, "
        "next_attempt_at = ?, last_error = ?, provider_message_id = ? WHERE id = ?",
        (
            status.value,
            attempts,
            to_iso(first_attempt_at),
            to_iso(next_attempt_at) if next_attempt_at else None,
            error,
            message_id,
            outbox_id,
        ),
    )


# --- Entradas pendientes (plan §7) ----------------------------------------------------------


def set_pending_input(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    kind: str,
    now: datetime,
    lead_id: int | None = None,
    data: str | None = None,
) -> None:
    """Crea o sustituye la entrada pendiente del usuario; caduca a los 30 min."""
    conn.execute(
        "INSERT INTO crm_pending_inputs (user_id, kind, lead_id, data, expires_at) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT (user_id) DO UPDATE SET kind = excluded.kind, "
        "lead_id = excluded.lead_id, data = excluded.data, expires_at = excluded.expires_at",
        (user_id, kind, lead_id, data, to_iso(now + PENDING_INPUT_TTL)),
    )


def get_pending_input(conn: sqlite3.Connection, user_id: int, now: datetime) -> PendingInput | None:
    """Entrada vigente del usuario; None si no hay o ya caducó."""
    row = conn.execute("SELECT * FROM crm_pending_inputs WHERE user_id = ?", (user_id,)).fetchone()
    if row is None or from_iso(row["expires_at"]) <= now:
        return None
    return PendingInput(**dict(row))


def clear_pending_input(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("DELETE FROM crm_pending_inputs WHERE user_id = ?", (user_id,))


def clear_lead_pending_inputs(conn: sqlite3.Connection, lead_id: int) -> None:
    """Borra las entradas pendientes de cualquier usuario sobre el lead (baja, VCRM-070)."""
    conn.execute("DELETE FROM crm_pending_inputs WHERE lead_id = ?", (lead_id,))


# --- Confirmaciones ✅/❌ (plan §7) ---------------------------------------------------------


def create_confirmation(
    conn: sqlite3.Connection,
    *,
    kind: str,
    lead_id: int,
    user_id: int,
    now: datetime,
    reason: str | None = None,
    reason_text: str | None = None,
) -> int:
    row = conn.execute(
        "INSERT INTO crm_confirmations (kind, lead_id, user_id, reason, reason_text, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
        (kind, lead_id, user_id, reason, reason_text, to_iso(now)),
    ).fetchone()
    return int(row["id"])


def get_confirmation(conn: sqlite3.Connection, confirmation_id: int) -> Confirmation | None:
    row = conn.execute(
        "SELECT * FROM crm_confirmations WHERE id = ?", (confirmation_id,)
    ).fetchone()
    return None if row is None else Confirmation(**dict(row))


def resolve_confirmation(
    conn: sqlite3.Connection, confirmation_id: int, status: str, now: datetime
) -> bool:
    """Resuelve una confirmación pendiente; False si no existe o ya estaba procesada."""
    cursor = conn.execute(
        "UPDATE crm_confirmations SET status = ?, resolved_at = ? "
        "WHERE id = ? AND status = 'pending'",
        (status, to_iso(now), confirmation_id),
    )
    return cursor.rowcount == 1


def cancel_pending_confirmations(conn: sqlite3.Connection, lead_id: int, now: datetime) -> int:
    """Cancela las confirmaciones pendientes del lead (VCRM-116); devuelve cuántas."""
    cursor = conn.execute(
        "UPDATE crm_confirmations SET status = 'cancelled', resolved_at = ? "
        "WHERE lead_id = ? AND status = 'pending'",
        (to_iso(now), lead_id),
    )
    return cursor.rowcount
