"""Tests de lista paginada y ficha por rol (VCRM-010, 011, 090, 092, 136)."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from crm_support import FakeClock, FakeTelegram, make_lead
from jerico.crm import leads, repo
from jerico.crm.bot import CrmBot
from jerico.crm.db import CrmDatabase
from jerico.crm.model import (
    AlertKind,
    AuditAction,
    AuditDetail,
    AuditOutcome,
    LeadState,
    Role,
    User,
)
from jerico.crm.parsing import build_callback, parse_callback
from jerico.crm.ports import Update
from jerico.crm.render import render_list_page
from jerico.crm.timeutil import to_iso

START = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
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
def tg() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def bot(db: CrmDatabase, tg: FakeTelegram) -> CrmBot:
    return CrmBot(db, tg, FakeClock(START + timedelta(days=30)).now)


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


def _lead(
    db: CrmDatabase,
    user_id: int | None,
    name: str,
    *,
    minutes: int = 0,
    accepted: bool = False,
    **changes: Any,
) -> int:
    """Lead con última interacción en `START + minutes`; `accepted` marca «alguna vez aceptado»."""
    with db.tx() as tx:
        lead_id = repo.insert_lead(
            tx, assigned_user_id=user_id, state=LeadState.NEW, now=START, fields={"name": name}
        )
        values: dict[str, Any] = dict(changes)
        if accepted:
            values["ever_accepted"] = 1
        repo.update_lead(tx, lead_id, values, now=START + timedelta(minutes=minutes))
    return lead_id


def _last_text(tg: FakeTelegram) -> str:
    return tg.sent[-1].text


def _last_audit(db: CrmDatabase) -> dict[str, Any]:
    with db.read() as conn:
        return dict(conn.execute("SELECT * FROM crm_audit ORDER BY id DESC LIMIT 1").fetchone())


def _labels(tg: FakeTelegram) -> list[str]:
    buttons = tg.sent[-1].buttons or []
    return [b.text for row in buttons for b in row]


# --- Lista por rol (VCRM-010) ----------------------------------------------------------


def test_vcrm010_commercial_sees_only_own_leads(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    _lead(db, users["com"].id, "Propio Uno")
    _lead(db, users["com2"].id, "Ajeno Dos")
    _lead(db, users["cto"].id, "Del Cto")
    run(bot, _msg(COM_TG, "/lista"))
    text = _last_text(tg)
    assert "Propio Uno" in text
    assert "Ajeno Dos" not in text and "Del Cto" not in text


def test_vcrm010_cto_sees_all_leads(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    _lead(db, users["com"].id, "Propio Uno")
    _lead(db, users["com2"].id, "Ajeno Dos")
    _lead(db, users["cto"].id, "Del Cto")
    run(bot, _msg(CTO_TG, "/lista"))
    text = _last_text(tg)
    assert "Propio Uno" in text and "Ajeno Dos" in text and "Del Cto" in text


def test_vcrm010_lawyer_sees_only_ever_accepted(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    _lead(db, users["com"].id, "Nunca Aceptado")
    _lead(db, users["com"].id, "Aceptado Hoy", accepted=True, state=LeadState.ACCEPTED.value)
    _lead(db, users["com2"].id, "Ganado Antes", accepted=True, state=LeadState.WON.value)
    _lead(db, users["com2"].id, "Retractado", accepted=True, state=LeadState.REJECTED.value)
    run(bot, _msg(LAW_TG, "/lista"))
    text = _last_text(tg)
    assert "Nunca Aceptado" not in text
    assert "Aceptado Hoy" in text and "Ganado Antes" in text and "Retractado" in text


def test_vcrm010_list_ordered_by_last_interaction_desc_with_fields(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    old = _lead(db, users["com"].id, "Antiguo", minutes=1)
    new = _lead(db, users["com"].id, "Reciente", minutes=300, state=LeadState.CONTACTED.value)
    mid = _lead(db, users["com"].id, "Medio", minutes=60)
    run(bot, _msg(COM_TG, "/lista"))
    lines = [line for line in _last_text(tg).split("\n") if line.startswith("L-")]
    assert [line.split(" · ")[0] for line in lines] == [
        f"L-{new:04d}",
        f"L-{mid:04d}",
        f"L-{old:04d}",
    ]
    # id, nombre, estado y fecha de última interacción (hora de Bogotá: 15:00 UTC + 300 min).
    assert lines[0] == f"L-{new:04d} · Reciente · contactado · 02/03/2026 15:00"


def test_vcrm010_list_ties_broken_by_id_desc(db: CrmDatabase, users: dict[str, User]) -> None:
    first = _lead(db, users["com"].id, "Uno")
    second = _lead(db, users["com"].id, "Dos")
    with db.read() as conn:
        listed = leads.visible_leads(conn, users["cto"])
    assert [lead.id for lead in listed] == [second, first]


def test_vcrm010_empty_list(tg: FakeTelegram, bot: CrmBot, users: dict[str, User]) -> None:
    run(bot, _msg(COM_TG, "/lista"))
    assert "No hay leads" in _last_text(tg)


# --- Paginación (VCRM-090) -------------------------------------------------------------


def test_vcrm090_25_leads_three_pages_with_navigation(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    for i in range(25):
        _lead(db, users["com"].id, f"Lead {i:02d}", minutes=i)
    run(bot, _msg(COM_TG, "/lista"))
    first = _last_text(tg)
    assert "página 1 de 3" in first and "Lead 24" in first and "Lead 14" not in first
    assert _labels(tg) == ["Siguiente"]
    run(bot, _msg(COM_TG, "/lista 2"))
    assert "página 2 de 3" in _last_text(tg)
    assert _labels(tg) == ["Anterior", "Siguiente"]
    buttons = tg.sent[-1].buttons or []
    following = parse_callback(buttons[0][1].callback_data)
    assert following is not None and following.args == ("3",)
    run(bot, _cb(COM_TG, buttons[0][1].callback_data))
    last = _last_text(tg)
    assert "página 3 de 3" in last and "Lead 00" in last
    assert _labels(tg) == ["Anterior"]


def test_vcrm090_list_callback_respects_role(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    for i in range(12):
        _lead(db, users["com"].id, f"Ajeno {i:02d}", minutes=i)
    run(bot, _cb(COM2_TG, build_callback("lista", "2")))
    assert "Ajeno" not in _last_text(tg)
    assert "página 1 de 1" in _last_text(tg)


def test_vcrm090_list_bad_page_argument(
    tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    run(bot, _msg(COM_TG, "/lista dos"))
    assert "Ejemplo: /lista 2" in _last_text(tg)
    run(bot, _cb(COM_TG, build_callback("lista", "x")))
    assert _last_text(tg) == "Botón no válido o caducado."


# --- «Sin comercial asignado» (VCRM-092) ---------------------------------------------


def test_vcrm092_cto_list_marks_unassigned_after_deactivation(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    orphan = _lead(db, users["com"].id, "Huérfano")
    kept = _lead(db, users["com2"].id, "Con Dueño")
    with db.tx() as tx:
        repo.deactivate_user(tx, users["com"].id, now=START)
    run(bot, _msg(CTO_TG, "/lista"))
    lines = {line.split(" · ")[0]: line for line in _last_text(tg).split("\n")}
    assert lines[f"L-{orphan:04d}"].endswith("sin comercial asignado")
    assert "sin comercial asignado" not in lines[f"L-{kept:04d}"]


def test_vcrm092_render_marks_only_given_ids() -> None:
    page = render_list_page(
        [make_lead(id=1, name="A"), make_lead(id=2, name="B")], 1, unassigned={2}
    )
    lines = page.text.split("\n")
    assert "sin comercial asignado" not in lines[1]
    assert lines[2].endswith("sin comercial asignado")


# --- Ficha (VCRM-011) -----------------------------------------------------------------


def test_vcrm011_full_card(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(
        db,
        users["com"].id,
        "Ana Pérez",
        phone_e164="+573001234567",
        email="ana@empresa.co",
        company="Empresa SAS",
        client_type="empresa",
        doc_type="NIT",
        doc_number="900123456",
        legal_rep="Luis Gómez",
        service="Asesoría",
        agreed_value="5000000",
        start_term="2026-04-01",
        state=LeadState.REJECTED.value,
        reject_reason="precio",
        reject_text="Le pareció caro",
        auth_status="authorized",
    )
    with db.tx() as tx:
        repo.insert_note(
            tx, lead_id=lead_id, author_user_id=users["com"].id, body="Llamar el martes", at=START
        )
        repo.insert_attachment(
            tx,
            lead_id=lead_id,
            kind="photo",
            author_user_id=users["com"].id,
            at=START,
            storage_key="k1",
            size_bytes=10,
            sha256="0" * 64,
        )
        repo.create_alert(tx, kind=AlertKind.NOTIFICATION_FAILED, now=START, lead_id=lead_id)
    run(bot, _msg(COM_TG, f"/ver L-{lead_id:04d}"))
    text = _last_text(tg)
    for expected in (
        f"L-{lead_id:04d}",
        "Ana Pérez",
        "+573001234567",
        "ana@empresa.co",
        "Empresa SAS",
        "Estado: rechazado",
        "Comercial: comercial com@k.co",
        "NIT 900123456",
        "Luis Gómez",
        "Asesoría",
        "5000000",
        "2026-04-01",
        "Llamar el martes",
        "com@k.co",
        "foto",
        "Motivo de rechazo: precio (Le pareció caro)",
        "Autorización de datos: autorizada",
        "Próxima acción: no aplica en F1",
        "notificación fallida",
        "02/03/2026 10:00",
    ):
        assert expected in text, expected


def test_vcrm011_card_without_optional_sections(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id, "Sin Extras")
    run(bot, _msg(CTO_TG, f"/ver L-{lead_id:04d}"))
    text = _last_text(tg)
    assert "Notas: ninguna" in text
    assert "Adjuntos: ninguno" in text
    assert "Alertas activas: ninguna" in text
    assert "Motivo de rechazo" not in text
    assert "Autorización de datos: sin autorización" in text


def test_vcrm011_card_hides_resolved_alerts_and_deleted_attachments(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id, "Limpio")
    with db.tx() as tx:
        alert = repo.create_alert(
            tx, kind=AlertKind.SUPPRESSION_NOTICE_FAILED, now=START, lead_id=lead_id
        )
        repo.resolve_alert(tx, alert, resolved_by=users["cto"].id, now=START)
        att = repo.insert_attachment(
            tx,
            lead_id=lead_id,
            kind="voice",
            author_user_id=users["com"].id,
            at=START,
            storage_key="k2",
            size_bytes=1,
            sha256="1" * 64,
        )
        tx.execute("UPDATE crm_attachments SET deleted_at = ? WHERE id = ?", ("x", att))
    run(bot, _msg(CTO_TG, f"/ver L-{lead_id:04d}"))
    text = _last_text(tg)
    assert "Alertas activas: ninguna" in text
    assert "Adjuntos: ninguno" in text


def test_vcrm011_lawyer_sees_card_of_ever_accepted_lead(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id, "Aceptada", accepted=True, state=LeadState.ACCEPTED.value)
    run(bot, _msg(LAW_TG, f"/ver L-{lead_id:04d}"))
    assert "Aceptada" in _last_text(tg) and "Estado: aceptado" in _last_text(tg)


def test_vcrm092_card_shows_unassigned_commercial(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id, "Huérfano")
    with db.tx() as tx:
        repo.deactivate_user(tx, users["com"].id, now=START)
    run(bot, _msg(CTO_TG, f"/ver L-{lead_id:04d}"))
    assert "Comercial: sin comercial asignado" in _last_text(tg)


def test_vcrm011_view_bad_format_and_missing_lead(
    tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    run(bot, _msg(CTO_TG, "/ver"))
    assert "Ejemplo: /ver L-0042" in _last_text(tg)
    run(bot, _msg(CTO_TG, "/ver L-0999"))
    assert _last_text(tg) == "El lead L-0999 no existe."


# --- Sin acceso (VCRM-109, VCRM-136) --------------------------------------------------


def test_vcrm136_lawyer_on_never_accepted_lead_denied_and_audited(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id, "Secreto Nombre", email="secreto@x.co")
    run(bot, _msg(LAW_TG, f"/ver L-{lead_id:04d}"))
    text = _last_text(tg)
    assert text == leads.NO_ACCESS
    assert "Secreto" not in text and "secreto@x.co" not in text
    row = _last_audit(db)
    assert row["actor"] == f"user:{users['law'].id}"
    assert row["action"] == AuditAction.PERMISSION_DENIED.value
    assert row["outcome"] == AuditOutcome.DENIED.value
    assert row["lead_id"] == lead_id
    assert row["detail_code"] == AuditDetail.FOREIGN_LEAD.value


def test_vcrm109_commercial_on_foreign_card_denied(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com2"].id, "Ajeno Total")
    run(bot, _msg(COM_TG, f"/ver L-{lead_id:04d}"))
    assert _last_text(tg) == leads.NO_ACCESS
    assert _last_audit(db)["detail_code"] == AuditDetail.FOREIGN_LEAD.value


def test_vcrm011_long_card_split_under_telegram_limit(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id, "Muchas Notas")
    with db.tx() as tx:
        for i in range(60):
            repo.insert_note(
                tx,
                lead_id=lead_id,
                author_user_id=users["com"].id,
                body=f"n{i} " + "x" * 100,
                at=START,
            )
    run(bot, _msg(COM_TG, f"/ver L-{lead_id:04d}"))
    assert len(tg.sent) > 1
    assert all(len(item.text) <= 4096 for item in tg.sent)
    joined = "\n".join(item.text for item in tg.sent)
    assert "n0 " in joined and "n59 " in joined and "Alertas activas: ninguna" in joined


def test_vcrm073_lead_suprimido_no_aparece_en_lista(
    db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, users: dict[str, User]
) -> None:
    # 1. Lead del comercial (no suprimido)
    l_com_active = _lead(db, users["com"].id, "Comercial Activo", minutes=1)
    # 2. Lead del mismo comercial (luego suprimido, marcado como ever_accepted)
    l_com_suppressed = _lead(db, users["com"].id, "Comercial Suprimido", minutes=2, accepted=True)
    # 3. Lead de otro comercial (com2, no suprimido, aceptado para que el abogado lo vea)
    l_com2_active = _lead(db, users["com2"].id, "Comercial2 Activo", minutes=3, accepted=True)

    # Suprimir el segundo lead marcando suppressed_at
    with db.tx() as tx:
        repo.update_lead(
            tx,
            l_com_suppressed,
            {"suppressed_at": to_iso(START), "name": None, "phone_e164": None, "email": None},
            now=START,
        )

    # 1) El comercial com ve solo su lead no suprimido:
    run(bot, _msg(COM_TG, "/lista"))
    com_text = _last_text(tg)
    assert f"L-{l_com_active:04d}" in com_text
    assert f"L-{l_com_suppressed:04d}" not in com_text
    assert f"L-{l_com2_active:04d}" not in com_text
    assert "página 1 de 1" in com_text

    # 2) El CTO ve los dos leads no suprimidos:
    run(bot, _msg(CTO_TG, "/lista"))
    cto_text = _last_text(tg)
    assert f"L-{l_com_active:04d}" in cto_text
    assert f"L-{l_com2_active:04d}" in cto_text
    assert f"L-{l_com_suppressed:04d}" not in cto_text
    assert "página 1 de 1" in cto_text

    # 3) El abogado ve solo los no suprimidos aceptados (l_com2_active):
    run(bot, _msg(LAW_TG, "/lista"))
    law_text = _last_text(tg)
    assert f"L-{l_com2_active:04d}" in law_text
    assert f"L-{l_com_suppressed:04d}" not in law_text
    assert f"L-{l_com_active:04d}" not in law_text
    assert "página 1 de 1" in law_text

    # 4) /ver del lead suprimido sigue respondiendo como antes (no se oculta en /ver):
    run(bot, _msg(CTO_TG, f"/ver L-{l_com_suppressed:04d}"))
    ver_text = _last_text(tg)
    assert f"Ficha L-{l_com_suppressed:04d}" in ver_text
