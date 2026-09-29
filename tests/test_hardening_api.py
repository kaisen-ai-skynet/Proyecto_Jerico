"""Revisión adversarial del endpoint /api/v1/ask: auth, validación, errores del LLM."""

import threading
from typing import Any

import pytest
from fastapi.testclient import TestClient

from jerico import api
from jerico.agent.conversation_loop import AgentTurnLoop
from jerico.agent.prompt_builder import PromptBuilder
from jerico.api import MAX_PROMPT_CHARS, RateLimiter, app, limiter
from jerico.config import Settings
from jerico.llm.token_accounting import LLMCompletion, TokenUsage
from jerico.llm_client import LLMError
from jerico.memory import memory
from jerico.router import TokenRouter
from jerico.state import StateEngine

AUTH = {"Authorization": "Bearer test-token"}


class FakeLLM:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = fail

    async def complete_messages_with_usage(self, messages, *, level: int = 1, tools=None):
        prompt = next(
            (message["content"] for message in reversed(messages) if message["role"] == "user"),
            "",
        )
        self.calls.append({"prompt": prompt, "level": level, "history": messages[1:-1]})
        if self.fail:
            raise LLMError("APITimeoutError en L1 (model-l1)")
        return LLMCompletion(f"echo:{prompt}", TokenUsage())


def _settings(**overrides: object) -> Settings:
    data: dict[str, Any] = {
        "llm_base_url": "http://localhost/v1",
        "llm_api_key": "test",
        "llm_model_l1": "model-l1",
        "llm_model_l2": "model-l2",
        "llm_model_l3": "model-l3",
        "api_token": "test-token",
        "rate_limit_per_min": 0,
        "_env_file": None,
    }
    data.update(overrides)
    return Settings(**data)


@pytest.fixture
def fake() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def client(monkeypatch, fake, tmp_path) -> TestClient:
    settings = _settings()
    monkeypatch.setattr("jerico.api.get_settings", lambda: settings)
    agent = AgentTurnLoop(
        StateEngine(tmp_path / "state.db"),
        fake,  # type: ignore[arg-type]
        router=TokenRouter(settings),
        prompt_builder=PromptBuilder(""),
    )
    monkeypatch.setattr("jerico.api.get_agent_loop", lambda: agent)
    memory.clear_all()
    limiter.reset()
    return TestClient(app, raise_server_exceptions=False)


# --- Auth ---


@pytest.mark.parametrize(
    "header",
    [
        "Bearer t\xe9st".encode("latin-1"),  # no-ASCII: antes TypeError -> 500
        b"Bearer test-token\xff",
    ],
)
def test_authorization_no_ascii_es_401_no_500(client, header):
    res = client.post("/api/v1/ask", json={"prompt": "hola"}, headers={"Authorization": header})
    assert res.status_code == 401


@pytest.mark.parametrize(
    "header",
    ["test-token", "bearer test-token", "Bearer  test-token", "Bearer test-token ", "Bearer "],
)
def test_variantes_del_token_se_rechazan(client, header):
    res = client.post("/api/v1/ask", json={"prompt": "hola"}, headers={"Authorization": header})
    assert res.status_code == 401


