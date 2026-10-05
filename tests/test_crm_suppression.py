"""Tests de la supresión ordenada por el CTO, excepción legal y aviso de copias (T20a).

Requisitos: VCRM-073, 094, 154, 155, 165 (decisiones K-3 y K-4).
"""

import asyncio
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from crm_support import FakeClock, FakeEmailSender, FakeTelegram
from jerico.crm import compliance, repo
from jerico.crm.bot import CrmBot
from jerico.crm.db import CrmDatabase
from jerico.crm.files import LocalFileStore
from jerico.crm.fingerprint import fingerprint
from jerico.crm.model import (
    AlertKind,
    AuditAction,
    AuthStatus,
    Channel,
    EventKind,
    LeadState,
    Role,
    User,
)
from jerico.crm.outbox import SUPPRESSION_KIND, OutboxWorker, enqueue_critical, escalate
from jerico.crm.ports import FileKind, FileRef, Update
from jerico.crm.timeutil import to_iso

START = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
CTO_TG = 1000
COM_TG = 2000
LAW_TG = 3000
KEY = "clave-actual"
PHONE = "+573001234567"
EMAIL = "ana@empresa.co"
# Centinelas: ningún dato del titular puede quedar en claro tras la supresión (VCRM-165).
NAME = "Zuleima Centinela"
DOC = "987654321012"
NOTE = "nota-centinela-xyz"
REJECT = "motivo-centinela-qwe"
LEGAL_REP = "Representante Centinela"


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
def store(tmp_path: Path) -> LocalFileStore:
    return LocalFileStore(tmp_path / "files")


@pytest.fixture
def bot(db: CrmDatabase, tg: FakeTelegram, store: LocalFileStore, clock: FakeClock) -> CrmBot:
    return CrmBot(db, tg, clock.now, fingerprint_keys=(KEY,), files=store)


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
        callback_data=data,
        callback_id=f"cb{uid}",
    )


def _file(user_tg: int, file_id: str, kind: FileKind) -> Update:
    return Update(
        update_id=next(_next_update),
        user_id=user_tg,
        chat_id=user_tg,
        chat_type="private",
        file=FileRef(file_id=file_id, size=None, kind=kind),
    )


def run(bot: CrmBot, u: Update) -> None:
    asyncio.run(bot.process_update(u))


def _lead(
    db: CrmDatabase,
    user_id: int | None,
    state: LeadState = LeadState.NUEVO,
    *,
    ever_accepted: bool = False,
    retracted: bool = False,
    **fields: Any,
) -> int:
    base: dict[str, Any] = {"name": NAME, "phone_e164": PHONE, "email": EMAIL}
    base.update(fields)
    with db.tx() as tx:
        lead_id = repo.insert_lead(
            tx, assigned_user_id=user_id, state=state, now=START, fields=base
        )
        changes: dict[str, Any] = {}
        if ever_accepted:
            changes["ever_accepted"] = 1
        if retracted:
            changes["rejection_is_retraction"] = 1
        if changes:
            repo.update_lead(tx, lead_id, changes, now=START)
    return lead_id


def _rows(db: CrmDatabase, sql: str) -> list[dict[str, Any]]:
    with db.read() as conn:
        return [dict(r) for r in conn.execute(sql).fetchall()]


def _lead_row(db: CrmDatabase, lead_id: int) -> dict[str, Any]:
    return _rows(db, f"SELECT * FROM crm_leads WHERE id = {lead_id}")[0]  # noqa: S608


def _attach(
    db: CrmDatabase,
    store: LocalFileStore,
    lead_id: int,
    author: int,
    content: bytes,
    kind: str = "photo",
) -> str:
    tmp = store.new_tmp_path(".bin")
    tmp.write_bytes(content)
    key = store.save_atomic(lead_id, tmp)
    with db.tx() as tx:
        repo.insert_attachment(
            tx,
            lead_id=lead_id,
            kind=kind,
            author_user_id=author,
            at=START,
            storage_key=key,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )
    return key


def _suppressed_ids(db: CrmDatabase) -> list[int]:
    rows = _rows(db, "SELECT id FROM crm_leads WHERE suppressed_at IS NOT NULL ORDER BY id")
    return [r["id"] for r in rows]


def _notices(db: CrmDatabase) -> list[dict[str, Any]]:
    return _rows(
        db,
        f"SELECT * FROM crm_outbox WHERE kind = '{SUPPRESSION_KIND}' ORDER BY id",  # noqa: S608
    )


