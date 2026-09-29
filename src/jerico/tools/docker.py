from jerico.tools.base import BaseTool


class DockerListContainersTool(BaseTool):
    name: str = "docker_list_containers"
    description: str = "Lista contenedores Docker del host. Read-only."
    readonly: bool = True

    def _execute(self, all: bool = True) -> dict[str, object]:  # type: ignore[override]
        return {
            "ok": True,
            "tool": self.name,
            "all": all,
            "containers": [],
            "note": "stub v0: requiere socket docker",
        }


class DockerRestartContainerTool(BaseTool):
    name: str = "docker_restart_container"
    description: str = "Reinicia un contenedor. ESCRITURA: exige confirm=True."
    readonly: bool = False


DOCKER_TOOLS: list[BaseTool] = [DockerListContainersTool(), DockerRestartContainerTool()]
