"""Pruebas unitarias de cadencias puras y de servicio (F2-T06, F2-T12).
VCRM-018..026, 032, 034, 121.

Módulo puro y pruebas de integración con SQLite para el servicio de cadencias.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jerico.crm import followup, leads, repo
from jerico.crm.cadence import (
    DEFAULT_CADENCE_MATRIX,
    CadenceRow,
    after_step,
    first_action,
    frequency_days,
    next_action_on_frequency,
    row_for,
)
from jerico.crm.db import CrmDatabase
from jerico.crm.leads import REJECT_REASONS
from jerico.crm.model import (
    SYSTEM_USER_ID,
    AuditAction,
    AuditDetail,
    AuditOutcome,
    AuthStatus,
    Cadence,
    CadenceStatus,
    LeadState,
    ProposalKind,
    Role,
    User,
)
from jerico.crm.timeutil import from_iso, to_iso

T0 = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)


def test_vcrm018_matriz_por_motivo() -> None:
    """VCRM-018 y plan-f2 §5.2: la matriz por defecto cubre todos los motivos de REJECT_REASONS.

    Cada motivo tiene 3 pasos, intervalo de 30 días y su tipo de contenido definido.
    """
    assert set(DEFAULT_CADENCE_MATRIX.keys()) == set(REJECT_REASONS.keys())

    for reason in REJECT_REASONS:
        row = row_for(reason)
        assert isinstance(row, CadenceRow)
        assert row.reason == reason
        assert row.steps == 3
        assert row.total_steps == 3
        assert row.interval_days == 30
        assert isinstance(row.content_type, str)
        assert len(row.content_type) > 0

    assert "propuesta de valor" in row_for("precio").content_type
    assert "recordatorio" in row_for("momento").content_type
    assert "contenido educativo" in row_for("proveedor").content_type
    assert "contenido educativo" in row_for("no_interesado").content_type
    assert "genérico" in row_for("otro").content_type

    # Cálculo de primera acción con el intervalo de la fila
    next_act = first_action(T0, row_for("precio").interval_days)
    assert next_act == T0 + timedelta(days=30)


def test_vcrm022_reanudar_desde_ahora() -> None:
    """VCRM-022: al reanudar una cadencia pausada, la próxima acción se calcula desde `now`.

    No genera acciones omitidas durante la pausa.
    """
    now = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    interval = 30
    resumed_next = first_action(now, interval)
    assert resumed_next == now + timedelta(days=30)

    # Con frecuencia semanal reanudada
    resumed_weekly = first_action(now, frequency_days("weekly"))
    assert resumed_weekly == now + timedelta(days=7)


def test_vcrm023_frecuencia_desde_ultimo_envio() -> None:
    """VCRM-023: al cambiar frecuencia con envío previo, recalcula desde el último envío."""
    assert frequency_days("weekly") == 7
    assert frequency_days("monthly") == 30

    now = datetime(2026, 2, 15, 12, 0, tzinfo=UTC)
    last_sent_at = datetime(2026, 2, 10, 8, 30, tzinfo=UTC)

    # Cambio a mensual desde último envío
    next_monthly = next_action_on_frequency(
        now, frequency_days("monthly"), last_sent_at=last_sent_at
    )
    assert next_monthly == last_sent_at + timedelta(days=30)

    # Cambio a semanal desde último envío
    next_weekly = next_action_on_frequency(now, frequency_days("weekly"), last_sent_at=last_sent_at)
    assert next_weekly == last_sent_at + timedelta(days=7)


def test_vcrm023_sin_envio_desde_cambio() -> None:
    """VCRM-023: cambio de frecuencia sin envíos previos recalcula desde la fecha-hora."""
    now = datetime(2026, 2, 15, 12, 0, tzinfo=UTC)

    next_weekly = next_action_on_frequency(now, frequency_days("weekly"), last_sent_at=None)
    assert next_weekly == now + timedelta(days=7)

    next_monthly = next_action_on_frequency(now, frequency_days("monthly"), last_sent_at=None)
    assert next_monthly == now + timedelta(days=30)


def test_vcrm026_ultimo_paso_completa() -> None:
    """VCRM-026: al completar el último paso (paso 3 de 3), la cadencia finaliza.

    Queda sin próxima acción (None), completed=True y status='completed'.
    """
    now = datetime(2026, 4, 1, 9, 0, tzinfo=UTC)

    # Si se completan 2 pasos previos y se consume el 3º con éxito ("sent")
    res = after_step(
        steps_done=2,
        total_steps=3,
        interval=30,
        now=now,
        outcome="sent",
        sent_count=2,
    )
    assert res.steps_done == 3
    assert res.total_steps == 3
    assert res.completed is True
    assert res.status == "completed"
    assert res.next_action_at is None
    assert res.sent_count == 3
    assert res.last_sent_at == now

    # Si se consume el 3º por cancelación
    res_cancel = after_step(
        steps_done=2,
        total_steps=3,
        interval=30,
        now=now,
        outcome="cancelled",
        sent_count=2,
    )
    assert res_cancel.steps_done == 3
    assert res_cancel.completed is True
    assert res_cancel.status == "completed"
    assert res_cancel.next_action_at is None
    assert res_cancel.sent_count == 2


def test_vcrm032_cancelar_salta_paso() -> None:
    """VCRM-032: cancelar envío salta al paso siguiente programando `now + interval`.

    No incrementa sent_count ni actualiza last_sent_at.
    """
    now = datetime(2026, 2, 1, 10, 0, tzinfo=UTC)
    prev_sent_at = datetime(2026, 1, 2, 10, 0, tzinfo=UTC)

    res = after_step(
        steps_done=1,
        total_steps=3,
        interval=30,
        now=now,
        outcome="cancelled",
        sent_count=1,
        last_sent_at=prev_sent_at,
    )
    assert res.steps_done == 2
    assert res.completed is False
    assert res.status == "active"
    assert res.next_action_at == now + timedelta(days=30)
    assert res.sent_count == 1
    assert res.last_sent_at == prev_sent_at


def test_vcrm034_expirar_salta_paso() -> None:
    """VCRM-034: expiración de la propuesta salta al paso siguiente como una cancelación."""
    now = datetime(2026, 2, 3, 10, 0, tzinfo=UTC)

    res = after_step(
        steps_done=0,
        total_steps=3,
        interval=30,
        now=now,
        outcome="expired",
        sent_count=0,
    )
    assert res.steps_done == 1
    assert res.completed is False
    assert res.status == "active"
    assert res.next_action_at == now + timedelta(days=30)
    assert res.sent_count == 0
    assert res.last_sent_at is None


def test_cadence_invalid_inputs() -> None:
    """Casos de error y tipos de entrada en cadence.py."""
    with pytest.raises(KeyError):
        row_for("motivo_inexistente")

    with pytest.raises(ValueError):
        frequency_days("biweekly")

    with pytest.raises(ValueError):
        after_step(steps_done=0, total_steps=3, interval=30, now=T0, outcome="desconocido")

    # first_action acepta timedelta directamente
    assert first_action(T0, timedelta(days=15)) == T0 + timedelta(days=15)

    # after_step cuando steps_done ya es >= total_steps
    res = after_step(steps_done=3, total_steps=3, interval=30, now=T0)
    assert res.completed is True
    assert res.steps_done == 3
    assert res.next_action_at is None


# ==============================================================================================
# F2-T12: Servicio de cadencias de seguimiento (VCRM-018..026, 121)
# ==============================================================================================


def _setup_db(
    tmp_path: Path, *, activate_f2: bool = True
) -> tuple[CrmDatabase, User, User, User, User]:
    db = CrmDatabase(tmp_path / "cadence_service.db")
    with db.tx() as conn:
        cto = repo.insert_user(conn, telegram_id=1000, role=Role.CTO, email="cto@k.ai", now=T0)
        com = repo.insert_user(
            conn, telegram_id=2000, role=Role.COMMERCIAL, email="com@k.ai", now=T0
        )
        com2 = repo.insert_user(
            conn, telegram_id=2100, role=Role.COMMERCIAL, email="com2@k.ai", now=T0
        )
        law = repo.insert_user(conn, telegram_id=3000, role=Role.LAWYER, email="law@k.ai", now=T0)
        if activate_f2:
            repo.set_meta(conn, "f2_activated_at", to_iso(T0))
    return db, cto, com, com2, law


def _create_lead(
    db: CrmDatabase,
    user_id: int | None,
    *,
    state: LeadState = LeadState.NEW,
    authorized: bool = False,
    reject_reason: str | None = None,
) -> int:
    with db.tx() as conn:
        lead_id = repo.insert_lead(
            conn,
            assigned_user_id=user_id,
            state=state,
            now=T0,
            fields={
                "name": "Cliente Cadencia",
                "phone_e164": "+573001234567",
                "email": "lead@cadencia.com",
            },
        )
        if reject_reason:
            repo.update_lead(conn, lead_id, {"reject_reason": reject_reason}, now=T0)
        if authorized:
            repo.update_lead(conn, lead_id, {"auth_status": AuthStatus.AUTHORIZED.value}, now=T0)
            repo.insert_consent(
                conn,
                lead_id=lead_id,
                status=AuthStatus.AUTHORIZED,
                medium="email",
                at=T0,
                actor_user_id=user_id or 1,
            )
    return lead_id


def test_vcrm018_rechazo_con_autorizacion_crea_cadencia(tmp_path: Path) -> None:
    """VCRM-018: rechazo con autorización vigente crea cadencia activa y pasa a NURTURING."""
    db, _, com, _, _ = _setup_db(tmp_path, activate_f2=True)
    lead_id = _create_lead(db, com.id, state=LeadState.CONTACTED, authorized=True)

    with db.tx() as conn:
        # Rechazar lead con motivo 'precio'
        out = leads.transition(conn, com, lead_id, LeadState.REJECTED, now=T0, reason="precio")
        lead = repo.get_lead(conn, lead_id)
        assert lead is not None
        # Lead pasa a NURTURING por el gancho de cadencia
        assert lead.state == LeadState.NURTURING.value
        cad = repo.get_cadence(conn, lead_id)
        assert cad is not None
        assert cad.status == CadenceStatus.ACTIVE.value
        assert cad.reason == "precio"
        assert cad.interval_days == 30
        assert from_iso(cad.next_action_at or "") == T0 + timedelta(days=30)
        assert any("cadencia" in m.text.lower() or "nutrición" in m.text.lower() for m in out)
    db.close()


def test_el_cambio_automatico_a_nutricion_se_atribuye_al_sistema(tmp_path: Path) -> None:
    """El paso a «en nutrición» lo hace el sistema: no se inventa un usuario como autor."""
    db, _, com, _, _ = _setup_db(tmp_path, activate_f2=True)
    lead_id = _create_lead(db, com.id, state=LeadState.CONTACTED, authorized=True)
    with db.tx() as conn:
        leads.transition(conn, com, lead_id, LeadState.REJECTED, now=T0, reason="precio")
        events = conn.execute(
            "SELECT actor_user_id FROM crm_lead_events WHERE lead_id = ? AND kind = 'state' "
            "AND new_value = 'nurturing'",
            (lead_id,),
        ).fetchall()
    assert [row["actor_user_id"] for row in events] == [SYSTEM_USER_ID]
    db.close()


def test_vcrm019_rechazo_sin_autorizacion_avisa(tmp_path: Path) -> None:
    """VCRM-019: rechazo sin autorización no crea cadencia y avisa al comercial (o CTO)."""
    db, cto, com, _, _ = _setup_db(tmp_path, activate_f2=True)
    lead_id = _create_lead(db, com.id, state=LeadState.CONTACTED, authorized=False)

    with db.tx() as conn:
        out = leads.transition(conn, com, lead_id, LeadState.REJECTED, now=T0, reason="precio")
        lead = repo.get_lead(conn, lead_id)
        assert lead is not None
        # Queda en REJECTED sin cadencia
        assert lead.state == LeadState.REJECTED.value
        assert repo.get_cadence(conn, lead_id) is None
        # Aviso al comercial indicando falta de autorización y comando /autorizacion
        assert any(m.chat_id == com.telegram_id and "/autorizacion" in m.text for m in out)

    # Lead sin comercial asignado avisa al CTO
    lead_no_com = _create_lead(db, None, state=LeadState.CONTACTED, authorized=False)
    with db.tx() as conn:
        out_cto = leads.transition(
            conn, cto, lead_no_com, LeadState.REJECTED, now=T0, reason="momento"
        )
        lead2 = repo.get_lead(conn, lead_no_com)
        assert lead2 is not None and lead2.state == LeadState.REJECTED.value
        assert repo.get_cadence(conn, lead_no_com) is None
        assert any(m.chat_id == cto.telegram_id and "/autorizacion" in m.text for m in out_cto)
    db.close()


def test_vcrm020_pausar_cancela_pendientes(tmp_path: Path) -> None:
    """VCRM-020: pausar pasa a PAUSED y cancela propuestas de seguimiento y envíos scheduled."""
    db, _, com, _, _ = _setup_db(tmp_path, activate_f2=True)
    lead_id = _create_lead(
        db, com.id, state=LeadState.REJECTED, authorized=True, reject_reason="precio"
    )

    with db.tx() as conn:
        lead = repo.get_lead(conn, lead_id)
        assert lead is not None
        followup.start_cadence(conn, lead, T0)

        # Crear una propuesta y un envío programado
        p_id = repo.insert_proposal(
            conn,
            lead_id=lead_id,
            kind=ProposalKind.FOLLOWUP,
            step=1,
            approver_user_id=com.id,
            expires_at=T0 + timedelta(hours=48),
            created_at=T0,
        )
        assert p_id is not None
        s_id = repo.insert_send(
            conn,
            proposal_id=p_id,
            version=1,
            approved_hash="hash",
            approved_by=com.id,
            approved_at=T0,
            scheduled_at=T0 + timedelta(days=1),
            lead_id=lead_id,
            week_start=T0,
        )

        out = followup.pause(conn, com, lead_id, T0 + timedelta(days=5))
        lead_up = repo.get_lead(conn, lead_id)
        assert lead_up is not None and lead_up.state == LeadState.PAUSED.value
        cad = repo.get_cadence(conn, lead_id)
        assert cad is not None and cad.status == CadenceStatus.PAUSED.value

        # Propuesta y envío quedan cancelados
        prop = repo.get_proposal(conn, p_id)
        assert prop is not None and prop.status == "cancelled"
        send = repo.get_send(conn, s_id)
        assert send is not None and send.status == "cancelled"
        assert any("pausada" in m.text.lower() for m in out)
    db.close()


def test_vcrm021_pausado_no_genera(tmp_path: Path) -> None:
    """VCRM-021: due_cadences no devuelve cadencias en estado 'paused'."""
    db, _, com, _, _ = _setup_db(tmp_path, activate_f2=True)
    lead_id = _create_lead(
        db, com.id, state=LeadState.REJECTED, authorized=True, reject_reason="precio"
    )

    with db.tx() as conn:
        lead = repo.get_lead(conn, lead_id)
        assert lead is not None
        followup.start_cadence(conn, lead, T0)
        due = repo.due_cadences(conn, T0 + timedelta(days=35))
        assert len(due) == 1

        followup.pause(conn, com, lead_id, T0 + timedelta(days=1))
        # Cadencia pausada ya no aparece en due_cadences
        assert len(repo.due_cadences(conn, T0 + timedelta(days=35))) == 0
    db.close()


def test_vcrm022_reanudar_sin_omitidas(tmp_path: Path) -> None:
    """VCRM-022: reanudar pasa a NURTURING y calcula next_action_at = now + intervalo."""
    db, _, com, _, _ = _setup_db(tmp_path, activate_f2=True)
    lead_id = _create_lead(
        db, com.id, state=LeadState.REJECTED, authorized=True, reject_reason="precio"
    )

    with db.tx() as conn:
        lead = repo.get_lead(conn, lead_id)
        assert lead is not None
        followup.start_cadence(conn, lead, T0)
        followup.pause(conn, com, lead_id, T0 + timedelta(days=2))

        resume_time = T0 + timedelta(days=40)
        out = followup.resume(conn, com, lead_id, resume_time)

        lead_up = repo.get_lead(conn, lead_id)
        assert lead_up is not None and lead_up.state == LeadState.NURTURING.value
        cad = repo.get_cadence(conn, lead_id)
        assert cad is not None
        assert cad.status == CadenceStatus.ACTIVE.value
        assert from_iso(cad.next_action_at or "") == resume_time + timedelta(days=30)
        assert any("reanudada" in m.text.lower() for m in out)
    db.close()


def test_vcrm023_frecuencia_semanal_mensual(tmp_path: Path) -> None:
    """VCRM-023: cambiar frecuencia recalcula next_action_at."""
    db, _, com, _, _ = _setup_db(tmp_path, activate_f2=True)
    lead_id = _create_lead(
        db, com.id, state=LeadState.REJECTED, authorized=True, reject_reason="precio"
    )

    with db.tx() as conn:
        lead = repo.get_lead(conn, lead_id)
        assert lead is not None
        followup.start_cadence(conn, lead, T0)

        # Cambio a weekly sin envíos previos recalcula desde now
        change_time = T0 + timedelta(days=2)
        out = followup.set_frequency(conn, com, lead_id, "weekly", change_time)
        cad = repo.get_cadence(conn, lead_id)
        assert cad is not None
        assert cad.interval_days == 7
        assert from_iso(cad.next_action_at or "") == change_time + timedelta(days=7)
        assert any("semanal" in m.text.lower() or "weekly" in m.text.lower() for m in out)

        # Simular un envío previo
        last_sent = T0 + timedelta(days=5)
        repo.update_cadence(conn, lead_id, last_sent_at=to_iso(last_sent))
        # Cambio a monthly con envío previo recalcula desde last_sent_at
        change_time_2 = T0 + timedelta(days=8)
        followup.set_frequency(conn, com, lead_id, "monthly", change_time_2)
        cad2 = repo.get_cadence(conn, lead_id)
        assert cad2 is not None
        assert cad2.interval_days == 30
        assert from_iso(cad2.next_action_at or "") == last_sent + timedelta(days=30)
    db.close()


def test_vcrm024_reactivado_detiene(tmp_path: Path) -> None:
    """VCRM-024: reactivar detiene cadencia y cancela pendientes."""
    db, _, com, _, _ = _setup_db(tmp_path, activate_f2=True)
    lead_id = _create_lead(
        db, com.id, state=LeadState.REJECTED, authorized=True, reject_reason="precio"
    )

    with db.tx() as conn:
        lead = repo.get_lead(conn, lead_id)
        assert lead is not None
        followup.start_cadence(conn, lead, T0)

        p_id = repo.insert_proposal(
            conn,
            lead_id=lead_id,
            kind=ProposalKind.FOLLOWUP,
            step=1,
            approver_user_id=com.id,
            expires_at=T0 + timedelta(hours=48),
            created_at=T0,
        )

        out = followup.reactivate(conn, com, lead_id, T0 + timedelta(days=3))
        lead_up = repo.get_lead(conn, lead_id)
        assert lead_up is not None and lead_up.state == LeadState.REACTIVATED.value
        cad = repo.get_cadence(conn, lead_id)
        assert cad is not None
        assert cad.status == CadenceStatus.STOPPED.value
        assert cad.next_action_at is None

        prop = repo.get_proposal(conn, p_id or 0)
        assert prop is not None and prop.status == "cancelled"
        assert any("reactivado" in m.text.lower() for m in out)
    db.close()


def test_vcrm026_ultimo_paso_avisa_sin_perder(tmp_path: Path) -> None:
    """VCRM-026: al completar el último paso avisa con botones «Marcar perdido» y «Reactivar»."""
    db, _, com, _, _ = _setup_db(tmp_path, activate_f2=True)
    lead_id = _create_lead(
        db, com.id, state=LeadState.REJECTED, authorized=True, reject_reason="precio"
    )

    with db.tx() as conn:
        lead = repo.get_lead(conn, lead_id)
        assert lead is not None
        followup.start_cadence(conn, lead, T0)

        # Consumir paso 1 y 2
        followup.on_step_consumed(conn, lead_id, "sent", T0 + timedelta(days=30))
        followup.on_step_consumed(conn, lead_id, "sent", T0 + timedelta(days=60))

        # Consumir paso 3 (último)
        out = followup.on_step_consumed(conn, lead_id, "sent", T0 + timedelta(days=90))
        cad = repo.get_cadence(conn, lead_id)
        assert cad is not None
        assert cad.status == CadenceStatus.COMPLETED.value
        assert cad.steps_done == 3
        assert cad.next_action_at is None

        # Lead sigue en NURTURING sin perderse
        lead_up = repo.get_lead(conn, lead_id)
        assert lead_up is not None and lead_up.state == LeadState.NURTURING.value

        # Aviso al comercial con botones
        assert len(out) == 1
        msg = out[0]
        assert msg.chat_id == com.telegram_id
        flattened_callbacks = [cb for row in msg.buttons for _, cb in row]
        assert any("cperdido" in cb for cb in flattened_callbacks)
        assert any("creactivar" in cb for cb in flattened_callbacks)
    db.close()


def test_vcrm121_autorizar_rechazado_crea_cadencia(tmp_path: Path) -> None:
    """VCRM-121: registrar autorización en lead REJECTED inicia cadencia."""
    db, _, com, _, _ = _setup_db(tmp_path, activate_f2=True)
    # Lead rechazado con motivo 'momento' pero sin autorización
    lead_id = _create_lead(
        db, com.id, state=LeadState.REJECTED, authorized=False, reject_reason="momento"
    )

    with db.tx() as conn:
        assert repo.get_cadence(conn, lead_id) is None
        # Simular autorización (consentimiento + update lead)
        repo.insert_consent(
            conn,
            lead_id=lead_id,
            status=AuthStatus.AUTHORIZED,
            medium="email",
            at=T0,
            actor_user_id=com.id,
        )
        repo.update_lead(conn, lead_id, {"auth_status": AuthStatus.AUTHORIZED.value}, now=T0)

        # start_cadence tras registrar autorización
        lead = repo.get_lead(conn, lead_id)
        assert lead is not None
        out = followup.start_cadence(conn, lead, T0)
        assert len(out) >= 1

        lead_up = repo.get_lead(conn, lead_id)
        assert lead_up is not None and lead_up.state == LeadState.NURTURING.value
        cad = repo.get_cadence(conn, lead_id)
        assert cad is not None and cad.status == CadenceStatus.ACTIVE.value
        assert cad.reason == "momento"
    db.close()


def test_f1_hooks_inert_without_f2_activation(tmp_path: Path) -> None:
    """Sin f2_activated_at los ganchos no crean cadencias (comportamiento F1 intacto)."""
    db, _, com, _, _ = _setup_db(tmp_path, activate_f2=False)
    lead_id = _create_lead(db, com.id, state=LeadState.CONTACTED, authorized=True)

    with db.tx() as conn:
        assert not followup.f2_active(conn)
        leads.transition(conn, com, lead_id, LeadState.REJECTED, now=T0, reason="precio")
        lead = repo.get_lead(conn, lead_id)
        assert lead is not None and lead.state == LeadState.REJECTED.value
        assert repo.get_cadence(conn, lead_id) is None
    db.close()


def test_cadence_permissions(tmp_path: Path) -> None:
    """Permisos: abogado denegado, comercial ajeno denegado con auditoría, CTO permitido."""
    db, cto, com, com2, law = _setup_db(tmp_path, activate_f2=True)
    lead_id = _create_lead(
        db, com.id, state=LeadState.REJECTED, authorized=True, reject_reason="precio"
    )

    with db.tx() as conn:
        lead = repo.get_lead(conn, lead_id)
        assert lead is not None
        followup.start_cadence(conn, lead, T0)

        # Abogado denegado
        out_law = followup.pause(conn, law, lead_id, T0)
        assert any("no tiene permiso" in m.text.lower() for m in out_law)

        # Comercial ajeno denegado y auditado (foreign_lead)
        out_com2 = followup.pause(conn, com2, lead_id, T0)
        assert any("no tiene acceso" in m.text.lower() for m in out_com2)
        # Auditoría registrada
        audit_rows = conn.execute(
            """SELECT * FROM crm_audit
            WHERE action = ? AND outcome = ? AND lead_id = ? AND detail_code = ?""",
            (
                AuditAction.PERMISSION_DENIED.value,
                AuditOutcome.DENIED.value,
                lead_id,
                AuditDetail.FOREIGN_LEAD.value,
            ),
        ).fetchall()
        assert len(audit_rows) == 1

        # CTO permitido
        out_cto = followup.pause(conn, cto, lead_id, T0)
        cad = repo.get_cadence(conn, lead_id)
        assert cad is not None and cad.status == CadenceStatus.PAUSED.value
        assert any("pausada" in m.text.lower() for m in out_cto)
    db.close()


def test_start_cadence_idempotent_and_unknown_reason(tmp_path: Path) -> None:
    """Idempotencia de start_cadence y fallback a 'otro' para motivo desconocido."""
    db, _, com, _, _ = _setup_db(tmp_path, activate_f2=True)
    lead_id = _create_lead(
        db, com.id, state=LeadState.REJECTED, authorized=True, reject_reason="motivo_raro"
    )

    with db.tx() as conn:
        lead = repo.get_lead(conn, lead_id)
        assert lead is not None
        out1 = followup.start_cadence(conn, lead, T0)
        assert len(out1) == 1
        cad = repo.get_cadence(conn, lead_id)
        assert cad is not None
        assert cad.reason == "otro"

        # Segunda llamada es no-op
        out2 = followup.start_cadence(conn, lead, T0)
        assert out2 == []
    db.close()


def test_cadence_operations_on_missing_cadence(tmp_path: Path) -> None:
    """Operaciones sobre lead sin cadencia responden claramente sin excepción."""
    db, _, com, _, _ = _setup_db(tmp_path, activate_f2=True)
    lead_id = _create_lead(db, com.id, state=LeadState.NEW, authorized=True)

    with db.tx() as conn:
        assert followup.pause(conn, com, lead_id, T0)[0].text != ""
        assert followup.resume(conn, com, lead_id, T0)[0].text != ""
        assert followup.set_frequency(conn, com, lead_id, "weekly", T0)[0].text != ""
        assert followup.on_step_consumed(conn, lead_id, "sent", T0) == []
    db.close()


def test_cadence_edge_cases_and_missing_leads(tmp_path: Path) -> None:
    """Cubre ramas de lead inexistente, transiciones inválidas y avisos sin comercial."""
    db, cto, com, _, other = _setup_db(tmp_path, activate_f2=True)

    # 1. Start cadence sin F2 activo
    db_no_f2, _, _, _, _ = _setup_db(tmp_path / "nof2", activate_f2=False)
    l_nof2 = _create_lead(db_no_f2, com.id, state=LeadState.REJECTED, authorized=True)
    with db_no_f2.tx() as conn:
        lead_nof2_obj = repo.get_lead(conn, l_nof2)
        assert lead_nof2_obj is not None
        assert followup.start_cadence(conn, lead_nof2_obj, T0) == []
    db_no_f2.close()

    # 2. Leads para pruebas de permisos y estados
    l_new = _create_lead(db, com.id, state=LeadState.NEW, authorized=True)
    l_no_com = _create_lead(
        db, None, state=LeadState.REJECTED, authorized=True, reject_reason="precio"
    )

    with db.tx() as conn:
        # Lead inexistente en cada operación
        assert "no existe" in followup.pause(conn, com, 99999, T0)[0].text
        assert "no existe" in followup.resume(conn, com, 99999, T0)[0].text
        assert "no existe" in followup.set_frequency(conn, com, 99999, "weekly", T0)[0].text
        assert "no existe" in followup.reactivate(conn, com, 99999, T0)[0].text
        assert followup.on_step_consumed(conn, 99999, "sent", T0) == []

        # Permisos denegados por otro comercial (Action.MANAGE_CADENCE)
        # Crear cadencia para l_new
        cad = Cadence(
            lead_id=l_new,
            reason="otro",
            interval_days=30,
            total_steps=3,
            started_at=to_iso(T0),
            updated_at=to_iso(T0),
        )
        repo.upsert_cadence(conn, cad)
        # other intentando pause, resume, set_frequency, reactivate
        assert (
            "no tiene permiso" in followup.pause(conn, other, l_new, T0)[0].text.lower()
            or "no_access" in followup.pause(conn, other, l_new, T0)[0].text.lower()
        )
        assert (
            "no tiene permiso" in followup.resume(conn, other, l_new, T0)[0].text.lower()
            or "no_access" in followup.resume(conn, other, l_new, T0)[0].text.lower()
        )
        assert (
            "no tiene permiso"
            in followup.set_frequency(conn, other, l_new, "weekly", T0)[0].text.lower()
            or "no_access"
            in followup.set_frequency(conn, other, l_new, "weekly", T0)[0].text.lower()
        )
        assert (
            "no tiene permiso" in followup.reactivate(conn, other, l_new, T0)[0].text.lower()
            or "no_access" in followup.reactivate(conn, other, l_new, T0)[0].text.lower()
        )

        # Lead en NEW con cadencia: no se puede pausar ni reanudar
        assert "no se puede pausar" in followup.pause(conn, com, l_new, T0)[0].text.lower()
        assert "no se puede reanudar" in followup.resume(conn, com, l_new, T0)[0].text.lower()

        # Reactivar lead en estado no permitido (ej. WON)
        repo.update_lead(conn, l_new, {"state": LeadState.WON.value}, now=T0)
        assert "no se puede reactivar" in followup.reactivate(conn, com, l_new, T0)[0].text.lower()

        # set_frequency en estado no permitido (ej. COMPLETED)
        repo.update_cadence(conn, l_new, status=CadenceStatus.COMPLETED.value)
        assert (
            "no se puede cambiar la frecuencia"
            in followup.set_frequency(conn, com, l_new, "weekly", T0)[0].text.lower()
        )

        # Lead autorizado sin comercial asignado: start_cadence notifica al CTO
        lead_no_com_obj = repo.get_lead(conn, l_no_com)
        assert lead_no_com_obj is not None
        out_start = followup.start_cadence(conn, lead_no_com_obj, T0)
        assert len(out_start) == 1 and out_start[0].chat_id == cto.telegram_id

        # on_step_consumed completado en lead sin comercial: notifica al CTO con botones
        followup.on_step_consumed(conn, l_no_com, "sent", T0)
        followup.on_step_consumed(conn, l_no_com, "sent", T0)
        out_comp = followup.on_step_consumed(conn, l_no_com, "sent", T0)
        assert len(out_comp) == 1 and out_comp[0].chat_id == cto.telegram_id

    # 3. Lead sin comercial y sin usuarios activos (ramas chat_id is None)
    db_no_user, _, _, _, _ = _setup_db(tmp_path / "nouser", activate_f2=True)
    l_orphan = _create_lead(
        db_no_user, None, state=LeadState.REJECTED, authorized=True, reject_reason="precio"
    )
    l_unauth = _create_lead(
        db_no_user, None, state=LeadState.REJECTED, authorized=False, reject_reason="precio"
    )
    with db_no_user.tx() as conn:
        conn.execute("UPDATE crm_users SET active = 0")
        lead_orphan_obj = repo.get_lead(conn, l_orphan)
        assert lead_orphan_obj is not None
        assert followup.start_cadence(conn, lead_orphan_obj, T0) == []

        lead_unauth_obj = repo.get_lead(conn, l_unauth)
        assert lead_unauth_obj is not None
        assert followup.start_cadence(conn, lead_unauth_obj, T0) == []
    db_no_user.close()
    db.close()
