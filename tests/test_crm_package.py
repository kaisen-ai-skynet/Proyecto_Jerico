"""Paquete de cierre: armado, completitud, hash y render (VCRM-C01..C05, C22, P01, P03)."""

from datetime import UTC, datetime

import pytest

from crm_support import make_lead
from jerico.crm.closing_model import LegalBasis, Offer, OfferLine
from jerico.crm.package import (
    PackageError,
    attachment_name,
    build_package,
    content_hash,
    render_markdown,
    resolve_legal_basis,
)

NOW = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)


def _complete(**kw: object):  # type: ignore[no-untyped-def]
    base = {
        "client_type": "empresa",
        "name": "Ana Pérez",
        "company": "Distribuciones Andina SAS",
        "doc_type": "NIT",
        "doc_number": "900123456",
        "legal_rep": "Carlos Gómez",
        "phone_e164": "+573001234567",
        "email": "contacto@andina.co",
        "service": "Chatbot de ventas",
        "agreed_value": "12.000.000 COP",
        "start_term": "1 de abril",
        "auth_status": "authorized",
        "state": "accepted",
    }
    return make_lead(**{**base, **kw})


def _offer(**kw: object) -> Offer:
    base: dict[str, object] = {
        "id": 3,
        "lead_id": 42,
        "version": 1,
        "currency": "COP",
        "payment_terms": "50 % anticipo",
        "valid_until": "2026-04-30",
        "special_conditions": None,
        "created_by": 1,
        "created_at": "2026-03-02T15:00:00Z",
        "lines": (OfferLine(1, "Chatbot", 1, 12_000_000),),
    }
    return Offer(**{**base, **kw})  # type: ignore[arg-type]


def test_vcrmc02_complete_lead_and_offer_build_a_package() -> None:
    pkg = build_package(
        _complete(), _offer(), version=1, legal_basis=LegalBasis.AUTHORIZATION, now=NOW
    )
    assert pkg.cotizacion.total == 12_000_000 and pkg.lead.id == 42
    assert pkg.legal_basis == "authorization" and pkg.version == 1


def test_vcrmc02_missing_handoff_fields_block_the_package_and_are_listed() -> None:
    lead = _complete(email=None, service=None)
    with pytest.raises(PackageError) as info:
        build_package(lead, _offer(), version=1, legal_basis=LegalBasis.AUTHORIZATION, now=NOW)
    assert "correo" in str(info.value) and "servicio" in str(info.value)


def test_vcrmc02_offer_without_lines_is_rejected() -> None:
    with pytest.raises(PackageError):
        build_package(
            _complete(), _offer(lines=()), version=1, legal_basis=LegalBasis.AUTHORIZATION, now=NOW
        )


def test_vcrmc04_hash_is_stable_changes_with_the_offer_and_ignores_the_clock() -> None:
    a = build_package(
        _complete(), _offer(), version=1, legal_basis=LegalBasis.AUTHORIZATION, now=NOW
    )
    later = datetime(2026, 3, 9, tzinfo=UTC)
    b = build_package(
        _complete(), _offer(), version=1, legal_basis=LegalBasis.AUTHORIZATION, now=later
    )
    c = build_package(
        _complete(),
        _offer(lines=(OfferLine(1, "Chatbot", 1, 13_000_000),)),
        version=1,
        legal_basis=LegalBasis.AUTHORIZATION,
        now=NOW,
    )
    assert content_hash(a) == content_hash(b) != content_hash(c)
    assert len(content_hash(a)) == 64


def test_vcrmp03_legal_basis_requires_authorization_or_lawyer_confirmation() -> None:
    assert (
        resolve_legal_basis(_complete(auth_status="authorized"), False) == LegalBasis.AUTHORIZATION
    )
    assert resolve_legal_basis(_complete(auth_status="unauthorized"), False) is None
    assert (
        resolve_legal_basis(_complete(auth_status="revoked"), True) == LegalBasis.LAWYER_CONFIRMED
    )
    assert (
        resolve_legal_basis(_complete(auth_status="unauthorized"), True)
        == LegalBasis.LAWYER_CONFIRMED
    )


def test_vcrmc22_attachment_name_has_no_personal_data() -> None:
    assert attachment_name(42, 3) == "paquete-L-0042-v3.md"


def test_render_markdown_includes_the_offer_and_only_the_package_data() -> None:
    lead = _complete()
    pkg = build_package(
        lead,
        _offer(special_conditions="Soporte 8x5"),
        version=2,
        legal_basis=LegalBasis.AUTHORIZATION,
        now=NOW,
    )
    text = render_markdown(pkg)
    for needle in (
        "L-0042",
        "versión 2",
        "Distribuciones Andina SAS",
        "900123456",
        "Chatbot",
        "12.000.000",
        "COP",
        "50 % anticipo",
        "Soporte 8x5",
        "autorización",
    ):
        assert needle in text
    assert "notas" not in text.lower()
