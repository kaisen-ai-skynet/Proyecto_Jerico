"""Modelos de dominio de la spec 004 (inmutables). Las tablas están en `closing_schema.py`."""

from dataclasses import dataclass
from enum import StrEnum


class PackageStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    SENT = "sent"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


class ContractStatus(StrEnum):
    PACKAGE_SENT = "package_sent"
    CONTRACT_UPLOADED = "contract_uploaded"
    APPROVED_FOR_SIGNATURE = "approved_for_signature"
    SENT_FOR_SIGNATURE = "sent_for_signature"
    SIGNED = "signed"
    DECLINED = "declined"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    SPECIAL_FORM = "special_form"


class LegalBasis(StrEnum):
    """Base legal del tratamiento del paquete (VCRM-P03); código cerrado."""

    AUTHORIZATION = "authorization"  # autorización vigente del titular (art. 9 Ley 1581)
    LAWYER_CONFIRMED = "lawyer_confirmed"  # otra base confirmada por escrito por el abogado


class CandidateStatus(StrEnum):
    PENDING = "pending"
    REGISTERED = "registered"
    DISCARDED = "discarded"


@dataclass(frozen=True)
class OfferLine:
    position: int
    description: str
    quantity: int
    unit_price: int  # unidades enteras de la moneda (pesos para COP)


@dataclass(frozen=True)
class Offer:
    id: int
    lead_id: int
    version: int
    currency: str
    payment_terms: str
    valid_until: str | None
    special_conditions: str | None
    created_by: int
    created_at: str
    lines: tuple[OfferLine, ...]


@dataclass(frozen=True)
class Package:
    id: int
    lead_id: int
    version: int
    offer_id: int
    content_hash: str
    status: str
    legal_basis: str
    created_by: int
    confirmed_by: int | None
    created_at: str
    sent_at: str | None


@dataclass(frozen=True)
class Contract:
    id: int
    package_id: int
    status: str
    file_path: str | None
    sha256: str | None
    uploaded_by: int | None
    approved_by: int | None
    return_reason: str | None
    expires_at: str | None
    signed_at: str | None
    created_at: str


@dataclass(frozen=True)
class Signature:
    id: int
    contract_id: int
    provider: str
    external_id: str | None
    status: str
    evidence_path: str | None
    evidence_sha256: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Mailbox:
    id: int
    user_id: int
    address: str
    secret_env: str
    active: int
    last_ok_at: str | None


@dataclass(frozen=True)
class MailCandidate:
    id: int
    mailbox_id: int
    message_id: str
    sender_email: str
    sender_name: str | None
    subject: str | None
    received_at: str
    status: str
    lead_id: int | None
    expires_at: str
