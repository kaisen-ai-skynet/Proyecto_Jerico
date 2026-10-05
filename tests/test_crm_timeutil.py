"""T02 — Tiempo, festivos de Colombia y días hábiles (VCRM-077; base de VCRM-150–152)."""

from datetime import UTC, date, datetime, timedelta, timezone
from zoneinfo import ZoneInfoNotFoundError

import pytest

from jerico.crm import timeutil
from jerico.crm.timeutil import (
    add_business_days,
    add_months,
    add_years,
    business_days_between,
    colombian_holidays,
    easter,
    format_local,
    from_iso,
    is_business_day,
    local_date,
    to_iso,
)

HOLIDAYS_2026 = {
    date(2026, 1, 1),
    date(2026, 1, 12),
    date(2026, 3, 23),
    date(2026, 4, 2),
    date(2026, 4, 3),
    date(2026, 5, 1),
    date(2026, 5, 18),
    date(2026, 6, 8),
    date(2026, 6, 15),
    date(2026, 6, 29),
    date(2026, 7, 20),
    date(2026, 8, 7),
    date(2026, 8, 17),
    date(2026, 10, 12),
    date(2026, 11, 2),
    date(2026, 11, 16),
    date(2026, 12, 8),
    date(2026, 12, 25),
}


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        (2024, date(2024, 3, 31)),
        (2025, date(2025, 4, 20)),
        (2026, date(2026, 4, 5)),
        (2027, date(2027, 3, 28)),
    ],
)
def test_vcrm077_easter_2024_2027(year: int, expected: date) -> None:
    assert easter(year) == expected


def test_vcrm077_colombian_holidays_2026_are_the_18_of_plan() -> None:
    assert colombian_holidays(2026) == frozenset(HOLIDAYS_2026)
    assert len(colombian_holidays(2026)) == 18


@pytest.mark.parametrize(
    "moved",
    [
        date(2027, 1, 11),  # Reyes (mié 6-ene) → lunes
        date(2027, 3, 22),  # San José (vie 19-mar) → lunes
        date(2027, 5, 10),  # Ascensión E+39 → lunes
        date(2027, 5, 31),  # Corpus Christi E+60 → lunes
        date(2027, 6, 7),  # Sagrado Corazón E+68 → lunes
        date(2027, 7, 5),  # San Pedro (mar 29-jun) → lunes
        date(2027, 8, 16),  # Asunción (dom 15-ago) → lunes
        date(2027, 10, 18),  # Día de la Raza (mar 12-oct) → lunes
        date(2027, 11, 1),  # Todos los Santos (ya lunes) → mismo día
        date(2027, 11, 15),  # Independencia de Cartagena (jue 11-nov) → lunes
    ],
)
def test_vcrm077_emiliani_moves_2027(moved: date) -> None:
    holidays = colombian_holidays(2027)
    assert moved in holidays
    assert moved.weekday() == 0


def test_vcrm077_emiliani_2027_original_dates_not_holidays() -> None:
    holidays = colombian_holidays(2027)
    for original in (date(2027, 1, 6), date(2027, 6, 29), date(2027, 10, 12)):
        assert original not in holidays
    assert {date(2027, 3, 25), date(2027, 3, 26)} <= holidays  # Jueves y Viernes Santo
    assert len(holidays) == 18


def test_vcrm150_is_business_day_weekend_and_holiday() -> None:
    assert is_business_day(date(2026, 1, 9))  # viernes laborable
    assert not is_business_day(date(2026, 1, 10))  # sábado
    assert not is_business_day(date(2026, 1, 11))  # domingo
    assert not is_business_day(date(2026, 1, 12))  # lunes festivo (Reyes)
    assert is_business_day(date(2026, 1, 13))


def test_vcrm150_add_business_days_counts_from_next_business_day() -> None:
    # Recepción el viernes 9-ene-2026, antes del lunes festivo 12-ene.
    friday = date(2026, 1, 9)
    assert add_business_days(friday, 1) == date(2026, 1, 13)
    assert add_business_days(friday, 2) == date(2026, 1, 14)
    assert add_business_days(friday, 10) == date(2026, 1, 26)
    assert add_business_days(friday, 0) == friday


def test_vcrm150_add_business_days_from_non_business_day() -> None:
    # Recepción en sábado: el primer día hábil siguiente es el martes 13-ene.
    assert add_business_days(date(2026, 1, 10), 1) == date(2026, 1, 13)
    # Semana Santa 2026: recepción miércoles 1-abr → jueves y viernes festivos.
    assert add_business_days(date(2026, 4, 1), 1) == date(2026, 4, 6)


def test_vcrm151_business_days_between_half_open_interval() -> None:
    friday = date(2026, 1, 9)
    assert business_days_between(friday, date(2026, 1, 12)) == 0
    assert business_days_between(friday, date(2026, 1, 14)) == 2
    assert business_days_between(friday, date(2026, 1, 26)) == 10
    assert business_days_between(friday, friday) == 0
    assert business_days_between(date(2026, 1, 26), friday) == 0


def test_vcrm150_business_days_round_trip_across_year_end() -> None:
    start = date(2026, 12, 22)
    end = add_business_days(start, 15)
    assert business_days_between(start, end) == 15
    assert date(2026, 12, 25) < end and end.year == 2027


