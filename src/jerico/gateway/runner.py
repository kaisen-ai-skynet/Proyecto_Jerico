import asyncio
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass

from jerico.agent.conversation_loop import AgentTurnLoop
from jerico.agent.types import SurfaceType, ToolsetPosture, TurnResult
from jerico.config import Settings, token_configured


@dataclass(frozen=True)
class InboundTurnResponse:
    answer: str
    result: TurnResult


@dataclass(frozen=True)
class StreamChunk:
    content: str
    done: bool = False


class OmniGateway:
    def __init__(self, agent: AgentTurnLoop, settings: Settings) -> None:
        self.agent = agent
        self.settings = settings
        self._subscribers: dict[str, set[asyncio.Queue[StreamChunk]]] = {}

    async def handle_inbound_turn(
        self, session_id: str, user_prompt: str, surface: SurfaceType, authorization: str
    ) -> InboundTurnResponse:
        expected = f"Bearer {self.settings.api_token}"
        if not token_configured(self.settings.api_token) or not secrets.compare_digest(
            expected.encode(), authorization.encode()
        ):
            raise PermissionError("unauthorized")
        result = await self.agent.run_turn(
            session_id, user_prompt, surface=surface, posture=ToolsetPosture.DEFAULT
        )
        for queue in self._subscribers.get(session_id, set()):
            queue.put_nowait(StreamChunk(result.answer, done=True))
        return InboundTurnResponse(result.answer, result)

    async def subscribe_stream(self, session_id: str) -> AsyncIterator[StreamChunk]:
        """Subscribe to completed turn responses for a session until cancelled."""
        queue: asyncio.Queue[StreamChunk] = asyncio.Queue()
        subscribers = self._subscribers.setdefault(session_id, set())
        subscribers.add(queue)
        try:
            while True:
                chunk = await queue.get()
                yield chunk
                if chunk.done:
                    return
        finally:
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(session_id, None)
