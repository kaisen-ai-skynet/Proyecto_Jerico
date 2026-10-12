"""T03 — Base propia del CRM, esquema y bitácora sin datos personales."""

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crm_support import V1_LEAD_ROWS, build_v1_database
from jerico.crm import repo
from jerico.crm.db import SCHEMA_SQL, SCHEMA_VERSION, CrmDatabase
from jerico.crm.migrate import STATE_MAP, MigrationError
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


# --- Migración v1 → v2 al abrir (F2-T04, VCRM-171) -------------------------------------------


def _raw(path: Path, sql: str) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return [tuple(r) for r in conn.execute(sql).fetchall()]
    finally:
        conn.close()


def test_vcrm171_abrir_base_v1_migra_y_conserva_datos(tmp_path: Path) -> None:
    path = tmp_path / "crm.db"
    build_v1_database(path)

    db = CrmDatabase(path)
    with db.read() as conn:
        assert repo.get_meta(conn, "schema_version") == "2"
        states = dict(conn.execute("SELECT id, state FROM crm_leads").fetchall())
    db.close()

    assert states == {i: STATE_MAP[state] for i, state, _ in V1_LEAD_ROWS}
    assert path.with_name(path.name + ".pre-v2.bak").exists()
    # Una segunda apertura ya es v2: no migra ni vuelve a copiar.
    CrmDatabase(path).close()


def test_vcrm171_falla_migracion_deja_v1_y_no_arranca(tmp_path: Path) -> None:
    path = tmp_path / "crm.db"
    build_v1_database(path)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE crm_leads SET state = 'zombi' WHERE id = 3")
    conn.commit()
    conn.close()

    with pytest.raises(MigrationError, match="zombi"):
        CrmDatabase(path)

    assert _raw(path, "SELECT value FROM crm_meta WHERE key = 'schema_version'") == [("1",)]
    assert _raw(path, "SELECT state FROM crm_leads WHERE id = 3") == [("zombi",)]


def _schema(path: Path) -> dict[str, object]:
    check = re.compile(r"CHECK\s*\((?:[^()]|\([^()]*\))*\)")
    out: dict[str, object] = {}
    for (table,) in _raw(
        path, "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'crm_%'"
    ):
        columns = [r[1:] for r in _raw(path, f"PRAGMA table_info({table})")]  # noqa: S608
        sql = _raw(path, f"SELECT sql FROM sqlite_master WHERE name = '{table}'")[0][0]  # noqa: S608
        checks = sorted(" ".join(c.split()) for c in check.findall(sql))
        out[table] = (columns, checks)
    indexes = {}
    for (name,) in _raw(
        path, "SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE '%ix_%'"
    ):
        indexes[name] = [r[2] for r in _raw(path, f"PRAGMA index_info({name})")]  # noqa: S608
    out["__indexes__"] = indexes
    return out


def test_vcrm171_esquema_migrado_igual_al_de_una_base_nueva(tmp_path: Path) -> None:
    fresh = tmp_path / "fresh.db"
    CrmDatabase(fresh).close()
    migrated = tmp_path / "migrated.db"
    build_v1_database(migrated)
    CrmDatabase(migrated).close()

    assert _schema(migrated) == _schema(fresh)


# --- Restricciones y persistencia F2 (F2-T10, VCRM-028, VCRM-169) ---------------------------


def test_vcrm028_unica_propuesta_por_lead_y_paso(tmp_path: Path) -> None:
    db = _open(tmp_path)
    user_id, lead_id = _seed(db)
    with db.tx() as conn:
        conn.execute(
            """INSERT INTO crm_proposals (
                lead_id, kind, step, status, approver_user_id, expires_at, created_at
            ) VALUES (?, 'followup', 1, 'pending', ?,
                      '2026-10-10T00:00:00Z', '2026-10-08T00:00:00Z')""",
            (lead_id, user_id),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO crm_proposals (
                    lead_id, kind, step, status, approver_user_id, expires_at, created_at
                ) VALUES (?, 'followup', 1, 'pending', ?,
                          '2026-10-10T00:00:00Z', '2026-10-08T00:00:00Z')""",
                (lead_id, user_id),
            )
        # Paso distinto en el mismo lead sí se admite
        conn.execute(
            """INSERT INTO crm_proposals (
                lead_id, kind, step, status, approver_user_id, expires_at, created_at
            ) VALUES (?, 'followup', 2, 'pending', ?,
                      '2026-10-10T00:00:00Z', '2026-10-08T00:00:00Z')""",
            (lead_id, user_id),
        )
    db.close()


def test_vcrm169_unico_message_id(tmp_path: Path) -> None:
    db = _open(tmp_path)
    with db.tx() as conn:
        conn.execute(
            """INSERT INTO crm_inbound (
                rfc_message_id, uid, received_at, sender_fp, lead_id,
                association, classification, new_text, decision
            ) VALUES (?, 1, '2026-10-08T00:00:00Z', 'fp1', NULL,
                      'none', 'review', 'hola', 'pending')""",
            ("<unique-123@domain.com>",),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO crm_inbound (
                    rfc_message_id, uid, received_at, sender_fp, lead_id,
                    association, classification, new_text, decision
                ) VALUES (?, 2, '2026-10-08T01:00:00Z', 'fp2', NULL,
                          'none', 'review', 'hola 2', 'pending')""",
                ("<unique-123@domain.com>",),
            )
    db.close()


