from jerico.memory import MemoryManager


def test_tope_de_sesiones_expulsa_la_mas_vieja():
    mem = MemoryManager(max_sessions=2)
    mem.append("a", "user", "uno")
    mem.append("b", "user", "dos")
    mem.append("c", "user", "tres")
    assert "a" not in mem._sessions
    assert mem._sessions["c"].messages[0]["content"] == "tres"


def test_contexto_no_incluye_el_turno_que_aun_no_se_appendea():
    mem = MemoryManager()
    assert mem.context("nueva") == []
    mem.append("nueva", "user", "hola")
    assert mem.context("nueva") == [{"role": "user", "content": "hola"}]
