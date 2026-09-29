import hashlib

import pytest

from jerico.state import StateEngine


def test_system_prompts_se_deduplican_y_sesion_tiene_linaje(tmp_path):
    with StateEngine(tmp_path / "state.db") as state:
        root = state.get_or_create_session("root", "system bytes", "model-l1")
        child = state.get_or_create_session("child", "system bytes", "model-l2", "root")
        assert root.system_prompt_hash == hashlib.sha256(b"system bytes").hexdigest()
        assert child.system_prompt_hash == root.system_prompt_hash
        assert child.parent_session_id == "root"
        with state._reader() as connection:
            assert connection.execute("SELECT count(*) FROM system_prompts").fetchone()[0] == 1
            assert connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 2


def test_prompt_de_sesion_es_inmutable_y_rollback_no_deja_filtraciones(tmp_path):
    with StateEngine(tmp_path / "state.db") as state:
        created = state.get_or_create_session("s", "system original", "model")
        with pytest.raises(ValueError, match="inmutable"):
            state.get_or_create_session("s", "system cambiado", "model")
        reopened = state.get_or_create_session("s", "system original", "model")
        assert reopened.session_id == created.session_id
        assert reopened.created_at == created.created_at
        assert reopened.updated_at >= created.updated_at
        with state._reader() as connection:
            assert connection.execute("SELECT count(*) FROM system_prompts").fetchone()[0] == 1


def test_append_message_transcript_y_limite(tmp_path):
    with StateEngine(tmp_path / "state.db") as state:
        state.get_or_create_session("s", "system", "model")
        first_id = state.append_message("s", "assistant", "tool call", tool_calls=[{"id": "c1"}])
        second_id = state.append_message(
            "s", "tool", "resultado", tool_call_id="c1", reasoning="reason"
        )
        state.append_message("s", "user", "siguiente")
        transcript = state.get_session_transcript("s")
        assert [message.id for message in transcript] == [first_id, second_id, second_id + 1]
        assert transcript[0].tool_calls == [{"id": "c1"}]
        assert transcript[1].tool_call_id == "c1"
        assert transcript[1].reasoning == "reason"
        assert [m.content for m in state.get_session_transcript("s", limit=1)] == ["tool call"]
        assert state.get_session_transcript("missing") == []
        with pytest.raises(ValueError, match="limit"):
            state.get_session_transcript("s", limit=-1)


def test_record_usage_acumula_y_rechaza_contadores_negativos(tmp_path):
    with StateEngine(tmp_path / "state.db") as state:
        state.get_or_create_session("s", "system", "model")
        state.record_usage("s", "model", 10, 5, 2)
        state.record_usage("s", "model", 3, 4, 1)
        assert state.get_usage("s", "model") == {
            "prompt_tokens": 13,
            "completion_tokens": 9,
            "cached_tokens": 3,
        }
        assert state.get_usage("s", "unknown") is None
        with pytest.raises(ValueError, match="negativos"):
            state.record_usage("s", "model", -1, 0)


def test_fallos_fk_o_role_invalido_hacen_rollback(tmp_path):
    import sqlite3

    with StateEngine(tmp_path / "state.db") as state:
        with pytest.raises(sqlite3.IntegrityError):
            state.get_or_create_session("orphan", "unused prompt", "model", "missing-parent")
        with state._reader() as connection:
            assert connection.execute("SELECT count(*) FROM system_prompts").fetchone()[0] == 0

        state.get_or_create_session("s", "system", "model")
        with pytest.raises(sqlite3.IntegrityError):
            state.append_message("s", "invalid-role", "not inserted")
        assert state.get_session_transcript("s") == []
        with pytest.raises(sqlite3.IntegrityError):
            state.record_usage("missing", "model", 1, 1)
