"""Respaldo nocturno cifrado fuera de la máquina (plan §8.6; VCRM-097, 098).

Instantánea con conexión propia de solo lectura → `tar.gz` con adjuntos y evidencias →
`age` (clave pública) → `rclone copyto`; retención por la fecha del nombre con
`rclone deletefile`. Cualquier fallo avisa al CTO por Telegram y por correo
(no crítico; decisión N-11).
"""

import asyncio
import shutil
import sqlite3
import tarfile
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jerico.crm import repo
from jerico.crm.db import CrmDatabase
from jerico.crm.model import Channel, Role
from jerico.crm.ports import CommandResult, CommandRunner, EmailSender, TelegramPort
from jerico.crm.timeutil import format_local, from_iso, to_iso

LAST_OK_KEY = "last_backup_ok_at"
NOTICE_KIND = "aviso_respaldo"
NOTICE_SUBJECT = "Falló el respaldo nocturno del CRM"
MAX_RETENTION_DAYS = 30  # tope legal (J-08)
COMMAND_TIMEOUT_S = 600.0
_PREFIX = "crm-"
_SUFFIX = ".tar.gz.age"
_STAMP = "%Y%m%dT%H%M%SZ"
_STDERR_TAIL = 500


class _StepFailed(Exception):
    def __init__(self, step: str, cause: str) -> None:
        super().__init__(f"{step}: {cause}")
        self.step = step
        self.cause = cause


def backup_name(now: datetime) -> str:
    return f"{_PREFIX}{now.astimezone(UTC).strftime(_STAMP)}{_SUFFIX}"


def expired_backups(names: Iterable[str], now: datetime, retention_days: int) -> list[str]:
    """Nombres con fecha de más de `min(retention_days, 30)` días; ignora los ajenos."""
    limit = timedelta(days=min(retention_days, MAX_RETENTION_DAYS))
    expired = []
    for name in names:
        if not (name.startswith(_PREFIX) and name.endswith(_SUFFIX)):
            continue
        try:
            taken = datetime.strptime(name[len(_PREFIX) : -len(_SUFFIX)], _STAMP)
        except ValueError:
            continue
        if now - taken.replace(tzinfo=UTC) >= limit:
            expired.append(name)
    return expired


def _snapshot(source: Path, dest: Path) -> None:
    """Conexión propia `mode=ro`, abierta y cerrada en el hilo que la usa (O3)."""
    src = sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _archive(snapshot: Path, attachments_dir: Path, dest: Path) -> None:
    with tarfile.open(dest, "w:gz") as tar:
        tar.add(snapshot, arcname="crm.db")
        if attachments_dir.exists():
            tar.add(attachments_dir, arcname="attachments")


async def _command(runner: CommandRunner, step: str, argv: list[str]) -> CommandResult:
    result = await runner.run(argv, COMMAND_TIMEOUT_S)
    if result.returncode != 0:
        raise _StepFailed(step, f"{argv[0]} {argv[1]} salió con código {result.returncode}")
    return result


async def _perform(
    db: CrmDatabase,
    runner: CommandRunner,
    now: datetime,
    work: Path,
    attachments_dir: Path,
    recipient: str,
    remote: str,
    retention_days: int,
) -> None:
    name = backup_name(now)
    snapshot, archive, encrypted = work / "crm.db", work / "crm.tar.gz", work / name
    try:
        await asyncio.to_thread(_snapshot, db.path, snapshot)
        await asyncio.to_thread(_archive, snapshot, attachments_dir, archive)
    except Exception as exc:
        raise _StepFailed("generación", type(exc).__name__) from exc
    await _command(
        runner,
        "cifrado",
        ["age", "--encrypt", "--recipient", recipient, "--output", str(encrypted), str(archive)],
    )
    await _command(
        runner, "transferencia", ["rclone", "copyto", str(encrypted), f"{remote}/{name}"]
    )
    step = "eliminación por vencimiento"
    listing = await _command(runner, step, ["rclone", "lsf", remote])
    names = [line.strip() for line in listing.stdout.splitlines() if line.strip()]
    for old in expired_backups(names, now, retention_days):
        await _command(runner, step, ["rclone", "deletefile", f"{remote}/{old}"])


async def _notify_failure(
    db: CrmDatabase,
    telegram: TelegramPort,
    email: EmailSender,
    now: datetime,
    failure: _StepFailed,
) -> None:
    with db.read() as conn:
        last = repo.get_meta(conn, LAST_OK_KEY)
        ctos = repo.active_users(conn, Role.CTO)
    last_text = format_local(from_iso(last)) if last else "ninguno"
    text = (
        f"⚠️ Falló el respaldo nocturno del CRM ({format_local(now)}).\n"
        f"Paso: {failure.step}. Causa: {failure.cause}.\n"
        f"Último respaldo correcto: {last_text}."
    )
    for cto in ctos:
        for channel in (Channel.TELEGRAM, Channel.EMAIL):
            if channel == Channel.TELEGRAM:
                result = await telegram.send_message(cto.telegram_id, text, None)
            else:
                result = await email.send(cto.email, NOTICE_SUBJECT, text)
            if not result.delivered:
                with db.tx() as tx:
                    repo.record_failed_noncritical(
                        tx,
                        recipient_user_id=cto.id,
                        kind=NOTICE_KIND,
                        error=result.error,
                        now=now,
                        channel=channel,
                    )


async def run_backup(
    db: CrmDatabase,
    telegram: TelegramPort,
    email: EmailSender,
    runner: CommandRunner,
    now: datetime,
    *,
    attachments_dir: Path,
    work_dir: Path,
    recipient: str | None,
    remote: str | None,
    retention_days: int,
) -> bool:
    """Ejecuta el respaldo; `True` si todo fue bien. Temporales borrados siempre."""
    try:
        if not recipient:
            raise _StepFailed("configuración", "falta JERICO_CRM_BACKUP_AGE_RECIPIENT")
        if not remote:
            raise _StepFailed("configuración", "falta JERICO_CRM_BACKUP_REMOTE")
        work_dir.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="backup-", dir=work_dir))
        try:
            await _perform(
                db, runner, now, work, attachments_dir, recipient, remote, retention_days
            )
        finally:
            shutil.rmtree(work, ignore_errors=True)
    except _StepFailed as failure:
        await _notify_failure(db, telegram, email, now, failure)
        return False
    with db.tx() as tx:
        repo.set_meta(tx, LAST_OK_KEY, to_iso(now))
    return True


class SubprocessRunner:
    """`CommandRunner` real sobre `asyncio.create_subprocess_exec` (sin *shell*)."""

    async def run(self, argv: list[str], timeout_s: float) -> CommandResult:
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        except FileNotFoundError:
            return CommandResult(returncode=127, stderr_tail=f"{argv[0]}: no encontrado")
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout_s)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return CommandResult(returncode=124, stderr_tail="tiempo agotado")
        return CommandResult(
            returncode=proc.returncode if proc.returncode is not None else 1,
            stderr_tail=err.decode(errors="replace")[-_STDERR_TAIL:],
            stdout=out.decode(errors="replace"),
        )


__all__ = [
    "LAST_OK_KEY",
    "MAX_RETENTION_DAYS",
    "NOTICE_KIND",
    "SubprocessRunner",
    "backup_name",
    "expired_backups",
    "run_backup",
]
