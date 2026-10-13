"""Tests de la retractación confirmada y la actualización del handoff (T17).

Requisitos: VCRM-084, 113, 114, 131, 156.
"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from crm_support import FakeClock, FakeEmailSender, FakeTelegram
from jerico.crm import repo
from jerico.crm.bot import ALREADY_PROCESSED, INVALID_BUTTON, CrmBot
from jerico.crm.db import CrmDatabase
from jerico.crm.handoff import LABEL_SERVICE, LABEL_TERM, LABEL_VALUE
from jerico.crm.model import LeadState, OutboxItem, Role, User
from jerico.crm.outbox import OutboxWorker
from jerico.crm.parsing import build_callback
from jerico.crm.ports import Update
from jerico.crm.timeutil import format_local, to_iso

START = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
NOW = START + timedelta(days=1)
CTO_TG, COM_TG, COM2_TG, LAW_TG = 1000, 2000, 2100, 3000
TG = {"cto": CTO_TG, "com": COM_TG, "com2": COM2_TG, "law": LAW_TG}
S = LeadState
NOTE = "Nota secreta del cliente"
COMPLETE: dict[str, Any] = {
    "client_type": "persona natural",
    "doc_type": "cédula de ciudadanía",
    "doc_number": "1020304050",
    "phone_e164": "+573001112233",
    "email": "ana@cliente.co",
    "service": "Desarrollo de chatbot",
    "agreed_value": "12.000.000 COP",
    "start_term": "01/04/2026",
}


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
def worker(db: CrmDatabase, tg: FakeTelegram, mail: FakeEmailSender) -> OutboxWorker:
    return OutboxWorker(db, tg, mail, FakeClock(NOW).now, interval_s=3600)


@pytest.fixture
def bot(db: CrmDatabase, tg: FakeTelegram, worker: OutboxWorker) -> CrmBot:
    return CrmBot(db, tg, FakeClock(NOW).now, kick=worker.kick)


@pytest.fixture
def users(db: CrmDatabase) -> dict[str, User]:
    roles = {"cto": Role.CTO, "com": Role.COMMERCIAL, "com2": Role.COMMERCIAL, "law": Role.LAWYER}
    with db.tx() as tx:
        return {
            k: repo.insert_user(tx, telegram_id=TG[k], role=r, email=f"{k}@k.co", now=START)
            for k, r in roles.items()
        }


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


def _lead(db: CrmDatabase, owner: User, state: LeadState = S.ACCEPTED, **changes: Any) -> int:
    fields = {**COMPLETE, "ever_accepted": 1 if state == S.ACCEPTED else 0, **changes}
    with db.tx() as tx:
        lead_id = repo.insert_lead(
            tx, assigned_user_id=owner.id, state=state, now=START, fields={"name": "Ana Pérez"}
        )
        repo.update_lead(tx, lead_id, fields, now=START)
        repo.insert_note(tx, lead_id=lead_id, author_user_id=owner.id, body=NOTE, at=START)
    return lead_id


def _get(db: CrmDatabase, lead_id: int) -> Any:
    with db.read() as conn:
        return repo.get_lead(conn, lead_id)


def _outbox(db: CrmDatabase) -> list[OutboxItem]:
    with db.read() as conn:
        rows = conn.execute("SELECT * FROM crm_outbox WHERE critical = 1 ORDER BY id").fetchall()
    return [OutboxItem(**dict(r)) for r in rows]


def _by_target(db: CrmDatabase, users: dict[str, User]) -> dict[tuple[str, str], OutboxItem]:
    names = {u.id: k for k, u in users.items()}
    return {(names[i.recipient_user_id], i.channel): i for i in _outbox(db)}


def _labels(tg: FakeTelegram) -> list[str]:
    return [b.text for row in tg.sent[-1].buttons or [] for b in row]


def _data(tg: FakeTelegram, label: str) -> str:
    for row in tg.sent[-1].buttons or []:
        for b in row:
            if b.text == label:
                return b.callback_data
    raise AssertionError(f"sin botón {label}")


def _ask_confirmation(bot: CrmBot, tg: FakeTelegram, who: str, lead_id: int, reason: str) -> None:
    run(bot, _msg(TG[who], f"/retractar L-{lead_id}"))
    run(bot, _cb(TG[who], _data(tg, reason)))


def _retract(bot: CrmBot, tg: FakeTelegram, who: str, lead_id: int) -> None:
    _ask_confirmation(bot, tg, who, lead_id, "Precio o presupuesto")
    run(bot, _cb(TG[who], _data(tg, "✅")))


# --- Solicitud y motivo (VCRM-131, 114) -----------------------------------------------------


def test_vcrm131_request_asks_reason_by_buttons_without_transition(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    run(bot, _msg(COM_TG, f"/retractar L-{lead_id}"))
    assert f"L-{lead_id:04d}" in tg.sent[-1].text
    assert "Otro" in _labels(tg) and "Precio o presupuesto" in _labels(tg)
    assert _get(db, lead_id).state == S.ACCEPTED
    assert _outbox(db) == []


@pytest.mark.parametrize("text", ["/retractar", "/retractar 42", "/retractar L-0"])
def test_vcrm131_bad_command_shows_example(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User], text: str
) -> None:
    run(bot, _msg(COM_TG, text))
    assert "/retractar L-0042" in tg.sent[-1].text


def test_vcrm131_missing_lead(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    run(bot, _msg(COM_TG, "/retractar L-0099"))
    assert "no existe" in tg.sent[-1].text


@pytest.mark.parametrize("who", ["com", "cto", "law"])
def test_vcrm131_confirmation_shows_id_name_and_reason(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User], who: str
) -> None:
    lead_id = _lead(db, users["com"])
    _ask_confirmation(bot, tg, who, lead_id, "Ya tiene proveedor")
    ask = tg.sent[-1]
    assert ask.chat_id == TG[who]
    assert f"L-{lead_id:04d}" in ask.text and "Ana Pérez" in ask.text
    assert "Ya tiene proveedor" in ask.text
    assert _labels(tg) == ["✅", "❌"]
    assert _get(db, lead_id).state == S.ACCEPTED
    assert _outbox(db) == []


def test_vcrm131_other_commercial_has_no_access(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    run(bot, _msg(COM2_TG, f"/retractar L-{lead_id}"))
    assert "no tiene acceso" in tg.sent[-1].text
    assert _get(db, lead_id).state == S.ACCEPTED


@pytest.mark.parametrize("state", [S.CONTACTED, S.REJECTED, S.WON])
def test_vcrm131_only_accepted_leads(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User], state: LeadState
) -> None:
    lead_id = _lead(db, users["com"], state)
    run(bot, _msg(CTO_TG, f"/retractar L-{lead_id}"))
    assert "solo un lead «aceptado»" in tg.sent[-1].text
    assert _get(db, lead_id).state == state


def test_vcrm114_invalid_reason_button_does_nothing(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    run(bot, _cb(COM_TG, build_callback("rmotivo", str(lead_id), "inventado")))
    assert tg.sent[-1].text == INVALID_BUTTON
    assert _get(db, lead_id).state == S.ACCEPTED
    assert _outbox(db) == []


@pytest.mark.parametrize("answer", ["   ", "/lista"])
def test_vcrm114_other_without_text_stays_accepted(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User], answer: str
) -> None:
    lead_id = _lead(db, users["com"])
    _ask_confirmation(bot, tg, "com", lead_id, "Otro")
    assert "Escriba el motivo de la retractación" in tg.sent[-1].text
    run(bot, _msg(COM_TG, answer))
    lead = _get(db, lead_id)
    assert (lead.state, lead.rejection_is_retraction) == (S.ACCEPTED, 0)
    assert _outbox(db) == []
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM crm_confirmations").fetchone()[0] == 0


def test_vcrm114_other_with_text_asks_confirmation(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    _ask_confirmation(bot, tg, "com", lead_id, "Otro")
    run(bot, _msg(COM_TG, "El cliente desistió por viaje"))
    assert "El cliente desistió por viaje" in tg.sent[-1].text
    assert _labels(tg) == ["✅", "❌"]


# --- Confirmación ✅/❌ (VCRM-131, 113, 156) --------------------------------------------------


def test_vcrm131_cancel_keeps_accepted_without_notifications(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    _ask_confirmation(bot, tg, "com", lead_id, "Precio o presupuesto")
    run(bot, _cb(COM_TG, _data(tg, "❌")))
    lead = _get(db, lead_id)
    assert (lead.state, lead.rejection_is_retraction, lead.accepted_exit_at) == (
        S.ACCEPTED,
        0,
        None,
    )
    assert "No se aplicó la retractación" in tg.sent[-1].text
    assert _outbox(db) == []


@pytest.mark.parametrize("who", ["com", "cto", "law"])
def test_vcrm113_confirm_rejects_as_retraction_and_enqueues_three(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User], who: str
) -> None:
    lead_id = _lead(db, users["com"])
    _retract(bot, tg, who, lead_id)
    lead = _get(db, lead_id)
    assert (lead.state, lead.rejection_is_retraction, lead.reject_reason) == (
        S.REJECTED,
        1,
        "precio",
    )
    assert lead.accepted_exit_at == to_iso(NOW)
    with db.read() as conn:
        last = repo.lead_events(conn, lead_id)[-1]
    assert (last.old_value, last.new_value, last.reason, last.actor_user_id) == (
        S.ACCEPTED,
        S.REJECTED,
        "precio",
        users[who].id,
    )
    targets = _by_target(db, users)
    assert set(targets) == {("cto", "telegram"), ("law", "telegram"), ("law", "email")}
    for (name, channel), item in targets.items():
        assert item.kind == "retractacion" and item.status == "pending"
        assert item.idempotency_key == (f"retract:{lead_id}:{last.id}:{channel}:{users[name].id}")
        body = item.body or ""
        assert f"L-{lead_id:04d}" in body and "Ana Pérez" in body
        assert "Precio o presupuesto" in body and f"{who}@k.co" in body
        assert format_local(NOW) in body
        assert NOTE not in body  # VCRM-156
    assert targets[("law", "email")].subject
    assert "retractación" in tg.sent[-1].text


def test_vcrm113_other_text_in_notifications_and_delivery(
    db: CrmDatabase,
    tg: FakeTelegram,
    mail: FakeEmailSender,
    bot: CrmBot,
    worker: OutboxWorker,
    users: dict[str, User],
) -> None:
    lead_id = _lead(db, users["com"])
    _ask_confirmation(bot, tg, "law", lead_id, "Otro")
    run(bot, _msg(LAW_TG, "Desistió"))
    run(bot, _cb(LAW_TG, _data(tg, "✅")))
    assert _get(db, lead_id).reject_text == "Desistió"
    asyncio.run(worker.deliver_due())
    assert {i.status for i in _outbox(db)} == {"delivered"}
    assert any("Desistió" in s.text and s.chat_id == CTO_TG for s in tg.sent)
    assert [m.to for m in mail.sent] == ["law@k.co"] and "Desistió" in mail.sent[0].body


def test_vcrm131_repeated_yes_does_not_duplicate(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    _ask_confirmation(bot, tg, "com", lead_id, "Precio o presupuesto")
    yes = _data(tg, "✅")
    run(bot, _cb(COM_TG, yes))
    run(bot, _cb(COM_TG, yes))
    assert tg.sent[-1].text == ALREADY_PROCESSED
    assert len(_outbox(db)) == 3


def test_vcrm131_confirm_after_state_changed_does_nothing(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    _ask_confirmation(bot, tg, "com", lead_id, "Precio o presupuesto")
    first = _data(tg, "✅")
    _ask_confirmation(bot, tg, "cto", lead_id, "No interesado")
    run(bot, _cb(CTO_TG, _data(tg, "✅")))
    run(bot, _cb(COM_TG, first))
    assert "no está «aceptado»" in tg.sent[-1].text
    assert len(_outbox(db)) == 3
    assert _get(db, lead_id).reject_reason == "no_interesado"


# --- Actualización del handoff (VCRM-084, 156) -----------------------------------------------


def test_vcrm084_completing_missing_field_notifies_cto_and_lawyer(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], service=None, agreed_value=None)
    run(bot, _msg(COM_TG, f"/editar L-{lead_id}; servicio; Chatbot de ventas"))
    targets = _by_target(db, users)
    assert set(targets) == {("cto", "telegram"), ("law", "telegram"), ("law", "email")}
    with db.read() as conn:
        last = repo.lead_events(conn, lead_id)[-1]
    for (name, channel), item in targets.items():
        assert item.kind == "handoff"
        assert item.idempotency_key == f"handoff:{lead_id}:{last.id}:{channel}:{users[name].id}"
        body = item.body or ""
        assert f"L-{lead_id:04d}" in body and LABEL_SERVICE in body
        assert "Chatbot de ventas" in body
        assert f"Faltantes: {LABEL_VALUE}" in body
        assert NOTE not in body  # VCRM-156
    assert "Se notificó al CTO y al abogado" in tg.sent[-1].text


def test_vcrm084_last_missing_field_reports_none_left(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], start_term=None)
    run(bot, _msg(CTO_TG, f"/editar L-{lead_id}; plazo; 15/04/2026"))
    bodies = [i.body or "" for i in _outbox(db)]
    assert len(bodies) == 3
    assert all(LABEL_TERM in b and "Faltantes: ninguno" in b for b in bodies)


def test_vcrm084_editing_non_missing_field_does_not_notify(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], service=None)
    run(bot, _msg(COM_TG, f"/editar L-{lead_id}; valor; 15.000.000 COP"))
    assert _get(db, lead_id).agreed_value == "15.000.000 COP"
    assert _outbox(db) == []
    assert "Se notificó" not in tg.sent[-1].text


def test_vcrm084_not_accepted_lead_does_not_notify(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], S.CONTACTED, service=None)
    run(bot, _msg(COM_TG, f"/editar L-{lead_id}; servicio; Chatbot"))
    assert _get(db, lead_id).service == "Chatbot"
    assert _outbox(db) == []


def test_vcrm084_field_still_missing_does_not_notify(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], client_type=None)
    run(bot, _msg(COM_TG, f"/editar L-{lead_id}; representante; Luis Gómez"))
    assert _get(db, lead_id).legal_rep == "Luis Gómez"
    assert _outbox(db) == []


# --- Botón «Retractar» en la ficha (VCRM-163, decisión K-2) ----------------------------------

RETRACT_LABEL = "Retractar"


@pytest.mark.parametrize("who", ["com", "cto", "law"])
def test_vcrm163_card_shows_retract_button_to_allowed_users(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User], who: str
) -> None:
    lead_id = _lead(db, users["com"])
    run(bot, _msg(TG[who], f"/ver L-{lead_id}"))
    assert RETRACT_LABEL in _labels(tg)
    data = _data(tg, RETRACT_LABEL)
    assert data == build_callback("retractar", str(lead_id))
    assert len(data.encode("utf-8")) <= 64


@pytest.mark.parametrize("state", [S.NEW, S.CONTACTED, S.REJECTED, S.WON, S.LOST])
def test_vcrm163_no_retract_button_outside_accepted(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User], state: LeadState
) -> None:
    lead_id = _lead(db, users["com"], state)
    for who in ("com", "cto", "law"):
        run(bot, _msg(TG[who], f"/ver L-{lead_id}"))
        assert RETRACT_LABEL not in _labels(tg)


def test_vcrm163_button_starts_same_flow_as_command(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    run(bot, _cb(COM_TG, build_callback("retractar", str(lead_id))))
    assert "motivo de la retractación" in tg.sent[-1].text
    assert "Otro" in _labels(tg) and "Precio o presupuesto" in _labels(tg)
    assert _get(db, lead_id).state == S.ACCEPTED
    run(bot, _cb(COM_TG, _data(tg, "Momento no oportuno")))
    assert _labels(tg) == ["✅", "❌"]
    assert _outbox(db) == []
    run(bot, _cb(COM_TG, _data(tg, "✅")))
    lead = _get(db, lead_id)
    assert (lead.state, lead.rejection_is_retraction) == (S.REJECTED, 1)
    assert len(_outbox(db)) == 3


def test_vcrm163_stale_button_is_rejected_with_reason(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    run(bot, _msg(COM_TG, f"/ver L-{lead_id}"))
    stale = _data(tg, RETRACT_LABEL)
    with db.tx() as tx:
        repo.update_lead(tx, lead_id, {"state": S.WON.value}, now=NOW)
    run(bot, _cb(COM_TG, stale))
    assert "solo un lead «aceptado»" in tg.sent[-1].text
    assert _get(db, lead_id).state == S.WON
    assert _outbox(db) == []


def test_vcrm163_foreign_commercial_has_no_button_and_press_is_rejected(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    run(bot, _msg(COM2_TG, f"/ver L-{lead_id}"))
    assert RETRACT_LABEL not in _labels(tg)
    run(bot, _cb(COM2_TG, build_callback("retractar", str(lead_id))))
    assert "no tiene acceso" in tg.sent[-1].text
    assert _get(db, lead_id).state == S.ACCEPTED
    assert _outbox(db) == []


@pytest.mark.parametrize("args", [("x",), ("1", "2")])
def test_vcrm163_malformed_retract_button_is_invalid(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User], args: tuple[str, ...]
) -> None:
    lead_id = _lead(db, users["com"])
    run(bot, _cb(COM_TG, build_callback("retractar", *args)))
    assert tg.sent[-1].text == INVALID_BUTTON
    assert _get(db, lead_id).state == S.ACCEPTED


def test_leads_confirm_retract_lead_inexistente(db: CrmDatabase, users: dict[str, User]) -> None:
    from jerico.crm import leads
    from jerico.crm.model import Confirmation

    conf = Confirmation(
        id=1,
        kind="retract",
        lead_id=999999,
        user_id=users["com"].id,
        reason="precio",
        reason_text=None,
        status="pending",
        created_at=to_iso(NOW),
        resolved_at=None,
    )
    with db.tx() as tx:
        out = leads.confirm_retract(tx, users["com"], conf, yes=True, now=NOW)
    assert len(out) == 1
    assert "no existe" in out[0].text


def test_leads_confirm_retract_comercial_ajeno_denegado(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    from jerico.crm import leads
    from jerico.crm.model import Confirmation

    lead_id = _lead(db, users["com"])
    conf = Confirmation(
        id=2,
        kind="retract",
        lead_id=lead_id,
        user_id=users["com2"].id,
        reason="precio",
        reason_text=None,
        status="pending",
        created_at=to_iso(NOW),
        resolved_at=None,
    )
    with db.tx() as tx:
        out = leads.confirm_retract(tx, users["com2"], conf, yes=True, now=NOW)
    assert len(out) == 1
    assert "no tiene acceso" in out[0].text


def test_leads_confirm_retract_con_f2_activa_arranca_cadencia(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    from jerico.crm import leads
    from jerico.crm.model import AuthStatus, Confirmation

    lead_id = _lead(db, users["com"], auth_status=AuthStatus.AUTHORIZED.value)
    with db.tx() as tx:
        repo.insert_consent(
            tx,
            lead_id=lead_id,
            status=AuthStatus.AUTHORIZED,
            medium="documento",
            at=START,
            actor_user_id=users["com"].id,
        )
        repo.set_meta(tx, "f2_activated_at", to_iso(NOW))
    conf = Confirmation(
        id=3,
        kind="retract",
        lead_id=lead_id,
        user_id=users["com"].id,
        reason="precio",
        reason_text=None,
        status="pending",
        created_at=to_iso(NOW),
        resolved_at=None,
    )
    with db.tx() as tx:
        out = leads.confirm_retract(tx, users["com"], conf, yes=True, now=NOW)
    assert out
    with db.read() as conn:
        cad = repo.get_cadence(conn, lead_id)
        assert cad is not None and cad.status == "active"
