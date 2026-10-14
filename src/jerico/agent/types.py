from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from jerico.llm.token_accounting import TokenUsage


class ToolsetPosture(StrEnum):
    CODING = "coding"
    OPS = "ops"
    PERSONAL = "personal"
    DEFAULT = "default"


class SurfaceType(StrEnum):
    REST = "rest"
    CLI = "cli"
    TELEGRAM = "telegram"
    SIRI = "siri"
    WEB = "web"


class TokenPressureLevel(StrEnum):
    LOW = "low"
    ELEVATED = "elevated"
    OVERFLOW = "overflow"


@dataclass(frozen=True)
class TurnResult:
    session_id: str
    answer: str
    level: int
    model: str
    iterations: int
    usage: TokenUsage = field(default_factory=TokenUsage)
    tool_results: tuple[dict[str, Any], ...] = ()
