"""Pruebas de T03: Validación del estado y privacidad (VJT-020, VJT-021, VJT-025)."""

import pytest

from jerico.decision.policy import load_policy
from jerico.decision.state import DataClass, InvalidState, validate_state


@pytest.fixture
def policy():
    return load_policy()


def test_dataclass_enum_values():
    """Valida los tres valores normativos de DataClass (VJT-022)."""
    assert DataClass.SIN_DATOS_PERSONALES.value == "sin_datos_personales"
    assert DataClass.SEUDONIMIZADO_VERIFICADO.value == "seudonimizado_verificado"
    assert DataClass.CON_DATOS_PERSONALES.value == "con_datos_personales"


def test_valid_state_passes(policy):
    """Un estado con campos y valores en lista cerrada es válido."""
    spec = policy.par("seguimiento_lead")
    valid_state = {
        "dias_sin_contacto": "3-7",
        "paso_cadencia": "1",
        "estado_lead": "en_contacto",
        "intentos_fallidos": "0",
    }
    es_valido, motivo = validate_state(spec, valid_state)
    assert es_valido is True
    assert motivo == "ok"


def test_state_rejects_missing_key(policy):
    """Rechaza un estado al que le falta una clave requerida."""
    spec = policy.par("seguimiento_lead")
    incomplete_state = {
        "dias_sin_contacto": "3-7",
        "paso_cadencia": "1",
        # Falta estado_lead e intentos_fallidos
    }
    es_valido, motivo = validate_state(spec, incomplete_state)
    assert es_valido is False
    assert "clave_faltante" in motivo


def test_state_rejects_extra_key(policy):
    """Rechaza un estado con claves no declaradas en la lista cerrada."""
    spec = policy.par("seguimiento_lead")
    extra_state = {
        "dias_sin_contacto": "3-7",
        "paso_cadencia": "1",
        "estado_lead": "en_contacto",
        "intentos_fallidos": "0",
        "campo_extra": "valor_no_permitido",
    }
    es_valido, motivo = validate_state(spec, extra_state)
    assert es_valido is False
    assert "clave_extra" in motivo


def test_state_rejects_value_outside_enum(policy):
    """Rechaza valores fuera del enumerado o rango de cubos."""
    spec = policy.par("seguimiento_lead")
    bad_val_state = {
        "dias_sin_contacto": "42_dias_exactos",  # No está en lista de rangos
        "paso_cadencia": "1",
        "estado_lead": "en_contacto",
        "intentos_fallidos": "0",
    }
    es_valido, motivo = validate_state(spec, bad_val_state)
    assert es_valido is False
    assert "valor_invalido" in motivo


def test_state_rejects_exact_integers_when_bucket_expected(policy):
    """Rechaza enteros exactos cuando se esperan rangos agrupados (VJT-020)."""
    spec = policy.par("seguimiento_lead")
    bad_int_state = {
        "dias_sin_contacto": 15,  # Debe ser "15-30" como string de rango
        "paso_cadencia": "1",
        "estado_lead": "en_contacto",
        "intentos_fallidos": "0",
    }
    es_valido, motivo = validate_state(spec, bad_int_state)
    assert es_valido is False
    assert "tipo_invalido" in motivo or "valor_invalido" in motivo


def test_state_rejects_bool_for_non_bool_field(policy):
    """Rechaza un booleano en un campo que espera valores enumerados."""
    spec = policy.par("seguimiento_lead")
    bad_type_state = {
        "dias_sin_contacto": True,  # bool no es string de rango
        "paso_cadencia": "1",
        "estado_lead": "en_contacto",
        "intentos_fallidos": "0",
    }
    es_valido, motivo = validate_state(spec, bad_type_state)
    assert es_valido is False


def test_strict_mode_raises_invalid_state(policy):
    """En modo estricto, validate_state lanza InvalidState."""
    spec = policy.par("seguimiento_lead")
    with pytest.raises(InvalidState):
        validate_state(spec, {"clave": "invalida"}, strict=True)


def test_privacy_markers_never_pass(policy):
    """Prueba de privacidad: correos, teléfonos, nombres o IDs nunca pasan (VJT-021)."""
    spec = policy.par("seguimiento_lead")

    marcadores = [
        ("email", "juan.perez@empresa.com"),
        ("telefono", "+57 300 123 4567"),
        ("nombre", "Santiago González"),
        ("id_lead", "L-9942"),
        ("nota_libre", "El cliente dijo que le parece costoso"),
    ]

    for clave_pii, valor_pii in marcadores:
        # PII como clave
        es_valido, motivo = validate_state(spec, {clave_pii: "0"})
        assert es_valido is False, f"PII en clave no debe pasar: {clave_pii}"

        # PII como valor inyectado en un campo existente
        estado_con_pii = {
            "dias_sin_contacto": valor_pii,
            "paso_cadencia": "1",
            "estado_lead": "en_contacto",
            "intentos_fallidos": "0",
        }
        es_valido, motivo = validate_state(spec, estado_con_pii)
        assert es_valido is False, f"PII en valor no debe pasar: {valor_pii}"


def test_state_not_dict_rejected(policy):
    """Rechaza un estado que no sea un diccionario."""
    spec = policy.par("seguimiento_lead")
    es_valido, motivo = validate_state(spec, "no_un_diccionario")  # type: ignore[arg-type]
    assert es_valido is False
    assert motivo == "estado_no_es_diccionario"

    with pytest.raises(InvalidState):
        validate_state(spec, "no_un_diccionario", strict=True)  # type: ignore[arg-type]


def test_strict_mode_all_error_types(policy):
    """En modo strict=True cada tipo de fallo lanza InvalidState."""
    spec = policy.par("seguimiento_lead")

    # Clave extra
    with pytest.raises(InvalidState, match="clave_extra"):
        validate_state(spec, {
            "dias_sin_contacto": "0",
            "paso_cadencia": "0",
            "estado_lead": "nuevo",
            "intentos_fallidos": "0",
            "extra": 123,
        }, strict=True)

    # Bool inválido
    with pytest.raises(InvalidState, match="tipo_invalido_bool"):
        validate_state(spec, {
            "dias_sin_contacto": True,
            "paso_cadencia": "0",
            "estado_lead": "nuevo",
            "intentos_fallidos": "0",
        }, strict=True)

    # Entero inválido
    with pytest.raises(InvalidState, match="valor_invalido_entero"):
        validate_state(spec, {
            "dias_sin_contacto": 999,
            "paso_cadencia": "0",
            "estado_lead": "nuevo",
            "intentos_fallidos": "0",
        }, strict=True)

    # Valor string inválido
    with pytest.raises(InvalidState, match="valor_invalido"):
        validate_state(spec, {
            "dias_sin_contacto": "no_existe",
            "paso_cadencia": "0",
            "estado_lead": "nuevo",
            "intentos_fallidos": "0",
        }, strict=True)
