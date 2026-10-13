"""Tests del núcleo del bot (VCRM-001, 002, 012, 079, 086)."""

import asyncio
import logging
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crm_support import FakeClock, FakeTelegram
from jerico.crm import bot as bot_module
from jerico.crm import repo
from jerico.crm.bot import GENERIC_ERROR, CrmBot
from jerico.crm.db import CrmDatabase
from jerico.crm.model import (
    AuditAction,
    AuditDetail,
    AuditOutcome,
    Confirmation,
    LeadState,
    Outgoing,
    PendingInput,
    Role,
    User,
)
from jerico.crm.parsing import build_callback
from jerico.crm.ports import Update
from jerico.crm.telegram import TelegramApiError
from jerico.crm.timeutil import to_iso

START = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
CTO_TG = 1000
COM_TG = 2000
STRANGER_TG = 9999


@pytest.fixture
def db(tmp_path: Path) -> Iterator[CrmDatabase]:
    database = CrmDatabase(tmp_path / "crm.db")
    yield database
    database.close()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(START)


@pytest.fixture
def tg() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def bot(db: CrmDatabase, tg: FakeTelegram, clock: FakeClock) -> CrmBot:
    return CrmBot(db, tg, clock.now)


@pytest.fixture
def users(db: CrmDatabase) -> tuple[User, User]:
    with db.tx() as tx:
        cto = repo.insert_user(tx, telegram_id=CTO_TG, role=Role.CTO, email="cto@k.co", now=START)
        com = repo.insert_user(
            tx, telegram_id=COM_TG, role=Role.COMMERCIAL, email="com@k.co", now=START
        )
    return cto, com


def _msg(update_id: int, user_tg: int, text: str, chat_type: str = "private") -> Update:
    return Update(
        update_id=update_id, user_id=user_tg, chat_id=user_tg, chat_type=chat_type, text=text
    )


def _cb(update_id: int, user_tg: int, data: str) -> Update:
    return Update(
        update_id=update_id,
        user_id=user_tg,
        chat_id=user_tg,
        chat_type="private",
        callback_id=f"cb{update_id}",
        callback_data=data,
    )


def _audit(db: CrmDatabase) -> list[dict[str, object]]:
    with db.read() as conn:
        return repo.audit_rows(conn)


def _count(db: CrmDatabase, sql: str) -> int:
    with db.read() as conn:
        return int(conn.execute(sql).fetchone()[0])


def _new_lead(db: CrmDatabase, user_id: int) -> int:
    with db.tx() as tx:
        return repo.insert_lead(
            tx, assigned_user_id=user_id, state=LeadState.NEW, now=START, fields={}
        )


def run(coro: object) -> None:
    asyncio.run(coro)  # type: ignore[arg-type]


# --- Identidad (VCRM-001, VCRM-002) -------------------------------------------------------


def test_vcrm001_authorized_command_is_processed(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: tuple[User, User]
) -> None:
    run(bot.process_update(_msg(1, CTO_TG, "/alta abogado; 3000; law@k.co")))
    with db.read() as conn:
        assert repo.active_user_by_telegram(conn, 3000) is not None
    assert [s.chat_id for s in tg.sent] == [CTO_TG]
    assert "Alta registrada" in tg.sent[0].text


def test_vcrm001_authorized_callback_is_processed_and_answered(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: tuple[User, User]
) -> None:
    lead_id = _new_lead(db, users[1].id)
    run(bot.process_update(_cb(1, CTO_TG, build_callback("reasignar", str(lead_id)))))
    assert tg.sent[0].chat_id == CTO_TG
    assert tg.sent[0].buttons  # teclado de destinos, como InlineButton
    assert tg.sent[0].buttons[0][0].callback_data.startswith("v1:reasignar:")
    assert tg.answered == [("cb1", None)]
    run(bot.process_update(_cb(2, CTO_TG, build_callback("reasignar", str(lead_id), "1"))))
    with db.read() as conn:
        lead = repo.get_lead(conn, lead_id)
    assert lead is not None and lead.assigned_user_id == users[0].id


def test_vcrm002_unknown_identity_message_has_no_effect_and_is_audited(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: tuple[User, User]
) -> None:
    run(bot.process_update(_msg(1, STRANGER_TG, "/alta abogado; 3000; law@k.co")))
    with db.read() as conn:
        assert repo.active_user_by_telegram(conn, 3000) is None
    assert tg.sent == [] and tg.attempts == []
    rows = _audit(db)
    assert len(rows) == 1
    row = rows[0]
    assert row["actor"] == f"tg:{STRANGER_TG}"
    assert row["action"] == AuditAction.ACCESS_DENIED
    assert row["outcome"] == AuditOutcome.DENIED
    assert row["detail_code"] == AuditDetail.MESSAGE
    assert row["at"] == to_iso(START)
    assert row["lead_id"] is None


