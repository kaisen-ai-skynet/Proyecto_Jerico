"""Pruebas unitarias para evaluator.py (spec 007, F3, T14 y Sección 7 de spec.md)."""

from jerico.decision.evaluator import (
    calculate_agreement_rate,
    calculate_brier_score,
    calculate_calibration_error,
    calculate_latency_p95,
    evaluate_promotion_criteria,
    generate_promotion_report,
)
from jerico.decision.policy import load_policy


def test_calculate_agreement_rate() -> None:
    records = [
        {"base_option": "A", "applied_option": "A"},
        {"base_option": "A", "applied_option": "B"},
        {"base_option": "B", "applied_option": "B"},
        {"base_option": "B", "applied_option": "B"},
    ]
    # 3 de 4 coinciden -> 0.75
    assert calculate_agreement_rate(records) == 0.75

    assert calculate_agreement_rate([]) == 0.0


def test_calculate_brier_score() -> None:
    # Brier score: promedio de (p - o)^2
    # Predicción 0.8 con desenlace 1 -> (0.8 - 1)^2 = 0.04
    # Predicción 0.2 con desenlace 0 -> (0.2 - 0)^2 = 0.04
    # Promedio = 0.04
    brier = calculate_brier_score([0.8, 0.2], [1, 0])
    assert round(brier, 4) == 0.04

    # Predicción perfecta
    assert calculate_brier_score([1.0, 0.0], [1, 0]) == 0.0

    # Predicción inversa
    assert calculate_brier_score([0.0, 1.0], [1, 0]) == 1.0


def test_calculate_calibration_error() -> None:
    # Calibración perfecta
    ece_perfect = calculate_calibration_error([0.9, 0.9], [1, 1], num_bins=5)
    assert round(ece_perfect, 2) <= 0.15

    # Descalibrado (predice 0.9 pero desenlace es 0)
    ece_bad = calculate_calibration_error([0.9, 0.9, 0.9], [0, 0, 0], num_bins=5)
    assert round(ece_bad, 2) >= 0.8


def test_calculate_latency_p95() -> None:
    # 100 registros con latencias 1 a 100
    records = [{"latency_ms": i} for i in range(1, 101)]
    p95 = calculate_latency_p95(records)
    assert 94 <= p95 <= 96

    assert calculate_latency_p95([]) == 0.0


def test_promotion_evaluation_sombra_to_sugerencia() -> None:
    policy = load_policy()

    # Menos de 200 decisiones -> no promovible
    few_records = [
        {"base_option": "gpt-6-luna", "applied_option": "gpt-6-luna", "latency_ms": 250}
        for _ in range(50)
    ]
    eval_few = evaluate_promotion_criteria("modelo", few_records, policy, current_mode="sombra")
    assert eval_few.can_promote is False
    assert "200 decisiones" in eval_few.reason

    # 200 decisiones válidas -> promovible a sugerencia
    valid_records = [
        {"base_option": "gpt-6-luna", "applied_option": "gpt-6-luna", "latency_ms": 250}
        for _ in range(200)
    ]
    eval_ready = evaluate_promotion_criteria("modelo", valid_records, policy, current_mode="sombra")
    assert eval_ready.can_promote is True
    assert eval_ready.target_mode == "sugerencia"


def test_promotion_evaluation_sugerencia_to_enrutado_restrictions() -> None:
    policy = load_policy()

    # Clase A nunca se promueve a enrutado (VJT-003, VJT-062)
    from jerico.decision.policy import Policy

    policy_clase_a = Policy(
        {
            "version": "1.0.0",
            "tipos": {
                "tipo_clase_a": {
                    "clase": "A",
                    "base": "fijo",
                    "opciones": ["fijo"],
                    "modo_defecto": "apagado",
                    "esquema_estado": {"campo": ["val"]},
                }
            },
        }
    )
    records_200 = [
        {"base_option": "humano", "applied_option": "humano", "latency_ms": 200, "confidence": 0.9}
        for _ in range(200)
    ]
    eval_a = evaluate_promotion_criteria(
        "tipo_clase_a", records_200, policy_clase_a, current_mode="sugerencia"
    )
    assert eval_a.can_promote is False
    assert "clase A" in eval_a.reason

    # Asesor nunca se promueve a enrutado (VJT-010a, VJT-063)
    eval_asesor = evaluate_promotion_criteria(
        "seguimiento_lead", records_200, policy, current_mode="sugerencia"
    )
    assert eval_asesor.can_promote is False
    assert "asesor" in eval_asesor.reason

    # Clase C: con latencia p95 > 1000 ms no promueve
    slow_records = [
        {"base_option": "gpt-6-luna", "applied_option": "gpt-6-luna", "latency_ms": 1500}
        for _ in range(200)
    ]
    eval_slow = evaluate_promotion_criteria(
        "modelo", slow_records, policy, current_mode="sugerencia"
    )
    assert eval_slow.can_promote is False
    assert "latencia p95" in eval_slow.reason


def test_generate_promotion_report_content() -> None:
    policy = load_policy()
    records = [
        {
            "event_id": f"evt-{i}",
            "base_option": "gpt-6-luna",
            "applied_option": "gpt-6-luna",
            "latency_ms": 250,
            "cost_usd": "no calculado",
            "jev_response": {"confidence": 0.85},
        }
        for i in range(210)
    ]
    report = generate_promotion_report("modelo", records, policy, current_mode="sombra")

    assert report["kind"] == "modelo"
    assert report["total_decisions"] == 210
    assert report["agreement_rate"] == 1.0
    assert report["latency_p95_ms"] == 250
    assert report["current_mode"] == "sombra"
    assert "promotion_evaluation" in report
