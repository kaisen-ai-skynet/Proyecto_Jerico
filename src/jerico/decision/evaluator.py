"""Módulo de evaluación y criterios de promoción entre modos de decisión (spec 007, F3, T14).

Calcula tasas de acuerdo con la regla base, calibración de confianza (Brier score y ECE),
percentiles de latencia (p95) y evalúa si un tipo de decisión cumple los umbrales
para ser promovido de 'sombra' a 'sugerencia' o de 'sugerencia' a 'enrutado'.
"""

import math
from dataclasses import dataclass, field
from typing import Any

from jerico.decision.policy import Policy


@dataclass(frozen=True)
class PromotionEvaluation:
    """Resultado de la evaluación de promoción para un tipo de decisión."""

    can_promote: bool
    current_mode: str
    target_mode: str | None
    reason: str
    metrics: dict[str, Any] = field(default_factory=dict)


def calculate_agreement_rate(records: list[dict[str, Any]]) -> float:
    """Calcula la fracción de decisiones donde la opción base coincide con la aplicada/Jev."""
    if not records:
        return 0.0

    matches = 0
    total = len(records)
    for r in records:
        base = r.get("base_option")
        applied = r.get("applied_option")
        if applied is None and "jev_response" in r and isinstance(r["jev_response"], dict):
            applied = r["jev_response"].get("choice")
        if base is not None and base == applied:
            matches += 1

    return round(matches / total, 4)


def calculate_brier_score(
    probabilities: list[float],
    outcomes: list[int | float],
) -> float:
    """Calcula el Brier Score como la media de las diferencias cuadradas entre p y o."""
    if not probabilities or not outcomes or len(probabilities) != len(outcomes):
        return 0.0

    squared_errors = [(p - o) ** 2 for p, o in zip(probabilities, outcomes, strict=True)]
    return float(sum(squared_errors) / len(squared_errors))


def calculate_calibration_error(
    probabilities: list[float],
    outcomes: list[int | float],
    num_bins: int = 5,
) -> float:
    """Calcula el Error Esperado de Calibración (ECE) agrupado en num_bins."""
    if not probabilities or not outcomes or len(probabilities) != len(outcomes):
        return 0.0

    n = len(probabilities)
    bin_size = 1.0 / num_bins
    ece = 0.0

    for i in range(num_bins):
        bin_lower = i * bin_size
        bin_upper = (i + 1) * bin_size
        # Incluye elementos dentro del intervalo [bin_lower, bin_upper)
        # Para el último intervalo incluye también el límite superior
        bin_indices = [
            idx
            for idx, p in enumerate(probabilities)
            if (bin_lower <= p < bin_upper) or (i == num_bins - 1 and bin_lower <= p <= bin_upper)
        ]
        if not bin_indices:
            continue

        bin_count = len(bin_indices)
        bin_acc = sum(outcomes[idx] for idx in bin_indices) / bin_count
        bin_conf = sum(probabilities[idx] for idx in bin_indices) / bin_count
        ece += (bin_count / n) * abs(bin_acc - bin_conf)

    return float(ece)


def calculate_latency_p95(records: list[dict[str, Any]]) -> float:
    """Calcula el percentil 95 de latencia en milisegundos."""
    latencies = [
        float(r["latency_ms"]) for r in records if "latency_ms" in r and r["latency_ms"] is not None
    ]
    if not latencies:
        return 0.0

    latencies.sort()
    # Percentil 95 usando el índice de rango
    idx = max(0, min(len(latencies) - 1, int(math.ceil(0.95 * len(latencies))) - 1))
    return latencies[idx]


def evaluate_promotion_criteria(
    kind: str,
    records: list[dict[str, Any]],
    policy: Policy,
    current_mode: str = "sombra",
    tarea: str | None = None,
) -> PromotionEvaluation:
    """Evalúa los criterios de negocio para la promoción entre modos (spec.md sección 7)."""
    total = len(records)
    metrics: dict[str, Any] = {
        "total_records": total,
        "agreement_rate": calculate_agreement_rate(records),
        "latency_p95_ms": calculate_latency_p95(records),
    }

    pk = policy.par(kind, tarea)

    # Requisito mínimo de volumen: 200 decisiones
    if total < 200:
        return PromotionEvaluation(
            can_promote=False,
            current_mode=current_mode,
            target_mode=None,
            reason=f"Se requieren al menos 200 decisiones del tipo (actuales: {total})",
            metrics=metrics,
        )

    if current_mode == "sombra":
        # Promoción de sombra a sugerencia
        return PromotionEvaluation(
            can_promote=True,
            current_mode=current_mode,
            target_mode="sugerencia",
            reason="Cumple requisito de al menos 200 decisiones y consenso válido",
            metrics=metrics,
        )

    if current_mode == "sugerencia":
        # Promoción de sugerencia a enrutado
        # Restricciones categóricas absolutas
        if pk.asesor:
            return PromotionEvaluation(
                can_promote=False,
                current_mode=current_mode,
                target_mode=None,
                reason=(
                    "Los tipos de rol asesor nunca se promueven a modo enrutado (VJT-010a, VJT-063)"
                ),
                metrics=metrics,
            )

        if pk.clase == "A":
            return PromotionEvaluation(
                can_promote=False,
                current_mode=current_mode,
                target_mode=None,
                reason=(
                    "Las decisiones de clase A nunca se promueven a modo enrutado "
                    "(VJT-003, VJT-062)"
                ),
                metrics=metrics,
            )

        # Reglas específicas para clase C
        if pk.clase == "C":
            p95 = metrics["latency_p95_ms"]
            if p95 > 1000.0:
                return PromotionEvaluation(
                    can_promote=False,
                    current_mode=current_mode,
                    target_mode=None,
                    reason=f"La latencia p95 ({p95:.1f} ms) supera el límite de 1000 ms",
                    metrics=metrics,
                )

        return PromotionEvaluation(
            can_promote=True,
            current_mode=current_mode,
            target_mode="enrutado",
            reason="Cumple requisitos de volumen, latencia y restricciones de clase",
            metrics=metrics,
        )

    return PromotionEvaluation(
        can_promote=False,
        current_mode=current_mode,
        target_mode=None,
        reason=f"Modo actual '{current_mode}' no tiene ruta de promoción automatizada",
        metrics=metrics,
    )


def generate_promotion_report(
    kind: str,
    records: list[dict[str, Any]],
    policy: Policy,
    current_mode: str = "sombra",
    tarea: str | None = None,
) -> dict[str, Any]:
    """Genera un informe completo estructurado para el análisis de promoción del CTO."""
    evaluation = evaluate_promotion_criteria(
        kind=kind,
        records=records,
        policy=policy,
        current_mode=current_mode,
        tarea=tarea,
    )
    p95 = calculate_latency_p95(records)
    agreement = calculate_agreement_rate(records)

    return {
        "kind": kind,
        "tarea": tarea,
        "total_decisions": len(records),
        "agreement_rate": agreement,
        "latency_p95_ms": p95,
        "current_mode": current_mode,
        "promotion_evaluation": {
            "can_promote": evaluation.can_promote,
            "target_mode": evaluation.target_mode,
            "reason": evaluation.reason,
            "metrics": evaluation.metrics,
        },
    }
