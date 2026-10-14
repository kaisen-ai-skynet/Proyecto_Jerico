"""Pruebas de enrutado operativo para tareas de clase C (spec 007, F3, T15).

Verifica:
1. Enrutado efectivo en clase C (VJT-005, VJT-013).
2. DeepSeek permitido solo en clase de datos sin_datos_personales (VJT-022, VJT-023).
3. Filtrado seguro si hay datos personales (VJT-008, VJT-024).
4. Manejo de opción fuera de permitidas (apply_floor).
5. Degradación automática tras fallos consecutivos del cliente (VJT-015).
6. Respeto al kill switch de emergencia.
"""

from pathlib import Path
from typing import Any

from jerico.decision.breaker import CircuitBreaker
from jerico.decision.cache import DecisionCache
from jerico.decision.config import DecisionSettings
from jerico.decision.policy import load_policy
from jerico.decision.port import Mode, decidir
from jerico.decision.state import DataClass


class MockJevClient:
    """Cliente falso de Jev para pruebas de enrutado."""

    def __init__(self, option_to_return: str = "deepseek-chat", fail: bool = False):
        self.option_to_return = option_to_return
        self.fail = fail
        self.call_count = 0

    def consultar(self, spec: Any, state: dict[str, Any]) -> dict[str, Any]:
        self.call_count += 1
        if self.fail:
            raise RuntimeError("Error de red simulado hacia Jev")
        return {
            "option": self.option_to_return,
            "confidence": 0.95,
            "latencia_ms": 120,
            "model_version": "jev-v2.1.0",
        }


def test_routing_class_c_sin_datos_personales(tmp_path: Path) -> None:
    """En clase C y sin_datos_personales, la opción de Jev (ej: deepseek-chat) se aplica."""
    policy = load_policy()
    settings = DecisionSettings(
        online=True,
        kill=False,
        base_dir=tmp_path,
        modes={"modelo_asistente": Mode.ENRUTADO},
    )
    breaker = CircuitBreaker(threshold=3)
    client = MockJevClient(option_to_return="deepseek-chat")
    cache = DecisionCache()

    state = {
        "tipo_tarea": "generar_web_app",
        "longitud_contexto": "corta",
    }

    class MockContext:
        clase_datos = DataClass.SIN_DATOS_PERSONALES
        sin_texto_libre = True

    dec = decidir(
        kind="modelo_asistente",
        tarea="generar_web_app",
        state=state,
        ctx=MockContext(),
        policy=policy,
        settings=settings,
        client=client,
        breaker=breaker,
        cache=cache,
    )

    assert dec.option == "deepseek-chat"
    assert dec.source == "jev"
    assert dec.reason == "enrutado_valido"
    assert client.call_count == 1


def test_routing_class_c_con_datos_personales_single_option_vjt008(tmp_path: Path) -> None:
    """Si hay datos personales, solo gpt-6-luna es apto; aplica VJT-008 sin consultar a Jev."""
    policy = load_policy()
    settings = DecisionSettings(
        online=True,
        kill=False,
        base_dir=tmp_path,
        modes={"modelo_asistente": Mode.ENRUTADO},
    )
    breaker = CircuitBreaker(threshold=3)
    client = MockJevClient(option_to_return="deepseek-chat")
    cache = DecisionCache()

    state = {
        "tipo_tarea": "resumen_lead",
        "longitud_contexto": "media",
    }

    class MockContext:
        clase_datos = DataClass.CON_DATOS_PERSONALES
        sin_texto_libre = False

    dec = decidir(
        kind="modelo_asistente",
        tarea="resumen_lead",
        state=state,
        ctx=MockContext(),
        policy=policy,
        settings=settings,
        client=client,
        breaker=breaker,
        cache=cache,
    )

    # Debe retornar una_opcion y no consultar a Jev
    assert dec.option == "gpt-6-luna"
    assert dec.reason == "una_opcion"
    assert client.call_count == 0


def test_routing_class_c_option_outside_allowed_falls_back_to_base(tmp_path: Path) -> None:
    """Si Jev retorna una opción no permitida, apply_floor cae a base con fuera_de_permitidas."""
    policy = load_policy()
    settings = DecisionSettings(
        online=True,
        kill=False,
        base_dir=tmp_path,
        modes={"modelo_asistente": Mode.ENRUTADO},
    )
    breaker = CircuitBreaker(threshold=3)
    client = MockJevClient(option_to_return="modelo-desconocido-no-permitido")
    cache = DecisionCache()

    state = {
        "tipo_tarea": "generar_web_app",
        "longitud_contexto": "corta",
    }

    class MockContext:
        clase_datos = DataClass.SIN_DATOS_PERSONALES
        sin_texto_libre = True

    dec = decidir(
        kind="modelo_asistente",
        tarea="generar_web_app",
        state=state,
        ctx=MockContext(),
        policy=policy,
        settings=settings,
        client=client,
        breaker=breaker,
        cache=cache,
    )

    assert dec.option == "gpt-6-luna"
    assert dec.reason == "fuera_de_permitidas"
    assert client.call_count == 1


def test_automatic_degradation_after_three_failures(tmp_path: Path) -> None:
    """Tras 3 fallos consecutivos del cliente, el modo se degrada automáticamente (VJT-015)."""
    policy = load_policy()
    settings = DecisionSettings(
        online=True,
        kill=False,
        base_dir=tmp_path,
        modes={"modelo_asistente": Mode.ENRUTADO},
    )
    breaker = CircuitBreaker(threshold=3)
    failing_client = MockJevClient(fail=True)
    cache = DecisionCache()

    state = {
        "tipo_tarea": "generar_web_app",
        "longitud_contexto": "corta",
    }

    # 3 fallos consecutivos
    for _ in range(3):
        dec = decidir(
            kind="modelo_asistente",
            tarea="generar_web_app",
            state=state,
            policy=policy,
            settings=settings,
            client=failing_client,
            breaker=breaker,
            cache=cache,
        )
        assert dec.option == "gpt-6-luna"
        assert dec.source == "respaldo"

    assert breaker.is_open() is True
    # settings debe haber registrado la degradación
    assert settings.is_degraded("modelo_asistente") is True
    assert settings.mode_for("modelo_asistente") == "sombra"


def test_kill_switch_forces_base_without_consulting_client(tmp_path: Path) -> None:
    """Si el kill switch está activo, retorna base inmediatamente sin invocar al cliente."""
    policy = load_policy()
    settings = DecisionSettings(
        online=True,
        kill=True,  # Kill switch activado
        base_dir=tmp_path,
        modes={"modelo_asistente": Mode.ENRUTADO},
    )
    breaker = CircuitBreaker(threshold=3)
    client = MockJevClient(option_to_return="deepseek-chat")
    cache = DecisionCache()

    state = {
        "tipo_tarea": "generar_web_app",
        "longitud_contexto": "corta",
    }

    dec = decidir(
        kind="modelo_asistente",
        tarea="generar_web_app",
        state=state,
        policy=policy,
        settings=settings,
        client=client,
        breaker=breaker,
        cache=cache,
    )

    assert dec.option == "gpt-6-luna"
    assert client.call_count == 0
