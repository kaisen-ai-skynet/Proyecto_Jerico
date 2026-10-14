"""Flujo comercial del cierre (spec 004 §4): `/oferta`, confirmación y entrega al abogado.

Todo lo que lleva datos del cliente a un tercero (el abogado) exige ✅ del comercial o del CTO
(VCRM-C03). Las acciones externas son idempotentes (clave determinista) y respetan DRY_RUN."""

import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from jerico.crm import closing_repo as crepo
from jerico.crm import leads, repo
from jerico.crm.bot import CrmBot, deny
from jerico.crm.closing_model import ContractStatus, LegalBasis, Package, PackageStatus
from jerico.crm.handoff import missing_handoff_fields
from jerico.crm.idempotency import claim, make_key
from jerico.crm.model import (
    AuditAction,
    AuditOutcome,
    Channel,
    Lead,
    LeadState,
    Outgoing,
    Role,
    User,
)
from jerico.crm.outbox import enqueue_critical
from jerico.crm.package import (
    PackageError,
    attachment_name,
    build_package,
    content_hash,
    render_markdown,
    resolve_legal_basis,
)
from jerico.crm.parsing import build_callback, parse_short_id
from jerico.crm.permissions import Action, authorize
from jerico.crm.render import short_id
from jerico.schemas import PaqueteContrato

OFFER_COMMAND = "oferta"
OFFER_EXAMPLE = (
    "/oferta L-0042; moneda COP; pago 50 % anticipo; linea Chatbot x1 @12000000; "
    "linea Soporte x1 @500000; vigencia 2026-04-30; condiciones Soporte 8x5"
)
PKG_SEND = "pkgok"
PKG_CANCEL = "pkgno"
MAX_TELEGRAM_CHARS = 3500
NOT_ACCEPTED = "El lead debe estar en «aceptado» para armar el paquete de cierre."
NO_LAWYER = (
    "No hay un abogado activo en el sistema: el paquete no se envía. "
    "Pídele al CTO que dé de alta al abogado con /alta."
)
NO_BASIS = (
    "No hay base legal para tratar los datos: falta la autorización vigente del titular. "
    "El abogado puede confirmar otra base con /basejuridica."
)
NOT_YOURS = "No encontré ese lead entre los que puedes gestionar."
STALE = "Los datos del cliente o de la oferta cambiaron. Genera el paquete de nuevo con /oferta."
GATE_CLOSED = "Esa propuesta ya no está pendiente."


@dataclass(frozen=True)
class ClosingContext:
    dry_run: bool = True  # Plan Maestro §4: lo externo se redirige al CTO


@dataclass(frozen=True)
class OfferInput:
    lead_id: int
    currency: str
    payment_terms: str
    lines: tuple[tuple[str, int, int], ...]
    valid_until: str | None
    special_conditions: str | None


@dataclass(frozen=True)
class OfferError:
    message: str


_LINE = re.compile(r"^linea\s+(.+?)\s+x\s*(\d+)\s+@\s*([\d.,]+)$", re.IGNORECASE)
_CURRENCY = re.compile(r"^[A-Za-z]{3}$")


def _price(raw: str) -> int | None:
    digits = re.sub(r"[.,]", "", raw)
    return int(digits) if digits.isdigit() else None


def parse_offer(text: str) -> OfferInput | OfferError:
    body = re.sub(r"^/\w+(?:@\w+)?", "", text.strip()).strip()
    first, *rest = [part.strip() for part in body.split(";")]
    lead_id = parse_short_id(first)
    if lead_id is None:
        return OfferError(f"Indica el lead al inicio. Ejemplo: {OFFER_EXAMPLE}")
    currency, payment, valid_until, conditions = "COP", "", None, None
    lines: list[tuple[str, int, int]] = []
    for segment in rest:
        key, _, value = segment.partition(" ")
        key, value = key.lower(), value.strip()
        if key == "moneda":
            if not _CURRENCY.match(value):
                return OfferError("La moneda debe ser un código de 3 letras, por ejemplo COP.")
            currency = value.upper()
        elif key == "pago":
            payment = value
        elif key == "linea":
            m = _LINE.match(segment)
            price = _price(m.group(3)) if m else None
            if m is None or price is None or int(m.group(2)) < 1:
                return OfferError(
                    f"Línea no válida: «{segment}». Formato: linea Chatbot x1 @12000000"
                )
            lines.append((m.group(1).strip(), int(m.group(2)), price))
        elif key == "vigencia":
            try:
                date.fromisoformat(value)
            except ValueError:
                return OfferError("La vigencia debe tener formato AAAA-MM-DD.")
            valid_until = value
        elif key == "condiciones":
            conditions = value or None
        elif segment:
            return OfferError(f"No entendí «{segment}». Ejemplo: {OFFER_EXAMPLE}")
    if not payment:
        return OfferError(f"Falta la forma de pago (pago ...). Ejemplo: {OFFER_EXAMPLE}")
    if not lines:
        return OfferError(f"Falta al menos una línea (linea ...). Ejemplo: {OFFER_EXAMPLE}")
    return OfferInput(lead_id, currency, payment, tuple(lines), valid_until, conditions)


