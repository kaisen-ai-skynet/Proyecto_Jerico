"""Servicio de cadencias y seguimiento comercial (plan-f2 §5.2; VCRM-018..026, 121).

Gestiona el ciclo de vida de las cadencias (alta, pausa, reanudación, frecuencia,
reactivación y consumo de pasos) garantizando postura de privacidad y permisos.
"""

import sqlite3
from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from jerico.crm import (
    cadence,
    compliance,
    delivery,
    followup_text,
    gate,
    permissions,
    repo,
    states,
)
from jerico.crm.followup_text import FollowupTexts
from jerico.crm.leads import deny_lead
from jerico.crm.model import (
    SYSTEM_USER_ID,
    Cadence,
    CadenceStatus,
    EventKind,
    Lead,
    LeadState,
    Outgoing,
    ProposalKind,
    Role,
    User,
)
from jerico.crm.parsing import build_callback
from jerico.crm.permissions import Action
from jerico.crm.render import short_id
from jerico.crm.timeutil import from_iso, to_iso


def f2_active(conn: sqlite3.Connection) -> bool:
    """True si F2 está activado en el sistema (crm_meta tiene `f2_activated_at`)."""
    return repo.get_meta(conn, "f2_activated_at") is not None


def start_cadence(
    conn: sqlite3.Connection,
    lead: Lead,
    now: datetime,
    keys: Sequence[str] = (),
) -> list[Outgoing]:
    """Inicia la cadencia para un lead si cuenta con autorización comercial vigente.

    Cubre VCRM-018 y VCRM-019.
    """
    if not f2_active(conn):
        return []

    existing = repo.get_cadence(conn, lead.id)
    if existing is not None and existing.status == CadenceStatus.ACTIVE.value:
        return []

    if not compliance.may_contact_commercially(conn, lead, keys):
        # VCRM-019: aviso al comercial del lead o al CTO si no tiene comercial asignado
        chat: int | None = None
        if lead.assigned_user_id is not None:
            commercial = repo.get_user(conn, lead.assigned_user_id)
            if commercial is not None and commercial.active:
                chat = commercial.telegram_id
        if chat is None:
            ctos = repo.active_users(conn, role=Role.CTO)
            if ctos:
                chat = ctos[0].telegram_id

        if chat is not None:
            text = (
                f"El lead {short_id(lead.id)} no cuenta con autorización vigente para contacto "
                f"comercial. No puede entrar en seguimiento. Use /autorizacion {short_id(lead.id)} "
                "para registrarla."
            )
            return [Outgoing(chat, text)]
        return []

    # Determinar fila de configuración según motivo de rechazo
    reason = lead.reject_reason or "otro"
    try:
        row = cadence.row_for(reason)
    except KeyError:
        row = cadence.row_for("otro")

    next_action = cadence.first_action(now, row.interval_days)
    cad = Cadence(
        lead_id=lead.id,
        reason=row.reason,
        interval_days=row.interval_days,
        total_steps=row.total_steps,
        steps_done=0,
        sent_count=0,
        next_action_at=to_iso(next_action),
        last_sent_at=None,
        status=CadenceStatus.ACTIVE.value,
        started_at=to_iso(now),
        updated_at=to_iso(now),
    )
    repo.upsert_cadence(conn, cad)

    src = LeadState(lead.state)
    check = states.check_transition(src, LeadState.NURTURING, phase=2)
    if check.ok:
        repo.update_lead(conn, lead.id, {"state": LeadState.NURTURING.value}, now=now)
        repo.add_event(
            conn,
            lead_id=lead.id,
            kind=EventKind.STATE,
            actor_user_id=SYSTEM_USER_ID,
            at=now,
            old_value=src.value,
            new_value=LeadState.NURTURING.value,
            reason=row.reason,
        )

    # Notificar inicio de cadencia al comercial o CTO
    chat_id: int | None = None
    if lead.assigned_user_id is not None:
        u = repo.get_user(conn, lead.assigned_user_id)
        if u is not None and u.active:
            chat_id = u.telegram_id
    if chat_id is None:
        ctos = repo.active_users(conn, role=Role.CTO)
        if ctos:
            chat_id = ctos[0].telegram_id

    if chat_id is not None:
        msg = (
            f"{short_id(lead.id)}: cadencia iniciada ({row.reason}, cada {row.interval_days} días)."
        )
        return [Outgoing(chat_id, msg)]
    return []


