from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from jerico.llm.tool_calls import ToolCallRequest


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0


@dataclass(frozen=True)
class LLMCompletion:
    content: str
    usage: TokenUsage
    tool_calls: tuple[ToolCallRequest, ...] = ()


def extract_token_usage(response: Any) -> TokenUsage:
    usage = _value(response, "usage")
    if usage is None:
        return TokenUsage()
    prompt_details = _value(usage, "prompt_tokens_details")
    input_details = _value(usage, "input_tokens_details")
    completion_details = _value(usage, "completion_tokens_details")
    cached = _value(prompt_details, "cached_tokens")
    if cached is None:
        cached = _value(input_details, "cached_tokens")
    if cached is None:
        cached = _value(usage, "cached_tokens")
    if cached is None:
        cached = _value(usage, "cache_read_input_tokens")
    reasoning = _value(completion_details, "reasoning_tokens")
    return TokenUsage(
        prompt_tokens=_nonnegative_int(_value(usage, "prompt_tokens")),
        completion_tokens=_nonnegative_int(_value(usage, "completion_tokens")),
        cached_tokens=_nonnegative_int(cached),
        reasoning_tokens=_nonnegative_int(reasoning),
    )


def _value(source: Any, key: str) -> Any:
    if isinstance(source, Mapping):
        return source.get(key)
    return getattr(source, key, None)


def _nonnegative_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, parsed)