def test_vcrm077_add_months_clips_to_month_end() -> None:
    dt = datetime(2026, 1, 31, 15, 0, tzinfo=UTC)  # 10:00 en Bogotá
    assert add_months(dt, 1) == datetime(2026, 2, 28, 15, 0, tzinfo=UTC)
    leap = datetime(2028, 1, 31, 15, 0, tzinfo=UTC)
    assert add_months(leap, 1) == datetime(2028, 2, 29, 15, 0, tzinfo=UTC)
    assert add_months(dt, 12) == datetime(2027, 1, 31, 15, 0, tzinfo=UTC)
    assert add_months(dt, -2) == datetime(2025, 11, 30, 15, 0, tzinfo=UTC)


def test_vcrm077_add_months_uses_bogota_calendar_day() -> None:
    # 1-mar 03:00 UTC es 28-feb 22:00 en Bogotá: el mes se suma sobre el día local.
    dt = datetime(2026, 3, 1, 3, 0, tzinfo=UTC)
    assert add_months(dt, 1) == datetime(2026, 3, 29, 3, 0, tzinfo=UTC)


def test_vcrm077_add_years_leap_day() -> None:
    dt = datetime(2028, 2, 29, 17, 0, tzinfo=UTC)
    assert add_years(dt, 1) == datetime(2029, 2, 28, 17, 0, tzinfo=UTC)
    assert add_years(dt, 4) == datetime(2032, 2, 29, 17, 0, tzinfo=UTC)


def test_vcrm077_calendar_arithmetic_rejects_naive() -> None:
    with pytest.raises(ValueError):
        add_months(datetime(2026, 1, 31, 10, 0), 1)


def test_vcrm077_to_iso_rejects_naive() -> None:
    with pytest.raises(ValueError):
        to_iso(datetime(2026, 1, 9, 10, 0))


def test_vcrm077_to_iso_stores_utc() -> None:
    local = datetime(2026, 1, 9, 10, 30, tzinfo=timeutil.BOGOTA)
    assert to_iso(local) == "2026-01-09T15:30:00Z"
    assert to_iso(datetime(2026, 1, 9, 15, 30, 0, 123456, tzinfo=UTC)) == (
        "2026-01-09T15:30:00.123456Z"
    )


def test_vcrm077_from_iso_returns_aware_utc() -> None:
    parsed = from_iso("2026-01-09T15:30:00Z")
    assert parsed == datetime(2026, 1, 9, 15, 30, tzinfo=UTC)
    assert parsed.utcoffset() == timedelta(0)
    assert from_iso(to_iso(datetime(2026, 5, 1, 8, 0, tzinfo=timeutil.BOGOTA))) == datetime(
        2026, 5, 1, 13, 0, tzinfo=UTC
    )


def test_vcrm077_from_iso_rejects_naive_text() -> None:
    with pytest.raises(ValueError):
        from_iso("2026-01-09T15:30:00")


def test_vcrm077_format_local_presents_in_bogota() -> None:
    assert format_local(datetime(2026, 1, 10, 3, 5, tzinfo=UTC)) == "09/01/2026 22:05"
    with pytest.raises(ValueError):
        format_local(datetime(2026, 1, 10, 3, 5))


def test_vcrm077_local_date_in_bogota() -> None:
    assert local_date(datetime(2026, 1, 10, 3, 5, tzinfo=UTC)) == date(2026, 1, 9)
    assert local_date(datetime(2026, 1, 10, 5, 0, tzinfo=UTC)) == date(2026, 1, 10)


def test_vcrm077_bogota_fallback_fixed_offset_when_zoneinfo_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(_key: str) -> None:
        raise ZoneInfoNotFoundError("sin base tz")

    monkeypatch.setattr(timeutil, "ZoneInfo", broken)
    tz = timeutil._load_bogota()
    assert isinstance(tz, timezone)
    assert tz.utcoffset(None) == timedelta(hours=-5)
    assert datetime(2026, 1, 10, 3, 5, tzinfo=UTC).astimezone(tz).strftime("%d/%m/%Y %H:%M") == (
        "09/01/2026 22:05"
    )


def test_vcrm077_bogota_uses_zoneinfo_when_available() -> None:
    assert str(timeutil._load_bogota()) == "America/Bogota"


# --- Festivos extraordinarios (T02b; VCRM-167) ----------------------------------------------

EXTRA_FRIDAY = date(2026, 11, 20)  # viernes; 16-nov es el festivo calculado de esa semana


def test_vcrm167_extraordinary_friday_is_not_business_day() -> None:
    assert EXTRA_FRIDAY.weekday() == 4
    assert is_business_day(EXTRA_FRIDAY)
    assert not is_business_day(EXTRA_FRIDAY, extra=frozenset({EXTRA_FRIDAY}))


def test_vcrm167_add_business_days_skips_extraordinary_holiday() -> None:
    extra = frozenset({EXTRA_FRIDAY})
    assert add_business_days(date(2026, 11, 19), 1) == EXTRA_FRIDAY
    assert add_business_days(date(2026, 11, 19), 1, extra=extra) == date(2026, 11, 23)


def test_vcrm167_business_days_between_skips_extraordinary_holiday() -> None:
    extra = frozenset({EXTRA_FRIDAY})
    assert business_days_between(date(2026, 11, 19), date(2026, 11, 23)) == 2
    assert business_days_between(date(2026, 11, 19), date(2026, 11, 23), extra=extra) == 1


def test_vcrm167_calculated_holidays_unchanged_by_extra() -> None:
    extra = frozenset({EXTRA_FRIDAY})
    assert colombian_holidays(2026) == frozenset(HOLIDAYS_2026)
    for day in HOLIDAYS_2026:
        assert not is_business_day(day, extra=extra)
