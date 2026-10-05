"""Tests de usuarios autorizados (VCRM-125, 126, 144, 091, 092, 093)."""

import logging
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crm_support import make_settings
from jerico.crm import repo
from jerico.crm.db import CrmDatabase
from jerico.crm.model import AuditAction, AuditOutcome, EventKind, LeadState, Outgoing, Role, User
from jerico.crm.parsing import build_callback
from jerico.crm.render import short_id
from jerico.crm.team import (
    add_user,
    assignee_label,
    deactivate_user,
    orphan_leads_message,
    reassign,
    reassign_command,
    reassign_keyboard,
    seed_cto,
)

NOW = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
CTO_TG = 1000
COM_TG = 2000
COM2_TG = 2100
LAW_TG = 3000


@pytest.fixture
def db(tmp_path: Path) -> Iterator[CrmDatabase]:
    database = CrmDatabase(tmp_path / "crm.db")
    yield database
    database.close()


@pytest.fixture
def conn(db: CrmDatabase) -> sqlite3.Connection:
    with db.tx() as tx:
        return tx


def _cto(conn: sqlite3.Connection) -> User:
    return repo.insert_user(conn, telegram_id=CTO_TG, role=Role.CTO, email="cto@k.co", now=NOW)


def _com(conn: sqlite3.Connection, tg: int = COM_TG) -> User:
    return repo.insert_user(
        conn, telegram_id=tg, role=Role.COMMERCIAL, email=f"c{tg}@k.co", now=NOW
    )


def _lead(conn: sqlite3.Connection, user_id: int | None, state: LeadState = LeadState.NUEVO) -> int:
    return repo.insert_lead(conn, assigned_user_id=user_id, state=state, now=NOW, fields={})


def _audits(conn: sqlite3.Connection, action: AuditAction) -> list[dict[str, object]]:
    return [r for r in repo.audit_rows(conn) if r["action"] == action.value]


# --- Siembra del CTO (VCRM-125, VCRM-126) -------------------------------------------------


def test_vcrm125_seed_cto_when_no_active_cto_and_persists_after_reopen(tmp_path: Path) -> None:
    settings = make_settings(seed_cto_telegram_id=str(CTO_TG), seed_cto_email="CTO@K.co")
    first = CrmDatabase(tmp_path / "crm.db")
    with first.tx() as tx:
        user = seed_cto(tx, settings, NOW)
    first.close()
    assert user is not None and user.role == Role.CTO and user.email == "cto@k.co"

    other = make_settings(seed_cto_telegram_id="999", seed_cto_email="otro@k.co")
    second = CrmDatabase(tmp_path / "crm.db")
    with second.tx() as tx:
        assert seed_cto(tx, other, NOW) is None
        ctos = repo.active_users(tx, Role.CTO)
    second.close()
    assert [(u.telegram_id, u.email) for u in ctos] == [(CTO_TG, "cto@k.co")]


@pytest.mark.parametrize(
    ("tg", "email", "names"),
    [
        ("", "", ["JERICO_CRM_SEED_CTO_TELEGRAM_ID", "JERICO_CRM_SEED_CTO_EMAIL"]),
        ("abc", "cto@k.co", ["JERICO_CRM_SEED_CTO_TELEGRAM_ID"]),
        ("1000", "sin-arroba", ["JERICO_CRM_SEED_CTO_EMAIL"]),
    ],
)
def test_vcrm126_seed_invalid_does_not_seed_and_logs_names_only(
    conn: sqlite3.Connection,
    caplog: pytest.LogCaptureFixture,
    tg: str,
    email: str,
    names: list[str],
) -> None:
    caplog.set_level(logging.WARNING, logger="jerico.crm.team")
    settings = make_settings(seed_cto_telegram_id=tg, seed_cto_email=email)
    assert seed_cto(conn, settings, NOW) is None
    assert repo.active_users(conn) == []
    for name in names:
        assert name in caplog.text
    for value in (tg, email):
        if value:
            assert value not in caplog.text


