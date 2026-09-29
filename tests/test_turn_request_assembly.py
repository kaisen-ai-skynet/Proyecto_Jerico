import pytest

from jerico.agent.turn_request_assembly import assemble_turn_request


def test_ensambla_prefijo_system_estable_historial_y_mensajes_efimeros():
    history = [
        {"role": "system", "content": "system antiguo"},
        {"role": "user", "content": "anterior"},
        {"role": "assistant", "content": "respuesta"},
        {"role": "tool", "content": "salida previa", "tool_call_id": "c1"},
        {"role": "invalid", "content": "ignorar"},
        {"role": "assistant", "content": ""},
    ]
    request = assemble_turn_request(
        "system sin mutación",
        "actual",
        history=history,
        ephemeral_messages=[{"role": "user", "content": "contexto: fecha"}],
    )
    assert request.messages == (
        {"role": "system", "content": "system sin mutación"},
        {"role": "user", "content": "anterior"},
        {"role": "assistant", "content": "respuesta"},
        {"role": "tool", "content": "salida previa", "tool_call_id": "c1"},
        {"role": "user", "content": "contexto: fecha"},
        {"role": "user", "content": "actual"},
    )
    assert history[0]["content"] == "system antiguo"


def test_no_duplica_turno_actual_si_ya_es_ultimo_mensaje():
    request = assemble_turn_request(
        None,
        "same turn",
        history=[{"role": "user", "content": "same turn"}],
    )
    assert request.system_prompt_hash is None
    assert request.messages == ({"role": "user", "content": "same turn"},)


def test_contexto_efimero_no_puede_modificar_system():
    with pytest.raises(ValueError, match="roles user o tool"):
        assemble_turn_request(
            "sistema", "pregunta", ephemeral_messages=[{"role": "system", "content": "mutado"}]
        )


def test_contexto_efimero_no_suprime_el_turno_real():
    request = assemble_turn_request(
        "sistema",
        "turno",
        history=[{"role": "user", "content": "turno"}],
        ephemeral_messages=[{"role": "tool", "content": "contexto"}],
    )
    assert request.messages[-2:] == (
        {"role": "tool", "content": "contexto"},
        {"role": "user", "content": "turno"},
    )
