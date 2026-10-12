"""*Outbox* de notificaciones críticas: calendario 0/1/5 min y trabajador (plan §8.5).

VCRM-049 (persistida antes del intento), 127 (tres intentos y «fallida»), 047 (primer intento
inmediato e independencia entre destinatarios); cadena de escalado `escalate` (VCRM-050, 087,
107, 128–130, 140). Regla: ningún `with db.tx()` contiene un `await`.
"""

import asyncio
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta

from jerico.crm import repo
from jerico.crm.db import CrmDatabase
from jerico.crm.model import AlertKind, Channel, OutboxItem, OutboxStatus, Role, User
from jerico.crm.permissions import commercial_recipients
from jerico.crm.ports import EmailSender, SendResult, TelegramPort
from jerico.crm.render import short_id
from jerico.crm.timeutil import from_iso, to_iso

logger = logging.getLogger(__name__)

OFFSETS = (timedelta(0), timedelta(seconds=60), timedelta(seconds=300))
MAX_ATTEMPTS = len(OFFSETS)
DEFAULT_INTERVAL_S = 5.0

# Críticas cuyo fallo activa el respaldo (VCRM-050); deben coincidir con las de `leads`.
ESCALATED_KINDS = frozenset({"aceptacion", "retractacion", "handoff"})
BACKUP_KIND = "respaldo_correo"  # VCRM-050
BACKUP_FAILED_KIND = "fallo_respaldo"  # VCRM-129
SUPPRESSION_KIND = "supresion_copias"  # VCRM-154

OnFailed = Callable[[sqlite3.Connection, OutboxItem, datetime], None]


def next_attempt_at(first_attempt_at: datetime, attempts_done: int) -> datetime | None:
    """Instante del siguiente intento según el calendario; `None` tras el tercero (puro)."""
    if attempts_done >= MAX_ATTEMPTS:
        return None
    return first_attempt_at + OFFSETS[attempts_done]


def enqueue_critical(
    tx: sqlite3.Connection,
    *,
    kind: str,
    channel: Channel,
    recipient_user_id: int,
    lead_id: int | None,
    subject: str | None,
    body: str,
    key: str,
    now: datetime,
    origin_outbox_id: int | None = None,
) -> int:
    """Persiste la crítica `pendiente` dentro de `tx`; la clave de idempotencia evita duplicados."""
    return repo.insert_outbox(
        tx,
        key=key,
        kind=kind,
        channel=Channel(channel).value,
        recipient_user_id=recipient_user_id,
        lead_id=lead_id,
        subject=subject,
        body=body,
        now=now,
        origin_outbox_id=origin_outbox_id,
    )


class OutboxWorker:
    """Tarea asyncio: entrega las debidas cada `interval_s` o de inmediato tras `kick()`."""

    def __init__(
        self,
        db: CrmDatabase,
        telegram: TelegramPort,
        email: EmailSender,
        clock: Callable[[], datetime],
        *,
        interval_s: float = DEFAULT_INTERVAL_S,
        on_failed: OnFailed | None = None,
    ) -> None:
        self._db = db
        self._telegram = telegram
        self._email = email
        self._clock = clock
        self._interval_s = interval_s
        self._on_failed = on_failed
        self._wake = asyncio.Event()

    def kick(self) -> None:
        """Despierta al trabajador sin esperar al intervalo (VCRM-047)."""
        self._wake.set()

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await self.deliver_due()
            waiters = [
                asyncio.ensure_future(self._wake.wait()),
                asyncio.ensure_future(stop.wait()),
            ]
            await asyncio.wait(
                waiters, timeout=self._interval_s, return_when=asyncio.FIRST_COMPLETED
            )
            for waiter in waiters:
                waiter.cancel()
            self._wake.clear()

    async def deliver_due(self) -> int:
        """Intenta todas las debidas en paralelo; cada resultado se guarda en su propia tx."""
        now = self._clock()
        with self._db.read() as conn:
            due = repo.due_outbox(conn, now)
            targets = [self._target(conn, item) for item in due]
        results = await asyncio.gather(
            *(self._send(item, target) for item, target in zip(due, targets, strict=True)),
            return_exceptions=True,
        )
        for item, result in zip(due, results, strict=True):
            if isinstance(result, BaseException):
                result = SendResult(delivered=False, error=type(result).__name__)
            with self._db.tx() as tx:
                self._record(tx, item, result, now)
        return len(due)

    @staticmethod
    def _target(conn: sqlite3.Connection, item: OutboxItem) -> int | str | None:
        user = repo.get_user(conn, item.recipient_user_id)
        if user is None:
            return None
        return user.telegram_id if item.channel == Channel.TELEGRAM else user.email

    async def _send(self, item: OutboxItem, target: int | str | None) -> SendResult:
        if target is None:
            return SendResult(delivered=False, error="recipient_not_found", permanent=True)
        if item.channel == Channel.TELEGRAM:
            return await self._telegram.send_message(int(target), item.body or "")
        return await self._email.send(str(target), item.subject or "", item.body or "")

    def _record(
        self, tx: sqlite3.Connection, item: OutboxItem, result: SendResult, now: datetime
    ) -> None:
        first = from_iso(item.first_attempt_at) if item.first_attempt_at else now
        if result.delivered:
            repo.update_outbox_attempt(
                tx,
                item.id,
                status=OutboxStatus.DELIVERED,
                attempts=item.attempts + 1,
                first_attempt_at=first,
                next_attempt_at=None,
                message_id=result.message_id,
            )
            return
        attempts = item.attempts if result.permanent else item.attempts + 1
        nxt = None if result.permanent else next_attempt_at(first, attempts)
        status = OutboxStatus.PENDING if nxt else OutboxStatus.FAILED
        repo.update_outbox_attempt(
            tx,
            item.id,
            status=status,
            attempts=attempts,
            first_attempt_at=first,
            next_attempt_at=nxt,
            error=result.error,
        )
        logger.warning("outbox %s: intento fallido (%s)", item.id, result.error)
        if status == OutboxStatus.FAILED and self._on_failed is not None:
            failed = replace(
                item,
                status=status.value,
                attempts=attempts,
                first_attempt_at=to_iso(first),
                next_attempt_at=None,
                last_error=result.error,
            )
            self._on_failed(tx, failed, now)


