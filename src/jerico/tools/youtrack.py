from jerico.tools.base import BaseTool


class YouTrackListIssuesTool(BaseTool):
    name: str = "youtrack_list_issues"
    description: str = "Lista issues de kaisensky.youtrack.cloud (read-only)."
    readonly: bool = True

    def _execute(  # type: ignore[override]
        self, project: str = "DEMO", query: str = "", limit: int = 10
    ) -> dict[str, object]:
        return {
            "ok": True,
            "tool": self.name,
            "project": project,
            "query": query,
            "limit": limit,
            "issues": [],
            "note": "stub v0: requiere JERICO_YOUTRACK_TOKEN",
        }


class YouTrackCreateIssueTool(BaseTool):
    name: str = "youtrack_create_issue"
    description: str = "Crea un issue en YouTrack. ESCRITURA: exige confirm=True."
    readonly: bool = False


YOUTRACK_TOOLS: list[BaseTool] = [YouTrackListIssuesTool(), YouTrackCreateIssueTool()]
