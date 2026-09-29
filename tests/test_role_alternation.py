import pytest

from jerico.agent.turn_request_assembly import assemble_turn_request, validate_role_alternation


def test_historial_agente_mantiene_system_assistant_tool_alternation():
    request = assemble_turn_request("system", "pregunta")
    messages = list(request.messages)
    messages.extend(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "x", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "resultado"},
            {"role": "assistant", "content": "final"},
        ]
    )
    assert [message["role"] for message in messages] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    validate_role_alternation(messages)


@pytest.mark.parametrize(
    "messages",
    [
        [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}],
        [{"role": "system", "content": "a"}, {"role": "assistant", "content": "b"}],
        [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
            {"role": "tool", "tool_call_id": "wrong", "content": "x"},
        ],
        [
            {"role": "system", "content": "a"},
            {"role": "user", "content": "b"},
            {"role": "system", "content": "duplicate"},
        ],
        [{"role": "unknown", "content": "x"}],
    ],
)
def test_rechaza_secuencias_de_roles_invalidas(messages):
    with pytest.raises(ValueError):
        validate_role_alternation(messages)
