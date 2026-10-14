"""Consultas de solo lectura en bloque para CRM-consejero (spec 007, VJC-005, VJC-008, VJC-012)."""

import sqlite3
from datetime import datetime, time, timedelta
from typing import Any

from jerico.crm.handoff import missing_handoff_fields
from jerico.crm.model import Lead
from jerico.crm.timeutil import BOGOTA, from_iso, local_date, to_iso


def load_context(conn: sqlite3.Connection, now_dt: datetime) -> list[dict[str, Any]]:
    """Carga en bloque el contexto de todos los leads sin escrituras y en ≤ 12 consultas SELECT."""
    today = local_date(now_dt)

    # Ventana de 30 días calendario en Bogotá para eventos
    cutoff_date = today - timedelta(days=30)
    cutoff_dt_bogota = datetime.combine(cutoff_date, time.min, tzinfo=BOGOTA)
    cutoff_iso = to_iso(cutoff_dt_bogota)

    # 1. Consulta de todos los leads con correo de comercial asignado
    leads_cursor = conn.execute(
        "SELECT l.*, u.email as assigned_user_email "
        "FROM crm_leads l "
        "LEFT JOIN crm_users u ON l.assigned_user_id = u.id "
        "ORDER BY l.id"
    )
    lead_rows = leads_cursor.fetchall()
    if not lead_rows:
        return []

    # 2. Conteo de eventos relevantes de los últimos 30 días
    events_cursor = conn.execute(
        "SELECT lead_id, COUNT(*) as cnt "
        "FROM crm_lead_events "
        "WHERE kind IN ('state', 'field', 'reassign') AND at >= ? "
        "GROUP BY lead_id",
        (cutoff_iso,),
    )
    events_30d_map = {row["lead_id"]: row["cnt"] for row in events_cursor.fetchall()}

    # 3. Último cambio de estado para cada lead (para calcular días en etapa actual)
    state_cursor = conn.execute(
        "SELECT lead_id, MAX(at) as max_state_at "
        "FROM crm_lead_events "
        "WHERE kind = 'state' "
        "GROUP BY lead_id"
    )
    last_state_map = {row["lead_id"]: row["max_state_at"] for row in state_cursor.fetchall()}

    # 4. Conteo de notas por lead
    notes_cursor = conn.execute("SELECT lead_id, COUNT(*) as cnt FROM crm_notes GROUP BY lead_id")
    notes_map = {row["lead_id"]: row["cnt"] for row in notes_cursor.fetchall()}

    # 5. Cadencias
    cadence_cursor = conn.execute(
        "SELECT lead_id, reason, interval_days, total_steps, steps_done, sent_count, "
        "next_action_at, status FROM crm_cadences"
    )
    cadence_map = {row["lead_id"]: dict(row) for row in cadence_cursor.fetchall()}

    # 6. Alertas sin resolver asociadas a leads
    alerts_cursor = conn.execute(
        "SELECT lead_id, COUNT(*) as cnt "
        "FROM crm_alerts "
        "WHERE lead_id IS NOT NULL AND resolved_at IS NULL "
        "GROUP BY lead_id"
    )
    alerts_map = {row["lead_id"]: row["cnt"] for row in alerts_cursor.fetchall()}

    # 7. Solicitudes de titular abiertas o vencidas asociadas a leads
    requests_cursor = conn.execute(
        "SELECT lead_id, COUNT(*) as cnt "
        "FROM crm_titular_requests "
        "WHERE lead_id IS NOT NULL AND status IN ('open', 'overdue') "
        "GROUP BY lead_id"
    )
    requests_map = {row["lead_id"]: row["cnt"] for row in requests_cursor.fetchall()}

    # 8. Propuestas pendientes de cualquier tipo
    proposals_cursor = conn.execute(
        "SELECT lead_id, COUNT(*) as cnt "
        "FROM crm_proposals "
        "WHERE status = 'pending' "
        "GROUP BY lead_id"
    )
    proposals_map = {row["lead_id"]: row["cnt"] for row in proposals_cursor.fetchall()}

    lead_fields = set(Lead.__dataclass_fields__.keys())

    results: list[dict[str, Any]] = []
    for row in lead_rows:
        lead_id = row["id"]
        row_dict = dict(row)

        reg_dt = from_iso(row_dict["registered_at"])
        last_int_dt = from_iso(row_dict["last_interaction_at"])

        antiguedad_dias = max(0, (today - local_date(reg_dt)).days)
        dias_sin_interaccion = max(0, (today - local_date(last_int_dt)).days)

        last_state_iso = last_state_map.get(lead_id)
        if last_state_iso:
            dias_etapa = max(0, (today - local_date(from_iso(last_state_iso))).days)
        else:
            dias_etapa = antiguedad_dias

        lead_kwargs = {k: row_dict[k] for k in lead_fields if k in row_dict}
        lead_obj = Lead(**lead_kwargs)
        missing_count = len(missing_handoff_fields(lead_obj))

        cadence_info = cadence_map.get(lead_id)
        if cadence_info:
            cad_status = cadence_info["status"]
            cad_done = cadence_info["steps_done"]
            cad_total = cadence_info["total_steps"]
            cad_sent = cadence_info["sent_count"]
            next_action_iso = cadence_info["next_action_at"]
            if next_action_iso:
                cad_has_next = True
                cad_days_next = (local_date(from_iso(next_action_iso)) - today).days
            else:
                cad_has_next = False
                cad_days_next = 0
        else:
            cad_status = None
            cad_done = 0
            cad_total = 0
            cad_sent = 0
            cad_has_next = False
            cad_days_next = 0

        lead_context: dict[str, Any] = {
            "id": lead_id,
            "stage": row_dict["state"],
            "created_at_days": antiguedad_dias,
            "days_since_interaction": dias_sin_interaccion,
            "days_in_stage": dias_etapa,
            "ever_accepted": bool(row_dict.get("ever_accepted", 0)),
            "retraction": bool(row_dict.get("rejection_is_retraction", 0)),
            "commercial_block": bool(row_dict.get("commercial_block", 0)),
            "phone": row_dict.get("phone_e164") or "",
            "email": row_dict.get("email") or "",
            "agreed_value": row_dict.get("agreed_value") or "",
            "service": row_dict.get("service") or "",
            "assigned_commercial": row_dict.get("assigned_user_email") or "",
            "client_type": row_dict.get("client_type") or "",
            "reject_reason": row_dict.get("reject_reason") or "",
            "authorization_status": row_dict.get("auth_status") or "unauthorized",
            "missing_handoff_fields": missing_count,
            "events_30d": events_30d_map.get(lead_id, 0),
            "notes_count": notes_map.get(lead_id, 0),
            "cadence_status": cad_status,
            "cadence_steps_done": cad_done,
            "cadence_steps_total": cad_total,
            "cadence_shipments_done": cad_sent,
            "cadence_has_next_action": cad_has_next,
            "cadence_days_next_action": cad_days_next,
            "pending_proposals": proposals_map.get(lead_id, 0),
            "pending_alerts": alerts_map.get(lead_id, 0),
            "pending_requests": requests_map.get(lead_id, 0),
            "suppressed_at": row_dict.get("suppressed_at"),
            "opted_out": row_dict["state"] == "opted_out",
        }
        results.append(lead_context)

    return results
