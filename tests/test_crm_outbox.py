"""T15 — Outbox de notificaciones críticas: persistencia, calendario 0/1/5 min y trabajador."""

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from crm_support import FakeClock, FakeEmailSender, FakeTelegram
from jerico.crm import repo
from jerico.crm.db import CrmDatabase
from jerico.crm.model import Channel, OutboxItem, OutboxStatus, Role
from jerico.crm.outbox import OutboxWorker, enqueue_critical, next_attempt_at
from jerico.crm.timeutil import from_iso, to_iso

T0 = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
CTO_TG, LAWYER_TG = 1001, 2002
LAWYER_MAIL = "abogado@kaisen.test"


def _setup(tmp_path: Path) -> tuple[CrmDatabase, int, int]:
    db = CrmDatabase(tmp_path / "crm.db")
    with db.tx() as tx:
        cto = repo.insert_user(tx, telegram_id=CTO_TG, role=Role.CTO, email="cto@k.test", now=T0)
        lawyer = repo.insert_user(
            tx, telegram_id=LAWYER_TG, role=Role.LAWYER, email=LAWYER_MAIL, now=T0
        )
    return db, cto.id, lawyer.id


def _enqueue(
    db: CrmDatabase, recipient: int, channel: Channel, key: str, now: datetime = T0
) -> int:
    with db.tx() as tx:
        return enqueue_critical(
            tx,
            kind="aceptacion",
            channel=channel,
            recipient_user_id=recipient,
            lead_id=None,
            subject="Lead aceptado",
            body="Lead #1 aceptado",
            key=key,
            now=now,
        )


def _item(db: CrmDatabase, outbox_id: int) -> OutboxItem:
    with db.read() as conn:
        item = repo.get_outbox(conn, outbox_id)
    assert item is not None
    return item


def _worker(
    db: CrmDatabase,
    clock: FakeClock,
    tg: FakeTelegram | None = None,
    mail: FakeEmailSender | None = None,
    **kwargs: object,
) -> OutboxWorker:
    return OutboxWorker(
        db,
        tg or FakeTelegram(),
        mail or FakeEmailSender(),
        clock.now,
        **kwargs,  # type: ignore[arg-type]
    )


# --- Calendario puro (VCRM-127) -----------------------------------------------------------


def test_vcrm127_next_attempt_offsets_0_1_5_min_then_none() -> None:
    assert next_attempt_at(T0, 0) == T0
    assert next_attempt_at(T0, 1) == T0 + timedelta(seconds=60)
    assert next_attempt_at(T0, 2) == T0 + timedelta(seconds=300)
    assert next_attempt_at(T0, 3) is None
    assert next_attempt_at(T0, 4) is None


# --- Persistencia (VCRM-049) ----------------------------------------------------------------


def test_vcrm049_row_persisted_pending_before_first_attempt(tmp_path: Path) -> None:
    db, cto, _ = _setup(tmp_path)
    oid = _enqueue(db, cto, Channel.TELEGRAM, "k1")
    item = _item(db, oid)
    assert item.status == OutboxStatus.PENDING
    assert item.critical == 1
    assert item.attempts == 0
    assert item.first_attempt_at is None
    assert item.next_attempt_at == to_iso(T0)

    seen: list[OutboxItem] = []

    class SpyTelegram(FakeTelegram):
        async def send_message(self, chat_id, text, buttons=None):  # type: ignore[no-untyped-def]
            seen.append(_item(db, oid))
            return await super().send_message(chat_id, text, buttons)

    clock = FakeClock(T0)
    asyncio.run(_worker(db, clock, SpyTelegram()).deliver_due())
    assert seen and seen[0].status == OutboxStatus.PENDING
    item = _item(db, oid)
    assert item.status == OutboxStatus.DELIVERED
    assert item.attempts == 1
    assert item.first_attempt_at == to_iso(T0)
    assert item.provider_message_id is not None
    assert item.next_attempt_at is None
    db.close()


def test_vcrm049_idempotency_key_avoids_duplicate_rows(tmp_path: Path) -> None:
    db, cto, _ = _setup(tmp_path)
    first = _enqueue(db, cto, Channel.TELEGRAM, "accept:1:cto")
    second = _enqueue(db, cto, Channel.TELEGRAM, "accept:1:cto")
    assert first == second
    with db.read() as conn:
        count = conn.execute("SELECT COUNT(*) FROM crm_outbox").fetchone()[0]
    assert count == 1
    db.close()


def test_vcrm049_enqueue_rejects_unknown_channel(tmp_path: Path) -> None:
    db, cto, _ = _setup(tmp_path)
    with pytest.raises((ValueError, sqlite3.IntegrityError)):
        _enqueue(db, cto, "fax", "k")  # type: ignore[arg-type]
    db.close()


