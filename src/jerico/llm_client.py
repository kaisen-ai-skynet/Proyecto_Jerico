from typing import Any

from openai import APIError, AsyncOpenAI

from jerico.agent.turn_request_assembly import assemble_turn_request
from jerico.config import Settings, get_settings
from jerico.llm.token_accounting import LLMCompletion, extract_token_usage


class LLMError(RuntimeError):
    """Fallo del proveedor (red, timeout, HTTP, respuesta sin choices)."""


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
    ) -> str:
        result = await self.complete_with_usage(
            prompt,
            level=level,
            system=system,
            history=history,
            ephemeral_messages=ephemeral_messages,
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
    ) -> LLMCompletion:
        if level <= 0:
            raise ValueError("nivel 0 se responde local; no se llama al LLM")
        client, model = self._client_for(level)
        request = assemble_turn_request(
            system,
            prompt,
            history=history,
            ephemeral_messages=ephemeral_messages,
        )
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=list(request.messages),  # type: ignore[arg-type]
                temperature=0.2,
            )
        except APIError as exc:
            raise LLMError(f"{type(exc).__name__} en L{level} ({model})") from exc
        if not resp.choices:
            raise LLMError(f"respuesta sin choices en L{level} ({model})")
        return LLMCompletion(
            content=resp.choices[0].message.content or "",
            usage=extract_token_usage(resp),
        )

    def _client_for(self, level: int) -> tuple[AsyncOpenAI, str]:
        base, key, model = self.settings.endpoint_for(level)
        client = self._clients.get((base, key))
        if client is None:
            client = AsyncOpenAI(
                base_url=base,
                api_key=key,
                timeout=self.settings.llm_timeout_s,
                max_retries=self.settings.llm_max_retries,
            )
            self._clients[(base, key)] = client
        return client, model