def test_vcrm002_unknown_identity_callback_is_audited_without_data(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: tuple[User, User]
) -> None:
    lead_id = _new_lead(db, users[1].id)
    run(bot.process_update(_cb(1, STRANGER_TG, build_callback("reasignar", str(lead_id)))))
    assert tg.sent == []
    assert tg.answered == [("cb1", None)]
    row = _audit(db)[0]
    assert row["actor"] == f"tg:{STRANGER_TG}"
    assert row["detail_code"] == AuditDetail.CALLBACK


def test_vcrm002_update_without_identity_is_ignored(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase
) -> None:
    run(bot.process_update(Update(update_id=1, text="hola")))
    assert tg.sent == []
    assert _audit(db)[0]["actor"] == "tg:0"


def test_vcrm001_deactivated_user_is_no_longer_served(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: tuple[User, User]
) -> None:
    run(bot.process_update(_msg(1, CTO_TG, f"/baja_usuario {COM_TG}")))
    tg.sent.clear()
    run(bot.process_update(_msg(2, COM_TG, "/reasignar L-1; cto")))
    assert tg.sent == []
    assert _audit(db)[-1]["actor"] == f"tg:{COM_TG}"
    assert _audit(db)[-1]["action"] == AuditAction.ACCESS_DENIED


def test_vcrm001_non_private_chat_is_ignored_and_audited(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: tuple[User, User]
) -> None:
    run(bot.process_update(_msg(1, CTO_TG, "/alta abogado; 3000; law@k.co", "group")))
    with db.read() as conn:
        assert repo.active_user_by_telegram(conn, 3000) is None
    assert tg.sent == []
    row = _audit(db)[0]
    assert row["actor"] == f"user:{users[0].id}"
    assert row["detail_code"] == AuditDetail.NON_PRIVATE_CHAT


# --- Deduplicación y offset (VCRM-079) ------------------------------------------------------


def test_vcrm079_same_update_twice_has_single_effect(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: tuple[User, User]
) -> None:
    update = _msg(7, CTO_TG, "/alta abogado; 3000; law@k.co")
    run(bot.process_update(update))
    run(bot.process_update(update))
    assert _count(db, "SELECT COUNT(*) FROM crm_users WHERE telegram_id = 3000") == 1
    assert len(tg.sent) == 1
    assert _count(db, "SELECT COUNT(*) FROM crm_processed_updates WHERE update_id = 7") == 1


def test_vcrm079_offset_is_persisted_and_survives_restart(
    db: CrmDatabase, tg: FakeTelegram, clock: FakeClock, users: tuple[User, User]
) -> None:
    run(CrmBot(db, tg, clock.now).process_update(_msg(41, CTO_TG, "/alta abogado; 3000; law@k.co")))
    with db.read() as conn:
        assert repo.get_meta(conn, "telegram_offset") == "42"

    seen: list[int | None] = []

    class OneShot(FakeTelegram):
        async def get_updates(self, offset: int | None, timeout_s: int) -> list[Update]:
            seen.append(offset)
            stop.set()
            return [_msg(42, CTO_TG, "/alta comercial; 2200; c2@k.co")]

    stop = asyncio.Event()
    beats: list[int] = []
    restarted = CrmBot(db, OneShot(), clock.now)
    run(restarted.run_polling(stop, heartbeat=lambda: beats.append(1)))
    assert seen == [42]
    assert beats == [1]
    with db.read() as conn:
        assert repo.get_meta(conn, "telegram_offset") == "43"
        assert repo.active_user_by_telegram(conn, 2200) is not None


def test_vcrm079_polling_survives_telegram_api_error(
    db: CrmDatabase, clock: FakeClock, users: tuple[User, User]
) -> None:
    calls: list[int | None] = []
    sleeps: list[float] = []

    class Flaky(FakeTelegram):
        async def get_updates(self, offset: int | None, timeout_s: int) -> list[Update]:
            calls.append(offset)
            if len(calls) == 1:
                raise TelegramApiError("getUpdates: HTTP 502")
            stop.set()
            return [_msg(5, CTO_TG, "/alta abogado; 3000; law@k.co")]

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    stop = asyncio.Event()
    flaky_bot = CrmBot(db, Flaky(), clock.now, sleep=fake_sleep)
    run(flaky_bot.run_polling(stop))
    assert calls == [None, None]
    assert sleeps == [5.0]
    with db.read() as conn:
        assert repo.active_user_by_telegram(conn, 3000) is not None


