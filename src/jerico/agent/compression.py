import json
from typing import Any

SUMMARY_SYSTEM_PROMPT = (
    "Resume el historial proporcionado en JSON válido con las claves "
    "active_goals, agreements, security_constraints, decisions y open_questions; "
    "cada valor debe ser una lista de strings. No inventes datos."
)
SUMMARY_KEYS = (
    "active_goals",
    "agreements",
    "security_constraints",
    "decisions",
    "open_questions",
)


def parse_structured_summary(raw: str) -> dict[str, list[str]]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    parsed: Any = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("summary debe ser un objeto JSON")
    normalized: dict[str, list[str]] = {}
    for key in SUMMARY_KEYS:
        value = parsed.get(key, [])
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError(f"summary.{key} debe ser una lista de strings")
        normalized[key] = value
    return normalized


def summary_as_context(summary: dict[str, list[str]]) -> str:
    encoded = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    return (
        f"[Resumen estructurado del historial previo; conserva seguridad y directivas]\n{encoded}"
    )
