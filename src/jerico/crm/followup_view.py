"""Vistas y comandos de seguimiento de la fase 2 (F2-T22, F2-T23).
Requisitos: VCRM-020..026; plan-f2 §5.9.
"""

import sqlite3
from datetime import datetime

from loguru import logger

from jerico.crm import followup, leads, permissions, render, repo, timeutil
from jerico.crm.model import Lead, LeadState, Outgoing, User
from jerico.crm.parsing import build_callback
from jerico.crm.render import short_id
from jerico.decision.config import load_settings
from jerico.decision.port import decidir

NO_FOLLOWUP = "No hay leads en seguimiento."


def _format_lead_line(conn: sqlite3.Connection, lead: Lead) -> str:
    cad = repo.get_cadence(conn, lead.id)
    if cad is None:
        return f"{short_id(lead.id)} · sin cadencia"
    reason = cad.reason or lead.reject_reason or "otro"
    reason_label = leads.REJECT_REASONS.get(reason, reason)
    if cad.interval_days == 7:
        freq = "semanal"
    elif cad.interval_days == 30:
        freq = "mensual"
    else:
        freq = f"cada {cad.interval_days} días"

    if cad.status == "paused" or lead.state == LeadState.PAUSED.value:
        next_action = "pausada"
    elif cad.status == "completed":
        next_action = "completada"
    elif cad.next_action_at is None:
        next_action = "a la espera de decisión"
    else:
        dt = timeutil.from_iso(cad.next_action_at)
        next_action = timeutil.format_local(dt)

    return (
        f"{short_id(lead.id)} · {reason_label} · {freq} · {next_action} · {cad.sent_count} envíos"
    )


def lead_followup_state(conn: sqlite3.Connection, lead: Lead, now: datetime) -> dict[str, str]:
    """Calcula el vector de estado de un lead para la decisión de seguimiento_lead (VJT-063)."""
    last_iso = lead.last_interaction_at or lead.registered_at
    if last_iso:
        days = max((now - timeutil.from_iso(last_iso)).days, 0)
    else:
        days = 0

    if days == 0:
        dias_bucket = "0"
    elif 1 <= days <= 2:
        dias_bucket = "1-2"
    elif 3 <= days <= 7:
        dias_bucket = "3-7"
    elif 8 <= days <= 14:
        dias_bucket = "8-14"
    elif 15 <= days <= 30:
        dias_bucket = "15-30"
    elif 31 <= days <= 90:
        dias_bucket = "31-90"
    else:
        dias_bucket = "mas_de_90"

    cad = repo.get_cadence(conn, lead.id)
    sent_count = cad.sent_count if cad is not None else 0
    paso_val = str(min(max(sent_count, 0), 4))

    state_map = {
        LeadState.NEW.value: "nuevo",
        LeadState.CONTACTED.value: "en_contacto",
        LeadState.ACCEPTED.value: "propuesta",
        LeadState.NURTURING.value: "esperando_cliente",
        LeadState.PAUSED.value: "pausado",
    }
    estado_val = state_map.get(lead.state, "esperando_cliente")

    return {
        "dias_sin_contacto": dias_bucket,
        "paso_cadencia": paso_val,
        "estado_lead": estado_val,
        "intentos_fallidos": "0",
    }


def following_command(
    conn: sqlite3.Connection, actor: User, text: str, now: datetime
) -> list[Outgoing]:
    """`/seguimiento`: leads visibles en «en nutrición» o «pausado» (VCRM-025)."""
    if not permissions.authorize(actor, permissions.Action.MANAGE_CADENCE, None).allowed:
        return leads._deny(conn, actor, now)
    visible = leads.visible_leads(conn, actor, include_suppressed=False)
    in_followup = [
        lead
        for lead in visible
        if lead.state in (LeadState.NURTURING.value, LeadState.PAUSED.value)
    ]
    if not in_followup:
        return [Outgoing(actor.telegram_id, NO_FOLLOWUP)]

    in_followup.sort(key=lambda lead: lead.id)

    # Enganche de decisión consultivo/asesor para seguimiento_lead (VJT-010a, VJT-063, T10):
    try:
        dec_settings = load_settings()
        for lead in in_followup:
            state = lead_followup_state(conn, lead, now)
            decidir("seguimiento_lead", state=state, settings=dec_settings)
    except Exception as exc:  # noqa: BLE001
        logger.debug("seguimiento: fallo al evaluar decision ({})", exc)

    lines = [_format_lead_line(conn, lead) for lead in in_followup]
    chunks = render.split_message("\n".join(lines))
    return [Outgoing(actor.telegram_id, chunk) for chunk in chunks]


def cadence_buttons(
    conn: sqlite3.Connection, actor: User, lead: Lead
) -> tuple[tuple[tuple[str, str], ...], ...]:
    """Botones de cadencia y reactivación en la ficha (F2-T23; VCRM-020, 022..026)."""
    if not followup.f2_active(conn):
        return ()
    if not permissions.authorize(actor, permissions.Action.MANAGE_CADENCE, lead).allowed:
        return ()

    from jerico.crm.f2_bot import (
        MONTHLY_CALLBACK,
        PAUSE_CALLBACK,
        REACTIVATE_CALLBACK,
        RESUME_CALLBACK,
        WEEKLY_CALLBACK,
    )

    if lead.state == LeadState.NURTURING.value:
        cad = repo.get_cadence(conn, lead.id)
        if cad is None:
            return ()
        row1 = (
            ("Pausar", build_callback(PAUSE_CALLBACK, str(lead.id))),
            ("Reactivar", build_callback(REACTIVATE_CALLBACK, str(lead.id))),
        )
        row2 = (
            ("Frecuencia semanal", build_callback(WEEKLY_CALLBACK, str(lead.id))),
            ("Frecuencia mensual", build_callback(MONTHLY_CALLBACK, str(lead.id))),
        )
        return (row1, row2)

    if lead.state == LeadState.PAUSED.value:
        paused_row = (
            ("Reanudar", build_callback(RESUME_CALLBACK, str(lead.id))),
            ("Reactivar", build_callback(REACTIVATE_CALLBACK, str(lead.id))),
        )
        return (paused_row,)

    if lead.state == LeadState.REJECTED.value:
        rejected_row = (("Reactivar", build_callback(REACTIVATE_CALLBACK, str(lead.id))),)
        return (rejected_row,)

    return ()


__all__ = [
    "NO_FOLLOWUP",
    "cadence_buttons",
    "following_command",
    "lead_followup_state",
]