def test_vcrm028_una_solicitud_de_autorizacion_abierta(tmp_path: Path) -> None:
    db = _open(tmp_path)
    user_id, lead_id = _seed(db)
    with db.tx() as conn:
        # Primera solicitud abierta (pending)
        cur = conn.execute(
            """INSERT INTO crm_proposals (
                lead_id, kind, step, status, approver_user_id, expires_at, created_at
            ) VALUES (?, 'auth_request', NULL, 'pending', ?,
                      '2026-10-10T00:00:00Z', '2026-10-08T00:00:00Z')""",
            (lead_id, user_id),
        )
        p1_id = cur.lastrowid
        # Segunda solicitud abierta (pending) falla por el índice único parcial
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO crm_proposals (
                    lead_id, kind, step, status, approver_user_id, expires_at, created_at
                ) VALUES (?, 'auth_request', NULL, 'pending', ?,
                          '2026-10-10T00:00:00Z', '2026-10-08T00:00:00Z')""",
                (lead_id, user_id),
            )
        # Segunda solicitud abierta (approved) también falla
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO crm_proposals (
                    lead_id, kind, step, status, approver_user_id, expires_at, created_at
                ) VALUES (?, 'auth_request', NULL, 'approved', ?,
                          '2026-10-10T00:00:00Z', '2026-10-08T00:00:00Z')""",
                (lead_id, user_id),
            )
        # Al resolver la primera (sent), ya se admite una nueva solicitud
        conn.execute("UPDATE crm_proposals SET status = 'sent' WHERE id = ?", (p1_id,))
        conn.execute(
            """INSERT INTO crm_proposals (
                lead_id, kind, step, status, approver_user_id, expires_at, created_at
            ) VALUES (?, 'auth_request', NULL, 'pending', ?,
                      '2026-10-11T00:00:00Z', '2026-10-09T00:00:00Z')""",
            (lead_id, user_id),
        )
    db.close()