def test_vcrm126_seed_repeated_telegram_id_does_not_seed(
    conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="jerico.crm.team")
    _com(conn, tg=CTO_TG)
    settings = make_settings(seed_cto_telegram_id=str(CTO_TG), seed_cto_email="cto@k.co")
    assert seed_cto(conn, settings, NOW) is None
    assert repo.active_users(conn, Role.CTO) == []
    assert "JERICO_CRM_SEED_CTO_TELEGRAM_ID" in caplog.text
    assert str(CTO_TG) not in caplog.text and "cto@k.co" not in caplog.text


# --- Alta por el bot (VCRM-144, VCRM-126) -------------------------------------------------


@pytest.mark.parametrize(
    ("word", "role"), [("comercial", Role.COMMERCIAL), ("abogado", Role.LAWYER)]
)
def test_vcrm144_cto_adds_user_with_immediate_access_confirmation_and_audit(
    conn: sqlite3.Connection, word: str, role: Role
) -> None:
    cto = _cto(conn)
    out = add_user(conn, cto, f"/alta {word}; {COM_TG}; Nuevo@K.co", NOW)
    added = repo.active_user_by_telegram(conn, COM_TG)
    assert added is not None and added.role == role and added.email == "nuevo@k.co"
    assert len(out) == 1 and out[0].chat_id == CTO_TG and "alta" in out[0].text.lower()
    rows = _audits(conn, AuditAction.USER_ADDED)
    assert len(rows) == 1
    assert rows[0]["actor"] == f"user:{cto.id}" and rows[0]["outcome"] == AuditOutcome.OK.value


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("/alta", "rol"),
        ("/alta comercial", "identificador de Telegram"),
        (f"/alta comercial; {COM_TG}", "correo"),
        (f"/alta cto; {COM_TG}; a@k.co", "rol"),
        ("/alta comercial; abc; a@k.co", "identificador de Telegram"),
        (f"/alta comercial; {COM_TG}; sin-arroba", "correo"),
        (f"/alta abogado; {CTO_TG}; a@k.co", "ya pertenece"),
    ],
)
def test_vcrm126_invalid_add_reports_missing_invalid_or_repeated(
    conn: sqlite3.Connection, text: str, fragment: str
) -> None:
    cto = _cto(conn)
    out = add_user(conn, cto, text, NOW)
    assert len(out) == 1 and fragment in out[0].text
    assert [u.telegram_id for u in repo.active_users(conn)] == [CTO_TG]
    assert _audits(conn, AuditAction.USER_ADDED) == []


def test_vcrm144_non_cto_cannot_add_user(conn: sqlite3.Connection) -> None:
    com = _com(conn)
    out = add_user(conn, com, f"/alta comercial; {COM2_TG}; a@k.co", NOW)
    assert "no tiene permiso" in out[0].text.lower() and out[0].chat_id == COM_TG
    assert repo.active_user_by_telegram(conn, COM2_TG) is None
    rows = _audits(conn, AuditAction.PERMISSION_DENIED)
    assert rows and rows[0]["outcome"] == AuditOutcome.DENIED.value


# --- Baja (VCRM-091, VCRM-092) ------------------------------------------------------------


def test_vcrm091_deactivate_commercial_lists_leads_with_reassign_buttons(
    conn: sqlite3.Connection,
) -> None:
    cto = _cto(conn)
    com = _com(conn)
    open_lead = _lead(conn, com.id, LeadState.CONTACTADO)
    lost = _lead(conn, com.id, LeadState.PERDIDO)
    _lead(conn, com.id, LeadState.BAJA)
    out = deactivate_user(conn, cto, f"/baja_usuario {COM_TG}", NOW)
    assert repo.active_user_by_telegram(conn, COM_TG) is None
    assert len(_audits(conn, AuditAction.USER_DEACTIVATED)) == 1
    callbacks = [cb for msg in out for row in msg.buttons for _, cb in row]
    assert build_callback("reasignar", str(open_lead)) in callbacks
    assert build_callback("reasignar", str(lost)) in callbacks
    assert len([cb for cb in callbacks if cb.startswith("v1:reasignar:")]) == 2
    assert all(msg.chat_id == CTO_TG for msg in out)


