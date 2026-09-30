from dataclasses import asdict

from pydantic import PrivateAttr

from jerico.state import StateEngine
from jerico.tools.base import BaseTool


class SessionSearchTool(BaseTool):
    name: str = "session_search"
    description: str = "Busca texto histórico en la sesión actual usando FTS5 trigram."
    readonly: bool = True
    _state: StateEngine = PrivateAttr()
    _session_id: str = PrivateAttr()

    def __init__(self, state: StateEngine, session_id: str) -> None:
        super().__init__(name="session_search")
        self._state = state
        self._session_id = session_id

    def _execute(self, query: str, limit: int = 10) -> dict[str, object]:  # type: ignore[override]
        results = self._state.search_history_fts(query, limit, session_id=self._session_id)
        return {"ok": True, "results": [asdict(result) for result in results]}