# --- Leads del mismo titular (VCRM-073; decisión K-3) ------------------------------------


def test_vcrm073_suppresses_every_lead_of_the_same_contact_and_confirms_all_ids(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    a = _lead(db, users["com"].id, LeadState.PERDIDO)
    b = _lead(
        db,
        users["com"].id,
        LeadState.RECHAZADO,
        ever_accepted=True,
        retracted=True,
        phone_e164="+573009999999",
    )  # retractado; solo comparte el correo
    other = _lead(db, users["com"].id, phone_e164="+573005555555", email="otro@x.co")
    run(bot, _msg(CTO_TG, "/suprimir L-0001"))
    assert _suppressed_ids(db) == [a, b]
    assert {_lead_row(db, i)["suppression_cause"] for i in (a, b)} == {"orden_cto"}
    assert _lead_row(db, other)["name"] == NAME
    reply = tg.sent[-1]
    assert reply.chat_id == CTO_TG
    assert "L-0001" in reply.text and "L-0002" in reply.text and "L-0003" not in reply.text
    audits = [r for r in repo_audit(db) if r["action"] == AuditAction.LEAD_SUPPRESSED]
    assert [(r["lead_id"], r["actor"], r["detail_code"]) for r in audits] == [
        (a, f"user:{users['cto'].id}", "orden_cto"),
        (b, f"user:{users['cto'].id}", "orden_cto"),
    ]


def repo_audit(db: CrmDatabase) -> list[dict[str, Any]]:
    with db.read() as conn:
        return repo.audit_rows(conn)


def test_vcrm073_titular_group_has_no_transitive_closure(
    bot: CrmBot, db: CrmDatabase, users: dict[str, User]
) -> None:
    a = _lead(db, users["com"].id, phone_e164="+573001111111", email="a@x.co")
    b = _lead(db, users["com"].id, phone_e164="+573001111111", email="bc@x.co")
    c = _lead(db, users["com"].id, phone_e164="+573003333333", email="bc@x.co")
    with db.read() as conn:
        lead_a = repo.get_lead(conn, a)
        assert lead_a is not None
        assert [lead.id for lead in compliance.titular_leads(conn, lead_a)] == [a, b]
    run(bot, _msg(CTO_TG, "/suprimir L-0001"))
    assert _suppressed_ids(db) == [a, b]
    assert _lead_row(db, c)["email"] == "bc@x.co"


def test_vcrm073_deletes_personal_data_and_keeps_contact_fingerprint(
    bot: CrmBot, db: CrmDatabase, store: LocalFileStore, users: dict[str, User]
) -> None:
    com = users["com"].id
    lead_id = _lead(
        db,
        com,
        LeadState.RECHAZADO,
        company="Empresa SAS",
        doc_type="CC",
        doc_number=DOC,
        legal_rep=LEGAL_REP,
        service="Plan anual",
        agreed_value="10",
        start_term="marzo",
    )
    key = _attach(db, store, lead_id, com, b"foto de la reunion")
    with db.tx() as tx:
        repo.update_lead(tx, lead_id, {"reject_reason": "otro", "reject_text": REJECT}, now=START)
        repo.insert_note(tx, lead_id=lead_id, author_user_id=com, body=NOTE, at=START)
        repo.add_event(
            tx,
            lead_id=lead_id,
            kind=EventKind.FIELD,
            actor_user_id=com,
            at=START,
            field="nombre",
            old_value="Ana",
            new_value=NAME,
        )
        repo.add_event(
            tx,
            lead_id=lead_id,
            kind=EventKind.STATE,
            actor_user_id=com,
            at=START,
            old_value="nuevo",
            new_value="rechazado",
            reason="otro",
            reason_text=REJECT,
        )
        enqueue_critical(
            tx,
            kind="handoff",
            channel=Channel.EMAIL,
            recipient_user_id=users["law"].id,
            lead_id=lead_id,
            subject=f"Handoff {NAME}",
            body=f"{NAME} {DOC}",
            key="h1",
            now=START,
        )
        repo.create_confirmation(
            tx, kind="retract", lead_id=lead_id, user_id=com, now=START, reason_text=REJECT
        )
        repo.set_pending_input(tx, user_id=com, kind="reject_other", now=START, lead_id=lead_id)
    run(bot, _msg(CTO_TG, "/suprimir L-0001"))
    row = _lead_row(db, lead_id)
    for column in (
        "name",
        "phone_e164",
        "email",
        "company",
        "client_type",
        "doc_type",
        "doc_number",
        "legal_rep",
        "service",
        "agreed_value",
        "start_term",
        "reject_text",
    ):
        assert row[column] is None, column
    assert row["suppressed_at"] == to_iso(START)
    assert row["legal_hold_basis"] is None and row["commercial_block"] == 0
    assert _rows(db, "SELECT * FROM crm_notes") == []
    assert not (store.base_dir / key).exists()
    assert [r["deleted_at"] for r in _rows(db, "SELECT * FROM crm_attachments")] == [to_iso(START)]
    events = _rows(db, "SELECT * FROM crm_lead_events")
    assert [(e["kind"], e["reason_text"]) for e in events] == [("state", None)]
    handoff = _rows(db, "SELECT * FROM crm_outbox WHERE kind = 'handoff'")[0]
    assert handoff["subject"] is None and handoff["body"] is None
    assert _rows(db, "SELECT * FROM crm_confirmations") == []
    assert _rows(db, "SELECT * FROM crm_pending_inputs") == []
    fps = {r["fingerprint"] for r in _rows(db, "SELECT * FROM crm_suppression")}
    assert fps == {fingerprint(KEY, PHONE), fingerprint(KEY, EMAIL)}


def _all_text(db: CrmDatabase) -> str:
    chunks: list[str] = []
    with db.read() as conn:
        tables = [
            r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        ]
        for table in tables:
            for row in conn.execute(f"SELECT * FROM {table}"):  # noqa: S608
                chunks += [str(v) for v in tuple(row) if v is not None]
    return "\n".join(chunks)


def test_vcrm165_evidence_reduced_to_minimal_footprint_without_personal_data(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, store: LocalFileStore, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id, doc_type="CC", doc_number=DOC, legal_rep=LEGAL_REP)
    with db.tx() as tx:
        repo.insert_note(tx, lead_id=lead_id, author_user_id=users["com"].id, body=NOTE, at=START)
    tg.files["ev1"] = b"firma del titular"
    run(bot, _msg(COM_TG, "/autorizacion L-0001"))
    run(bot, _file(COM_TG, "ev1", "document"))
    evidence = _rows(db, "SELECT * FROM crm_attachments")[0]
    consent_before = _rows(db, "SELECT * FROM crm_consents")
    assert (store.base_dir / evidence["storage_key"]).exists()
    run(bot, _msg(CTO_TG, "/suprimir L-0001"))
    assert not (store.base_dir / evidence["storage_key"]).exists()
    after = _rows(db, "SELECT * FROM crm_attachments")[0]
    assert after["kind"] == "authorization"
    assert after["size_bytes"] == len(b"firma del titular")
    assert after["sha256"] == hashlib.sha256(b"firma del titular").hexdigest()
    assert after["deleted_at"] == to_iso(START)
    assert _rows(db, "SELECT * FROM crm_consents") == consent_before
    assert consent_before[0]["status"] == AuthStatus.AUTORIZADA
    text = _all_text(db)
    for sentinel in (NAME, PHONE, EMAIL, DOC, NOTE, LEGAL_REP, "3001234567"):
        assert sentinel not in text, sentinel


@pytest.mark.parametrize("who", [COM_TG, LAW_TG])
def test_vcrm073_only_cto_may_order_suppression(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User], who: int
) -> None:
    _lead(db, users["com"].id, LeadState.ACEPTADO, ever_accepted=True)
    run(bot, _msg(who, "/suprimir L-0001"))
    assert _suppressed_ids(db) == []
    assert _notices(db) == []
    assert tg.sent[-1].chat_id == who


