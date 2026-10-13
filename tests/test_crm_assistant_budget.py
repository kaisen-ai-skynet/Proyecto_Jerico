"""Pruebas del control presupuestario y circuit breaker del asistente LLM (VCRM-A21..A24, A33)."""

from collections.abc import Iterator
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from crm_support import make_settings
from jerico.crm import repo
from jerico.crm.assistant_budget import (
    AssistantBudget,
    BudgetDecision,
    RecordOutcome,
)
from jerico.crm.db import CrmDatabase
from jerico.crm.llm import LlmResult

NOW = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)  # 10:00 en Bogotá (UTC-5)
USER_1 = 101
USER_2 = 102


@pytest.fixture
def db(tmp_path: Path) -> Iterator[CrmDatabase]:
    database = CrmDatabase(tmp_path / "crm.db")
    yield database
    database.close()


def test_budget_decision_frozen() -> None:
    decision = BudgetDecision(allowed=True, reason=None)
    assert decision.allowed is True
    assert decision.reason is None
    with pytest.raises(FrozenInstanceError):
        decision.allowed = False  # type: ignore[misc]


def test_record_outcome_frozen() -> None:
    outcome = RecordOutcome(cost_usd=0.012, cap_reached=False)
    assert outcome.cost_usd == 0.012
    assert outcome.cap_reached is False
    with pytest.raises(FrozenInstanceError):
        outcome.cap_reached = True  # type: ignore[misc]


def test_cost_usd_sin_tarifas_o_parcial() -> None:
    # Sin ninguna tarifa
    budget_none = AssistantBudget(make_settings())
    assert budget_none.cost_usd(1000, 500) is None

    # Solo tarifa de entrada
    budget_only_in = AssistantBudget(make_settings(assistant_price_in_per_mtok=1.5))
    assert budget_only_in.cost_usd(1000, 500) is None

    # Solo tarifa de salida
    budget_only_out = AssistantBudget(make_settings(assistant_price_out_per_mtok=3.0))
    assert budget_only_out.cost_usd(1000, 500) is None


def test_cost_usd_calculo_exacto() -> None:
    budget = AssistantBudget(
        make_settings(
            assistant_price_in_per_mtok=1.5,
            assistant_price_out_per_mtok=3.0,
        )
    )
    # 0 tokens -> 0.0 USD
    assert budget.cost_usd(0, 0) == 0.0

    # 1_000_000 entrada (1.5 USD) + 500_000 salida (1.5 USD) = 3.0 USD
    cost = budget.cost_usd(1_000_000, 500_000)
    assert cost == pytest.approx(3.0)

    # Pequeño volumen: 10_000 entrada + 2_000 salida
    # 10_000 * 1.5 = 15_000; 2_000 * 3.0 = 6_000; (15_000 + 6_000) / 1_000_000 = 0.021 USD
    cost_small = budget.cost_usd(10_000, 2_000)
    assert cost_small == pytest.approx(0.021)


def test_check_allowed_inicial_no_muta_base(db: CrmDatabase) -> None:
    budget = AssistantBudget(make_settings())
    with db.tx() as tx:
        decision = budget.check(tx, USER_1, NOW)
        assert decision.allowed is True
        assert decision.reason is None
        # La tabla crm_meta debe seguir completamente vacía
        assert repo.get_meta(tx, f"llm:tokens:{NOW.date().isoformat()}") is None


def test_check_cortado_por_token_cap(db: CrmDatabase) -> None:
    budget = AssistantBudget(make_settings(assistant_daily_token_cap=500))
    day = "2026-10-13"
    with db.tx() as tx:
        # Por debajo del tope
        repo.set_meta(tx, f"llm:tokens:{day}", "499")
        assert budget.check(tx, USER_1, NOW).allowed is True

        # En el tope exacto
        repo.set_meta(tx, f"llm:tokens:{day}", "500")
        decision = budget.check(tx, USER_1, NOW)
        assert decision.allowed is False
        assert decision.reason == "daily_cap"

        # Superando el tope
        repo.set_meta(tx, f"llm:tokens:{day}", "501")
        assert budget.check(tx, USER_1, NOW).reason == "daily_cap"


