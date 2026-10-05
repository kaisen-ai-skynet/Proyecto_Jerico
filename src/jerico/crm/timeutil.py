"""Tiempo y calendario del CRM (VCRM-077; base de VCRM-150–152).

Se almacena en UTC y se calcula y presenta en America/Bogota. Festivos de Colombia
según la Ley 51 de 1983 («Ley Emiliani»), con implementación pura propia.
"""

import calendar
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Colombia no usa horario de verano desde 1993: el desfase fijo es un respaldo exacto.
_BOGOTA_FIXED = timezone(timedelta(hours=-5), "America/Bogota")


def _load_bogota() -> tzinfo:
    try:
        return ZoneInfo("America/Bogota")
    except ZoneInfoNotFoundError:
        return _BOGOTA_FIXED


BOGOTA = _load_bogota()


def _require_aware(dt: datetime) -> None:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("fecha-hora sin zona horaria (naive)")


def to_iso(dt: datetime) -> str:
    """Serializa en UTC con sufijo `Z`; rechaza fechas naive."""
    _require_aware(dt)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def from_iso(text: str) -> datetime:
    """Devuelve una fecha-hora UTC aware; rechaza textos sin zona."""
    dt = datetime.fromisoformat(text)
    _require_aware(dt)
    return dt.astimezone(UTC)


def local_date(dt: datetime) -> date:
    _require_aware(dt)
    return dt.astimezone(BOGOTA).date()


def format_local(dt: datetime) -> str:
    """`DD/MM/YYYY HH:mm` en hora de Bogotá."""
    _require_aware(dt)
    return dt.astimezone(BOGOTA).strftime("%d/%m/%Y %H:%M")


def easter(year: int) -> date:
    """Domingo de Pascua (algoritmo anónimo gregoriano de Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


def _next_monday(d: date) -> date:
    return d + timedelta(days=(7 - d.weekday()) % 7)


_FIXED = ((1, 1), (5, 1), (7, 20), (8, 7), (12, 8), (12, 25))
_MOVABLE = ((1, 6), (3, 19), (6, 29), (8, 15), (10, 12), (11, 1), (11, 11))


@lru_cache(maxsize=64)
def colombian_holidays(year: int) -> frozenset[date]:
    days = {date(year, m, d) for m, d in _FIXED}
    days |= {_next_monday(date(year, m, d)) for m, d in _MOVABLE}
    e = easter(year)
    days |= {e - timedelta(days=3), e - timedelta(days=2)}
    days |= {_next_monday(e + timedelta(days=n)) for n in (39, 60, 68)}
    return frozenset(days)


_NO_EXTRA: frozenset[date] = frozenset()


def is_business_day(d: date, extra: frozenset[date] = _NO_EXTRA) -> bool:
    """Lunes a viernes sin festivos calculados ni extraordinarios (`extra`, VCRM-167)."""
    return d.weekday() < 5 and d not in colombian_holidays(d.year) and d not in extra


def add_business_days(d: date, n: int, extra: frozenset[date] = _NO_EXTRA) -> date:
    """Cuenta `n` días hábiles desde el día hábil siguiente a `d`."""
    current, counted = d, 0
    while counted < n:
        current += timedelta(days=1)
        if is_business_day(current, extra):
            counted += 1
    return current


def business_days_between(a: date, b: date, extra: frozenset[date] = _NO_EXTRA) -> int:
    """Días hábiles en el intervalo (a, b]."""
    count, current = 0, a
    while current < b:
        current += timedelta(days=1)
        if is_business_day(current, extra):
            count += 1
    return count


def add_months(dt: datetime, n: int) -> datetime:
    """Suma meses de calendario en hora de Bogotá, con recorte a fin de mes."""
    _require_aware(dt)
    local = dt.astimezone(BOGOTA)
    year, month0 = divmod(local.month - 1 + n, 12)
    year += local.year
    day = min(local.day, calendar.monthrange(year, month0 + 1)[1])
    return local.replace(year=year, month=month0 + 1, day=day).astimezone(dt.tzinfo)


def add_years(dt: datetime, n: int) -> datetime:
    return add_months(dt, 12 * n)
