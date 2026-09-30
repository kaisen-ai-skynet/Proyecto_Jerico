from jerico.agent.types import TokenPressureLevel


class TurnOverflowDetector:
    @staticmethod
    def should_compact(
        current_tokens: int,
        max_window: int,
        threshold: float = 0.80,
    ) -> bool:
        if current_tokens < 0 or max_window <= 0:
            raise ValueError("tokens debe ser no negativo y max_window positivo")
        if not 0 < threshold <= 1:
            raise ValueError("threshold debe estar en (0, 1]")
        return current_tokens / max_window > threshold

    @staticmethod
    def classify(current_tokens: int, max_window: int) -> TokenPressureLevel:
        if current_tokens < 0 or max_window <= 0:
            raise ValueError("tokens debe ser no negativo y max_window positivo")
        ratio = current_tokens / max_window
        if ratio > 1:
            return TokenPressureLevel.OVERFLOW
        if ratio > 0.8:
            return TokenPressureLevel.ELEVATED
        return TokenPressureLevel.LOW
