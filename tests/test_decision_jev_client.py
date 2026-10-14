"""Pruebas de T12: Cliente de Jev para el Nivel 2 (VJT-031 a VJT-053).

Pruebas herméticas con transporte falso inyectado, sin dependencias de red externas.
"""

import threading
import time
from typing import Any

import pytest

from jerico.decision.jev_client import JevClient
from jerico.decision.policy import PolicyKind


def _sample_policy_kind() -> PolicyKind:
    return PolicyKind(
        kind="nivel_turno",
        clase="B",
        base="L1",
        opciones=["L1", "L2", "L3"],
        orden_exigencia=["L1", "L2", "L3"],
        modo_defecto="sugerencia",
        clase_datos="sin_datos_personales",
    )


def test_client_parses_choice_response():
    """JevClient interpreta respuestas tipo 'choice' con opción y confianza (VJT-031)."""
    mock_body = {
        "model": "jev-1.13.0",
        "usage": {"input_tokens": 580, "output_tokens": 15},
        "answers": {
            "nivel_turno": {
                "choice": "L2",
                "confidence": 0.88,
                "probabilities": {"L1": 0.05, "L2": 0.88, "L3": 0.07},
            }
        },
    }

    def fake_transport(payload: dict[str, Any], headers: dict[str, str], timeout_s: float):
        assert payload["model"] == "jev-1.13.0"
        assert "Authorization" in headers
        assert "nivel_turno" in payload["questions"]
        return 200, mock_body

    client = JevClient(transport=fake_transport, api_key="secret-key-xyz", model="jev-1.13.0")
    spec = _sample_policy_kind()
    state = {"tipo_mensaje": "complejo", "longitud_rango": "larga"}

    ans = client.consultar(spec, state)

    assert ans["option"] == "L2"
    assert ans["confidence"] == 0.88
    assert ans["model_version"] == "jev-1.13.0"
    assert ans["tokens_in"] == 580
    assert ans["tokens_out"] == 15
    assert ans.get("empate") is False
    assert "latencia_ms" in ans


def test_client_parses_score_numeric_response():
    """JevClient interpreta respuestas numéricas tipo 'score' y las mapea al rango de opciones."""
    # Opciones de nivel_turno: ["L1", "L2", "L3"] -> índices 0, 1, 2
    mock_body = {
        "model": "jev-1.13.0",
        "answers": {
            "nivel_turno": {
                "score": 1.0,
                "confidence": 0.75,
            }
        },
    }

    def fake_transport(payload, headers, timeout):
        return 200, mock_body

    client = JevClient(transport=fake_transport, api_key="test-key")
    spec = _sample_policy_kind()
    ans = client.consultar(spec, {"tipo_mensaje": "complejo", "longitud_rango": "larga"})

    assert ans["option"] == "L2"
    assert ans["confidence"] == 0.75


def test_client_parses_score_float_response():
    """JevClient redondea score float al índice de opción más cercano."""
    mock_body = {
        "model": "jev-1.13.0",
        "answers": {
            "nivel_turno": {
                "score": 1.8,  # Redondea a 2 -> L3
                "confidence": 0.90,
            }
        },
    }

    def fake_transport(payload, headers, timeout):
        return 200, mock_body

    client = JevClient(transport=fake_transport, api_key="test-key")
    spec = _sample_policy_kind()
    ans = client.consultar(spec, {"tipo_mensaje": "complejo", "longitud_rango": "larga"})

    assert ans["option"] == "L3"


def test_client_detects_tie_empate():
    """Si dos opciones tienen igual probabilidad máxima, marca empate=True (VJT-037)."""
    mock_body = {
        "model": "jev-1.13.0",
        "answers": {
            "nivel_turno": {
                "choice": "L1",
                "probabilities": {"L1": 0.45, "L2": 0.45, "L3": 0.10},
            }
        },
    }

    def fake_transport(payload, headers, timeout):
        return 200, mock_body

    client = JevClient(transport=fake_transport, api_key="test-key")
    spec = _sample_policy_kind()
    ans = client.consultar(spec, {"tipo_mensaje": "simple", "longitud_rango": "corta"})

    assert ans["empate"] is True


