from jerico.config import Settings
from jerico.router import RouteDecision, TokenRouter


def make_router(l2_keywords: str = "codigo,auditoria,finanzas,arquitectura") -> TokenRouter:
    settings = Settings(
        llm_base_url="http://localhost/v1",
        llm_api_key="test",
        llm_model_l1="glm-5.3-flash",
        llm_model_l2="deepseek-flash",
        router_l2_keywords=l2_keywords,
        api_token="test",
        _env_file=None,
    )
    return TokenRouter(settings)


def test_l0_saludo_directo_sin_llm():
    r = make_router()
    d = r.route("Hola")
    assert d.level == 0
    assert d.answer is not None and "Hola" in d.answer
    assert d.model == "none"


def test_l1_operativo_usa_glm():
    r = make_router()
    d = r.route("Crea el recordatorio del devocional de mañana")
    assert d.level == 1
    assert d.model == "glm-5.3-flash"
    assert d.answer is None


def test_l2_codigo_usa_deepseek():
    r = make_router()
    d = r.route("Auditoria del codigo del router")
    assert d.level == 2
    assert d.model == "deepseek-flash"


def test_prohibido_alias_latest_o_preview():
    r = make_router()
    for level in (1, 2):
        model = r.model_for_level(level)
        assert not model.endswith("-latest")
        assert not model.endswith("-preview")


def test_clasificacion_vacia_es_l0():
    r = make_router()
    assert r.classify("") == 0


def test_decision_dataclass_campos():
    d = RouteDecision(1, "glm-5.3-flash", "operativo")
    assert d.answer is None
