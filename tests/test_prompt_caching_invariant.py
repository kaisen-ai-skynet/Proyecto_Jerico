import hashlib
from dataclasses import FrozenInstanceError

import pytest

from jerico.agent.prompt_builder import PromptBuilder
from jerico.state import StateEngine


def test_system_prompt_es_byte_estable_y_separa_contexto_dinamico():
    prompt = "Eres Jericó. Política: conservar ñ y espacios finales.\n"
    builder = PromptBuilder(prompt)
    original_bytes = builder.system_prompt.encode("utf-8")
    first = builder.assemble(
        "pregunta", ephemeral_messages=[{"role": "user", "content": "fecha: hoy"}]
    )
    second = builder.assemble(
        "otra pregunta", ephemeral_messages=[{"role": "tool", "content": "perfil"}]
    )

    assert first.messages[0] == {"role": "system", "content": prompt}
    assert second.messages[0] == first.messages[0]
    assert first.messages[0]["content"].encode("utf-8") == original_bytes
    assert first.system_prompt_hash == hashlib.sha256(original_bytes).hexdigest()
    assert builder.prompt_hash == first.system_prompt_hash
    assert all(message["role"] != "system" for message in first.messages[1:])
    assert first.messages[-2]["content"] == "fecha: hoy"


def test_prompt_builder_no_permite_mutacion_y_registra_hash_por_sesion(tmp_path):
    builder = PromptBuilder("system fijo")
    with pytest.raises(FrozenInstanceError):
        builder.snapshot = builder.snapshot  # type: ignore[misc]

    with StateEngine(tmp_path / "state.db") as state:
        session = builder.bind_session(state, "s", "model")
        assert session.system_prompt_hash == builder.prompt_hash
        with pytest.raises(ValueError, match="inmutable"):
            PromptBuilder("system distinto").bind_session(state, "s", "model")


def test_hash_no_depende_de_fecha_o_contexto_efimero():
    builder = PromptBuilder("prompt estable")
    hashes = {
        builder.assemble(
            "pregunta",
            ephemeral_messages=[{"role": "user", "content": f"timestamp={timestamp}"}],
        ).system_prompt_hash
        for timestamp in range(10)
    }
    assert hashes == {builder.prompt_hash}
