"""Consultas y persistencia para cierre, contrato, firma y buzones (Spec 004)."""

import sqlite3
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from jerico.crm.closing_model import (
    CandidateStatus,
    Contract,
    ContractStatus,
    LegalBasis,
    Mailbox,
    MailCandidate,
    Offer,
    OfferLine,
    Package,
    PackageStatus,
    Signature,
)
from jerico.crm.timeutil import to_iso

_ALLOWED_CONTRACT_COLUMNS = frozenset(
    {
        "status",
        "file_path",
        "sha256",
        "uploaded_by",
        "approved_by",
        "return_reason",
        "expires_at",
        "signed_at",
    }
)


def _format_datetime(val: datetime | str | None) -> str | None:
    if val is None:
        return None
    return to_iso(val) if isinstance(val, datetime) else str(val)


def _fetch_offer(conn: sqlite3.Connection, row: sqlite3.Row) -> Offer:
    lines_rows = conn.execute(
        "SELECT position, description, quantity, unit_price FROM crm_offer_lines "
        "WHERE offer_id = ? ORDER BY position ASC",
        (row["id"],),
    ).fetchall()
    lines = tuple(
        OfferLine(
            position=lr["position"],
            description=lr["description"],
            quantity=lr["quantity"],
            unit_price=lr["unit_price"],
        )
        for lr in lines_rows
    )
    return Offer(
        id=row["id"],
        lead_id=row["lead_id"],
        version=row["version"],
        currency=row["currency"],
        payment_terms=row["payment_terms"],
        valid_until=row["valid_until"],
        special_conditions=row["special_conditions"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        lines=lines,
    )


# --- Ofertas --------------------------------------------------------------------------


def insert_offer(
    conn: sqlite3.Connection,
    *,
    lead_id: int,
    currency: str,
    payment_terms: str,
    valid_until: datetime | str | None = None,
    special_conditions: str | None = None,
    created_by: int,
    now: datetime,
    lines: Sequence[tuple[str, int, int]],
) -> Offer:
    """Inserta una oferta con versión incremental por lead y sus líneas desde posición 1."""
    row_ver = conn.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 AS next_ver FROM crm_offers WHERE lead_id = ?",
        (lead_id,),
    ).fetchone()
    next_ver = int(row_ver["next_ver"])
    created_at = to_iso(now)
    valid_until_str = _format_datetime(valid_until)

    cur = conn.execute(
        "INSERT INTO crm_offers (lead_id, version, currency, payment_terms, valid_until, "
        "special_conditions, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
        (
            lead_id,
            next_ver,
            currency,
            payment_terms,
            valid_until_str,
            special_conditions,
            created_by,
            created_at,
        ),
    )
    offer_id = cur.fetchone()["id"]

    offer_lines: list[OfferLine] = []
    for idx, (desc, qty, unit_price) in enumerate(lines, start=1):
        conn.execute(
            "INSERT INTO crm_offer_lines (offer_id, position, description, quantity, unit_price) "
            "VALUES (?, ?, ?, ?, ?)",
            (offer_id, idx, desc, qty, unit_price),
        )
        offer_lines.append(
            OfferLine(
                position=idx,
                description=desc,
                quantity=qty,
                unit_price=unit_price,
            )
        )

    return Offer(
        id=offer_id,
        lead_id=lead_id,
        version=next_ver,
        currency=currency,
        payment_terms=payment_terms,
        valid_until=valid_until_str,
        special_conditions=special_conditions,
        created_by=created_by,
        created_at=created_at,
        lines=tuple(offer_lines),
    )


def get_offer(conn: sqlite3.Connection, offer_id: int) -> Offer | None:
    row = conn.execute("SELECT * FROM crm_offers WHERE id = ?", (offer_id,)).fetchone()
    return None if row is None else _fetch_offer(conn, row)


def latest_offer(conn: sqlite3.Connection, lead_id: int) -> Offer | None:
    row = conn.execute(
        "SELECT * FROM crm_offers WHERE lead_id = ? ORDER BY version DESC LIMIT 1",
        (lead_id,),
    ).fetchone()
    return None if row is None else _fetch_offer(conn, row)


# --- Paquetes -------------------------------------------------------------------------


