import time
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class Session:
    session_id: str
    messages: list[dict[str, str]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class MemoryManager:
    """Memoria de corto plazo en proceso, con TTL y tope de sesiones."""

    def __init__(
        self,
        max_messages: int = 20,
        ttl_seconds: int = 24 * 3600,
        max_sessions: int = 100,
    ) -> None:
        self._max_messages = max_messages
        self._ttl_seconds = ttl_seconds
        self._max_sessions = max_sessions
        self._sessions: dict[str, Session] = {}
        self._seen: dict[str, float] = {}

    def get(self, session_id: str) -> Session:
        self._purge()
        if session_id not in self._sessions:
            self._evict_if_needed()
            self._sessions[session_id] = Session(session_id=session_id)
        self._seen[session_id] = time.monotonic()
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
        self._seen.pop(session_id, None)

    def clear_all(self) -> None:
        self._sessions.clear()
        self._seen.clear()

    def _purge(self) -> None:
        if self._ttl_seconds <= 0:
            return
        now = time.monotonic()
        expired = [sid for sid, seen in self._seen.items() if now - seen > self._ttl_seconds]
        for sid in expired:
            self.clear(sid)

    def _evict_if_needed(self) -> None:
        while len(self._sessions) >= self._max_sessions and self._seen:
            oldest = min(self._seen, key=self._seen.__getitem__)
            self.clear(oldest)


memory = MemoryManager()