@pytest.mark.parametrize(
    "text",
    [
        "/suprimir",
        "/suprimir X-1",
        "/suprimir L-0001; conservar: nombre",
        "/suprimir L-0001; conservar: color; fundamento: contrato",
        "/suprimir L-0001; fundamento: contrato; conservar: nombre",
    ],
)
def test_vcrm073_invalid_format_suppresses_nothing(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User], text: str
) -> None:
    _lead(db, users["com"].id, LeadState.GANADO, ever_accepted=True)
    run(bot, _msg(CTO_TG, text))
    assert _suppressed_ids(db) == []
    assert "/suprimir L-0042" in tg.sent[-1].text


def test_vcrm073_unknown_or_already_suppressed_lead(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    run(bot, _msg(CTO_TG, "/suprimir L-0009"))
    assert "no existe" in tg.sent[-1].text
    _lead(db, users["com"].id)
    run(bot, _msg(CTO_TG, "/suprimir L-0001"))
    count = len(_notices(db))
    run(bot, _msg(CTO_TG, "/suprimir L-0001"))
    assert "ya fue suprimido" in tg.sent[-1].text
    assert len(_notices(db)) == count


# --- Excepción por deber legal o contractual (VCRM-094) ----------------------------------


def test_vcrm094_keeps_only_listed_fields_on_won_lead_and_suppresses_the_rest(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    won = _lead(
        db,
        users["com"].id,
        LeadState.GANADO,
        ever_accepted=True,
        doc_type="CC",
        doc_number=DOC,
        legal_rep=LEGAL_REP,
    )
    lost = _lead(db, users["com"].id, LeadState.PERDIDO, doc_number=DOC)
    run(
        bot,
        _msg(
            CTO_TG, "/suprimir L-0001; conservar: nombre, documento; fundamento: contrato vigente"
        ),
    )
    assert _suppressed_ids(db) == [won, lost]
    kept = _lead_row(db, won)
    assert (kept["name"], kept["doc_type"], kept["doc_number"]) == (NAME, "CC", DOC)
    assert kept["phone_e164"] is None and kept["email"] is None and kept["legal_rep"] is None
    assert kept["commercial_block"] == 1
    assert kept["legal_hold_basis"] == "contrato vigente"
    gone = _lead_row(db, lost)
    assert gone["name"] is None and gone["doc_number"] is None
    assert gone["commercial_block"] == 0 and gone["legal_hold_basis"] is None
    assert "L-0001" in tg.sent[-1].text and "L-0002" in tg.sent[-1].text
    with db.read() as conn:
        lead = repo.get_lead(conn, won)
        assert lead is not None
        assert not compliance.may_contact_commercially(conn, lead, (KEY,))


def test_vcrm094_exception_rejected_when_no_lead_is_accepted_or_won(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    _lead(db, users["com"].id, LeadState.RECHAZADO, ever_accepted=True, retracted=True)
    run(bot, _msg(CTO_TG, "/suprimir L-0001; conservar: nombre; fundamento: contrato"))
    assert _suppressed_ids(db) == []
    assert _notices(db) == []
    assert "aceptado" in tg.sent[-1].text and "ganado" in tg.sent[-1].text


# --- Notificación de supresión de copias (VCRM-154, 155) ---------------------------------


def test_vcrm154_one_critical_notice_per_recipient_and_channel_without_personal_data(
    bot: CrmBot, db: CrmDatabase, users: dict[str, User]
) -> None:
    accepted = _lead(db, users["com"].id, LeadState.GANADO, ever_accepted=True)
    _lead(db, users["com"].id, LeadState.PERDIDO)
    run(bot, _msg(CTO_TG, "/suprimir L-0002"))
    notices = _notices(db)
    got = {(n["recipient_user_id"], n["channel"]) for n in notices}
    assert got == {
        (users["cto"].id, "telegram"),
        (users["law"].id, "telegram"),
        (users["law"].id, "email"),
    }
    assert len(notices) == 3
    for n in notices:
        assert n["critical"] == 1 and n["status"] == "pendiente"
        content = f"{n['subject'] or ''}\n{n['body']}"
        for sentinel in (NAME, PHONE, EMAIL):
            assert sentinel not in content
        assert "L-0001" in n["body"]
        assert ("L-0002" in n["body"]) == (n["recipient_user_id"] == users["cto"].id)
        assert "suprim" in n["body"].lower()
    assert accepted == 1


def test_vcrm154_no_lawyer_notice_when_no_lead_was_ever_accepted(
    bot: CrmBot, db: CrmDatabase, users: dict[str, User]
) -> None:
    _lead(db, users["com"].id, LeadState.PERDIDO)
    run(bot, _msg(CTO_TG, "/suprimir L-0001"))
    notices = _notices(db)
    assert [(n["recipient_user_id"], n["channel"]) for n in notices] == [
        (users["cto"].id, "telegram")
    ]


def test_vcrm155_failed_notice_raises_alert_per_lead_until_attended(
    bot: CrmBot,
    tg: FakeTelegram,
    db: CrmDatabase,
    users: dict[str, User],
    clock: FakeClock,
) -> None:
    a = _lead(db, users["com"].id, LeadState.PERDIDO)
    b = _lead(db, users["com"].id, LeadState.NUEVO, phone_e164="+573008888888")
    run(bot, _msg(CTO_TG, "/suprimir L-0001"))
    worker = OutboxWorker(db, tg, FakeEmailSender(), clock.now, on_failed=escalate)
    tg.fail_next(CTO_TG, 3)
    for _ in range(4):
        asyncio.run(worker.deliver_due())
        clock.advance(seconds=300)
    failed = _notices(db)[0]
    assert failed["status"] == "fallida"
    with db.read() as conn:
        alerts = repo.open_alerts(conn)
    assert [(x.kind, x.lead_id, x.outbox_id) for x in alerts] == [
        (AlertKind.SUPPRESSION_NOTICE_FAILED, a, failed["id"]),
        (AlertKind.SUPPRESSION_NOTICE_FAILED, b, failed["id"]),
    ]
    run(bot, _msg(CTO_TG, "/ver L-0001"))
    card = tg.sent[-1]
    assert "aviso de supresión fallido" in card.text
    assert "cto@k.co" in card.text and "telegram" in card.text
    assert card.buttons is not None
    data = card.buttons[-1][0].callback_data
    run(bot, _cb(CTO_TG, data))
    with db.read() as conn:
        assert [x.lead_id for x in repo.open_alerts(conn)] == [b]


# --- Fallo al borrar archivos (VCRM-073) -------------------------------------------------


class _FailingStore(LocalFileStore):
    def __init__(self, base_dir: Path, failing: set[str]) -> None:
        super().__init__(base_dir)
        self.failing = failing

    def delete(self, storage_key: str) -> None:
        if storage_key in self.failing:
            raise OSError("disco no disponible")
        super().delete(storage_key)


def test_vcrm073_file_delete_failure_marks_nothing(
    db: CrmDatabase, tg: FakeTelegram, tmp_path: Path, users: dict[str, User]
) -> None:
    store = _FailingStore(tmp_path / "files", set())
    bot = CrmBot(db, tg, FakeClock(START).now, fingerprint_keys=(KEY,), files=store)
    a = _lead(db, users["com"].id)
    b = _lead(db, users["com"].id, LeadState.PERDIDO)
    _attach(db, store, a, users["com"].id, b"uno")
    store.failing.add(_attach(db, store, b, users["com"].id, b"dos"))
    with db.tx() as tx:
        repo.insert_note(tx, lead_id=b, author_user_id=users["com"].id, body=NOTE, at=START)
    run(bot, _msg(CTO_TG, "/suprimir L-0001"))
    assert _suppressed_ids(db) == []
    assert _rows(db, "SELECT deleted_at FROM crm_attachments") == [
        {"deleted_at": None},
        {"deleted_at": None},
    ]
    assert len(_rows(db, "SELECT * FROM crm_notes")) == 1
    assert _notices(db) == []
    assert _rows(db, "SELECT * FROM crm_suppression") == []
    assert "No se pudo" in tg.sent[-1].text


def test_vcrm073_without_file_store_suppression_with_files_fails(
    db: CrmDatabase, tg: FakeTelegram, store: LocalFileStore, users: dict[str, User]
) -> None:
    bot = CrmBot(db, tg, FakeClock(START).now, fingerprint_keys=(KEY,))
    lead_id = _lead(db, users["com"].id)
    _attach(db, store, lead_id, users["com"].id, b"uno")
    run(bot, _msg(CTO_TG, "/suprimir L-0001"))
    assert _suppressed_ids(db) == []
    assert "No se pudo" in tg.sent[-1].text


# --- Plan puro (VCRM-164, 165) -----------------------------------------------------------


def test_vcrm165_plan_reduces_evidence_only_on_cto_order(
    db: CrmDatabase, store: LocalFileStore, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id, LeadState.GANADO)
    _attach(db, store, lead_id, users["com"].id, b"foto")
    _attach(db, store, lead_id, users["com"].id, b"firma", kind="authorization")
    with db.read() as conn:
        lead = repo.get_lead(conn, lead_id)
        attachments = repo.lead_attachments(conn, lead_id)
    assert lead is not None
    ordered = compliance.plan_suppression(lead, attachments, cause="orden_cto")
    assert [a.kind for a in ordered.files] == ["photo"]
    assert [a.kind for a in ordered.evidence_files] == ["authorization"]
    assert "name" in ordered.null_columns
    by_term = compliance.plan_suppression(
        lead, attachments, cause="final_state", keep_attachments_of_won=True
    )
    assert by_term.files == () and by_term.evidence_files == ()
    kept = compliance.plan_suppression(
        lead, attachments, cause="orden_cto", keep_fields=frozenset({"name"})
    )
    assert "name" not in kept.null_columns and "email" in kept.null_columns
