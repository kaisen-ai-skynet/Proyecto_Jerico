from jerico.agent.types import SurfaceType, ToolsetPosture


def belongs_to_posture(name: str, posture: ToolsetPosture, surface: SurfaceType) -> bool:
    del surface
    if posture == ToolsetPosture.DEFAULT:
        return True
    prefixes = {
        ToolsetPosture.CODING: ("youtrack_", "session_"),
        ToolsetPosture.OPS: ("docker_", "session_"),
        ToolsetPosture.PERSONAL: ("notion_", "session_"),
    }
    return name.startswith(prefixes[posture])
