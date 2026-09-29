"""Revisión adversarial de config (endpoints, alias) y del router L0-L3."""

from typing import Any

import pytest
from pydantic import ValidationError

from jerico.config import Settings, token_configured
from jerico.router import EMPTY_ANSWER, TokenRouter


def make_settings(**overrides: object) -> Settings:
    data: dict[str, Any] = {
        "llm_base_url": "https://gateway/v1",
        "llm_api_key": "gw-key",
        "llm_model_l1": "m1",
        "llm_model_l2": "m2",
        "llm_model_l3": "m3",
        "api_token": "test",
        "_env_file": None,
    }
    data.update(overrides)
    return Settings(**data)


def classify(prompt: str, **overrides: object) -> int:
    return TokenRouter(make_settings(**overrides)).classify(prompt)


# --- Endpoints por nivel ---


def test_l3_sin_modelo_usa_endpoint_de_l2_no_el_gateway():
    s = make_settings(
        llm_model_l3="", llm_base_url_l2="https://api.deepseek.com", llm_api_key_l2="dk"
    )
    assert s.endpoint_for(3) == ("https://api.deepseek.com", "dk", "m2")


def test_l3_con_modelo_propio_usa_su_endpoint():
    s = make_settings(llm_base_url_l3="https://frontier", llm_api_key_l3="fk")
    assert s.endpoint_for(3) == ("https://frontier", "fk", "m3")


def test_l3_sin_overrides_usa_gateway():
    assert make_settings().endpoint_for(3) == ("https://gateway/v1", "gw-key", "m3")


@pytest.mark.parametrize(
    "override",
    [
        {"llm_base_url_l2": "https://api.deepseek.com"},  # key del gateway -> tercero
        {"llm_api_key_l1": "direct-key"},  # key directa -> gateway
        {"llm_base_url_l3": "https://x"},
    ],
)
def test_override_parcial_de_endpoint_se_rechaza(override):
    with pytest.raises(ValidationError, match="incompleto"):
        make_settings(**override)


@pytest.mark.parametrize("level", [0, -1, 4, 99])
def test_endpoint_niveles_fuera_de_rango_no_revientan(level):
    base, key, _ = make_settings().endpoint_for(level)
    assert (base, key) == ("https://gateway/v1", "gw-key")


# --- Alias flotantes ---


@pytest.mark.parametrize(
    "model",
    ["foo-latest", "FOO-LATEST", "llama3:latest", "x@latest", "gemini-preview", "m-latest  "],
)
def test_alias_flotantes_rechazados(model):
    with pytest.raises(ValidationError):
        make_settings(llm_model_l2=model)


@pytest.mark.parametrize(
    "model", ["openai/gpt-4o-mini", "gemini-2.5-pro-preview-05-06", "latest-model-v1"]
)
def test_modelos_fijados_aceptados(model):
    assert make_settings(llm_model_l1=model).llm_model_l1 == model


def test_modelo_se_normaliza_sin_espacios():
    assert make_settings(llm_model_l1="  m1 \n").llm_model_l1 == "m1"


# --- Token ---


@pytest.mark.parametrize("token", ["", "   ", "changeme", "CHANGEME", " ChangeMe "])
def test_token_placeholder_variantes(token):
    assert token_configured(token) is False


# --- Router ---


@pytest.mark.parametrize(
    "prompt",
    ["Hola!", "hola.", "¡Hola!", "gracias!!", "¿Qué tal?", "  Buenos   días  ", "OK."],
)
def test_saludos_con_puntuacion_son_l0(prompt):
    d = TokenRouter(make_settings()).route(prompt)
    assert d.level == 0
    assert d.answer and d.answer != EMPTY_ANSWER


@pytest.mark.parametrize("prompt", ["", "   ", "?", "..."])
def test_vacio_es_l0_con_respuesta(prompt):
    d = TokenRouter(make_settings()).route(prompt)
    assert d.level == 0
    assert d.answer == EMPTY_ANSWER


@pytest.mark.parametrize(
    ("prompt", "level"),
    [
        ("revisa los contratos", 3),
        ("temas legales pendientes", 3),
        ("hay dos demandas", 3),
        ("hay dos bugs en prod", 2),
        ("revisa las auditorías", 2),
        ("códigos de error", 2),
    ],
)
def test_plurales_no_escapan_del_nivel(prompt, level):
    assert classify(prompt) == level


@pytest.mark.parametrize(
    "prompt", ["ok, revisa el bug", "hola, revisa el contrato", "gracias. mira el sql"]
)
def test_saludo_con_contenido_no_es_l0(prompt):
    assert classify(prompt) >= 2


def test_excepcion_l2_no_degrada_l3():
    assert classify("demanda de agua", router_l2_exceptions="demanda de agua") == 3


def test_excepcion_l2_sigue_funcionando():
    assert classify("codigo postal de bogota") == 1
    assert classify("codigo postal y el codigo del login") == 2


def test_l3_gana_a_l2():
    assert classify("bug en el contrato") == 3


def test_keyword_dentro_de_otra_palabra_no_dispara():
    assert classify("el debugger de sqlite") == 1
    assert classify("ilegalmente") == 1


def test_keywords_vacias_todo_es_l1():
    kw: dict[str, object] = {"router_l2_keywords": "", "router_l3_keywords": ""}
    assert classify("contrato con bug", **kw) == 1


def test_keywords_con_regex_especial_se_escapan():
    assert classify("usa c++ aqui", router_l2_keywords="c++") == 2
    assert classify("usa cxx aqui", router_l2_keywords="c++") == 1


def test_prompt_enorme_no_es_lento():
    import time

    start = time.perf_counter()
    classify("palabra " * 50_000 + "contrato")
    assert time.perf_counter() - start < 2.0
