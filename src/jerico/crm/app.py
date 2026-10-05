"""Cableado del CRM (`CrmApp`), entrypoint `jerico-crm`, latido y parada ordenada (plan §9)."""

import asyncio
import signal
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

from jerico.crm import repo
from jerico.crm.backup import SubprocessRunner, run_backup
from jerico.crm.bot import CrmBot
from jerico.crm.config import (
    ConfigWarning,
    CrmSettings,
    HolidayWarning,
    effective_params,
    parse_extra_holidays,
)
from jerico.crm.db import CrmDatabase
from jerico.crm.files import LocalFileStore
from jerico.crm.jobs import register_jobs
from jerico.crm.mail import build_email_sender
from jerico.crm.model import Role
from jerico.crm.outbox import OutboxWorker, escalate
from jerico.crm.ports import CommandRunner, EmailSender, TelegramPort
from jerico.crm.retention import daily_sweep
from jerico.crm.team import seed_cto
from jerico.crm.telegram import HttpxTelegramClient
from jerico.cron.scheduler import CronScheduler

EXIT_CONFIG = 2
STARTUP_NOTICE_KIND = "aviso_arranque"
EXECUTION_TIMEOUT_S = 1800
POLL_INTERVAL_S = 20
TOKEN_VAR = "JERICO_CRM_TELEGRAM_BOT_TOKEN"
KEY_VAR = "JERICO_CRM_FINGERPRINT_KEY"


def utcnow() -> datetime:
    """Único reloj real del CRM (plan §1.2)."""
    return datetime.now(UTC)


def _secret(value: object) -> str:
    getter = getattr(value, "get_secret_value", None)
    return (getter() if getter else str(value or "")).strip()


def missing_secrets(settings: CrmSettings) -> list[str]:
    """Nombres (nunca valores) de los secretos obligatorios ausentes."""
    names = []
    if not settings.telegram_bot_token or not _secret(settings.telegram_bot_token):
        names.append(TOKEN_VAR)
    if not settings.fingerprint_key or not _secret(settings.fingerprint_key):
        names.append(KEY_VAR)
    return names


def fingerprint_keys(settings: CrmSettings) -> list[str]:
    """Clave actual primero y luego las previas (solo para comprobar huellas)."""
    previous = _secret(settings.fingerprint_previous_keys).split(",")
    return [_secret(settings.fingerprint_key), *(k.strip() for k in previous if k.strip())]


def config_notice(w: ConfigWarning) -> str:  # VCRM-162
    return (
        f"⚠️ Configuración del CRM: {w.param} = {w.rejected:g} no se aplica "
        f"(fuera del límite legal o no positivo). Rige {w.effective:g}."
    )


def holiday_notice(w: HolidayWarning) -> str:  # VCRM-168
    return f"⚠️ Festivo extraordinario ignorado: «{w.entry}». Motivo: {w.reason}."