def test_check_cortado_por_cost_cap(db: CrmDatabase) -> None:
    budget = AssistantBudget(
        make_settings(
            assistant_daily_cost_cap_usd=2.0,
            assistant_price_in_per_mtok=1.5,
            assistant_price_out_per_mtok=3.0,
        )
    )
    day = "2026-10-13"
    with db.tx() as tx:
        # 1.99 USD = 1_990_000 micro-USD -> permitido
        repo.set_meta(tx, f"llm:cost_micro:{day}", "1990000")
        assert budget.check(tx, USER_1, NOW).allowed is True

        # 2.00 USD = 2_000_000 micro-USD -> daily_cap
        repo.set_meta(tx, f"llm:cost_micro:{day}", "2000000")
        decision = budget.check(tx, USER_1, NOW)
        assert decision.allowed is False
        assert decision.reason == "daily_cap"


def test_check_cost_cap_ignorado_si_faltan_tarifas(db: CrmDatabase) -> None:
    # Si assistant_daily_cost_cap_usd está configurado pero faltan tarifas, no rige costo
    budget = AssistantBudget(
        make_settings(
            assistant_daily_cost_cap_usd=1.0,
            assistant_price_in_per_mtok=None,
            assistant_price_out_per_mtok=None,
        )
    )
    day = "2026-10-13"
    with db.tx() as tx:
        repo.set_meta(tx, f"llm:cost_micro:{day}", "5000000")
        assert budget.check(tx, USER_1, NOW).allowed is True


def test_check_cortado_por_user_daily_calls(db: CrmDatabase) -> None:
    budget = AssistantBudget(make_settings(assistant_user_daily_calls=5))
    day = "2026-10-13"
    with db.tx() as tx:
        repo.set_meta(tx, f"llm:calls:{day}:{USER_1}", "4")
        assert budget.check(tx, USER_1, NOW).allowed is True

        # USER_1 alcanza su tope
        repo.set_meta(tx, f"llm:calls:{day}:{USER_1}", "5")
        decision_u1 = budget.check(tx, USER_1, NOW)
        assert decision_u1.allowed is False
        assert decision_u1.reason == "user_cap"

        # USER_2 no tiene llamadas registradas -> permitido
        assert budget.check(tx, USER_2, NOW).allowed is True


def test_check_prioridad_breaker_sobre_caps(db: CrmDatabase) -> None:
    budget = AssistantBudget(
        make_settings(
            assistant_daily_token_cap=100,
            assistant_user_daily_calls=2,
        )
    )
    day = "2026-10-13"
    with db.tx() as tx:
        repo.set_meta(tx, f"llm:tokens:{day}", "500")
        repo.set_meta(tx, f"llm:calls:{day}:{USER_1}", "10")

        # Breaker abierto
        budget.record_failure(NOW)
        budget.record_failure(NOW)
        budget.record_failure(NOW)

        # Debe prevalecer 'breaker' sobre 'daily_cap' y 'user_cap'
        decision = budget.check(tx, USER_1, NOW)
        assert decision.allowed is False
        assert decision.reason == "breaker"


def test_check_prioridad_daily_cap_sobre_user_cap(db: CrmDatabase) -> None:
    budget = AssistantBudget(
        make_settings(
            assistant_daily_token_cap=100,
            assistant_user_daily_calls=2,
        )
    )
    day = "2026-10-13"
    with db.tx() as tx:
        repo.set_meta(tx, f"llm:tokens:{day}", "200")
        repo.set_meta(tx, f"llm:calls:{day}:{USER_1}", "5")

        decision = budget.check(tx, USER_1, NOW)
        assert decision.allowed is False
        assert decision.reason == "daily_cap"


def test_check_valores_no_numericos_en_meta_cuentan_como_cero(db: CrmDatabase) -> None:
    budget = AssistantBudget(make_settings(assistant_daily_token_cap=100))
    day = "2026-10-13"
    with db.tx() as tx:
        repo.set_meta(tx, f"llm:tokens:{day}", "corrupto")
        repo.set_meta(tx, f"llm:cost_micro:{day}", "no-numero")
        repo.set_meta(tx, f"llm:calls:{day}:{USER_1}", "xyz")

        decision = budget.check(tx, USER_1, NOW)
        assert decision.allowed is True
        assert decision.reason is None


