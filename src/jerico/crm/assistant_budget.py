"""Control presupuestario y circuit breaker del asistente comercial LLM (VCRM-A21..A24, A33)."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from jerico.crm.config import CrmSettings
from jerico.crm.llm import LlmResult
from jerico.crm.repo import get_meta, set_meta
from jerico.crm.timeutil import local_date

CapReason = Literal["daily_cap", "user_cap", "breaker"]


@dataclass(frozen=True, slots=True)
class BudgetDecision:
    allowed: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RecordOutcome:
    cost_usd: float | None
    cap_reached: bool


def _read_int(conn: sqlite3.Connection, key: str) -> int:
    val = get_meta(conn, key)
    if val is None:
        return 0
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


class AssistantBudget:
    """Control presupuestario por día en Bogotá y circuit breaker en memoria."""

    def __init__(self, settings: CrmSettings) -> None:
        self._settings = settings
        self._consecutive_failures: int = 0
        self._breaker_until: datetime | None = None

    def _is_breaker_open(self, now: datetime) -> bool:
        return self._breaker_until is not None and now < self._breaker_until

    def _has_rates(self) -> bool:
        return (
            self._settings.assistant_price_in_per_mtok is not None
            and self._settings.assistant_price_out_per_mtok is not None
        )

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float | None:
        """Calcula el costo estimado en USD con tarifas por millón de tokens."""
        p_in = self._settings.assistant_price_in_per_mtok
        p_out = self._settings.assistant_price_out_per_mtok
        if p_in is None or p_out is None:
            return None
        return (input_tokens * p_in + output_tokens * p_out) / 1_000_000.0

    def check(self, conn: sqlite3.Connection, user_id: int, now: datetime) -> BudgetDecision:
        """Verificación pura de solo lectura de presupuestos y estado del breaker."""
        if self._is_breaker_open(now):
            return BudgetDecision(allowed=False, reason="breaker")

        day = local_date(now).isoformat()

        # Tope diario global de tokens
        tokens = _read_int(conn, f"llm:tokens:{day}")
        if tokens >= self._settings.assistant_daily_token_cap:
            return BudgetDecision(allowed=False, reason="daily_cap")

        # Tope diario global en USD (requiere tarifas)
        if self._settings.assistant_daily_cost_cap_usd is not None and self._has_rates():
            cost_micro = _read_int(conn, f"llm:cost_micro:{day}")
            cost_usd = cost_micro / 1_000_000.0
            if cost_usd >= self._settings.assistant_daily_cost_cap_usd:
                return BudgetDecision(allowed=False, reason="daily_cap")

        # Tope diario por usuario
        calls = _read_int(conn, f"llm:calls:{day}:{user_id}")
        if calls >= self._settings.assistant_user_daily_calls:
            return BudgetDecision(allowed=False, reason="user_cap")

        return BudgetDecision(allowed=True, reason=None)

    def record_failure(self, now: datetime) -> None:
        """Registra un fallo consecutivo; 3 fallos seguidos abren el breaker 5 minutos."""
        if self._breaker_until is not None and now >= self._breaker_until:
            self._breaker_until = None
            self._consecutive_failures = 0
        self._consecutive_failures += 1
        if self._consecutive_failures >= 3:
            self._breaker_until = now + timedelta(minutes=5)

    def record_success(self, now: datetime | None = None) -> None:
        """Reinicia el contador de fallos consecutivos y cierra el circuit breaker."""
        self._consecutive_failures = 0
        self._breaker_until = None

    def record(
        self,
        conn: sqlite3.Connection,
        user_id: int,
        now: datetime,
        result: LlmResult,
    ) -> RecordOutcome:
        """Acumula tokens, llamadas y micro-USD en crm_meta y evalúa si se alcanzó algún tope."""
        self.record_success(now)

        day = local_date(now).isoformat()

        # Acumular tokens
        tokens_key = f"llm:tokens:{day}"
        call_tokens = result.input_tokens + result.output_tokens
        curr_tokens = _read_int(conn, tokens_key)
        new_tokens = curr_tokens + call_tokens
        set_meta(conn, tokens_key, str(new_tokens))

        # Acumular llamadas de usuario
        calls_key = f"llm:calls:{day}:{user_id}"
        curr_calls = _read_int(conn, calls_key)
        set_meta(conn, calls_key, str(curr_calls + 1))

        # Acumular costo si hay tarifas
        call_cost = self.cost_usd(result.input_tokens, result.output_tokens)
        new_cost_micro = 0
        if call_cost is not None:
            cost_key = f"llm:cost_micro:{day}"
            call_micro = int(round(call_cost * 1_000_000))
            curr_cost_micro = _read_int(conn, cost_key)
            new_cost_micro = curr_cost_micro + call_micro
            set_meta(conn, cost_key, str(new_cost_micro))

        # Evaluar si se alcanzó o superó algún tope diario
        cap_reached = False
        if new_tokens >= self._settings.assistant_daily_token_cap:
            cap_reached = True
        elif (
            call_cost is not None
            and self._settings.assistant_daily_cost_cap_usd is not None
            and (new_cost_micro / 1_000_000.0) >= self._settings.assistant_daily_cost_cap_usd
        ):
            cap_reached = True

        return RecordOutcome(cost_usd=call_cost, cap_reached=cap_reached)

    def cap_notice_due(self, conn: sqlite3.Connection, now: datetime) -> bool:
        """Devuelve True exactamente una vez por día en Bogotá cuando se alcanza el tope."""
        day = local_date(now).isoformat()
        key = f"llm:cap_notice:{day}"
        val = get_meta(conn, key)
        if val is not None:
            return False
        set_meta(conn, key, "1")
        return True
