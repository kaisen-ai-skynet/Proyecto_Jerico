"""Tests de handoff y textos (VCRM-048, 090, 104, 111, 112, 156)."""

import dataclasses

import pytest

from crm_support import make_lead
from jerico.crm.handoff import (
    CLIENT_TYPES,
    DOC_TYPES,
    HandoffValueError,
    missing_handoff_fields,
    validate_handoff_value,
)
from jerico.crm.model import Lead
from jerico.crm.parsing import parse_callback
from jerico.crm.render import (
    PAGE_SIZE,
    TELEGRAM_LIMIT,
    LawyerView,
    acceptance_alert_for_lawyer,
    acceptance_email_for_lawyer,
    acceptance_for_cto,
    handoff_error_text,
    lawyer_view,
    render_list_page,
    short_id,
    split_message,
)

REP = "representante legal (obligatorio si es empresa)"

COMPLETE_NATURAL = {
    "client_type": "persona natural",
    "doc_type": "cédula de ciudadanía",
    "doc_number": "1020304050",
    "service": "Plan anual",
    "agreed_value": "12.000.000 COP",
    "start_term": "2026-11-01",
}
COMPLETE_COMPANY = {
    **COMPLETE_NATURAL,
    "client_type": "empresa",
    "company": "Empresa SAS",
    "doc_type": "NIT",
    "doc_number": "900123456-7",
    "legal_rep": "Luis Gómez",
}

# --- Completitud del handoff (VCRM-111) -------------------------------------


def test_vcrm111_natural_person_complete_has_no_missing() -> None:
    assert missing_handoff_fields(make_lead(**COMPLETE_NATURAL)) == ()


def test_vcrm111_natural_person_does_not_require_legal_rep_nor_company() -> None:
    lead = make_lead(**{**COMPLETE_NATURAL, "service": None, "start_term": None})
    assert missing_handoff_fields(lead) == ("servicio contratado", "plazo o fecha de inicio")


def test_vcrm111_natural_person_uses_name_as_name_or_company() -> None:
    lead = make_lead(**{**COMPLETE_NATURAL, "name": None, "company": "Otra SAS"})
    assert missing_handoff_fields(lead) == ("nombre o razón social",)


def test_vcrm111_company_requires_company_and_legal_rep() -> None:
    lead = make_lead(**{**COMPLETE_COMPANY, "company": None, "legal_rep": None})
    assert missing_handoff_fields(lead) == ("nombre o razón social", "representante legal")


def test_vcrm111_company_complete_has_no_missing() -> None:
    assert missing_handoff_fields(make_lead(**COMPLETE_COMPANY)) == ()


def test_vcrm111_document_requires_type_and_number() -> None:
    lead = make_lead(**{**COMPLETE_NATURAL, "doc_number": None})
    assert missing_handoff_fields(lead) == ("documento de identificación",)


def test_vcrm111_contact_requires_phone_and_email() -> None:
    lead = make_lead(**{**COMPLETE_NATURAL, "phone_e164": None, "email": None})
    assert missing_handoff_fields(lead) == ("teléfono de contacto", "correo de contacto")


def test_vcrm111_unregistered_type_lists_type_and_legal_rep_annotated() -> None:
    assert missing_handoff_fields(make_lead()) == (
        "tipo de cliente",
        "documento de identificación",
        REP,
        "servicio contratado",
        "valor acordado",
        "plazo o fecha de inicio",
    )


# --- Validación de valores (VCRM-112) ----------------------------------------


@pytest.mark.parametrize(
    "field", ["tipo", "documento", "representante", "servicio", "valor", "plazo"]
)
@pytest.mark.parametrize("value", ["", "   "])
def test_vcrm112_empty_value_is_rejected(field: str, value: str) -> None:
    result = validate_handoff_value(field, value)
    assert isinstance(result, HandoffValueError)
    assert result.code == "empty"
    assert result.field == field


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("persona natural", "persona natural"),
        ("EMPRESA", "empresa"),
        (" Persona Natural ", "persona natural"),
    ],
)
def test_vcrm112_client_type_admitted(raw: str, expected: str) -> None:
    assert validate_handoff_value("tipo", raw) == {"client_type": expected}


def test_vcrm112_client_type_not_admitted_lists_admitted_values() -> None:
    result = validate_handoff_value("tipo", "fundación")
    assert result == HandoffValueError(code="invalid", field="tipo", allowed=CLIENT_TYPES)
    assert CLIENT_TYPES == ("persona natural", "empresa")


def test_vcrm112_document_nit_splits_type_and_number() -> None:
    result = validate_handoff_value("documento", "NIT 900123456-7")
    assert result == {"doc_type": "NIT", "doc_number": "900123456-7"}


@pytest.mark.parametrize(
    ("raw", "doc_type", "number"),
    [
        ("cedula de ciudadania 1020304050", "cédula de ciudadanía", "1020304050"),
        ("Cédula de Extranjería E-55", "cédula de extranjería", "E-55"),
        ("pasaporte AB123456", "pasaporte", "AB123456"),
        ("nit 900 123 456", "NIT", "900 123 456"),
    ],
)
def test_vcrm112_document_admitted_types(raw: str, doc_type: str, number: str) -> None:
    assert validate_handoff_value("documento", raw) == {"doc_type": doc_type, "doc_number": number}


