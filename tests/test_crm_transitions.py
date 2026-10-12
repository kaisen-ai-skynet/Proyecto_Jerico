"""Tests de transiciones: contacto, rechazo con motivo, ganado y perdido (T14).

Requisitos: VCRM-014, 015, 016, 017, 089, 109, 115, 116, 117, 118, 132, 133, 134.
"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from crm_support import FakeClock, FakeTelegram
from jerico.crm import leads, repo, team
from jerico.crm.bot import INVALID_BUTTON, CrmBot
from jerico.crm.db import CrmDatabase
from jerico.crm.model import AuditAction, AuditDetail, AuditOutcome, LeadState, Role, User
from jerico.crm.parsing import build_callback
from jerico.crm.ports import Update
from jerico.crm.timeutil import to_iso

START = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
NOW = START + timedelta(days=1)
CTO_TG = 1000
COM_TG = 2000
COM2_TG = 2100
LAW_TG = 3000
S = LeadState


@pytest.fixture
def db(tmp_path: Path) -> Iterator[CrmDatabase]:
    database = CrmDatabase(tmp_path / "crm.db")
    yield database
    database.close()


@pytest.fixture
def tg() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def bot(db: CrmDatabase, tg: FakeTelegram) -> CrmBot:
    return CrmBot(db, tg, FakeClock(NOW).now)


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


def _lead(db: CrmDatabase, owner: User, state: LeadState, **changes: Any) -> int:
    with db.tx() as tx:
        lead_id = repo.insert_lead(
            tx, assigned_user_id=owner.id, state=state, now=START, fields={"name": "Ana Pérez"}
        )
        if changes:
            repo.update_lead(tx, lead_id, changes, now=START)
    return lead_id


def _state(db: CrmDatabase, lead_id: int) -> str:
    with db.read() as conn:
        lead = repo.get_lead(conn, lead_id)
    assert lead is not None
    return lead.state


def _transition(
    db: CrmDatabase, actor: User, lead_id: int, dst: LeadState, **kw: str | None
) -> list[Any]:
    with db.tx() as tx:
        return leads.transition(tx, actor, lead_id, dst, NOW, **kw)


def _state_events(db: CrmDatabase, lead_id: int) -> list[Any]:
    with db.read() as conn:
        return [e for e in repo.lead_events(conn, lead_id) if e.kind == "state"]


def _last_audit(db: CrmDatabase) -> dict[str, Any]:
    with db.read() as conn:
        return dict(conn.execute("SELECT * FROM crm_audit ORDER BY id DESC LIMIT 1").fetchone())


def _labels(out: Any) -> list[str]:
    return [label for row in out.buttons for label, _ in row]


def _sent_labels(tg: FakeTelegram) -> list[str]:
    buttons = tg.sent[-1].buttons or []
    return [b.text for row in buttons for b in row]


def _sent_data(tg: FakeTelegram, label: str) -> str:
    for row in tg.sent[-1].buttons or []:
        for b in row:
            if b.text == label:
                return b.callback_data
    raise AssertionError(f"sin botón {label}")


# --- Registrar contacto (VCRM-089) -------------------------------------------------------


@pytest.mark.parametrize("src", [S.NEW, S.REJECTED])
def test_vcrm089_contact_button_moves_to_contactado(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User], src: LeadState
) -> None:
    lead_id = _lead(db, users["com"], src)
    run(bot, _msg(COM_TG, f"/ver L-{lead_id}"))
    assert "Registrar contacto" in _sent_labels(tg)
    run(bot, _cb(COM_TG, _sent_data(tg, "Registrar contacto")))
    assert _state(db, lead_id) == S.CONTACTED
    assert "contactado" in tg.sent[-1].text


def test_vcrm089_contact_not_offered_from_contactado(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], S.CONTACTED)
    run(bot, _msg(COM_TG, f"/ver L-{lead_id}"))
    assert "Registrar contacto" not in _sent_labels(tg)
    assert "Rechazar" in _sent_labels(tg)


# --- Rechazo con motivo (VCRM-016, 017, 118) ----------------------------------------------


def test_vcrm016_reject_without_reason_asks_reason_buttons(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], S.CONTACTED)
    out = _transition(db, users["com"], lead_id, S.REJECTED)
    assert _state(db, lead_id) == S.CONTACTED
    assert _labels(out[0]) == list(leads.REJECT_REASONS.values())
    assert _state_events(db, lead_id) == []


def test_vcrm016_unknown_reason_not_applied(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = _lead(db, users["com"], S.NEW)
    out = _transition(db, users["com"], lead_id, S.REJECTED, reason="capricho")
    assert _state(db, lead_id) == S.NEW
    assert _labels(out[0]) == list(leads.REJECT_REASONS.values())


def test_vcrm016_reject_flow_by_buttons(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], S.NEW)
    run(bot, _msg(COM_TG, f"/ver L-{lead_id}"))
    run(bot, _cb(COM_TG, _sent_data(tg, "Rechazar")))
    assert _state(db, lead_id) == S.NEW
    assert _sent_labels(tg) == list(leads.REJECT_REASONS.values())
    run(bot, _cb(COM_TG, _sent_data(tg, leads.REJECT_REASONS["precio"])))
    with db.read() as conn:
        lead = repo.get_lead(conn, lead_id)
    assert lead is not None
    assert (lead.state, lead.reject_reason, lead.reject_text) == (S.REJECTED, "precio", None)


def test_vcrm017_other_without_text_asks_text_and_does_not_transition(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], S.CONTACTED)
    run(bot, _cb(COM_TG, build_callback("motivo", str(lead_id), "otro")))
    assert _state(db, lead_id) == S.CONTACTED
    assert "Escriba el motivo" in tg.sent[-1].text
    run(bot, _msg(COM_TG, "   "))
    assert _state(db, lead_id) == S.CONTACTED
    assert "Escriba el motivo" in tg.sent[-1].text
    run(bot, _msg(COM_TG, "Se fue con un familiar"))
    with db.read() as conn:
        lead = repo.get_lead(conn, lead_id)
    assert lead is not None
    assert (lead.state, lead.reject_reason, lead.reject_text) == (
        S.REJECTED,
        "otro",
        "Se fue con un familiar",
    )


def test_vcrm017_direct_other_with_blank_text_sets_pending(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], S.NEW)
    out = _transition(db, users["com"], lead_id, S.REJECTED, reason="otro", reason_text="  ")
    assert _state(db, lead_id) == S.NEW
    assert "Escriba el motivo" in out[0].text
    with db.read() as conn:
        pending = repo.get_pending_input(conn, users["com"].id, NOW)
    assert pending is not None
    assert (pending.kind, pending.lead_id) == (leads.REJECT_TEXT_KIND, lead_id)


def test_vcrm118_reject_leaves_rejected_without_next_action(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], S.CONTACTED)
    _transition(db, users["com"], lead_id, S.REJECTED, reason="momento")
    assert _state(db, lead_id) == S.REJECTED
    with db.read() as conn:
        outbox = conn.execute("SELECT COUNT(*) FROM crm_outbox WHERE lead_id = ?", (lead_id,))
        assert outbox.fetchone()[0] == 0
    run(bot, _msg(COM_TG, f"/ver L-{lead_id}"))
    card = "\n".join(m.text for m in tg.sent)
    assert "Próxima acción: no aplica en F1" in card
    assert "Motivo de rechazo: momento" in card


def test_reject_from_accepted_requires_retraction_flow(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], S.ACCEPTED, ever_accepted=1)
    out = _transition(db, users["com"], lead_id, S.REJECTED, reason="precio")
    assert _state(db, lead_id) == S.ACCEPTED
    assert "retractación" in out[0].text


# --- Vuelta desde rechazado (VCRM-132) ----------------------------------------------------


@pytest.mark.parametrize("retracted", [0, 1])
@pytest.mark.parametrize("dst", [S.CONTACTED, S.ACCEPTED])
def test_vcrm132_return_from_rejected_preserves_history_and_data(
    db: CrmDatabase, users: dict[str, User], dst: LeadState, retracted: int
) -> None:
    com = users["com"]
    lead_id = _lead(db, com, S.CONTACTED, auth_status="authorized")
    _transition(db, com, lead_id, S.REJECTED, reason="otro", reason_text="Sin fondos")
    with db.tx() as tx:
        repo.update_lead(tx, lead_id, {"rejection_is_retraction": retracted}, now=NOW)
        repo.insert_note(tx, lead_id=lead_id, author_user_id=com.id, body="nota", at=NOW)
        repo.insert_attachment(
            tx,
            lead_id=lead_id,
            kind="photo",
            author_user_id=com.id,
            at=NOW,
            storage_key="k",
            size_bytes=1,
            sha256="0" * 64,
        )
        tx.execute(
            "INSERT INTO crm_consents (lead_id, status, medium, at, actor_user_id) "
            "VALUES (?, 'authorized', 'documento', ?, ?)",
            (lead_id, to_iso(NOW), com.id),
        )
    _transition(db, users["cto"], lead_id, dst)
    events = _state_events(db, lead_id)
    assert [(e.old_value, e.new_value) for e in events] == [
        (S.CONTACTED, S.REJECTED),
        (S.REJECTED, dst),
    ]
    assert (events[0].reason, events[0].reason_text, events[0].actor_user_id) == (
        "otro",
        "Sin fondos",
        com.id,
    )
    with db.read() as conn:
        lead = repo.get_lead(conn, lead_id)
        assert len(repo.lead_notes(conn, lead_id)) == 1
        assert len(repo.lead_attachments(conn, lead_id)) == 1
        consents = conn.execute("SELECT COUNT(*) FROM crm_consents WHERE lead_id = ?", (lead_id,))
        assert consents.fetchone()[0] == 1
    assert lead is not None
    assert (lead.state, lead.auth_status, lead.rejection_is_retraction) == (
        dst,
        "authorized",
        retracted,
    )


# --- Ganado (VCRM-115, 134) ---------------------------------------------------------------


@pytest.mark.parametrize("who", ["cto", "law"])
def test_vcrm115_won_by_cto_or_lawyer(db: CrmDatabase, users: dict[str, User], who: str) -> None:
    lead_id = _lead(db, users["com"], S.ACCEPTED, ever_accepted=1)
    out = _transition(db, users[who], lead_id, S.WON)
    with db.read() as conn:
        lead = repo.get_lead(conn, lead_id)
    assert lead is not None
    assert (lead.state, lead.won_at) == (S.WON, to_iso(NOW))
    events = _state_events(db, lead_id)
    assert [(e.old_value, e.new_value, e.actor_user_id) for e in events] == [
        (S.ACCEPTED, S.WON, users[who].id)
    ]
    assert "ganado" in out[0].text


def test_vcrm115_won_button_end_to_end_for_lawyer(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], S.ACCEPTED, ever_accepted=1)
    run(bot, _msg(LAW_TG, f"/ver L-{lead_id}"))
    assert _sent_labels(tg) == ["Ganado", "Retractar"]  # VCRM-163: el abogado puede retractar
    run(bot, _cb(LAW_TG, _sent_data(tg, "Ganado")))
    assert _state(db, lead_id) == S.WON


def test_vcrm134_commercial_cannot_mark_won(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], S.ACCEPTED, ever_accepted=1)
    run(bot, _msg(COM_TG, f"/ver L-{lead_id}"))
    assert "Ganado" not in _sent_labels(tg)
    run(bot, _cb(COM_TG, build_callback("estado", "ganado", str(lead_id))))
    assert _state(db, lead_id) == S.ACCEPTED
    assert tg.sent[-1].text == leads.WON_RESERVED
    assert "corresponde al CTO o al abogado" in leads.WON_RESERVED
    row = _last_audit(db)
    assert (row["action"], row["outcome"], row["lead_id"]) == (
        AuditAction.PERMISSION_DENIED,
        AuditOutcome.DENIED,
        lead_id,
    )


# --- Perdido (VCRM-116, 133) --------------------------------------------------------------


@pytest.mark.parametrize("src", [S.NEW, S.CONTACTED, S.REJECTED])
@pytest.mark.parametrize("who", ["com", "cto"])
def test_vcrm116_lost_by_owner_or_cto(
    db: CrmDatabase, users: dict[str, User], src: LeadState, who: str
) -> None:
    lead_id = _lead(db, users["com"], src)
    with db.tx() as tx:
        conf_id = repo.create_confirmation(
            tx, kind="accept", lead_id=lead_id, user_id=users["com"].id, now=START
        )
    _transition(db, users[who], lead_id, S.LOST)
    with db.read() as conn:
        lead = repo.get_lead(conn, lead_id)
        conf = repo.get_confirmation(conn, conf_id)
    assert lead is not None and conf is not None
    assert (lead.state, lead.final_state_at) == (S.LOST, to_iso(NOW))
    assert conf.status == "cancelled"


def test_vcrm116_lawyer_cannot_mark_lost(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = _lead(db, users["com"], S.REJECTED, ever_accepted=1)
    out = _transition(db, users["law"], lead_id, S.LOST)
    assert _state(db, lead_id) == S.REJECTED
    assert out[0].text == team.DENIED
    assert _last_audit(db)["action"] == AuditAction.PERMISSION_DENIED


def test_vcrm133_accepted_to_lost_requires_retraction(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], S.ACCEPTED, ever_accepted=1)
    out = _transition(db, users["cto"], lead_id, S.LOST)
    assert _state(db, lead_id) == S.ACCEPTED
    assert "primero" in out[0].text.lower() and "retractación" in out[0].text


# --- Estados finales y transiciones no permitidas (VCRM-117, 014) --------------------------


@pytest.mark.parametrize("src", [S.WON, S.LOST])
@pytest.mark.parametrize("dst", [S.CONTACTED, S.REJECTED, S.WON, S.LOST])
def test_vcrm117_final_states_only_allow_baja(
    db: CrmDatabase, users: dict[str, User], src: LeadState, dst: LeadState
) -> None:
    lead_id = _lead(db, users["com"], src, ever_accepted=1)
    out = _transition(db, users["cto"], lead_id, dst, reason="precio")
    assert _state(db, lead_id) == src
    assert out[0].text.endswith("Transiciones válidas: baja.")


def test_vcrm117_final_states_offer_no_state_buttons(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], S.WON, ever_accepted=1)
    run(bot, _msg(CTO_TG, f"/ver L-{lead_id}"))
    assert _sent_labels(tg) == []


def test_vcrm014_not_allowed_lists_valid_targets(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = _lead(db, users["com"], S.CONTACTED)
    out = _transition(db, users["com"], lead_id, S.CONTACTED)
    assert _state(db, lead_id) == S.CONTACTED
    assert out[0].text == (
        "No se aplicó la transición: desde «contactado» no se puede pasar a «contactado». "
        "Transiciones válidas: aceptado, rechazado, perdido, baja."
    )
    assert _state_events(db, lead_id) == []


# --- Historial (VCRM-015) -----------------------------------------------------------------


def test_vcrm015_history_records_origin_target_author_date_reason(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], S.NEW)
    _transition(db, users["com"], lead_id, S.REJECTED, reason="proveedor")
    (event,) = _state_events(db, lead_id)
    assert (
        event.old_value,
        event.new_value,
        event.actor_user_id,
        event.at,
        event.reason,
        event.reason_text,
    ) == (S.NEW, S.REJECTED, users["com"].id, to_iso(NOW), "proveedor", None)


def test_vcrm015_history_has_no_edit_or_delete_operation() -> None:
    names = [n for n in dir(repo) if "event" in n]
    assert names and all(not n.startswith(("update", "delete", "remove", "edit")) for n in names)


# --- Acceso y botones inválidos (VCRM-109) -------------------------------------------------


def test_vcrm109_foreign_commercial_state_button_no_access(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], S.NEW)
    run(bot, _cb(COM2_TG, build_callback("estado", "contacto", str(lead_id))))
    assert _state(db, lead_id) == S.NEW
    assert tg.sent[-1].text == leads.NO_ACCESS
    row = _last_audit(db)
    assert (row["lead_id"], row["detail_code"]) == (lead_id, AuditDetail.FOREIGN_LEAD.value)


def test_transition_on_missing_lead(db: CrmDatabase, users: dict[str, User]) -> None:
    out = _transition(db, users["cto"], 999, S.CONTACTED)
    assert out[0].text == "El lead L-0999 no existe."


@pytest.mark.parametrize(
    "data",
    [
        build_callback("estado", "volar", "1"),
        build_callback("estado", "contacto", "x"),
        build_callback("estado", "contacto"),
        build_callback("motivo", "1", "capricho"),
        build_callback("motivo", "x", "precio"),
    ],
)
def test_invalid_state_buttons(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User], data: str
) -> None:
    run(bot, _cb(CTO_TG, data))
    assert tg.sent[-1].text == INVALID_BUTTON


def test_card_buttons_by_role_on_rejected_lead(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], S.REJECTED, ever_accepted=1)
    run(bot, _msg(CTO_TG, f"/ver L-{lead_id}"))
    assert _sent_labels(tg) == ["Registrar contacto", "Aceptar", "Perdido"]
    run(bot, _msg(LAW_TG, f"/ver L-{lead_id}"))
    assert _sent_labels(tg) == []