# --- Entrega, reintentos y fallos (VCRM-127, 047, 012) ---------------------------------------


def test_vcrm127_successive_failures_attempt_at_0_1_5_min_then_failed(tmp_path: Path) -> None:
    db, cto, _ = _setup(tmp_path)
    clock = FakeClock(T0)
    tg = FakeTelegram()
    tg.fail_next(CTO_TG, times=10)
    failed: list[int] = []
    worker = _worker(db, clock, tg, on_failed=lambda tx, item, now: failed.append(item.id))
    oid = _enqueue(db, cto, Channel.TELEGRAM, "k")
    attempt_times: list[datetime] = []
    for _ in range(40):  # cada 15 s durante 10 min
        before = len(tg.attempts)
        asyncio.run(worker.deliver_due())
        if len(tg.attempts) > before:
            attempt_times.append(clock.now())
        clock.advance(seconds=15)
    assert attempt_times == [T0, T0 + timedelta(minutes=1), T0 + timedelta(minutes=5)]
    item = _item(db, oid)
    assert item.status == OutboxStatus.FAILED
    assert item.attempts == 3
    assert item.next_attempt_at is None
    assert item.last_error == "sendMessage: HTTP 502"
    assert failed == [oid]
    db.close()


def test_vcrm127_retry_succeeds_on_second_attempt(tmp_path: Path) -> None:
    db, cto, _ = _setup(tmp_path)
    clock = FakeClock(T0)
    tg = FakeTelegram()
    tg.fail_next(CTO_TG)
    worker = _worker(db, clock, tg)
    oid = _enqueue(db, cto, Channel.TELEGRAM, "k")
    asyncio.run(worker.deliver_due())
    assert _item(db, oid).next_attempt_at == to_iso(T0 + timedelta(minutes=1))
    clock.advance(seconds=30)
    asyncio.run(worker.deliver_due())
    assert len(tg.attempts) == 1
    clock.advance(seconds=30)
    asyncio.run(worker.deliver_due())
    item = _item(db, oid)
    assert item.status == OutboxStatus.DELIVERED
    assert item.attempts == 2
    assert item.first_attempt_at == to_iso(T0)
    db.close()


def test_vcrm047_failing_recipient_does_not_delay_others(tmp_path: Path) -> None:
    db, cto, lawyer = _setup(tmp_path)
    clock = FakeClock(T0)
    tg, mail = FakeTelegram(), FakeEmailSender()
    tg.fail_next(CTO_TG, times=3)
    ids = [
        _enqueue(db, cto, Channel.TELEGRAM, "a"),
        _enqueue(db, lawyer, Channel.TELEGRAM, "b"),
        _enqueue(db, lawyer, Channel.EMAIL, "c"),
    ]
    asyncio.run(_worker(db, clock, tg, mail).deliver_due())
    items = [_item(db, i) for i in ids]
    assert all(i.first_attempt_at == to_iso(T0) for i in items)
    assert items[0].status == OutboxStatus.PENDING
    assert items[1].status == OutboxStatus.DELIVERED
    assert items[2].status == OutboxStatus.DELIVERED
    assert [m.to for m in mail.sent] == [LAWYER_MAIL]
    assert mail.sent[0].subject == "Lead aceptado"
    assert [s.chat_id for s in tg.sent] == [LAWYER_TG]
    db.close()


def test_vcrm047_exception_in_one_send_is_isolated(tmp_path: Path) -> None:
    db, cto, lawyer = _setup(tmp_path)
    clock = FakeClock(T0)

    class BoomTelegram(FakeTelegram):
        async def send_message(self, chat_id, text, buttons=None):  # type: ignore[no-untyped-def]
            if chat_id == CTO_TG:
                raise ConnectionError("boom")
            return await super().send_message(chat_id, text, buttons)

    a = _enqueue(db, cto, Channel.TELEGRAM, "a")
    b = _enqueue(db, lawyer, Channel.TELEGRAM, "b")
    asyncio.run(_worker(db, clock, BoomTelegram()).deliver_due())
    assert _item(db, a).status == OutboxStatus.PENDING
    assert _item(db, a).attempts == 1
    assert _item(db, a).last_error == "ConnectionError"
    assert _item(db, b).status == OutboxStatus.DELIVERED
    db.close()