def test_vcrm091_orphan_leads_are_paginated(conn: sqlite3.Connection) -> None:
    _cto(conn)
    com = _com(conn)
    for _ in range(12):
        _lead(conn, com.id)
    first = orphan_leads_message(conn, CTO_TG, com.id, 1)
    second = orphan_leads_message(conn, CTO_TG, com.id, 2)
    assert "página 1 de 2" in first.text and "página 2 de 2" in second.text
    nav = [cb for row in first.buttons for _, cb in row]
    assert build_callback("baja_leads", str(com.id), "2") in nav
    assert len([cb for cb in nav if cb.startswith("v1:reasignar:")]) == 10


def test_vcrm091_deactivate_lawyer(conn: sqlite3.Connection) -> None:
    cto = _cto(conn)
    repo.insert_user(conn, telegram_id=LAW_TG, role=Role.LAWYER, email="l@k.co", now=NOW)
    out = deactivate_user(conn, cto, f"/baja_usuario {LAW_TG}", NOW)
    assert repo.active_user_by_telegram(conn, LAW_TG) is None
    assert len(out) == 1 and out[0].buttons == ()
    assert len(_audits(conn, AuditAction.USER_DEACTIVATED)) == 1


def test_vcrm091_cto_cannot_be_deactivated(conn: sqlite3.Connection) -> None:
    cto = _cto(conn)
    out = deactivate_user(conn, cto, f"/baja_usuario {CTO_TG}", NOW)
    assert "CTO" in out[0].text
    assert repo.active_user_by_telegram(conn, CTO_TG) is not None
    assert _audits(conn, AuditAction.USER_DEACTIVATED) == []


@pytest.mark.parametrize("text", ["/baja_usuario", "/baja_usuario abc", "/baja_usuario 4242"])
def test_vcrm091_deactivate_unknown_or_invalid_identifier(
    conn: sqlite3.Connection, text: str
) -> None:
    cto = _cto(conn)
    out = deactivate_user(conn, cto, text, NOW)
    assert len(out) == 1 and "identificador de Telegram" in out[0].text
    assert _audits(conn, AuditAction.USER_DEACTIVATED) == []


def test_vcrm091_non_cto_cannot_deactivate(conn: sqlite3.Connection) -> None:
    _cto(conn)
    com = _com(conn)
    out = deactivate_user(conn, com, f"/baja_usuario {CTO_TG}", NOW)
    assert "no tiene permiso" in out[0].text.lower()
    assert repo.active_user_by_telegram(conn, CTO_TG) is not None


def test_vcrm092_lead_of_inactive_commercial_shows_unassigned(conn: sqlite3.Connection) -> None:
    cto = _cto(conn)
    com = _com(conn)
    assert assignee_label(com) == f"comercial {com.email}"
    assert assignee_label(cto) == "del CTO"
    assert assignee_label(None) == "sin comercial asignado"
    deactivate_user(conn, cto, f"/baja_usuario {COM_TG}", NOW)
    assert assignee_label(repo.get_user(conn, com.id)) == "sin comercial asignado"


# --- Reasignación (VCRM-093) ---------------------------------------------------------------


def test_vcrm093_reassign_records_event_with_previous_new_author_and_date(
    conn: sqlite3.Connection,
) -> None:
    cto = _cto(conn)
    com = _com(conn)
    com2 = _com(conn, tg=COM2_TG)
    lead_id = _lead(conn, com.id)
    later = datetime(2026, 3, 3, 9, 30, tzinfo=UTC)
    out = reassign(conn, cto, lead_id, com2.id, later)
    lead = repo.get_lead(conn, lead_id)
    assert lead is not None and lead.assigned_user_id == com2.id
    assert lead.last_interaction_at == "2026-03-02T15:00:00Z"
    events = [e for e in repo.lead_events(conn, lead_id) if e.kind == EventKind.REASSIGN.value]
    assert len(events) == 1
    event = events[0]
    assert (event.old_value, event.new_value) == (str(com.id), str(com2.id))
    assert event.actor_user_id == cto.id and event.at == "2026-03-03T09:30:00Z"
    assert out[0].chat_id == CTO_TG and "L-" in out[0].text


