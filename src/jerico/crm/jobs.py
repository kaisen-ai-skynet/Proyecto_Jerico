"""Registro de los jobs del CRM en `CronScheduler` (plan §9). Cron en UTC; Bogotá = UTC−5."""

from collections.abc import Callable, Coroutine
from typing import Any

from jerico.cron.scheduler import CronScheduler

DAILY_JOB = "crm-daily"
DAILY_CRON = "0 13 * * *"  # 08:00 Bogotá
BACKUP_JOB = "crm-backup"
BACKUP_CRON = "0 8 * * *"  # 03:00 Bogotá
RETRIES = 1

JobCallback = Callable[[], Coroutine[Any, Any, None]]


def register_jobs(scheduler: CronScheduler, *, daily: JobCallback, backup: JobCallback) -> None:
    """Único punto de contacto con `CronScheduler.register_job`."""
    scheduler.register_job(DAILY_JOB, DAILY_CRON, daily, max_retries=RETRIES)
    scheduler.register_job(BACKUP_JOB, BACKUP_CRON, backup, max_retries=RETRIES)


__all__ = ["BACKUP_CRON", "BACKUP_JOB", "DAILY_CRON", "DAILY_JOB", "register_jobs"]
