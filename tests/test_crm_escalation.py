"""Tests de la cadena de escalado: respaldo, aviso de fallo y alertas (T18).

Requisitos: VCRM-050, 087, 107, 128, 129, 130, 140 (integración).
"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from crm_support import FakeClock, FakeEmailSender, FakeTelegram
from jerico.crm import leads, repo
from jerico.crm.bot import CANCELLED, CrmBot
from jerico.crm.db import CrmDatabase
from jerico.crm.model import Channel, LeadState, Role, User
from jerico.crm.outbox import (
    BACKUP_FAILED_KIND,
    BACKUP_KIND,
    ESCALATED_KINDS,
    OutboxWorker,
    enqueue_critical,
    escalate,
)
from jerico.crm.parsing import build_callback
from jerico.crm.ports import Update
from jerico.crm.render import ALERT_MARK, short_id
from jerico.crm.team import DENIED

START = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
NOW = START + timedelta(days=1)
CTO_TG = 1000
COM_TG = 2000
LAW_TG = 3000
CONTENT = "Lead aceptado: contenido completo de la notificación"


@pytest.fixture
def db(tmp_path: Path) -> Iterator[CrmDatabase]:
    database = CrmDatabase(tmp_path / "crm.db")
    yield database
    database.close()


@pytest.fixture
def tg() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def mail() -> FakeEmailSender:
    return FakeEmailSender()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(NOW)


def _worker(db: CrmDatabase, tg: FakeTelegram, mail: FakeEmailSender, clock: FakeClock) -> Any:
    return OutboxWorker(db, tg, mail, clock.now, interval_s=3600, on_failed=escalate)


@pytest.fixture
def worker(db: CrmDatabase, tg: FakeTelegram, mail: FakeEmailSender, clock: FakeClock) -> Any:
    return _worker(db, tg, mail, clock)


@pytest.fixture
def users(db: CrmDatabase) -> dict[str, User]:
    with db.tx() as tx:
        return {
            "cto": repo.insert_user(
                tx, telegram_id=CTO_TG, role=Role.CTO, email="cto@k.co", now=START
            ),
            "com": repo.insert_user(
                tx, telegram_id=COM_TG, role=Role.COMMERCIAL, email="com@k.co", now=START
            ),
            "law": repo.insert_user(
                tx, telegram_id=LAW_TG, role=Role.LAWYER, email="law@k.co", now=START
            ),
        }


def _lead(db: CrmDatabase, owner: User) -> int:
    with db.tx() as tx:
        return repo.insert_lead(
            tx,
            assigned_user_id=owner.id,
            state=LeadState.ACCEPTED,
            now=START,
            fields={"name": "Ana Pérez"},
        )


def _notice(
    db: CrmDatabase,
    lead_id: int,
    user: User,
    channel: Channel,
    now: datetime,
    kind: str = leads.ACCEPT_NOTICE_KIND,
) -> int:
    with db.tx() as tx:
        return enqueue_critical(
            tx,
            kind=kind,
            channel=channel,
            recipient_user_id=user.id,
            lead_id=lead_id,
            subject="Aceptación" if channel == Channel.EMAIL else None,
            body=CONTENT,
            key=f"{kind}:{lead_id}:1:{channel}:{user.id}",
            now=now,
        )


def _rows(db: CrmDatabase, kind: str | None = None) -> list[Any]:
    with db.read() as conn:
        rows = conn.execute("SELECT * FROM crm_outbox ORDER BY id").fetchall()
    return [dict(r) for r in rows if kind is None or r["kind"] == kind]


def _deliver(worker: OutboxWorker) -> None:
    asyncio.run(worker.deliver_due())


def _drain(worker: OutboxWorker, clock: FakeClock, cycles: int = 20) -> None:
    """Recorre los calendarios de todas las filas encadenadas (intentos a 0, 1 y 5 min)."""
    for _ in range(cycles):
        _deliver(worker)
        clock.advance(seconds=60)


def _mails_to(mail: FakeEmailSender, to: str) -> list[Any]:
    return [m for m in mail.sent if m.to == to]


_next_update = iter(range(1, 100_000))


def _msg(user_tg: int, text: str) -> Update:
    return Update(
        update_id=next(_next_update),
        user_id=user_tg,
        chat_id=user_tg,
        chat_type="private",
        text=text,
    )


def _cb(user_tg: int, data: str) -> Update:
    return Update(
        update_id=next(_next_update),
        user_id=user_tg,
        chat_id=user_tg,
        chat_type="private",
        callback_data=data,
        callback_id=f"cb{user_tg}",
    )


def run(bot: CrmBot, u: Update) -> None:
    asyncio.run(bot.process_update(u))


# --- VCRM-128: nunca en paralelo a los intentos -------------------------------------------


def test_vcrm151_vcrm128_no_backup_while_attempts_remain(
    db: CrmDatabase,
    tg: FakeTelegram,
    mail: FakeEmailSender,
    clock: FakeClock,
    worker: OutboxWorker,
    users: dict[str, User],
) -> None:
    lead_id = _lead(db, users["com"])
    _notice(db, lead_id, users["law"], Channel.TELEGRAM, clock.now())
    tg.fail_next(LAW_TG, 3)
    _deliver(worker)
    clock.advance(seconds=60)
    _deliver(worker)
    assert _rows(db, BACKUP_KIND) == []
    assert mail.attempts == []
    clock.advance(seconds=240)
    _deliver(worker)  # tercer intento fallido → solo ahora se encola el respaldo
    assert len(_rows(db, BACKUP_KIND)) == 2
    assert mail.attempts == []
    _deliver(worker)
    assert {m.to for m in mail.sent} == {"cto@k.co", "com@k.co"}


def test_vcrm151_vcrm128_delivered_on_retry_never_escalates(
    db: CrmDatabase,
    tg: FakeTelegram,
    mail: FakeEmailSender,
    clock: FakeClock,
    worker: OutboxWorker,
    users: dict[str, User],
) -> None:
    lead_id = _lead(db, users["com"])
    _notice(db, lead_id, users["law"], Channel.TELEGRAM, clock.now())
    tg.fail_next(LAW_TG, 2)
    _drain(worker, clock)
    assert _rows(db, BACKUP_KIND) == []
    with db.read() as conn:
        assert repo.open_alerts(conn) == []


# --- VCRM-050 / 107: correo de respaldo --------------------------------------------------


def test_vcrm151_vcrm050_lawyer_telegram_failure_backup_to_cto_and_commercial(
    db: CrmDatabase,
    tg: FakeTelegram,
    mail: FakeEmailSender,
    clock: FakeClock,
    worker: OutboxWorker,
    users: dict[str, User],
) -> None:
    lead_id = _lead(db, users["com"])
    failed_id = _notice(db, lead_id, users["law"], Channel.TELEGRAM, clock.now())
    tg.fail_next(LAW_TG, 3)
    _drain(worker, clock)
    backups = _rows(db, BACKUP_KIND)
    assert all(r["origin_outbox_id"] == failed_id and r["channel"] == "email" for r in backups)
    for to in ("cto@k.co", "com@k.co"):
        (sent,) = _mails_to(mail, to)
        assert short_id(lead_id) in sent.subject and short_id(lead_id) in sent.body
        assert "law@k.co" in sent.body and "telegram" in sent.body
        assert CONTENT not in sent.body  # contenido completo solo si falló el Telegram del CTO


def test_vcrm151_vcrm050_lawyer_email_failure_triggers_backup(
    db: CrmDatabase,
    tg: FakeTelegram,
    mail: FakeEmailSender,
    clock: FakeClock,
    worker: OutboxWorker,
    users: dict[str, User],
) -> None:
    lead_id = _lead(db, users["com"])
    _notice(db, lead_id, users["law"], Channel.EMAIL, clock.now())
    mail.fail_next("law@k.co", 3)
    _drain(worker, clock)
    for to in ("cto@k.co", "com@k.co"):
        (sent,) = _mails_to(mail, to)
        assert "law@k.co" in sent.body and "email" in sent.body


@pytest.mark.parametrize("kind", sorted(ESCALATED_KINDS))
def test_vcrm151_vcrm050_single_backup_when_commercial_is_cto(
    db: CrmDatabase,
    tg: FakeTelegram,
    mail: FakeEmailSender,
    clock: FakeClock,
    worker: OutboxWorker,
    users: dict[str, User],
    kind: str,
) -> None:
    lead_id = _lead(db, users["cto"])
    _notice(db, lead_id, users["law"], Channel.TELEGRAM, clock.now(), kind=kind)
    tg.fail_next(LAW_TG, 3)
    _drain(worker, clock)
    assert [m.to for m in mail.sent] == ["cto@k.co"]


def test_vcrm151_vcrm050_kinds_match_critical_notifications() -> None:
    assert (
        frozenset({leads.ACCEPT_NOTICE_KIND, leads.RETRACT_NOTICE_KIND, leads.HANDOFF_NOTICE_KIND})
        == ESCALATED_KINDS
    )


def test_vcrm151_vcrm050_other_kinds_are_not_escalated(
    db: CrmDatabase,
    tg: FakeTelegram,
    mail: FakeEmailSender,
    clock: FakeClock,
    worker: OutboxWorker,
    users: dict[str, User],
) -> None:
    lead_id = _lead(db, users["com"])
    _notice(db, lead_id, users["law"], Channel.TELEGRAM, clock.now(), kind="otro")
    tg.fail_next(LAW_TG, 3)
    _drain(worker, clock)
    assert len(_rows(db)) == 1 and mail.attempts == []


def test_vcrm151_vcrm107_cto_telegram_failure_backup_includes_full_content(
    db: CrmDatabase,
    tg: FakeTelegram,
    mail: FakeEmailSender,
    clock: FakeClock,
    worker: OutboxWorker,
    users: dict[str, User],
) -> None:
    lead_id = _lead(db, users["com"])
    _notice(db, lead_id, users["cto"], Channel.TELEGRAM, clock.now())
    tg.fail_next(CTO_TG, 3)
    _drain(worker, clock)
    (to_cto,) = _mails_to(mail, "cto@k.co")
    (to_com,) = _mails_to(mail, "com@k.co")
    assert CONTENT in to_cto.body and "cto@k.co" in to_cto.body
    assert CONTENT not in to_com.body


def test_vcrm151_vcrm050_backup_without_lead_goes_to_cto(
    db: CrmDatabase,
    tg: FakeTelegram,
    mail: FakeEmailSender,
    clock: FakeClock,
    worker: OutboxWorker,
    users: dict[str, User],
) -> None:
    _notice(db, 999, users["law"], Channel.TELEGRAM, clock.now())  # lead ya inexistente
    tg.fail_next(LAW_TG, 3)
    _drain(worker, clock)
    assert [m.to for m in mail.sent] == ["cto@k.co"]


# --- VCRM-129 / 130: aviso de fallo del respaldo ----------------------------------------


def test_vcrm151_vcrm129_backup_failure_warns_by_telegram_and_email(
    db: CrmDatabase,
    tg: FakeTelegram,
    mail: FakeEmailSender,
    clock: FakeClock,
    worker: OutboxWorker,
    users: dict[str, User],
) -> None:
    lead_id = _lead(db, users["com"])
    _notice(db, lead_id, users["law"], Channel.TELEGRAM, clock.now())
    tg.fail_next(LAW_TG, 3)
    mail.fail_next("cto@k.co", 3)
    _drain(worker, clock)
    warnings = _rows(db, BACKUP_FAILED_KIND)
    assert {(r["channel"], r["recipient_user_id"]) for r in warnings} == {
        ("telegram", users["cto"].id),
        ("email", users["cto"].id),
        ("telegram", users["com"].id),
        ("email", users["com"].id),
    }
    for chat in (CTO_TG, COM_TG):
        (msg,) = [m for m in tg.sent if m.chat_id == chat]
        assert short_id(lead_id) in msg.text
        assert "law@k.co" in msg.text and "telegram" in msg.text  # notificación original
        assert "cto@k.co" in msg.text  # destinatario del respaldo que falló
    assert len(_mails_to(mail, "cto@k.co")) == 1  # el aviso por correo
    assert len(_mails_to(mail, "com@k.co")) == 2  # respaldo + aviso


def test_vcrm151_vcrm130_failed_warning_on_both_channels_stops(
    db: CrmDatabase,
    tg: FakeTelegram,
    clock: FakeClock,
    users: dict[str, User],
) -> None:
    mail = FakeEmailSender(configured=False)
    worker = _worker(db, tg, mail, clock)
    lead_id = _lead(db, users["cto"])
    _notice(db, lead_id, users["law"], Channel.TELEGRAM, clock.now())
    tg.fail_next(LAW_TG, 3)
    tg.fail_next(CTO_TG, 100)
    _drain(worker, clock, cycles=30)
    kinds = [r["kind"] for r in _rows(db)]
    assert kinds.count(BACKUP_KIND) == 1 and kinds.count(BACKUP_FAILED_KIND) == 2
    assert len(kinds) == 4 and all(r["status"] == "failed" for r in _rows(db))
    attempts = len(tg.attempts)
    _drain(worker, clock)
    assert len(tg.attempts) == attempts and len(_rows(db)) == 4
    with db.read() as conn:
        assert len(repo.open_alerts(conn, lead_id=lead_id)) == 1  # la alerta se mantiene


# --- VCRM-140: buzón sin configurar --------------------------------------------------------


def test_vcrm151_vcrm140_unconfigured_mailbox_fails_without_attempts_and_escalates(
    db: CrmDatabase,
    tg: FakeTelegram,
    clock: FakeClock,
    users: dict[str, User],
) -> None:
    mail = FakeEmailSender(configured=False)
    worker = _worker(db, tg, mail, clock)
    lead_id = _lead(db, users["com"])
    failed_id = _notice(db, lead_id, users["law"], Channel.EMAIL, clock.now())
    _deliver(worker)
    (row,) = [r for r in _rows(db) if r["id"] == failed_id]
    assert row["status"] == "failed" and row["attempts"] == 0
    assert len(_rows(db, BACKUP_KIND)) == 2
    _deliver(worker)  # respaldos: también «fallida» sin intentos → aviso (VCRM-129)
    assert all(r["attempts"] == 0 for r in _rows(db, BACKUP_KIND))
    _deliver(worker)
    assert {m.chat_id for m in tg.sent} == {CTO_TG, COM_TG}


# --- VCRM-087: alerta en ficha y lista hasta «Atendida por otro medio» --------------------


def _failed_lead(
    db: CrmDatabase,
    tg: FakeTelegram,
    clock: FakeClock,
    worker: OutboxWorker,
    users: dict[str, User],
) -> int:
    lead_id = _lead(db, users["com"])
    _notice(db, lead_id, users["law"], Channel.TELEGRAM, clock.now())
    tg.fail_next(LAW_TG, 3)
    _drain(worker, clock)
    tg.sent.clear()
    return lead_id


def test_vcrm151_vcrm087_alert_in_card_and_cto_list_until_attended(
    db: CrmDatabase,
    tg: FakeTelegram,
    clock: FakeClock,
    worker: OutboxWorker,
    users: dict[str, User],
) -> None:
    lead_id = _failed_lead(db, tg, clock, worker, users)
    with db.read() as conn:
        (alert,) = repo.open_alerts(conn, lead_id=lead_id)
    bot = CrmBot(db, tg, clock.now)
    sid = short_id(lead_id)
    run(bot, _msg(CTO_TG, f"/ver {sid}"))
    card = tg.sent[-1]
    assert "notificación fallida" in card.text
    attend = build_callback("atendida", str(alert.id))
    assert card.buttons is not None
    assert any(b.callback_data == attend for row in card.buttons for b in row)
    run(bot, _msg(CTO_TG, "/lista"))
    assert any(sid in line and ALERT_MARK in line for line in tg.sent[-1].text.splitlines())
    run(bot, _msg(COM_TG, f"/ver {sid}"))  # el comercial ve la alerta, pero sin el botón
    assert "notificación fallida" in tg.sent[-1].text
    assert not any(b.callback_data == attend for row in (tg.sent[-1].buttons or []) for b in row)
    run(bot, _msg(COM_TG, "/lista"))
    assert ALERT_MARK not in tg.sent[-1].text

    run(bot, _cb(COM_TG, attend))  # solo el CTO
    assert tg.sent[-1].text == DENIED
    with db.read() as conn:
        assert len(repo.open_alerts(conn, lead_id=lead_id)) == 1

    clock.advance(minutes=30)
    run(bot, _cb(CTO_TG, attend))
    assert "atendida por otro medio" in tg.sent[-1].text
    with db.read() as conn:
        assert repo.open_alerts(conn) == []
        row = conn.execute("SELECT * FROM crm_alerts WHERE id = ?", (alert.id,)).fetchone()
    assert row["resolved_by"] == users["cto"].id and row["resolved_at"] is not None
    run(bot, _msg(CTO_TG, f"/ver {sid}"))
    assert "Alertas activas: ninguna" in tg.sent[-1].text
    run(bot, _msg(CTO_TG, "/lista"))
    assert ALERT_MARK not in tg.sent[-1].text

    run(bot, _cb(CTO_TG, attend))  # repetido → ya atendida
    assert "ya" in tg.sent[-1].text
    run(bot, _cb(CTO_TG, build_callback("atendida", "x")))
    assert tg.sent[-1].text.startswith("Botón no válido")


# --- Rama del bot: tipo de confirmación sin handler registrado ---------------------------


def test_vcrm151_vcrm046_unregistered_confirmation_kind_is_inert(
    db: CrmDatabase,
    tg: FakeTelegram,
    clock: FakeClock,
    users: dict[str, User],
) -> None:
    lead_id = _lead(db, users["com"])
    with db.tx() as tx:
        no_id = repo.create_confirmation(
            tx, kind=leads.RETRACT_KIND, lead_id=lead_id, user_id=users["com"].id, now=clock.now()
        )
        yes_id = repo.create_confirmation(
            tx, kind=leads.RETRACT_KIND, lead_id=lead_id, user_id=users["com"].id, now=clock.now()
        )
    bot = CrmBot(db, tg, clock.now)
    bot._confirmations.pop(leads.RETRACT_KIND)  # tipo persistido sin handler registrado
    run(bot, _cb(COM_TG, build_callback("conf", str(no_id), "no")))
    assert tg.sent[-1].text == CANCELLED
    sent = len(tg.sent)
    run(bot, _cb(COM_TG, build_callback("conf", str(yes_id), "si")))
    assert len(tg.sent) == sent