def insert_package(
    conn: sqlite3.Connection,
    *,
    lead_id: int,
    offer_id: int,
    content_hash: str,
    legal_basis: str | LegalBasis,
    created_by: int,
    now: datetime,
) -> Package | None:
    """Inserta paquete en draft; devuelve None si ya existe un paquete vivo (ux_packages_live)."""
    row_ver = conn.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 AS next_ver FROM crm_packages WHERE lead_id = ?",
        (lead_id,),
    ).fetchone()
    next_ver = int(row_ver["next_ver"])
    legal_basis_str = legal_basis.value if isinstance(legal_basis, LegalBasis) else str(legal_basis)
    created_at = to_iso(now)

    cur = conn.execute(
        "INSERT INTO crm_packages (lead_id, version, offer_id, content_hash, status, "
        "legal_basis, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT DO NOTHING RETURNING *",
        (
            lead_id,
            next_ver,
            offer_id,
            content_hash,
            PackageStatus.DRAFT.value,
            legal_basis_str,
            created_by,
            created_at,
        ),
    )
    row = cur.fetchone()
    return None if row is None else Package(**dict(row))


def get_package(conn: sqlite3.Connection, package_id: int) -> Package | None:
    row = conn.execute("SELECT * FROM crm_packages WHERE id = ?", (package_id,)).fetchone()
    return None if row is None else Package(**dict(row))


def live_package(conn: sqlite3.Connection, lead_id: int) -> Package | None:
    row = conn.execute(
        "SELECT * FROM crm_packages WHERE lead_id = ? AND status IN ('draft','confirmed','sent')",
        (lead_id,),
    ).fetchone()
    return None if row is None else Package(**dict(row))


def set_package_status(
    conn: sqlite3.Connection,
    package_id: int,
    status: str | PackageStatus,
    *,
    confirmed_by: int | None = None,
    sent_at: datetime | str | None = None,
    now: datetime | None = None,
) -> None:
    """Actualiza el estado del paquete; solo modifica confirmed_by/sent_at si se pasan."""
    status_str = status.value if isinstance(status, PackageStatus) else str(status)
    updates = ["status = ?"]
    params: list[Any] = [status_str]

    if confirmed_by is not None:
        updates.append("confirmed_by = ?")
        params.append(confirmed_by)
    if sent_at is not None:
        updates.append("sent_at = ?")
        params.append(_format_datetime(sent_at))

    params.append(package_id)
    # S608 seguro: updates contiene solo identificadores fijos
    conn.execute(f"UPDATE crm_packages SET {', '.join(updates)} WHERE id = ?", params)  # noqa: S608


def packages_sent(conn: sqlite3.Connection) -> list[Package]:
    rows = conn.execute(
        "SELECT * FROM crm_packages WHERE status = 'sent' ORDER BY id ASC"
    ).fetchall()
    return [Package(**dict(r)) for r in rows]


# --- Contratos ------------------------------------------------------------------------


def insert_contract(
    conn: sqlite3.Connection,
    *,
    package_id: int,
    now: datetime,
) -> Contract | None:
    """Inserta contrato en package_sent; None si ya hay uno vivo para el paquete."""
    cur = conn.execute(
        "INSERT INTO crm_contracts (package_id, status, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT DO NOTHING RETURNING *",
        (package_id, ContractStatus.PACKAGE_SENT.value, to_iso(now)),
    )
    row = cur.fetchone()
    return None if row is None else Contract(**dict(row))


def get_contract(conn: sqlite3.Connection, contract_id: int) -> Contract | None:
    row = conn.execute("SELECT * FROM crm_contracts WHERE id = ?", (contract_id,)).fetchone()
    return None if row is None else Contract(**dict(row))


def contract_for_package(conn: sqlite3.Connection, package_id: int) -> Contract | None:
    row = conn.execute(
        "SELECT * FROM crm_contracts WHERE package_id = ? ORDER BY id DESC LIMIT 1",
        (package_id,),
    ).fetchone()
    return None if row is None else Contract(**dict(row))


