"""Tests del parser, normalización y huella (spec §4.3; VCRM-004, 005, 081, 082, 095)."""

import pytest

from jerico.crm.fingerprint import fingerprint, matches
from jerico.crm.parsing import (
    EDITABLE,
    EXAMPLE_EDIT,
    EXAMPLE_REGISTER,
    MAX_CALLBACK_BYTES,
    CallbackData,
    EditCommand,
    ParseError,
    RegisterCommand,
    build_callback,
    normalize_email,
    normalize_phone,
    parse_callback,
    parse_edit,
    parse_register,
    parse_short_id,
)

# --- Registro (§4.3) ---------------------------------------------------------


def test_vcrm003_register_full_example() -> None:
    result = parse_register(
        "/nuevo Ana Pérez; 300 123 4567; ana@empresa.co; Empresa SAS; Interesada en el plan anual"
    )
    assert result == RegisterCommand(
        name="Ana Pérez",
        phone="+573001234567",
        email="ana@empresa.co",
        company="Empresa SAS",
        note="Interesada en el plan anual",
    )


def test_vcrm003_register_email_only_example() -> None:
    result = parse_register("/nuevo Ana Pérez; ; ana@empresa.co")
    assert result == RegisterCommand(
        name="Ana Pérez", phone=None, email="ana@empresa.co", company=None, note=None
    )


def test_vcrm003_register_note_keeps_semicolons() -> None:
    result = parse_register("/nuevo Ana; 3001234567; ; ; uno; dos ;tres")
    assert isinstance(result, RegisterCommand)
    assert result.note == "uno; dos ;tres"
    assert result.company is None
    assert result.email is None


def test_vcrm003_register_phone_only_without_trailing_fields() -> None:
    result = parse_register("/nuevo  Beto Ruiz ;  3101234567  ")
    assert result == RegisterCommand(
        name="Beto Ruiz", phone="+573101234567", email=None, company=None, note=None
    )


def test_vcrm003_register_bot_suffix_accepted() -> None:
    result = parse_register("/nuevo@JericoCrmBot Ana; 3001234567")
    assert isinstance(result, RegisterCommand)
    assert result.name == "Ana"


def test_vcrm004_register_missing_name() -> None:
    result = parse_register("/nuevo ; 3001234567; ana@empresa.co")
    assert result == ParseError(code="missing", field="nombre", example=EXAMPLE_REGISTER)


def test_vcrm004_register_empty_body_reports_name() -> None:
    result = parse_register("/nuevo")
    assert isinstance(result, ParseError)
    assert (result.code, result.field, result.example) == ("missing", "nombre", EXAMPLE_REGISTER)


@pytest.mark.parametrize(
    "text", ["/nuevo Ana", "/nuevo Ana; ;", "/nuevo Ana;  ;  ; Empresa SAS; nota"]
)
def test_vcrm004_register_missing_all_contact(text: str) -> None:
    result = parse_register(text)
    assert result == ParseError(code="missing", field="contacto", example=EXAMPLE_REGISTER)


def test_vcrm004_example_shows_format() -> None:
    assert EXAMPLE_REGISTER.startswith("/nuevo ")
    assert EXAMPLE_REGISTER.count(";") == 4


def test_vcrm005_register_invalid_phone() -> None:
    result = parse_register("/nuevo Ana; 12345; ana@empresa.co")
    assert isinstance(result, ParseError)
    assert (result.code, result.field) == ("invalid", "telefono")


@pytest.mark.parametrize(
    "email", ["ana.empresa.co", "ana@empresa", "ana@", "@empresa.co", "a na@empresa.co"]
)
def test_vcrm005_register_invalid_email(email: str) -> None:
    result = parse_register(f"/nuevo Ana; 3001234567; {email}")
    assert isinstance(result, ParseError)
    assert (result.code, result.field) == ("invalid", "correo")


def test_register_not_a_register_command() -> None:
    result = parse_register("/nuevoAna; 3001234567")
    assert isinstance(result, ParseError)
    assert result.code == "bad_format"


# --- Normalización (VCRM-005) -----------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("300 123 4567", "+573001234567"),
        ("300-123-4567", "+573001234567"),
        ("(601) 234.5678", "+576012345678"),
        ("+57 300 123 4567", "+573001234567"),
        ("+1 (415) 555-0100", "+14155550100"),
        ("0034 612 345 678", "+34612345678"),
        ("+12345678", "+12345678"),
        ("+123456789012345", "+123456789012345"),
    ],
)
def test_vcrm005_normalize_phone_valid(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "12345",
        "300123456",
        "30012345678",
        "+0573001234567",
        "+1234567",
        "+1234567890123456",
        "300abc4567",
        "+57+300",
    ],
)
def test_vcrm005_normalize_phone_invalid(raw: str) -> None:
    assert normalize_phone(raw) is None


def test_vcrm005_normalize_phone_custom_default_country() -> None:
    assert normalize_phone("2025550100", default_cc="1") == "+12025550100"


def test_vcrm005_normalize_email() -> None:
    assert normalize_email("  Ana.Perez@Empresa.CO ") == "ana.perez@empresa.co"
    assert normalize_email("ana;x@empresa.co") is None
    assert normalize_email("") is None


# --- Edición (VCRM-081, 082) -------------------------------------------------


def test_vcrm081_edit_example_valid() -> None:
    assert parse_edit("/editar L-0042; documento; NIT 900123456-7") == EditCommand(
        short_id=42, field="documento", value="NIT 900123456-7"
    )


def test_vcrm081_edit_alias_with_accent_and_case() -> None:
    assert parse_edit("/editar l-42; Teléfono; 300 123 4567") == EditCommand(
        short_id=42, field="telefono", value="+573001234567"
    )


