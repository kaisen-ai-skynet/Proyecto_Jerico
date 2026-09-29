import asyncio
import json
from dataclasses import dataclass
from typing import Any

from jerico.agent.types import SurfaceType, ToolsetPosture
from jerico.llm.tool_calls import ToolCallRequest
from jerico.tools import REGISTRY
from jerico.tools.base import BaseTool


@dataclass(frozen=True)
class ToolRoundOutcome:
    assistant_tool_calls: list[dict[str, Any]]
    tool_messages: tuple[dict[str, Any], ...]
    results: tuple[dict[str, Any], ...]


class TurnToolRound:
    """Validate and dispatch one model-proposed tool round."""

    def __init__(self, registry: dict[str, BaseTool] | None = None) -> None:
        self.registry = registry if registry is not None else REGISTRY

    def provider_schemas(
        self,
        *,
        posture: ToolsetPosture = ToolsetPosture.DEFAULT,
        surface: SurfaceType = SurfaceType.REST,
    ) -> list[dict[str, Any]]:
        del posture, surface  # posture-aware filtering is introduced with the toolset registry
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.description or f"Jerico tool: {name}",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": True,
                    },
                },
            }
            for name, tool in sorted(self.registry.items())
        ]

    async def execute(self, calls: tuple[ToolCallRequest, ...]) -> ToolRoundOutcome:
        messages: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        for call in calls:
            result = await self._execute_one(call)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.call_id,
                    "content": json.dumps(result, ensure_ascii=False, sort_keys=True, default=str),
                }
            )
            results.append({"tool_call_id": call.call_id, "name": call.name, **result})
        return ToolRoundOutcome(
            assistant_tool_calls=[call.to_provider_payload() for call in calls],
            tool_messages=tuple(messages),
            results=tuple(results),
        )

    async def _execute_one(self, call: ToolCallRequest) -> dict[str, Any]:
        tool = self.registry.get(call.name)
        if tool is None:
            return {"ok": False, "error": "UNKNOWN_TOOL"}
        arguments = dict(call.arguments)
        # Approval can never be self-granted by the model's tool arguments.
        arguments.pop("confirm", None)
        try:
            if not tool.readonly:
                result = await asyncio.to_thread(tool.run, confirm=False, **arguments)
            else:
                result = await asyncio.to_thread(tool.run, **arguments)
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": "INVALID_ARGUMENTS", "message": str(exc)}
        except Exception as exc:  # pragma: no cover - concrete tool failures are provider-specific
            return {"ok": False, "error": "TOOL_FAILED", "message": type(exc).__name__}
        return dict(result)
