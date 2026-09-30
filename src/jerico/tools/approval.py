from dataclasses import dataclass


@dataclass(frozen=True)
class ToolExecutionContext:
    session_id: str = ""
    confirmed: bool = False


def explicitly_approved(context: ToolExecutionContext) -> bool:
    """Only trusted surface context can carry approval; model arguments cannot."""
    return context.confirmed is True
