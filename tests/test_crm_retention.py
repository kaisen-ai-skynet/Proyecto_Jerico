"""Tests de conservación y supresión por plazo en el barrido diario (T22).

Requisitos: VCRM-145, 146, 147, 154, 158, 159, 164 (J-01, J-14; decisión K-4).
"""

import asyncio
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from crm_support import FakeTelegram
from jerico.crm import repo, retention
from jerico.crm.config import default_params
from jerico.crm.db import CrmDatabase
from jerico.crm.files import LocalFileStore
from jerico.crm.fingerprint import fingerprint
from jerico.crm.model import AuditAction, AuditDetail, AuthStatus, Channel, LeadState, Role, User
from jerico.crm.outbox import SUPPRESSION_KIND
from jerico.crm.render import short_id
from jerico.crm.timeutil import add_months, add_years, to_iso

START = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
CTO_TG = 1000
COM_TG = 2000
LAW_TG = 3000
KEY = "clave-actual"
PHONE = "+573001234567"
NAME = "Zuleima Centinela"
PARAMS = default_params()


class FlakyStore(LocalFileStore):
    """Almacén cuyo borrado falla mientras `broken` sea verdadero."""

    broken = False

    def delete(self, storage_key: str) -> None:
        if self.broken:
            raise OSError("disco no disponible")
        super().delete(storage_key)


@pytest.fixture
def db(tmp_path: Path) -> Iterator[CrmDatabase]:
    database = CrmDatabase(tmp_path / "crm.db")
    yield database
    database.close()


@pytest.fixture
def tg() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def store(tmp_path: Path) -> FlakyStore:
    return FlakyStore(tmp_path / "files")


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


def _lead(db: CrmDatabase, owner: int | None, state: LeadState, **cols: Any) -> int:
    with db.tx() as tx:
        lead_id = repo.insert_lead(
            tx,
            assigned_user_id=owner,
            state=state,
            now=START,
            fields={"name": NAME, "phone_e164": PHONE},
        )
        for column, value in cols.items():
            if isinstance(value, datetime):
                value = to_iso(value)
            # Columnas fijas del test.
            tx.execute(f"UPDATE crm_leads SET {column} = ? WHERE id = ?", (value, lead_id))  # noqa: S608
    return lead_id


def _attach(db: CrmDatabase, store: LocalFileStore, lead_id: int, author: int, kind: str) -> str:
    tmp = store.new_tmp_path(".bin")
    tmp.write_bytes(kind.encode())
    key = store.save_atomic(lead_id, tmp)
    with db.tx() as tx:
        repo.insert_attachment(
            tx,
            lead_id=lead_id,
            kind=kind,
            author_user_id=author,
            at=START,
            storage_key=key,
            size_bytes=4,
            sha256="0" * 64,
        )
    return key


def _sweep(db: CrmDatabase, tg: FakeTelegram, store: LocalFileStore, now: datetime) -> None:
    asyncio.run(retention.daily_sweep(db, tg, now, PARAMS, store=store, keys=(KEY,)))


def _get(db: CrmDatabase, lead_id: int) -> Any:
    with db.read() as conn:
        lead = repo.get_lead(conn, lead_id)
    assert lead is not None
    return lead


def _texts(tg: FakeTelegram, chat: int) -> list[str]:
    return [s.text for s in tg.sent if s.chat_id == chat]


def _suppression_outbox(db: CrmDatabase) -> list[sqlite3.Row]:
    with db.read() as conn:
        return conn.execute(
            "SELECT * FROM crm_outbox WHERE kind = ?", (SUPPRESSION_KIND,)
        ).fetchall()


def _audits(db: CrmDatabase, action: AuditAction) -> list[dict[str, Any]]:
    with db.read() as conn:
        return [r for r in repo.audit_rows(conn) if r["action"] == action.value]


def _suppressed_fp(db: CrmDatabase) -> bool:
    with db.read() as conn:
        return repo.any_suppressed(conn, [fingerprint(KEY, PHONE)])


# --- J-14 ---------------------------------------------------------------------------------


def test_vcrm158_warns_once_at_25_days_with_id_name_and_date(
    db: CrmDatabase, tg: FakeTelegram, store: FlakyStore, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id, LeadState.CONTACTADO)
    _sweep(db, tg, store, START + timedelta(days=24))
    assert _texts(tg, COM_TG) == []
    day25 = START + timedelta(days=25)
    _sweep(db, tg, store, day25)
    _sweep(db, tg, store, day25 + timedelta(hours=2))
    _sweep(db, tg, store, day25 + timedelta(days=1))
    texts = _texts(tg, COM_TG)
    assert len(texts) == 1
    assert short_id(lead_id) in texts[0] and NAME in texts[0]
    assert "01/04/2026" in texts[0]  # registro + 30 días, fecha local
    assert _texts(tg, CTO_TG) == []
    assert _get(db, lead_id).suppressed_at is None


