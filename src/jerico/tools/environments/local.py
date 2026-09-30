import asyncio
import os
import signal
from pathlib import Path

from jerico.tools.environments.base import ExecutionEnvironment, ProcessExecutionResult


class LocalEnvironment(ExecutionEnvironment):
    def __init__(self) -> None:
        self.processes: set[asyncio.subprocess.Process] = set()

    async def execute_command(
        self,
        command: str,
        *,
        cwd: Path | None = None,
        timeout_s: float = 60,
        env: dict[str, str] | None = None,
    ) -> ProcessExecutionResult:
        if timeout_s <= 0:
            raise ValueError("timeout debe ser positivo")
        process = await asyncio.create_subprocess_exec(
            "/bin/sh",
            "-c",
            command,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        self.processes.add(process)
        timed_out = False
        try:
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout_s)
            except TimeoutError:
                timed_out = True
                self._kill(process)
                stdout, stderr = await process.communicate()
            return ProcessExecutionResult(
                process.returncode or 0,
                stdout.decode(errors="replace"),
                stderr.decode(errors="replace"),
                timed_out,
            )
        finally:
            if process.returncode is None:
                self._kill(process)
                await process.wait()
            self.processes.discard(process)

    @staticmethod
    def _kill(process: asyncio.subprocess.Process) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    async def cleanup(self) -> None:
        for process in list(self.processes):
            self._kill(process)
            await process.wait()
        self.processes.clear()