def test_vcrm012_permanent_failure_marks_failed_without_retries(tmp_path: Path) -> None:
    db, _, lawyer = _setup(tmp_path)
    clock = FakeClock(T0)
    mail = FakeEmailSender(configured=False)
    failed: list[int] = []
    worker = _worker(db, clock, mail=mail, on_failed=lambda tx, item, now: failed.append(item.id))
    oid = _enqueue(db, lawyer, Channel.EMAIL, "k")
    asyncio.run(worker.deliver_due())
    clock.advance(minutes=10)
    asyncio.run(worker.deliver_due())
    item = _item(db, oid)
    assert item.status == OutboxStatus.FAILED
    assert item.attempts == 0
    assert item.next_attempt_at is None
    assert item.last_error == "mailbox_not_configured"
    assert failed == [oid]
    db.close()


def test_vcrm012_unknown_recipient_is_permanent_failure(tmp_path: Path) -> None:
    db, _, _ = _setup(tmp_path)
    clock = FakeClock(T0)
    tg = FakeTelegram()
    oid = _enqueue(db, 999, Channel.TELEGRAM, "k")
    asyncio.run(_worker(db, clock, tg).deliver_due())
    item = _item(db, oid)
    assert item.status == OutboxStatus.FAILED
    assert item.last_error == "recipient_not_found"
    assert tg.attempts == []
    db.close()


def test_vcrm012_noncritical_failed_rows_are_never_retried(tmp_path: Path) -> None:
    db, cto, _ = _setup(tmp_path)
    clock = FakeClock(T0)
    tg = FakeTelegram()
    with db.tx() as tx:
        repo.record_failed_noncritical(tx, recipient_user_id=cto, kind="reply", error="x", now=T0)
    clock.advance(minutes=10)
    asyncio.run(_worker(db, clock, tg).deliver_due())
    assert tg.attempts == []
    db.close()


# --- Reinicio (VCRM-049) --------------------------------------------------------------------


def test_vcrm049_after_reopen_pending_gets_only_remaining_attempts(tmp_path: Path) -> None:
    db, cto, _ = _setup(tmp_path)
    clock = FakeClock(T0)
    tg = FakeTelegram()
    tg.fail_next(CTO_TG, times=10)
    oid = _enqueue(db, cto, Channel.TELEGRAM, "k")
    asyncio.run(_worker(db, clock, tg).deliver_due())
    db.close()

    db = CrmDatabase(tmp_path / "crm.db")
    clock.advance(seconds=200)  # el segundo intento (60 s) quedó atrasado durante la caída
    worker = _worker(db, clock, tg)
    asyncio.run(worker.deliver_due())
    item = _item(db, oid)
    assert item.attempts == 2
    assert item.first_attempt_at == to_iso(T0)
    assert from_iso(item.next_attempt_at or "") == T0 + timedelta(seconds=300)
    clock.advance(seconds=100)
    asyncio.run(worker.deliver_due())
    clock.advance(minutes=30)
    asyncio.run(worker.deliver_due())
    assert len(tg.attempts) == 3
    assert _item(db, oid).status == OutboxStatus.FAILED
    db.close()


# --- Trabajador: kick e intervalo (VCRM-047) -------------------------------------------------


def test_vcrm047_kick_triggers_attempt_without_waiting_interval(tmp_path: Path) -> None:
    db, cto, _ = _setup(tmp_path)
    clock = FakeClock(T0)
    tg = FakeTelegram()
    worker = _worker(db, clock, tg, interval_s=3600)

    async def scenario() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(worker.run(stop))
        await asyncio.sleep(0.01)  # primer ciclo vacío; queda esperando
        oid = _enqueue(db, cto, Channel.TELEGRAM, "k")
        worker.kick()
        for _ in range(100):
            if _item(db, oid).status == OutboxStatus.DELIVERED:
                break
            await asyncio.sleep(0.01)
        stop.set()
        await asyncio.wait_for(task, timeout=1)
        assert _item(db, oid).first_attempt_at == to_iso(T0)

    asyncio.run(scenario())
    assert len(tg.sent) == 1
    db.close()


def test_vcrm049_worker_delivers_pending_on_start_and_on_interval(tmp_path: Path) -> None:
    db, cto, _ = _setup(tmp_path)
    clock = FakeClock(T0)
    tg = FakeTelegram()
    first = _enqueue(db, cto, Channel.TELEGRAM, "a")
    worker = _worker(db, clock, tg, interval_s=0.01)

    async def scenario() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(worker.run(stop))
        await asyncio.sleep(0.02)
        assert _item(db, first).status == OutboxStatus.DELIVERED
        second = _enqueue(db, cto, Channel.TELEGRAM, "b")  # sin kick: lo toma el intervalo
        for _ in range(100):
            if _item(db, second).status == OutboxStatus.DELIVERED:
                break
            await asyncio.sleep(0.01)
        assert _item(db, second).status == OutboxStatus.DELIVERED
        stop.set()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(scenario())
    db.close()
