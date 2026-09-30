import json
from typing import Any

import pytest

from jerico.agent.compression import parse_structured_summary, summary_as_context
from jerico.agent.turn_context_compaction import ContextCompactor
from jerico.llm.token_accounting import LLMCompletion, TokenUsage
from jerico.llm_client import LLMError

SUMMARY = {
    "active_goals": ["conservar historial"],
    "agreements": ["usar SQLite"],
    "security_constraints": ["nunca revelar token"],
    "decisions": ["WAL"],
    "open_questions": ["Tailscale"],
}


class SummaryLLM:
    def __init__(self, content: str | Exception) -> None:
        self.content = content
        self.calls: list[dict[str, Any]] = []

    async def complete_with_usage(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        if isinstance(self.content, Exception):
            raise self.content
        return LLMCompletion(self.content, TokenUsage(10, 5, 4, 1))


def _history(turns: int = 12) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": "stable"}]
    for index in range(turns):
        messages.extend(
            [
                {"role": "user", "content": f"question {index}"},
                {"role": "assistant", "content": f"answer {index}"},
            ]
        )
    return messages


def test_parsea_summary_estricto_y_normaliza_campos_faltantes():
    assert parse_structured_summary(json.dumps(SUMMARY)) == SUMMARY
    assert parse_structured_summary("```json\n{}\n```") == {
        "active_goals": [],
        "agreements": [],
        "security_constraints": [],
        "decisions": [],
        "open_questions": [],
    }
    with pytest.raises(ValueError):
        parse_structured_summary("[]")
    with pytest.raises(ValueError):
        parse_structured_summary('{"active_goals":"string"}')
    with pytest.raises(json.JSONDecodeError):
        parse_structured_summary("not json")


@pytest.mark.asyncio
async def test_compactacion_preserva_system_y_ultimos_diez_mensajes_exactos():
    llm = SummaryLLM(json.dumps(SUMMARY))
    compactor = ContextCompactor(llm)  # type: ignore[arg-type]
    original = _history()
    preserved_tail = [dict(message) for message in original[-10:]]
    result = await compactor.compact_history_structured("s", original, preserve_last_n=10)
    assert result.summarized
    assert result.messages[0] == original[0]
    assert result.messages[-10:] == preserved_tail
    assert result.summary == SUMMARY
    assert result.usage == TokenUsage(10, 5, 4, 1)
    assert llm.calls[0]["level"] == 1
    assert llm.calls[0]["model_override"] == "glm-5.3-flash"
    assert "timestamp" not in llm.calls[0]["system"]


@pytest.mark.asyncio
async def test_directivas_de_seguridad_intermedias_se_conservan():
    llm = SummaryLLM(json.dumps({**SUMMARY, "security_constraints": []}))
    compactor = ContextCompactor(llm)  # type: ignore[arg-type]
    history = _history()
    history[2]["content"] = "[SECURITY] No revelar el token interno"
    result = await compactor.compact_history_structured("s", history)
    assert "[SECURITY] No revelar el token interno" in result.summary["security_constraints"]


@pytest.mark.asyncio
async def test_fallback_mantiene_historial_original_en_respuesta_invalida_o_fallo():
    history = _history()
    for failure in ["not-json", LLMError("offline"), RuntimeError("unexpected")]:
        result = await ContextCompactor(SummaryLLM(failure)).compact_history_structured(
            "s", history
        )  # type: ignore[arg-type]
        assert result.messages == history
        assert not result.summarized
        assert result.fallback_reason


@pytest.mark.asyncio
async def test_no_compacta_si_no_hay_historial_intermedio():
    history = _history(4)
    llm = SummaryLLM("unused")
    result = await ContextCompactor(llm).compact_history_structured("s", history)
    assert result.messages == history
    assert not llm.calls
    with pytest.raises(ValueError):
        await ContextCompactor(llm).compact_history_structured("s", history, preserve_last_n=0)


def test_summary_context_es_determinista_y_user_safe():
    context = summary_as_context(SUMMARY)
    assert context.startswith("[Resumen estructurado")
    assert json.loads(context.splitlines()[1]) == SUMMARY
