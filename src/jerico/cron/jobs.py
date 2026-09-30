import asyncio
import sqlite3
from collections.abc import Awaitable, Callable
from pathlib import Path

from jerico.state import StateEngine
from jerico.tools.environments.base import ExecutionEnvironment, ProcessExecutionResult


async def docker_watchdog(environment: ExecutionEnvironment) -> ProcessExecutionResult:
    return await environment.execute_command(
        "docker ps --format '{{.Names}} {{.Status}}'", timeout_s=10
    )


async def postgres_watchdog(health_check: Callable[[], Awaitable[bool]]) -> bool:
    """Run an injected PostgreSQL health check without embedding credentials here."""
    return await health_check()


async def sync_external_state(*syncers: Callable[[], Awaitable[None]]) -> None:
    """Run configured YouTrack/Notion sync workers sequentially in a cron task."""
    for sync in syncers:
        await sync()


async def maintain_state(state: StateEngine) -> None:
    def maintain() -> None:
        with state._write_lock:
            connection = state._require_writer()
            connection.execute("PRAGMA optimize")
            connection.execute("PRAGMA wal_checkpoint(PASSIVE)")

    await asyncio.to_thread(maintain)


async def backup_state(state: StateEngine, destination: Path, *, keep: int = 7) -> Path:
    if keep < 1:
        raise ValueError("keep debe ser positivo")

    def backup() -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with state._write_lock, sqlite3.connect(destination) as target:
            state._require_writer().backup(target)
        backups = sorted(
            destination.parent.glob("jerico-backup-*.db"), key=lambda path: path.stat().st_mtime
        )
        for path in backups[:-keep]:
            if path != destination:
                path.unlink()
        return destination

    return await asyncio.to_thread(backup)
