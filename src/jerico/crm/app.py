"""Cableado del CRM (`CrmApp`), entrypoint `jerico-crm`, latido y parada ordenada (plan §9)."""

import asyncio
import signal
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

from jerico.crm import CURRENT_PHASE, repo
from jerico.crm.advisor_snapshot import run_snapshot
from jerico.crm.assistant import AssistantContext, register_assistant
from jerico.crm.assistant_budget import AssistantBudget
from jerico.crm.assistant_memory import AssistantMemory
from jerico.crm.backup import SubprocessRunner, run_backup
from jerico.crm.bot import CrmBot
from jerico.crm.closing_contract import contract_sweep, register_contract
from jerico.crm.closing_flow import ClosingContext, register_closing
from jerico.crm.config import (
    ConfigWarning,
    CrmSettings,
    HolidayWarning,
    effective_params,
    parse_allowed_ids,
    parse_extra_holidays,
)
from jerico.crm.db import CrmDatabase
from jerico.crm.dryrun import DryRunEmailSender, dry_run_active
from jerico.crm.f2_bot import F2Context, register_f2
from jerico.crm.files import LocalFileStore
from jerico.crm.inbox import build_inbox
from jerico.crm.jobs import register_jobs
from jerico.crm.legal_bot import build_legal_bot
from jerico.crm.llm import LlmPort, OpenAIResponsesClient
from jerico.crm.mail import build_email_sender
from jerico.crm.mailboxes import MailContext, poll_mailboxes, register_mailboxes
from jerico.crm.migrate import MigrationError, migrate_if_needed
from jerico.crm.model import Role
from jerico.crm.outbox import OutboxWorker, escalate
from jerico.crm.ports import CommandRunner, EmailSender, InboxPort, TelegramPort
from jerico.crm.retention import daily_sweep
from jerico.crm.signature import DocuSealClient, DryRunSignature, SignaturePort
from jerico.crm.sweep import SweepContext, deliver_now, followup_sweep
from jerico.crm.team import seed_cto
from jerico.crm.telegram import HttpxTelegramClient
from jerico.cron.scheduler import CronScheduler
from jerico.shadowlog.jsonl import BOGOTA_TZ, DailyJsonlWriter

EXIT_CONFIG = 2
EXIT_MIGRATION = 3  # la migración v1 -> v2 falló: la base queda en v1 (VCRM-171)
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


def outbound_email(settings: CrmSettings) -> EmailSender:
    """Correo real; con DRY_RUN activo (por defecto) todo se redirige al correo del CTO."""
    sender = build_email_sender(settings)
    if dry_run_active(settings):
        return DryRunEmailSender(sender, settings.seed_cto_email)
    return sender


def build_signature(settings: CrmSettings) -> SignaturePort | None:
    """DocuSeal real; con DRY_RUN (por defecto) un doble que nunca sale a terceros."""
    token = _secret(settings.docuseal_token)
    real = (
        DocuSealClient(base_url=settings.docuseal_url, token=token)
        if settings.docuseal_url and token
        else None
    )
    return DryRunSignature(real) if dry_run_active(settings) else real


