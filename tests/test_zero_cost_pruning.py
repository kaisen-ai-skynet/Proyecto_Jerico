import pytest

from jerico.agent.turn_context_compaction import ContextCompactor


class NoCallLLM:
    async def complete_with_usage(self, *_args, **_kwargs):
        raise AssertionError("zero-cost pruning no debe invocar el LLM")


def test_poda_tool_results_viejos_preserva_tail_y_evidencia():
    messages = [
        {"role": "user", "content": "pregunta antigua"},
        {"role": "assistant", "content": "tool call"},
        {"role": "tool", "content": "x" * 500},
        {"role": "assistant", "content": "respuesta antigua"},
        {"role": "user", "content": "pregunta reciente"},
        {"role": "tool", "content": "y" * 500},
        {"role": "assistant", "content": "respuesta reciente"},
    ]
    original_tail = [dict(message) for message in messages[-3:]]
    compacted = ContextCompactor(
        NoCallLLM(), tool_result_max_chars=20
    ).prune_tool_results_zero_cost(
        messages,
        preserve_tail_turns=1,
    )
    assert len(compacted[2]["content"]) < 100
    assert "sha256=" in compacted[2]["content"]
    assert compacted[-3:] == original_tail
    assert messages[2]["content"] == "x" * 500


def test_no_poda_si_historial_cabe_en_tail_y_rechaza_argumentos_invalidos():
    compactor = ContextCompactor(NoCallLLM())
    history = [{"role": "user", "content": "q"}, {"role": "tool", "content": "x" * 500}]
    assert compactor.prune_tool_results_zero_cost(history, preserve_tail_turns=5) == history
    with pytest.raises(ValueError):
        compactor.prune_tool_results_zero_cost(history, preserve_tail_turns=-1)
    with pytest.raises(ValueError):
        ContextCompactor(NoCallLLM(), tool_result_max_chars=0)
