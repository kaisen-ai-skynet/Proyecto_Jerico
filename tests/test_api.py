from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from jerico.api import app, get_llm, limiter
from jerico.config import Settings, token_configured
from jerico.main import resolve_bind
from jerico.memory import memory
from jerico.router import TokenRouter


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def complete(
        self,
        prompt: str,
        *,
        level: int = 1,
        history: list | None = None,
        system: str | None = None,
    ) -> str:
        self.calls.append({"prompt": prompt, "level": level, "history": history or []})
        return f"echo:{prompt}"


def _settings(**overrides: object) -> Settings:
    data: dict[str, Any] = {
        "llm_base_url": "http://localhost/v1",
        "llm_api_key": "test",
        "llm_model_l1": "model-l1",
        "llm_model_l2": "model-l2",
        "llm_model_l3": "model-l3",
        "api_token": "test-token",
        "rate_limit_per_min": 0,
        "host": "127.0.0.1",
        "port": 9000,
        "_env_file": None,
    }
    data.update(overrides)
    return Settings(**data)


def _client(monkeypatch, settings: Settings, fake: FakeLLM) -> TestClient:
    monkeypatch.setattr("jerico.api.get_settings", lambda: settings)
    monkeypatch.setitem(app.dependency_overrides, get_llm, lambda: fake)
    monkeypatch.setattr("jerico.api.get_router", lambda: TokenRouter(settings))
    memory.clear_all()
    limiter.reset()
    return TestClient(app)


def test_health_sin_auth():
    res = TestClient(app).get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_ask_sin_token_es_401(monkeypatch):
    client = _client(monkeypatch, _settings(), FakeLLM())
    res = client.post("/api/v1/ask", json={"prompt": "hola"})
    assert res.status_code == 401


def test_ask_l0_no_llama_al_llm(monkeypatch):
    fake = FakeLLM()
    client = _client(monkeypatch, _settings(), fake)
    res = client.post(
        "/api/v1/ask",
        json={"prompt": "hola"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["level"] == 0
    assert "Hola" in body["answer"]
    assert fake.calls == []


def test_ask_pasa_historial(monkeypatch):
    fake = FakeLLM()
    client = _client(monkeypatch, _settings(), fake)
    headers = {"Authorization": "Bearer test-token"}
    first = client.post(
        "/api/v1/ask",
        json={"prompt": "agenda de mañana", "session_id": "s1"},
        headers=headers,
    )
    second = client.post(
        "/api/v1/ask",
        json={"prompt": "y el de pasado", "session_id": "s1"},
        headers=headers,
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert fake.calls[1]["history"][0]["content"] == "agenda de mañana"
    assert fake.calls[1]["level"] == 1


@pytest.mark.asyncio
async def test_endpoint_async_awaits_cliente_llm(monkeypatch):
    settings = _settings()
    fake = FakeLLM()
    monkeypatch.setattr("jerico.api.get_settings", lambda: settings)
    monkeypatch.setattr("jerico.api.get_router", lambda: TokenRouter(settings))
    monkeypatch.setitem(app.dependency_overrides, get_llm, lambda: fake)
    memory.clear_all()
    limiter.reset()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.post(
            "/api/v1/ask",
            json={"prompt": "agenda de hoy"},
            headers={"Authorization": "Bearer test-token"},
        )
    assert res.status_code == 200
    assert res.json()["answer"] == "echo:agenda de hoy"


def test_token_placeholder_no_arranca():
    assert token_configured("changeme") is False
    assert token_configured("abc") is True


def test_bind_respeta_env_si_cli_no_pasa_nada():
    settings = _settings()
    assert resolve_bind(None, None, settings) == ("127.0.0.1", 9000)
    assert resolve_bind("0.0.0.0", 8000, settings) == ("0.0.0.0", 8000)


def test_rate_limit_429(monkeypatch):
    fake = FakeLLM()
    client = _client(monkeypatch, _settings(rate_limit_per_min=1), fake)
    headers = {"Authorization": "Bearer test-token"}
    assert client.post("/api/v1/ask", json={"prompt": "hola"}, headers=headers).status_code == 200
    assert client.post("/api/v1/ask", json={"prompt": "hola"}, headers=headers).status_code == 429
