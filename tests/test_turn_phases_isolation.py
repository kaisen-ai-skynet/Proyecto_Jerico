import time

import pytest

from jerico.agent.turn_api_call import TurnApiCaller
from jerico.agent.turn_preflight import TurnPreflightGate
from jerico.agent.types import TokenPressureLevel
from jerico.llm.token_accounting import LLMCompletion, TokenUsage
from jerico.llm_client import LLMError
from jerico.state import StateEngine


@pytest.mark.asyncio
async def test_lease_es_exclusivo_entre_instancias_y_se_libera(tmp_path):
    path = tmp_path / "state.db"
    first_state = StateEngine(path)
    second_state = StateEngine(path)
    try:
        first = TurnPreflightGate(first_state)
        second = TurnPreflightGate(second_state)
        lease = await first.acquire_lease("s")
        with pytest.raises(TimeoutError, match="lease"):
            await second.acquire_lease("s", timeout_s=0.02)
        assert not second_state.release_session_lease("s", "wrong-owner")
        await first.release_lease(lease)
        new_lease = await second.acquire_lease("s", timeout_s=0.1)
        assert new_lease.owner_token != lease.owner_token
        await second.release_lease(new_lease)
    finally:
        first_state.close()
        second_state.close()


def test_presion_de_tokens_tiene_limites_deterministas():
    evaluate = TurnPreflightGate.evaluate_token_pressure
    assert evaluate("s", 80, 100) is TokenPressureLevel.LOW
    assert evaluate("s", 81, 100) is TokenPressureLevel.ELEVATED
    assert evaluate("s", 100, 100) is TokenPressureLevel.ELEVATED
    assert evaluate("s", 101, 100) is TokenPressureLevel.OVERFLOW
    with pytest.raises(ValueError):
        evaluate("s", -1, 100)
    with pytest.raises(ValueError):
        evaluate("s", 1, 0)


class RetryingClient:
    def __init__(self, errors: list[LLMError]) -> None:
        self.errors = errors
        self.calls = 0

    async def complete_messages_with_usage(self, *_args, **_kwargs):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return LLMCompletion("ok", TokenUsage())


@pytest.mark.asyncio
async def test_api_caller_reintenta_solo_errores_transitorios():
    waits: list[float] = []

    async def fake_sleep(delay: float) -> None:
        waits.append(delay)

    client = RetryingClient([LLMError("timeout", retryable=True), LLMError("429", retryable=True)])
    caller = TurnApiCaller(
        client,  # type: ignore[arg-type]
        max_retries=2,
        base_delay_s=0.01,
        sleep=fake_sleep,
        jitter=lambda: 1.0,
    )
    completion = await caller.call([], level=1)
    assert completion.content == "ok"
    assert client.calls == 3
    assert waits == [0.01, 0.02]


@pytest.mark.asyncio
async def test_api_caller_propaga_errores_no_reintentables():
    client = RetryingClient([LLMError("invalid", retryable=False)])
    caller = TurnApiCaller(client, max_retries=3)  # type: ignore[arg-type]
    with pytest.raises(LLMError, match="invalid"):
        await caller.call([], level=1)
    assert client.calls == 1


@pytest.mark.asyncio
async def test_timeout_cero_intenta_una_vez_y_falla(tmp_path):
    state = StateEngine(tmp_path / "state.db")
    gate = TurnPreflightGate(state)
    try:
        lease = await gate.acquire_lease("s", timeout_s=0)
        await gate.release_lease(lease)
    finally:
        state.close()


def test_lease_expirada_puede_ser_adquirida_por_otro_owner(tmp_path):
    state = StateEngine(tmp_path / "state.db")
    try:
        assert state.try_acquire_session_lease("s", "owner-a", 0.01)
        time.sleep(0.02)
        assert state.try_acquire_session_lease("s", "owner-b", 1)
        assert not state.release_session_lease("s", "owner-a")
        assert state.release_session_lease("s", "owner-b")
        with pytest.raises(ValueError):
            state.try_acquire_session_lease("s", "owner", 0)
    finally:
        state.close()
