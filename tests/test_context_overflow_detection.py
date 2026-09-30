import pytest

from jerico.agent.turn_overflow import TurnOverflowDetector
from jerico.agent.types import TokenPressureLevel


@pytest.mark.parametrize(
    ("tokens", "threshold", "expected"),
    [(79, 0.8, False), (80, 0.8, False), (81, 0.8, True), (99, 0.8, True)],
)
def test_deteccion_compactacion_estrictamente_sobre_umbral(tokens, threshold, expected):
    assert TurnOverflowDetector.should_compact(tokens, 100, threshold) is expected


def test_clasifica_overflow_and_invalid_bounds():
    assert TurnOverflowDetector.classify(101, 100) is TokenPressureLevel.OVERFLOW
    with pytest.raises(ValueError):
        TurnOverflowDetector.should_compact(-1, 100)
    with pytest.raises(ValueError):
        TurnOverflowDetector.should_compact(1, 0)
    with pytest.raises(ValueError):
        TurnOverflowDetector.should_compact(1, 100, 0)
