"""Caché en memoria, claves deterministas y SingleFlight (spec 007, VJT-034, 036, 041)."""

import hashlib
import json
import secrets
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")

_seq_lock = threading.Lock()
_global_seq = 0


def _get_next_seq() -> int:
    global _global_seq
    with _seq_lock:
        _global_seq += 1
        return _global_seq


def decision_key(
    kind: str, tarea: str | None, state: dict[str, Any], policy_version: str
) -> str:
    """Genera una clave determinista de (tipo, tarea, estado, version) (VJT-041)."""
    canonical_state = json.dumps(state, sort_keys=True, separators=(",", ":"))
    raw = f"{kind}:{tarea or ''}:{canonical_state}:{policy_version}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_event_id(clock: Callable[[], float] | None = None, seq: int | None = None) -> str:
    """Genera un identificador de evento único por ocurrencia, sin datos personales (VJT-041)."""
    now = clock() if clock is not None else time.time()
    ts_ms = int(now * 1000)
    current_seq = seq if seq is not None else _get_next_seq()
    rand_suffix = secrets.token_hex(4)
    return f"evt_{ts_ms}_{current_seq}_{rand_suffix}"


class DecisionCache:
    """Caché en memoria para opciones decididas, con TTL (VJT-034)."""

    def __init__(
        self, ttl_seconds: float = 86400.0, clock: Callable[[], float] | None = None
    ) -> None:
        self.ttl = ttl_seconds
        self._clock = clock if clock is not None else time.time
        self._entries: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        """Devuelve la opción cacheada si sigue vigente."""
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            option, expires_at = entry
            if now >= expires_at:
                del self._entries[key]
                return None
            return option

    def put(self, key: str, option: str) -> None:
        """Guarda la opción con tiempo de expiración según TTL."""
        now = self._clock()
        with self._lock:
            self._entries[key] = (option, now + self.ttl)


class SingleFlight:
    """Garantiza una sola ejecución para peticiones concurrentes con la misma clave (VJT-036)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: dict[str, tuple[threading.Event, list[Any], list[Exception]]] = {}

    def run(self, key: str, fn: Callable[[], T]) -> T:
        """Ejecuta fn una sola vez por clave entre invocaciones concurrentes."""
        event: threading.Event
        res_box: list[Any]
        err_box: list[Exception]
        is_leader = False

        with self._lock:
            if key in self._calls:
                event, res_box, err_box = self._calls[key]
            else:
                event = threading.Event()
                res_box = []
                err_box = []
                self._calls[key] = (event, res_box, err_box)
                is_leader = True

        if not is_leader:
            event.wait()
            if err_box:
                raise err_box[0]
            return res_box[0]  # type: ignore[no-any-return]

        try:
            val = fn()
            res_box.append(val)
            return val
        except Exception as exc:
            err_box.append(exc)
            raise
        finally:
            with self._lock:
                event.set()
                self._calls.pop(key, None)