# --- Denegaciones (VCRM-086) ---------------------------------------------------------------


def test_vcrm086_command_not_allowed_replies_and_audits(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: tuple[User, User]
) -> None:
    run(bot.process_update(_msg(1, COM_TG, "/alta abogado; 3000; law@k.co")))
    with db.read() as conn:
        assert repo.active_user_by_telegram(conn, 3000) is None
    assert "no tiene permiso" in tg.sent[0].text.lower()
    row = _audit(db)[-1]
    assert row["actor"] == f"user:{users[1].id}"
    assert row["action"] == AuditAction.PERMISSION_DENIED
    assert row["outcome"] == AuditOutcome.DENIED


def test_vcrm086_callback_not_allowed_replies_and_audits(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: tuple[User, User]
) -> None:
    _new_lead(db, users[1].id)
    run(bot.process_update(_cb(1, COM_TG, build_callback("baja_leads", str(users[1].id), "1"))))
    assert len(tg.sent) == 1
    assert "no tiene permiso" in tg.sent[0].text.lower()
    assert "L-" not in tg.sent[0].text
    assert _audit(db)[-1]["action"] == AuditAction.PERMISSION_DENIED


def test_vcrm086_cto_can_page_orphan_leads(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: tuple[User, User]
) -> None:
    _new_lead(db, users[1].id)
    run(bot.process_update(_cb(1, CTO_TG, build_callback("baja_leads", str(users[1].id), "1"))))
    assert "Leads del comercial" in tg.sent[0].text


# --- Enrutado ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("update", "expected"),
    [
        (_msg(1, CTO_TG, "/desconocida"), "Orden no reconocida"),
        (_msg(1, CTO_TG, "texto libre"), "Orden no reconocida"),
        (_cb(1, CTO_TG, "basura"), "Botón no válido"),
        (_cb(1, CTO_TG, "v1:nada:1"), "Botón no válido"),
        (_cb(1, CTO_TG, "v1:reasignar:x"), "Botón no válido"),
        (_cb(1, CTO_TG, "v1:reasignar:1:2:3"), "Botón no válido"),
        (_cb(1, CTO_TG, "v1:baja_leads:1"), "Botón no válido"),
        (_cb(1, CTO_TG, "v1:conf:1"), "Botón no válido"),
        (_cb(1, CTO_TG, "v1:conf:1:quizas"), "Botón no válido"),
        (_cb(1, CTO_TG, "v1:conf:99:si"), "Botón no válido"),
        (
            Update(update_id=1, user_id=CTO_TG, chat_id=CTO_TG, chat_type="private"),
            "Orden no reconocida",
        ),
    ],
)
def test_vcrm001_unroutable_input_gets_neutral_reply(
    bot: CrmBot, tg: FakeTelegram, users: tuple[User, User], update: Update, expected: str
) -> None:
    run(bot.process_update(update))
    assert expected in tg.sent[0].text


def test_vcrm001_command_with_bot_suffix_is_routed(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: tuple[User, User]
) -> None:
    run(bot.process_update(_msg(1, CTO_TG, "/alta@JericoBot abogado; 3000; law@k.co")))
    assert "Alta registrada" in tg.sent[0].text


# --- Entradas pendientes ------------------------------------------------------------------


def test_vcrm001_pending_input_receives_free_text_until_expiry(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, clock: FakeClock, users: tuple[User, User]
) -> None:
    received: list[tuple[PendingInput, str | None]] = []

    def handler(
        conn: sqlite3.Connection, user: User, pending: PendingInput, update: Update, now: datetime
    ) -> list[Outgoing]:
        received.append((pending, update.text))
        return [Outgoing(user.telegram_id, "Texto recibido.")]

    bot.register_pending("reject_other", handler)
    with db.tx() as tx:
        repo.set_pending_input(
            tx, user_id=users[0].id, kind="reject_other", now=clock.now(), lead_id=5
        )
    run(bot.process_update(_msg(1, CTO_TG, "el cliente se mudó")))
    assert received[0][0].lead_id == 5 and received[0][1] == "el cliente se mudó"
    assert tg.sent[-1].text == "Texto recibido."
    with db.read() as conn:  # consumida
        assert repo.get_pending_input(conn, users[0].id, clock.now()) is None

    with db.tx() as tx:
        repo.set_pending_input(tx, user_id=users[0].id, kind="reject_other", now=clock.now())
    clock.advance(minutes=31)
    run(bot.process_update(_msg(2, CTO_TG, "tarde")))
    assert len(received) == 1
    assert "Orden no reconocida" in tg.sent[-1].text


