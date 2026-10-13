"""Enumeraciones y registros del CRM (puro, sin E/S)."""

from dataclasses import dataclass
from enum import StrEnum

# Actor de las acciones que aplica el propio sistema (bajas por correo, etc.): no es un usuario.
SYSTEM_USER_ID = 0


class Role(StrEnum):
    COMMERCIAL = "commercial"
    CTO = "cto"
    LAWYER = "lawyer"


class LeadState(StrEnum):
    NEW = "new"
    CONTACTED = "contacted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NURTURING = "nurturing"
    PAUSED = "paused"
    REACTIVATED = "reactivated"
    WON = "won"
    LOST = "lost"
    OPTED_OUT = "opted_out"


class AuthStatus(StrEnum):
    UNAUTHORIZED = "unauthorized"
    AUTHORIZED = "authorized"
    REVOKED = "revoked"


class EventKind(StrEnum):
    STATE = "state"
    FIELD = "field"
    REASSIGN = "reassign"
    TITULAR_REQUEST = "titular_request"


class Channel(StrEnum):
    TELEGRAM = "telegram"
    EMAIL = "email"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"


class AlertKind(StrEnum):
    NOTIFICATION_FAILED = "notification_failed"  # VCRM-087
    SUPPRESSION_NOTICE_FAILED = "suppression_notice_failed"  # VCRM-155
    REQUEST_OVERDUE = "request_overdue"  # VCRM-152


class AuditAction(StrEnum):
    """Acciones de la bitácora (VCRM-075, 002, 086); cerrada, sin texto libre (VCRM-096)."""

    LEAD_CREATED = "lead_created"
    LEAD_UPDATED = "lead_updated"
    LEAD_EXPORTED = "lead_exported"
    LEAD_SUPPRESSED = "lead_suppressed"
    ACCESS_DENIED = "access_denied"
    PERMISSION_DENIED = "permission_denied"
    USER_ADDED = "user_added"  # VCRM-144
    USER_DEACTIVATED = "user_deactivated"  # VCRM-091
    HANDLER_ERROR = "handler_error"  # plan §7, regla O1
    ATTACHMENT_EXPIRED = "attachment_expired"  # VCRM-145
    LLM_CALL = "llm_call"  # VCRM-A21: llamada al asistente, sin texto del prompt


class AuditOutcome(StrEnum):
    OK = "ok"
    DENIED = "denied"
    ERROR = "error"


class AuditDetail(StrEnum):
    """Códigos de detalle de la bitácora; cerrada, sin texto libre (VCRM-096)."""

    MESSAGE = "message"
    CALLBACK = "callback"
    NON_PRIVATE_CHAT = "non_private_chat"  # el bot solo opera en chats individuales
    FOREIGN_LEAD = "foreign_lead"  # comercial sobre lead ajeno (VCRM-109)
    ORDEN_CTO = "orden_cto"  # causa de la supresión ordenada por el CTO (VCRM-073)
    VENCIMIENTO_PLAZO = "vencimiento_plazo"  # supresión por plazo (VCRM-146, 159)


@dataclass(frozen=True)
class User:
    id: int
    telegram_id: int
    role: str
    email: str
    active: int
    created_at: str
    deactivated_at: str | None


@dataclass(frozen=True)
class Lead:
    id: int
    assigned_user_id: int | None
    state: str
    name: str | None
    phone_e164: str | None
    email: str | None
    company: str | None
    client_type: str | None
    doc_type: str | None
    doc_number: str | None
    legal_rep: str | None
    service: str | None
    agreed_value: str | None
    start_term: str | None
    reject_reason: str | None
    reject_text: str | None
    rejection_is_retraction: int
    auth_status: str
    ever_accepted: int
    registered_at: str
    last_interaction_at: str
    accepted_exit_at: str | None
    won_at: str | None
    final_state_at: str | None
    legal_hold_basis: str | None
    commercial_block: int
    suppressed_at: str | None
    suppression_cause: str | None


@dataclass(frozen=True)
class LeadEvent:
    id: int
    lead_id: int
    kind: str
    field: str | None
    old_value: str | None
    new_value: str | None
    reason: str | None
    reason_text: str | None
    actor_user_id: int
    at: str


@dataclass(frozen=True)
class Note:
    id: int
    lead_id: int
    author_user_id: int
    body: str
    at: str


@dataclass(frozen=True)
class Attachment:
    id: int
    lead_id: int
    kind: str
    author_user_id: int
    at: str
    storage_key: str
    size_bytes: int
    sha256: str
    deleted_at: str | None


