from typing import Any

from jerico.config import Settings
from jerico.router import RouteDecision, TokenRouter


def make_settings(**overrides: object) -> Settings:
    data: dict[str, Any] = {
        "llm_base_url": "http://localhost/v1",
        "llm_api_key": "test",
        "llm_model_l1": "glm-5.3-flash",
        "llm_model_l2": "deepseek-flash",
        "llm_model_l3": "frontier-model",
        "api_token": "test",
        "_env_file": None,
    }
    data.update(overrides)
    return Settings(**data)


def make_router(**overrides: object) -> TokenRouter:
    return TokenRouter(make_settings(**overrides))


def test_l0_saludo_directo_sin_llm():
    d = make_router().route("Hola")
    assert d.level == 0
    assert d.answer is not None and "Hola" in d.answer
    assert d.model == "none"


def test_l0_que_tal_con_tilde():
    d = make_router().route("Qué tal")
    assert d.level == 0
    assert d.answer is not None


def test_l1_operativo():
    d = make_router().route("Crea el recordatorio del devocional de mañana")
    assert d.level == 1
    assert d.model == "glm-5.3-flash"
    assert d.answer is None


def test_l2_con_tilde():
    d = make_router().route("Auditoría del gasto")
    assert d.level == 2
    assert d.model == "deepseek-flash"


def test_codigo_postal_no_es_l2():
    d = make_router().route("cuál es el código postal de Medellín")
    assert d.level == 1


def test_l3_finanzas_usa_modelo_de_frontera():
    d = make_router().route("Revisa el contrato y la rentabilidad")
    assert d.level == 3
    assert d.model == "frontier-model"


def test_l3_sin_modelo_cae_a_l2():
    d = make_router(llm_model_l3="").route("Revisa el contrato")
    assert d.level == 3
    assert d.model == "deepseek-flash"


def test_prohibido_alias_latest_o_preview():
    r = make_router()
    for level in (1, 2, 3):
        model = r.model_for_level(level)
        assert not model.endswith("-latest")
        assert not model.endswith("-preview")


def test_alias_flotante_rechazado():
    try:
        make_settings(llm_model_l1="foo-latest")
    except ValueError:
        return
    raise AssertionError("debio rechazar -latest")


def test_clasificacion_vacia_es_l0():
    assert make_router().classify("") == 0


def test_decision_dataclass_campos():
    assert RouteDecision(1, "glm-5.3-flash", "operativo").answer is None


def test_endpoint_por_nivel_con_fallback():
    settings = make_settings(llm_base_url_l2="https://api.deepseek.com", llm_api_key_l2="k2")
    base, key, model = settings.endpoint_for(2)
    assert base == "https://api.deepseek.com"
    assert key == "k2"
    assert model == "deepseek-flash"
    assert settings.endpoint_for(1)[0] == "http://localhost/v1"
