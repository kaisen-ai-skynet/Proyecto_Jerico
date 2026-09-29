from typing import Any

from openai import OpenAI

from jerico.config import Settings, get_settings


class LLMClient:
    """Cliente OpenAI-compatible. Un gateway compartido o credenciales por nivel."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._clients: dict[tuple[str, str], OpenAI] = {}

    def complete(
        self,
        prompt: str,
        *,
        level: int = 1,
        system: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        client, model = self._client_for(level)
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        for item in history or []:
            role = item.get("role", "")
            content = item.get("content", "")
            if role in {"user", "assistant", "system"} and content:
                messages.append({"role": role, "content": content})
        if not messages or messages[-1].get("content") != prompt:
            messages.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(model=model, messages=messages, temperature=0.2)  # type: ignore[arg-type]
        return resp.choices[0].message.content or ""

    def _client_for(self, level: int) -> tuple[OpenAI, str]:
        base, key, model = self.settings.endpoint_for(level)
        client = self._clients.get((base, key))
        if client is None:
            client = OpenAI(
                base_url=base,
                api_key=key,
                timeout=self.settings.llm_timeout_s,
                max_retries=self.settings.llm_max_retries,
            )
            self._clients[(base, key)] = client
        return client, model
