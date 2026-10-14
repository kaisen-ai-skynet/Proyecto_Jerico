"""Pruebas de T06: Cortacircuitos (VJT-032)."""

from jerico.decision.breaker import CircuitBreaker


def test_breaker_opens_after_n_failures():
    """El cortacircuitos se abre tras N fallos consecutivos (VJT-032)."""
    current_time = 100.0
    breaker = CircuitBreaker(threshold=3, cooldown=300.0, clock=lambda: current_time)

    assert breaker.is_open() is False

    breaker.record_failure()
    assert breaker.is_open() is False

    breaker.record_failure()
    assert breaker.is_open() is False

    # Tercer fallo abre el circuito
    breaker.record_failure()
    assert breaker.is_open() is True


def test_breaker_resets_on_success():
    """Un éxito resetea la cuenta de fallos consecutivos."""
    breaker = CircuitBreaker(threshold=3, cooldown=300.0)

    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()

    assert breaker.failure_count == 0
    assert breaker.is_open() is False


def test_breaker_closes_after_cooldown():
    """Tras el periodo de pausa (cooldown), el cortacircuitos se cierra."""
    current_time = 100.0
    breaker = CircuitBreaker(threshold=3, cooldown=300.0, clock=lambda: current_time)

    for _ in range(3):
        breaker.record_failure()
    assert breaker.is_open() is True

    # Avanzar tiempo durante el cooldown
    current_time = 250.0
    assert breaker.is_open() is True

    # Avanzar tiempo tras terminar el cooldown
    current_time = 401.0
    assert breaker.is_open() is False
