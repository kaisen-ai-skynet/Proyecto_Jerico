from types import SimpleNamespace
from typing import Any

import pytest

from jerico.config import Settings
from jerico.llm.token_accounting import TokenUsage, extract_token_usage
from jerico.llm.tool_calls import ToolCallRequest
from jerico.llm_client import AsyncLLMClient, LLMError


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            SimpleNamespace(
                usage=SimpleNamespace(
                    prompt_tokens=100,
                    completion_tokens=40,
                    prompt_tokens_details=SimpleNamespace(cached_tokens=75),
                    completion_tokens_details=SimpleNamespace(reasoning_tokens=12),
                )
            ),
            TokenUsage(100, 40, 75, 12),
        ),
        (
            {"usage": {"prompt_tokens": 25, "completion_tokens": 7, "cached_tokens": 4}},
            TokenUsage(25, 7, 4, 0),
        ),
        (
            {
                "usage": {
                    "input_tokens_details": {"cached_tokens": 3},
                    "completion_tokens_details": {"reasoning_tokens": 2},
                }
            },
            TokenUsage(0, 0, 3, 2),
        ),
        (
            {"usage": {"cache_read_input_tokens": 8, "prompt_tokens": -2}},
            TokenUsage(0, 0, 8, 0),
        ),
        (SimpleNamespace(usage=None), TokenUsage()),
        ({"usage": {"prompt_tokens": "invalid", "completion_tokens": None}}, TokenUsage()),
    ],
)
def test_extrae_usage_y_tokens_cache_de_varios_formatos(response: Any, expected: TokenUsage):
    assert extract_token_usage(response) == expected


class FakeCompletions:
    def __init__(self, response: Any | None = None) -> None:
        self.kwargs: dict[str, Any] = {}
        self.response = response

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if self.response is not None:
            return self.response
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="respuesta"))],
            usage=SimpleNamespace(
                prompt_tokens=11,
                completion_tokens=6,
                prompt_tokens_details=SimpleNamespace(cached_tokens=7),
            ),
        )


@pytest.mark.asyncio
async def test_cliente_expone_usage_sin_mutar_prefijo_del_system():
    settings = Settings(
        llm_base_url="http://localhost/v1",
        llm_api_key="test",
        llm_model_l1="model",
        _env_file=None,
    )
    client = AsyncLLMClient(settings)
    completions = FakeCompletions()
    fake: Any = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client._client_for = lambda _level: (fake, "model")  # type: ignore[method-assign]

    result = await client.complete_with_usage(
        "pregunta",
        system="prompt inmutable",
        ephemeral_messages=[{"role": "user", "content": "fecha dinámica"}],
    )

    assert result.content == "respuesta"
    assert result.usage == TokenUsage(11, 6, 7, 0)
    assert completions.kwargs["messages"][0] == {
        "role": "system",
        "content": "prompt inmutable",
    }
    assert completions.kwargs["messages"][1] == {
        "role": "user",
        "content": "fecha dinámica",
    }


@pytest.mark.asyncio
async def test_cliente_parsea_tool_calls_del_proveedor():
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="",
                    tool_calls=[
                        SimpleNamespace(
                            id="call-1",
                            function=SimpleNamespace(name="lookup", arguments='{"q":"x"}'),
                        )
                    ],
                )
            )
        ],
        usage=None,
    )
    settings = Settings(llm_base_url="http://localhost/v1", llm_api_key="k", _env_file=None)
    client = AsyncLLMClient(settings)
    completions = FakeCompletions(response)
    fake: Any = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client._client_for = lambda _level: (fake, "model")  # type: ignore[method-assign]
    result = await client.complete_messages_with_usage(
        [{"role": "user", "content": "look up"}],
        level=1,
        tools=[{"type": "function", "function": {"name": "lookup"}}],
    )
    assert result.tool_calls == (ToolCallRequest("call-1", "lookup", {"q": "x"}),)
    assert completions.kwargs["tools"][0]["function"]["name"] == "lookup"


@pytest.mark.asyncio
async def test_cliente_rechaza_tool_arguments_invalidos():
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="",
                    tool_calls=[
                        SimpleNamespace(
                            id="call-1",
                            function=SimpleNamespace(name="lookup", arguments="[]"),
                        )
                    ],
                )
            )
        ]
    )
    settings = Settings(llm_base_url="http://localhost/v1", llm_api_key="k", _env_file=None)
    client = AsyncLLMClient(settings)
    client._client_for = lambda _level: (  # type: ignore[method-assign]
        SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions(response))),
        "model",
    )
    with pytest.raises(LLMError, match="tool calls inválidas"):
        await client.complete_messages_with_usage([{"role": "user", "content": "x"}])
