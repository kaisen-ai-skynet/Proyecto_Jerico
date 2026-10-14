"""Correo por niveles: buzones, aislamiento, candidatos de lead (spec 004 C3; VCRM-M01..M09)."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from crm_support import FakeClock, FakeTelegram, make_settings
from jerico.crm import closing_repo as crepo
from jerico.crm import repo
from jerico.crm.bot import CrmBot
from jerico.crm.db import CrmDatabase
from jerico.crm.fingerprint import fingerprint
from jerico.crm.mailboxes import (
    CAND_NO,
    CAND_OK,
    NO_CANDIDATES,
    MailContext,
    poll_mailboxes,
    register_mailboxes,
)
from jerico.crm.model import Role
from jerico.crm.parsing import build_callback
from jerico.crm.ports import InboundMessage, InboxBatch, InboxError, Update
from jerico.crm.team import DENIED

START = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
CTO_TG, COM_TG, COM2_TG, LAW_TG = 1000, 2000, 2001, 3000
KEY = "clave-hmac-de-prueba"


def _msg(
    uid: int, sender: str, subject: str = "Cotización", mid: str | None = None
) -> InboundMessage:
    return InboundMessage(
        uid=uid,
        rfc_message_id=mid or f"<m{uid}@x>",
        in_reply_to=None,
        references=(),
        from_addr=sender,
        subject=subject,
        body_text="CUERPO SECRETO QUE NO SE GUARDA",
        date=START,
        truncated=False,
    )


class FakeInbox:
    def __init__(self, messages: list[InboundMessage] | None = None) -> None:
        self.messages = messages or []
        self.error: InboxError | None = None
        self.calls: list[tuple[int | None, int]] = []

    async def fetch_new(self, uidvalidity: int | None, last_uid: int) -> InboxBatch:
        self.calls.append((uidvalidity, last_uid))
        if self.error is not None:
            raise self.error
        fresh = tuple(m for m in self.messages if m.uid > last_uid)
        return InboxBatch(uidvalidity=7, messages=fresh, has_more=False)


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.db = CrmDatabase(tmp_path / "crm.db")
        self.tg = FakeTelegram()
        self.clock = FakeClock(START)
        self.inboxes: dict[int, FakeInbox] = {}
        self.ctx = MailContext(
            settings=make_settings(inbox_poll_minutes=5, mail_candidate_days=30),
            keys=[KEY],
            clock=self.clock.now,
            environ={"JERICO_MAILBOX_DUVAN_PASSWORD": "pw-duvan"},
            inbox_factory=lambda mb: self.inboxes.get(mb.id),
        )
        self.bot = CrmBot(self.db, self.tg, self.clock.now)
        register_mailboxes(self.bot, self.ctx)
        with self.db.tx() as tx:
            self.cto = repo.insert_user(
                tx, telegram_id=CTO_TG, role=Role.CTO, email="cto@k.co", now=START
            )
            self.com = repo.insert_user(
                tx, telegram_id=COM_TG, role=Role.COMMERCIAL, email="duvan@k.co", now=START
            )
            self.com2 = repo.insert_user(
                tx, telegram_id=COM2_TG, role=Role.COMMERCIAL, email="ana@k.co", now=START
            )
            self.law = repo.insert_user(
                tx, telegram_id=LAW_TG, role=Role.LAWYER, email="law@k.co", now=START
            )
            self.box1 = crepo.upsert_mailbox(
                tx,
                user_id=self.com.id,
                address="duvan@kaisen.co",
                secret_env="JERICO_MAILBOX_DUVAN_PASSWORD",
            )
            self.box2 = crepo.upsert_mailbox(
                tx,
                user_id=self.com2.id,
                address="ana@kaisen.co",
                secret_env="JERICO_MAILBOX_ANA_PASSWORD",
            )
        self.inboxes[self.box1.id] = FakeInbox()
        self.inboxes[self.box2.id] = FakeInbox()
        self.uid = 0

    def say(self, tg_id: int, text: str) -> None:
        self.uid += 1
        asyncio.run(
            self.bot.process_update(
                Update(
                    update_id=self.uid, user_id=tg_id, chat_id=tg_id, chat_type="private", text=text
                )
            )
        )

    def press(self, tg_id: int, data: str) -> None:
        self.uid += 1
        asyncio.run(
            self.bot.process_update(
                Update(
                    update_id=self.uid,
                    user_id=tg_id,
                    chat_id=tg_id,
                    chat_type="private",
                    callback_data=data,
                    callback_id="c",
                )
            )
        )

    def poll(self, minutes: int = 0) -> None:
        asyncio.run(poll_mailboxes(self.db, self.ctx, START + timedelta(minutes=minutes)))

    def texts(self, chat: int) -> list[str]:
        return [s.text for s in self.tg.sent if s.chat_id == chat]

    def candidates(self, mailbox_id: int) -> list[object]:
        with self.db.read() as conn:
            return list(
                conn.execute("SELECT * FROM crm_mail_candidates WHERE mailbox_id=?", (mailbox_id,))
            )

    def outbox(self, kind: str) -> list[dict[str, object]]:
        with self.db.read() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM crm_outbox WHERE kind=?", (kind,))]


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    e = Env(tmp_path)
    yield e
    e.db.close()


# --- Administración ---------------------------------------------------------------------------


def test_cto_registers_and_deactivates_mailboxes(env: Env) -> None:
    env.say(CTO_TG, "/buzon alta ana@k.co; ana.nueva@kaisen.co; JERICO_MAILBOX_ANA2_PASSWORD")
    with env.db.read() as conn:
        mailbox = crepo.mailbox_for_user(conn, env.com2.id)
    assert mailbox is not None and mailbox.address == "ana.nueva@kaisen.co"
    assert mailbox.secret_env == "JERICO_MAILBOX_ANA2_PASSWORD" and mailbox.active == 1
    env.say(CTO_TG, "/buzon baja ana@k.co")
    with env.db.read() as conn:
        assert crepo.mailbox_for_user(conn, env.com2.id).active == 0  # type: ignore[union-attr]
    env.say(CTO_TG, "/buzon baja nadie@k.co")
    assert env.texts(CTO_TG)[-1] == "Ese usuario no tiene buzón."


@pytest.mark.parametrize(
    "command",
    [
        "/buzon alta",
        "/buzon alta ana@k.co; ana@kaisen.co",
        "/buzon alta nadie@k.co; x@kaisen.co; JERICO_MAILBOX_X_PASSWORD",
        "/buzon alta law@k.co; x@kaisen.co; JERICO_MAILBOX_X_PASSWORD",  # el abogado no tiene buzón
        "/buzon alta ana@k.co; no-es-correo; JERICO_MAILBOX_X_PASSWORD",
        "/buzon alta ana@k.co; x@kaisen.co; JERICO_TELEGRAM_BOT_TOKEN",  # otro secreto: no
        "/buzon alta ana@k.co; x@kaisen.co; OPENAI_API_KEY",
        "/buzon cualquier cosa",
    ],
)
def test_invalid_mailbox_registrations_change_nothing(env: Env, command: str) -> None:
    env.say(CTO_TG, command)
    with env.db.read() as conn:
        assert [m.address for m in crepo.all_mailboxes(conn)] == [
            "duvan@kaisen.co",
            "ana@kaisen.co",
        ]


def test_only_the_cto_administers_mailboxes(env: Env) -> None:
    for who in (COM_TG, LAW_TG):
        env.say(who, "/buzon alta ana@k.co; x@kaisen.co; JERICO_MAILBOX_X_PASSWORD")
        env.say(who, "/buzon baja ana@k.co")
        env.say(who, "/buzones")
    with env.db.read() as conn:
        assert all(m.active == 1 for m in crepo.all_mailboxes(conn))
        assert crepo.mailbox_for_user(conn, env.com2.id).address == "ana@kaisen.co"  # type: ignore[union-attr]
    assert DENIED in env.texts(LAW_TG)


def test_vcrmm02_each_user_sees_only_their_own_mailbox_but_the_cto_sees_all(env: Env) -> None:
    env.say(COM_TG, "/buzon")
    assert (
        "duvan@kaisen.co" in env.texts(COM_TG)[-1] and "ana@kaisen.co" not in env.texts(COM_TG)[-1]
    )
    env.say(CTO_TG, "/buzones")
    assert "duvan@kaisen.co" in env.texts(CTO_TG)[-1] and "ana@kaisen.co" in env.texts(CTO_TG)[-1]
    with env.db.tx() as tx:
        tx.execute("DELETE FROM crm_mailboxes WHERE user_id=?", (env.com2.id,))
    env.say(COM2_TG, "/buzon")
    assert env.texts(COM2_TG)[-1] == "No tienes un buzón configurado."
    with env.db.tx() as tx:
        tx.execute("DELETE FROM crm_mailboxes")
    env.say(CTO_TG, "/buzones")
    assert env.texts(CTO_TG)[-1] == "No hay buzones."


# --- Lectura y candidatos -----------------------------------------------------------------------


def test_vcrmm04_unknown_senders_become_candidates_visible_only_to_their_owner(env: Env) -> None:
    env.inboxes[env.box1.id].messages = [
        _msg(1, "cliente.nuevo@empresa.co", "Quiero una cotización")
    ]
    env.inboxes[env.box2.id].messages = [_msg(1, "otro@empresa.co", "Hola")]
    env.poll()
    assert len(env.candidates(env.box1.id)) == 1 and len(env.candidates(env.box2.id)) == 1
    env.say(COM_TG, "/candidatos")
    mine = [s for s in env.tg.sent if s.chat_id == COM_TG]
    assert len(mine) == 1 and "cliente.nuevo@empresa.co" in mine[0].text
    assert "otro@empresa.co" not in mine[0].text
    env.say(CTO_TG, "/candidatos")
    cto_view = " ".join(env.texts(CTO_TG))
    assert "cliente.nuevo@empresa.co" in cto_view and "otro@empresa.co" in cto_view
    env.say(LAW_TG, "/candidatos")
    assert env.texts(LAW_TG) == [NO_CANDIDATES]
    assert {r["recipient_user_id"] for r in env.outbox("mail_candidates")} == {
        env.com.id,
        env.com2.id,
        env.cto.id,
    }


def test_vcrmm03_message_bodies_are_never_stored(env: Env) -> None:
    env.inboxes[env.box1.id].messages = [_msg(1, "x@empresa.co", "A" * 300)]
    env.poll()
    with env.db.read() as conn:
        dump = " ".join(str(tuple(r)) for r in conn.execute("SELECT * FROM crm_mail_candidates"))
        dump += " ".join(str(tuple(r)) for r in conn.execute("SELECT * FROM crm_outbox"))
        subject = conn.execute("SELECT subject FROM crm_mail_candidates").fetchone()[0]
    assert "CUERPO SECRETO" not in dump and len(subject) == 80


def test_automated_internal_known_and_suppressed_senders_are_skipped(env: Env) -> None:
    with env.db.tx() as tx:
        repo.insert_lead(
            tx,
            assigned_user_id=env.com.id,
            state=__import__("jerico.crm.model", fromlist=["LeadState"]).LeadState.NEW,
            now=START,
            fields={"email": "ya@empresa.co"},
        )
        repo.add_suppression(tx, fingerprint(KEY, "baja@empresa.co"), at=START, medium="email")
    env.inboxes[env.box1.id].messages = [
        _msg(1, "noreply@servicio.com"),
        _msg(2, "mailer-daemon@x.com"),
        _msg(3, "ana@k.co"),  # un compañero
        _msg(4, "ana@kaisen.co"),  # el buzón de otro comercial
        _msg(5, "YA@empresa.co"),  # ya es lead (sin distinguir mayúsculas)
        _msg(6, "baja@empresa.co"),  # pidió la baja
        _msg(7, ""),  # sin remitente fiable
        _msg(8, "valido@empresa.co"),
    ]
    env.poll()
    with env.db.read() as conn:
        senders = [c.sender_email for c in crepo.pending_candidates(conn, [env.box1.id])]
    assert senders == ["valido@empresa.co"]


def test_polling_is_incremental_and_throttled(env: Env) -> None:
    inbox = env.inboxes[env.box1.id]
    inbox.messages = [_msg(1, "a@empresa.co")]
    env.poll(0)
    inbox.messages.append(_msg(2, "b@empresa.co"))
    env.poll(2)  # <5 min: no consulta
    assert len(inbox.calls) == 1
    env.poll(6)
    assert inbox.calls[-1] == (7, 1)  # continúa desde el último UID
    assert len(env.candidates(env.box1.id)) == 2


def test_duplicate_message_ids_do_not_duplicate_candidates(env: Env) -> None:
    inbox = env.inboxes[env.box1.id]
    inbox.messages = [
        _msg(1, "a@empresa.co", mid="<igual@x>"),
        _msg(2, "a@empresa.co", mid="<igual@x>"),
    ]
    env.poll()
    assert len(env.candidates(env.box1.id)) == 1


def test_vcrmm09_mailbox_errors_warn_owner_and_cto_once_per_day(env: Env) -> None:
    env.inboxes[env.box1.id].error = InboxError("imap_error:login")
    env.poll(0)
    env.poll(6)
    assert len(env.outbox("mailbox_error")) == 2  # comercial + CTO, una sola vez al día
    assert all("duvan@kaisen.co" in str(r["body"]) for r in env.outbox("mailbox_error"))


def test_mailbox_without_credentials_is_skipped_quietly(env: Env) -> None:
    env.ctx.inbox_factory = lambda mb: None
    env.poll()
    assert env.candidates(env.box1.id) == []


def test_default_factory_reads_the_password_from_the_environment_only(tmp_path: Path) -> None:
    from jerico.crm.mailboxes import default_inbox

    ctx = MailContext(
        settings=make_settings(imap_host="imap.example.com"),
        keys=[KEY],
        clock=FakeClock(START).now,
        environ={"JERICO_MAILBOX_DUVAN_PASSWORD": "pw-duvan"},
    )
    from jerico.crm.closing_model import Mailbox

    factory = default_inbox(ctx)
    assert factory(Mailbox(1, 1, "d@kaisen.co", "JERICO_MAILBOX_NADA_PASSWORD", 1, None)) is None
    inbox = factory(Mailbox(1, 1, "d@kaisen.co", "JERICO_MAILBOX_DUVAN_PASSWORD", 1, None))
    assert inbox is not None and "pw-duvan" not in repr(inbox)


def test_expired_candidates_are_purged(env: Env) -> None:
    env.inboxes[env.box1.id].messages = [_msg(1, "a@empresa.co")]
    env.poll(0)
    env.poll(60 * 24 * 31)
    assert env.candidates(env.box1.id) == []


# --- ✅ / ❌ ----------------------------------------------------------------------------------


def _pending(env: Env) -> int:
    with env.db.read() as conn:
        return crepo.pending_candidates(conn, [env.box1.id])[0].id


def test_vcrmm04_register_creates_a_lead_for_the_mailbox_owner_and_writes_to_nobody(
    env: Env,
) -> None:
    env.inboxes[env.box1.id].messages = [_msg(1, "nuevo@empresa.co")]
    env.poll()
    cid = _pending(env)
    env.press(COM_TG, build_callback(CAND_OK, str(cid)))
    with env.db.read() as conn:
        leads = repo.leads_by_email(conn, "nuevo@empresa.co")
        candidate = crepo.get_candidate(conn, cid)
        sent = conn.execute("SELECT COUNT(*) FROM crm_sends").fetchone()[0]
    assert len(leads) == 1 and leads[0].assigned_user_id == env.com.id and leads[0].state == "new"
    assert candidate.status == "registered" and candidate.lead_id == leads[0].id  # type: ignore[union-attr]
    assert sent == 0
    assert "pedirautorizacion" in env.texts(COM_TG)[-1]
    env.press(COM_TG, build_callback(CAND_OK, str(cid)))  # doble pulsación: no duplica
    with env.db.read() as conn:
        assert len(repo.leads_by_email(conn, "nuevo@empresa.co")) == 1
    assert env.texts(COM_TG)[-1] == "Ese correo ya no está pendiente."


def test_discard_marks_the_candidate_and_registers_nothing(env: Env) -> None:
    env.inboxes[env.box1.id].messages = [_msg(1, "nuevo@empresa.co")]
    env.poll()
    env.press(COM_TG, build_callback(CAND_NO, str(_pending(env))))
    with env.db.read() as conn:
        assert repo.leads_by_email(conn, "nuevo@empresa.co") == []
        assert crepo.pending_candidates(conn, [env.box1.id]) == []


def test_foreign_commercial_and_lawyer_cannot_act_on_a_candidate(env: Env) -> None:
    env.inboxes[env.box1.id].messages = [_msg(1, "nuevo@empresa.co")]
    env.poll()
    cid = _pending(env)
    for who in (COM2_TG, LAW_TG):
        env.press(who, build_callback(CAND_OK, str(cid)))
        env.press(who, build_callback(CAND_NO, str(cid)))
    with env.db.read() as conn:
        assert repo.leads_by_email(conn, "nuevo@empresa.co") == []
        assert crepo.get_candidate(conn, cid).status == "pending"  # type: ignore[union-attr]
    env.press(CTO_TG, build_callback(CAND_OK, str(cid)))  # el CTO sí puede
    with env.db.read() as conn:
        assert repo.leads_by_email(conn, "nuevo@empresa.co")[0].assigned_user_id == env.com.id


def test_registering_a_sender_who_became_a_lead_or_asked_to_stop_is_refused(env: Env) -> None:
    from jerico.crm.model import LeadState

    env.inboxes[env.box1.id].messages = [_msg(1, "a@empresa.co"), _msg(2, "b@empresa.co")]
    env.poll()
    with env.db.read() as conn:
        first, second = [c.id for c in crepo.pending_candidates(conn, [env.box1.id])]
    with env.db.tx() as tx:
        repo.insert_lead(
            tx,
            assigned_user_id=env.com.id,
            state=LeadState.NEW,
            now=START,
            fields={"email": "a@empresa.co"},
        )
        repo.add_suppression(tx, fingerprint(KEY, "b@empresa.co"), at=START, medium="email")
    env.press(COM_TG, build_callback(CAND_OK, str(first)))
    assert "Ya existe un lead" in env.texts(COM_TG)[-1]
    env.press(COM_TG, build_callback(CAND_OK, str(second)))
    assert "pidió no ser contactada" in env.texts(COM_TG)[-1]
    with env.db.read() as conn:
        assert repo.leads_by_email(conn, "b@empresa.co") == []


def test_malformed_candidate_buttons(env: Env) -> None:
    env.press(COM_TG, build_callback(CAND_OK, "999"))
    env.press(COM_TG, build_callback(CAND_NO, "abc"))
    assert env.texts(COM_TG) == ["Ese correo ya no está pendiente."] * 2


def test_an_already_claimed_candidate_key_blocks_a_second_lead(env: Env) -> None:
    from jerico.crm.idempotency import claim, make_key

    env.inboxes[env.box1.id].messages = [_msg(1, "nuevo@empresa.co")]
    env.poll()
    cid = _pending(env)
    with env.db.tx() as tx:
        assert claim(tx, make_key("lead_from_mail", cid), START)
    env.press(COM_TG, build_callback(CAND_OK, str(cid)))
    with env.db.read() as conn:
        assert repo.leads_by_email(conn, "nuevo@empresa.co") == []