def test_vcrm158_warning_goes_to_cto_without_commercial(
    db: CrmDatabase, tg: FakeTelegram, store: FlakyStore, users: dict[str, User]
) -> None:
    lead_id = _lead(db, None, LeadState.NUEVO)
    _sweep(db, tg, store, START + timedelta(days=25))
    texts = _texts(tg, CTO_TG)
    assert len(texts) == 1 and short_id(lead_id) in texts[0]


def test_vcrm159_suppresses_at_30_days_without_fingerprint(
    db: CrmDatabase, tg: FakeTelegram, store: FlakyStore, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id, LeadState.CONTACTADO)
    photo = _attach(db, store, lead_id, users["com"].id, "photo")
    day30 = START + timedelta(days=30)
    _sweep(db, tg, store, day30)
    lead = _get(db, lead_id)
    assert lead.suppressed_at == to_iso(day30)
    assert lead.name is None and lead.phone_e164 is None
    assert not (store.base_dir / photo).exists()
    assert not _suppressed_fp(db)
    for chat in (COM_TG, CTO_TG):
        texts = _texts(tg, chat)
        assert len(texts) == 1 and short_id(lead_id) in texts[0]
        assert NAME not in texts[0]
    outbox = _suppression_outbox(db)
    assert [(r["recipient_user_id"], r["channel"]) for r in outbox] == [
        (users["cto"].id, Channel.TELEGRAM.value)
    ]
    audits = _audits(db, AuditAction.LEAD_SUPPRESSED)
    assert [(a["lead_id"], a["detail_code"]) for a in audits] == [
        (lead_id, AuditDetail.VENCIMIENTO_PLAZO.value)
    ]
    _sweep(db, tg, store, day30 + timedelta(hours=3))
    assert len(_audits(db, AuditAction.LEAD_SUPPRESSED)) == 1
    assert len(_suppression_outbox(db)) == 1
    assert len(_texts(tg, CTO_TG)) == 1


def test_vcrm159_authorized_before_deadline_is_not_suppressed(
    db: CrmDatabase, tg: FakeTelegram, store: FlakyStore, users: dict[str, User]
) -> None:
    lead_id = _lead(
        db, users["com"].id, LeadState.CONTACTADO, auth_status=AuthStatus.AUTORIZADA.value
    )
    _sweep(db, tg, store, START + timedelta(days=40))
    assert _get(db, lead_id).suppressed_at is None
    assert tg.sent == []


@pytest.mark.parametrize("state", [LeadState.ACEPTADO, LeadState.GANADO])
def test_vcrm159_clock_stopped_in_accepted_or_won(
    db: CrmDatabase,
    tg: FakeTelegram,
    store: FlakyStore,
    users: dict[str, User],
    state: LeadState,
) -> None:
    lead_id = _lead(db, users["com"].id, state)
    _sweep(db, tg, store, START + timedelta(days=60))
    assert _get(db, lead_id).suppressed_at is None
    assert tg.sent == []


def test_vcrm159_clock_restarts_on_leaving_accepted(
    db: CrmDatabase, tg: FakeTelegram, store: FlakyStore, users: dict[str, User]
) -> None:
    exit_at = START + timedelta(days=50)
    lead_id = _lead(
        db, users["com"].id, LeadState.RECHAZADO, accepted_exit_at=exit_at, ever_accepted=1
    )
    _sweep(db, tg, store, exit_at + timedelta(days=29))
    assert _get(db, lead_id).suppressed_at is None
    assert len(_texts(tg, COM_TG)) == 1  # aviso a los 25 días del reinicio
    _sweep(db, tg, store, exit_at + timedelta(days=30))
    assert _get(db, lead_id).suppressed_at is not None
    lawyer = [r for r in _suppression_outbox(db) if r["recipient_user_id"] == users["law"].id]
    assert {r["channel"] for r in lawyer} == {Channel.TELEGRAM.value, Channel.EMAIL.value}


# --- VCRM-146 / 164 -----------------------------------------------------------------------


