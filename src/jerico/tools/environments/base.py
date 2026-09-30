from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessExecutionResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


class ExecutionEnvironment(ABC):
    @abstractmethod
    async def execute_command(
        self,
        command: str,
        *,
        cwd: Path | None = None,
        timeout_s: float = 60,
        env: dict[str, str] | None = None,
    ) -> ProcessExecutionResult:
        raise NotImplementedError

    @abstractmethod
    async def cleanup(self) -> None:
        raise NotImplementedError