def test_check_diferenciacion_por_dia_bogota(db: CrmDatabase) -> None:
    budget = AssistantBudget(make_settings(assistant_daily_token_cap=100))
    # 2026-10-14 02:00 UTC = 2026-10-13 21:00 en Bogotá (mismo día 13)
    t_bogota_dia13 = datetime(2026, 10, 14, 2, 0, tzinfo=UTC)
    # 2026-10-14 06:00 UTC = 2026-10-14 01:00 en Bogotá (nuevo día 14)
    t_bogota_dia14 = datetime(2026, 10, 14, 6, 0, tzinfo=UTC)

    with db.tx() as tx:
        repo.set_meta(tx, "llm:tokens:2026-10-13", "150")

        # En día 13 en Bogotá está bloqueado
        assert budget.check(tx, USER_1, t_bogota_dia13).reason == "daily_cap"
        # En día 14 en Bogotá está libre
        assert budget.check(tx, USER_1, t_bogota_dia14).allowed is True


def test_circuit_breaker_tres_fallos_y_cinco_minutos() -> None:
    budget = AssistantBudget(make_settings())

    # Fallos 1 y 2 no abren el breaker
    budget.record_failure(NOW)
    assert budget._is_breaker_open(NOW) is False
    budget.record_failure(NOW + timedelta(seconds=10))
    assert budget._is_breaker_open(NOW + timedelta(seconds=10)) is False

    # Fallo 3 abre el breaker por 5 minutos
    t_fail_3 = NOW + timedelta(seconds=20)
    budget.record_failure(t_fail_3)
    assert budget._is_breaker_open(t_fail_3) is True

    # Durante los 5 minutos sigue abierto
    assert budget._is_breaker_open(t_fail_3 + timedelta(minutes=4, seconds=59)) is True

    # A los 5 minutos exactos (o después) ya no está abierto
    t_cooled = t_fail_3 + timedelta(minutes=5)
    assert budget._is_breaker_open(t_cooled) is False

    # Al volver a fallar tras enfriarse, empieza nueva cuenta (no abre al 1er fallo)
    budget.record_failure(t_cooled + timedelta(seconds=1))
    assert budget._is_breaker_open(t_cooled + timedelta(seconds=1)) is False


def test_circuit_breaker_record_success_reinicia_conteo() -> None:
    budget = AssistantBudget(make_settings())
    budget.record_failure(NOW)
    budget.record_failure(NOW + timedelta(seconds=5))

    # Éxito reinicia fallos seguidos
    budget.record_success(NOW + timedelta(seconds=10))

    # 2 fallos nuevos no deben abrir el breaker
    budget.record_failure(NOW + timedelta(seconds=15))
    budget.record_failure(NOW + timedelta(seconds=20))
    assert budget._is_breaker_open(NOW + timedelta(seconds=20)) is False


def test_circuit_breaker_record_success_cierra_breaker_abierto() -> None:
    budget = AssistantBudget(make_settings())
    budget.record_failure(NOW)
    budget.record_failure(NOW)
    budget.record_failure(NOW)
    assert budget._is_breaker_open(NOW) is True

    budget.record_success()
    assert budget._is_breaker_open(NOW) is False