def build_assistant_llm(settings: CrmSettings) -> LlmPort | None:
    """Cliente real solo con el flag encendido y la llave presente (VCRM-A30, A31)."""
    key = _secret(settings.openai_api_key)
    if not settings.assistant_enabled or not key:
        return None
    return OpenAIResponsesClient(
        api_key=key,
        model=settings.openai_model,
        effort=settings.openai_reasoning_effort,
    )


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
        inbox: InboxPort | None = None,
        assistant_llm: LlmPort | None = None,
        legal_telegram: TelegramPort | None = None,
    ) -> None:
        self.settings = settings
        self.telegram = telegram
        self.email = email
        self.runner = runner
        self.clock = clock
        self.inbox: InboxPort = inbox or build_inbox(settings)
        self.assistant_llm: LlmPort | None = assistant_llm or build_assistant_llm(settings)
        self._tasks: set[asyncio.Task[None]] = set()
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
            lawyer_telegram=legal_telegram,
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
        self.assistant_memory: AssistantMemory | None = (
            AssistantMemory(self.data_dir / "assistant_memory.db")
            if settings.assistant_enabled
            else None
        )
        register_assistant(
            self.bot,
            AssistantContext(
                settings=settings,
                db=self.db,
                client=self.assistant_llm,
                budget=AssistantBudget(settings),
                clock=clock,
                memory=self.assistant_memory,
            ),
        )
        self.closing_ctx = ClosingContext(
            dry_run=dry_run_active(settings),
            files=self.files,
            signature=build_signature(settings),
            validity_days=settings.signature_validity_days,
            telegram=telegram,
            email=email if hasattr(email, "send_with_attachment") else None,  # type: ignore[arg-type]
            clock=clock,
        )
        register_closing(self.bot, self.closing_ctx)
        register_contract(self.bot, self.db, self.closing_ctx)
        self.legal_bot: CrmBot | None = None
        if legal_telegram is not None:  # sin IDs permitidos solo responde /start (modo registro)
            self.legal_bot = build_legal_bot(
                self.db, legal_telegram, clock, settings, self.closing_ctx, self.files
            )
        self.mail_ctx = MailContext(settings=settings, keys=self.keys, clock=clock)
        register_mailboxes(self.bot, self.mail_ctx)
        register_f2(
            self.bot,
            F2Context(
                keys=tuple(self.keys),
                params=self.params,
                settings=settings,
                sender_name=settings.sender_name,
                kick_delivery=self._kick_delivery,
            ),
        )
        self.scheduler = CronScheduler(
            execution_timeout_s=EXECUTION_TIMEOUT_S, poll_interval_s=POLL_INTERVAL_S
        )
        self._snapshot_fail_count = 0
        self.snapshot_writer: DailyJsonlWriter | None = None
        snapshot_cb = None
        snapshot_key = self.settings.jev_snapshot_key.get_secret_value().strip()
        if self.settings.jev_snapshot_enabled and snapshot_key:
            snapshot_dir = self.settings.jev_snapshot_dir or (
                self.settings.data_dir / "jev_snapshot"
            )
            self.snapshot_writer = DailyJsonlWriter(
                snapshot_dir,
                tz=BOGOTA_TZ,
                clock=lambda: self.clock().timestamp(),
                retention_days=self.settings.jev_snapshot_retention_days,
            )
            snapshot_cb = self.run_snapshot_job

        register_jobs(
            self.scheduler,
            daily=self.run_daily_job,
            backup=self.run_backup_job,
            followup=self.run_followup_job,
            snapshot=snapshot_cb,
        )

    async def startup(self) -> None:
        """Siembra del CTO, avisos de configuración, barrido de recuperación y latido."""
        with self.db.tx() as tx:
            seed_cto(tx, self.settings, self.clock())
        notices = [config_notice(w) for w in self.config_warnings]
        notices += [holiday_notice(w) for w in self.holiday_warnings]
        for w in self.holiday_warnings:
            logger.warning("Festivo extraordinario ignorado: {} ({})", w.entry, w.reason)
        if self.settings.assistant_enabled and self.assistant_llm is None:  # VCRM-A31
            notices.append(
                "El asistente comercial está activado pero falta OPENAI_API_KEY: "
                "queda no disponible hasta que se configure."
            )
        if (
            self.settings.jev_snapshot_enabled
            and not self.settings.jev_snapshot_key.get_secret_value().strip()
        ):
            notices.append(
                "El módulo CRM-consejero (instantánea) está activado pero falta "
                "JERICO_CRM_JEV_SNAPSHOT_KEY: queda desactivado hasta que se configure."
            )
        notices += self._legal_bot_notices()
        await self._notify_cto(notices)
        await self.run_daily_job()
        await self.run_followup_job()  # activa F2 si procede y avisa si falta configuración
        self.heartbeat()

    def _legal_bot_notices(self) -> list[str]:
        """Avisos de arranque del bot del abogado: solo nombres de variable, nunca valores."""
        if self.legal_bot is None:
            return []
        allowed, rejected = parse_allowed_ids(self.settings.legal_allowed_ids)
        notices = []
        if not allowed:
            notices.append(
                "El bot del abogado está activo en modo registro: pídele que escriba /start y "
                "pon el ID que reciba en JERICO_CRM_LEGAL_ALLOWED_IDS y dalo de alta con /alta."
            )
        if rejected:
            notices.append(
                f"{len(rejected)} entrada(s) de JERICO_CRM_LEGAL_ALLOWED_IDS no son numéricas "
                "y se ignoraron."
            )
        return notices

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

    def _sweep_context(self) -> SweepContext:
        return SweepContext(
            db=self.db,
            telegram=self.telegram,
            email=self.email,
            inbox=self.inbox,
            settings=self.settings,
            params=self.params,
            keys=tuple(self.keys),
        )

    async def run_followup_job(self) -> None:
        """Barrido único de F2 (cada minuto): buzón, expiración, generación y entrega."""
        await followup_sweep(self._sweep_context(), self.clock())
        await contract_sweep(self.db, self.closing_ctx, self.clock())  # spec 004 §5
        await poll_mailboxes(self.db, self.mail_ctx, self.clock())  # spec 004 §7

    def _kick_delivery(self) -> None:
        """Primer intento de envío en línea tras un ✅ dentro de franja y cupo (D-3)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - el bot siempre corre dentro del bucle
            return
        task = loop.create_task(deliver_now(self._sweep_context(), self.clock()))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

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

    async def run_snapshot_job(self) -> None:
        """Corrida diaria de la instantánea de CRM-consejero (spec 007, VJC-006, VJC-009)."""
        if self.snapshot_writer is None:
            return
        snapshot_key = self.settings.jev_snapshot_key.get_secret_value().strip()
        try:
            report = await asyncio.to_thread(
                run_snapshot,
                self.db,
                self.snapshot_writer,
                key=snapshot_key,
                clock=lambda: self.clock().timestamp(),
                retention_days=self.settings.jev_snapshot_retention_days,
            )
            if not report.success:
                self._snapshot_fail_count += 1
                logger.warning(
                    "Corrida de instantánea finalizó con fallos. Fallos acumulados: {}",
                    self._snapshot_fail_count,
                )
        except Exception as exc:  # noqa: BLE001
            self._snapshot_fail_count += 1
            logger.warning(
                "Falla ordinaria en corrida de instantánea: {}. Fallos acumulados: {}",
                exc,
                self._snapshot_fail_count,
            )

    def heartbeat(self) -> None:
        """Latido para el *healthcheck* del contenedor (mtime)."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "heartbeat").touch()

    async def serve(self, stop: asyncio.Event) -> None:
        await self.scheduler.start()
        try:
            loops = [self.bot.run_polling(stop, heartbeat=self.heartbeat), self.worker.run(stop)]
            if self.legal_bot is not None:  # spec 004: segundo bot, mismo servicio y misma base
                loops.append(self.legal_bot.run_polling(stop))
            await asyncio.gather(*loops)
        finally:
            await self.scheduler.stop()

    def close(self) -> None:
        if self.assistant_memory is not None:
            self.assistant_memory.close()
        self.db.close()


