import asyncio
import secrets
from collections.abc import Awaitable, Callable
from typing import Any

from jerico.llm.token_accounting import LLMCompletion
from jerico.llm_client import AsyncLLMClient, LLMError


class TurnApiCaller:
    """Interruptible LLM calls with a bounded exponential retry ladder."""

    def __init__(
        self,
        client: AsyncLLMClient,
        *,
        max_retries: int = 2,
        base_delay_s: float = 0.1,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = lambda: secrets.SystemRandom().uniform(0.75, 1.25),
    ) -> None:
        if max_retries < 0 or base_delay_s < 0:
            raise ValueError("retries y backoff no pueden ser negativos")
        self.client = client
        self.max_retries = max_retries
        self.base_delay_s = base_delay_s
        self.sleep = sleep
        self.jitter = jitter

    async def call(
        self,
        messages: list[dict[str, Any]],
        *,
        level: int,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMCompletion:
        for attempt in range(self.max_retries + 1):
            try:
                return await self.client.complete_messages_with_usage(
                    messages,
                    level=level,
                    tools=tools,
                )
            except LLMError as exc:
                if not exc.retryable or attempt == self.max_retries:
                    raise
                delay = self.base_delay_s * (2**attempt) * max(0.0, self.jitter())
                await self.sleep(delay)
        raise AssertionError("retry loop terminó sin respuesta ni excepción")
