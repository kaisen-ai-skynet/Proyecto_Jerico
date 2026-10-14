"""Pruebas de T05: Claves, ID de evento, caché y un solo vuelo (VJT-034, 036, 041)."""

import threading
import time

from jerico.decision.cache import DecisionCache, SingleFlight, decision_key, new_event_id


def test_decision_key_deterministic():
    """Misma combinación de (kind, tarea, state, policy_version) produce la misma clave."""
    state1 = {"a": "1", "b": "2"}
    state2 = {"b": "2", "a": "1"}  # Orden distinto pero mismo contenido

    k1 = decision_key("modelo_asistente", "borrador", state1, "1.0.0")
    k2 = decision_key("modelo_asistente", "borrador", state2, "1.0.0")
    assert k1 == k2

    # Diferente versión de política genera diferente clave
    k3 = decision_key("modelo_asistente", "borrador", state1, "1.0.1")
    assert k1 != k3


def test_new_event_id_unique_and_no_collision():
    """Identificadores de evento son únicos incluso con el mismo instante de reloj."""
    fake_time = 1700000000.0
    ids = [new_event_id(clock=lambda: fake_time, seq=i) for i in range(100)]
    assert len(set(ids)) == 100


def test_cache_hit_and_expiration():
    """La caché devuelve acierto dentro del TTL y expira tras superarlo (VJT-034)."""
    current_time = 1000.0
    cache = DecisionCache(ttl_seconds=60.0, clock=lambda: current_time)

    cache.put("k1", "gpt-6-luna")
    assert cache.get("k1") == "gpt-6-luna"

    # Avanzar tiempo dentro de vigencia
    current_time = 1050.0
    assert cache.get("k1") == "gpt-6-luna"

    # Expirar tiempo
    current_time = 1061.0
    assert cache.get("k1") is None


def test_single_flight_coalesces_concurrent_calls():
    """20 llamadas concurrentes con la misma clave ejecutan la función una sola vez (VJT-036)."""
    sf = SingleFlight()
    counter = 0
    lock = threading.Lock()

    def heavy_call():
        nonlocal counter
        with lock:
            counter += 1
        time.sleep(0.05)
        return "resultado_unico"

    results = []

    def worker():
        res = sf.run("misma_clave", heavy_call)
        results.append(res)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 20
    assert all(r == "resultado_unico" for r in results)
    assert counter == 1  # Solo una ejecución real