def pause(
    conn: sqlite3.Connection,
    actor: User,
    lead_id: int,
    now: datetime,
) -> list[Outgoing]:
    """Pausa la cadencia del lead, pasando a PAUSED y cancelando pendientes (VCRM-020)."""
    lead = repo.get_lead(conn, lead_id)
    if lead is None:
        return [Outgoing(actor.telegram_id, f"El lead {short_id(lead_id)} no existe.")]

    decision = permissions.authorize(actor, Action.MANAGE_CADENCE, lead)
    if not decision.allowed:
        return deny_lead(conn, actor, decision, lead.id, now)

    cad = repo.get_cadence(conn, lead.id)
    if cad is None:
        return [Outgoing(actor.telegram_id, f"{short_id(lead.id)} no tiene cadencia configurada.")]

    src = LeadState(lead.state)
    check = states.check_transition(src, LeadState.PAUSED, phase=2)
    if not check.ok:
        return [
            Outgoing(
                actor.telegram_id,
                f"No se puede pausar {short_id(lead.id)} en estado «{src.value}».",
            )
        ]

    repo.update_lead(conn, lead.id, {"state": LeadState.PAUSED.value}, now=now)
    repo.add_event(
        conn,
        lead_id=lead.id,
        kind=EventKind.STATE,
        actor_user_id=actor.id,
        at=now,
        old_value=src.value,
        new_value=LeadState.PAUSED.value,
    )
    repo.update_cadence(
        conn,
        lead.id,
        status=CadenceStatus.PAUSED.value,
        updated_at=to_iso(now),
    )
    repo.cancel_open_followups(conn, lead.id, now)
    repo.cancel_scheduled_sends(conn, lead.id, now)

    return [Outgoing(actor.telegram_id, f"{short_id(lead.id)}: cadencia pausada.")]


def resume(
    conn: sqlite3.Connection,
    actor: User,
    lead_id: int,
    now: datetime,
) -> list[Outgoing]:
    """Reanuda la cadencia del lead, recalculando next_action_at desde now (VCRM-022)."""
    lead = repo.get_lead(conn, lead_id)
    if lead is None:
        return [Outgoing(actor.telegram_id, f"El lead {short_id(lead_id)} no existe.")]

    decision = permissions.authorize(actor, Action.MANAGE_CADENCE, lead)
    if not decision.allowed:
        return deny_lead(conn, actor, decision, lead.id, now)

    cad = repo.get_cadence(conn, lead.id)
    if cad is None:
        return [Outgoing(actor.telegram_id, f"{short_id(lead.id)} no tiene cadencia configurada.")]

    src = LeadState(lead.state)
    check = states.check_transition(src, LeadState.NURTURING, phase=2)
    if not check.ok:
        return [
            Outgoing(
                actor.telegram_id,
                f"No se puede reanudar {short_id(lead.id)} en estado «{src.value}».",
            )
        ]

    repo.update_lead(conn, lead.id, {"state": LeadState.NURTURING.value}, now=now)
    repo.add_event(
        conn,
        lead_id=lead.id,
        kind=EventKind.STATE,
        actor_user_id=actor.id,
        at=now,
        old_value=src.value,
        new_value=LeadState.NURTURING.value,
    )
    next_action = cadence.first_action(now, cad.interval_days)
    repo.update_cadence(
        conn,
        lead.id,
        status=CadenceStatus.ACTIVE.value,
        next_action_at=to_iso(next_action),
        updated_at=to_iso(now),
    )
    return [Outgoing(actor.telegram_id, f"{short_id(lead.id)}: cadencia reanudada.")]


