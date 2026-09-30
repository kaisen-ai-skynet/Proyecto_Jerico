import asyncio
import inspect
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jerico.agent.types import SurfaceType, ToolsetPosture
from jerico.tools.approval import ToolExecutionContext, explicitly_approved
from jerico.tools.base import BaseTool
from jerico.tools.toolsets import belongs_to_posture


@dataclass
class Registration:
    tool: BaseTool
    check_fn: Callable[[], bool] | None
    ttl: int
    checked_at: float | None = None
    available: bool = False


class ToolRegistry:
    def __init__(self) -> None:
        self.entries: dict[str, Registration] = {}

    def register(
        self, tool: BaseTool, *, check_fn: Callable[[], bool] | None = None, check_ttl_s: int = 300
    ) -> None:
        if check_ttl_s < 0:
            raise ValueError("TTL no puede ser negativo")
        self.entries[tool.name] = Registration(tool, check_fn, check_ttl_s)

    def get(self, name: str) -> BaseTool | None:
        entry = self.entries.get(name)
        if entry is None:
            return None
        if entry.check_fn is None:
            return entry.tool
        now = time.monotonic()
        if entry.checked_at is None or now - entry.checked_at >= entry.ttl:
            try:
                entry.available = entry.check_fn() is True
            except Exception:
                entry.available = False
            entry.checked_at = now
        return entry.tool if entry.available else None

    def resolve_for_session(
        self, posture: ToolsetPosture, surface: SurfaceType
    ) -> list[dict[str, Any]]:
        schemas = []
        for name in sorted(self.entries):
            tool = self.get(name)
            if tool is None or not belongs_to_posture(name, posture, surface):
                continue
            schemas.append(tool_schema(tool))
        return schemas

    async def dispatch(
        self, tool_name: str, arguments: dict[str, Any], context: ToolExecutionContext
    ) -> dict[str, Any]:
        tool = self.get(tool_name)
        if tool is None:
            return {"ok": False, "error": "TOOL_UNAVAILABLE"}
        args = dict(arguments)
        args.pop("confirm", None)
        try:
            return await asyncio.to_thread(tool.run, confirm=explicitly_approved(context), **args)
        except (TypeError, ValueError):
            return {"ok": False, "error": "INVALID_ARGUMENTS"}
        except Exception:
            return {"ok": False, "error": "TOOL_FAILED"}


def tool_schema(tool: BaseTool) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required = []
    types = {str: "string", int: "integer", float: "number", bool: "boolean"}
    for name, parameter in inspect.signature(tool._execute).parameters.items():
        if parameter.kind in {parameter.VAR_KEYWORD, parameter.VAR_POSITIONAL}:
            continue
        properties[name] = {"type": types.get(parameter.annotation, "string")}
        if parameter.default is parameter.empty:
            required.append(name)
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }
