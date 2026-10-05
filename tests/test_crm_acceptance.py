"""Tests de la aceptación con confirmación ✅/❌ y handoff (T16).

Requisitos: VCRM-046, 047, 048, 051, 052, 104, 111, 156.
"""

import asyncio
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from crm_support import FakeClock, FakeEmailSender, FakeTelegram
from jerico.crm import leads, repo
from jerico.crm.bot import ALREADY_PROCESSED, INVALID_BUTTON, CrmBot
from jerico.crm.db import CrmDatabase
from jerico.crm.handoff import LABEL_DOC, LABEL_VALUE, REP_IF_COMPANY
from jerico.crm.model import LeadState, OutboxItem, Role, User
from jerico.crm.outbox import OutboxWorker
from jerico.crm.parsing import build_callback
from jerico.crm.ports import Update
from jerico.crm.timeutil import format_local, to_iso

START = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
NOW = START + timedelta(days=1)
CTO_TG = 1000
COM_TG = 2000
COM2_TG = 2100
LAW_TG = 3000
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
def clock() -> FakeClock:
    return FakeClock(NOW)


@pytest.fixture
def worker(db: CrmDatabase, tg: FakeTelegram, mail: FakeEmailSender, clock: FakeClock) -> Any:
    return OutboxWorker(db, tg, mail, clock.now, interval_s=3600)


@pytest.fixture
def bot(db: CrmDatabase, tg: FakeTelegram, clock: FakeClock, worker: OutboxWorker) -> CrmBot:
    return CrmBot(db, tg, clock.now, kick=worker.kick)


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


def _lead(db: CrmDatabase, owner: User, state: LeadState = S.CONTACTADO, **changes: Any) -> int:
    with db.tx() as tx:
        lead_id = repo.insert_lead(
            tx, assigned_user_id=owner.id, state=state, now=START, fields={"name": "Ana Pérez"}
        )
        if changes:
            repo.update_lead(tx, lead_id, changes, now=START)
        repo.insert_note(tx, lead_id=lead_id, author_user_id=owner.id, body=NOTE, at=START)
    return lead_id


def _get(db: CrmDatabase, lead_id: int) -> Any:
    with db.read() as conn:
        return repo.get_lead(conn, lead_id)


def _outbox(db: CrmDatabase) -> list[OutboxItem]:
    with db.read() as conn:
        rows = conn.execute("SELECT * FROM crm_outbox WHERE critical = 1 ORDER BY id").fetchall()
    return [OutboxItem(**dict(r)) for r in rows]


def _sent_data(tg: FakeTelegram, label: str) -> str:
    for row in tg.sent[-1].buttons or []:
        for b in row:
            if b.text == label:
                return b.callback_data
    raise AssertionError(f"sin botón {label}")


def _request(db: CrmDatabase, actor: User, lead_id: int) -> list[Any]:
    with db.tx() as tx:
        return leads.request_accept(tx, actor, lead_id, NOW)


def _conf_data(out: list[Any], label: str) -> str:
    for row in out[-1].buttons:
        for text, data in row:
            if text == label:
                return str(data)
    raise AssertionError(f"sin botón {label}")


def _accept(bot: CrmBot, db: CrmDatabase, user_tg: int, actor: User, lead_id: int) -> str:
    """Pide la aceptación y devuelve el callback de ✅."""
    out = _request(db, actor, lead_id)
    yes = _conf_data(out, "✅")
    run(bot, _cb(user_tg, yes))
    return yes


def _by_target(db: CrmDatabase, users: dict[str, User]) -> dict[tuple[str, str], OutboxItem]:
    names = {u.id: k for k, u in users.items()}
    return {(names[i.recipient_user_id], i.channel): i for i in _outbox(db)}


# --- Confirmación ✅/❌ (VCRM-046) ---------------------------------------------------------


def test_vcrm046_accept_button_asks_confirmation_with_summary(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], **COMPLETE)
    run(bot, _msg(COM_TG, f"/ver L-{lead_id}"))
    run(bot, _cb(COM_TG, _sent_data(tg, "Aceptar")))
    ask = tg.sent[-1]
    assert f"L-{lead_id:04d}" in ask.text and "Ana Pérez" in ask.text
    assert "Comercial: com@k.co" in ask.text and "1020304050" in ask.text
    assert [b.text for row in ask.buttons or [] for b in row] == ["✅", "❌"]
    assert _get(db, lead_id).state == S.CONTACTADO  # solo pide confirmación
    assert _outbox(db) == []


def test_vcrm046_cancel_does_not_transition(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    out = _request(db, users["com"], lead_id)
    run(bot, _cb(COM_TG, _conf_data(out, "❌")))
    lead = _get(db, lead_id)
    assert (lead.state, lead.ever_accepted) == (S.CONTACTADO, 0)
    assert "No se aplicó la aceptación" in tg.sent[-1].text
    assert _outbox(db) == []


@pytest.mark.parametrize("src", [S.NUEVO, S.CONTACTADO, S.RECHAZADO])
def test_vcrm046_047_confirm_transitions_marks_and_enqueues_three(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User], src: LeadState
) -> None:
    lead_id = _lead(db, users["com"], src, **COMPLETE)
    _accept(bot, db, COM_TG, users["com"], lead_id)
    lead = _get(db, lead_id)
    assert (lead.state, lead.ever_accepted) == (S.ACEPTADO, 1)
    with db.read() as conn:
        last = repo.lead_events(conn, lead_id)[-1]
    assert (last.old_value, last.new_value, last.actor_user_id) == (
        src,
        S.ACEPTADO,
        users["com"].id,
    )
    targets = _by_target(db, users)
    assert set(targets) == {("cto", "telegram"), ("law", "telegram"), ("law", "email")}
    assert {i.kind for i in targets.values()} == {"aceptacion"}
    assert all(i.lead_id == lead_id and i.status == "pendiente" for i in targets.values())
    assert "aceptado" in tg.sent[-1].text


def test_n01_rejected_card_button_requests_confirmation_not_direct_transition(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], S.RECHAZADO, reject_reason="precio")
    run(bot, _msg(CTO_TG, f"/ver L-{lead_id}"))
    run(bot, _cb(CTO_TG, _sent_data(tg, "Aceptar")))
    assert _get(db, lead_id).state == S.RECHAZADO
    run(bot, _cb(CTO_TG, _sent_data(tg, "✅")))
    lead = _get(db, lead_id)
    assert (lead.state, lead.ever_accepted) == (S.ACEPTADO, 1)
    assert len(_outbox(db)) == 3


# --- Primer intento inmediato e independencia (VCRM-047) ---------------------------------


def test_vcrm047_first_attempt_at_confirmation_instant_via_kick(
    db: CrmDatabase,
    tg: FakeTelegram,
    mail: FakeEmailSender,
    bot: CrmBot,
    worker: OutboxWorker,
    users: dict[str, User],
) -> None:
    lead_id = _lead(db, users["com"], **COMPLETE)
    yes = _conf_data(_request(db, users["com"], lead_id), "✅")
    tg.fail_next(CTO_TG)  # el fallo de una no retrasa a las demás

    async def scenario() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(worker.run(stop))
        await asyncio.sleep(0.01)  # primer ciclo sin nada debido; luego espera 3600 s
        await bot.process_update(_cb(COM_TG, yes))
        for _ in range(200):
            if len(_outbox(db)) == 3 and all(i.attempts >= 1 for i in _outbox(db)):
                break
            await asyncio.sleep(0.005)
        stop.set()
        await task

    asyncio.run(scenario())
    targets = _by_target(db, users)
    assert {i.first_attempt_at for i in targets.values()} == {to_iso(NOW)}
    assert targets[("cto", "telegram")].status == "pendiente"
    assert targets[("law", "telegram")].status == "entregada"
    assert targets[("law", "email")].status == "entregada"
    assert [m.to for m in mail.sent] == ["law@k.co"]
    assert any(m.chat_id == LAW_TG for m in tg.sent)


# --- Contenido (VCRM-048, 104, 156) ------------------------------------------------------


def test_vcrm048_cto_notification_content(
    db: CrmDatabase, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], auth_status="autorizada", **COMPLETE)
    _accept(bot, db, CTO_TG, users["cto"], lead_id)
    body = _by_target(db, users)[("cto", "telegram")].body or ""
    for part in (
        f"L-{lead_id:04d}",
        "Comercial: com@k.co",
        f"Aceptado: {format_local(NOW)}",
        NOTE,
        "Autorización de datos: autorizada",
        "1020304050",
        "12.000.000 COP",
        "Faltantes: ninguno",
    ):
        assert part in body


def test_vcrm104_lawyer_telegram_alert_content(
    db: CrmDatabase, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], **COMPLETE)
    _accept(bot, db, COM_TG, users["com"], lead_id)
    body = _by_target(db, users)[("law", "telegram")].body or ""
    for part in (
        f"L-{lead_id:04d}",
        "Ana Pérez",
        "Comercial: com@k.co",
        format_local(NOW),
        "ficha completa se envió por correo",
    ):
        assert part in body
    assert NOTE not in body and "1020304050" not in body


def test_vcrm048_156_lawyer_email_only_handoff_data(
    db: CrmDatabase, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(
        db,
        users["com"],
        S.RECHAZADO,
        reject_reason="otro",
        reject_text="Motivo privado",
        **COMPLETE,
    )
    _accept(bot, db, COM_TG, users["com"], lead_id)
    item = _by_target(db, users)[("law", "email")]
    body = item.body or ""
    assert f"L-{lead_id:04d}" in (item.subject or "")
    for value in COMPLETE.values():
        assert value in body
    assert "Comercial: com@k.co" in body and format_local(NOW) in body
    assert "Autorización de datos: sin autorización" in body
    assert "preparar el contrato y la autorización de tratamiento de datos" in body
    for private in (NOTE, "Motivo privado", "rechaz", "Notas"):
        assert private not in body


# --- Faltantes del handoff (VCRM-052, 111) ------------------------------------------------


def test_vcrm052_111_missing_fields_in_all_three_and_request_to_commercial(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    partial = {k: v for k, v in COMPLETE.items() if k not in ("client_type", "agreed_value")}
    lead_id = _lead(db, users["com"], **partial)
    _accept(bot, db, CTO_TG, users["cto"], lead_id)
    items = _by_target(db, users)
    for key in (("cto", "telegram"), ("law", "email")):
        body = items[key].body or ""
        assert "Faltantes:" in body and REP_IF_COMPANY in body and LABEL_VALUE in body
    alert = items[("law", "telegram")].body or ""
    assert "Faltan campos del handoff" in alert and LABEL_VALUE in alert
    request = [m for m in tg.sent if m.chat_id == COM_TG]
    assert len(request) == 1
    assert f"L-{lead_id:04d}" in request[0].text and LABEL_VALUE in request[0].text
    assert "/editar" in request[0].text


def test_vcrm052_request_goes_to_cto_when_lead_is_his(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["cto"])
    _accept(bot, db, CTO_TG, users["cto"], lead_id)
    to_cto = [m.text for m in tg.sent if m.chat_id == CTO_TG]
    assert any("Faltan campos del handoff" in t and LABEL_DOC in t for t in to_cto)
    assert all(m.chat_id == CTO_TG for m in tg.sent)


def test_vcrm052_complete_handoff_sends_no_request(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], **COMPLETE)
    _accept(bot, db, CTO_TG, users["cto"], lead_id)
    assert not any(m.chat_id == COM_TG for m in tg.sent)
    assert "Faltan campos" not in (_by_target(db, users)[("law", "telegram")].body or "")
    assert "Faltantes: ninguno" in (_by_target(db, users)[("cto", "telegram")].body or "")


# --- Aceptación repetida (VCRM-051) -------------------------------------------------------


def test_vcrm051_double_confirm_says_already_accepted(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], **COMPLETE)
    yes = _accept(bot, db, COM_TG, users["com"], lead_id)
    run(bot, _cb(COM_TG, yes))
    assert "ya estaba aceptado" in tg.sent[-1].text
    assert len(_outbox(db)) == 3


