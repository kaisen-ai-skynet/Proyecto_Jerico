import asyncio
from typing import Any

import pytest

from jerico.agent.conversation_loop import AgentTurnLoop
from jerico.agent.prompt_builder import PromptBuilder
from jerico.agent.turn_tool_round import TurnToolRound
from jerico.llm.token_accounting import LLMCompletion, TokenUsage
from jerico.llm.tool_calls import ToolCallRequest
from jerico.router import TokenRouter
from jerico.state import StateEngine


class FakeLLM:
    def __init__(self, completions: list[LLMCompletion]) -> None:
        self.completions = completions
        self.calls: list[dict[str, Any]] = []
        self.started = asyncio.Event()

    async def complete_messages_with_usage(self, messages, *, level, tools=None):
        self.calls.append(
            {"messages": [dict(message) for message in messages], "level": level, "tools": tools}
        )
        self.started.set()
        return self.completions.pop(0)


def _loop(path, fake: FakeLLM, *, max_iterations: int = 8) -> AgentTurnLoop:
    state = StateEngine(path)
    return AgentTurnLoop(
        state,
        fake,  # type: ignore[arg-type]
        router=TokenRouter(),
        prompt_builder=PromptBuilder("stable system"),
        max_iterations=max_iterations,
    )


@pytest.mark.asyncio
async def test_turno_multi_vuelta_persiste_roles_usage_y_resultados(tmp_path):
    tool_call = ToolCallRequest("call-1", "docker_list_containers", {})
    fake = FakeLLM(
        [
            LLMCompletion("", TokenUsage(10, 2, 3), (tool_call,)),
            LLMCompletion("resultado final", TokenUsage(8, 4, 2)),
        ]
    )
    loop = _loop(tmp_path / "state.db", fake)
    try:
        result = await loop.run_turn("session", "consulta de hoy")
        assert result.answer == "resultado final"
        assert result.iterations == 2
        assert result.usage == TokenUsage(18, 6, 5)
        assert result.tool_results[0]["tool_call_id"] == "call-1"

        messages = loop.state.get_session_transcript("session")
        assert [message.role for message in messages] == [
            "user",
            "assistant",
            "tool",
            "assistant",
        ]
        assert messages[1].tool_calls[0]["id"] == "call-1"  # type: ignore[index]
        assert messages[2].tool_call_id == "call-1"
        assert fake.calls[0]["messages"][0] == {"role": "system", "content": "stable system"}
        assert [item["role"] for item in fake.calls[1]["messages"]] == [
            "system",
            "user",
            "assistant",
            "tool",
        ]
        assert fake.calls[0]["messages"][0] == fake.calls[1]["messages"][0]
        assert loop.state.get_usage("session", result.model) == {
            "prompt_tokens": 18,
            "completion_tokens": 6,
            "cached_tokens": 5,
        }
    finally:
        loop.state.close()


@pytest.mark.asyncio
async def test_l0_no_llama_al_llm_y_persiste_turno_local(tmp_path):
    fake = FakeLLM([])
    loop = _loop(tmp_path / "state.db", fake)
    try:
        result = await loop.run_turn("greeting", "hola")
        assert result.level == 0
        assert result.iterations == 0
        assert result.answer
        assert fake.calls == []
        assert [message.role for message in loop.state.get_session_transcript("greeting")] == [
            "user",
            "assistant",
        ]
    finally:
        loop.state.close()


@pytest.mark.asyncio
async def test_limite_de_iteraciones_responde_y_cierra_turno(tmp_path):
    tool_call = ToolCallRequest("call", "unknown_tool", {})
    fake = FakeLLM([LLMCompletion("", TokenUsage(), (tool_call,))])
    loop = _loop(tmp_path / "state.db", fake, max_iterations=1)
    try:
        result = await loop.run_turn("limited", "operación")
        assert result.iterations == 1
        assert result.answer.startswith("Se alcanzó el límite")
        assert result.tool_results == ()
        assert [m.role for m in loop.state.get_session_transcript("limited")] == [
            "user",
            "assistant",
        ]
    finally:
        loop.state.close()


@pytest.mark.asyncio
async def test_request_interrupt_cancela_llm_y_libera_lease(tmp_path):
    class BlockingLLM:
        def __init__(self) -> None:
            self.started = asyncio.Event()

        async def complete_messages_with_usage(self, *_args, **_kwargs):
            self.started.set()
            await asyncio.Event().wait()

    fake = BlockingLLM()
    loop = _loop(tmp_path / "state.db", fake)  # type: ignore[arg-type]
    try:
        task = asyncio.create_task(loop.run_turn("interrupt", "pregunta"))
        await asyncio.wait_for(fake.started.wait(), timeout=1)
        assert loop.request_interrupt("interrupt")
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not loop.request_interrupt("interrupt")
        assert loop.state.try_acquire_session_lease("interrupt", "check", 1)
        assert loop.state.release_session_lease("interrupt", "check")
    finally:
        loop.state.close()


@pytest.mark.asyncio
async def test_tool_mutable_nunca_se_autoconfirma():
    calls = (ToolCallRequest("write", "docker_restart_container", {"confirm": True}),)
    result = await TurnToolRound().execute(calls)
    assert result.results[0]["ok"] is False
    assert result.results[0]["error"] == "CONFIRMATION_REQUIRED"


@pytest.mark.asyncio
async def test_tool_call_desconocida_se_devuelve_como_error_validado():
    outcome = await TurnToolRound().execute((ToolCallRequest("bad", "missing", {}),))
    assert outcome.tool_messages[0]["role"] == "tool"
    assert outcome.tool_messages[0]["tool_call_id"] == "bad"
    assert "UNKNOWN_TOOL" in str(outcome.results[0])
