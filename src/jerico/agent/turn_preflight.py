import asyncio
import time
import uuid
from dataclasses import dataclass

from jerico.agent.types import TokenPressureLevel
from jerico.state import StateEngine


@dataclass(frozen=True)
class SessionLease:
    session_id: str
    owner_token: str
    expires_at: float


class TurnPreflightGate:
    def __init__(self, state: StateEngine, *, lease_seconds: float = 120.0) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds debe ser positivo")
        self.state = state
        self.lease_seconds = lease_seconds

    async def acquire_lease(self, session_id: str, timeout_s: float = 5.0) -> SessionLease:
        if timeout_s < 0:
            raise ValueError("timeout_s no puede ser negativo")
        owner_token = uuid.uuid4().hex
        deadline = asyncio.get_running_loop().time() + timeout_s
        while True:
            acquired = await asyncio.to_thread(
                self.state.try_acquire_session_lease,
                session_id,
                owner_token,
                self.lease_seconds,
            )
            if acquired:
                return SessionLease(session_id, owner_token, time.time() + self.lease_seconds)
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError(f"timeout esperando lease de sesión {session_id}")
            await asyncio.sleep(min(0.02, remaining))

    async def release_lease(self, lease: SessionLease) -> None:
        await asyncio.to_thread(
            self.state.release_session_lease,
            lease.session_id,
            lease.owner_token,
        )

    @staticmethod
    def evaluate_token_pressure(
        session_id: str,
        current_history_tokens: int,
        window_limit: int,
    ) -> TokenPressureLevel:
        del session_id  # reserved for future session-specific metrics
        if current_history_tokens < 0 or window_limit <= 0:
            raise ValueError("historial debe ser no negativo y ventana positiva")
        ratio = current_history_tokens / window_limit
        if ratio > 1:
            return TokenPressureLevel.OVERFLOW
        if ratio > 0.8:
            return TokenPressureLevel.ELEVATED
        return TokenPressureLevel.LOW
