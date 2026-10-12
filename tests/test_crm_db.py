"""T03 — Base propia del CRM, esquema y bitácora sin datos personales."""

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jerico.crm import repo
from jerico.crm.db import SCHEMA_SQL, SCHEMA_VERSION, CrmDatabase
from jerico.crm.model import (
    AlertKind,
    AuditAction,
    AuditDetail,
    AuditOutcome,
    EventKind,
    LeadState,
    Role,
)

NOW = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 6, 9, 30, tzinfo=UTC)

TITULAR = {
    "name": "Ana Pérez Gómez",
    "phone_e164": "+573001234567",
    "email": "ana.perez@example.com",
    "company": "Ferretería La Esquina",
    "doc_type": "CC",
    "doc_number": "1020304050",
}


def _open(tmp_path: Path) -> CrmDatabase:
    return CrmDatabase(tmp_path / "crm.db")


def _seed(db: CrmDatabase) -> tuple[int, int]:
    with db.tx() as conn:
        user = repo.insert_user(
            conn, telegram_id=111, role=Role.COMMERCIAL, email="c@kaisen.ai", now=NOW
        )
        lead_id = repo.insert_lead(
            conn, assigned_user_id=user.id, state=LeadState.NEW, now=NOW, fields=TITULAR
        )
    return user.id, lead_id


# --- VCRM-078: base propia, WAL, esquema y persistencia ---------------------------------


def test_vcrm078_wal_active_and_schema_version_in_meta(tmp_path: Path) -> None:
    db = _open(tmp_path)
    with db.read() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert repo.get_meta(conn, "schema_version") == "2"
    assert SCHEMA_VERSION == 2
    db.close()


def test_vcrm078_reopen_is_idempotent_and_rejects_other_schema_version(tmp_path: Path) -> None:
    _open(tmp_path).close()
    db = _open(tmp_path)
    with db.tx() as conn:
        repo.set_meta(conn, "schema_version", "99")
    db.close()
    with pytest.raises(RuntimeError, match="schema_version"):
        _open(tmp_path)


def test_vcrm078_tx_rolls_back_on_exception(tmp_path: Path) -> None:
    db = _open(tmp_path)
    with pytest.raises(ValueError, match="boom"), db.tx() as conn:
        repo.set_meta(conn, "telegram_offset", "42")
        raise ValueError("boom")
    with db.read() as conn:
        assert repo.get_meta(conn, "telegram_offset") is None
    db.close()


def test_vcrm078_committed_data_survives_close_and_reopen(tmp_path: Path) -> None:
    db = _open(tmp_path)
    user_id, lead_id = _seed(db)
    with db.tx() as conn:
        repo.update_lead(conn, lead_id, {"state": LeadState.CONTACTED.value}, now=LATER)
        repo.add_event(
            conn,
            lead_id=lead_id,
            kind=EventKind.STATE,
            actor_user_id=user_id,
            at=LATER,
            old_value=LeadState.NEW.value,
            new_value=LeadState.CONTACTED.value,
        )
        repo.set_meta(conn, "telegram_offset", "7")
    db.close()

    db = _open(tmp_path)
    with db.read() as conn:
        lead = repo.get_lead(conn, lead_id)
        assert lead is not None
        assert lead.state == LeadState.CONTACTED.value
        assert lead.name == TITULAR["name"]
        assert lead.assigned_user_id == user_id
        assert lead.last_interaction_at == "2026-10-06T09:30:00Z"
        events = repo.lead_events(conn, lead_id)
        assert [(e.kind, e.old_value, e.new_value) for e in events] == [
            ("state", "new", "contacted")
        ]
        assert repo.get_meta(conn, "telegram_offset") == "7"
        user = repo.active_user_by_telegram(conn, 111)
        assert user is not None and user.role == Role.COMMERCIAL.value
    db.close()


