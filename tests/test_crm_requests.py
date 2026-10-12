"""Tests de las solicitudes de titulares: plazos hábiles, escalado y vencimiento (T21).

Requisitos: VCRM-150, 151, 152 (decisiones J-05, J-06).
"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from crm_support import FakeClock, FakeTelegram, make_settings
from jerico.crm import compliance, repo, retention
from jerico.crm.bot import CrmBot
from jerico.crm.config import Params, default_params, effective_params
from jerico.crm.db import CrmDatabase
from jerico.crm.model import (
    AlertKind,
    EventKind,
    LeadState,
    RequestStatus,
    RequestType,
    Role,
    User,
)
from jerico.crm.ports import Update
from jerico.crm.render import ALERT_MARK

# Lunes 02/03/2026, 10:00 en Bogotá. Festivo: lunes 23/03/2026 (San José trasladado).
START = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
CTO_TG = 1000
COM_TG = 2000
COM2_TG = 2100
LAW_TG = 3000
PARAMS = default_params()


def at(day: date) -> datetime:
    """10:00 de Bogotá del día indicado."""
    return datetime(day.year, day.month, day.day, 15, 0, tzinfo=UTC)


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
                tx, telegram_id=COM2_TG, role=Role.COMMERCIAL, email="n@k.co", now=START
            ),
            "law": repo.insert_user(
                tx, telegram_id=LAW_TG, role=Role.LAWYER, email="l@k.co", now=START
            ),
        }


@pytest.fixture
def lead_id(db: CrmDatabase, users: dict[str, User]) -> int:
    with db.tx() as tx:
        return repo.insert_lead(
            tx,
            assigned_user_id=users["com"].id,
            state=LeadState.NEW,
            now=START,
            fields={"name": "Ana Pérez", "phone_e164": "+573001234567"},
        )


def make_bot(
    db: CrmDatabase, tg: FakeTelegram, clock: FakeClock, params: Params = PARAMS
) -> CrmBot:
    return CrmBot(db, tg, clock.now, fingerprint_keys=("k",), params=params)


_ids = iter(range(1, 100_000))


def send(bot: CrmBot, user_tg: int, text: str) -> None:
    u = Update(
        update_id=next(_ids), user_id=user_tg, chat_id=user_tg, chat_type="private", text=text
    )
    asyncio.run(bot.process_update(u))


def texts(tg: FakeTelegram, chat_id: int) -> list[str]:
    return [s.text for s in tg.sent if s.chat_id == chat_id]


def sweep(db: CrmDatabase, day: date, params: Params = PARAMS) -> list[str]:
    with db.tx() as tx:
        out = retention.sweep_requests(tx, at(day), params)
    assert all(o.chat_id == CTO_TG for o in out)
    return [o.text for o in out]


def register(db: CrmDatabase, actor: User, text: str, day: date = date(2026, 3, 2)) -> str:
    with db.tx() as tx:
        out = compliance.request_command(tx, actor, text, at(day), PARAMS)
    return out[0].text


# --- Plazos (VCRM-150) -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "received", "extra", "due"),
    [
        (RequestType.INQUIRY, date(2026, 3, 2), frozenset(), date(2026, 3, 16)),
        (RequestType.CLAIM, date(2026, 3, 2), frozenset(), date(2026, 3, 24)),  # festivo 23/03
        (RequestType.INQUIRY, date(2026, 3, 16), frozenset(), date(2026, 3, 31)),
        (RequestType.INQUIRY, date(2026, 3, 2), frozenset({date(2026, 3, 3)}), date(2026, 3, 17)),
        (RequestType.INQUIRY, date(2026, 3, 7), frozenset(), date(2026, 3, 20)),  # sábado
    ],
)
def test_due_on_counts_business_days_from_next_business_day(
    kind: RequestType, received: date, extra: frozenset[date], due: date
) -> None:
    params = effective_params(make_settings(), extra)[0]
    assert compliance.request_due_on(kind, received, params) == due


def test_configured_deadline_above_legal_cap_uses_cap() -> None:
    params, warnings = effective_params(
        make_settings(query_deadline_business_days=20, claim_deadline_business_days=30)
    )
    assert {w.param for w in warnings} >= {
        "query_deadline_business_days",
        "claim_deadline_business_days",
    }
    assert compliance.request_due_on(RequestType.INQUIRY, date(2026, 3, 2), params) == date(
        2026, 3, 16
    )
    assert compliance.request_due_on(RequestType.CLAIM, date(2026, 3, 2), params) == date(
        2026, 3, 24
    )


def test_shorter_configured_deadline_is_respected() -> None:
    params = effective_params(make_settings(query_deadline_business_days=5))[0]
    assert compliance.request_due_on(RequestType.INQUIRY, date(2026, 3, 2), params) == date(
        2026, 3, 9
    )


# --- Registro por el bot (VCRM-150) -----------------------------------------------------


def test_commercial_registers_own_lead_request_and_cto_is_shown(
    db: CrmDatabase, tg: FakeTelegram, clock: FakeClock, users: dict[str, User], lead_id: int
) -> None:
    bot = make_bot(db, tg, clock)
    send(bot, COM_TG, "/solicitud L-0001; consulta; 2026-03-02; correo electrónico")
    with db.tx() as tx:
        (req,) = repo.titular_requests(tx)
        events = repo.lead_events(tx, lead_id)
    assert req.lead_id == lead_id
    assert req.type == RequestType.INQUIRY
    assert req.medium == "correo electrónico"
    assert req.received_on == "2026-03-02"
    assert req.due_on == "2026-03-16"
    assert req.status == RequestStatus.OPEN
    assert req.registered_by == users["com"].id
    assert any(e.kind == EventKind.TITULAR_REQUEST for e in events)
    (mine,) = texts(tg, COM_TG)
    assert "S-0001" in mine and "16/03/2026" in mine
    (shown,) = texts(tg, CTO_TG)
    for piece in ("S-0001", "L-0001", "consulta", "correo electrónico", "02/03/2026", "16/03/2026"):
        assert piece in shown


def test_cto_registers_on_any_lead_without_self_copy(
    db: CrmDatabase, tg: FakeTelegram, clock: FakeClock, users: dict[str, User], lead_id: int
) -> None:
    bot = make_bot(db, tg, clock)
    send(bot, CTO_TG, "/solicitud L-0001; reclamo; 2026-03-02; llamada")
    with db.tx() as tx:
        (req,) = repo.titular_requests(tx)
    assert req.type == RequestType.CLAIM and req.due_on == "2026-03-24"
    assert len(texts(tg, CTO_TG)) == 1


def test_registration_uses_extra_holidays_from_params(
    db: CrmDatabase, tg: FakeTelegram, clock: FakeClock, users: dict[str, User], lead_id: int
) -> None:
    params = effective_params(make_settings(), frozenset({date(2026, 3, 3)}))[0]
    bot = make_bot(db, tg, clock, params)
    send(bot, COM_TG, "/solicitud L-0001; consulta; 2026-03-02; correo")
    with db.tx() as tx:
        (req,) = repo.titular_requests(tx)
    assert req.due_on == "2026-03-17"


def test_future_reception_date_is_rejected(
    db: CrmDatabase, users: dict[str, User], lead_id: int
) -> None:
    text = register(db, users["com"], "/solicitud L-0001; consulta; 2026-03-03; correo")
    assert "futura" in text
    with db.tx() as tx:
        assert repo.titular_requests(tx) == []


@pytest.mark.parametrize(
    "command",
    [
        "/solicitud",
        "/solicitud L-0001; consulta; 2026-03-02",
        "/solicitud X-1; consulta; 2026-03-02; correo",
        "/solicitud L-0001; queja; 2026-03-02; correo",
        "/solicitud L-0001; consulta; 02/03/2026; correo",
        "/solicitud L-0001; consulta; 2026-02-30; correo",
    ],
)
def test_malformed_request_is_rejected_with_example(
    db: CrmDatabase, users: dict[str, User], lead_id: int, command: str
) -> None:
    text = register(db, users["cto"], command)
    assert compliance.EXAMPLE_REQUEST in text
    with db.tx() as tx:
        assert repo.titular_requests(tx) == []


def test_unknown_lead_foreign_lead_and_lawyer_are_rejected(
    db: CrmDatabase, users: dict[str, User], lead_id: int
) -> None:
    assert "no existe" in register(db, users["cto"], "/solicitud L-0099; consulta; 2026-03-02; c")
    assert (
        "no tiene acceso"
        in register(db, users["com2"], "/solicitud L-0001; consulta; 2026-03-02; c").lower()
    )
    register(db, users["law"], "/solicitud L-0001; consulta; 2026-03-02; c")
    with db.tx() as tx:
        assert repo.titular_requests(tx) == []


def test_requests_list_only_for_cto(
    db: CrmDatabase, tg: FakeTelegram, clock: FakeClock, users: dict[str, User], lead_id: int
) -> None:
    bot = make_bot(db, tg, clock)
    send(bot, CTO_TG, "/solicitudes")
    assert texts(tg, CTO_TG)[-1] == compliance.NO_REQUESTS
    send(bot, COM_TG, "/solicitud L-0001; consulta; 2026-03-02; correo")
    send(bot, CTO_TG, "/solicitudes")
    listing = texts(tg, CTO_TG)[-1]
    for piece in ("S-0001", "L-0001", "consulta", "02/03/2026", "16/03/2026", "abierta"):
        assert piece in listing
    send(bot, COM_TG, "/solicitudes")
    assert "S-0001" not in texts(tg, COM_TG)[-1]


# --- Escalado (VCRM-151) y vencimiento (VCRM-152) ------------------------------------------


def test_escalation_after_two_business_days_once_per_business_day(
    db: CrmDatabase, users: dict[str, User], lead_id: int
) -> None:
    register(db, users["com"], "/solicitud L-0001; consulta; 2026-03-02; correo")
    assert sweep(db, date(2026, 3, 3)) == []
    (first,) = sweep(db, date(2026, 3, 4))
    for piece in ("S-0001", "L-0001", "consulta", "02/03/2026", "8"):
        assert piece in first
    assert sweep(db, date(2026, 3, 4)) == []  # no dos veces el mismo día
    assert len(sweep(db, date(2026, 3, 5))) == 1
    assert sweep(db, date(2026, 3, 7)) == []  # sábado
    assert sweep(db, date(2026, 3, 8)) == []  # domingo
    assert len(sweep(db, date(2026, 3, 9))) == 1


def test_no_escalation_on_holiday_or_extra_holiday(
    db: CrmDatabase, users: dict[str, User], lead_id: int
) -> None:
    register(db, users["cto"], "/solicitud L-0001; consulta; 2026-03-16; correo", date(2026, 3, 16))
    assert len(sweep(db, date(2026, 3, 18))) == 1
    assert sweep(db, date(2026, 3, 23)) == []  # festivo
    extra = effective_params(make_settings(), frozenset({date(2026, 3, 24)}))[0]
    assert sweep(db, date(2026, 3, 24), extra) == []  # festivo extraordinario
    assert len(sweep(db, date(2026, 3, 25))) == 1


def test_vcrm152_overdue_marks_alert_and_keeps_daily_notice(
    db: CrmDatabase, tg: FakeTelegram, clock: FakeClock, users: dict[str, User], lead_id: int
) -> None:
    register(db, users["com"], "/solicitud L-0001; consulta; 2026-03-02; correo")
    (notice,) = sweep(db, date(2026, 3, 16))
    assert "vencida" in notice and "0" in notice
    with db.tx() as tx:
        (req,) = repo.titular_requests(tx)
        alerts = repo.open_alerts(tx)
    assert req.status == RequestStatus.OVERDUE
    assert [(a.kind, a.lead_id, a.request_id) for a in alerts] == [
        (AlertKind.REQUEST_OVERDUE, lead_id, req.id)
    ]
    assert sweep(db, date(2026, 3, 16)) == []
    assert len(sweep(db, date(2026, 3, 17))) == 1
    with db.tx() as tx:
        assert len(repo.open_alerts(tx)) == 1  # sin alertas duplicadas
    clock.advance(days=15)
    send(make_bot(db, tg, clock), CTO_TG, "/lista")
    assert ALERT_MARK in texts(tg, CTO_TG)[-1]


def test_attended_only_by_cto_records_author_and_stops_notices(
    db: CrmDatabase, tg: FakeTelegram, clock: FakeClock, users: dict[str, User], lead_id: int
) -> None:
    register(db, users["com"], "/solicitud L-0001; consulta; 2026-03-02; correo")
    sweep(db, date(2026, 3, 16))
    bot = make_bot(db, tg, clock)
    clock.advance(days=15)
    send(bot, COM_TG, "/atendida S-0001")
    with db.tx() as tx:
        assert repo.titular_requests(tx)[0].status == RequestStatus.OVERDUE
    send(bot, CTO_TG, "/atendida S-0001")
    with db.tx() as tx:
        (req,) = repo.titular_requests(tx)
        assert repo.open_alerts(tx) == []
    assert req.status == RequestStatus.ATTENDED
    assert req.attended_by == users["cto"].id
    assert req.attended_at is not None
    assert "S-0001" in texts(tg, CTO_TG)[-1]
    assert sweep(db, date(2026, 3, 18)) == []
    send(bot, CTO_TG, "/atendida S-0001")
    assert texts(tg, CTO_TG)[-1] == compliance.REQUEST_ALREADY_ATTENDED
    send(bot, CTO_TG, "/atendida S-0042")
    assert "no existe" in texts(tg, CTO_TG)[-1]
    send(bot, CTO_TG, "/atendida L-0001")
    assert compliance.EXAMPLE_ATTENDED in texts(tg, CTO_TG)[-1]


def test_attended_before_escalation_never_notifies(
    db: CrmDatabase, users: dict[str, User], lead_id: int
) -> None:
    register(db, users["com"], "/solicitud L-0001; consulta; 2026-03-02; correo")
    with db.tx() as tx:
        compliance.attended_command(tx, users["cto"], "/atendida S-0001", at(date(2026, 3, 3)))
    assert sweep(db, date(2026, 3, 4)) == []
    assert sweep(db, date(2026, 3, 16)) == []


def test_daily_sweep_delivers_and_records_failed_notice(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User], lead_id: int
) -> None:
    register(db, users["com"], "/solicitud L-0001; consulta; 2026-03-02; correo")
    asyncio.run(retention.daily_sweep(db, tg, at(date(2026, 3, 4)), PARAMS))
    assert len(texts(tg, CTO_TG)) == 1
    tg.fail_next(CTO_TG)
    asyncio.run(retention.daily_sweep(db, tg, at(date(2026, 3, 5)) + timedelta(hours=1), PARAMS))
    with db.tx() as tx:
        failed = tx.execute(
            "SELECT recipient_user_id, body FROM crm_outbox WHERE status = 'failed'"
        ).fetchall()
    assert [(r["recipient_user_id"], r["body"]) for r in failed] == [(users["cto"].id, None)]
