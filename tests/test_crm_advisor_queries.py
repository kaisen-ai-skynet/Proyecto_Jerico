"""Pruebas unitarias para advisor_queries (spec 007, CRM-consejero, VJC-005, VJC-008, VJC-012)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from jerico.crm.advisor_queries import load_context
from jerico.crm.db import CrmDatabase
from jerico.crm.model import EventKind, LeadState, RequestStatus, RequestType
from jerico.crm.repo import (
    add_event,
    insert_lead,
    insert_note,
    insert_titular_request,
    lead_notes,
    open_alerts,
    titular_requests,
)

BOGOTA = ZoneInfo("America/Bogota")


def test_load_context_matches_individual_queries(tmp_path: Path) -> None:
    db = CrmDatabase(tmp_path / "crm_test.db")
    now_dt = datetime(2026, 10, 14, 12, 0, 0, tzinfo=BOGOTA)
    now_utc = now_dt.astimezone(UTC)

    with db.tx() as tx:
        # Lead 1: con eventos, notas, cadencia activa, alertas, solicitudes y propuestas
        lead1_id = insert_lead(
            tx,
            assigned_user_id=None,
            state=LeadState.CONTACTED,
            now=now_utc - timedelta(days=20),
            fields={
                "name": "Empresa Alfa",
                "phone_e164": "+573001111111",
                "email": "alfa@example.com",
                "company": "Alfa SAS",
                "client_type": "empresa",
                "service": "Consultoría",
                "agreed_value": "5000000",
            },
        )
        add_event(
            tx,
            lead_id=lead1_id,
            kind=EventKind.STATE,
            field="state",
            old_value="new",
            new_value="contacted",
            actor_user_id=1,
            at=now_utc - timedelta(days=5),
        )
        insert_note(
            tx,
            lead_id=lead1_id,
            author_user_id=1,
            body="Nota 1",
            at=now_utc - timedelta(days=2),
        )
        tx.execute(
            "INSERT INTO crm_cadences (lead_id, reason, interval_days, total_steps, steps_done, "
            "sent_count, next_action_at, status, started_at, updated_at) "
            "VALUES (?, 'precio', 3, 3, 1, 1, ?, 'active', ?, ?)",
            (
                lead1_id,
                (now_utc + timedelta(days=2)).isoformat(),
                now_utc.isoformat(),
                now_utc.isoformat(),
            ),
        )
        tx.execute(
            "INSERT INTO crm_alerts (lead_id, kind, created_at) "
            "VALUES (?, 'notification_failed', ?)",
            (lead1_id, now_utc.isoformat()),
        )
        insert_titular_request(
            tx,
            lead_id=lead1_id,
            kind=RequestType.INQUIRY,
            medium="email",
            received_on="2026-10-10",
            due_on="2026-10-24",
            registered_by=1,
            now=now_utc,
        )
        tx.execute(
            "INSERT INTO crm_proposals "
            "(lead_id, kind, step, status, approver_user_id, expires_at, created_at) "
            "VALUES (?, 'followup', 1, 'pending', 1, ?, ?)",
            (lead1_id, (now_utc + timedelta(days=1)).isoformat(), now_utc.isoformat()),
        )

        # Lead 2: básico sin eventos ni cadencia
        lead2_id = insert_lead(
            tx,
            assigned_user_id=None,
            state=LeadState.NEW,
            now=now_utc - timedelta(days=1),
            fields={
                "name": "Persona Beta",
                "phone_e164": "+573002222222",
                "email": "beta@example.com",
                "client_type": "persona natural",
            },
        )

    with db.read() as conn:
        ctx = load_context(conn, now_dt)

        # Verificar equivalencia para Lead 1
        lead1_ctx = next(item for item in ctx if item["id"] == lead1_id)
        assert lead1_ctx["notes_count"] == len(lead_notes(conn, lead1_id))
        assert lead1_ctx["pending_alerts"] == len(open_alerts(conn, lead_id=lead1_id))
        expected_requests = [
            r
            for r in titular_requests(conn, [RequestStatus.OPEN, RequestStatus.OVERDUE])
            if r.lead_id == lead1_id
        ]
        assert lead1_ctx["pending_requests"] == len(expected_requests)
        assert lead1_ctx["cadence_status"] == "active"
        assert lead1_ctx["pending_proposals"] == 1
        assert lead1_ctx["days_in_stage"] == 5

        # Verificar equivalencia para Lead 2
        lead2_ctx = next(item for item in ctx if item["id"] == lead2_id)
        assert lead2_ctx["notes_count"] == 0
        assert lead2_ctx["cadence_status"] is None
        assert lead2_ctx["pending_alerts"] == 0
        assert lead2_ctx["pending_requests"] == 0
        assert lead2_ctx["pending_proposals"] == 0
        assert lead2_ctx["days_in_stage"] == 1


def test_load_context_statement_count_invariant(tmp_path: Path) -> None:
    db = CrmDatabase(tmp_path / "crm_count.db")
    now_dt = datetime(2026, 10, 14, 12, 0, 0, tzinfo=BOGOTA)
    now_utc = now_dt.astimezone(UTC)

    # Crear 10 leads
    with db.tx() as tx:
        for i in range(10):
            insert_lead(
                tx,
                assigned_user_id=None,
                state=LeadState.NEW,
                now=now_utc,
                fields={
                    "name": f"Lead {i}",
                    "phone_e164": f"+57300{i:07d}",
                    "email": f"lead{i}@example.com",
                },
            )

    stmts_10: list[str] = []
    with db.read() as conn:
        conn.set_trace_callback(stmts_10.append)
        ctx_10 = load_context(conn, now_dt)
        conn.set_trace_callback(None)

    assert len(ctx_10) == 10
    count_10 = len(stmts_10)
    assert count_10 <= 12

    # Agregar más leads (hasta 50 leads)
    with db.tx() as tx:
        for i in range(10, 50):
            insert_lead(
                tx,
                assigned_user_id=None,
                state=LeadState.NEW,
                now=now_utc,
                fields={
                    "name": f"Lead {i}",
                    "phone_e164": f"+57300{i:07d}",
                    "email": f"lead{i}@example.com",
                },
            )

    stmts_50: list[str] = []
    with db.read() as conn:
        conn.set_trace_callback(stmts_50.append)
        ctx_50 = load_context(conn, now_dt)
        conn.set_trace_callback(None)

    assert len(ctx_50) == 50
    count_50 = len(stmts_50)

    # Invariante: exactamente el mismo número de sentencias
    assert count_10 == count_50


def test_load_context_static_analysis_only_select() -> None:
    advisor_queries_path = Path("src/jerico/crm/advisor_queries.py")
    code = advisor_queries_path.read_text(encoding="utf-8").upper()

    # Comprueba que no hay sentencias de escritura en SQL literals
    for forbidden in ["INSERT INTO", "UPDATE ", "DELETE FROM", "PRAGMA "]:
        assert forbidden not in code, f"Encontrado comando de escritura no permitido: {forbidden}"