def test_vcrm078_users_active_lookup_and_deactivation(tmp_path: Path) -> None:
    db = _open(tmp_path)
    with db.tx() as conn:
        user = repo.insert_user(conn, telegram_id=5, role=Role.CTO, email="cto@k.ai", now=NOW)
        assert repo.get_user(conn, user.id) == user
        assert repo.get_user(conn, 999) is None
        assert repo.active_users(conn, role=Role.CTO) == [user]
        assert repo.deactivate_user(conn, user.id, now=LATER) is True
        assert repo.deactivate_user(conn, user.id, now=LATER) is False
        assert repo.active_user_by_telegram(conn, 5) is None
        assert repo.active_users(conn) == []
    db.close()


def test_vcrm078_update_lead_rejects_unknown_column(tmp_path: Path) -> None:
    db = _open(tmp_path)
    _, lead_id = _seed(db)
    with pytest.raises(ValueError, match="columna"), db.tx() as conn:
        repo.update_lead(conn, lead_id, {"id; DROP TABLE crm_leads": 1}, now=LATER)
    with pytest.raises(ValueError, match="columna"), db.tx() as conn:
        repo.insert_lead(
            conn, assigned_user_id=None, state=LeadState.NEW, now=NOW, fields={"bogus": "x"}
        )
    with db.read() as conn:
        assert repo.get_lead(conn, 999) is None
    db.close()


def test_vcrm078_ddl_is_portable_text(tmp_path: Path) -> None:
    upper = SCHEMA_SQL.upper()
    assert "INSERT OR IGNORE" not in upper
    assert "AUTOINCREMENT" not in upper
    assert "USER_VERSION" not in upper
    assert "FTS5" not in upper
    assert "CREATE TABLE IF NOT EXISTS CRM_META" in upper


# --- VCRM-075 / VCRM-096: bitácora con códigos cerrados y sin datos del titular ----------


def test_vcrm075_audit_records_actor_action_lead_and_time(tmp_path: Path) -> None:
    db = _open(tmp_path)
    user_id, lead_id = _seed(db)
    with db.tx() as conn:
        for action in (
            AuditAction.LEAD_CREATED,
            AuditAction.LEAD_UPDATED,
            AuditAction.LEAD_EXPORTED,
            AuditAction.LEAD_SUPPRESSED,
        ):
            repo.audit(
                conn,
                actor=f"user:{user_id}",
                action=action,
                outcome=AuditOutcome.OK,
                at=NOW,
                lead_id=lead_id,
            )
        repo.audit(
            conn,
            actor="tg:999",
            action=AuditAction.ACCESS_DENIED,
            outcome=AuditOutcome.DENIED,
            at=NOW,
            detail=AuditDetail.MESSAGE,
        )
    with db.read() as conn:
        rows = repo.audit_rows(conn)
    assert [r["action"] for r in rows] == [
        "lead_created",
        "lead_updated",
        "lead_exported",
        "lead_suppressed",
        "access_denied",
    ]
    assert rows[0]["actor"] == f"user:{user_id}"
    assert rows[0]["lead_id"] == lead_id
    assert rows[0]["at"] == "2026-10-05T15:00:00Z"
    assert rows[-1]["detail_code"] == "message"
    assert rows[-1]["lead_id"] is None
    db.close()


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"action": "lead_created"}, TypeError),
        ({"action": "Ana Pérez llamó"}, TypeError),
        ({"outcome": "ok"}, TypeError),
        ({"detail": "teléfono +573001234567"}, TypeError),
        ({"actor": "Ana Pérez"}, ValueError),
        ({"actor": "user:abc"}, ValueError),
    ],
)
def test_vcrm096_audit_rejects_free_text(
    tmp_path: Path, kwargs: dict[str, object], error: type[Exception]
) -> None:
    db = _open(tmp_path)
    base: dict[str, object] = {
        "actor": "system",
        "action": AuditAction.LEAD_CREATED,
        "outcome": AuditOutcome.OK,
        "at": NOW,
    }
    with pytest.raises(error), db.tx() as conn:
        repo.audit(conn, **{**base, **kwargs})  # type: ignore[arg-type]
    with db.read() as conn:
        assert repo.audit_rows(conn) == []
    db.close()


