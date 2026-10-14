from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    system_prompt_hash: str
    model: str
    parent_session_id: str | None
    created_at: str
    updated_at: str
    user_id: int | None = None
    role: str | None = None


@dataclass(frozen=True)
class MessageRecord:
    id: int
    session_id: str
    role: str
    content: str
    tool_calls: list[dict[str, Any]] | None
    tool_call_id: str | None
    reasoning: str | None
    created_at: str
