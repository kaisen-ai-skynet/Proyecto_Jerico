from jerico.agent.types import SurfaceType, ToolsetPosture
from jerico.tools import REGISTRY
from jerico.tools.registry import ToolRegistry


def test_postures_and_canonical_order():
    registry = ToolRegistry()
    for tool in reversed(list(REGISTRY.values())):
        registry.register(tool)
    for posture, prefix in [
        (ToolsetPosture.CODING, "youtrack_"),
        (ToolsetPosture.OPS, "docker_"),
        (ToolsetPosture.PERSONAL, "notion_"),
    ]:
        schemas = registry.resolve_for_session(posture, SurfaceType.REST)
        assert schemas
        assert all(item["function"]["name"].startswith(prefix) for item in schemas)
    names = [
        s["function"]["name"]
        for s in registry.resolve_for_session(ToolsetPosture.DEFAULT, SurfaceType.CLI)
    ]
    assert names == sorted(REGISTRY)
