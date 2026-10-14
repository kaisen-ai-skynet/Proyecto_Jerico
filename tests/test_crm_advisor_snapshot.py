"""Pruebas unitarias para advisor_snapshot (spec 007, CRM-consejero).

Requisitos: VJC-003 a 010, VJC-021 a 024.
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from jerico.crm.advisor_snapshot import run_snapshot
from jerico.crm.advisor_state import lead_ref
from jerico.crm.db import CrmDatabase
from jerico.crm.model import LeadState
from jerico.crm.repo import insert_lead, update_lead
from jerico.shadowlog.jsonl import DailyJsonlWriter

BOGOTA = ZoneInfo("America/Bogota")


def _dump_db(db_path: Path) -> bytes:
    con = sqlite3.connect(str(db_path))
    dump_lines = list(con.iterdump())
    con.close()
    return "\n".join(dump_lines).encode("utf-8")


def test_snapshot_eligible_leads_and_idempotency(tmp_path: Path) -> None:
    db_path = tmp_path / "crm_test.db"
    db = CrmDatabase(db_path)
    snapshot_dir = tmp_path / "snapshots"
    writer = DailyJsonlWriter(snapshot_dir)
    key = "secret-key-1"

    now_dt = datetime(2026, 10, 14, 12, 0, 0, tzinfo=BOGOTA)
    now_utc = now_dt.astimezone(UTC)

    with db.tx() as tx:
        insert_lead(
            tx,
            assigned_user_id=None,
            state=LeadState.NEW,
            now=now_utc,
            fields={"name": "Lead 1", "phone_e164": "+573001111111"},
        )
        insert_lead(
            tx,
            assigned_user_id=None,
            state=LeadState.WON,  # estado final sí es elegible
            now=now_utc,
            fields={"name": "Lead 2", "phone_e164": "+573002222222"},
        )
        insert_lead(
            tx,
            assigned_user_id=None,
            state=LeadState.OPTED_OUT,  # no elegible
            now=now_utc,
            fields={"name": "Lead 3", "phone_e164": "+573003333333"},
        )

    dump_before = _dump_db(db_path)

    report = run_snapshot(db, writer, key=key, clock=lambda: now_dt.timestamp())
    assert report.success is True
    assert report.eligible_count == 2
    assert report.written_count == 2
    assert report.omitted_count == 0

    # Base queda 100% idéntica (VJC-005)
    dump_after = _dump_db(db_path)
    assert dump_before == dump_after

    # Segunda corrida en el mismo día no duplica (VJC-004)
    report2 = run_snapshot(db, writer, key=key, clock=lambda: now_dt.timestamp())
    assert report2.written_count == 0
    records = writer.read_day("2026-10-14")
    assert len(records) == 2


def test_snapshot_withdrawals_on_suppression_and_key_change(tmp_path: Path) -> None:
    db_path = tmp_path / "crm_test.db"
    db = CrmDatabase(db_path)
    snapshot_dir = tmp_path / "snapshots"
    writer = DailyJsonlWriter(snapshot_dir)
    key1 = "secret-key-1"

    dt_day1 = datetime(2026, 10, 13, 12, 0, 0, tzinfo=BOGOTA)
    with db.tx() as tx:
        l1 = insert_lead(
            tx,
            assigned_user_id=None,
            state=LeadState.NEW,
            now=dt_day1.astimezone(UTC),
            fields={"name": "Lead 1", "phone_e164": "+573001111111"},
        )
        l2 = insert_lead(
            tx,
            assigned_user_id=None,
            state=LeadState.NEW,
            now=dt_day1.astimezone(UTC),
            fields={"name": "Lead 2", "phone_e164": "+573002222222"},
        )

    run_snapshot(db, writer, key=key1, clock=lambda: dt_day1.timestamp())
    assert len(writer.read_day("2026-10-13")) == 2

    # Día 2: l1 es suprimido
    dt_day2 = datetime(2026, 10, 14, 12, 0, 0, tzinfo=BOGOTA)
    with db.tx() as tx:
        update_lead(
            tx,
            l1,
            {
                "suppressed_at": dt_day2.astimezone(UTC).isoformat(),
                "suppression_cause": "orden_cto",
            },
            now=dt_day2.astimezone(UTC),
        )

    report_day2 = run_snapshot(db, writer, key=key1, clock=lambda: dt_day2.timestamp())
    assert report_day2.withdrawals_count == 1

    # Líneas de l1 fueron eliminadas de 2026-10-13 (VJC-022)
    records_13 = writer.read_day("2026-10-13")
    assert len(records_13) == 1
    assert records_13[0]["lead_ref"] == lead_ref(l2, key1)

    # Archivo de retiros contiene la referencia de l1 (VJC-024)
    withdrawals_writer = DailyJsonlWriter(snapshot_dir, prefix="retiros-")
    ret_records = withdrawals_writer.read_day("2026-10-14")
    assert len(ret_records) == 1
    assert ret_records[0]["lead_ref"] == lead_ref(l1, key1)
    assert ret_records[0]["withdrawal_day"] == "2026-10-14"

    # Cambio de clave: retira las líneas de la clave anterior (VJC-022)
    key2 = "new-secret-key-2"
    report_day2_rekey = run_snapshot(db, writer, key=key2, clock=lambda: dt_day2.timestamp())
    assert report_day2_rekey.withdrawals_count == 1  # l2 con key1 retirado
    assert len(writer.read_day("2026-10-13")) == 0


def test_zero_eligible_leads_does_not_write_but_purges(tmp_path: Path) -> None:
    db = CrmDatabase(tmp_path / "crm_empty.db")
    snapshot_dir = tmp_path / "snapshots"
    writer = DailyJsonlWriter(snapshot_dir)

    now_dt = datetime(2026, 10, 14, 12, 0, 0, tzinfo=BOGOTA)
    report = run_snapshot(db, writer, key="test-key", clock=lambda: now_dt.timestamp())

    assert report.eligible_count == 0
    assert report.written_count == 0
    assert not (snapshot_dir / "2026-10-14.jsonl").exists()


def test_read_failure_does_not_write(tmp_path: Path) -> None:
    db = CrmDatabase(tmp_path / "crm_test.db")
    snapshot_dir = tmp_path / "snapshots"
    writer = DailyJsonlWriter(snapshot_dir)

    now_dt = datetime(2026, 10, 14, 12, 0, 0, tzinfo=BOGOTA)
    with patch("jerico.crm.advisor_snapshot.load_context", side_effect=OSError("Read error")):
        report = run_snapshot(db, writer, key="test-key", clock=lambda: now_dt.timestamp())
        assert report.success is False
        assert not (snapshot_dir / "2026-10-14.jsonl").exists()
