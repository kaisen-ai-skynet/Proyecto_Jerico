"""Pruebas unitarias para advisor_state (spec 007, VJC-007, VJC-011 a 016)."""

import json

import pytest

from jerico.crm.advisor_state import (
    CAPS,
    SCHEMA_VERSION,
    InvalidVector,
    build_vector,
    is_eligible,
    lead_ref,
    validate_vector,
)


def test_lead_ref_properties() -> None:
    key1 = "secret-key-1"
    key2 = "secret-key-2"
    ref1 = lead_ref(12345, key1)
    ref2 = lead_ref(12345, key1)
    ref3 = lead_ref(12345, key2)

    # Estable
    assert ref1 == ref2
    # 16 caracteres hexadecimales
    assert len(ref1) == 16
    assert all(c in "0123456789abcdef" for c in ref1)
    # Cambia con otra clave
    assert ref1 != ref3
    # No contiene el número interno
    assert "12345" not in ref1


def test_is_eligible_rules() -> None:
    # Elegible estándar
    assert is_eligible(
        {"suppressed_at": None, "opted_out": False, "authorization_status": "authorized"}
    )

    # Suprimido -> no elegible
    assert not is_eligible(
        {
            "suppressed_at": "2026-10-14T00:00:00Z",
            "opted_out": False,
            "authorization_status": "authorized",
        }
    )

    # Opted out (baja) -> no elegible
    assert not is_eligible(
        {"suppressed_at": None, "opted_out": True, "authorization_status": "authorized"}
    )

    # Autorización revocada -> no elegible
    assert not is_eligible(
        {"suppressed_at": None, "opted_out": False, "authorization_status": "revoked"}
    )

    # Estados finales sí son elegibles
    assert is_eligible(
        {
            "suppressed_at": None,
            "opted_out": False,
            "authorization_status": "authorized",
            "stage": "won",
        }
    )
    assert is_eligible(
        {
            "suppressed_at": None,
            "opted_out": False,
            "authorization_status": "authorized",
            "stage": "lost",
        }
    )


def test_build_vector_and_validation() -> None:
    raw_lead = {
        "id": 101,
        "stage": "new",
        "created_at_days": 10,
        "days_since_interaction": 2,
        "days_in_stage": 5,
        "ever_accepted": False,
        "retraction": False,
        "commercial_block": False,
        "phone": "+573001234567",
        "email": "lead@example.com",
        "agreed_value": "1000000",
        "service": "Auditoría IA",
        "assigned_commercial": "Juan",
        "client_type": "persona natural",
        "reject_reason": "",
        "authorization_status": "authorized",
        "missing_handoff_fields": 2,
        "events_30d": 3,
        "notes_count": 1,
        "cadence_status": "active",
        "cadence_steps_done": 1,
        "cadence_steps_total": 3,
        "cadence_shipments_done": 1,
        "cadence_has_next_action": True,
        "cadence_days_next_action": 3,
        "pending_proposals": 1,
        "pending_alerts": 0,
        "pending_requests": 0,
    }

    vec = build_vector(raw_lead, key="test-key", capture_day="2026-10-14", weekday=2)
    validate_vector(vec)

    assert vec["schema_version"] == SCHEMA_VERSION
    assert vec["capture_day"] == "2026-10-14"
    assert len(vec["lead_ref"]) == 16
    assert vec["stage"] == "new"
    assert vec["tiene_telefono"] is True
    assert vec["tiene_correo"] is True
    assert vec["client_type"] == "persona_natural"
    assert vec["reject_reason"] == "ninguno"
    assert vec["cadencia_dias_proxima_accion"] == 3


def test_build_vector_mapping_and_caps() -> None:
    raw_lead = {
        "id": 102,
        "stage": "rejected",
        "created_at_days": 500,  # mayor a cap 365
        "days_since_interaction": 400,  # mayor a cap 365
        "days_in_stage": 400,
        "ever_accepted": True,
        "retraction": False,
        "commercial_block": False,
        "phone": "",
        "email": "",
        "agreed_value": "",
        "service": "",
        "assigned_commercial": "",
        "client_type": "desconocido",  # -> ninguno
        "reject_reason": "otro_raro",  # -> otro
        "authorization_status": "unauthorized",
        "missing_handoff_fields": 15,  # cap a 9
        "events_30d": 99,  # cap a 50
        "notes_count": 80,  # cap a 50
        "cadence_status": None,  # -> ninguna
        "cadence_steps_done": 60,  # cap a 50
        "cadence_steps_total": 60,
        "cadence_shipments_done": 60,
        "cadence_has_next_action": False,
        "cadence_days_next_action": -500,  # clamped a -365
        "pending_proposals": 100,
        "pending_alerts": 100,
        "pending_requests": 100,
    }

    vec = build_vector(raw_lead, key="test-key", capture_day="2026-10-14", weekday=2)
    validate_vector(vec)

    assert vec["antiguedad_dias"] == CAPS["antiguedad_dias"]
    assert vec["dias_sin_interaccion"] == CAPS["dias_sin_interaccion"]
    assert vec["client_type"] == "ninguno"
    assert vec["reject_reason"] == "otro"
    assert vec["cadencia_estado"] == "ninguna"
    assert vec["campos_faltantes_handoff"] == 9
    assert vec["actividad_eventos_30d"] == CAPS["eventos_30d"]
    assert vec["cadencia_dias_proxima_accion"] == -365


