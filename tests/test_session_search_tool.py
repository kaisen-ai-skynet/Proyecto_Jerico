from jerico.state import StateEngine
from jerico.tools.session_search import SessionSearchTool


def test_tool_scopes_search_to_own_session(tmp_path):
    with StateEngine(tmp_path / "state.db") as state:
        for session in ("a", "b"):
            state.get_or_create_session(session, "system", "model")
            state.append_message(session, "user", f"architecture {session}")
        result = SessionSearchTool(state, "a").run(query="architecture")
        assert result["ok"]
        assert [row["session_id"] for row in result["results"]] == ["a"]