@dataclass(frozen=True)
class Alert:
    id: int
    lead_id: int | None
    kind: str
    outbox_id: int | None
    request_id: int | None
    created_at: str
    resolved_by: int | None
    resolved_at: str | None


@dataclass(frozen=True)
class Outgoing:
    """Mensaje de respuesta del bot; `buttons`: filas de (etiqueta, callback_data)."""

    chat_id: int
    text: str
    buttons: tuple[tuple[tuple[str, str], ...], ...] = ()


@dataclass(frozen=True)
class PendingInput:
    """Dato libre que el bot espera de un usuario (caduca a los 30 min; plan §7)."""

    user_id: int
    kind: str
    lead_id: int | None
    data: str | None
    expires_at: str


@dataclass(frozen=True)
class Confirmation:
    """Confirmación ✅/❌ idempotente (`crm_confirmations`; plan §7)."""

    id: int
    kind: str
    lead_id: int
    user_id: int
    reason: str | None
    reason_text: str | None
    status: str
    created_at: str
    resolved_at: str | None


@dataclass(frozen=True)
class OutboxItem:
    """Fila de `crm_outbox` (VCRM-049, 012)."""

    id: int
    idempotency_key: str
    kind: str
    critical: int
    channel: str
    recipient_user_id: int
    lead_id: int | None
    origin_outbox_id: int | None
    subject: str | None
    body: str | None
    status: str
    attempts: int
    first_attempt_at: str | None
    next_attempt_at: str | None
    last_error: str | None
    provider_message_id: str | None
    created_at: str


class RequestType(StrEnum):
    """Tipo de solicitud de un titular (VCRM-150, 153)."""

    INQUIRY = "inquiry"
    CLAIM = "claim"
    UNCLASSIFIED = "unclassified"


class RequestStatus(StrEnum):
    OPEN = "open"
    OVERDUE = "overdue"  # VCRM-152
    ATTENDED = "attended"


@dataclass(frozen=True)
class TitularRequest:
    """Solicitud de un titular; fechas de recepción y límite en Bogotá (`YYYY-MM-DD`)."""

    id: int
    lead_id: int | None  # None: respuesta «por clasificar» sin lead asociable (VCRM-122)
    type: str
    medium: str
    received_on: str
    due_on: str
    status: str
    registered_by: int
    registered_at: str
    last_escalation_on: str | None
    attended_by: int | None
    attended_at: str | None
    inbound_id: int | None = None


# --- Fase 2: Cadencias, propuestas, envíos y entrantes (F2-T10) ---------------------------


class CadenceStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"


class ProposalKind(StrEnum):
    FOLLOWUP = "followup"
    AUTH_REQUEST = "auth_request"


class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    BLOCKED = "blocked"


class SendStatus(StrEnum):
    SCHEDULED = "scheduled"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InboundAssociation(StrEnum):
    THREAD = "thread"
    SENDER = "sender"
    TOKEN = "token"
    NONE = "none"


class InboundClassification(StrEnum):
    STOP_KEYWORD = "stop_keyword"
    STOP_HEADER = "stop_header"
    AUTH_CANDIDATE = "auth_candidate"
    REVIEW = "review"
    UNASSOCIATED = "unassociated"


class InboundDecision(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    NOT_APPLICABLE = "n/a"


@dataclass(frozen=True)
class Cadence:
    lead_id: int
    reason: str
    interval_days: int
    total_steps: int
    steps_done: int = 0
    sent_count: int = 0
    next_action_at: str | None = None
    last_sent_at: str | None = None
    status: str = "active"
    started_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class Proposal:
    id: int
    lead_id: int
    kind: str
    step: int | None
    status: str
    current_version: int
    approver_user_id: int
    expires_at: str
    created_at: str
    resolved_at: str | None = None
    resolved_by: int | None = None


@dataclass(frozen=True)
class ProposalVersion:
    proposal_id: int
    version: int
    subject: str
    body: str
    content_hash: str
    author_user_id: int
    created_at: str


@dataclass(frozen=True)
class Send:
    id: int
    proposal_id: int
    version: int
    approved_hash: str
    approved_by: int
    approved_at: str
    scheduled_at: str
    status: str
    attempts: int
    first_attempt_at: str | None
    next_attempt_at: str | None
    rfc_message_id: str | None
    last_error: str | None
    sent_at: str | None
    lead_id: int
    week_start: str


@dataclass(frozen=True)
class Inbound:
    id: int
    rfc_message_id: str
    uid: int | None
    received_at: str
    sender_fp: str
    lead_id: int | None
    association: str
    classification: str
    new_text: str | None
    decision: str
    decided_by: int | None = None
    decided_at: str | None = None