def update_contract(conn: sqlite3.Connection, contract_id: int, **changes: Any) -> None:
    """Actualiza columnas permitidas del contrato; lanza ValueError si la columna no es válida."""
    if not changes:
        return
    for col in changes:
        if col not in _ALLOWED_CONTRACT_COLUMNS:
            raise ValueError(f"columna no permitida en crm_contracts: {col}")

    set_parts: list[str] = []
    params: list[Any] = []
    for col in sorted(changes.keys()):
        val = changes[col]
        if col == "status" and isinstance(val, ContractStatus):
            val = val.value
        elif col in ("expires_at", "signed_at") and isinstance(val, datetime):
            val = to_iso(val)
        set_parts.append(f"{col} = ?")
        params.append(val)

    params.append(contract_id)
    # S608 seguro: set_parts proviene estrictamente de _ALLOWED_CONTRACT_COLUMNS
    conn.execute(f"UPDATE crm_contracts SET {', '.join(set_parts)} WHERE id = ?", params)  # noqa: S608


def contracts_with_status(conn: sqlite3.Connection, status: str | ContractStatus) -> list[Contract]:
    status_str = status.value if isinstance(status, ContractStatus) else str(status)
    rows = conn.execute(
        "SELECT * FROM crm_contracts WHERE status = ? ORDER BY id ASC",
        (status_str,),
    ).fetchall()
    return [Contract(**dict(r)) for r in rows]


def expired_contracts(conn: sqlite3.Connection, now: datetime) -> list[Contract]:
    now_iso = to_iso(now)
    rows = conn.execute(
        "SELECT * FROM crm_contracts WHERE status = 'sent_for_signature' "
        "AND expires_at IS NOT NULL AND expires_at <= ? ORDER BY id ASC",
        (now_iso,),
    ).fetchall()
    return [Contract(**dict(r)) for r in rows]


# --- Firmas ---------------------------------------------------------------------------


def insert_signature(
    conn: sqlite3.Connection,
    *,
    contract_id: int,
    provider: str,
    external_id: str | None = None,
    status: str,
    now: datetime,
) -> Signature:
    now_iso = to_iso(now)
    cur = conn.execute(
        "INSERT INTO crm_signatures (contract_id, provider, external_id, status, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?) RETURNING *",
        (contract_id, provider, external_id, status, now_iso, now_iso),
    )
    return Signature(**dict(cur.fetchone()))


def signature_by_external(
    conn: sqlite3.Connection, provider: str, external_id: str
) -> Signature | None:
    row = conn.execute(
        "SELECT * FROM crm_signatures WHERE provider = ? AND external_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (provider, external_id),
    ).fetchone()
    return None if row is None else Signature(**dict(row))


def update_signature(
    conn: sqlite3.Connection,
    signature_id: int,
    *,
    status: str,
    now: datetime,
    evidence_path: str | None = None,
    evidence_sha256: str | None = None,
) -> None:
    updates = ["status = ?", "updated_at = ?"]
    params: list[Any] = [status, to_iso(now)]
    if evidence_path is not None:
        updates.append("evidence_path = ?")
        params.append(evidence_path)
    if evidence_sha256 is not None:
        updates.append("evidence_sha256 = ?")
        params.append(evidence_sha256)

    params.append(signature_id)
    # S608 seguro: updates contiene solo identificadores fijos
    conn.execute(f"UPDATE crm_signatures SET {', '.join(updates)} WHERE id = ?", params)  # noqa: S608


# --- Buzones --------------------------------------------------------------------------


def upsert_mailbox(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    address: str,
    secret_env: str,
) -> Mailbox:
    cur = conn.execute(
        "INSERT INTO crm_mailboxes (user_id, address, secret_env, active) VALUES (?, ?, ?, 1) "
        "ON CONFLICT (user_id) DO UPDATE SET address = excluded.address, "
        "secret_env = excluded.secret_env, active = 1 RETURNING *",
        (user_id, address, secret_env),
    )
    return Mailbox(**dict(cur.fetchone()))


def mailbox_for_user(conn: sqlite3.Connection, user_id: int) -> Mailbox | None:
    row = conn.execute("SELECT * FROM crm_mailboxes WHERE user_id = ?", (user_id,)).fetchone()
    return None if row is None else Mailbox(**dict(row))


def active_mailboxes(conn: sqlite3.Connection) -> list[Mailbox]:
    rows = conn.execute("SELECT * FROM crm_mailboxes WHERE active = 1 ORDER BY id ASC").fetchall()
    return [Mailbox(**dict(r)) for r in rows]


