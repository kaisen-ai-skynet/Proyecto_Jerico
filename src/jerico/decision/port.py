"""Puerto orquestador decidir y modelo Decision (spec 007, VJT-010 a 015, 030, 037)."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from jerico.decision.breaker import CircuitBreaker
from jerico.decision.cache import DecisionCache, SingleFlight, decision_key, new_event_id
from jerico.decision.config import DecisionSettings, load_settings
from jerico.decision.floor import allowed_options, apply_floor
from jerico.decision.policy import Policy, PolicyKind, load_policy
from jerico.decision.recorder import DecisionRecorder
from jerico.decision.state import validate_state

logger = logging.getLogger(__name__)

_global_policy: Policy | None = None
_global_cache: DecisionCache | None = None
_global_single_flight = SingleFlight()


def _get_default_policy() -> Policy:
    global _global_policy
    if _global_policy is None:
        _global_policy = load_policy()
    return _global_policy


def _get_default_cache() -> DecisionCache:
    global _global_cache
    if _global_cache is None:
        _global_cache = DecisionCache()
    return _global_cache


def reset_global_cache() -> None:
    """Restablece la caché global de decisiones (útil en pruebas y reinicio)."""
    global _global_cache
    if _global_cache is not None:
        _global_cache.clear()
    _global_cache = None


class Mode(StrEnum):
    """Modos de operación para cada tipo de decisión (VJT-010)."""

    APAGADO = "apagado"
    SOMBRA = "sombra"
    SUGERENCIA = "sugerencia"
    ENRUTADO = "enrutado"


@dataclass(frozen=True)
class Decision:
    """Resultado inmutable de una consulta de decisión transversal."""

    option: str
    source: str
    reason: str
    event_id: str
    decision_key: str
    suggested: str | None = None


def decidir(
    kind: str,
    state: dict[str, Any],
    tarea: str | None = None,
    *,
    ctx: Any = None,
    policy: Policy | None = None,
    settings: DecisionSettings | None = None,
    recorder: DecisionRecorder | None = None,
    cache: DecisionCache | None = None,
    breaker: CircuitBreaker | None = None,
    client: Any = None,
    user_role: str | None = None,
    clock: Callable[[], float] | None = None,
) -> Decision:
    """Punto de entrada único para consultar o registrar una decisión.

    Garantiza que NUNCA lanza excepciones al invocador (VJT-030).
    """
    event_id = new_event_id(clock=clock)
    base_default = "base"
    dkey_fallback = "dkey_error"

    try:
        active_policy = policy or _get_default_policy()
        active_settings = settings or load_settings()
        active_cache = cache or _get_default_cache()
        active_recorder = recorder or DecisionRecorder(dir_path=active_settings.base_dir)

        spec: PolicyKind = active_policy.par(kind, tarea)
        base_default = spec.base
        dkey = decision_key(kind, tarea, state, active_policy.version)

        # 1. Validación estricta del estado (VJT-025, se aplica en todos los modos)
        es_valido, motivo_val = validate_state(spec, state)
        if not es_valido:
            # En estado inválido, no se registran datos ni se entrega a Jev
            return Decision(
                option=spec.base,
                source="base",
                reason=f"estado_invalido: {motivo_val}",
                event_id=event_id,
                decision_key=dkey,
            )

        # 2. Modo efectivo considerando kill-switch y degradación
        modo = active_settings.mode_for(kind, default=spec.modo_defecto)

        # 3. Conjunto permitido (VJT-001)
        allowed = allowed_options(spec, ctx=ctx)

        # 4. Optimización de una sola opción (VJT-008)
        if len(allowed) == 1:
            if modo != "apagado":
                active_recorder.record(
                    {
                        "event_id": event_id,
                        "decision_key": dkey,
                        "kind": kind,
                        "tarea": tarea,
                        "mode": modo,
                        "state": state,
                        "base_option": spec.base,
                        "applied_option": allowed[0],
                        "suggested_option": None,
                        "source": "base",
                        "reason": "una_opcion",
                        "policy_version": active_policy.version,
                    }
                )
            return Decision(
                option=allowed[0],
                source="base",
                reason="una_opcion",
                event_id=event_id,
                decision_key=dkey,
            )

        # 5. Modos apagado, sombra o clases A / asesor (VJT-003, VJT-010a, VJT-011)
        if spec.clase == "A" or spec.asesor or modo in ("apagado", "sombra"):
            if modo != "apagado":
                active_recorder.record(
                    {
                        "event_id": event_id,
                        "decision_key": dkey,
                        "kind": kind,
                        "tarea": tarea,
                        "mode": modo,
                        "state": state,
                        "base_option": spec.base,
                        "applied_option": spec.base,
                        "suggested_option": None,
                        "source": "base",
                        "reason": modo,
                        "policy_version": active_policy.version,
                    }
                )
            return Decision(
                option=spec.base,
                source="base",
                reason=modo,
                event_id=event_id,
                decision_key=dkey,
            )

        # 6. Modos activos (sugerencia y enrutado)
        # Comprobar caché
        cached_opt = active_cache.get(dkey)
        if cached_opt is not None:
            aplicada, motivo_piso = apply_floor(
                spec.clase, spec.orden_exigencia, spec.base, cached_opt, allowed
            )
            suggested = cached_opt if (modo == "sugerencia" and user_role == "cto") else None
            if modo == "sugerencia":
                aplicada = spec.base
            if modo != "apagado":
                active_recorder.record(
                    {
                        "event_id": event_id,
                        "decision_key": dkey,
                        "kind": kind,
                        "tarea": tarea,
                        "mode": modo,
                        "state": state,
                        "base_option": spec.base,
                        "applied_option": aplicada,
                        "suggested_option": cached_opt if modo == "sugerencia" else None,
                        "source": "cache",
                        "reason": motivo_piso,
                        "policy_version": active_policy.version,
                    }
                )
            return Decision(
                option=aplicada,
                source="cache",
                reason=motivo_piso,
                event_id=event_id,
                decision_key=dkey,
                suggested=suggested,
            )

        # Cortacircuitos
        if breaker is not None and breaker.is_open():
            return Decision(
                option=spec.base,
                source="respaldo",
                reason="cortacircuitos",
                event_id=event_id,
                decision_key=dkey,
            )

        # Resolución de cliente en línea (Nivel 2 o respaldo de Nivel 1)
        active_client = client
        if active_client is None and active_settings.online:
            try:
                from jerico.decision.jev_client import JevClient

                active_client = JevClient(
                    api_key=active_settings.api_key,
                    endpoint=active_settings.endpoint,
                    model=active_settings.model,
                    timeout_s=active_settings.timeout_s,
                )
            except Exception:
                active_client = None

        if active_client is None:
            return Decision(
                option=spec.base,
                source="respaldo",
                reason="sin_cliente_en_linea",
                event_id=event_id,
                decision_key=dkey,
            )

        if hasattr(active_client, "enabled") and not active_client.enabled:
            return Decision(
                option=spec.base,
                source="respaldo",
                reason="sin_llave",
                event_id=event_id,
                decision_key=dkey,
            )

        # Consulta con un solo vuelo
        def _call() -> Any:
            return active_client.consultar(spec, state)

        try:
            answer = _global_single_flight.run(dkey, _call)
            if breaker is not None:
                breaker.record_success()
        except Exception:
            if breaker is not None:
                breaker.record_failure()
                if breaker.failure_count >= breaker.threshold:
                    active_settings.set_degraded(kind)  # VJT-015
            return Decision(
                option=spec.base,
                source="respaldo",
                reason="fallo_cliente",
                event_id=event_id,
                decision_key=dkey,
            )

        # Empate (VJT-037)
        if isinstance(answer, dict) and answer.get("empate") is True:
            return Decision(
                option=spec.base,
                source="respaldo",
                reason="empate_jev",
                event_id=event_id,
                decision_key=dkey,
            )

        jev_option = answer.get("option", spec.base) if isinstance(answer, dict) else str(answer)
        aplicada, motivo_piso = apply_floor(
            spec.clase, spec.orden_exigencia, spec.base, jev_option, allowed
        )

        active_cache.put(dkey, jev_option)

        suggested = jev_option if (modo == "sugerencia" and user_role == "cto") else None
        if modo == "sugerencia":
            aplicada = spec.base

        record_payload = {
            "event_id": event_id,
            "decision_key": dkey,
            "kind": kind,
            "tarea": tarea,
            "mode": modo,
            "state": state,
            "base_option": spec.base,
            "applied_option": aplicada,
            "suggested_option": jev_option if (modo == "sugerencia" or modo == "sombra") else None,
            "source": "jev",
            "reason": motivo_piso,
            "policy_version": active_policy.version,
        }
        if isinstance(answer, dict):
            record_payload["jev_response"] = {
                "option": jev_option,
                "confidence": answer.get("confidence"),
                "probabilities": answer.get("probabilities"),
            }
            if answer.get("model_version") or answer.get("model"):
                record_payload["model_version"] = answer.get("model_version") or answer.get("model")
            if answer.get("latencia_ms") is not None:
                record_payload["latency_ms"] = answer.get("latencia_ms")
            if answer.get("tokens_in") is not None:
                record_payload["tokens_in"] = answer.get("tokens_in")

        active_recorder.record(record_payload)

        return Decision(
            option=aplicada,
            source="jev",
            reason=motivo_piso,
            event_id=event_id,
            decision_key=dkey,
            suggested=suggested,
        )

    except Exception as exc:  # noqa: BLE001
        logger.exception("Fallo inesperado en decidir: %s", exc)
        return Decision(
            option=base_default,
            source="respaldo",
            reason="excepcion",
            event_id=event_id,
            decision_key=dkey_fallback,
        )