def test_f2_tablas_ida_y_vuelta_y_foreign_keys(tmp_path: Path) -> None:
    db = _open(tmp_path)
    user_id, lead_id = _seed(db)
    with db.tx() as conn:
        # 1. crm_cadences
        conn.execute(
            """INSERT INTO crm_cadences (
                lead_id, reason, interval_days, total_steps, steps_done, sent_count,
                next_action_at, last_sent_at, status, started_at, updated_at
            ) VALUES (?, 'precio', 30, 3, 0, 0, '2026-11-05T15:00:00Z', NULL,
                      'active', '2026-10-05T15:00:00Z', '2026-10-05T15:00:00Z')""",
            (lead_id,),
        )
        cad_row = conn.execute(
            "SELECT * FROM crm_cadences WHERE lead_id = ?", (lead_id,)
        ).fetchone()
        assert cad_row["reason"] == "precio"
        assert cad_row["status"] == "active"

        # 2. crm_inbound
        cur = conn.execute(
            """INSERT INTO crm_inbound (
                rfc_message_id, uid, received_at, sender_fp, lead_id,
                association, classification, new_text, decision, decided_by, decided_at
            ) VALUES ('<inbound@msg>', 42, '2026-10-05T15:30:00Z', 'fp_abc', ?,
                      'thread', 'auth_candidate', 'ok', 'pending', NULL, NULL)""",
            (lead_id,),
        )
        inbound_id = cur.lastrowid
        inb_row = conn.execute("SELECT * FROM crm_inbound WHERE id = ?", (inbound_id,)).fetchone()
        assert inb_row["rfc_message_id"] == "<inbound@msg>"
        assert inb_row["uid"] == 42

        # 3. crm_titular_requests con inbound_id
        cur = conn.execute(
            """INSERT INTO crm_titular_requests (
                lead_id, type, medium, received_on, due_on, status,
                registered_by, registered_at, inbound_id
            ) VALUES (?, 'inquiry', 'email', '2026-10-05', '2026-10-20', 'open', ?,
                      '2026-10-05T15:00:00Z', ?)""",
            (lead_id, user_id, inbound_id),
        )
        req_row = conn.execute(
            "SELECT inbound_id FROM crm_titular_requests WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        assert req_row["inbound_id"] == inbound_id

        # 4. crm_proposals
        cur = conn.execute(
            """INSERT INTO crm_proposals (
                lead_id, kind, step, status, current_version, approver_user_id,
                expires_at, created_at, resolved_at, resolved_by
            ) VALUES (?, 'followup', 1, 'pending', 1, ?, '2026-10-07T15:00:00Z',
                      '2026-10-05T15:00:00Z', NULL, NULL)""",
            (lead_id, user_id),
        )
        proposal_id = cur.lastrowid
        prop_row = conn.execute(
            "SELECT * FROM crm_proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        assert prop_row["kind"] == "followup"
        assert prop_row["step"] == 1

        # 5. crm_proposal_versions
        conn.execute(
            """INSERT INTO crm_proposal_versions (
                proposal_id, version, subject, body, content_hash, author_user_id, created_at
            ) VALUES (?, 1, 'Asunto test', 'Cuerpo test', 'sha256_hash', ?,
                      '2026-10-05T15:00:00Z')""",
            (proposal_id, user_id),
        )
        ver_row = conn.execute(
            "SELECT * FROM crm_proposal_versions WHERE proposal_id = ? AND version = 1",
            (proposal_id,),
        ).fetchone()
        assert ver_row["content_hash"] == "sha256_hash"

        # 6. crm_sends
        cur = conn.execute(
            """INSERT INTO crm_sends (
                proposal_id, version, approved_hash, approved_by, approved_at,
                scheduled_at, status, attempts, first_attempt_at, next_attempt_at,
                rfc_message_id, last_error, sent_at, lead_id, week_start
            ) VALUES (?, 1, 'sha256_hash', ?, '2026-10-05T16:00:00Z', '2026-10-06T09:00:00Z',
                      'scheduled', 0, NULL, '2026-10-06T09:00:00Z', NULL, NULL, NULL, ?,
                      '2026-10-05T00:00:00Z')""",
            (proposal_id, user_id, lead_id),
        )
        send_row = conn.execute("SELECT * FROM crm_sends WHERE id = ?", (cur.lastrowid,)).fetchone()
        assert send_row["proposal_id"] == proposal_id
        assert send_row["status"] == "scheduled"

        # Verificación estricta de claves foráneas
        fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        assert fk_errors == []
    db.close()


def test_vcrm028_solo_las_propuestas_vivas_ocupan_el_paso(tmp_path: Path) -> None:
    db = CrmDatabase(tmp_path / "crm.db")
    with db.tx() as tx:
        user = repo.insert_user(tx, telegram_id=1, role=Role.COMMERCIAL, email="m@k.co", now=NOW)
        lead_id = repo.insert_lead(
            tx, assigned_user_id=user.id, state=LeadState.NURTURING, now=NOW, fields={"name": "A"}
        )

        def new(step: int = 1) -> int | None:
            return repo.insert_proposal(
                tx,
                lead_id=lead_id,
                kind="followup",
                step=step,
                approver_user_id=user.id,
                expires_at=NOW,
                created_at=NOW,
            )

        first = new()
        assert first is not None and new() is None  # pendiente: ocupa el paso
        for dead in ("cancelled", "blocked"):  # canceladas y bloqueadas liberan el paso
            repo.update_proposal(tx, first, status=dead)
            replacement = new()
            assert replacement is not None and replacement != first
            repo.update_proposal(tx, replacement, status=dead)
            first = replacement
        alive = new()
        assert alive is not None
        for living in ("approved", "sent", "failed", "expired"):  # el resto sigue ocupándolo
            repo.update_proposal(tx, alive, status=living)
            assert new() is None, living
        assert new(step=2) is not None  # otro paso es independiente
    db.close()