@pytest.mark.parametrize(("state", "with_fp"), [(LeadState.PERDIDO, False), (LeadState.BAJA, True)])
def test_vcrm146_vcrm164_final_state_suppressed_at_12_months_keeping_evidence(
    db: CrmDatabase,
    tg: FakeTelegram,
    store: FlakyStore,
    users: dict[str, User],
    state: LeadState,
    with_fp: bool,
) -> None:
    final_at = START + timedelta(days=5)
    lead_id = _lead(
        db,
        users["com"].id,
        state,
        final_state_at=final_at,
        auth_status=AuthStatus.AUTORIZADA.value,
    )
    photo = _attach(db, store, lead_id, users["com"].id, "photo")
    evidence = _attach(db, store, lead_id, users["com"].id, "authorization")
    deadline = add_months(final_at, 12)
    _sweep(db, tg, store, deadline - timedelta(minutes=1))
    assert _get(db, lead_id).suppressed_at is None
    _sweep(db, tg, store, deadline)
    lead = _get(db, lead_id)
    assert lead.suppressed_at == to_iso(deadline) and lead.name is None
    assert _suppressed_fp(db) is with_fp
    assert not (store.base_dir / photo).exists()
    assert (store.base_dir / evidence).exists()  # VCRM-164
    with db.read() as conn:
        assert [a.kind for a in repo.lead_attachments(conn, lead_id)] == ["authorization"]
    assert len(_suppression_outbox(db)) == 1
    assert [a["detail_code"] for a in _audits(db, AuditAction.LEAD_SUPPRESSED)] == [
        AuditDetail.VENCIMIENTO_PLAZO.value
    ]
    _sweep(db, tg, store, deadline + timedelta(hours=1))
    assert len(_audits(db, AuditAction.LEAD_SUPPRESSED)) == 1


# --- VCRM-145 -----------------------------------------------------------------------------


def test_vcrm145_won_then_baja_keeps_attachments_until_10_years(
    db: CrmDatabase, tg: FakeTelegram, store: FlakyStore, users: dict[str, User]
) -> None:
    won_at = START + timedelta(days=10)
    final_at = START + timedelta(days=100)
    lead_id = _lead(
        db,
        users["com"].id,
        LeadState.BAJA,
        won_at=won_at,
        final_state_at=final_at,
        auth_status=AuthStatus.AUTORIZADA.value,
        ever_accepted=1,
    )
    photo = _attach(db, store, lead_id, users["com"].id, "photo")
    evidence = _attach(db, store, lead_id, users["com"].id, "authorization")
    _sweep(db, tg, store, add_months(final_at, 12))
    assert _get(db, lead_id).suppressed_at is not None
    assert (store.base_dir / photo).exists()
    ten = add_years(won_at, 10)
    _sweep(db, tg, store, ten - timedelta(minutes=1))
    assert (store.base_dir / photo).exists()
    _sweep(db, tg, store, ten)
    _sweep(db, tg, store, ten + timedelta(hours=1))
    assert not (store.base_dir / photo).exists()
    assert (store.base_dir / evidence).exists()  # VCRM-164
    with db.read() as conn:
        assert [a.kind for a in repo.lead_attachments(conn, lead_id)] == ["authorization"]
    expired = _audits(db, AuditAction.ATTACHMENT_EXPIRED)
    assert [a["lead_id"] for a in expired] == [lead_id]


def test_vcrm145_won_lead_attachments_expire_after_10_years(
    db: CrmDatabase, tg: FakeTelegram, store: FlakyStore, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id, LeadState.GANADO, won_at=START)
    photo = _attach(db, store, lead_id, users["com"].id, "photo")
    _sweep(db, tg, store, add_years(START, 10))
    assert not (store.base_dir / photo).exists()
    assert _get(db, lead_id).suppressed_at is None


# --- VCRM-147 -----------------------------------------------------------------------------


def test_vcrm147_failed_suppression_alerts_cto_and_retries(
    db: CrmDatabase, tg: FakeTelegram, store: FlakyStore, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id, LeadState.CONTACTADO)
    photo = _attach(db, store, lead_id, users["com"].id, "photo")
    store.broken = True
    day30 = START + timedelta(days=30)
    _sweep(db, tg, store, day30)
    _sweep(db, tg, store, day30 + timedelta(hours=1))
    lead = _get(db, lead_id)
    assert lead.suppressed_at is None and lead.name == NAME
    cto = _texts(tg, CTO_TG)
    assert len(cto) == 1 and short_id(lead_id) in cto[0] and "disco no disponible" in cto[0]
    assert _suppression_outbox(db) == []
    store.broken = False
    _sweep(db, tg, store, day30 + timedelta(days=1))
    assert _get(db, lead_id).suppressed_at is not None
    assert not (store.base_dir / photo).exists()


def test_vcrm147_failed_attachment_expiry_alerts_and_retries(
    db: CrmDatabase, tg: FakeTelegram, store: FlakyStore, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id, LeadState.GANADO, won_at=START)
    photo = _attach(db, store, lead_id, users["com"].id, "photo")
    store.broken = True
    ten = add_years(START, 10)
    _sweep(db, tg, store, ten)
    assert (store.base_dir / photo).exists()
    assert len(_texts(tg, CTO_TG)) == 1
    assert _audits(db, AuditAction.ATTACHMENT_EXPIRED) == []
    store.broken = False
    _sweep(db, tg, store, ten + timedelta(days=1))
    assert not (store.base_dir / photo).exists()
    assert len(_audits(db, AuditAction.ATTACHMENT_EXPIRED)) == 1
