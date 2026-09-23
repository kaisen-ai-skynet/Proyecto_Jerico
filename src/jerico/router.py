from dataclasses import dataclass, field

from jerico.config import Settings

L2_DEFAULT_KEYWORDS = ("codigo", "auditoria", "finanzas", "arquitectura")


@dataclass
class RouteDecision:
    level: int
    model: str
    reason: str
    answer: str | None = field(default=None)


L0_ANSWERS = {
    "hola": "Hola. ¿En qué te ayudo?",
    "buenos dias": "Buenos días. ¿En qué te ayudo?",
    "buenas tardes": "Buenas tardes. ¿En qué te ayudo?",
    "buenas noches": "Buenas noches. ¿En qué te ayudo?",
    "gracias": "Con gusto. Aquí estoy si necesitas algo más.",
    "adios": "Hasta luego.",
}


class TokenRouter:
    """Ruteo de tokens L0 directo / L1 GLM / L2 DeepSeek (v2 20/09/2026)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()
        self._l2_keywords = self._settings.l2_keywords or L2_DEFAULT_KEYWORDS
        self._model_l1 = self._settings.llm_model_l1
        self._model_l2 = self._settings.llm_model_l2

    def classify(self, prompt: str) -> int:
        text = prompt.strip().lower()
        if not text:
            return 0
        if text in L0_ANSWERS:
            return 0
        if any(k in text for k in self._l2_keywords):
            return 2
        return 1

    def model_for_level(self, level: int) -> str:
        if level >= 2:
            return self._model_l2
        return self._model_l1

    def route(self, prompt: str) -> RouteDecision:
        """Decide nivel; L0 responde directo sin tools ni LLM."""
        level = self.classify(prompt)
        if level == 0:
            text = prompt.strip().lower()
            return RouteDecision(0, "none", "saludo/conversacional", L0_ANSWERS.get(text))
        reason = "keyword" if level == 2 else "operativo"
        return RouteDecision(level, self.model_for_level(level), reason)
