"""Pruebas unitarias de cadencias puras (F2-T06; VCRM-018, 022, 023, 026, 032, 034).

Módulo puro sin E/S ni reloj del sistema.
"""

from datetime import UTC, datetime, timedelta

import pytest

from jerico.crm.cadence import (
    DEFAULT_CADENCE_MATRIX,
    CadenceRow,
    after_step,
    first_action,
    frequency_days,
    next_action_on_frequency,
    row_for,
)
from jerico.crm.leads import REJECT_REASONS

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
    next_weekly = next_action_on_frequency(
        now, frequency_days("weekly"), last_sent_at=last_sent_at
    )
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