def _audit(
    conn: sqlite3.Connection, actor: User, lead_id: int, outcome: AuditOutcome, now: datetime
) -> None:
    repo.audit(
        conn,
        actor=f"user:{actor.id}",
        action=AuditAction.PACKAGE_EVENT,
        outcome=outcome,
        at=now,
        lead_id=lead_id,
    )


def lawyer_basis_key(lead_id: int) -> str:
    return f"legal_basis_confirmed:{lead_id}"


def _basis(conn: sqlite3.Connection, lead: Lead) -> LegalBasis | None:
    return resolve_legal_basis(lead, repo.get_meta(conn, lawyer_basis_key(lead.id)) is not None)


def offer_command(
    conn: sqlite3.Connection, actor: User, text: str, now: datetime
) -> list[Outgoing]:
    chat = actor.telegram_id
    parsed = parse_offer(text)
    if isinstance(parsed, OfferError):
        return [Outgoing(chat, parsed.message)]
    lead = repo.get_lead(conn, parsed.lead_id)
    if lead is None:
        return [Outgoing(chat, NOT_YOURS)]
    decision = authorize(actor, Action.PACKAGE_MANAGE, lead)
    if not decision.allowed:
        return leads.deny_lead(conn, actor, decision, lead.id, now)
    if lead.state != LeadState.ACCEPTED or lead.suppressed_at is not None or lead.commercial_block:
        return [Outgoing(chat, NOT_ACCEPTED)]
    missing = missing_handoff_fields(lead)
    if missing:
        return [Outgoing(chat, "Faltan datos del cliente: " + ", ".join(missing) + ".")]
    basis = _basis(conn, lead)
    if basis is None:
        return [Outgoing(chat, NO_BASIS)]

    live = crepo.live_package(conn, lead.id)
    if live is not None:  # C04: una edición crea versión nueva y retira la anterior
        crepo.set_package_status(conn, live.id, PackageStatus.SUPERSEDED)
        old = crepo.contract_for_package(conn, live.id)
        if old is not None and old.status != ContractStatus.SIGNED:
            crepo.update_contract(conn, old.id, status=ContractStatus.CANCELLED)
    offer = crepo.insert_offer(
        conn,
        lead_id=lead.id,
        currency=parsed.currency,
        payment_terms=parsed.payment_terms,
        valid_until=parsed.valid_until,
        special_conditions=parsed.special_conditions,
        created_by=actor.id,
        now=now,
        lines=parsed.lines,
    )
    version = (live.version + 1) if live is not None else 1
    try:
        package = build_package(lead, offer, version=version, legal_basis=basis, now=now)
    except (PackageError, ValueError) as exc:
        return [Outgoing(chat, str(exc))]
    stored = crepo.insert_package(
        conn,
        lead_id=lead.id,
        offer_id=offer.id,
        content_hash=content_hash(package),
        legal_basis=basis.value,
        created_by=actor.id,
        now=now,
    )
    if stored is None:  # pragma: no cover - defensa: el paquete vivo ya se retiró arriba
        return [Outgoing(chat, GATE_CLOSED)]
    _audit(conn, actor, lead.id, AuditOutcome.OK, now)
    preview = render_markdown(package)[:MAX_TELEGRAM_CHARS]
    return [
        Outgoing(
            chat,
            f"{preview}\n¿Enviar este paquete al abogado? Contiene datos personales del cliente.",
            (
                (
                    ("✅ Enviar al abogado", build_callback(PKG_SEND, str(stored.id))),
                    ("❌ Cancelar", build_callback(PKG_CANCEL, str(stored.id))),
                ),
            ),
        )
    ]


