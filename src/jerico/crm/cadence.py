"""Lógica pura de cadencias de nutrición y seguimiento (plan-f2 §5.2).

Requisitos: VCRM-018, 022, 023, 026, 032, 034 (cálculo de fechas y estados).
Módulo puro sin E/S ni llamadas a `datetime.now()` (recibe `now` por parámetro).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

VALID_OUTCOMES = frozenset({"sent", "cancelled", "expired"})
StepOutcome = Literal["sent", "cancelled", "expired"]


@dataclass(frozen=True)
class CadenceRow:
    """Definición de una cadencia por motivo de rechazo en la matriz."""

    reason: str
    total_steps: int = 3
    interval_days: int = 30
    content_type: str = ""

    @property
    def steps(self) -> int:
        """Alias de `total_steps` para compatibilidad."""
        return self.total_steps


@dataclass(frozen=True)
class StepResult:
    """Resultado del avance o consumo de un paso de cadencia."""

    steps_done: int
    total_steps: int
    sent_count: int
    status: str
    next_action_at: datetime | None
    completed: bool
    last_sent_at: datetime | None = None


# Alias para conveniencia de nomenclatura
CadenceStepResult = StepResult

# Matriz por defecto (plan-f2 §5.2, spec §4.6)
DEFAULT_CADENCE_MATRIX: dict[str, CadenceRow] = {
    "precio": CadenceRow(
        reason="precio",
        total_steps=3,
        interval_days=30,
        content_type="propuesta de valor (alcance y opciones)",
    ),
    "momento": CadenceRow(
        reason="momento",
        total_steps=3,
        interval_days=30,
        content_type="recordatorio",
    ),
    "proveedor": CadenceRow(
        reason="proveedor",
        total_steps=3,
        interval_days=30,
        content_type="contenido educativo",
    ),
    "no_interesado": CadenceRow(
        reason="no_interesado",
        total_steps=3,
        interval_days=30,
        content_type="contenido educativo",
    ),
    "otro": CadenceRow(
        reason="otro",
        total_steps=3,
        interval_days=30,
        content_type="genérico",
    ),
}

DEFAULT_CADENCES = DEFAULT_CADENCE_MATRIX


def row_for(reason: str) -> CadenceRow:
    """Devuelve la fila de configuración para el motivo en la matriz por defecto."""
    if reason not in DEFAULT_CADENCE_MATRIX:
        raise KeyError(f"Motivo no reconocido en matriz de cadencias: {reason}")
    return DEFAULT_CADENCE_MATRIX[reason]


def first_action(now: datetime, interval: int | timedelta) -> datetime:
    """Calcula la fecha-hora de la primera acción o próxima acción sumando el intervalo a `now`."""
    delta = timedelta(days=interval) if isinstance(interval, int) else interval
    return now + delta


def frequency_days(frequency: str) -> int:
    """Mapea la frecuencia ('weekly' o 'monthly') al número de días correspondiente."""
    match frequency:
        case "weekly":
            return 7
        case "monthly":
            return 30
        case _:
            msg = f"Frecuencia no admitida: {frequency!r} (debe ser 'weekly' o 'monthly')"
            raise ValueError(msg)


def next_action_on_frequency(
    now: datetime,
    interval: int | timedelta,
    last_sent_at: datetime | None = None,
) -> datetime:
    """Recalcula la próxima acción al cambiar frecuencia (VCRM-023).

    Si hubo envío previo al cliente, se calcula desde `last_sent_at`; si no, desde `now`.
    """
    base = last_sent_at if last_sent_at is not None else now
    return first_action(base, interval)


def after_step(
    steps_done: int,
    total_steps: int,
    interval: int | timedelta,
    now: datetime,
    outcome: str = "sent",
    *,
    sent_count: int = 0,
    last_sent_at: datetime | None = None,
) -> StepResult:
    """Calcula el nuevo estado de la cadencia tras consumir un paso (plan-f2 §5.2).

    Soporta los resultados: 'sent' (VCRM-029), 'cancelled' (VCRM-032) y 'expired' (VCRM-034).
    Al alcanzar el total de pasos completa la cadencia (VCRM-026).
    """
    if outcome not in VALID_OUTCOMES:
        raise ValueError(
            f"Resultado de paso no reconocido: {outcome!r} (admitidos: {sorted(VALID_OUTCOMES)})"
        )

    if steps_done < total_steps:
        new_steps = steps_done + 1
    else:
        new_steps = steps_done

    if outcome == "sent":
        new_sent_count = sent_count + 1
        new_last_sent_at: datetime | None = now
    else:
        new_sent_count = sent_count
        new_last_sent_at = last_sent_at

    is_completed = new_steps >= total_steps
    if is_completed:
        status = "completed"
        next_action_at = None
    else:
        status = "active"
        next_action_at = first_action(now, interval)

    return StepResult(
        steps_done=new_steps,
        total_steps=total_steps,
        sent_count=new_sent_count,
        status=status,
        next_action_at=next_action_at,
        completed=is_completed,
        last_sent_at=new_last_sent_at,
    )
