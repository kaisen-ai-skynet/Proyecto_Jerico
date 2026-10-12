"""VCRM-072, 076, 100, 101: franja de envío, festivos y cupo semanal (Ley 2300, J-11)."""

from datetime import UTC, date, datetime, timedelta

import pytest

from jerico.crm.sendwindow import LEGAL_WINDOW, Window, allowed, next_slot, schedule, week_start
from jerico.crm.timeutil import BOGOTA

NO_EXTRA: frozenset[date] = frozenset()


def bog(day: int, hour: int, minute: int = 0, month: int = 10) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=BOGOTA)


# Calendario de referencia (octubre de 2026): mié 14, sáb 17, dom 18; lun 12 es festivo.


def test_vcrm072_franja_lv_sab_festivos() -> None:
    assert allowed(bog(14, 7)) is True  # 07:00 incluido
    assert allowed(bog(14, 6, 59)) is False
    assert allowed(bog(14, 18, 59)) is True
    assert allowed(bog(14, 19)) is False  # 19:00 excluido
    assert allowed(bog(17, 8)) is True  # sábado 08:00 incluido
    assert allowed(bog(17, 7, 59)) is False
    assert allowed(bog(17, 14, 59)) is True
    assert allowed(bog(17, 15)) is False  # sábado 15:00 excluido
    assert allowed(bog(18, 10)) is False  # domingo cerrado
    assert allowed(bog(12, 10)) is False  # lunes festivo
    # Festivo extraordinario configurado: el miércoles 14 deja de ser válido.
    extra = frozenset({date(2026, 10, 14)})
    assert allowed(bog(14, 10), extra) is False
    assert allowed(bog(15, 10), extra) is True


def test_vcrm072_utc_a_bogota_cambio_de_dia() -> None:
    # 2026-10-15 00:00 UTC es el miércoles 14 a las 19:00 en Bogotá: fuera de franja.
    assert allowed(datetime(2026, 10, 15, 0, 0, tzinfo=UTC)) is False
    # 2026-10-14 23:59 UTC es el miércoles 14 a las 18:59 en Bogotá: dentro de franja.
    assert allowed(datetime(2026, 10, 14, 23, 59, tzinfo=UTC)) is True
    # 2026-10-17 03:30 UTC es el viernes 16 a las 22:30 en Bogotá: el siguiente es el sábado 08:00.
    assert next_slot(datetime(2026, 10, 17, 3, 30, tzinfo=UTC)) == bog(17, 8)
    # El instante devuelto se expresa en hora de Bogotá aunque la entrada sea UTC.
    assert next_slot(datetime(2026, 10, 17, 3, 30, tzinfo=UTC)).utcoffset() == timedelta(hours=-5)


def test_vcrm072_exige_fecha_con_zona() -> None:
    with pytest.raises(ValueError, match="zona"):
        allowed(datetime(2026, 10, 14, 10, 0))


def test_vcrm100_difiere_al_inicio_de_franja() -> None:
    assert next_slot(bog(14, 10)) == bog(14, 10)  # ya dentro: no se difiere
    assert next_slot(bog(14, 5)) == bog(14, 7)  # antes de abrir: abre ese mismo día
    assert next_slot(bog(14, 19)) == bog(15, 7)  # tras cerrar: siguiente día hábil
    assert next_slot(bog(16, 19)) == bog(17, 8)  # viernes tarde: sábado a las 08:00
    assert next_slot(bog(17, 15)) == bog(19, 7, month=10)  # sábado tarde: domingo cerrado, lunes
    assert next_slot(bog(11, 12)) == bog(13, 7)  # domingo: lunes 12 es festivo, martes 13
    extra = frozenset({date(2026, 10, 15)})
    assert next_slot(bog(14, 19), extra) == bog(16, 7)  # festivo extraordinario salta el jueves


def test_vcrm076_un_contacto_por_semana() -> None:
    # La semana calendario va de lunes 00:00 a domingo 23:59 (hora de Bogotá).
    assert week_start(bog(14, 10)) == bog(12, 0)
    assert week_start(bog(18, 23, 59)) == bog(12, 0)  # domingo pertenece a la semana del lunes 12
    assert week_start(bog(19, 0)) == bog(19, 0)  # el lunes 19 abre una semana nueva
    assert week_start(datetime(2026, 10, 19, 4, 59, tzinfo=UTC)) == bog(
        12, 0
    )  # lunes 19 aún es dom 18 en Bogotá
    now = bog(14, 10)
    assert schedule(now, lambda _week: 0, limit=1) == now  # sin envíos previos: no se difiere
    assert schedule(now, lambda _week: 0, limit=2) == now


def test_vcrm101_excedente_a_semana_siguiente() -> None:
    now = bog(14, 10)
    counts = {bog(12, 0): 1}  # la semana del lunes 12 ya tiene su contacto

    def sends(week: datetime) -> int:
        return counts.get(week, 0)

    # Lunes 19 es hábil (no festivo): primera franja de la semana siguiente.
    assert schedule(now, sends, limit=1) == bog(19, 7)
    # Si la semana siguiente también está llena, se salta otra más.
    counts[bog(19, 0)] = 1
    assert schedule(now, sends, limit=1) == bog(26, 7)
    # Un límite mayor admite el envío en la misma semana.
    assert schedule(now, sends, limit=2) == now
    # Si el lunes de la semana siguiente es festivo, abre el primer día hábil.
    assert schedule(
        bog(10, 10, month=11), lambda w: 1 if w == bog(9, 0, month=11) else 0, limit=1
    ) == bog(17, 7, month=11)  # lun 16/11/2026 festivo -> martes 17


def test_vcrm101_limite_invalido_o_semanas_sin_fin() -> None:
    with pytest.raises(ValueError, match="limit"):
        schedule(bog(14, 10), lambda _w: 0, limit=0)
    with pytest.raises(ValueError, match="semanas"):
        schedule(bog(14, 10), lambda _w: 99, limit=1)  # siempre lleno: no hay hueco


def test_vcrm072_ventana_configurable_solo_se_estrecha() -> None:
    assert LEGAL_WINDOW == Window(
        weekday_open=7, weekday_close=19, saturday_open=8, saturday_close=15
    )
    estrecha = Window(weekday_open=9, weekday_close=17, saturday_open=9, saturday_close=13)
    assert allowed(bog(14, 8), window=estrecha) is False
    assert allowed(bog(14, 9), window=estrecha) is True
    assert allowed(bog(14, 17), window=estrecha) is False
    assert allowed(bog(17, 13), window=estrecha) is False
    assert next_slot(bog(14, 17), window=estrecha) == bog(15, 9)
    with pytest.raises(ValueError, match="legal"):
        Window(weekday_open=6, weekday_close=19, saturday_open=8, saturday_close=15)
    with pytest.raises(ValueError, match="legal"):
        Window(weekday_open=7, weekday_close=20, saturday_open=8, saturday_close=15)
    with pytest.raises(ValueError, match="legal"):
        Window(weekday_open=7, weekday_close=19, saturday_open=7, saturday_close=15)
    with pytest.raises(ValueError, match="legal"):
        Window(weekday_open=7, weekday_close=19, saturday_open=8, saturday_close=16)
    with pytest.raises(ValueError, match="legal"):
        Window(weekday_open=12, weekday_close=12, saturday_open=8, saturday_close=15)