def _package_for_callback(
    conn: sqlite3.Connection, args: tuple[str, ...]
) -> tuple[Package | None, Lead | None]:
    if len(args) != 1 or not args[0].isdigit():
        return None, None
    package = crepo.get_package(conn, int(args[0]))
    lead = None if package is None else repo.get_lead(conn, package.lead_id)
    return package, lead


def cancel_callback(
    conn: sqlite3.Connection, actor: User, args: tuple[str, ...], now: datetime
) -> list[Outgoing]:
    package, lead = _package_for_callback(conn, args)
    if package is None or lead is None or package.status != PackageStatus.DRAFT:
        return [Outgoing(actor.telegram_id, GATE_CLOSED)]
    decision = authorize(actor, Action.PACKAGE_MANAGE, lead)
    if not decision.allowed:
        return leads.deny_lead(conn, actor, decision, lead.id, now)
    crepo.set_package_status(conn, package.id, PackageStatus.CANCELLED)
    _audit(conn, actor, lead.id, AuditOutcome.OK, now)
    return [Outgoing(actor.telegram_id, f"Paquete de {short_id(lead.id)} cancelado.")]


def _rebuild(
    conn: sqlite3.Connection, lead: Lead, package: Package, now: datetime
) -> PaqueteContrato | None:
    offer = crepo.get_offer(conn, package.offer_id)
    if offer is None:  # pragma: no cover - la oferta existe por clave foránea
        return None
    return build_package(
        lead,
        offer,
        version=package.version,
        legal_basis=LegalBasis(package.legal_basis),
        now=now,
    )


def send_callback(
    ctx: ClosingContext,
) -> Callable[[sqlite3.Connection, User, tuple[str, ...], datetime], list[Outgoing]]:
    def handler(
        conn: sqlite3.Connection, actor: User, args: tuple[str, ...], now: datetime
    ) -> list[Outgoing]:
        chat = actor.telegram_id
        package, lead = _package_for_callback(conn, args)
        if package is None or lead is None or package.status != PackageStatus.DRAFT:
            return [Outgoing(chat, GATE_CLOSED)]
        decision = authorize(actor, Action.PACKAGE_MANAGE, lead)
        if not decision.allowed:
            return leads.deny_lead(conn, actor, decision, lead.id, now)
        lawyers = repo.active_users(conn, Role.LAWYER)
        if not lawyers:  # C21
            return [Outgoing(chat, NO_LAWYER)]
        if (
            lead.state != LeadState.ACCEPTED
            or lead.suppressed_at is not None
            or lead.commercial_block
        ):
            return [Outgoing(chat, NOT_ACCEPTED)]
        try:
            rebuilt = _rebuild(conn, lead, package, now)
        except (PackageError, ValueError):
            rebuilt = None
        if rebuilt is None or content_hash(rebuilt) != package.content_hash:
            return [Outgoing(chat, STALE)]  # C04: el contenido aprobado es el que se envía
        if not claim(conn, make_key("package_send", lead.id, f"v{package.version}"), now):
            return [Outgoing(chat, GATE_CLOSED)]
        crepo.set_package_status(
            conn, package.id, PackageStatus.SENT, confirmed_by=actor.id, sent_at=now
        )
        crepo.insert_contract(conn, package_id=package.id, now=now)
        _deliver_to_lawyer(conn, ctx, lead, package.version, rebuilt, lawyers, now)
        _audit(conn, actor, lead.id, AuditOutcome.OK, now)
        suffix = " (DRY_RUN: redirigido al CTO)" if ctx.dry_run else ""
        return [Outgoing(chat, f"Paquete de {short_id(lead.id)} enviado al abogado{suffix}.")]

    return handler