def test_vcrm001_new_command_replaces_pending_input(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, clock: FakeClock, users: tuple[User, User]
) -> None:
    with db.tx() as tx:
        repo.set_pending_input(tx, user_id=users[0].id, kind="reject_other", now=clock.now())
        repo.set_pending_input(
            tx, user_id=users[0].id, kind="authorization", now=clock.now(), data="x"
        )
        pending = repo.get_pending_input(tx, users[0].id, clock.now())
    assert pending is not None and pending.kind == "authorization" and pending.data == "x"
    run(bot.process_update(_msg(1, CTO_TG, "/desconocida")))
    with db.read() as conn:
        assert repo.get_pending_input(conn, users[0].id, clock.now()) is None


def test_vcrm001_pending_input_without_handler_is_dropped(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, clock: FakeClock, users: tuple[User, User]
) -> None:
    with db.tx() as tx:
        repo.set_pending_input(tx, user_id=users[0].id, kind="sin_handler", now=clock.now())
    run(bot.process_update(_msg(1, CTO_TG, "hola")))
    assert "Orden no reconocida" in tg.sent[0].text


# --- Confirmaciones (idempotentes) ----------------------------------------------------------


def test_vcrm079_confirmation_resolves_once(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, clock: FakeClock, users: tuple[User, User]
) -> None:
    calls: list[tuple[Confirmation, bool]] = []

    def on_accept(
        conn: sqlite3.Connection, user: User, conf: Confirmation, yes: bool, now: datetime
    ) -> list[Outgoing]:
        calls.append((conf, yes))
        return [Outgoing(user.telegram_id, "Aceptación confirmada.")]

    bot.register_confirmation("accept", on_accept)
    lead_id = _new_lead(db, users[0].id)
    with db.tx() as tx:
        conf_id = repo.create_confirmation(
            tx, kind="accept", lead_id=lead_id, user_id=users[0].id, now=clock.now()
        )
    run(bot.process_update(_cb(1, CTO_TG, build_callback("conf", str(conf_id), "si"))))
    run(bot.process_update(_cb(2, CTO_TG, build_callback("conf", str(conf_id), "no"))))
    assert len(calls) == 1 and calls[0][1] is True and calls[0][0].lead_id == lead_id
    assert tg.sent[0].text == "Aceptación confirmada."
    assert "ya fue procesada" in tg.sent[1].text
    with db.read() as conn:
        conf = repo.get_confirmation(conn, conf_id)
    assert conf is not None and conf.status == "confirmed" and conf.resolved_at == to_iso(START)


def test_vcrm079_confirmation_cancel_and_unregistered_kind(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, clock: FakeClock, users: tuple[User, User]
) -> None:
    lead_id = _new_lead(db, users[0].id)
    with db.tx() as tx:
        conf_id = repo.create_confirmation(
            tx,
            kind="retract",
            lead_id=lead_id,
            user_id=users[0].id,
            now=clock.now(),
            reason="otro",
            reason_text="x",
        )
    run(bot.process_update(_cb(1, CTO_TG, build_callback("conf", str(conf_id), "no"))))
    with db.read() as conn:
        conf = repo.get_confirmation(conn, conf_id)
    assert conf is not None and conf.status == "cancelled" and conf.reason == "otro"
    # Desde T17 el tipo «retract» tiene manejador: ❌ responde con su propio texto.
    assert tg.sent[0].text == f"No se aplicó la retractación de L-{lead_id:04d}."


def test_vcrm086_confirmation_of_another_user_is_denied(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, clock: FakeClock, users: tuple[User, User]
) -> None:
    lead_id = _new_lead(db, users[0].id)
    with db.tx() as tx:
        conf_id = repo.create_confirmation(
            tx, kind="accept", lead_id=lead_id, user_id=users[0].id, now=clock.now()
        )
    run(bot.process_update(_cb(1, COM_TG, build_callback("conf", str(conf_id), "si"))))
    assert "no tiene permiso" in tg.sent[0].text.lower()
    assert _audit(db)[-1]["action"] == AuditAction.PERMISSION_DENIED
    with db.read() as conn:
        conf = repo.get_confirmation(conn, conf_id)
    assert conf is not None and conf.status == "pending"


