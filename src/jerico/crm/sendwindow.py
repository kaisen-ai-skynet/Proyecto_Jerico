"""Franja de envío, festivos y cupo semanal (VCRM-072, 076, 100, 101; plan-f2 §5.1).

Módulo puro, sin E/S ni reloj interno. Implementa los topes legales de la Ley 2300 de 2023 que el
CTO fijó como conservadores también para B2B (J-11): lunes a viernes de 07:00 a 19:00 y sábados de
08:00 a 15:00 en hora de Colombia, sin domingos ni festivos, y un contacto por lead y semana
calendario. La franja configurada solo puede ESTRECHAR la legal, nunca ampliarla (VCRM-162).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from jerico.crm.timeutil import BOGOTA, colombian_holidays, local_date

_NO_EXTRA: frozenset[date] = frozenset()
_SATURDAY = 5
_SUNDAY = 6
_MAX_SEARCH_DAYS = 400  # holgura enorme: con festivos reales siempre hay un día hábil en <= 5
_MAX_SCHEDULE_WEEKS = 104


@dataclass(frozen=True)
class Window:
    """Horas locales de apertura y cierre (cierre excluido). Debe caber en la franja legal."""

    weekday_open: int = 7
    weekday_close: int = 19
    saturday_open: int = 8
    saturday_close: int = 15

    def __post_init__(self) -> None:
        within_legal = (
            7 <= self.weekday_open < self.weekday_close <= 19
            and 8 <= self.saturday_open < self.saturday_close <= 15
        )
        if not within_legal:
            raise ValueError("la franja de envío debe quedar dentro de la franja legal")


LEGAL_WINDOW = Window()


def _is_open_day(d: date, extra: frozenset[date]) -> bool:
    return d.weekday() != _SUNDAY and d not in colombian_holidays(d.year) and d not in extra


def _hours(d: date, window: Window) -> tuple[int, int]:
    if d.weekday() == _SATURDAY:
        return window.saturday_open, window.saturday_close
    return window.weekday_open, window.weekday_close


def allowed(
    at: datetime, extra: frozenset[date] = _NO_EXTRA, window: Window = LEGAL_WINDOW
) -> bool:
    """¿Se puede enviar en el instante `at`? (`at` con zona; se evalúa en hora de Bogotá)."""
    d = local_date(at)
    if not _is_open_day(d, extra):
        return False
    local = at.astimezone(BOGOTA)
    opens, closes = _hours(d, window)
    return time(opens) <= local.timetz().replace(tzinfo=None) < time(closes)


def next_slot(
    at: datetime, extra: frozenset[date] = _NO_EXTRA, window: Window = LEGAL_WINDOW
) -> datetime:
    """Primer instante >= `at` dentro de la franja, en hora de Bogotá (VCRM-100)."""
    if allowed(at, extra, window):
        return at.astimezone(BOGOTA)
    local = at.astimezone(BOGOTA)
    day = local.date()
    for offset in range(_MAX_SEARCH_DAYS):
        candidate = day + timedelta(days=offset)
        if not _is_open_day(candidate, extra):
            continue
        opens, _ = _hours(candidate, window)
        slot = datetime.combine(candidate, time(opens), tzinfo=BOGOTA)
        if slot >= local:
            return slot
    raise ValueError("no hay franja de envío disponible")  # pragma: no cover - inalcanzable


def week_start(at: datetime) -> datetime:
    """Lunes 00:00 (Bogotá) de la semana calendario de `at` (VCRM-076)."""
    d = local_date(at)
    monday = d - timedelta(days=d.weekday())
    return datetime.combine(monday, time(0), tzinfo=BOGOTA)


def schedule(
    now: datetime,
    sends_in_week: Callable[[datetime], int],
    limit: int,
    extra: frozenset[date] = _NO_EXTRA,
    window: Window = LEGAL_WINDOW,
) -> datetime:
    """Primer instante de envío en franja y con cupo semanal libre (VCRM-100, 101).

    `sends_in_week(week_start)` cuenta los contactos del lead (programados y enviados) en esa
    semana. Si la semana está llena, se pasa a la primera franja de la semana siguiente.
    """
    if limit < 1:
        raise ValueError("limit debe ser >= 1")
    candidate = next_slot(now, extra, window)
    for _ in range(_MAX_SCHEDULE_WEEKS):
        start = week_start(candidate)
        if sends_in_week(start) < limit:
            return candidate
        candidate = next_slot(start + timedelta(days=7), extra, window)
    raise ValueError(f"sin cupo en {_MAX_SCHEDULE_WEEKS} semanas")