def suppression_key(now: datetime, recipient_user_id: int, channel: Channel, ids: list[int]) -> str:
    """Clave de idempotencia del aviso de supresión; termina en los ids de los leads (VCRM-154)."""
    joined = "-".join(str(i) for i in ids)
    return f"{SUPPRESSION_KIND}:{to_iso(now)}:{recipient_user_id}:{Channel(channel).value}:{joined}"


def suppression_lead_ids(item: OutboxItem) -> list[int]:
    """Leads cubiertos por un aviso de supresión, leídos de su clave (VCRM-155)."""
    return [int(i) for i in item.idempotency_key.rsplit(":", 1)[1].split("-")]


# --- Cadena de escalado (plan §8.5) ---------------------------------------------------------


def _escalation_recipients(conn: sqlite3.Connection, lead_id: int | None) -> list[User]:
    """CTO activo y comercial del lead (4.5), sin repetir si el comercial es el CTO."""
    active = repo.active_users(conn)
    lead = None if lead_id is None else repo.get_lead(conn, lead_id)
    pool = [u for u in active if u.role == Role.CTO]
    if lead is not None:
        pool += commercial_recipients(lead, active)
    unique: dict[int, User] = {}
    for user in pool:
        unique.setdefault(user.id, user)
    return list(unique.values())


def _describe(conn: sqlite3.Connection, item: OutboxItem) -> tuple[User | None, str]:
    user = repo.get_user(conn, item.recipient_user_id)
    who = f"{user.role} {user.email}" if user else f"usuario {item.recipient_user_id}"
    return user, f"«{item.kind}» a {who} por {item.channel}"


def escalate(tx: sqlite3.Connection, item: OutboxItem, now: datetime) -> None:
    """Hook `on_failed`: solo se llama con la fila ya «fallida» (VCRM-128)."""
    sid = short_id(item.lead_id) if item.lead_id is not None else "sin lead"
    if item.kind in ESCALATED_KINDS:
        repo.create_alert(  # VCRM-087
            tx,
            kind=AlertKind.NOTIFICATION_FAILED,
            now=now,
            lead_id=item.lead_id,
            outbox_id=item.id,
        )
        failed_user, described = _describe(tx, item)
        cto_telegram = (
            failed_user is not None
            and failed_user.role == Role.CTO
            and item.channel == Channel.TELEGRAM
        )
        for user in _escalation_recipients(tx, item.lead_id):  # VCRM-050
            body = (
                f"No se pudo entregar la notificación del lead {sid}.\n"
                f"Destinatario y canal que fallaron: {described}."
            )
            if cto_telegram and user.role == Role.CTO:  # VCRM-107
                body += f"\n\nContenido completo:\n{item.body or ''}"
            enqueue_critical(
                tx,
                kind=BACKUP_KIND,
                channel=Channel.EMAIL,
                recipient_user_id=user.id,
                lead_id=item.lead_id,
                subject=f"Respaldo: notificación fallida del lead {sid}",
                body=body,
                key=f"backup:{item.id}:{user.id}",
                now=now,
                origin_outbox_id=item.id,
            )
    elif item.kind == BACKUP_KIND:  # VCRM-129
        origin = (
            None if item.origin_outbox_id is None else repo.get_outbox(tx, item.origin_outbox_id)
        )
        original = _describe(tx, origin)[1] if origin else "desconocida"
        backup_user = repo.get_user(tx, item.recipient_user_id)
        backup_to = backup_user.email if backup_user else str(item.recipient_user_id)
        body = (
            f"Falló el correo de respaldo del lead {sid}.\n"
            f"Notificación original: {original}.\n"
            f"Destinatario del respaldo: {backup_to}."
        )
        for user in _escalation_recipients(tx, item.lead_id):
            for channel in (Channel.TELEGRAM, Channel.EMAIL):
                enqueue_critical(
                    tx,
                    kind=BACKUP_FAILED_KIND,
                    channel=channel,
                    recipient_user_id=user.id,
                    lead_id=item.lead_id,
                    subject=f"Aviso: falló el respaldo del lead {sid}"
                    if channel == Channel.EMAIL
                    else None,
                    body=body,
                    key=f"backupfail:{item.id}:{channel}:{user.id}",
                    now=now,
                    origin_outbox_id=item.id,
                )
    elif item.kind == SUPPRESSION_KIND:  # VCRM-155: una alerta por lead afectado
        for lead_id in suppression_lead_ids(item):
            repo.create_alert(
                tx,
                kind=AlertKind.SUPPRESSION_NOTICE_FAILED,
                now=now,
                lead_id=lead_id,
                outbox_id=item.id,
            )
    # BACKUP_FAILED_KIND y demás: nada más (VCRM-130); la alerta de VCRM-087 se mantiene.
