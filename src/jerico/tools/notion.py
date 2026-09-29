from jerico.tools.base import BaseTool


class NotionQueryDBTool(BaseTool):
    name: str = "notion_query_db"
    description: str = "Consulta una DB del Segundo Cerebro (DB-01..DB-07). Read-only."
    readonly: bool = True

    def _execute(  # type: ignore[override]
        self, db_id: str = "", filter_property: str = "", limit: int = 10
    ) -> dict[str, object]:
        return {
            "ok": True,
            "tool": self.name,
            "db_id": db_id,
            "limit": limit,
            "results": [],
            "note": "stub v0: requiere JERICO_NOTION_TOKEN",
        }


class NotionAppendRowTool(BaseTool):
    name: str = "notion_append_row"
    description: str = "Agrega fila a DB de Notion. ESCRITURA: exige confirm=True."
    readonly: bool = False


NOTION_TOOLS: list[BaseTool] = [NotionQueryDBTool(), NotionAppendRowTool()]