@pytest.mark.parametrize("raw", ["RUT 900123456", "cédula 1020304050", "NIT", "NIT900123456"])
def test_vcrm112_document_not_admitted_lists_admitted_types(raw: str) -> None:
    result = validate_handoff_value("documento", raw)
    assert result == HandoffValueError(code="invalid", field="documento", allowed=DOC_TYPES)
    assert DOC_TYPES == ("cédula de ciudadanía", "NIT", "cédula de extranjería", "pasaporte")


@pytest.mark.parametrize(
    ("field", "column"),
    [
        ("representante", "legal_rep"),
        ("servicio", "service"),
        ("valor", "agreed_value"),
        ("plazo", "start_term"),
    ],
)
def test_vcrm112_free_text_fields_map_to_columns(field: str, column: str) -> None:
    assert validate_handoff_value(field, "  algo  ") == {column: "algo"}


def test_vcrm112_unknown_field_raises() -> None:
    with pytest.raises(ValueError):
        validate_handoff_value("correo", "a@b.co")


def test_vcrm112_error_text_names_field_and_admitted_values() -> None:
    text = handoff_error_text(HandoffValueError(code="invalid", field="tipo", allowed=CLIENT_TYPES))
    assert "tipo" in text and "persona natural" in text and "empresa" in text
    text = handoff_error_text(
        HandoffValueError(code="invalid", field="documento", allowed=DOC_TYPES)
    )
    assert all(t in text for t in DOC_TYPES)
    text = handoff_error_text(HandoffValueError(code="empty", field="valor"))
    assert "valor" in text and "vacío" in text


# --- Notificaciones de aceptación (VCRM-048, 104) ----------------------------

ACCEPTED_AT = "04/10/2026 10:30"


def test_vcrm048_cto_notification_content() -> None:
    lead = make_lead(**{**COMPLETE_COMPANY, "service": None}, auth_status="autorizada")
    text = acceptance_for_cto(
        lead, commercial="Carlos (123)", accepted_at=ACCEPTED_AT, notes=["Llamar el lunes"]
    )
    for expected in (
        "L-0042",
        "Carlos (123)",
        ACCEPTED_AT,
        "Llamar el lunes",
        "autorizada",
        "Empresa SAS",
        "NIT 900123456-7",
        "Luis Gómez",
        "+573001234567",
        "ana@empresa.co",
        "12.000.000 COP",
        "2026-11-01",
        "Faltantes: servicio contratado",
    ):
        assert expected in text


def test_vcrm048_cto_notification_without_notes_or_missing() -> None:
    text = acceptance_for_cto(
        make_lead(**COMPLETE_NATURAL), commercial="Carlos", accepted_at=ACCEPTED_AT, notes=[]
    )
    assert "Notas: ninguna" in text
    assert "Faltantes: ninguno" in text
    assert "sin autorización" in text


def test_vcrm048_lawyer_email_content() -> None:
    lead = make_lead(**{**COMPLETE_COMPANY, "legal_rep": None})
    view = lawyer_view(lead, commercial="Carlos", accepted_at=ACCEPTED_AT)
    email = acceptance_email_for_lawyer(view)
    assert "L-0042" in email.subject
    for expected in (
        "L-0042",
        "Carlos",
        ACCEPTED_AT,
        "sin autorización",
        "empresa",
        "Empresa SAS",
        "NIT 900123456-7",
        "+573001234567",
        "ana@empresa.co",
        "Plan anual",
        "12.000.000 COP",
        "2026-11-01",
        "Faltantes: representante legal",
        "preparar el contrato y la autorización de tratamiento de datos",
    ):
        assert expected in email.body


def test_vcrm048_lawyer_email_lists_every_handoff_field() -> None:
    view = lawyer_view(make_lead(), commercial="Carlos", accepted_at=ACCEPTED_AT)
    labels = [label for label, _ in view.handoff]
    assert labels == [
        "tipo de cliente",
        "nombre o razón social",
        "documento de identificación",
        "representante legal",
        "teléfono de contacto",
        "correo de contacto",
        "servicio contratado",
        "valor acordado",
        "plazo o fecha de inicio",
    ]
    body = acceptance_email_for_lawyer(view).body
    assert all(label in body for label in labels)
    assert "(sin valor)" in body


def test_vcrm104_lawyer_telegram_alert_content() -> None:
    lead = make_lead(**COMPLETE_COMPANY)
    text = acceptance_alert_for_lawyer(
        lawyer_view(lead, commercial="Carlos", accepted_at=ACCEPTED_AT)
    )
    for expected in ("L-0042", "Empresa SAS", "Carlos", ACCEPTED_AT, "correo"):
        assert expected in text
    assert "900123456-7" not in text


