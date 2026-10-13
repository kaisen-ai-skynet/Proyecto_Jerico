"""Seudonimización de datos personales antes de enviarlos a OpenAI (Ley 1581; VCRM-A10..A13).

Función pura: no guarda el mapa ni lo registra. Los marcadores se reponen solo localmente, en la
respuesta que ve el comercial. Es una barrera por valores conocidos del lead y por patrones; no
detecta nombres de terceros escritos en texto libre (riesgo residual A15)."""

import re
import unicodedata
from dataclasses import dataclass

from jerico.crm.model import Lead

_MARKER = re.compile(r"(\[[A-Z_]+\])")
_URL = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_NUMBERISH = re.compile(r"\+?\(?\d[\d\s().\-/]{4,}\d")
_DATE = re.compile(r"\d{1,4}[-/]\d{1,2}[-/]\d{1,4}")
_MIN_PART = 3  # las partes de nombre más cortas no se tratan como identificadores aislados
_MIN_COMPANY_PART = 4
_LEGAL_SUFFIXES = frozenset({"ltda", "sas", "s.a.s", "cia", "eirl"})
_MIN_DIGITS = 6


def _fold(text: str) -> str:
    """Minúsculas sin tildes, conservando la longitud (permite reemplazar por posición)."""
    out: list[str] = []
    for char in text:
        base = unicodedata.normalize("NFD", char)[0]
        lowered = base.lower()
        out.append(lowered if len(lowered) == 1 else base)
    return "".join(out)


def _replace_value(text: str, value: str, marker: str, *, whole_word: bool) -> str:
    """Sustituye `value` (sin distinguir tildes ni mayúsculas) por `marker`."""
    pattern = re.escape(_fold(value.strip()))  # los valores llegan no vacíos por construcción
    if whole_word:
        pattern = rf"(?<!\w){pattern}(?!\w)"
    folded = _fold(text)
    pieces: list[str] = []
    last = 0
    for match in re.finditer(pattern, folded):
        pieces.append(text[last : match.start()])
        pieces.append(marker)
        last = match.end()
    pieces.append(text[last:])
    return "".join(pieces)


def _numberish(match: re.Match[str]) -> str:
    raw = match.group(0)
    if _DATE.fullmatch(raw.strip()):
        return raw
    digits = sum(char.isdigit() for char in raw)
    return "[NUM]" if digits >= _MIN_DIGITS else raw


@dataclass(frozen=True)
class Redactor:
    """Valores conocidos de un lead → marcadores, más depuración por patrones."""

    values: tuple[tuple[str, str], ...]  # (marcador, valor real), más largos primero
    parts: tuple[tuple[str, str], ...]  # (marcador, parte de nombre >= 3 letras)

    @classmethod
    def for_lead(cls, lead: Lead) -> "Redactor":
        pairs = [
            ("[CLIENTE]", lead.name),
            ("[EMPRESA]", lead.company),
            ("[REPRESENTANTE]", lead.legal_rep),
            ("[CORREO]", lead.email),
            ("[TEL]", lead.phone_e164),
            ("[DOC]", lead.doc_number),
        ]
        values = tuple(
            sorted(
                ((marker, value.strip()) for marker, value in pairs if value and value.strip()),
                key=lambda pair: -len(pair[1]),
            )
        )
        parts = tuple(
            (marker, word)
            for marker, value in values
            if marker in {"[CLIENTE]", "[REPRESENTANTE]", "[EMPRESA]"}
            for word in re.findall(r"\w+", value)
            if len(word) >= (_MIN_COMPANY_PART if marker == "[EMPRESA]" else _MIN_PART)
            and word.lower() not in _LEGAL_SUFFIXES
        )
        return cls(values=values, parts=parts)

    def scrub(self, text: str) -> str:
        """Texto sin datos personales conocidos ni patrones de contacto/identificación."""
        segments = _MARKER.split(text)
        for index in range(0, len(segments), 2):  # los marcadores ya puestos no se tocan
            segments[index] = self._scrub_segment(segments[index])
        return "".join(segments)

    def _scrub_segment(self, text: str) -> str:
        for marker, value in self.values:
            text = _replace_value(text, value, marker, whole_word=False)
        for marker, word in self.parts:
            text = _replace_value(text, word, marker, whole_word=True)
        text = _URL.sub("[ENLACE]", text)
        text = _EMAIL.sub("[CORREO_X]", text)
        return _NUMBERISH.sub(_numberish, text)

    def restore(self, text: str) -> str:
        """Repone los marcadores del lead; solo para mostrar al comercial, nunca para enviar."""
        for marker, value in self.values:
            text = text.replace(marker, value)
        return text
