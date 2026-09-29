import re
from dataclasses import dataclass, field

from jerico.config import Settings
from jerico.textutil import normalize

L0_ANSWERS = {
    "hola": "Hola. ¿En qué te ayudo?",
    "hey": "Hey. ¿En qué te ayudo?",
    "buenas": "Buenas. ¿En qué te ayudo?",
    "buenos dias": "Buenos días. ¿En qué te ayudo?",
    "buenas tardes": "Buenas tardes. ¿En qué te ayudo?",
    "buenas noches": "Buenas noches. ¿En qué te ayudo?",
    "que tal": "Aquí estoy. ¿En qué te ayudo?",
    "gracias": "Con gusto. Aquí estoy si necesitas algo más.",
    "adios": "Hasta luego.",
    "ok": "Ok.",
}
EMPTY_ANSWER = "¿En qué te ayudo?"


@dataclass
class RouteDecision:
    level: int
    model: str
    reason: str
    answer: str | None = field(default=None)


def _pattern(keywords: tuple[str, ...]) -> re.Pattern[str] | None:
    if not keywords:
        return None
    # Plural opcional: "contratos" y "bugs" no pueden escaparse del nivel.
    # Lookarounds en vez de \b: con \b, keywords como "c++" o "c#" nunca matchean.
    return re.compile(
        "|".join(rf"(?<!\w){re.escape(word)}(?:s|es)?(?!\w)" for word in keywords)
    )


def _l0_key(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text)).strip()


class TokenRouter:
    """L0 local / L1 operativo / L2 código / L3 alto riesgo. Modelos salen de config."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()
        self._l2 = _pattern(self._settings.l2_keywords)
        self._l3 = _pattern(self._settings.l3_keywords)
        self._exceptions = self._settings.l2_exceptions

    def classify(self, prompt: str) -> int:
        text = normalize(prompt)
        key = _l0_key(text)
        if not key or key in L0_ANSWERS:
            return 0
        # Las excepciones son de L2: nunca degradan una señal de alto riesgo.
        if self._l3 and self._l3.search(text):
            return 3
        scanned = text
        for phrase in sorted(self._exceptions, key=len, reverse=True):
            scanned = scanned.replace(phrase, " ")
        if self._l2 and self._l2.search(scanned):
            return 2
        return 1

    def model_for_level(self, level: int) -> str:
        return self._settings.model_for_level(level)

    def route(self, prompt: str) -> RouteDecision:
        level = self.classify(prompt)
        if level == 0:
            answer = L0_ANSWERS.get(_l0_key(normalize(prompt)), EMPTY_ANSWER)
            return RouteDecision(0, "none", "saludo/conversacional", answer)
        reason = {3: "l3-keyword", 2: "l2-keyword"}.get(level, "operativo")
        return RouteDecision(level, self.model_for_level(level), reason)
