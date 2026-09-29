import hashlib
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TurnRequest:
    messages: tuple[dict[str, Any], ...]
    system_prompt_hash: str | None


def assemble_turn_request(
    system_prompt: str | None,
    user_prompt: str,
    *,
    history: list[dict[str, Any]] | None = None,
    ephemeral_messages: list[dict[str, Any]] | None = None,
) -> TurnRequest:
    """Assemble one provider request with a stable system prefix and ephemeral tail."""
    messages: list[dict[str, Any]] = []
    prompt_hash = None
    if system_prompt is not None:
        messages.append({"role": "system", "content": system_prompt})
        prompt_hash = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()

    filtered_history: list[dict[str, Any]] = []
    for item in history or []:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant", "tool"} and content:
            filtered_history.append(dict(item))
    messages.extend(filtered_history)

    for item in ephemeral_messages or []:
        role = item.get("role")
        if role not in {"user", "tool"}:
            raise ValueError("el contexto efímero solo puede usar roles user o tool")
        messages.append(dict(item))

    # Contexto dinámico nunca sustituye el turno real ni contamina el system prompt.
    if not (
        not ephemeral_messages
        and filtered_history
        and filtered_history[-1].get("role") == "user"
        and filtered_history[-1].get("content") == user_prompt
    ):
        messages.append({"role": "user", "content": user_prompt})

    return TurnRequest(messages=tuple(messages), system_prompt_hash=prompt_hash)
