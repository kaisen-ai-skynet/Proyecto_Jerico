import asyncio
import os
from datetime import UTC, datetime

import pytest

from jerico.cron.jobs import (
    backup_state,
    docker_watchdog,
    maintain_state,
    postgres_watchdog,
    sync_external_state,
)
from jerico.cron.scheduler import CronScheduler
from jerico.state import StateEngine


@pytest.mark.asyncio
async def test_scheduler_matches_cron_retries_and_runs_once_per_minute():
    scheduler = CronScheduler(execution_timeout_s=0.5, poll_interval_s=0.01)
    attempts = 0

    async def flaky_job() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient")

    scheduler.register_job("minute", "*/5 * * * *", flaky_job, max_retries=1)
    now = datetime(2026, 9, 30, 12, 10, tzinfo=UTC)
    await scheduler.tick(now)
    await scheduler.tick(now)
    await asyncio.gather(*scheduler.tasks.values())
    assert attempts == 2

    await scheduler.tick(datetime(2026, 9, 30, 12, 11, tzinfo=UTC))
    await asyncio.gather(*scheduler.tasks.values())
    assert attempts == 2
    await scheduler.stop()


@pytest.mark.asyncio
async def test_scheduler_timeout_and_clean_shutdown():
    scheduler = CronScheduler(execution_timeout_s=0.01, poll_interval_s=0.01)
    started = asyncio.Event()
    scheduler.register_job("slow", "* * * * *", lambda: wait_forever(started))
    await scheduler.tick(datetime(2026, 9, 30, 12, 0, tzinfo=UTC))
    await started.wait()
    await asyncio.gather(*scheduler.tasks.values())
    assert scheduler.tasks["slow"].done()
    await scheduler.start()
    assert scheduler.runner is not None
    await scheduler.stop()
    assert scheduler.runner is None
    assert scheduler.tasks == {}


async def wait_forever(started: asyncio.Event) -> None:
    started.set()
    await asyncio.Event().wait()


def test_scheduler_rejects_invalid_expression_and_duplicates():
    scheduler = CronScheduler()

    async def callback() -> None:
        return None

    with pytest.raises(ValueError):
        scheduler.register_job("bad", "60 * * * *", callback)
    scheduler.register_job("ok", "0 0 * * *", callback)
    with pytest.raises(ValueError, match="duplicado"):
        scheduler.register_job("ok", "0 1 * * *", callback)


@pytest.mark.asyncio
async def test_cron_supports_standard_day_or_sunday_alias_and_step_from_value():
    scheduler = CronScheduler()
    ran: list[str] = []

    async def day_or() -> None:
        ran.append("day-or")

    async def sunday() -> None:
        ran.append("sunday")

    async def stepped() -> None:
        ran.append("step")

    scheduler.register_job("day-or", "0 0 30 * 1", day_or)
    scheduler.register_job("sunday", "0 0 * * 7", sunday)
    scheduler.register_job("step", "5/10 * * * *", stepped)
    await scheduler.tick(datetime(2026, 9, 30, 0, 0, tzinfo=UTC))
    await scheduler.tick(datetime(2026, 10, 4, 0, 0, tzinfo=UTC))
    await scheduler.tick(datetime(2026, 10, 4, 0, 35, tzinfo=UTC))
    await asyncio.gather(*scheduler.tasks.values())
    assert ran == ["day-or", "sunday", "step"]
    await scheduler.stop()


@pytest.mark.asyncio
async def test_state_maintenance_and_consistent_sqlite_backup(tmp_path):
    db = tmp_path / "state.db"
    backup = tmp_path / "backups" / "jerico-backup-test.db"
    with StateEngine(db) as state:
        state.get_or_create_session("saved", "system", "model")
        await maintain_state(state)
        assert await backup_state(state, backup, keep=2) == backup
    with StateEngine(backup) as restored:
        assert restored.get_session_transcript("saved") == []


@pytest.mark.asyncio
async def test_health_and_external_sync_jobs_use_injected_integrations():
    class Environment:
        async def execute_command(self, command: str, *, timeout_s: float):
            return command, timeout_s

    calls: list[str] = []

    async def sync(name: str) -> None:
        calls.append(name)

    assert await docker_watchdog(Environment()) == (
        "docker ps --format '{{.Names}} {{.Status}}'",
        10,
    )
    assert await postgres_watchdog(lambda: asyncio.sleep(0, result=True)) is True
    await sync_external_state(lambda: sync("youtrack"), lambda: sync("notion"))
    assert calls == ["youtrack", "notion"]


@pytest.mark.asyncio
async def test_backup_retention_removes_oldest_files(tmp_path):
    db = tmp_path / "state.db"
    with StateEngine(db) as state:
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        old_backups = [backup_dir / f"jerico-backup-{i}.db" for i in range(3)]
        for index, path in enumerate(old_backups):
            path.touch()
            os.utime(path, (index, index))
        await backup_state(state, backup_dir / "jerico-backup-current.db", keep=2)
        assert old_backups[0].exists() is False
        assert old_backups[1].exists() is False
        assert old_backups[2].exists() is True