def _deliver_to_lawyer(
    conn: sqlite3.Connection,
    ctx: ClosingContext,
    lead: Lead,
    version: int,
    package: PaqueteContrato,
    lawyers: list[User],
    now: datetime,
) -> None:
    body = render_markdown(package)
    name = attachment_name(lead.id, version)
    subject = f"Paquete de cierre {short_id(lead.id)} (v{version})"
    prefix = "[DRY_RUN → abogado] " if ctx.dry_run else ""
    telegram_text = f"{prefix}{subject}\n\n{body}"[:MAX_TELEGRAM_CHARS]
    email_body = f"{body}\nArchivo lógico: {name}\n"
    telegram_to = repo.active_users(conn, Role.CTO) if ctx.dry_run else lawyers
    for user in telegram_to:
        enqueue_critical(
            conn,
            kind="package_delivery",
            channel=Channel.TELEGRAM,
            recipient_user_id=user.id,
            lead_id=lead.id,
            subject=None,
            body=telegram_text,
            key=make_key("package_send", lead.id, f"v{version}", "telegram", user.id),
            now=now,
        )
    for lawyer in lawyers:  # el correo sale por el EmailSender (que ya redirige en DRY_RUN)
        enqueue_critical(
            conn,
            kind="package_delivery",
            channel=Channel.EMAIL,
            recipient_user_id=lawyer.id,
            lead_id=lead.id,
            subject=subject,
            body=email_body,
            key=make_key("package_send", lead.id, f"v{version}", "email", lawyer.id),
            now=now,
        )


# --- Abogado (spec 004 §8) --------------------------------------------------------------------

NO_CASES = "No tienes casos con paquete enviado."


def cases_command(
    conn: sqlite3.Connection, actor: User, text: str, now: datetime
) -> list[Outgoing]:
    chat = actor.telegram_id
    if actor.role != Role.LAWYER:  # /casos es del abogado (VCRM-R01)
        return deny(conn, actor, now)
    rows: list[str] = []
    for package in crepo.packages_sent(conn):
        lead = repo.get_lead(conn, package.lead_id)
        if lead is None or not lead.ever_accepted:
            continue
        contract = crepo.contract_for_package(conn, package.id)
        status = contract.status if contract is not None else "sin contrato"
        rows.append(f"{short_id(lead.id)} · paquete v{package.version} · {status}")
    return [Outgoing(chat, "\n".join(rows) if rows else NO_CASES)]


def package_command(
    conn: sqlite3.Connection, actor: User, text: str, now: datetime
) -> list[Outgoing]:
    chat = actor.telegram_id
    arg = re.sub(r"^/\w+(?:@\w+)?", "", text.strip()).strip()
    lead_id = parse_short_id(arg)
    lead = None if lead_id is None else repo.get_lead(conn, lead_id)
    if lead is None:
        return [Outgoing(chat, "Indica el caso, por ejemplo: /paquete L-0042")]
    decision = authorize(actor, Action.PACKAGE_VIEW, lead)
    if not decision.allowed:
        return leads.deny_lead(conn, actor, decision, lead.id, now)
    package = crepo.live_package(conn, lead.id)
    if package is None or package.status != PackageStatus.SENT:
        if actor.role == Role.LAWYER:
            return [Outgoing(chat, "Ese caso no tiene un paquete enviado.")]
        return [Outgoing(chat, "Ese lead no tiene un paquete enviado.")]
    built = _rebuild(conn, lead, package, now)
    if built is None:  # pragma: no cover - la oferta existe por clave foránea
        return [Outgoing(chat, STALE)]
    return [Outgoing(chat, render_markdown(built)[:MAX_TELEGRAM_CHARS])]


def legal_basis_command(
    conn: sqlite3.Connection, actor: User, text: str, now: datetime
) -> list[Outgoing]:
    """El abogado confirma por escrito otra base legal cuando no hay autorización (VCRM-P03)."""
    chat = actor.telegram_id
    arg = re.sub(r"^/\w+(?:@\w+)?", "", text.strip()).strip()
    lead_id = parse_short_id(arg)
    lead = None if lead_id is None else repo.get_lead(conn, lead_id)
    if lead is None:
        return [Outgoing(chat, "Indica el caso, por ejemplo: /basejuridica L-0042")]
    decision = authorize(actor, Action.CONTRACT_UPLOAD, lead)
    if not decision.allowed:
        return leads.deny_lead(conn, actor, decision, lead.id, now)
    repo.set_meta(conn, lawyer_basis_key(lead.id), str(actor.id))
    _audit(conn, actor, lead.id, AuditOutcome.OK, now)
    return [
        Outgoing(chat, f"Base legal de {short_id(lead.id)} confirmada por ti. Queda registrada.")
    ]


def register_closing(bot: CrmBot, ctx: ClosingContext) -> None:
    bot.register_command(OFFER_COMMAND, offer_command)
    bot.register_callback(PKG_SEND, send_callback(ctx))
    bot.register_callback(PKG_CANCEL, cancel_callback)
    bot.register_command("casos", cases_command)
    bot.register_command("paquete", package_command)
    bot.register_command("basejuridica", legal_basis_command)
