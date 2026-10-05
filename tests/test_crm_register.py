"""Tests del registro de leads (VCRM-003, 004, 006, 066, 088, 110, 135, 137)."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crm_support import FakeClock, FakeTelegram
from jerico.crm import repo
from jerico.crm.bot import CANCELLED, CrmBot
from jerico.crm.db import CrmDatabase
from jerico.crm.fingerprint import fingerprint
from jerico.crm.model import AuditAction, AuditOutcome, AuthStatus, LeadState, Role, User
from jerico.crm.parsing import EXAMPLE_REGISTER, build_callback
from jerico.crm.ports import Update
from jerico.crm.timeutil import to_iso

START = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
CTO_TG = 1000
COM_TG = 2000
COM2_TG = 2100
LAW_TG = 3000
KEY = "clave-actual"
OLD_KEY = "clave-previa"
NEW_LEAD = "/nuevo Ana Pérez; 300 123 4567; ana@empresa.co; Empresa SAS; Plan anual"


@pytest.fixture
def db(tmp_path: Path) -> Iterator[CrmDatabase]:
    database = CrmDatabase(tmp_path / "crm.db")
    yield database
    database.close()


@pytest.fixture
def tg() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(START)


@pytest.fixture
def bot(db: CrmDatabase, tg: FakeTelegram, clock: FakeClock) -> CrmBot:
    return CrmBot(db, tg, clock.now, fingerprint_keys=(KEY, OLD_KEY))


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
            "com2": repo.insert_user(
                tx, telegram_id=COM2_TG, role=Role.COMMERCIAL, email="com2@k.co", now=START
            ),
            "law": repo.insert_user(
                tx, telegram_id=LAW_TG, role=Role.LAWYER, email="law@k.co", now=START
            ),
        }


_next_update = iter(range(1, 10_000))


def _msg(user_tg: int, text: str) -> Update:
    return Update(
        update_id=next(_next_update),
        user_id=user_tg,
        chat_id=user_tg,
        chat_type="private",
        text=text,
    )


def _cb(user_tg: int, data: str) -> Update:
    uid = next(_next_update)
    return Update(
        update_id=uid,
        user_id=user_tg,
        chat_id=user_tg,
        chat_type="private",
        callback_id=f"cb{uid}",
        callback_data=data,
    )


def run(bot: CrmBot, u: Update) -> None:
    asyncio.run(bot.process_update(u))


def _leads(db: CrmDatabase) -> list[dict[str, object]]:
    with db.read() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM crm_leads ORDER BY id").fetchall()]


def _lead(
    db: CrmDatabase,
    user_id: int | None,
    *,
    state: LeadState = LeadState.NUEVO,
    phone: str | None = "+573001234567",
    email: str | None = None,
) -> int:
    with db.tx() as tx:
        return repo.insert_lead(
            tx,
            assigned_user_id=user_id,
            state=state,
            now=START,
            fields={"name": "Previo", "phone_e164": phone, "email": email},
        )


def _suppress(db: CrmDatabase, normalized: str, key: str = KEY) -> None:
    with db.tx() as tx:
        tx.execute(
            "INSERT INTO crm_suppression (fingerprint, at, medium) VALUES (?, ?, 'telegram')",
            (fingerprint(key, normalized), to_iso(START)),
        )


def _buttons(sent: object) -> list[tuple[str, str]]:
    rows = getattr(sent, "buttons", None) or []
    return [(b.text, b.callback_data) for row in rows for b in row]


# --- Registro válido (VCRM-003, VCRM-066) ------------------------------------------------


def test_vcrm003_commercial_registers_new_lead_assigned_to_self(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    run(bot, _msg(COM_TG, NEW_LEAD))
    leads = _leads(db)
    assert len(leads) == 1
    lead = leads[0]
    assert lead["state"] == LeadState.NUEVO
    assert lead["assigned_user_id"] == users["com"].id
    assert lead["name"] == "Ana Pérez"
    assert lead["phone_e164"] == "+573001234567"
    assert lead["email"] == "ana@empresa.co"
    assert lead["company"] == "Empresa SAS"
    reply = tg.sent[-1]
    assert reply.chat_id == COM_TG
    assert "L-0001" in reply.text
    for value in ("Ana Pérez", "+573001234567", "ana@empresa.co", "Empresa SAS", "Plan anual"):
        assert value in reply.text


def test_vcrm003_cto_registers_lead_assigned_to_cto(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    run(bot, _msg(CTO_TG, "/nuevo Luis; ; luis@x.co"))
    lead = _leads(db)[0]
    assert lead["assigned_user_id"] == users["cto"].id
    assert lead["phone_e164"] is None
    assert "L-0001" in tg.sent[-1].text


def test_vcrm003_registration_records_event_note_and_audit(
    bot: CrmBot, db: CrmDatabase, users: dict[str, User]
) -> None:
    run(bot, _msg(COM_TG, NEW_LEAD))
    with db.read() as conn:
        events = repo.lead_events(conn, 1)
        notes = [dict(r) for r in conn.execute("SELECT * FROM crm_notes").fetchall()]
        audits = repo.audit_rows(conn)
    assert [(e.kind, e.new_value, e.actor_user_id) for e in events] == [
        ("state", "nuevo", users["com"].id)
    ]
    assert [(n["body"], n["author_user_id"]) for n in notes] == [("Plan anual", users["com"].id)]
    assert any(
        a["action"] == AuditAction.LEAD_CREATED and a["lead_id"] == 1 and a["outcome"] == "ok"
        for a in audits
    )


def test_vcrm003_without_note_no_note_is_stored(
    bot: CrmBot, db: CrmDatabase, users: dict[str, User]
) -> None:
    run(bot, _msg(COM_TG, "/nuevo Ana; 3001234567"))
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM crm_notes").fetchone()[0] == 0


def test_vcrm066_registration_asks_authorization_with_buttons(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    run(bot, _msg(COM_TG, NEW_LEAD))
    reply = tg.sent[-1]
    assert "autorización" in reply.text
    buttons = _buttons(reply)
    assert [text for text, _ in buttons] == ["Sí", "No"]
    with db.read() as conn:
        rows = conn.execute("SELECT * FROM crm_confirmations").fetchall()
    assert len(rows) == 1
    assert rows[0]["kind"] == "authorization_question"
    assert rows[0]["lead_id"] == 1
    assert rows[0]["user_id"] == users["com"].id
    assert buttons[0][1] == build_callback("conf", str(rows[0]["id"]), "si")
    assert buttons[1][1] == build_callback("conf", str(rows[0]["id"]), "no")


def test_vcrm066_unanswered_question_leaves_lead_without_authorization(
    bot: CrmBot, db: CrmDatabase, users: dict[str, User]
) -> None:
    run(bot, _msg(COM_TG, NEW_LEAD))
    assert _leads(db)[0]["auth_status"] == AuthStatus.SIN_AUTORIZACION


def test_vcrm066_answer_no_marks_without_authorization(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    run(bot, _msg(COM_TG, NEW_LEAD))
    run(bot, _cb(COM_TG, "v1:conf:1:no"))
    assert _leads(db)[0]["auth_status"] == AuthStatus.SIN_AUTORIZACION
    assert "sin autorización" in tg.sent[-1].text
    assert "L-0001" in tg.sent[-1].text
    with db.read() as conn:
        assert repo.get_pending_input(conn, users["com"].id, START) is None


def test_vcrm066_answer_yes_asks_for_evidence_and_opens_pending_input(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    run(bot, _msg(COM_TG, NEW_LEAD))
    run(bot, _cb(COM_TG, "v1:conf:1:si"))
    assert "Adjunte" in tg.sent[-1].text
    with db.read() as conn:
        pending = repo.get_pending_input(conn, users["com"].id, START)
    assert pending is not None
    assert pending.kind == "authorization_evidence"
    assert pending.lead_id == 1
    assert _leads(db)[0]["auth_status"] == AuthStatus.SIN_AUTORIZACION


def test_vcrm066_answer_yes_on_reassigned_lead_is_denied(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    run(bot, _msg(COM_TG, NEW_LEAD))
    with db.tx() as tx:
        repo.set_assignee(tx, 1, users["com2"].id)
    run(bot, _cb(COM_TG, "v1:conf:1:si"))
    assert "No tiene permiso" in tg.sent[-1].text
    with db.read() as conn:
        assert repo.get_pending_input(conn, users["com"].id, START) is None
        assert repo.audit_rows(conn)[-1]["action"] == AuditAction.PERMISSION_DENIED


# --- Errores de formato (VCRM-004) ------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "field"),
    [
        ("/nuevo ; 3001234567", "nombre"),
        ("/nuevo Ana", "contacto"),
        ("/nuevo Ana; ; ", "contacto"),
    ],
)
def test_vcrm004_missing_data_reports_field_and_example(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User], text: str, field: str
) -> None:
    run(bot, _msg(COM_TG, text))
    assert _leads(db) == []
    reply = tg.sent[-1].text
    assert field in reply
    assert EXAMPLE_REGISTER in reply


def test_vcrm004_invalid_contact_reports_field_and_example(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    run(bot, _msg(COM_TG, "/nuevo Ana; 12; "))
    assert _leads(db) == []
    assert "telefono" in tg.sent[-1].text
    assert EXAMPLE_REGISTER in tg.sent[-1].text


def test_vcrm004_lawyer_cannot_register(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    run(bot, _msg(LAW_TG, NEW_LEAD))
    assert _leads(db) == []
    assert "No tiene permiso" in tg.sent[-1].text
    with db.read() as conn:
        last = repo.audit_rows(conn)[-1]
    assert (last["action"], last["outcome"]) == (AuditAction.PERMISSION_DENIED, AuditOutcome.DENIED)


# --- Duplicado visible (VCRM-006) --------------------------------------------------------


def test_vcrm006_visible_duplicate_by_phone_warns_with_buttons(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    existing = _lead(db, users["com"].id, state=LeadState.CONTACTADO)
    run(bot, _msg(COM_TG, NEW_LEAD))
    assert len(_leads(db)) == 1
    reply = tg.sent[-1]
    assert "ya está registrado" in reply.text
    assert "L-0001" in reply.text
    assert "contactado" in reply.text
    assert "com@k.co" in reply.text
    assert _buttons(reply) == [
        ("Abrir lead existente", build_callback("abrir", str(existing))),
        ("Cancelar", build_callback("cancelar", str(existing))),
    ]
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM crm_confirmations").fetchone()[0] == 0


def test_vcrm006_visible_duplicate_by_email_for_cto(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    _lead(db, users["com"].id, phone=None, email="ana@empresa.co")
    run(bot, _msg(CTO_TG, "/nuevo Ana; ; ANA@Empresa.co"))
    assert len(_leads(db)) == 1
    assert "ya está registrado" in tg.sent[-1].text
    assert "com@k.co" in tg.sent[-1].text
    assert [s.chat_id for s in tg.sent] == [CTO_TG]


def test_vcrm006_open_existing_button_shows_lead(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    existing = _lead(db, users["com"].id)
    run(bot, _cb(COM_TG, build_callback("abrir", str(existing))))
    assert "L-0001" in tg.sent[-1].text
    assert "Previo" in tg.sent[-1].text


def test_vcrm006_open_foreign_lead_is_denied_without_data(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    existing = _lead(db, users["com2"].id)
    run(bot, _cb(COM_TG, build_callback("abrir", str(existing))))
    assert "Previo" not in tg.sent[-1].text
    assert "No tiene permiso" in tg.sent[-1].text


@pytest.mark.parametrize("data", ["v1:abrir:999", "v1:abrir:x"])
def test_vcrm006_open_missing_lead_or_bad_button(
    bot: CrmBot, tg: FakeTelegram, users: dict[str, User], data: str
) -> None:
    run(bot, _cb(COM_TG, data))
    assert "L-0999" in tg.sent[-1].text or "no válido" in tg.sent[-1].text


def test_vcrm006_cancel_button(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    existing = _lead(db, users["com"].id)
    run(bot, _cb(COM_TG, build_callback("cancelar", str(existing))))
    assert tg.sent[-1].text == CANCELLED
    assert len(_leads(db)) == 1


# --- Duplicado no visible (VCRM-110, VCRM-137) -------------------------------------------


@pytest.mark.parametrize(("owner", "label"), [("com2", "com2@k.co"), ("cto", "del CTO")])
def test_vcrm110_hidden_duplicate_no_data_and_cto_notice(
    bot: CrmBot,
    tg: FakeTelegram,
    db: CrmDatabase,
    users: dict[str, User],
    owner: str,
    label: str,
) -> None:
    existing = _lead(db, users[owner].id, state=LeadState.ACEPTADO)
    run(bot, _msg(COM_TG, NEW_LEAD))
    assert len(_leads(db)) == 1
    to_com = [s for s in tg.sent if s.chat_id == COM_TG]
    assert len(to_com) == 1
    assert "ya está registrado en el sistema" in to_com[0].text
    assert "se avisó al CTO" in to_com[0].text
    for leaked in ("L-0001", "Previo", "aceptado", label, "Abrir"):
        assert leaked not in to_com[0].text
    assert not to_com[0].buttons
    to_cto = [s for s in tg.sent if s.chat_id == CTO_TG]
    assert len(to_cto) == 1
    notice = to_cto[0]
    for expected in ("L-0001", label, "com@k.co", "02/03/2026 10:00"):
        assert expected in notice.text
    assert _buttons(notice) == [("Reasignar", build_callback("reasignar", str(existing)))]


def test_vcrm137_unassigned_lead_notice_says_without_commercial(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    _lead(db, users["com2"].id)
    with db.tx() as tx:
        repo.deactivate_user(tx, users["com2"].id, now=START)
    run(bot, _msg(COM_TG, NEW_LEAD))
    notice = next(s for s in tg.sent if s.chat_id == CTO_TG)
    assert "sin comercial asignado" in notice.text


def test_vcrm137_reassign_button_from_notice_opens_targets(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    existing = _lead(db, users["com2"].id)
    run(bot, _msg(COM_TG, NEW_LEAD))
    notice = next(s for s in tg.sent if s.chat_id == CTO_TG)
    run(bot, _cb(CTO_TG, _buttons(notice)[0][1]))
    targets = _buttons(tg.sent[-1])
    assert build_callback("reasignar", str(existing), str(users["com"].id)) in [
        data for _, data in targets
    ]


# --- Perdidos (VCRM-135) -----------------------------------------------------------------


def test_vcrm135_match_only_with_lost_creates_new_lead(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    lost = _lead(db, users["com2"].id, state=LeadState.PERDIDO)
    run(bot, _msg(COM_TG, NEW_LEAD))
    leads = _leads(db)
    assert len(leads) == 2
    assert leads[0]["state"] == LeadState.PERDIDO
    assert leads[0]["assigned_user_id"] == users["com2"].id
    assert leads[1]["assigned_user_id"] == users["com"].id
    assert "L-0002" in tg.sent[-1].text
    assert [s.chat_id for s in tg.sent] == [COM_TG]
    with db.read() as conn:
        assert repo.lead_events(conn, lost) == []


# --- Supresión (VCRM-088) ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("normalized", "key"),
    [("+573001234567", KEY), ("ana@empresa.co", KEY), ("ana@empresa.co", OLD_KEY)],
)
def test_vcrm088_suppressed_fingerprint_blocks_registration(
    bot: CrmBot,
    tg: FakeTelegram,
    db: CrmDatabase,
    users: dict[str, User],
    normalized: str,
    key: str,
) -> None:
    _suppress(db, normalized, key)
    run(bot, _msg(COM_TG, NEW_LEAD))
    assert _leads(db) == []
    reply = tg.sent[-1]
    assert "solicitó no ser contactado" in reply.text
    assert "Ana" not in reply.text
    assert not reply.buttons


def test_vcrm088_suppression_prevails_over_duplicates(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    _lead(db, users["com"].id)
    _lead(db, users["com2"].id, email="ana@empresa.co", phone=None)
    _lead(db, users["com2"].id, state=LeadState.PERDIDO)
    _suppress(db, "+573001234567")
    run(bot, _msg(COM_TG, NEW_LEAD))
    assert len(_leads(db)) == 3
    assert [s.chat_id for s in tg.sent] == [COM_TG]
    assert "solicitó no ser contactado" in tg.sent[0].text
    assert "L-000" not in tg.sent[0].text


def test_vcrm088_suppressed_other_contact_does_not_block(
    bot: CrmBot, db: CrmDatabase, users: dict[str, User]
) -> None:
    _suppress(db, "otro@x.co")
    run(bot, _msg(COM_TG, NEW_LEAD))
    assert len(_leads(db)) == 1
