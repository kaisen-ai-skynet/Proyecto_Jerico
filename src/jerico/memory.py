from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class Session:
    session_id: str
    messages: list[dict[str, str]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class MemoryManager:
    """Memoria de corto plazo. v0: en proceso; Fase 3: Redis con TTL 24h."""

    def __init__(self, max_messages: int = 20) -> None:
        self._max_messages = max_messages
        self._sessions: dict[str, Session] = {}

    def get(self, session_id: str) -> Session:
        if session_id not in self._sessions:
            self._sessions[session_id] = Session(session_id=session_id)
        return self._sessions[session_id]

    def append(self, session_id: str, role: str, content: str) -> None:
        session = self.get(session_id)
        session.messages.append({"role": role, "content": content})
        if len(session.messages) > self._max_messages:
            session.messages = session.messages[-self._max_messages :]

    def context(self, session_id: str) -> list[dict[str, str]]:
        return list(self.get(session_id).messages)

    def clear(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


memory = MemoryManager()
