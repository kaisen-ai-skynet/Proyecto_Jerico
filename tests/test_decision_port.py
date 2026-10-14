"""Pruebas de T08: Puerto decidir y configuración.

Cubre requisitos VJT-010 a 015, 026, 030, 033, 037, 044, 052, 054.
"""

from pathlib import Path

from jerico.decision.breaker import CircuitBreaker
from jerico.decision.cache import DecisionCache, decision_key
from jerico.decision.config import DecisionSettings
from jerico.decision.policy import load_policy
from jerico.decision.port import Decision, decidir
from jerico.decision.recorder import DecisionRecorder


def test_decidir_apagado_devuelve_base(tmp_path: Path):
    """En modo 'apagado', decidir aplica siempre la base con fuente 'base' (VJT-011)."""
    settings = DecisionSettings(modes={"nivel_turno": "apagado"}, base_dir=tmp_path)
    state = {"tipo_mensaje": "simple", "longitud_rango": "corta"}

    decision = decidir("nivel_turno", state, settings=settings)

    assert isinstance(decision, Decision)
    assert decision.option == "L1"
    assert decision.source == "base"
    assert decision.reason == "apagado"
    assert decision.event_id.startswith("evt_")


def test_decidir_sombra_devuelve_base(tmp_path: Path):
    """En modo 'sombra', Nivel 1 aplica la base y registra (VJT-011, VJT-054)."""
    recorder = DecisionRecorder(dir_path=tmp_path)
    settings = DecisionSettings(modes={"nivel_turno": "sombra"}, base_dir=tmp_path)
    state = {"tipo_mensaje": "complejo", "longitud_rango": "larga"}

    decision = decidir("nivel_turno", state, settings=settings, recorder=recorder)

    assert decision.option == "L1"
    assert decision.source == "base"
    assert decision.reason == "sombra"

    # Verificar que quedó registrado
    files = list(tmp_path.glob("decision-*.jsonl"))
    assert len(files) == 1


def test_decidir_una_sola_opcion_devuelve_base_una_opcion(tmp_path: Path):
    """Con una sola opción permitida, devuelve esa opción sin consultar (VJT-008)."""
    settings = DecisionSettings(modes={"modelo_asistente": "sombra"}, base_dir=tmp_path)
    state = {"tipo_tarea": "resumen_lead", "longitud_contexto": "corta"}

    decision = decidir("modelo_asistente", state, tarea="resumen_lead", settings=settings)

    assert decision.option == "gpt-6-luna"
    assert decision.source == "base"
    assert decision.reason == "una_opcion"


def test_decidir_estado_invalido_devuelve_base_sin_lanzar(tmp_path: Path):
    """Si el estado no cumple validación, devuelve la base (VJT-025, 030)."""
    settings = DecisionSettings(base_dir=tmp_path)
    bad_state = {"campo_inventado": "xxx"}

    decision = decidir("nivel_turno", bad_state, settings=settings)

    assert decision.option == "L1"
    assert decision.source == "base"
    assert "estado_invalido" in decision.reason


def test_decidir_kill_switch_por_archivo_marcador(tmp_path: Path):
    """El archivo marcador decision.KILL fuerza modo apagado sin reiniciar (VJT-014)."""
    settings = DecisionSettings(modes={"nivel_turno": "sombra"}, base_dir=tmp_path)
    kill_file = tmp_path / "decision.KILL"
    state = {"tipo_mensaje": "simple", "longitud_rango": "corta"}

    # Sin archivo marcador -> sombra
    d1 = decidir("nivel_turno", state, settings=settings)
    assert d1.reason == "sombra"

    # Crear archivo marcador -> apagado
    kill_file.write_text("kill general activo", encoding="utf-8")
    d2 = decidir("nivel_turno", state, settings=settings)
    assert d2.reason == "apagado"