def set_frequency(
    conn: sqlite3.Connection,
    actor: User,
    lead_id: int,
    frequency: Literal["weekly", "monthly"],
    now: datetime,
) -> list[Outgoing]:
    """Ajusta la frecuencia de la cadencia a semanal o mensual (VCRM-023)."""
    lead = repo.get_lead(conn, lead_id)
    if lead is None:
        return [Outgoing(actor.telegram_id, f"El lead {short_id(lead_id)} no existe.")]

    decision = permissions.authorize(actor, Action.MANAGE_CADENCE, lead)
    if not decision.allowed:
        return deny_lead(conn, actor, decision, lead.id, now)

    cad = repo.get_cadence(conn, lead.id)
    if cad is None:
        return [Outgoing(actor.telegram_id, f"{short_id(lead.id)} no tiene cadencia configurada.")]

    if cad.status not in (CadenceStatus.ACTIVE.value, CadenceStatus.PAUSED.value):
        return [
            Outgoing(
                actor.telegram_id, f"No se puede cambiar la frecuencia en estado «{cad.status}»."
            )
        ]

    days = cadence.frequency_days(frequency)
    last_sent = from_iso(cad.last_sent_at) if cad.last_sent_at else None
    next_action = cadence.next_action_on_frequency(now, days, last_sent_at=last_sent)

    repo.update_cadence(
        conn,
        lead.id,
        interval_days=days,
        next_action_at=to_iso(next_action),
        updated_at=to_iso(now),
    )
    return [Outgoing(actor.telegram_id, f"{short_id(lead.id)}: frecuencia ajustada a {frequency}.")]


def reactivate(
    conn: sqlite3.Connection,
    actor: User,
    lead_id: int,
    now: datetime,
) -> list[Outgoing]:
    """Reactiva el lead, deteniendo la cadencia y cancelando pendientes (VCRM-024)."""
    lead = repo.get_lead(conn, lead_id)
    if lead is None:
        return [Outgoing(actor.telegram_id, f"El lead {short_id(lead_id)} no existe.")]

    decision = permissions.authorize(actor, Action.MANAGE_CADENCE, lead)
    if not decision.allowed:
        return deny_lead(conn, actor, decision, lead.id, now)

    src = LeadState(lead.state)
    check = states.check_transition(src, LeadState.REACTIVATED, phase=2)
    if not check.ok:
        return [
            Outgoing(
                actor.telegram_id,
                f"No se puede reactivar {short_id(lead.id)} en estado «{src.value}».",
            )
        ]

    repo.update_lead(conn, lead.id, {"state": LeadState.REACTIVATED.value}, now=now)
    repo.add_event(
        conn,
        lead_id=lead.id,
        kind=EventKind.STATE,
        actor_user_id=actor.id,
        at=now,
        old_value=src.value,
        new_value=LeadState.REACTIVATED.value,
    )

    cad = repo.get_cadence(conn, lead.id)
    if cad is not None:
        repo.update_cadence(
            conn,
            lead.id,
            status=CadenceStatus.STOPPED.value,
            next_action_at=None,
            updated_at=to_iso(now),
        )

    repo.cancel_open_followups(conn, lead.id, now)
    repo.cancel_scheduled_sends(conn, lead.id, now)

    return [Outgoing(actor.telegram_id, f"{short_id(lead.id)}: lead reactivado.")]


def on_step_consumed(
    conn: sqlite3.Connection,
    lead_id: int,
    outcome: Literal["sent", "cancelled", "expired"],
    now: datetime,
    sent_at: datetime | None = None,
) -> list[Outgoing]:
    """Avanza la cadencia tras el consumo de un paso (VCRM-026, 029, 032, 034)."""
    lead = repo.get_lead(conn, lead_id)
    if lead is None:
        return []

    cad = repo.get_cadence(conn, lead_id)
    if cad is None:
        return []

    last_sent = from_iso(cad.last_sent_at) if cad.last_sent_at else None
    consumed_now = sent_at if (outcome == "sent" and sent_at is not None) else now
    res = cadence.after_step(
        steps_done=cad.steps_done,
        total_steps=cad.total_steps,
        interval=cad.interval_days,
        now=consumed_now,
        outcome=outcome,
        sent_count=cad.sent_count,
        last_sent_at=last_sent,
    )

    repo.update_cadence(
        conn,
        lead_id,
        steps_done=res.steps_done,
        sent_count=res.sent_count,
        status=res.status,
        next_action_at=to_iso(res.next_action_at) if res.next_action_at else None,
        last_sent_at=to_iso(res.last_sent_at) if res.last_sent_at else None,
        updated_at=to_iso(now),
    )

    if res.completed:
        # VCRM-026: notificar al comercial o CTO con botones «Marcar perdido» y «Reactivar»
        chat: int | None = None
        if lead.assigned_user_id is not None:
            u = repo.get_user(conn, lead.assigned_user_id)
            if u is not None and u.active:
                chat = u.telegram_id
        if chat is None:
            ctos = repo.active_users(conn, role=Role.CTO)
            if ctos:
                chat = ctos[0].telegram_id

        if chat is not None:
            buttons = (
                (
                    ("Marcar perdido", build_callback("cperdido", str(lead.id))),
                    ("Reactivar", build_callback("creactivar", str(lead.id))),
                ),
            )
            text = (
                f"{short_id(lead.id)}: cadencia de seguimiento completada "
                f"({res.steps_done}/{res.total_steps} pasos). "
                "Decida si desea marcar como perdido o reactivar el lead."
            )
            return [Outgoing(chat, text, buttons=buttons)]

    return []


