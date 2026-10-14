"""Cliente de la Responses API de OpenAI con transporte simulado (VCRM-A14, A32, A34)."""

import json

import httpx
import pytest

from jerico.crm.llm import LlmError, LlmResult, OpenAIResponsesClient


def _client(handler: httpx.MockTransport | None, **kw: object) -> OpenAIResponsesClient:
    return OpenAIResponsesClient(
        api_key="sk-secret-123",
        model="gpt-6-luna",
        effort="low",
        transport=handler,
        **kw,  # type: ignore[arg-type]
    )


def _ok_body(text: str = "Hola", status: str = "completed") -> dict[str, object]:
    return {
        "status": status,
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": text}]},
        ],
        "usage": {"input_tokens": 120, "output_tokens": 30},
    }


@pytest.mark.asyncio
async def test_vcrma14_request_shape_and_parsing() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_body("Resumen listo"))

    result = await _client(httpx.MockTransport(handler)).complete(
        system="Eres un asistente.", user="Resume.", max_output_tokens=300
    )
    assert result == LlmResult(text="Resumen listo", input_tokens=120, output_tokens=30)
    assert seen["url"] == "https://api.openai.com/v1/responses"
    assert seen["auth"] == "Bearer sk-secret-123"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["model"] == "gpt-6-luna"
    assert body["reasoning"] == {"effort": "low"}
    assert body["max_output_tokens"] == 300
    assert body["store"] is False
    assert body["instructions"] == "Eres un asistente."
    assert body["input"] == "Resume."
    assert "user" not in body  # sin identificadores de usuario


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(401, json={"error": {"message": "bad key sk-secret-123"}}), "http"),
        (httpx.Response(500, text="boom"), "http"),
        (httpx.Response(200, text="no es json"), "bad_response"),
        (httpx.Response(200, json=[1, 2]), "bad_response"),
        (
            httpx.Response(200, json={"output": ["x", {"type": "message", "content": ["y"]}]}),
            "empty",
        ),
        (httpx.Response(200, json={"status": "completed", "output": []}), "empty"),
        (httpx.Response(200, json=_ok_body("  ")), "empty"),
        (
            httpx.Response(
                200,
                json={
                    "status": "completed",
                    "output": [
                        {"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}
                    ],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            ),
            "refused",
        ),
    ],
)
async def test_vcrma32_failures_raise_closed_codes_without_leaking_secrets(
    response: httpx.Response, code: str
) -> None:
    client = _client(httpx.MockTransport(lambda _request: response))
    with pytest.raises(LlmError) as info:
        await client.complete(system="s", user="u", max_output_tokens=100)
    assert info.value.code == code
    assert "sk-secret-123" not in str(info.value) and "sk-secret-123" not in repr(info.value)


@pytest.mark.asyncio
async def test_vcrma32_timeout_and_network_errors_map_to_codes() -> None:
    def timeout(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    def down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(LlmError) as t:
        await _client(httpx.MockTransport(timeout)).complete(
            system="s", user="u", max_output_tokens=9
        )
    assert t.value.code == "timeout"
    with pytest.raises(LlmError) as n:
        await _client(httpx.MockTransport(down)).complete(system="s", user="u", max_output_tokens=9)
    assert n.value.code == "network"


@pytest.mark.asyncio
async def test_incomplete_with_text_is_returned_and_flagged() -> None:
    client = _client(
        httpx.MockTransport(lambda _r: httpx.Response(200, json=_ok_body("parcial", "incomplete")))
    )
    result = await client.complete(system="s", user="u", max_output_tokens=10)
    assert result.text == "parcial" and result.truncated is True


def test_vcrma34_repr_hides_the_key() -> None:
    assert "sk-secret-123" not in repr(_client(None))
