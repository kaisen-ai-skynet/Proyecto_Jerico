import asyncio
from typing import Any

from jerico.agent.types import TurnResult
from jerico.llm.token_accounting import TokenUsage
from jerico.state import StateEngine


class TurnFinalizer:
    def __init__(self, state: StateEngine) -> None:
        self.state = state

    async def finalize(
        self,
        *,
        session_id: str,
        user_prompt: str,
        answer: str,
        level: int,
        model: str,
        iterations: int,
        usage: TokenUsage,
        tool_results: tuple[dict[str, Any], ...] = (),
        user_message_persisted: bool = False,
    ) -> TurnResult:
        messages: list[dict[str, object]] = []
        if not user_message_persisted:
            messages.append({"role": "user", "content": user_prompt})
        messages.append({"role": "assistant", "content": answer})
        await asyncio.to_thread(self.state.append_messages, session_id, messages)
        if usage.prompt_tokens or usage.completion_tokens or usage.cached_tokens:
            await asyncio.to_thread(
                self.state.record_usage,
                session_id,
                model,
                usage.prompt_tokens,
                usage.completion_tokens,
                usage.cached_tokens,
            )
        return TurnResult(
            session_id=session_id,
            answer=answer,
            level=level,
            model=model,
            iterations=iterations,
            usage=usage,
            tool_results=tool_results,
        )