class CrmApp:
    """Construye base, adaptadores, bot, *outbox* y planificador sobre `settings.data_dir`."""

    def __init__(
        self,
        settings: CrmSettings,
        *,
        telegram: TelegramPort,
        email: EmailSender,
        runner: CommandRunner,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.settings = settings
        self.telegram = telegram
        self.email = email
        self.runner = runner
        self.clock = clock
        holidays, self.holiday_warnings = parse_extra_holidays(settings.extra_holidays)
        self.params, self.config_warnings = effective_params(settings, extra_holidays=holidays)
        self.keys = fingerprint_keys(settings)
        self.data_dir = Path(settings.data_dir)
        self.attachments_dir = self.data_dir / "attachments"
        self.db = CrmDatabase(self.data_dir / "crm.db")
        self.files = LocalFileStore(self.attachments_dir)
        self.worker = OutboxWorker(
            self.db,
            telegram,
            email,
            clock,
            interval_s=self.params.outbox_interval_s,
            on_failed=escalate,
        )
        self.bot = CrmBot(
            self.db,
            telegram,
            clock,
            kick=self.worker.kick,
            fingerprint_keys=self.keys,
            files=self.files,
            params=self.params,
        )
        self.scheduler = CronScheduler(
            execution_timeout_s=EXECUTION_TIMEOUT_S, poll_interval_s=POLL_INTERVAL_S
        )
        register_jobs(self.scheduler, daily=self.run_daily_job, backup=self.run_backup_job)

    async def startup(self) -> None:
        """Siembra del CTO, avisos de configuración, barrido de recuperación y latido."""
        with self.db.tx() as tx:
            seed_cto(tx, self.settings, self.clock())
        notices = [config_notice(w) for w in self.config_warnings]
        notices += [holiday_notice(w) for w in self.holiday_warnings]
        for w in self.holiday_warnings:
            logger.warning("Festivo extraordinario ignorado: {} ({})", w.entry, w.reason)
        await self._notify_cto(notices)
        await self.run_daily_job()
        self.heartbeat()

    async def _notify_cto(self, texts: list[str]) -> None:
        if not texts:
            return
        now = self.clock()
        with self.db.read() as conn:
            ctos = repo.active_users(conn, Role.CTO)
        for cto in ctos:
            for text in texts:
                result = await self.telegram.send_message(cto.telegram_id, text, None)
                if result.delivered:
                    continue
                with self.db.tx() as tx:
                    repo.record_failed_noncritical(
                        tx,
                        recipient_user_id=cto.id,
                        kind=STARTUP_NOTICE_KIND,
                        error=result.error,
                        now=now,
                    )

    async def run_daily_job(self) -> None:
        await daily_sweep(
            self.db, self.telegram, self.clock(), self.params, store=self.files, keys=self.keys
        )

    async def run_backup_job(self) -> None:
        await run_backup(
            self.db,
            self.telegram,
            self.email,
            self.runner,
            self.clock(),
            attachments_dir=self.attachments_dir,
            work_dir=self.data_dir / "backup-tmp",
            recipient=self.settings.backup_age_recipient,
            remote=self.settings.backup_remote,
            retention_days=self.params.backup_retention_days,
        )

    def heartbeat(self) -> None:
        """Latido para el *healthcheck* del contenedor (mtime)."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "heartbeat").touch()

    async def serve(self, stop: asyncio.Event) -> None:
        await self.scheduler.start()
        try:
            await asyncio.gather(
                self.bot.run_polling(stop, heartbeat=self.heartbeat), self.worker.run(stop)
            )
        finally:
            await self.scheduler.stop()

    def close(self) -> None:
        self.db.close()


async def run_service(
    settings: CrmSettings,
    *,
    telegram: TelegramPort | None = None,
    email: EmailSender | None = None,
    runner: CommandRunner | None = None,
    clock: Callable[[], datetime] = utcnow,
    stop: asyncio.Event | None = None,
) -> None:
    """Arranca el servicio; `SIGTERM`/`SIGINT` → parada ordenada."""
    client = None
    if telegram is None:  # pragma: no cover - adaptador real (red)
        client = HttpxTelegramClient(_secret(settings.telegram_bot_token))
        telegram = client
    app = CrmApp(
        settings,
        telegram=telegram,
        email=email or build_email_sender(settings),
        runner=runner or SubprocessRunner(),
        clock=clock,
    )
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        await app.startup()
        await app.serve(stop)
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)
        app.close()
        if client is not None:  # pragma: no cover - adaptador real (red)
            await client.aclose()


def main(settings: CrmSettings | None = None) -> None:
    """Entrypoint `jerico-crm`: sin token o sin clave HMAC sale con código 2."""
    settings = settings or CrmSettings()
    missing = missing_secrets(settings)
    if missing:
        logger.error("jerico-crm no arranca: falta la variable {}", ", ".join(missing))
        raise SystemExit(EXIT_CONFIG)
    asyncio.run(run_service(settings))


__all__ = [
    "EXIT_CONFIG",
    "STARTUP_NOTICE_KIND",
    "CrmApp",
    "fingerprint_keys",
    "main",
    "missing_secrets",
    "run_service",
    "utcnow",
]
