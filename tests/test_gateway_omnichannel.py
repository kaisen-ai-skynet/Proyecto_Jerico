import asyncio
from pathlib import Path
from typing import Any

import pytest

from jerico.agent.types import SurfaceType, TurnResult
from jerico.config import Settings
from jerico.gateway.platforms.cli import interactive_cli
from jerico.gateway.platforms.rest import handle_rest
from jerico.gateway.platforms.siri import handle_siri
from jerico.gateway.platforms.telegram import handle_telegram
from jerico.gateway.runner import OmniGateway
from jerico.llm.token_accounting import TokenUsage


class FakeAgent:
    def __init__(self, answer: str = "respuesta") -> None:
        self.answer = answer
        self.calls: list[tuple[str, str, SurfaceType]] = []

    async def run_turn(self, session_id, prompt, *, surface, posture):
        self.calls.append((session_id, prompt, surface))
        return TurnResult(session_id, self.answer, 1, "test-model", 1, TokenUsage())


def _gateway(answer: str = "respuesta") -> tuple[OmniGateway, FakeAgent]:
    values: dict[str, Any] = {
        "api_token": "secret",
        "allowed_telegram_ids": "42",
        "_env_file": None,
    }
    settings = Settings(**values)
    agent = FakeAgent(answer)
    return OmniGateway(agent, settings), agent  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_all_channels_delegate_to_same_agent_and_tag_surface(tmp_path):
    gateway, agent = _gateway("  línea uno\n" + "a" * 300)
    rest = await handle_rest(gateway, "r", "hola rest", "Bearer secret")
    siri = await handle_siri(gateway, "s", "hola siri", "Bearer secret")
    assert rest.answer.startswith("  línea uno")
    assert len(siri) == 280

    (tmp_path / "voice.wav").write_bytes(b"audio mock")
    telegram = await handle_telegram(
        gateway,
        "42",
        "chat",
        "Bearer secret",
        voice_path=tmp_path / "voice.wav",
        transcribe=lambda _: "nota transcrita",
    )
    cli_inputs = iter(("mensaje de cli", "/exit"))
    cli_output: list[str] = []
    await interactive_cli(
        gateway,
        "cli-session",
        "Bearer secret",
        read=lambda: next(cli_inputs),
        write=cli_output.append,
    )

    assert telegram.result.answer.startswith("  línea uno")
    assert cli_output == ["  línea uno\n" + "a" * 300]
    assert [call[2] for call in agent.calls] == [
        SurfaceType.REST,
        SurfaceType.SIRI,
        SurfaceType.TELEGRAM,
        SurfaceType.CLI,
    ]
    assert agent.calls[2][1] == "nota transcrita"


@pytest.mark.asyncio
async def test_gateway_and_telegram_reject_unauthorized_callers():
    gateway, agent = _gateway()
    with pytest.raises(PermissionError):
        await gateway.handle_inbound_turn("s", "prompt", SurfaceType.REST, "Bearer wrong")
    with pytest.raises(PermissionError):
        await handle_telegram(gateway, "other", "chat", "Bearer secret", text="hola")
    assert agent.calls == []


@pytest.mark.asyncio
async def test_gateway_stream_delivers_turn_and_unsubscribes():
    gateway, _ = _gateway("respuesta completa")
    stream = gateway.subscribe_stream("session")
    pending = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    await gateway.handle_inbound_turn("session", "hola", SurfaceType.REST, "Bearer secret")
    chunk = await pending
    assert chunk.content == "respuesta completa"
    assert chunk.done is True
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    assert gateway._subscribers == {}


@pytest.mark.asyncio
async def test_voice_stt_errors_are_not_sent_to_agent(tmp_path):
    gateway, agent = _gateway()
    (tmp_path / "voice.wav").touch()
    with pytest.raises(RuntimeError, match="VOICE_EXTRA_MISSING"):
        await handle_telegram(
            gateway,
            "42",
            "chat",
            "Bearer secret",
            voice_path=Path(tmp_path / "voice.wav"),
            transcribe=lambda _: {"ok": False, "error": "VOICE_EXTRA_MISSING"},  # type: ignore[arg-type]
        )
    assert agent.calls == []
