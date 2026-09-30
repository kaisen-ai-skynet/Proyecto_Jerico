import shlex
from pathlib import Path

from jerico.tools.environments.base import ExecutionEnvironment, ProcessExecutionResult
from jerico.tools.environments.local import LocalEnvironment


class DockerEnvironment(ExecutionEnvironment):
    def __init__(self, image: str, runner: ExecutionEnvironment | None = None) -> None:
        self.image = image
        self.runner = runner or LocalEnvironment()

    async def execute_command(
        self,
        command: str,
        *,
        cwd: Path | None = None,
        timeout_s: float = 60,
        env: dict[str, str] | None = None,
    ) -> ProcessExecutionResult:
        if cwd is not None:
            raise ValueError("host cwd mounts requieren política aprobada")
        args = [
            "docker",
            "run",
            "--rm",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user=65534:65534",
            "--memory=128m",
            "--cpus=1",
            "--pids-limit=64",
            "--tmpfs=/tmp",
        ]
        for key, value in sorted((env or {}).items()):
            args.extend(["--env", f"{key}={value}"])
        args.extend([self.image, "/bin/sh", "-c", command])
        return await self.runner.execute_command(shlex.join(args), timeout_s=timeout_s)

    async def cleanup(self) -> None:
        await self.runner.cleanup()
