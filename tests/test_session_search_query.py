import pytest

from jerico.state import StateEngine


def test_multilingual_literal_search_and_limits(tmp_path):
    with StateEngine(tmp_path / "state.db") as state:
        state.get_or_create_session("a", "system", "model")
        state.get_or_create_session("b", "system", "model")
        state.append_message("a", "user", "incidencia producción 東京駅")
        state.append_message("b", "assistant", "incidencia another service")
        assert len(state.search_history_fts("incidencia")) == 2
        assert state.search_history_fts("東京駅")[0].session_id == "a"
        assert len(state.search_history_fts("incidencia", 1)) == 1
        assert state.search_history_fts("ab") == []
        assert state.search_history_fts("' OR 1=1 --") == []
        assert state.search_history_fts('" OR "') == []
        with pytest.raises(ValueError):
            state.search_history_fts("incidencia", 0)
