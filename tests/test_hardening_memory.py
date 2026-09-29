"""Revisión adversarial de MemoryManager: TTL, tope, aislamiento y concurrencia."""

import sys
import threading

import pytest

from jerico import memory as memory_module
from jerico.memory import MemoryManager


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(memory_module.time, "monotonic", lambda: now[0])
    return now


@pytest.fixture
def switch_agresivo():
    # Fuerza cambios de hilo frecuentes para destapar carreras.
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    yield
    sys.setswitchinterval(old)


def test_ttl_expira_sesion(clock):
    mem = MemoryManager(ttl_seconds=10)
    mem.append("a", "user", "hola")
    clock[0] += 11
    assert mem.context("a") == []
    mem.append("b", "user", "x")  # dispara purge
    assert "a" not in mem._sessions


def test_ttl_se_renueva_con_actividad(clock):
    mem = MemoryManager(ttl_seconds=10)
    mem.append("a", "user", "uno")
    clock[0] += 8
    mem.append("a", "user", "dos")
    clock[0] += 8
    assert [m["content"] for m in mem.context("a")] == ["uno", "dos"]


def test_ttl_cero_desactiva_expiracion(clock):
    mem = MemoryManager(ttl_seconds=0)
    mem.append("a", "user", "hola")
    clock[0] += 10**9
    assert mem.context("a") == [{"role": "user", "content": "hola"}]


def test_tope_de_mensajes_conserva_los_ultimos():
    mem = MemoryManager(max_messages=4)
    for i in range(10):
        mem.append("a", "user", str(i))
    assert [m["content"] for m in mem.context("a")] == ["6", "7", "8", "9"]


def test_eviction_respeta_la_sesion_usada_recientemente(clock):
    mem = MemoryManager(max_sessions=2)
    mem.append("a", "user", "1")
    clock[0] += 1
    mem.append("b", "user", "2")
    clock[0] += 1
    mem.append("a", "user", "3")  # "a" pasa a ser la más reciente
    clock[0] += 1
    mem.append("c", "user", "4")
    assert set(mem._sessions) == {"a", "c"}


def test_context_no_crea_sesion_ni_expulsa_otras():
    mem = MemoryManager(max_sessions=1)
    mem.append("real", "user", "dato")
    for i in range(10):
        assert mem.context(f"sonda-{i}") == []
    assert mem.context("real") == [{"role": "user", "content": "dato"}]


def test_context_devuelve_copia_defensiva():
    mem = MemoryManager()
    mem.append("a", "user", "original")
    ctx = mem.context("a")
    ctx[0]["content"] = "mutado"
    ctx.append({"role": "user", "content": "extra"})
    assert mem.context("a") == [{"role": "user", "content": "original"}]


def test_clear_de_sesion_inexistente_no_falla():
    mem = MemoryManager()
    mem.clear("nunca-existio")


def test_record_turn_agrega_par():
    mem = MemoryManager()
    mem.record_turn("a", "pregunta", "respuesta")
    assert mem.context("a") == [
        {"role": "user", "content": "pregunta"},
        {"role": "assistant", "content": "respuesta"},
    ]


def test_memory_global_usa_config():
    assert memory_module.memory._ttl_seconds == memory_module.get_settings().memory_ttl_hours * 3600
    assert memory_module.memory._max_sessions == memory_module.get_settings().memory_max_sessions


def test_concurrencia_evict_y_purge_sin_runtimeerror(switch_agresivo):
    mem = MemoryManager(max_sessions=5, ttl_seconds=3600)
    errors: list[BaseException] = []

    def spam(n: int) -> None:
        try:
            for i in range(2000):
                mem.append(f"s{n}-{i}", "user", "x")
                mem.context(f"s{n}-{i}")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=spam, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(mem._sessions) <= 5


def test_concurrencia_turnos_no_se_intercalan(switch_agresivo):
    mem = MemoryManager(max_messages=10_000)

    def turnos(n: int) -> None:
        for i in range(200):
            mem.record_turn("compartida", f"q{n}-{i}", f"a{n}-{i}")

    threads = [threading.Thread(target=turnos, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    msgs = mem.context("compartida")
    assert len(msgs) == 6 * 200 * 2
    for user, assistant in zip(msgs[::2], msgs[1::2], strict=True):
        assert user["role"] == "user" and assistant["role"] == "assistant"
        assert user["content"][1:] == assistant["content"][1:]
