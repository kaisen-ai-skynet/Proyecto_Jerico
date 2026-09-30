import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from loguru import logger


def _field(raw: str, low: int, high: int, *, sunday: bool = False) -> set[int]:
    values: set[int] = set()
    for item in raw.split(","):
        base, separator, step_raw = item.partition("/")
        step = int(step_raw) if separator else 1
        if step < 1:
            raise ValueError("cron step debe ser positivo")
        if base == "*":
            start, stop = low, high
        elif "-" in base:
            start, stop = map(int, base.split("-", 1))
        else:
            start = int(base)
            stop = high if separator else start
        if not low <= start <= stop <= high:
            raise ValueError("cron field fuera de rango")
        selected = range(start, stop + 1, step)
        values.update(value % 7 if sunday else value for value in selected)
    return values


@dataclass
class Job:
    fields: tuple[set[int], ...]
    callback: Callable[[], Coroutine[Any, Any, None]]
    retries: int
    day_of_month_wildcard: bool
    day_of_week_wildcard: bool
    last_minute: tuple[int, ...] | None = None


class CronScheduler:
    def __init__(self, *, execution_timeout_s: float = 60, poll_interval_s: float = 1) -> None:
        if execution_timeout_s <= 0 or poll_interval_s <= 0:
            raise ValueError("timeouts deben ser positivos")
        self.timeout = execution_timeout_s
        self.interval = poll_interval_s
        self.jobs: dict[str, Job] = {}
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.runner: asyncio.Task[None] | None = None

    def register_job(
        self,
        job_id: str,
        cron_expression: str,
        callback: Callable[[], Coroutine[Any, Any, None]],
        *,
        max_retries: int = 2,
    ) -> None:
        parts = cron_expression.split()
        if len(parts) != 5 or max_retries < 0:
            raise ValueError("cron requiere cinco campos y retries no negativos")
        if job_id in self.jobs:
            raise ValueError("job_id duplicado")
        bounds = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]
        self.jobs[job_id] = Job(
            tuple(
                _field(part, *bound, sunday=index == 4)
                for index, (part, bound) in enumerate(zip(parts, bounds, strict=True))
            ),
            callback,
            max_retries,
            parts[2] == "*",
            parts[4] == "*",
        )

    async def tick(self, now: datetime) -> None:
        minute = (now.year, now.month, now.day, now.hour, now.minute)
        components = (now.minute, now.hour, now.day, now.month, (now.weekday() + 1) % 7)
        for name, job in self.jobs.items():
            if job.last_minute == minute or (name in self.tasks and not self.tasks[name].done()):
                continue
            if (
                not all(value in job.fields[index] for index, value in enumerate(components[:2]))
                or components[3] not in job.fields[3]
            ):
                continue
            day_of_month = components[2] in job.fields[2]
            day_of_week = components[4] in job.fields[4]
            if job.day_of_month_wildcard and job.day_of_week_wildcard:
                day_matches = True
            elif job.day_of_month_wildcard:
                day_matches = day_of_week
            elif job.day_of_week_wildcard:
                day_matches = day_of_month
            else:
                day_matches = day_of_month or day_of_week
            if day_matches:
                job.last_minute = minute
                self.tasks[name] = asyncio.create_task(self._execute(job))

    async def _execute(self, job: Job) -> None:
        for attempt in range(job.retries + 1):
            try:
                await asyncio.wait_for(job.callback(), timeout=self.timeout)
                return
            except Exception as exc:
                logger.warning("cron failure attempt={}: {}", attempt, type(exc).__name__)

    async def start(self) -> None:
        if self.runner is None or self.runner.done():
            self.runner = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while True:
            await self.tick(datetime.now(UTC))
            await asyncio.sleep(self.interval)

    async def stop(self) -> None:
        tasks = list(self.tasks.values())
        if self.runner is not None:
            tasks.append(self.runner)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
        self.runner = None