def test_record_acumula_tokens_llamadas_y_costo(db: CrmDatabase) -> None:
    budget = AssistantBudget(
        make_settings(
            assistant_daily_token_cap=10_000,
            assistant_user_daily_calls=10,
            assistant_price_in_per_mtok=2.0,
            assistant_price_out_per_mtok=4.0,
        )
    )
    result = LlmResult(
        text="Resumen generado",
        input_tokens=1_000,
        output_tokens=500,
    )
    day = "2026-10-13"

    with db.tx() as tx:
        # 1er registro
        outcome = budget.record(tx, USER_1, NOW, result)
        # Costo: (1000 * 2.0 + 500 * 4.0) / 1_000_000 = (2000 + 2000) / 1_000_000 = 0.004 USD
        assert outcome.cost_usd == pytest.approx(0.004)
        assert outcome.cap_reached is False

        assert repo.get_meta(tx, f"llm:tokens:{day}") == "1500"
        assert repo.get_meta(tx, f"llm:calls:{day}:{USER_1}") == "1"
        assert repo.get_meta(tx, f"llm:cost_micro:{day}") == "4000"

        # 2do registro (acumulativo)
        outcome2 = budget.record(tx, USER_1, NOW, result)
        assert outcome2.cost_usd == pytest.approx(0.004)
        assert outcome2.cap_reached is False

        assert repo.get_meta(tx, f"llm:tokens:{day}") == "3000"
        assert repo.get_meta(tx, f"llm:calls:{day}:{USER_1}") == "2"
        assert repo.get_meta(tx, f"llm:cost_micro:{day}") == "8000"


def test_record_sin_tarifas_no_escribe_costo(db: CrmDatabase) -> None:
    budget = AssistantBudget(make_settings(assistant_daily_token_cap=5_000))
    result = LlmResult(text="OK", input_tokens=200, output_tokens=100)
    day = "2026-10-13"

    with db.tx() as tx:
        outcome = budget.record(tx, USER_1, NOW, result)
        assert outcome.cost_usd is None
        assert outcome.cap_reached is False
        assert repo.get_meta(tx, f"llm:cost_micro:{day}") is None
        assert repo.get_meta(tx, f"llm:tokens:{day}") == "300"


def test_record_cap_reached_por_tokens(db: CrmDatabase) -> None:
    budget = AssistantBudget(make_settings(assistant_daily_token_cap=1_000))
    result = LlmResult(text="Grande", input_tokens=800, output_tokens=200)

    with db.tx() as tx:
        outcome = budget.record(tx, USER_1, NOW, result)
        # 1000 tokens alcanzados == tope de 1000
        assert outcome.cap_reached is True


def test_record_cap_reached_por_costo(db: CrmDatabase) -> None:
    budget = AssistantBudget(
        make_settings(
            assistant_daily_cost_cap_usd=0.01,
            assistant_price_in_per_mtok=10.0,
            assistant_price_out_per_mtok=10.0,
        )
    )
    # 500 in + 500 out con tarifa 10.0 => 1000 * 10 / 1_000_000 = 0.01 USD
    result = LlmResult(text="Costoso", input_tokens=500, output_tokens=500)

    with db.tx() as tx:
        outcome = budget.record(tx, USER_1, NOW, result)
        assert outcome.cost_usd == pytest.approx(0.01)
        assert outcome.cap_reached is True


def test_record_resetea_fallos_del_breaker(db: CrmDatabase) -> None:
    budget = AssistantBudget(make_settings())
    budget.record_failure(NOW)
    budget.record_failure(NOW)
    assert budget._consecutive_failures == 2

    result = LlmResult(text="OK", input_tokens=10, output_tokens=10)
    with db.tx() as tx:
        budget.record(tx, USER_1, NOW, result)

    assert budget._consecutive_failures == 0


def test_cap_notice_due_una_vez_por_dia_bogota(db: CrmDatabase) -> None:
    budget = AssistantBudget(make_settings())
    # 13 de octubre en Bogotá
    t1 = datetime(2026, 10, 13, 14, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 13, 18, 0, tzinfo=UTC)
    # 14 de octubre en Bogotá (07:00 UTC = 02:00 Bogotá)
    t3 = datetime(2026, 10, 14, 7, 0, tzinfo=UTC)

    with db.tx() as tx:
        # Primera llamada del día 13 -> True
        assert budget.cap_notice_due(tx, t1) is True
        # Segunda llamada del mismo día 13 -> False
        assert budget.cap_notice_due(tx, t2) is False

        # Primera llamada del día 14 -> True
        assert budget.cap_notice_due(tx, t3) is True
        # Segunda llamada del día 14 -> False
        assert budget.cap_notice_due(tx, t3 + timedelta(minutes=10)) is False