def test_vcrm104_alert_uses_name_for_natural_person() -> None:
    text = acceptance_alert_for_lawyer(
        lawyer_view(make_lead(**COMPLETE_NATURAL), commercial="C", accepted_at=ACCEPTED_AT)
    )
    assert "Ana Pérez" in text


# --- Contenido limitado al abogado (VCRM-156) ---------------------------------

SENTINEL = "ZZ-CENTINELA-ZZ"


def test_vcrm156_lawyer_view_exposes_only_handoff_and_metadata() -> None:
    names = {f.name for f in dataclasses.fields(LawyerView)}
    assert names == {
        "short_id",
        "name_or_company",
        "commercial",
        "accepted_at",
        "auth_status",
        "handoff",
        "missing",
    }


def test_vcrm156_property_no_lawyer_text_contains_notes_attachments_or_history() -> None:
    lead = make_lead(
        **COMPLETE_COMPANY,
        reject_text=SENTINEL,
        reject_reason=SENTINEL,
        legal_hold_basis=SENTINEL,
        suppression_cause=SENTINEL,
    )
    notes = [f"nota {SENTINEL}"]
    attachments = [f"adjunto-{SENTINEL}.pdf"]
    history = [f"contactado → aceptado ({SENTINEL})"]
    view = lawyer_view(lead, commercial="Carlos", accepted_at=ACCEPTED_AT)
    email = acceptance_email_for_lawyer(view)
    lawyer_texts = [acceptance_alert_for_lawyer(view), email.subject, email.body]
    for text in lawyer_texts:
        assert SENTINEL not in text
    for leaked in (*notes, *attachments, *history):
        assert all(leaked not in text for text in lawyer_texts)
    # Control: el texto al CTO sí lleva las notas.
    cto = acceptance_for_cto(lead, commercial="Carlos", accepted_at=ACCEPTED_AT, notes=notes)
    assert SENTINEL in cto


# --- Paginación (VCRM-090) ----------------------------------------------------


def _leads(n: int) -> list[Lead]:
    return [make_lead(id=i, name=f"Lead {i}") for i in range(1, n + 1)]


def test_vcrm090_page_size_is_ten() -> None:
    assert PAGE_SIZE == 10


def test_vcrm090_first_page_of_25() -> None:
    page = render_list_page(_leads(25), 1)
    assert "página 1 de 3" in page.text
    assert page.text.count("\nL-") + page.text.startswith("L-") == 10
    assert "L-0001" in page.text and "L-0010" in page.text and "L-0011" not in page.text
    labels = [label for label, _ in page.buttons]
    assert labels == ["Siguiente"]
    action = parse_callback(page.buttons[0][1])
    assert action is not None and action.action == "lista" and action.args == ("2",)


def test_vcrm090_middle_and_last_page() -> None:
    middle = render_list_page(_leads(25), 2)
    assert "página 2 de 3" in middle.text
    assert [label for label, _ in middle.buttons] == ["Anterior", "Siguiente"]
    last = render_list_page(_leads(25), 3)
    assert "página 3 de 3" in last.text
    assert "L-0021" in last.text and "L-0025" in last.text
    assert [label for label, _ in last.buttons] == ["Anterior"]


def test_vcrm090_out_of_range_page_is_clamped() -> None:
    assert "página 3 de 3" in render_list_page(_leads(25), 9).text
    assert "página 1 de 3" in render_list_page(_leads(25), 0).text


def test_vcrm090_ten_or_fewer_leads_single_page_without_buttons() -> None:
    page = render_list_page(_leads(10), 1)
    assert page.buttons == ()
    assert "página 1 de 1" in page.text


def test_vcrm090_empty_list() -> None:
    page = render_list_page([], 1)
    assert page.buttons == ()
    assert "No hay leads" in page.text


def test_short_id_format() -> None:
    assert short_id(42) == "L-0042"
    assert short_id(12345) == "L-12345"


# --- Troceo a 4096 (Telegram) -------------------------------------------------


def test_split_message_short_text_is_single_chunk() -> None:
    assert split_message("hola") == ["hola"]
    assert TELEGRAM_LIMIT == 4096


def test_split_message_cuts_on_newlines_within_limit() -> None:
    lines = [f"línea {i:04d} " + "x" * 80 for i in range(200)]
    text = "\n".join(lines)
    chunks = split_message(text)
    assert len(chunks) > 1
    assert all(len(c) <= 4096 for c in chunks)
    assert "\n".join(chunks) == text


def test_split_message_hard_cuts_long_line() -> None:
    text = "a" * 9000 + "\nfin"
    chunks = split_message(text)
    assert all(len(c) <= 4096 for c in chunks)
    assert "".join(chunks).replace("\n", "") == "a" * 9000 + "fin"


def test_split_message_custom_limit() -> None:
    chunks = split_message("abc\ndef\nghi", limit=7)
    assert chunks == ["abc\ndef", "ghi"]


def test_split_message_rejects_non_positive_limit() -> None:
    with pytest.raises(ValueError):
        split_message("x", limit=0)
