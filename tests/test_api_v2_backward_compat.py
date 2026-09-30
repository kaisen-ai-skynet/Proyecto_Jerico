from typing import Any

from fastapi.testclient import TestClient

from jerico.agent.conversation_loop import AgentTurnLoop
from jerico.agent.prompt_builder import PromptBuilder
from jerico.api import app, limiter
from jerico.config import Settings
from jerico.llm.token_accounting import LLMCompletion, TokenUsage
from jerico.memory import memory
from jerico.router import TokenRouter
from jerico.state import StateEngine


class FakeLLM:
    async def complete_messages_with_usage(
        self, messages: list[dict[str, Any]], *, level: int = 1, tools=None
    ) -> LLMCompletion:
        prompt = next(
            (message["content"] for message in reversed(messages) if message["role"] == "user"),
            "",
        )
        return LLMCompletion(f"echo:{prompt}", TokenUsage())


def _settings() -> Settings:
    values: dict[str, Any] = {
        "llm_base_url": "http://localhost/v1",
        "llm_api_key": "test",
        "llm_model_l1": "model-l1",
        "llm_model_l2": "model-l2",
        "api_token": "test-token",
        "rate_limit_per_min": 0,
        "_env_file": None,
    }
    return Settings(**values)


def _client(monkeypatch, tmp_path) -> TestClient:
    settings = _settings()
    monkeypatch.setattr("jerico.api.get_settings", lambda: settings)
    agent = AgentTurnLoop(
        StateEngine(tmp_path / "state.db"),
        FakeLLM(),  # type: ignore[arg-type]
        router=TokenRouter(settings),
        prompt_builder=PromptBuilder(""),
    )
    monkeypatch.setattr("jerico.api.get_agent_loop", lambda: agent)
    memory.clear_all()
    limiter.reset()
    return TestClient(app)


def test_ask_response_keeps_v1_compatible_shape(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    response = client.post(
        "/api/v1/ask",
        json={"prompt": "agenda de hoy", "session_id": "existing-client"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert set(response.json()) == {"level", "model", "answer"}
    assert response.json()["answer"] == "echo:agenda de hoy"


def test_siri_route_is_authenticated_and_returns_concise_compatible_body(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    unauthorized = client.post("/api/v1/siri", json={"prompt": "hola"})
    assert unauthorized.status_code == 401
    response = client.post(
        "/api/v1/siri",
        json={"prompt": "agenda de hoy", "session_id": "siri-client"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert response.json()["answer"] == "echo:agenda de hoy"