async def run_service(
    settings: CrmSettings,
    *,
    telegram: TelegramPort | None = None,
    email: EmailSender | None = None,
    runner: CommandRunner | None = None,
    clock: Callable[[], datetime] = utcnow,
    stop: asyncio.Event | None = None,
    inbox: InboxPort | None = None,
    legal_telegram: TelegramPort | None = None,
) -> None:
    """Arranca el servicio; `SIGTERM`/`SIGINT` → parada ordenada."""
    legal_client = None
    legal_token = _secret(settings.legal_bot_token)
    if legal_telegram is None and legal_token:  # pragma: no cover - adaptador real (red)
        legal_client = HttpxTelegramClient(legal_token)
        legal_telegram = legal_client
    client = None
    if telegram is None:  # pragma: no cover - adaptador real (red)
        client = HttpxTelegramClient(_secret(settings.telegram_bot_token))
        telegram = client
    app = CrmApp(
        settings,
        telegram=telegram,
        email=email or outbound_email(settings),
        runner=runner or SubprocessRunner(),
        clock=clock,
        inbox=inbox,
        legal_telegram=legal_telegram,
    )
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        await app.startup()
        logger.info("jerico-crm iniciado (fase {})", CURRENT_PHASE)
        await app.serve(stop)
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)
        app.close()
        logger.info("jerico-crm detenido")
        if client is not None:  # pragma: no cover - adaptador real (red)
            await client.aclose()
        if legal_client is not None:  # pragma: no cover - adaptador real (red)
            await legal_client.aclose()


def main(settings: CrmSettings | None = None) -> None:
    """Entrypoint `jerico-crm`: sin token o sin clave HMAC sale con código 2."""
    settings = settings or CrmSettings()
    missing = missing_secrets(settings)
    if missing:
        logger.error("jerico-crm no arranca: falta la variable {}", ", ".join(missing))
        raise SystemExit(EXIT_CONFIG)
    try:
        migrate_if_needed(Path(settings.data_dir) / "crm.db")
    except MigrationError as exc:
        logger.error("jerico-crm no arranca: la migración de la base falló: {}", exc)
        raise SystemExit(EXIT_MIGRATION) from exc
    asyncio.run(run_service(settings))


__all__ = [
    "EXIT_CONFIG",
    "EXIT_MIGRATION",
    "STARTUP_NOTICE_KIND",
    "build_assistant_llm",
    "build_signature",
    "outbound_email",
    "CrmApp",
    "fingerprint_keys",
    "main",
    "missing_secrets",
    "run_service",
    "utcnow",
]
