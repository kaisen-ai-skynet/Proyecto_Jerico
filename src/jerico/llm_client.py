from typing import Any

from openai import OpenAI

from jerico.config import Settings, get_settings


class LLMClient:
    """Cliente OpenAI-compatible con modelo pinedo por nivel (L1/L2)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = OpenAI(
            base_url=self.settings.llm_base_url,
            api_key=self.settings.llm_api_key,
        )

    def complete(self, prompt: str, *, level: int = 1, system: str | None = None) -> str:
        model = self._model_for_level(level)
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
        )
        content = resp.choices[0].message.content
        return content or ""

    def _model_for_level(self, level: int) -> str:
        if level >= 2:
            return self.settings.llm_model_l2
        return self.settings.llm_model_l1