def test_token_placeholder_en_mayusculas_no_autentica(monkeypatch, fake):
    settings = _settings(api_token="CHANGEME")
    monkeypatch.setattr("jerico.api.get_settings", lambda: settings)
    res = TestClient(app).post(
        "/api/v1/ask", json={"prompt": "hola"}, headers={"Authorization": "Bearer CHANGEME"}
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "token_not_configured"


def test_401_no_consume_cupo_del_rate_limit(monkeypatch, fake, tmp_path):
    settings = _settings(rate_limit_per_min=1)
    monkeypatch.setattr("jerico.api.get_settings", lambda: settings)
    agent = AgentTurnLoop(
        StateEngine(tmp_path / "state.db"),
        fake,  # type: ignore[arg-type]
        router=TokenRouter(settings),
        prompt_builder=PromptBuilder(""),
    )
    monkeypatch.setattr("jerico.api.get_agent_loop", lambda: agent)
    limiter.reset()
    client = TestClient(app)
    for _ in range(3):
        bad = client.post("/api/v1/ask", json={"prompt": "hola"}, headers={"Authorization": "x"})
        assert bad.status_code == 401
    assert client.post("/api/v1/ask", json={"prompt": "hola"}, headers=AUTH).status_code == 200


# --- Validación de entrada ---


@pytest.mark.parametrize("prompt", ["", "   ", "\n\t", "???", "¡!"])
def test_prompt_vacio_o_solo_puntuacion_no_llama_al_llm(client, fake, prompt):
    res = client.post("/api/v1/ask", json={"prompt": prompt}, headers=AUTH)
    assert res.status_code == 200
    body = res.json()
    assert body["level"] == 0
    assert body["answer"]
    assert fake.calls == []


def test_prompt_demasiado_largo_es_422(client, fake):
    res = client.post("/api/v1/ask", json={"prompt": "a" * (MAX_PROMPT_CHARS + 1)}, headers=AUTH)
    assert res.status_code == 422
    assert fake.calls == []


def test_prompt_en_el_limite_se_acepta(client, fake):
    res = client.post("/api/v1/ask", json={"prompt": "a" * MAX_PROMPT_CHARS}, headers=AUTH)
    assert res.status_code == 200


@pytest.mark.parametrize("session_id", ["", "s" * 129])
def test_session_id_invalido_es_422(client, session_id):
    res = client.post(
        "/api/v1/ask", json={"prompt": "hola", "session_id": session_id}, headers=AUTH
    )
    assert res.status_code == 422


@pytest.mark.parametrize("payload", [{}, {"prompt": None}, {"prompt": 123}, {"prompt": ["x"]}])
def test_payload_malformado_es_422(client, payload):
    assert client.post("/api/v1/ask", json=payload, headers=AUTH).status_code == 422


def test_json_invalido_es_422(client):
    res = client.post(
        "/api/v1/ask",
        content=b"{no json",
        headers={**AUTH, "Content-Type": "application/json"},
    )
    assert res.status_code == 422


# --- Errores del LLM ---


def test_fallo_del_llm_es_502_y_no_ensucia_memoria(client, fake):
    fake.fail = True
    res = client.post(
        "/api/v1/ask", json={"prompt": "agenda de hoy", "session_id": "s-err"}, headers=AUTH
    )
    assert res.status_code == 502
    assert res.json()["detail"] == "llm_unavailable"
    assert "APITimeoutError" not in res.text
    assert memory.context("s-err") == []


def test_turnos_quedan_en_pares_user_assistant(client):
    for prompt in ["uno", "dos", "hola"]:
        client.post("/api/v1/ask", json={"prompt": prompt, "session_id": "p"}, headers=AUTH)
    agent = api.get_agent_loop()
    roles = [message.role for message in agent.state.get_session_transcript("p")]
    assert roles == ["user", "assistant"] * 3


def test_sesiones_aisladas_entre_si(client, fake):
    client.post("/api/v1/ask", json={"prompt": "secreto A", "session_id": "a"}, headers=AUTH)
    client.post("/api/v1/ask", json={"prompt": "pregunta B", "session_id": "b"}, headers=AUTH)
    assert fake.calls[1]["history"] == []


# --- Rate limiter ---


def test_rate_limiter_es_exacto_bajo_concurrencia():
    rl = RateLimiter()
    allowed: list[int] = []
    lock = threading.Lock()

    def hit() -> None:
        for _ in range(50):
            if rl.allow("k", 50):
                with lock:
                    allowed.append(1)

    threads = [threading.Thread(target=hit) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(allowed) == 50


def test_rate_limiter_ventana_expira(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(api.time, "monotonic", lambda: now[0])
    rl = RateLimiter()
    assert rl.allow("k", 1)
    assert not rl.allow("k", 1)
    now[0] += 60.0
    assert rl.allow("k", 1)


def test_rate_limiter_por_clave_independiente():
    rl = RateLimiter()
    assert rl.allow("a", 1)
    assert rl.allow("b", 1)
    assert not rl.allow("a", 1)


def test_rate_limit_negativo_desactiva_limite():
    rl = RateLimiter()
    assert all(rl.allow("k", -1) for _ in range(100))


def test_get_llm_y_get_router_se_reutilizan(monkeypatch):
    api.get_llm.cache_clear()
    api.get_router.cache_clear()
    settings = _settings()
    monkeypatch.setattr("jerico.api.get_settings", lambda: settings)
    try:
        assert api.get_llm() is api.get_llm()
        assert api.get_router() is api.get_router()
    finally:
        api.get_llm.cache_clear()
        api.get_router.cache_clear()
