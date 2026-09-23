import pytest

from jerico.tools import REGISTRY, get_tool
from jerico.tools.base import BaseTool


def test_registry_no_vacio_y_nombres_unicos():
    assert len(REGISTRY) >= 3
    names = [t.name for t in REGISTRY.values()]
    assert len(names) == len(set(names))


def test_get_tool_devuelve_none_si_no_existe():
    assert get_tool("no_existe") is None


@pytest.mark.parametrize(
    "name", ["youtrack_list_issues", "notion_query_db", "docker_list_containers"]
)
def test_tools_lectura_son_readonly(name):
    tool = get_tool(name)
    assert tool is not None and tool.readonly is True
    result = tool.run()
    assert result["ok"] is True


@pytest.mark.parametrize(
    "name", ["youtrack_create_issue", "notion_append_row", "docker_restart_container"]
)
def test_tools_escritura_bloqueadas_sin_confirm(name):
    tool = get_tool(name)
    assert tool is not None and tool.readonly is False
    result = tool.run(proyecto="x")
    assert result["ok"] is False
    assert result["error"] == "CONFIRMATION_REQUIRED"


def test_write_tool_con_confirm_ejecuta_stub(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tool = get_tool("youtrack_create_issue")
    result = tool.run(confirm=True, summary="issue de prueba")
    assert result["ok"] is True
    assert (tmp_path / "logs" / "audit.log").exists()


def test_base_tool_subclase_declara_name():
    class ToolDummy(BaseTool):
        name: str = "dummy"

    assert ToolDummy().run()["ok"] is True