def set_mailbox_ok(conn: sqlite3.Connection, mailbox_id: int, now: datetime) -> None:
    conn.execute(
        "UPDATE crm_mailboxes SET last_ok_at = ? WHERE id = ?",
        (to_iso(now), mailbox_id),
    )


# --- Candidatos de correo -------------------------------------------------------------


def insert_candidate(
    conn: sqlite3.Connection,
    *,
    mailbox_id: int,
    message_id: str,
    sender_email: str,
    sender_name: str | None = None,
    subject: str | None = None,
    received_at: datetime | str,
    expires_at: datetime | str,
) -> MailCandidate | None:
    rx_iso = to_iso(received_at) if isinstance(received_at, datetime) else str(received_at)
    exp_iso = to_iso(expires_at) if isinstance(expires_at, datetime) else str(expires_at)

    cur = conn.execute(
        "INSERT INTO crm_mail_candidates (mailbox_id, message_id, sender_email, sender_name, "
        "subject, received_at, status, expires_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?) "
        "ON CONFLICT (mailbox_id, message_id) DO NOTHING RETURNING *",
        (
            mailbox_id,
            message_id,
            sender_email,
            sender_name,
            subject,
            rx_iso,
            exp_iso,
        ),
    )
    row = cur.fetchone()
    return None if row is None else MailCandidate(**dict(row))


def pending_candidates(conn: sqlite3.Connection, mailbox_ids: Sequence[int]) -> list[MailCandidate]:
    if not mailbox_ids:
        return []
    placeholders = ", ".join("?" for _ in mailbox_ids)
    # S608 seguro: placeholders son únicamente signos '?' según la longitud de mailbox_ids
    query = (
        f"SELECT * FROM crm_mail_candidates WHERE status = 'pending' "  # noqa: S608
        f"AND mailbox_id IN ({placeholders}) ORDER BY id ASC"
    )
    rows = conn.execute(query, list(mailbox_ids)).fetchall()
    return [MailCandidate(**dict(r)) for r in rows]


def get_candidate(conn: sqlite3.Connection, candidate_id: int) -> MailCandidate | None:
    row = conn.execute("SELECT * FROM crm_mail_candidates WHERE id = ?", (candidate_id,)).fetchone()
    return None if row is None else MailCandidate(**dict(row))


def set_candidate_status(
    conn: sqlite3.Connection,
    candidate_id: int,
    status: str | CandidateStatus,
    *,
    lead_id: int | None = None,
) -> None:
    status_str = status.value if isinstance(status, CandidateStatus) else str(status)
    if lead_id is not None:
        conn.execute(
            "UPDATE crm_mail_candidates SET status = ?, lead_id = ? WHERE id = ?",
            (status_str, lead_id, candidate_id),
        )
    else:
        conn.execute(
            "UPDATE crm_mail_candidates SET status = ? WHERE id = ?",
            (status_str, candidate_id),
        )


def purge_expired_candidates(conn: sqlite3.Connection, now: datetime) -> int:
    """Borra candidatos pending o discarded vencidos; anonimiza los registered vencidos."""
    now_iso = to_iso(now)
    cur = conn.execute(
        "DELETE FROM crm_mail_candidates WHERE status IN ('pending', 'discarded') AND "
        "expires_at <= ?",
        (now_iso,),
    )
    deleted_count = cur.rowcount
    conn.execute(
        "UPDATE crm_mail_candidates SET sender_email = '', sender_name = '', subject = '' "
        "WHERE status = 'registered' AND expires_at <= ? AND "
        "(sender_email != '' OR sender_name != '' OR subject != '')",
        (now_iso,),
    )
    return deleted_count


def next_package_version(conn: sqlite3.Connection, lead_id: int) -> int:
    """Versión que asignará `insert_package` (máximo + 1), para armar el hash con la misma."""
    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 FROM crm_packages WHERE lead_id = ?", (lead_id,)
    ).fetchone()
    return int(row[0])


def signature_for_contract(conn: sqlite3.Connection, contract_id: int) -> Signature | None:
    """Firma más reciente del contrato (puede haberse reintentado)."""
    row = conn.execute(
        "SELECT * FROM crm_signatures WHERE contract_id = ? ORDER BY id DESC LIMIT 1",
        (contract_id,),
    ).fetchone()
    return None if row is None else Signature(**dict(row))
