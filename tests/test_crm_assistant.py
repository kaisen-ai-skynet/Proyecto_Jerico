"""Asistente comercial con LLM: flag, permisos, seudonimización, costos y degradación (VCRM-A*)."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crm_support import FakeClock, FakeTelegram, make_settings
from jerico.crm import repo
from jerico.crm.assistant import (
    CAP_REASONS,
    DISABLED,
    DRAFT_HEADER,
    HELP,
    NOT_ALLOWED_LEAD,
    NOT_FOUND,
    UNAVAILABLE,
    AssistantContext,
    register_assistant,
)
from jerico.crm.assistant_budget import AssistantBudget
from jerico.crm.bot import CrmBot
from jerico.crm.db import CrmDatabase
from jerico.crm.llm import LlmError, LlmResult
from jerico.crm.model import AuditAction, AuditOutcome, EventKind, LeadState, Role, User
from jerico.crm.ports import Update

START = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
CTO_TG, COM_TG, COM2_TG, LAW_TG = 1000, 2000, 2001, 3000
SECRETS = ("Ana", "Pérez", "Andina", "3001234567", "ana.perez@andina.co", "1020304050", "Gómez")


class FakeLlm:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.reply = LlmResult(text="Hola [CLIENTE]: seguimos.", input_tokens=100, output_tokens=40)
        self.error: LlmError | None = None

    async def complete(self, *, system: str, user: str, max_output_tokens: int) -> LlmResult:
        self.calls.append({"system": system, "user": user, "max": max_output_tokens})
        if self.error is not None:
            raise self.error
        return self.reply

    def sent_text(self) -> str:
        return " ".join(f"{c['system']} {c['user']}" for c in self.calls)


@pytest.fixture
def db(tmp_path: Path) -> Iterator[CrmDatabase]:
    database = CrmDatabase(tmp_path / "crm.db")
    yield database
    database.close()


@pytest.fixture
def tg() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def llm() -> FakeLlm:
    return FakeLlm()


def _build(db: CrmDatabase, tg: FakeTelegram, llm: FakeLlm | None, **settings: object) -> CrmBot:
    clock = FakeClock(START)
    cfg = make_settings(**{"assistant_enabled": True, **settings})
    bot = CrmBot(db, tg, clock.now)
    register_assistant(bot, AssistantContext(cfg, db, llm, AssistantBudget(cfg), clock.now))
    return bot


@pytest.fixture
def users(db: CrmDatabase) -> dict[str, User]:
    with db.tx() as tx:
        return {
            "cto": repo.insert_user(
                tx, telegram_id=CTO_TG, role=Role.CTO, email="c@k.co", now=START
            ),
            "com": repo.insert_user(
                tx, telegram_id=COM_TG, role=Role.COMMERCIAL, email="m@k.co", now=START
            ),
            "com2": repo.insert_user(
                tx, telegram_id=COM2_TG, role=Role.COMMERCIAL, email="m2@k.co", now=START
            ),
            "law": repo.insert_user(
                tx, telegram_id=LAW_TG, role=Role.LAWYER, email="l@k.co", now=START
            ),
        }


def _lead(db: CrmDatabase, owner: User, **fields: str) -> int:
    base = {
        "name": "Ana María Pérez",
        "company": "Distribuciones Andina",
        "phone_e164": "+573001234567",
        "email": "ana.perez@andina.co",
        "doc_number": "1020304050",
        "legal_rep": "Carlos Gómez",
        "service": "Automatización para Andina",
    }
    with db.tx() as tx:
        lead_id = repo.insert_lead(
            tx,
            assigned_user_id=owner.id,
            state=LeadState.CONTACTED,
            now=START,
            fields={**base, **fields},
        )
        repo.add_event(
            tx,
            lead_id=lead_id,
            kind=EventKind.STATE,
            actor_user_id=owner.id,
            at=START,
            new_value="contacted",
        )
        repo.add_event(
            tx,
            lead_id=lead_id,
            kind=EventKind.FIELD,
            actor_user_id=owner.id,
            at=START,
            field="phone_e164",
            old_value="+570000000",
            new_value="+573001234567",
        )
        repo.insert_note(
            tx,
            lead_id=lead_id,
            author_user_id=owner.id,
            body="Habló Ana Pérez al 3001234567, quiere cotización",
            at=START,
        )
    return lead_id


def _say(bot: CrmBot, tg_id: int, text: str, uid: int = 1) -> None:
    asyncio.run(
        bot.process_update(
            Update(update_id=uid, user_id=tg_id, chat_id=tg_id, chat_type="private", text=text)
        )
    )


def _texts(tg: FakeTelegram, chat: int) -> list[str]:
    return [s.text for s in tg.sent if s.chat_id == chat]


def _count(db: CrmDatabase, sql: str) -> int:
    with db.read() as conn:
        return int(conn.execute(sql).fetchone()[0])


# --- Flag, permisos y ayuda ---------------------------------------------------------------


def test_vcrma30_disabled_flag_never_touches_the_network(
    db: CrmDatabase, tg: FakeTelegram, llm: FakeLlm, users: dict[str, User]
) -> None:
    bot = _build(db, tg, llm, assistant_enabled=False)
    _say(bot, COM_TG, "/asistente pregunta cuántos leads tengo")
    assert _texts(tg, COM_TG) == [DISABLED] and llm.calls == []


def test_vcrma04_lawyer_is_denied_without_calling(
    db: CrmDatabase, tg: FakeTelegram, llm: FakeLlm, users: dict[str, User]
) -> None:
    bot = _build(db, tg, llm)
    _say(bot, LAW_TG, "/asistente pregunta hola")
    assert llm.calls == []
    assert _count(db, "SELECT COUNT(*) FROM crm_audit WHERE action='permission_denied'") == 1


def test_help_and_missing_client(
    db: CrmDatabase, tg: FakeTelegram, llm: FakeLlm, users: dict[str, User]
) -> None:
    bot = _build(db, tg, llm)
    _say(bot, COM_TG, "/asistente")
    _say(bot, COM_TG, "/asistente pregunta", uid=2)  # sin texto
    assert _texts(tg, COM_TG) == [HELP, HELP] and llm.calls == []
    bot2 = _build(db, tg, None)  # A31: flag sin llave
    _say(bot2, COM_TG, "/asistente resumen L-0001", uid=3)
    assert _texts(tg, COM_TG)[-1] == UNAVAILABLE


# --- Seudonimización (A10..A13) -----------------------------------------------------------


def test_vcrma10_summary_sends_no_personal_data_and_restores_locally(
    db: CrmDatabase, tg: FakeTelegram, llm: FakeLlm, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    bot = _build(db, tg, llm)
    _say(bot, COM_TG, f"/asistente resumen L-{lead_id:04d}")
    assert len(llm.calls) == 1
    leaked = [s for s in SECRETS if s in llm.sent_text()]
    assert leaked == []
    reply = _texts(tg, COM_TG)[-1]
    assert "Hola Ana María Pérez: seguimos." in reply  # A13: se repone solo localmente
    assert "Generado por IA" in reply


def test_vcrma11_notes_are_not_sent_by_default_and_scrubbed_when_enabled(
    db: CrmDatabase, tg: FakeTelegram, llm: FakeLlm, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    _say(_build(db, tg, llm), COM_TG, f"/asistente resumen L-{lead_id:04d}")
    assert "cotización" not in llm.sent_text()
    llm.calls.clear()
    on = _build(db, tg, llm, assistant_include_notes=True)
    _say(on, COM_TG, f"/asistente resumen L-{lead_id:04d}", uid=2)
    assert "cotización" in llm.sent_text()
    assert [s for s in SECRETS if s in llm.sent_text()] == []


def test_vcrma12_free_text_is_scrubbed_and_field_values_never_travel(
    db: CrmDatabase, tg: FakeTelegram, llm: FakeLlm, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    bot = _build(db, tg, llm)
    _say(
        bot,
        COM_TG,
        f"/asistente borrador L-{lead_id:04d} menciona que llamé al 3109998877 "
        "y escribí a otra@gmail.com",
    )
    sent = llm.sent_text()
    assert "3109998877" not in sent and "otra@gmail.com" not in sent
    assert "+570000000" not in sent  # valor antiguo de un campo editado: nunca


# --- Gate y alcance (A01..A06) ------------------------------------------------------------


def test_vcrma01_draft_is_labelled_and_creates_nothing_for_the_client(
    db: CrmDatabase, tg: FakeTelegram, llm: FakeLlm, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    bot = _build(db, tg, llm)
    before = {
        "crm_proposals": _count(db, "SELECT COUNT(*) FROM crm_proposals"),
        "crm_sends": _count(db, "SELECT COUNT(*) FROM crm_sends"),
    }
    state_before = _count(db, "SELECT COUNT(*) FROM crm_lead_events")
    _say(bot, COM_TG, f"/asistente borrador L-{lead_id:04d}")
    assert _texts(tg, COM_TG)[-1].startswith(DRAFT_HEADER)
    assert _count(db, "SELECT COUNT(*) FROM crm_proposals") == before["crm_proposals"]
    assert _count(db, "SELECT COUNT(*) FROM crm_sends") == before["crm_sends"]
    assert _count(db, "SELECT COUNT(*) FROM crm_lead_events") == state_before
    assert all(s.chat_id == COM_TG for s in tg.sent)  # nada al cliente ni a terceros


def test_vcrma05_foreign_lead_is_invisible(
    db: CrmDatabase, tg: FakeTelegram, llm: FakeLlm, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com2"])
    bot = _build(db, tg, llm)
    _say(bot, COM_TG, f"/asistente resumen L-{lead_id:04d}")
    _say(bot, COM_TG, "/asistente resumen L-9999", uid=2)
    _say(bot, COM_TG, "/asistente resumen xyz", uid=3)
    assert _texts(tg, COM_TG) == [NOT_FOUND] * 3 and llm.calls == []


def test_vcrma06_suppressed_and_blocked_leads_are_refused(
    db: CrmDatabase, tg: FakeTelegram, llm: FakeLlm, users: dict[str, User]
) -> None:
    suppressed = _lead(db, users["com"])
    blocked = _lead(db, users["com"])
    with db.tx() as tx:
        tx.execute(
            "UPDATE crm_leads SET suppressed_at=? WHERE id=?", ("2026-03-01T00:00:00Z", suppressed)
        )
        tx.execute("UPDATE crm_leads SET commercial_block=1 WHERE id=?", (blocked,))
    bot = _build(db, tg, llm)
    _say(bot, COM_TG, f"/asistente resumen L-{suppressed:04d}")
    _say(bot, COM_TG, f"/asistente borrador L-{blocked:04d}", uid=2)
    assert _texts(tg, COM_TG) == [NOT_ALLOWED_LEAD, NOT_ALLOWED_LEAD] and llm.calls == []


def test_vcrma05_pipeline_question_uses_only_visible_aggregates(
    db: CrmDatabase, tg: FakeTelegram, llm: FakeLlm, users: dict[str, User]
) -> None:
    _lead(db, users["com"])
    _lead(db, users["com2"], name="Beatriz Ruiz")
    bot = _build(db, tg, llm)
    _say(bot, COM_TG, "/asistente pregunta cuántos leads tengo")
    sent = llm.sent_text()
    assert "Leads visibles: 1" in sent
    assert [s for s in (*SECRETS, "Beatriz", "Ruiz") if s in sent] == []


# --- Costos y degradación (A20..A33) ------------------------------------------------------


def test_vcrma20_21_output_is_capped_and_each_call_is_audited_and_counted(
    db: CrmDatabase, tg: FakeTelegram, llm: FakeLlm, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    bot = _build(db, tg, llm, assistant_max_output_tokens=999_999)
    _say(bot, COM_TG, f"/asistente resumen L-{lead_id:04d}")
    assert llm.calls[0]["max"] == 2000
    with db.read() as conn:
        rows = [r for r in repo.audit_rows(conn) if r["action"] == AuditAction.LLM_CALL]
        tokens = repo.get_meta(conn, "llm:tokens:2026-03-02")
    assert [r["outcome"] for r in rows] == [AuditOutcome.OK]
    assert tokens == "140"


def test_vcrma22_daily_cap_cuts_service_and_warns_cto_once(
    db: CrmDatabase, tg: FakeTelegram, llm: FakeLlm, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    bot = _build(db, tg, llm, assistant_daily_token_cap=100)
    _say(bot, COM_TG, f"/asistente resumen L-{lead_id:04d}")  # 140 tokens: alcanza el tope
    _say(bot, COM_TG, f"/asistente resumen L-{lead_id:04d}", uid=2)
    _say(bot, COM_TG, f"/asistente resumen L-{lead_id:04d}", uid=3)
    assert len(llm.calls) == 1
    assert _texts(tg, COM_TG)[-1] == CAP_REASONS["daily_cap"]
    assert len(_texts(tg, CTO_TG)) == 1  # un solo aviso al CTO por día


def test_vcrma23_per_user_cap(
    db: CrmDatabase, tg: FakeTelegram, llm: FakeLlm, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    bot = _build(db, tg, llm, assistant_user_daily_calls=1)
    _say(bot, COM_TG, f"/asistente resumen L-{lead_id:04d}")
    _say(bot, COM_TG, f"/asistente resumen L-{lead_id:04d}", uid=2)
    assert len(llm.calls) == 1 and _texts(tg, COM_TG)[-1] == CAP_REASONS["user_cap"]


def test_vcrma32_33_failures_degrade_cleanly_then_breaker_opens(
    db: CrmDatabase, tg: FakeTelegram, llm: FakeLlm, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    llm.error = LlmError("http")
    bot = _build(db, tg, llm)
    for uid in (1, 2, 3):
        _say(bot, COM_TG, f"/asistente resumen L-{lead_id:04d}", uid=uid)
    assert _texts(tg, COM_TG).count(UNAVAILABLE) == 3
    _say(bot, COM_TG, f"/asistente resumen L-{lead_id:04d}", uid=4)
    assert len(llm.calls) == 3  # con el corta-circuito abierto no se llama
    assert _texts(tg, COM_TG)[-1] == CAP_REASONS["breaker"]
    with db.read() as conn:
        outcomes = [
            r["outcome"] for r in repo.audit_rows(conn) if r["action"] == AuditAction.LLM_CALL
        ]
    assert outcomes == [AuditOutcome.ERROR] * 3


def test_vcrma21_nothing_of_the_conversation_is_logged_or_audited(
    db: CrmDatabase, tg: FakeTelegram, llm: FakeLlm, users: dict[str, User]
) -> None:
    from loguru import logger

    lines: list[str] = []
    sink = logger.add(lines.append, format="{message}", level="INFO")
    try:
        lead_id = _lead(db, users["com"])
        _say(_build(db, tg, llm), COM_TG, f"/asistente resumen L-{lead_id:04d}")
    finally:
        logger.remove(sink)
    text = "".join(lines)
    assert "caso=resumen" in text and "entrada=100" in text and "salida=40" in text
    assert "costo=no calculado" in text
    assert [s for s in (*SECRETS, "seguimos") if s in text] == []


def test_vcrma22_cost_cap_requires_prices_and_cuts_when_reached(
    db: CrmDatabase, tg: FakeTelegram, llm: FakeLlm, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    bot = _build(
        db,
        tg,
        llm,
        assistant_price_in_per_mtok=1_000_000.0,  # 1 USD por token: solo para la prueba
        assistant_price_out_per_mtok=1_000_000.0,
        assistant_daily_cost_cap_usd=100.0,
    )
    _say(bot, COM_TG, f"/asistente resumen L-{lead_id:04d}")  # 140 USD
    _say(bot, COM_TG, f"/asistente resumen L-{lead_id:04d}", uid=2)
    assert len(llm.calls) == 1 and _texts(tg, COM_TG)[-1] == CAP_REASONS["daily_cap"]


def test_context_covers_cadence_reassign_and_titular_events(
    db: CrmDatabase, tg: FakeTelegram, llm: FakeLlm, users: dict[str, User]
) -> None:
    from jerico.crm.model import Cadence

    lead_id = _lead(db, users["com"])
    with db.tx() as tx:
        repo.upsert_cadence(
            tx,
            Cadence(lead_id=lead_id, reason="price", interval_days=7, total_steps=4, steps_done=1),
        )
        for kind in (EventKind.REASSIGN, EventKind.TITULAR_REQUEST):
            repo.add_event(tx, lead_id=lead_id, kind=kind, actor_user_id=users["com"].id, at=START)
    _say(_build(db, tg, llm), COM_TG, f"/asistente resumen L-{lead_id:04d}")
    sent = llm.sent_text()
    assert "cada 7 días, paso 1 de 4" in sent
    assert "reasignación de comercial" in sent and "solicitud del titular" in sent


def test_cap_without_active_cto_does_not_crash(
    db: CrmDatabase, tg: FakeTelegram, llm: FakeLlm, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    with db.tx() as tx:
        tx.execute("UPDATE crm_users SET active=0 WHERE role='cto'")
    bot = _build(db, tg, llm, assistant_daily_token_cap=100)
    _say(bot, COM_TG, f"/asistente resumen L-{lead_id:04d}")
    _say(bot, COM_TG, f"/asistente resumen L-{lead_id:04d}", uid=2)
    assert _texts(tg, COM_TG)[-1] == CAP_REASONS["daily_cap"] and _texts(tg, CTO_TG) == []
