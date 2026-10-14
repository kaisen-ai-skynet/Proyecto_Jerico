"""Paquete de cierre (spec 004 §4): armado, completitud, hash y texto. Puro, sin red ni base.

Contiene solo el handoff validado de F1 y la oferta (VCRM-P01): nunca notas, historial ni correos.
El texto jurídico del contrato NO se genera aquí ni en ningún otro sitio (VCRM-C13)."""

import hashlib
import json
from datetime import date, datetime

from jerico.crm.closing_model import LegalBasis, Offer
from jerico.crm.handoff import missing_handoff_fields
from jerico.crm.model import AuthStatus, Lead
from jerico.crm.render import short_id
from jerico.schemas import Cotizacion, CotizacionLinea, PaqueteContrato
from jerico.schemas import Lead as LeadSchema


class PackageError(ValueError):
    """El paquete no se puede armar; el mensaje es apto para mostrarse al comercial."""


def resolve_legal_basis(lead: Lead, lawyer_confirmed: bool) -> LegalBasis | None:
    """VCRM-P03: autorización vigente, o base confirmada por escrito por el abogado."""
    if lead.auth_status == AuthStatus.AUTHORIZED:
        return LegalBasis.AUTHORIZATION
    return LegalBasis.LAWYER_CONFIRMED if lawyer_confirmed else None


def build_package(
    lead: Lead, offer: Offer, *, version: int, legal_basis: LegalBasis, now: datetime
) -> PaqueteContrato:
    missing = missing_handoff_fields(lead)
    if missing:
        raise PackageError("Faltan datos del cliente: " + ", ".join(missing) + ".")
    if not offer.lines:
        raise PackageError("La oferta no tiene líneas de servicio.")
    quote = Cotizacion(
        currency=offer.currency,
        lines=[
            CotizacionLinea(
                description=line.description, quantity=line.quantity, unit_price=line.unit_price
            )
            for line in offer.lines
        ],
        payment_terms=offer.payment_terms,
        valid_until=date.fromisoformat(offer.valid_until) if offer.valid_until else None,
        special_conditions=offer.special_conditions,
    )
    return PaqueteContrato(
        lead=LeadSchema(
            id=lead.id,
            state=lead.state,
            name=lead.name,
            company=lead.company,
            client_type=lead.client_type,
            doc_type=lead.doc_type,
            doc_number=lead.doc_number,
            legal_rep=lead.legal_rep,
            phone_e164=lead.phone_e164,
            email=lead.email,
            service=lead.service,
            agreed_value=lead.agreed_value,
            start_term=lead.start_term,
        ),
        cotizacion=quote,
        version=version,
        legal_basis=legal_basis.value,
        generated_at=now,
    )


def content_hash(package: PaqueteContrato) -> str:
    """SHA-256 del contenido; excluye la fecha de generación para que sea reproducible."""
    data = package.model_dump(mode="json", exclude={"generated_at"})
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def attachment_name(lead_id: int, version: int) -> str:
    """VCRM-C22: el nombre del archivo no lleva datos personales."""
    return f"paquete-{short_id(lead_id)}-v{version}.md"


def _money(amount: int, currency: str) -> str:
    return f"{amount:,}".replace(",", ".") + f" {currency}"


_BASIS_TEXT = {
    LegalBasis.AUTHORIZATION.value: "autorización vigente del titular",
    LegalBasis.LAWYER_CONFIRMED.value: "base confirmada por escrito por el abogado",
}


def render_markdown(package: PaqueteContrato) -> str:
    lead, quote = package.lead, package.cotizacion
    rows = [
        ("Tipo de cliente", lead.client_type),
        ("Nombre o razón social", lead.company or lead.name),
        ("Documento", f"{lead.doc_type} {lead.doc_number}"),
        ("Representante legal", lead.legal_rep),
        ("Teléfono", lead.phone_e164),
        ("Correo", lead.email),
        ("Servicio", lead.service),
        ("Plazo o inicio", lead.start_term),
    ]
    lines = [
        f"# Paquete de cierre {short_id(lead.id)} — versión {package.version}",
        "",
        "## Cliente",
        *[f"- {label}: {value}" for label, value in rows if value],
        "",
        "## Oferta",
        *[
            f"- {line.description}: {line.quantity} × {_money(line.unit_price, quote.currency)}"
            for line in quote.lines
        ],
        f"- **Total: {_money(quote.total, quote.currency)}**",
        f"- Forma de pago: {quote.payment_terms}",
    ]
    if quote.valid_until:
        lines.append(f"- Vigencia de la oferta: {quote.valid_until.isoformat()}")
    if quote.special_conditions:
        lines.append(f"- Condiciones especiales: {quote.special_conditions}")
    lines += [
        "",
        "## Tratamiento de datos",
        f"- Base: {_BASIS_TEXT.get(package.legal_basis, package.legal_basis)}.",
        "- Uso exclusivo para preparar el contrato; no reenviar ni conservar fuera del caso.",
    ]
    return "\n".join(lines) + "\n"