def test_client_retries_429_and_529_once_with_backoff():
    """JevClient reintenta una sola vez ante respuestas 429 o 529 con backoff (VJT-031)."""
    attempts = 0
    sleeps: list[float] = []

    def fake_transport(payload, headers, timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return 429, None  # Rate limit
        return 200, {
            "model": "jev-1.13.0",
            "answers": {"nivel_turno": {"choice": "L2"}},
        }

    client = JevClient(
        transport=fake_transport,
        api_key="test-key",
        backoff_s=0.25,
        sleep=lambda s: sleeps.append(s),
    )
    spec = _sample_policy_kind()
    ans = client.consultar(spec, {"tipo_mensaje": "simple", "longitud_rango": "corta"})

    assert attempts == 2
    assert sleeps == [0.25]
    assert ans["option"] == "L2"


def test_client_fails_if_retry_also_returns_error():
    """Si el reintento de 429/529 falla, lanza RuntimeError (VJT-031)."""
    attempts = 0

    def fake_transport(payload, headers, timeout):
        nonlocal attempts
        attempts += 1
        return 529, None

    client = JevClient(
        transport=fake_transport,
        api_key="test-key",
        backoff_s=0.1,
        sleep=lambda s: None,
    )
    spec = _sample_policy_kind()

    with pytest.raises(RuntimeError) as exc_info:
        client.consultar(spec, {"tipo_mensaje": "simple", "longitud_rango": "corta"})

    assert "529" in str(exc_info.value)
    assert attempts == 2


def test_client_respects_timeout():
    """Si el transporte excede el tiempo límite, lanza TimeoutError (VJT-031)."""

    def fake_transport(payload, headers, timeout):
        raise TimeoutError(f"Tiempo de espera agotado ({timeout}s)")

    client = JevClient(transport=fake_transport, api_key="test-key", timeout_s=3.0)
    spec = _sample_policy_kind()

    with pytest.raises(TimeoutError) as exc_info:
        client.consultar(spec, {"tipo_mensaje": "simple", "longitud_rango": "corta"})

    assert "Tiempo de espera agotado" in str(exc_info.value)


def test_api_key_never_leaked_in_errors_or_repr():
    """La clave TYPESAFE_API_KEY NUNCA aparece en errores ni en representaciones (VJT-051)."""
    secret = "typesafe_super_secret_key_9999"

    def fake_transport_error(payload, headers, timeout):
        raise ValueError(f"Falla con headers de auth: {headers.get('Authorization')}")

    client = JevClient(transport=fake_transport_error, api_key=secret)

    # 1. __repr__ y __str__ nunca contienen la clave
    assert secret not in repr(client)
    assert secret not in str(client)

    # 2. Excepciones lanzadas nunca contienen la clave
    spec = _sample_policy_kind()
    try:
        client.consultar(spec, {"tipo_mensaje": "simple", "longitud_rango": "corta"})
    except Exception as exc:
        assert secret not in str(exc)


def test_single_query_per_decision_no_multi_query():
    """En Nivel 2 realiza una sola consulta HTTP por decisión (VJT-035)."""
    calls = 0

    def fake_transport(payload, headers, timeout):
        nonlocal calls
        calls += 1
        return 200, {
            "model": "jev-1.13.0",
            "answers": {"nivel_turno": {"choice": "L1"}},
        }

    client = JevClient(transport=fake_transport, api_key="test-key")
    spec = _sample_policy_kind()
    client.consultar(spec, {"tipo_mensaje": "simple", "longitud_rango": "corta"})

    assert calls == 1


def test_state_privacy_validation_rejects_personal_data():
    """Rechaza state con correos o números largos antes de transmitir (Ley 1581, VJT-020)."""
    client = JevClient(transport=lambda p, h, t: (200, {}), api_key="test-key")
    spec = _sample_policy_kind()

    bad_state_email = {"tipo_mensaje": "simple", "email": "usuario@kaisen.com"}
    with pytest.raises(ValueError) as exc:
        client.consultar(spec, bad_state_email)
    assert "datos personales" in str(exc.value)

    bad_state_phone = {"tipo_mensaje": "simple", "telefono": "300123456789"}
    with pytest.raises(ValueError) as exc:
        client.consultar(spec, bad_state_phone)
    assert "datos personales" in str(exc.value)


def test_concurrent_query_does_not_delay_other_messages():
    """Una consulta de 2 segundos simulada no retrasa a otro mensaje más de 100 ms (VJT-033)."""

    def slow_transport(payload, headers, timeout):
        time.sleep(2.0)
        return 200, {
            "model": "jev-1.13.0",
            "answers": {"nivel_turno": {"choice": "L2"}},
        }

    def fast_transport(payload, headers, timeout):
        return 200, {
            "model": "jev-1.13.0",
            "answers": {"nivel_turno": {"choice": "L1"}},
        }

    client_slow = JevClient(transport=slow_transport, api_key="key1")
    client_fast = JevClient(transport=fast_transport, api_key="key2")
    spec = _sample_policy_kind()

    state_complex = {"tipo_mensaje": "complejo", "longitud_rango": "larga"}
    slow_thread = threading.Thread(target=lambda: client_slow.consultar(spec, state_complex))
    slow_thread.start()

    # Damos un instante para que el hilo lento comience su espera
    time.sleep(0.05)

    # Mensaje concurrente rápido
    t_msg2_start = time.perf_counter()
    ans_fast = client_fast.consultar(spec, {"tipo_mensaje": "simple", "longitud_rango": "corta"})
    t_msg2_duration = (time.perf_counter() - t_msg2_start) * 1000  # ms

    # Esperamos a que el hilo lento concluya
    slow_thread.join()

    assert ans_fast["option"] == "L1"
    # El procesamiento del segundo mensaje no debe retrasarse más de 100 ms
    assert t_msg2_duration < 100.0, f"Mensaje 2 tardó {t_msg2_duration:.2f} ms (> 100 ms)"