# --- Respuestas fallidas (VCRM-012) ------------------------------------------------------


def test_vcrm012_failed_reply_is_recorded_without_body_and_not_retried(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: tuple[User, User]
) -> None:
    tg.fail_next(CTO_TG)
    update = _msg(1, CTO_TG, "/alta abogado; 3000; law@k.co")
    run(bot.process_update(update))
    run(bot.process_update(update))
    assert len(tg.attempts) == 1
    with db.read() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM crm_outbox").fetchall()]
        assert repo.active_user_by_telegram(conn, 3000) is not None  # el efecto se conserva
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "failed" and row["critical"] == 0
    assert row["body"] is None and row["subject"] is None
    assert row["channel"] == "telegram" and row["recipient_user_id"] == users[0].id
    assert row["attempts"] == 1 and row["next_attempt_at"] is None
    assert row["last_error"] == "sendMessage: HTTP 502"


def test_vcrm012_failed_reply_to_unknown_chat_is_attributed_to_actor(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: tuple[User, User]
) -> None:
    def handler(conn: sqlite3.Connection, user: User, text: str, now: datetime) -> list[Outgoing]:
        return [Outgoing(555, "aviso")]

    bot.register_command("aviso", handler)
    tg.fail_next(555)
    run(bot.process_update(_msg(1, CTO_TG, "/aviso")))
    with db.read() as conn:
        rows = conn.execute("SELECT recipient_user_id FROM crm_outbox").fetchall()
    assert [r[0] for r in rows] == [users[0].id]


# --- Errores de handler (regla O1) -----------------------------------------------------------


