import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from jerico.state.messages import SessionRecord

if TYPE_CHECKING:
    from jerico.agent.turn_request_assembly import TurnRequest
    from jerico.state import StateEngine


@dataclass(frozen=True)
class SystemPromptSnapshot:
    content: str
    sha256: str

    @classmethod
    def from_content(cls, content: str) -> "SystemPromptSnapshot":
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return cls(content=content, sha256=digest)


@dataclass(frozen=True, init=False)
class PromptBuilder:
    """Holds one immutable system prompt and binds it to a durable session."""

    snapshot: SystemPromptSnapshot

    def __init__(self, system_prompt: str) -> None:
        object.__setattr__(self, "snapshot", SystemPromptSnapshot.from_content(system_prompt))

    @property
    def system_prompt(self) -> str:
        return self.snapshot.content

    @property
    def prompt_hash(self) -> str:
        return self.snapshot.sha256

    def bind_session(
        self,
        state: "StateEngine",
        session_id: str,
        model: str,
        parent_session_id: str | None = None,
    ) -> SessionRecord:
        session = state.get_or_create_session(
            session_id,
            self.snapshot.content,
            model,
            parent_session_id,
        )
        if session.system_prompt_hash != self.snapshot.sha256:
            raise ValueError("system prompt hash no coincide con la sesión")
        return session

    def assemble(
        self,
        user_prompt: str,
        *,
        history: list[dict[str, Any]] | None = None,
        ephemeral_messages: list[dict[str, Any]] | None = None,
    ) -> "TurnRequest":
        from jerico.agent.turn_request_assembly import assemble_turn_request

        return assemble_turn_request(
            self.snapshot.content,
            user_prompt,
            history=history,
            ephemeral_messages=ephemeral_messages,
        )