def test_decidir_sugerencia_expone_opcion_solo_al_cto(tmp_path: Path):
    """Modo sugerencia aplica la base y expone suggested solo al rol CTO (VJT-012)."""
    policy = load_policy()
    cache = DecisionCache()
    # Inyectamos en caché una respuesta de Jev simulada
    state = {"tipo_mensaje": "complejo", "longitud_rango": "larga"}
    dkey = decision_key("nivel_turno", None, state, policy.version)
    cache.put(dkey, "L3")

    settings = DecisionSettings(modes={"nivel_turno": "sugerencia"}, base_dir=tmp_path)

    # Usuario normal -> applied=base, suggested=None
    d_user = decidir("nivel_turno", state, settings=settings, cache=cache, user_role="asesor")
    assert d_user.option == "L1"
    assert d_user.suggested is None

    # Usuario CTO -> applied=base, suggested="L3"
    d_cto = decidir("nivel_turno", state, settings=settings, cache=cache, user_role="cto")
    assert d_cto.option == "L1"
    assert d_cto.suggested == "L3"


def test_decidir_degradacion_persiste_tras_tres_fallos(tmp_path: Path):
    """Tres fallos consecutivos degradan a sombra con marcador (VJT-015)."""
    breaker = CircuitBreaker(threshold=3, cooldown=300.0)
    settings = DecisionSettings(modes={"nivel_turno": "enrutado"}, base_dir=tmp_path)
    state = {"tipo_mensaje": "complejo", "longitud_rango": "larga"}

    class MockFailingClient:
        def consultar(self, *args, **kwargs):
            raise RuntimeError("Jev timeout")

    client = MockFailingClient()

    # 3 llamadas fallidas
    for _ in range(3):
        decidir("nivel_turno", state, settings=settings, breaker=breaker, client=client)

    # Debe haberse creado el archivo marcador de degradación
    marker = tmp_path / "degraded_nivel_turno.marker"
    assert marker.exists()

    # Nueva llamada debe operar en sombra debido al marcador
    d_post = decidir("nivel_turno", state, settings=settings)
    assert d_post.reason == "sombra"


def test_decidir_empate_resuelve_a_base(tmp_path: Path):
    """Si Jev devuelve opciones con igual probabilidad (empate), aplica la base (VJT-037)."""
    settings = DecisionSettings(modes={"nivel_turno": "enrutado"}, base_dir=tmp_path)
    state = {"tipo_mensaje": "complejo", "longitud_rango": "larga"}

    class MockTieClient:
        def consultar(self, *args, **kwargs):
            return {"option": "L3", "empate": True}

    d = decidir("nivel_turno", state, settings=settings, client=MockTieClient())
    assert d.option == "L1"
    assert d.reason == "empate_jev"


def test_decidir_nunca_lanza_excepcion(tmp_path: Path):
    """decidir nunca lanza excepciones ante fallos catastróficos inyectados (VJT-030)."""

    # Simulamos un objeto que falla en get
    class BrokenCache:
        def get(self, *args):
            raise ZeroDivisionError("Falla catastrófica de memoria")

    settings = DecisionSettings(modes={"nivel_turno": "enrutado"}, base_dir=tmp_path)
    d = decidir(
        "nivel_turno",
        {"tipo_mensaje": "simple", "longitud_rango": "corta"},
        settings=settings,
        cache=BrokenCache(),  # type: ignore[arg-type]
    )
    assert isinstance(d, Decision)
    assert d.source == "respaldo"
    assert d.reason == "excepcion"


def test_decidir_enrutado_exitoso_con_cliente(tmp_path: Path):
    """Enrutado con cliente válido consulta, aplica piso y registra (VJT-005, VJT-040)."""
    recorder = DecisionRecorder(dir_path=tmp_path)
    settings = DecisionSettings(modes={"nivel_turno": "enrutado"}, base_dir=tmp_path)
    state = {"tipo_mensaje": "complejo", "longitud_rango": "larga"}

    class MockOkClient:
        def consultar(self, *args, **kwargs):
            return {"option": "L2"}

    d = decidir(
        "nivel_turno",
        state,
        settings=settings,
        recorder=recorder,
        client=MockOkClient(),
    )
    assert d.option == "L2"
    assert d.source == "jev"
    assert d.reason == "piso_cumplido"

    # Verificar que quedó registrado en disco
    files = list(tmp_path.glob("decision-*.jsonl"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert "piso_cumplido" in content