def test_vcrm079_handler_error_rolls_back_replies_generic_and_marks_processed(
    bot: CrmBot,
    tg: FakeTelegram,
    db: CrmDatabase,
    users: tuple[User, User],
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[int] = []

    def boom(conn: sqlite3.Connection, user: User, text: str, now: datetime) -> list[Outgoing]:
        calls.append(1)
        repo.insert_lead(
            conn,
            assigned_user_id=user.id,
            state=LeadState.NEW,
            now=now,
            fields={"name": "Ana Pérez"},
        )
        raise ValueError("Ana Pérez +573001234567")

    bot.register_command("boom", boom)
    update = _msg(9, CTO_TG, "/boom")
    with caplog.at_level(logging.ERROR):
        run(bot.process_update(update))
        run(bot.process_update(update))
    assert calls == [1]
    assert _count(db, "SELECT COUNT(*) FROM crm_leads") == 0
    assert [s.text for s in tg.sent] == [GENERIC_ERROR]
    assert "Ana" not in GENERIC_ERROR
    row = _audit(db)[-1]
    assert row["action"] == AuditAction.HANDLER_ERROR
    assert row["outcome"] == AuditOutcome.ERROR
    assert row["actor"] == f"user:{users[0].id}"
    assert _count(db, "SELECT COUNT(*) FROM crm_processed_updates WHERE update_id = 9") == 1
    with db.read() as conn:
        assert repo.get_meta(conn, "telegram_offset") == "10"
    assert "ValueError" in caplog.text
    assert "Ana" not in caplog.text and "+57" not in caplog.text


def test_vcrm079_handler_error_with_failed_bookkeeping_is_logged(
    bot: CrmBot,
    tg: FakeTelegram,
    db: CrmDatabase,
    users: tuple[User, User],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(conn: sqlite3.Connection, user: User, text: str, now: datetime) -> list[Outgoing]:
        raise RuntimeError("x")

    real_audit = repo.audit

    def audit(conn: sqlite3.Connection, **kwargs: object) -> None:
        if kwargs["action"] == AuditAction.HANDLER_ERROR:
            raise sqlite3.OperationalError("disk I/O error")
        real_audit(conn, **kwargs)  # type: ignore[arg-type]

    bot.register_command("boom", boom)
    monkeypatch.setattr(bot_module.repo, "audit", audit)
    with caplog.at_level(logging.ERROR):
        run(bot.process_update(_msg(3, CTO_TG, "/boom")))
    assert [s.text for s in tg.sent] == [GENERIC_ERROR]
    assert _count(db, "SELECT COUNT(*) FROM crm_processed_updates") == 0
    assert "OperationalError" in caplog.text


def test_vcrm012_kick_is_called_after_routed_update(
    db: CrmDatabase, tg: FakeTelegram, clock: FakeClock, users: tuple[User, User]
) -> None:
    kicks: list[int] = []
    kicking = CrmBot(db, tg, clock.now, kick=lambda: kicks.append(1))
    run(kicking.process_update(_msg(1, CTO_TG, "/desconocida")))
    run(kicking.process_update(_msg(2, STRANGER_TG, "/desconocida")))
    assert kicks == [1]


# --- Repositorio --------------------------------------------------------------------------


def test_vcrm079_repo_mark_processed_and_confirmation_helpers(db: CrmDatabase) -> None:
    with db.tx() as tx:
        assert repo.mark_update_processed(tx, 1, START) is True
        assert repo.mark_update_processed(tx, 1, START) is False
        assert repo.get_confirmation(tx, 404) is None
        assert repo.resolve_confirmation(tx, 404, "confirmed", START) is False
        repo.clear_pending_input(tx, 404)


def test_vcrm001_registered_callback_is_routed(
    bot: CrmBot, tg: FakeTelegram, users: tuple[User, User]
) -> None:
    def handler(
        conn: sqlite3.Connection, user: User, args: tuple[str, ...], now: datetime
    ) -> list[Outgoing]:
        return [Outgoing(user.telegram_id, f"args={args}")]

    bot.register_callback("ver", handler)
    run(bot.process_update(_cb(1, CTO_TG, build_callback("ver", "7"))))
    assert tg.sent[0].text == "args=('7',)"


def test_vcrm002_error_before_identity_sends_nothing(
    bot: CrmBot,
    tg: FakeTelegram,
    db: CrmDatabase,
    users: tuple[User, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(conn: sqlite3.Connection, telegram_id: int) -> User | None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(bot_module.repo, "active_user_by_telegram", broken)
    run(bot.process_update(_msg(4, CTO_TG, "/alta abogado; 3000; law@k.co")))
    assert tg.attempts == []
    row = _audit(db)[-1]
    assert row["actor"] == "system" and row["action"] == AuditAction.HANDLER_ERROR


# --- Trabajos diferidos tras el *commit* (asistente LLM; VCRM-A36) ---------------------------


def test_vcrma36_deferred_job_runs_after_commit_and_replies(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: tuple[User, User]
) -> None:
    seen: list[bool] = []

    def handler(conn: sqlite3.Connection, user: User, text: str, now: datetime) -> list[Outgoing]:
        async def job() -> list[Outgoing]:
            with db.read() as check:  # la transacción del handler ya se confirmó
                seen.append(repo.get_meta(check, "telegram_offset") == "2")
            return [Outgoing(user.telegram_id, "respuesta diferida")]

        bot.defer(job)
        return [Outgoing(user.telegram_id, "consultando")]

    bot.register_command("diferido", handler)
    run(bot.process_update(_msg(1, CTO_TG, "/diferido")))
    assert [s.text for s in tg.sent] == ["consultando", "respuesta diferida"]
    assert seen == [True]


def test_vcrma36_deferred_job_is_dropped_on_handler_error(
    bot: CrmBot, tg: FakeTelegram, users: tuple[User, User]
) -> None:
    ran: list[int] = []

    def handler(conn: sqlite3.Connection, user: User, text: str, now: datetime) -> list[Outgoing]:
        async def job() -> list[Outgoing]:
            ran.append(1)
            return []

        bot.defer(job)
        raise ValueError("x")

    bot.register_command("roto", handler)
    run(bot.process_update(_msg(1, CTO_TG, "/roto")))
    assert ran == [] and [s.text for s in tg.sent] == [GENERIC_ERROR]


def test_vcrma36_failing_deferred_job_replies_generic_error_and_keeps_loop(
    bot: CrmBot,
    tg: FakeTelegram,
    users: tuple[User, User],
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(conn: sqlite3.Connection, user: User, text: str, now: datetime) -> list[Outgoing]:
        async def job() -> list[Outgoing]:
            raise RuntimeError("Ana Pérez +573001234567")

        bot.defer(job)
        return []

    bot.register_command("falla", handler)
    with caplog.at_level(logging.ERROR):
        run(bot.process_update(_msg(1, CTO_TG, "/falla")))
    assert [s.text for s in tg.sent] == [GENERIC_ERROR]
    assert "RuntimeError" in caplog.text and "Ana" not in caplog.text