def test_vcrm093_reassign_to_cto_by_command(conn: sqlite3.Connection) -> None:
    cto = _cto(conn)
    com = _com(conn)
    lead_id = _lead(conn, com.id)
    reassign_command(conn, cto, f"/reasignar L-{lead_id}; cto", NOW)
    lead = repo.get_lead(conn, lead_id)
    assert lead is not None and lead.assigned_user_id == cto.id


def test_vcrm093_reassign_by_command_to_commercial(conn: sqlite3.Connection) -> None:
    cto = _cto(conn)
    _com(conn)
    com2 = _com(conn, tg=COM2_TG)
    lead_id = _lead(conn, None)
    reassign_command(conn, cto, f"/reasignar L-{lead_id}; {COM2_TG}", NOW)
    lead = repo.get_lead(conn, lead_id)
    assert lead is not None and lead.assigned_user_id == com2.id
    events = repo.lead_events(conn, lead_id)
    assert events[0].old_value is None and events[0].new_value == str(com2.id)


@pytest.mark.parametrize(
    "text",
    ["/reasignar", "/reasignar L-x; cto", "/reasignar L-999; cto", "/reasignar L-{lead}; 4242"],
)
def test_vcrm093_reassign_command_invalid(conn: sqlite3.Connection, text: str) -> None:
    cto = _cto(conn)
    com = _com(conn)
    lead_id = _lead(conn, com.id)
    out = reassign_command(conn, cto, text.format(lead=lead_id), NOW)
    assert len(out) == 1 and out[0].chat_id == CTO_TG
    assert repo.lead_events(conn, lead_id) == []


def test_vcrm093_reassign_rejects_inactive_or_lawyer_target(conn: sqlite3.Connection) -> None:
    cto = _cto(conn)
    com = _com(conn)
    law = repo.insert_user(conn, telegram_id=LAW_TG, role=Role.LAWYER, email="l@k.co", now=NOW)
    lead_id = _lead(conn, cto.id)
    repo.deactivate_user(conn, com.id, now=NOW)
    for target in (com.id, law.id, 9999):
        out = reassign(conn, cto, lead_id, target, NOW)
        assert len(out) == 1 and "destino" in out[0].text
    assert repo.lead_events(conn, lead_id) == []


def test_vcrm093_non_cto_cannot_reassign(conn: sqlite3.Connection) -> None:
    _cto(conn)
    com = _com(conn)
    lead_id = _lead(conn, com.id)
    out = reassign(conn, com, lead_id, com.id, NOW)
    assert "no tiene permiso" in out[0].text.lower()
    assert reassign_keyboard(conn, com, lead_id, NOW)[0].text == out[0].text
    assert reassign_command(conn, com, f"/reasignar L-{lead_id}; cto", NOW)[0].text == out[0].text
    assert repo.lead_events(conn, lead_id) == []


def test_vcrm091_reassign_keyboard_lists_active_commercials_and_cto(
    conn: sqlite3.Connection,
) -> None:
    cto = _cto(conn)
    com = _com(conn)
    com2 = _com(conn, tg=COM2_TG)
    repo.insert_user(conn, telegram_id=LAW_TG, role=Role.LAWYER, email="l@k.co", now=NOW)
    lead_id = _lead(conn, com.id)
    repo.deactivate_user(conn, com.id, now=NOW)
    out = reassign_keyboard(conn, cto, lead_id, NOW)
    callbacks = [cb for row in out[0].buttons for _, cb in row]
    assert callbacks == [
        build_callback("reasignar", str(lead_id), str(cto.id)),
        build_callback("reasignar", str(lead_id), str(com2.id)),
    ]
    assert "sin comercial asignado" in out[0].text


def test_vcrm093_reassign_keyboard_unknown_lead(conn: sqlite3.Connection) -> None:
    cto = _cto(conn)
    out = reassign_keyboard(conn, cto, 999, NOW)
    assert out[0].buttons == () and short_id(999) in out[0].text


def test_outgoing_defaults_without_buttons() -> None:
    assert Outgoing(chat_id=1, text="x").buttons == ()
