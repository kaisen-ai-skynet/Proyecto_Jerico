from jerico.tools.base import BaseTool
from jerico.tools.catalogo import CATALOGO_TOOLS
from jerico.tools.docker import DOCKER_TOOLS
from jerico.tools.notion import NOTION_TOOLS
from jerico.tools.youtrack import YOUTRACK_TOOLS

REGISTRY: dict[str, BaseTool] = {
    tool.name: tool for tool in [*YOUTRACK_TOOLS, *NOTION_TOOLS, *DOCKER_TOOLS, *CATALOGO_TOOLS]
}


def get_tool(name: str) -> BaseTool | None:
    return REGISTRY.get(name)
