import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolCallRequest:
    call_id: str
    name: str
    arguments: dict[str, Any]

    def to_provider_payload(self) -> dict[str, Any]:
        return {
            "id": self.call_id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False, sort_keys=True),
            },
        }


def extract_tool_calls(response: Any) -> tuple[ToolCallRequest, ...]:
    if not response.choices:
        return ()
    raw_calls = getattr(response.choices[0].message, "tool_calls", None) or ()
    calls: list[ToolCallRequest] = []
    for raw in raw_calls:
        function = getattr(raw, "function", None)
        call_id = getattr(raw, "id", None)
        name = getattr(function, "name", None)
        raw_arguments = getattr(function, "arguments", "{}")
        if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
            raise ValueError("tool call sin id o nombre")
        arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
        if not isinstance(arguments, dict):
            raise ValueError("tool call arguments debe ser un objeto JSON")
        calls.append(ToolCallRequest(call_id, name, arguments))
    return tuple(calls)
