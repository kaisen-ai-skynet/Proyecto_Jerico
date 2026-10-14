"""Pruebas de T13: Modo sugerencia solo para el CTO (VJT-012, VJT-013, VJT-015).

Verifica que la opción de Jev en modo 'sugerencia' se expone únicamente a un usuario con
rol CTO verificado, mientras que para asesores, comerciales o clientes la opción aplicada
es siempre la base y la sugerida es None.
"""

from pathlib import Path
from typing import Any

from jerico.decision.breaker import CircuitBreaker
from jerico.decision.cache import DecisionCache
from jerico.decision.config import DecisionSettings
from jerico.decision.jev_client import JevClient
from jerico.decision.port import decidir
from jerico.decision.recorder import DecisionRecorder


def _sample_client(option: str = "L3") -> JevClient:
    def fake_transport(payload: dict[str, Any], headers: dict[str, str], timeout_s: float):
        return 200, {
            "model": "jev-1.13.0",
            "usage": {"input_tokens": 500, "output_tokens": 10},
            "answers": {
                "nivel_turno": {
                    "choice": option,
                    "confidence": 0.95,
                    "probabilities": {"L1": 0.02, "L2": 0.03, "L3": 0.95},
                }
            },
        }

    return JevClient(transport=fake_transport, api_key="secret-key")


def test_suggestion_mode_shows_jev_option_only_to_cto(tmp_path: Path):
    """En modo sugerencia, Jev sugiere una opción pero solo se expone al CTO (VJT-012)."""
    cache = DecisionCache()
    settings = DecisionSettings(modes={"nivel_turno": "sugerencia"}, base_dir=tmp_path)
    client = _sample_client("L3")
    state = {"tipo_mensaje": "complejo", "longitud_rango": "larga"}

    # 1. Rol CTO: aplicada=base (L1), sugerida=L3
    d_cto = decidir(
        "nivel_turno",
        state,
        settings=settings,
        cache=cache,
        client=client,
        user_role="cto",
    )
    assert d_cto.option == "L1"  # Base siempre aplicada
    assert d_cto.suggested == "L3"  # Expuesta al CTO

    # 2. Rol asesor / comercial: aplicada=base (L1), sugerida=None
    d_asesor = decidir(
        "nivel_turno",
        state,
        settings=settings,
        cache=cache,
        client=client,
        user_role="asesor",
    )
    assert d_asesor.option == "L1"
    assert d_asesor.suggested is None  # Oculta a usuarios normales

    # 3. Rol cliente / no autenticado: aplicada=base (L1), sugerida=None
    d_anon = decidir(
        "nivel_turno",
        state,
        settings=settings,
        cache=cache,
        client=client,
        user_role=None,
    )
    assert d_anon.option == "L1"
    assert d_anon.suggested is None


def test_suggestion_mode_logs_suggested_option_in_recorder(tmp_path: Path):
    """En modo sugerencia, la opción de Jev se registra en disco para auditoría (VJT-012)."""
    recorder = DecisionRecorder(dir_path=tmp_path)
    cache = DecisionCache()
    settings = DecisionSettings(modes={"nivel_turno": "sugerencia"}, base_dir=tmp_path)
    client = _sample_client("L2")
    state = {"tipo_mensaje": "complejo", "longitud_rango": "larga"}

    d = decidir(
        "nivel_turno",
        state,
        settings=settings,
        recorder=recorder,
        cache=cache,
        client=client,
        user_role="asesor",  # Asesor no la ve en respuesta...
    )
    assert d.suggested is None

    # ...pero en el registro persistido sí queda registrada
    files = list(tmp_path.glob("decision-*.jsonl"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert '"suggested_option": "L2"' in content
    assert '"applied_option": "L1"' in content


def test_suggestion_mode_cached_preserves_role_filtering(tmp_path: Path):
    """La caché no filtra por rol; el filtrado se aplica al leerla (VJT-012, VJT-034)."""
    cache = DecisionCache()
    settings = DecisionSettings(modes={"nivel_turno": "sugerencia"}, base_dir=tmp_path)
    client = _sample_client("L3")
    state = {"tipo_mensaje": "complejo", "longitud_rango": "larga"}

    # Primera llamada como CTO (carga la caché con L3)
    d1 = decidir(
        "nivel_turno", state, settings=settings, client=client, cache=cache, user_role="cto"
    )
    assert d1.suggested == "L3"

    # Segunda llamada como Asesor (reutiliza caché)
    d2 = decidir(
        "nivel_turno", state, settings=settings, client=client, cache=cache, user_role="asesor"
    )
    assert d2.source == "cache"
    assert d2.option == "L1"
    assert d2.suggested is None  # Asesor no debe ver la sugerencia cacheadada

    # Tercera llamada como CTO (reutiliza caché)
    d3 = decidir(
        "nivel_turno", state, settings=settings, client=client, cache=cache, user_role="cto"
    )
    assert d3.source == "cache"
    assert d3.option == "L1"
    assert d3.suggested == "L3"


def test_suggestion_mode_degrades_to_sombra_on_three_consecutive_failures(tmp_path: Path):
    """3 fallos consecutivos en sugerencia degradan a sombra con marcador (VJT-015)."""
    breaker = CircuitBreaker(threshold=3, cooldown=300.0)
    cache = DecisionCache()
    settings = DecisionSettings(modes={"nivel_turno": "sugerencia"}, base_dir=tmp_path)
    state = {"tipo_mensaje": "complejo", "longitud_rango": "larga"}

    class FailingClient:
        def consultar(self, *args, **kwargs):
            raise RuntimeError("Jev API 500 internal error")

    failing_client = FailingClient()

    # Ejecutar 3 fallos
    for _ in range(3):
        d = decidir(
            "nivel_turno",
            state,
            settings=settings,
            breaker=breaker,
            cache=cache,
            client=failing_client,
            user_role="cto",
        )
        assert d.source == "respaldo"
        assert d.reason == "fallo_cliente"

    # El marcador de degradación debe haberse escrito
    marker = tmp_path / "degraded_nivel_turno.marker"
    assert marker.exists()

    # La siguiente llamada opera automáticamente en sombra
    d_next = decidir("nivel_turno", state, settings=settings, user_role="cto")
    assert d_next.reason == "sombra"
