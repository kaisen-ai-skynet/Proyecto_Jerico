"""Vistas y comandos de seguimiento de la fase 2 (F2-T22, F2-T23).
Requisitos: VCRM-020..026; plan-f2 §5.9.
"""

import sqlite3
from datetime import datetime

from jerico.crm import followup, leads, permissions, render, repo, timeutil
from jerico.crm.model import Lead, LeadState, Outgoing, User
from jerico.crm.parsing import build_callback
from jerico.crm.render import short_id

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
]