def test_vcrm081_edit_email_normalized_and_value_keeps_semicolons() -> None:
    assert parse_edit("/editar L-7; correo; Ana.Perez@Empresa.co") == EditCommand(
        short_id=7, field="correo", value="ana.perez@empresa.co"
    )
    result = parse_edit("/editar L-7; servicio; asesoría; fase 1")
    assert isinstance(result, EditCommand)
    assert result.value == "asesoría; fase 1"


def test_vcrm081_edit_field_not_editable_lists_editables() -> None:
    result = parse_edit("/editar L-0042; estado; ganado")
    assert result == ParseError(
        code="field_not_editable", field="estado", example=EXAMPLE_EDIT, editable=EDITABLE
    )


def test_vcrm081_edit_invalid_lead_id_lists_editables() -> None:
    result = parse_edit("/editar X-12; correo; ana@empresa.co")
    assert isinstance(result, ParseError)
    assert result.code == "invalid_lead_id"
    assert result.editable == EDITABLE


def test_vcrm081_edit_missing_parts() -> None:
    result = parse_edit("/editar L-1; correo")
    assert isinstance(result, ParseError)
    assert (result.code, result.field, result.example) == ("missing", "valor", EXAMPLE_EDIT)
    result = parse_edit("/editar L-1; correo;   ")
    assert isinstance(result, ParseError)
    assert (result.code, result.field) == ("missing", "valor")


def test_vcrm081_editable_fields_match_spec() -> None:
    assert set(EDITABLE) == {
        "nombre",
        "telefono",
        "correo",
        "empresa",
        "tipo",
        "documento",
        "representante",
        "servicio",
        "valor",
        "plazo",
    }


def test_edit_not_an_edit_command() -> None:
    result = parse_edit("/nuevo Ana; 3001234567")
    assert isinstance(result, ParseError)
    assert result.code == "bad_format"


@pytest.mark.parametrize(
    ("text", "field"),
    [("/editar L-1; telefono; 12345", "telefono"), ("/editar L-1; correo; ana@empresa", "correo")],
)
def test_vcrm082_edit_invalid_contact(text: str, field: str) -> None:
    result = parse_edit(text)
    assert isinstance(result, ParseError)
    assert (result.code, result.field) == ("invalid", field)


# --- Identificador corto y callbacks ------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"), [("L-0042", 42), ("l-42", 42), (" L-1 ", 1), ("L-123456", 123456)]
)
def test_parse_short_id_valid(raw: str, expected: int) -> None:
    assert parse_short_id(raw) == expected


@pytest.mark.parametrize("raw", ["", "L-", "L-0", "L-0000", "42", "S-42", "L-4a", "L--4", "L-42x"])
def test_parse_short_id_invalid(raw: str) -> None:
    assert parse_short_id(raw) is None


def test_callback_roundtrip_and_limit() -> None:
    data = build_callback("state", "42", "ganado")
    assert data == "v1:state:42:ganado"
    assert len(data.encode()) <= MAX_CALLBACK_BYTES == 64
    assert parse_callback(data) == CallbackData(action="state", args=("42", "ganado"))


def test_callback_too_long_rejected() -> None:
    with pytest.raises(ValueError):
        build_callback("reassign", "x" * 60)
    assert parse_callback("v1:reassign:" + "x" * 60) is None


@pytest.mark.parametrize("bad", [("st:ate", "1"), ("state", "a:b"), ("", "1")])
def test_callback_build_rejects_separator_or_empty(bad: tuple[str, str]) -> None:
    with pytest.raises(ValueError):
        build_callback(*bad)


@pytest.mark.parametrize("data", ["", "v2:state:1", "v1:state", "v1::1", "v1:state:", "state:1"])
def test_callback_parse_rejects_malformed(data: str) -> None:
    assert parse_callback(data) is None


def test_callback_multibyte_counts_bytes() -> None:
    with pytest.raises(ValueError):
        build_callback("a", "ñ" * 30)


# --- Huella (VCRM-095) --------------------------------------------------------


def test_vcrm095_fingerprint_stable_hex_hmac() -> None:
    fp1 = fingerprint("clave-actual", "+573001234567")
    assert fp1 == fingerprint("clave-actual", "+573001234567")
    assert len(fp1) == 64
    int(fp1, 16)
    assert fingerprint(b"clave-actual", "+573001234567") == fp1


def test_vcrm095_fingerprint_differs_with_other_key_and_value() -> None:
    fp1 = fingerprint("clave-actual", "+573001234567")
    assert fingerprint("otra-clave", "+573001234567") != fp1
    assert fingerprint("clave-actual", "+573001234568") != fp1


def test_vcrm095_fingerprint_does_not_contain_contact() -> None:
    for contact in ("+573001234567", "ana@empresa.co"):
        fp = fingerprint("k", contact)
        assert contact not in fp
        assert contact.lstrip("+") not in fp
        assert "ana" not in fp


def test_vcrm095_matches_with_current_and_previous_keys() -> None:
    stored = {fingerprint("clave-vieja", "ana@empresa.co")}
    assert matches(stored, "ana@empresa.co", ["clave-nueva", "clave-vieja"])
    assert not matches(stored, "ana@empresa.co", ["clave-nueva"])
    assert not matches(stored, "otra@empresa.co", ["clave-nueva", "clave-vieja"])
    assert not matches(stored, "ana@empresa.co", [])


def test_vcrm095_fingerprint_rejects_empty_key() -> None:
    with pytest.raises(ValueError):
        fingerprint("", "ana@empresa.co")
