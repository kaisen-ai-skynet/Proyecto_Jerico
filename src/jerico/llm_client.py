from typing import Any

from openai import APIConnectionError, APIError, APITimeoutError, AsyncOpenAI, RateLimitError

from jerico.agent.turn_request_assembly import assemble_turn_request
from jerico.config import Settings, get_settings
from jerico.llm.token_accounting import LLMCompletion, extract_token_usage
from jerico.llm.tool_calls import extract_tool_calls


class LLMError(RuntimeError):
    """Fallo del proveedor (red, timeout, HTTP, respuesta sin choices)."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class AsyncLLMClient:
    """Cliente OpenAI-compatible asíncrono, compartido por endpoint y credenciales."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._clients: dict[tuple[str, str], AsyncOpenAI] = {}

    async def complete(
        self,
        prompt: str,
        *,
        level: int = 1,
        system: str | None = None,
        history: list[dict[str, str]] | None = None,
        ephemeral_messages: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        model_override: str | None = None,
    ) -> str:
        result = await self.complete_with_usage(
            prompt,
            level=level,
            system=system,
            history=history,
            ephemeral_messages=ephemeral_messages,
            tools=tools,
            model_override=model_override,
        )
        return result.content

    async def complete_with_usage(
        self,
        prompt: str,
        *,
        level: int = 1,
        system: str | None = None,
        history: list[dict[str, str]] | None = None,
        ephemeral_messages: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        model_override: str | None = None,
    ) -> LLMCompletion:
        request = assemble_turn_request(
            system,
            prompt,
            history=history,
            ephemeral_messages=ephemeral_messages,
        )
        return await self.complete_messages_with_usage(
            list(request.messages),
            level=level,
            tools=tools,
            model_override=model_override,
        )

    async def complete_messages_with_usage(
        self,
        messages: list[dict[str, Any]],
        *,
        level: int = 1,
        tools: list[dict[str, Any]] | None = None,
        model_override: str | None = None,
    ) -> LLMCompletion:
        if level <= 0:
            raise ValueError("nivel 0 se responde local; no se llama al LLM")
        client, model = self._client_for(level)
        model = model_override or model
        request: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0.2}
        if tools is not None:
            request["tools"] = tools
        try:
            resp = await client.chat.completions.create(**request)
        except APIError as exc:
            status_code = getattr(exc, "status_code", None)
            retryable = isinstance(exc, (APIConnectionError, APITimeoutError, RateLimitError)) or (
                isinstance(status_code, int) and status_code >= 500
            )
            raise LLMError(
                f"{type(exc).__name__} en L{level} ({model})", retryable=retryable
            ) from exc
        if not resp.choices:
            raise LLMError(f"respuesta sin choices en L{level} ({model})")
        try:
            tool_calls = extract_tool_calls(resp)
        except (TypeError, ValueError) as exc:
            raise LLMError(f"tool calls inválidas en L{level} ({model})") from exc
        return LLMCompletion(
            content=resp.choices[0].message.content or "",
            usage=extract_token_usage(resp),
            tool_calls=tool_calls,
        )

    def _client_for(self, level: int) -> tuple[AsyncOpenAI, str]:
        base, key, model = self.settings.endpoint_for(level)
        client = self._clients.get((base, key))
        if client is None:
            client = AsyncOpenAI(
                base_url=base,
                api_key=key,
                timeout=self.settings.llm_timeout_s,
                max_retries=0,
            )
            self._clients[(base, key)] = client
        return client, model