def generate_due(
    conn: sqlite3.Connection,
    now: datetime,
    keys: Sequence[str],
    texts: FollowupTexts | None,
    sender_name: str,
) -> list[Outgoing]:
    """Crea propuestas para cadencias activas vencidas sin enviar correos (plan-f2 §5.3)."""
    if not f2_active(conn):
        return []

    out: list[Outgoing] = []
    due = repo.due_cadences(conn, now)

    for cad in due:
        paso = cad.steps_done + 1

        # a. Lead en estado NURTURING
        lead = repo.get_lead(conn, cad.lead_id)
        if lead is None or lead.state != LeadState.NURTURING.value:
            continue

        # b. Guarda de contacto comercial
        if not compliance.may_contact_commercially(conn, lead, keys):
            continue

        # c. Sin correo: aviso único por (lead, paso) al comercial o CTO
        email = (lead.email or "").strip()
        if not email:
            notice_key = f"f2_notice:no_email:{lead.id}:{paso}"
            if repo.get_meta(conn, notice_key) is None:
                recipients = permissions.commercial_recipients(lead, repo.active_users(conn))
                if recipients:
                    msg = (
                        f"El lead {short_id(lead.id)} no tiene correo "
                        f"electrónico para el paso {paso} de seguimiento. "
                        "Complete el dato para generar la propuesta."
                    )
                    out.append(Outgoing(recipients[0].telegram_id, msg))
                repo.set_meta(conn, notice_key, to_iso(now))
            continue

        # d. Texto del paso: aviso único al CTO por (motivo, paso) si falta
        text = texts.lookup(cad.reason, paso) if texts is not None else None
        if text is None:
            notice_key = f"f2_notice:no_text:{cad.reason}:{paso}"
            if repo.get_meta(conn, notice_key) is None:
                ctos = repo.active_users(conn, role=Role.CTO)
                if ctos:
                    msg = (
                        f"No hay texto configurado para el motivo «{cad.reason}», paso {paso} "
                        "de seguimiento. Configure cadences.toml."
                    )
                    out.append(Outgoing(ctos[0].telegram_id, msg))
                repo.set_meta(conn, notice_key, to_iso(now))
            continue

        # e. Aprobador: comercial asignado si activo, o CTO activo
        recipients = permissions.commercial_recipients(lead, repo.active_users(conn))
        if not recipients:
            continue
        approver = recipients[0]

        # f. Crear propuesta
        expires_at = now + gate.GATE_DEADLINE
        proposal_id = repo.insert_proposal(
            conn,
            lead_id=cad.lead_id,
            kind=ProposalKind.FOLLOWUP,
            step=paso,
            approver_user_id=approver.id,
            expires_at=expires_at,
            created_at=now,
        )
        if proposal_id is None:
            continue

        # g. Versión 1
        subject = (texts.subject(cad.reason) if texts else None) or "Seguimiento"
        client_name = lead.name or lead.company or ""
        body_text = followup_text.render(text, name=client_name, commercial="")
        full_body = f"{body_text}\n\n{followup_text.footer(sender_name)}"
        chash = delivery.content_hash(subject, full_body)

        repo.add_proposal_version(
            conn,
            proposal_id=proposal_id,
            version=1,
            subject=subject,
            body=full_body,
            content_hash=chash,
            author_user_id=approver.id,
            created_at=now,
        )

        # h. Cadencia esperando decisión
        repo.update_cadence(conn, cad.lead_id, next_action_at=None, updated_at=to_iso(now))

        # i. Presentación con botones ✅/❌
        out.extend(gate.present(conn, proposal_id))

    return out
