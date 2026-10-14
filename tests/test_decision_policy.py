"""Pruebas de T01: Cargador y validador de la política (VJT-006, VJT-010)."""

import json
from pathlib import Path

import pytest

from jerico.decision.policy import Policy, PolicyKind, PolicyValidationError, load_policy


def test_load_default_policy():
    """La política base v1 carga correctamente y su versión es estable."""
    policy = load_policy()
    assert isinstance(policy, Policy)
    assert policy.version == "1.0.0"

    # Debe contener los tipos principales
    assert "modelo_asistente" in policy.tipos
    assert "seguimiento_lead" in policy.tipos
    assert "nivel_turno" in policy.tipos
    assert "ruta_consulta_financiera" in policy.tipos


def test_policy_rejects_invalid_class(tmp_path: Path):
    """Rechaza una política con clase inválida."""
    bad_data = {
        "version": "1.0.0",
        "tipos": {
            "invalido": {
                "clase": "Z",  # No es A, B, C ni asesor
                "base": "op1",
                "opciones": ["op1", "op2"],
                "modo_defecto": "apagado",
                "esquema_estado": {"campo": ["val1"]},
            }
        },
    }
    path = tmp_path / "bad_policy.json"
    path.write_text(json.dumps(bad_data), encoding="utf-8")

    with pytest.raises(PolicyValidationError, match="Clase inválida"):
        load_policy(path)


def test_policy_rejects_base_not_in_options(tmp_path: Path):
    """Rechaza una política donde la opción base no está en las opciones permitidas."""
    bad_data = {
        "version": "1.0.0",
        "tipos": {
            "invalido": {
                "clase": "C",
                "base": "op_inexistente",
                "opciones": ["op1", "op2"],
                "modo_defecto": "apagado",
                "esquema_estado": {"campo": ["val1"]},
            }
        },
    }
    path = tmp_path / "bad_policy.json"
    path.write_text(json.dumps(bad_data), encoding="utf-8")

    with pytest.raises(PolicyValidationError, match="Base.*fuera de las opciones"):
        load_policy(path)


def test_policy_rejects_class_b_without_order(tmp_path: Path):
    """Rechaza clase B sin orden de exigencia."""
    bad_data = {
        "version": "1.0.0",
        "tipos": {
            "invalido": {
                "clase": "B",
                "base": "op1",
                "opciones": ["op1", "op2"],
                "modo_defecto": "apagado",
                "esquema_estado": {"campo": ["val1"]},
                # Falta orden_exigencia
            }
        },
    }
    path = tmp_path / "bad_policy.json"
    path.write_text(json.dumps(bad_data), encoding="utf-8")

    with pytest.raises(PolicyValidationError, match="Clase B exige orden_exigencia"):
        load_policy(path)


def test_policy_rejects_default_mode_not_apagado(tmp_path: Path):
    """Rechaza un modo por defecto distinto de 'apagado' (VJT-010)."""
    bad_data = {
        "version": "1.0.0",
        "tipos": {
            "invalido": {
                "clase": "C",
                "base": "op1",
                "opciones": ["op1", "op2"],
                "modo_defecto": "sombra",  # Prohibido como defecto
                "esquema_estado": {"campo": ["val1"]},
            }
        },
    }
    path = tmp_path / "bad_policy.json"
    path.write_text(json.dumps(bad_data), encoding="utf-8")

    with pytest.raises(PolicyValidationError, match="Modo por defecto debe ser 'apagado'"):
        load_policy(path)


def test_policy_rejects_missing_state_schema(tmp_path: Path):
    """Rechaza un tipo sin esquema de estado de lista cerrada."""
    bad_data = {
        "version": "1.0.0",
        "tipos": {
            "invalido": {
                "clase": "C",
                "base": "op1",
                "opciones": ["op1", "op2"],
                "modo_defecto": "apagado",
                "esquema_estado": {},  # Esquema vacío no permitido
            }
        },
    }
    path = tmp_path / "bad_policy.json"
    path.write_text(json.dumps(bad_data), encoding="utf-8")

    with pytest.raises(PolicyValidationError, match="Esquema de estado.*lista cerrada"):
        load_policy(path)


def test_policy_resolves_par():
    """Prueba la resolución de (tipo, tarea) a PolicyKind."""
    policy = load_policy()
    spec = policy.par("modelo_asistente", "resumen_lead")
    assert isinstance(spec, PolicyKind)
    assert spec.clase == "C"
    assert spec.base == "gpt-6-luna"

    spec_borrador = policy.par("modelo_asistente", "borrador")
    assert spec_borrador.clase == "B"
    assert spec_borrador.base == "gpt-6-luna"
    assert spec_borrador.orden_exigencia is not None