def test_vcrm051_second_confirmation_of_accepted_lead(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], **COMPLETE)
    first = _conf_data(_request(db, users["com"], lead_id), "✅")
    second = _conf_data(_request(db, users["cto"], lead_id), "✅")
    run(bot, _cb(COM_TG, first))
    run(bot, _cb(CTO_TG, second))
    assert "ya estaba aceptado" in tg.sent[-1].text
    assert len(_outbox(db)) == 3
    with db.read() as conn:
        states = [e for e in repo.lead_events(conn, lead_id) if e.kind == "state"]
    assert len(states) == 1


def test_vcrm051_request_on_accepted_lead(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = _lead(db, users["com"], S.ACEPTADO, ever_accepted=1)
    out = _request(db, users["cto"], lead_id)
    assert "ya estaba aceptado" in out[0].text and not out[0].buttons


def test_double_confirm_after_cancel_is_already_processed(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    out = _request(db, users["com"], lead_id)
    run(bot, _cb(COM_TG, _conf_data(out, "❌")))
    run(bot, _cb(COM_TG, _conf_data(out, "✅")))
    assert tg.sent[-1].text == ALREADY_PROCESSED
    assert _get(db, lead_id).state == S.CONTACTADO


# --- Permisos y casos de error ------------------------------------------------------------


def test_vcrm046_lawyer_and_foreign_commercial_cannot_request(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    for actor in (users["law"], users["com2"]):
        out = _request(db, actor, lead_id)
        assert "No tiene permiso" in out[0].text and not out[0].buttons
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM crm_confirmations").fetchone()[0] == 0


def test_request_unknown_lead_and_invalid_state(db: CrmDatabase, users: dict[str, User]) -> None:
    assert "no existe" in _request(db, users["cto"], 999)[0].text
    lead_id = _lead(db, users["com"], S.GANADO, ever_accepted=1)
    out = _request(db, users["cto"], lead_id)
    assert "Transiciones válidas: baja." in out[0].text and not out[0].buttons


def test_confirm_when_state_changed_meanwhile_does_not_notify(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    yes = _conf_data(_request(db, users["com"], lead_id), "✅")
    with db.tx() as tx:
        repo.update_lead(tx, lead_id, {"state": S.GANADO}, now=NOW)
    run(bot, _cb(COM_TG, yes))
    assert _get(db, lead_id).state == S.GANADO
    assert "No se aplicó la transición" in tg.sent[-1].text
    assert _outbox(db) == []


def test_confirm_by_other_user_is_denied(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    yes = _conf_data(_request(db, users["com"], lead_id), "✅")
    run(bot, _cb(CTO_TG, yes))
    assert _get(db, lead_id).state == S.CONTACTADO
    assert _outbox(db) == []


def test_confirm_after_permission_lost_is_denied(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = _lead(db, users["com"])
    out = _request(db, users["com"], lead_id)
    with db.tx() as tx:
        repo.set_assignee(tx, lead_id, users["com2"].id)
        conf = repo.get_confirmation(tx, int(_conf_data(out, "✅").split(":")[2]))
        assert conf is not None
        denied = leads.confirm_accept(tx, users["com"], conf, True, NOW)
        gone = leads.confirm_accept(tx, users["com"], replace(conf, lead_id=999), True, NOW)
    assert "No tiene permiso" in denied[0].text
    assert "no existe" in gone[0].text
    assert _get(db, lead_id).state == S.CONTACTADO


def test_state_callback_accept_bad_args_is_invalid(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    run(bot, _cb(CTO_TG, build_callback("estado", "aceptar", "x")))
    assert tg.sent[-1].text == INVALID_BUTTON