def test_validate_vector_rejections() -> None:
    raw_lead = {
        "id": 103,
        "stage": "new",
        "created_at_days": 10,
        "days_since_interaction": 2,
        "days_in_stage": 5,
        "ever_accepted": False,
        "retraction": False,
        "commercial_block": False,
        "phone": "300",
        "email": "a@b.com",
        "agreed_value": "",
        "service": "",
        "assigned_commercial": "",
        "client_type": "empresa",
        "reject_reason": "",
        "authorization_status": "authorized",
        "missing_handoff_fields": 0,
        "events_30d": 0,
        "notes_count": 0,
        "cadence_status": "ninguna",
        "cadence_steps_done": 0,
        "cadence_steps_total": 0,
        "cadence_shipments_done": 0,
        "cadence_has_next_action": False,
        "cadence_days_next_action": 0,
        "pending_proposals": 0,
        "pending_alerts": 0,
        "pending_requests": 0,
    }
    vec = build_vector(raw_lead, key="test-key", capture_day="2026-10-14", weekday=2)

    # Clave faltante
    vec_missing = dict(vec)
    del vec_missing["stage"]
    with pytest.raises(InvalidVector, match="faltante"):
        validate_vector(vec_missing)

    # Clave extra
    vec_extra = dict(vec)
    vec_extra["extra_key"] = "forbidden"
    with pytest.raises(InvalidVector, match="extra"):
        validate_vector(vec_extra)

    # Bool en lugar de int (un bool no vale como entero)
    vec_bool_for_int = dict(vec)
    vec_bool_for_int["antiguedad_dias"] = True
    with pytest.raises(InvalidVector, match="tipo"):
        validate_vector(vec_bool_for_int)

    # Entero fuera de tope
    vec_over_cap = dict(vec)
    vec_over_cap["antiguedad_dias"] = 500
    with pytest.raises(InvalidVector, match="tope"):
        validate_vector(vec_over_cap)

    # Cadena fuera de enumerado
    vec_bad_enum = dict(vec)
    vec_bad_enum["stage"] = "inventado"
    with pytest.raises(InvalidVector, match="enumerado"):
        validate_vector(vec_bad_enum)


def test_privacy_proof_no_personal_data() -> None:
    raw_lead = {
        "id": 99999,
        "stage": "contacted",
        "created_at_days": 1,
        "days_since_interaction": 1,
        "days_in_stage": 1,
        "ever_accepted": False,
        "retraction": False,
        "commercial_block": False,
        "phone": "+573119876543_TELEFONO_PRIVADO",
        "email": "correo_secreto_titular@empresa-confidencial.com",
        "agreed_value": "$50.000.000 COP pactados en secreto",
        "service": "Proyecto Secreto Alpha",
        "assigned_commercial": "Santiago Comercial Privado",
        "client_type": "persona natural",
        "reject_reason": "",
        "authorization_status": "authorized",
        "missing_handoff_fields": 1,
        "events_30d": 1,
        "notes_count": 2,
        "cadence_status": "active",
        "cadence_steps_done": 1,
        "cadence_steps_total": 3,
        "cadence_shipments_done": 1,
        "cadence_has_next_action": True,
        "cadence_days_next_action": 1,
        "pending_proposals": 0,
        "pending_alerts": 0,
        "pending_requests": 0,
    }

    vec = build_vector(raw_lead, key="clave-secreta-crm", capture_day="2026-10-14", weekday=2)
    serialized = json.dumps(vec)

    # Marcadores únicos que nunca deben aparecer en el vector serializado
    assert "99999" not in serialized
    assert "TELEFONO_PRIVADO" not in serialized
    assert "correo_secreto_titular" not in serialized
    assert "empresa-confidencial" not in serialized
    assert "50.000.000" not in serialized
    assert "Proyecto Secreto Alpha" not in serialized
    assert "Santiago Comercial Privado" not in serialized
