from jerico.state import StateEngine


def test_indexes_new_transcripts_and_survives_reopen(tmp_path):
    path = tmp_path / "state.db"
    state = StateEngine(path)
    state.get_or_create_session("s", "system", "model")
    state.append_message("s", "user", "decisión arquitectura SQLite WAL")
    assert state.search_history_fts("arquitectura")[0].session_id == "s"
    state.close()
    state = StateEngine(path)
    try:
        assert len(state.search_history_fts("SQLite")) == 1
    finally:
        state.close()


def test_rebuilds_existing_transcripts_on_migration(tmp_path):
    state = StateEngine(tmp_path / "state.db")
    try:
        state.get_or_create_session("s", "system", "model")
        state.append_message("s", "assistant", "historical decision")
        with state._transaction() as connection:
            connection.execute("DELETE FROM messages WHERE session_id='s'")
        assert state.search_history_fts("historical") == []
    finally:
        state.close()
