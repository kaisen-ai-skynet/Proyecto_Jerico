import asyncio
from collections.abc import Callable
from typing import Any

from jerico.agent.compression import summary_as_context
from jerico.agent.prompt_builder import PromptBuilder
from jerico.agent.turn_api_call import TurnApiCaller
from jerico.agent.turn_context_compaction import ContextCompactor
from jerico.agent.turn_finalizer import TurnFinalizer
from jerico.agent.turn_preflight import SessionLease, TurnPreflightGate
from jerico.agent.turn_recovery import MAX_ITERATIONS, exhausted_iterations_answer
from jerico.agent.turn_request_assembly import validate_role_alternation
from jerico.agent.turn_tool_round import TurnToolRound
from jerico.agent.types import (
    SurfaceType,
    TokenPressureLevel,
    ToolsetPosture,
    TurnResult,
)
from jerico.llm.token_accounting import TokenUsage
from jerico.llm_client import AsyncLLMClient, LLMError
from jerico.router import TokenRouter
from jerico.state import StateEngine
from jerico.state.messages import MessageRecord


class AgentTurnLoop:
    """Facade for a bounded, persistent and interruptible agent turn."""

    def __init__(
        self,
        state: StateEngine,
        llm: AsyncLLMClient,
        *,
        router: TokenRouter | None = None,
        prompt_builder: PromptBuilder | None = None,
        preflight: TurnPreflightGate | None = None,
        tool_round: TurnToolRound | None = None,
        api_caller: TurnApiCaller | None = None,
        max_iterations: int = MAX_ITERATIONS,
        window_limit: int = 128_000,
    ) -> None:
        if max_iterations < 1:
            raise ValueError("max_iterations debe ser al menos 1")
        if window_limit < 1:
            raise ValueError("window_limit debe ser positivo")
        self.state = state
        self.llm = llm
        self.router = router or TokenRouter()
        # No system persona is invented: deployments can inject the CTO-approved prompt.
        self.prompt_builder = prompt_builder or PromptBuilder("")
        self.preflight = preflight or TurnPreflightGate(state)
        self.tool_round = tool_round or TurnToolRound()
        self.api_caller = api_caller or TurnApiCaller(llm)
        self.compactor = ContextCompactor(llm)
        self.max_iterations = max_iterations
        self.window_limit = window_limit
        self._active_tasks: dict[str, asyncio.Task[Any]] = {}
        self._token_estimator: Callable[[str], int] = _estimate_tokens
        self._last_compaction: Any | None = None

    async def run_turn(
        self,
        session_id: str,
        user_prompt: str,
        *,
        task_id: str | None = None,
        posture: ToolsetPosture = ToolsetPosture.DEFAULT,
        surface: SurfaceType = SurfaceType.REST,
    ) -> TurnResult:
        del task_id  # carried by the facade for gateway correlation in a later phase
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("run_turn debe ejecutarse dentro de asyncio")
        self._active_tasks[session_id] = task
        lease: SessionLease | None = None
        try:
            lease = await self.preflight.acquire_lease(session_id)
            decision = self.router.route(user_prompt)
            await asyncio.to_thread(
                self.prompt_builder.bind_session,
                self.state,
                session_id,
                decision.model,
            )
            history_records = await asyncio.to_thread(self.state.get_session_transcript, session_id)
            history = _provider_history(history_records)
            history_tokens = sum(
                self._token_estimator(str(item.get("content", ""))) for item in history
            )
            self.preflight.evaluate_token_pressure(
                session_id,
                history_tokens,
                self.window_limit,
            )
            if decision.answer is not None:
                return await TurnFinalizer(self.state).finalize(
                    session_id=session_id,
                    user_prompt=user_prompt,
                    answer=decision.answer,
                    level=decision.level,
                    model=decision.model,
                    iterations=0,
                    usage=TokenUsage(),
                )

            ephemeral_messages: list[dict[str, Any]] = []
            if self.compactor.should_compact(history_tokens, self.window_limit):
                compacted = await self.compactor.compact(
                    session_id,
                    history,
                    preserve_tail_turns=5,
                    preserve_last_n=10,
                )
                history = compacted.messages
                if compacted.summarized and compacted.summary is not None:
                    ephemeral_messages.append(
                        {
                            "role": "user",
                            "content": summary_as_context(compacted.summary),
                        }
                    )
                history_tokens = sum(
                    self._token_estimator(str(item.get("content", ""))) for item in history
                )
                self._last_compaction = compacted
                if (
                    self.preflight.evaluate_token_pressure(
                        session_id,
                        history_tokens,
                        self.window_limit,
                    )
                    is TokenPressureLevel.OVERFLOW
                ):
                    raise LLMError("historial supera la ventana de contexto tras compactar")

            effective_prompt = user_prompt
            if ephemeral_messages:
                effective_prompt = (
                    str(ephemeral_messages[0]["content"])
                    + "\n\nPregunta original del usuario:\n"
                    + user_prompt
                )
            request = self.prompt_builder.assemble(
                effective_prompt,
                history=history,
            )
            messages = [dict(message) for message in request.messages]
            usage = TokenUsage()
            tool_results: list[dict[str, Any]] = []
            user_persisted = False
            tool_schemas = self.tool_round.provider_schemas(posture=posture, surface=surface)

            for iteration in range(1, self.max_iterations + 1):
                try:
                    validate_role_alternation(messages)
                except ValueError as exc:
                    raise LLMError(f"historial inválido: {exc}") from exc
                completion = await self.api_caller.call(
                    messages,
                    level=decision.level,
                    tools=tool_schemas,
                )
                usage = _sum_usage(usage, completion.usage)
                if not completion.tool_calls:
                    if not completion.content:
                        raise LLMError("respuesta del proveedor vacía")
                    return await TurnFinalizer(self.state).finalize(
                        session_id=session_id,
                        user_prompt=user_prompt,
                        answer=completion.content,
                        level=decision.level,
                        model=decision.model,
                        iterations=iteration,
                        usage=usage,
                        tool_results=tuple(tool_results),
                        user_message_persisted=user_persisted,
                    )

                if iteration == self.max_iterations:
                    break
                outcome = await self.tool_round.execute(completion.tool_calls)
                assistant_message: dict[str, object] = {
                    "role": "assistant",
                    "content": completion.content,
                    "tool_calls": outcome.assistant_tool_calls,
                }
                round_messages: list[dict[str, object]] = []
                needs_user_message = not user_persisted
                if needs_user_message:
                    round_messages.append({"role": "user", "content": user_prompt})
                round_messages.append(assistant_message)
                for tool_message in outcome.tool_messages:
                    round_messages.append(dict(tool_message))
                await asyncio.to_thread(self.state.append_messages, session_id, round_messages)
                messages.extend(
                    dict(message)
                    for message in (round_messages[1:] if needs_user_message else round_messages)
                )
                user_persisted = True
                tool_results.extend(outcome.results)

            return await TurnFinalizer(self.state).finalize(
                session_id=session_id,
                user_prompt=user_prompt,
                answer=exhausted_iterations_answer(),
                level=decision.level,
                model=decision.model,
                iterations=self.max_iterations,
                usage=usage,
                tool_results=tuple(tool_results),
                user_message_persisted=user_persisted,
            )
        finally:
            if lease is not None:
                await self.preflight.release_lease(lease)
            if self._active_tasks.get(session_id) is task:
                self._active_tasks.pop(session_id, None)

    def request_interrupt(self, session_id: str) -> bool:
        task = self._active_tasks.get(session_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True


def _provider_history(records: list[MessageRecord]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for record in records:
        message: dict[str, Any] = {"role": record.role, "content": record.content}
        if record.tool_calls is not None:
            message["tool_calls"] = record.tool_calls
        if record.tool_call_id is not None:
            message["tool_call_id"] = record.tool_call_id
        messages.append(message)
    return messages


def _estimate_tokens(text: str) -> int:
    return (len(text) + 3) // 4


def _sum_usage(left: TokenUsage, right: TokenUsage) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=left.prompt_tokens + right.prompt_tokens,
        completion_tokens=left.completion_tokens + right.completion_tokens,
        cached_tokens=left.cached_tokens + right.cached_tokens,
        reasoning_tokens=left.reasoning_tokens + right.reasoning_tokens,
    )