def test_vcrm096_audit_table_has_no_titular_columns_nor_titular_data(tmp_path: Path) -> None:
    db = _open(tmp_path)
    user_id, lead_id = _seed(db)
    with db.tx() as conn:
        repo.audit(
            conn,
            actor=f"user:{user_id}",
            action=AuditAction.LEAD_CREATED,
            outcome=AuditOutcome.OK,
            at=NOW,
            lead_id=lead_id,
        )
    with db.read() as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(crm_audit)")}
        dump = " ".join(str(v) for r in repo.audit_rows(conn) for v in r.values())
    assert columns == {"id", "at", "actor", "action", "lead_id", "outcome", "detail_code"}
    for value in TITULAR.values():
        assert value not in dump
    db.close()


# --- Alertas persistentes (VCRM-087, 152, 155) ------------------------------------------


def test_vcrm087_alert_open_per_lead_and_for_cto_then_resolved_once(tmp_path: Path) -> None:
    db = _open(tmp_path)
    user_id, lead_id = _seed(db)
    with db.tx() as conn:
        alert_id = repo.create_alert(
            conn, kind=AlertKind.NOTIFICATION_FAILED, now=NOW, lead_id=lead_id, outbox_id=3
        )
        other = repo.create_alert(conn, kind=AlertKind.REQUEST_OVERDUE, now=NOW, request_id=8)
    with db.read() as conn:
        by_lead = repo.open_alerts(conn, lead_id=lead_id)
        for_cto = repo.open_alerts(conn)
    assert [a.id for a in by_lead] == [alert_id]
    assert by_lead[0].kind == "notification_failed"
    assert by_lead[0].outbox_id == 3
    assert [a.id for a in for_cto] == [alert_id, other]

    with db.tx() as conn:
        assert repo.resolve_alert(conn, alert_id, resolved_by=user_id, now=LATER) is True
        assert repo.resolve_alert(conn, alert_id, resolved_by=999, now=NOW) is False
        assert repo.resolve_alert(conn, 12345, resolved_by=user_id, now=NOW) is False
    with db.read() as conn:
        assert repo.open_alerts(conn, lead_id=lead_id) == []
        assert [a.id for a in repo.open_alerts(conn)] == [other]
        row = conn.execute(
            "SELECT resolved_by, resolved_at FROM crm_alerts WHERE id = ?", (alert_id,)
        ).fetchone()
        assert tuple(row) == (user_id, "2026-10-06T09:30:00Z")
        assert conn.execute("SELECT COUNT(*) FROM crm_alerts").fetchone()[0] == 2
    db.close()


def test_vcrm078_create_alert_rejects_unknown_kind(tmp_path: Path) -> None:
    db = _open(tmp_path)
    with pytest.raises(TypeError), db.tx() as conn:
        repo.create_alert(conn, kind="free text", now=NOW)  # type: ignore[arg-type]
    db.close()


def test_vcrm078_closed_database_refuses_use(tmp_path: Path) -> None:
    db = _open(tmp_path)
    db.close()
    db.close()
    with pytest.raises(RuntimeError), db.tx():
        pass
    with pytest.raises(RuntimeError), db.read():
        pass


def test_vcrm078_ddl_only_uses_named_tables(tmp_path: Path) -> None:
    db = _open(tmp_path)
    with db.read() as conn:
        names = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            if isinstance(r[0], str)
        }
    assert all(re.fullmatch(r"crm_[a-z_]+", n) for n in names)
    assert {"crm_meta", "crm_users", "crm_leads", "crm_lead_events", "crm_alerts"} <= names
    db.close()
