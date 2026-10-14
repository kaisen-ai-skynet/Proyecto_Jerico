"""Cortacircuitos en memoria para aislamiento de fallos (spec 007, VJT-032)."""

import threading
import time
from collections.abc import Callable


class CircuitBreaker:
    """Cortacircuitos puro con reloj inyectable (VJT-032)."""

    def __init__(
        self,
        threshold: int = 3,
        cooldown: float = 300.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self._clock = clock if clock is not None else time.time
        self.failure_count = 0
        self._open_until: float = 0.0
        self._is_open = False
        self._lock = threading.Lock()

    def is_open(self) -> bool:
        """Indica si el cortacircuitos está abierto (bloqueando consultas)."""
        now = self._clock()
        with self._lock:
            if self._is_open:
                if now >= self._open_until:
                    # Concluyó el tiempo de pausa; se cierra el circuito
                    self._is_open = False
                    self.failure_count = 0
                    return False
                return True
            return False

    def record_failure(self) -> None:
        """Registra un fallo consecutivo; abre el circuito si alcanza el umbral."""
        now = self._clock()
        with self._lock:
            self.failure_count += 1
            if self.failure_count >= self.threshold:
                self._is_open = True
                self._open_until = now + self.cooldown

    def record_success(self) -> None:
        """Registra un éxito y reinicia la cuenta de fallos consecutivos."""
        with self._lock:
            self.failure_count = 0
            self._is_open = False
            self._open_until = 0.0
