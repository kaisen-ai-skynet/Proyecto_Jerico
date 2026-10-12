"""Textos de seguimiento comercial, pie legal y solicitud de autorización (F2-T08).

Requisitos: VCRM-027, 069, 148, 149, 161 (plan-f2 §5.3, §5.5, §5.6).
Módulo puro salvo la lectura de archivos TOML locales. Sin red, sin datetime.now().
"""

from __future__ import annotations

import tomllib
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

_DISALLOWED_CATEGORIES = frozenset({"Cc", "Cf"})
_DEFAULT_CLIENT_NAME = "cliente"
_DEFAULT_COMMERCIAL_NAME = "el equipo de Kaisen AI"
_DEFAULT_SENDER_NAME = "Kaisen AI"
_UNSUB_PHRASE = "Responda BAJA para no recibir más mensajes."


def _sanitize_string(value: str, default: str) -> str:
    """Elimina caracteres de control (Cc, Cf) y saltos de línea; devuelve default si queda vacío."""
    cleaned = "".join(
        c
        for c in value
        if unicodedata.category(c) not in _DISALLOWED_CATEGORIES and c not in ("\r", "\n")
    ).strip()
    return cleaned if cleaned else default


@dataclass(frozen=True)
class FollowupTexts:
    """Plantillas de seguimiento comercial cargadas desde archivo TOML."""

    version: str
    reasons: tuple[str, ...]
    _texts: dict[str, dict[str, str]] = field(default_factory=dict, repr=False)

    def lookup(self, reason: str, step: int) -> str | None:
        """Texto crudo del paso o None si falta el motivo o el paso (VCRM-161)."""
        table = self._texts.get(reason)
        if not table:
            return None
        return table.get(str(step))

    def subject(self, reason: str) -> str | None:
        """Asunto configurado para el motivo o None si no existe."""
        table = self._texts.get(reason)
        if not table:
            return None
        return table.get("subject")


def load_followup_texts(path: Path) -> FollowupTexts | None:
    """Carga textos de cadencias desde un archivo TOML.

    Devuelve None si el archivo no existe, no es legible, no es UTF-8, es TOML inválido
    o carece de versión. En errores, no registra el contenido del archivo ni el texto
    de tomllib, solo la ruta y el nombre del tipo de error a nivel warning (loguru).
    """
    try:
        raw_bytes = path.read_bytes()
    except (OSError, FileNotFoundError) as exc:
        logger.warning(
            "No se pudo cargar textos de seguimiento desde {path}: {error_type}",
            path=str(path),
            error_type=type(exc).__name__,
        )
        return None

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        logger.warning(
            "No se pudo cargar textos de seguimiento desde {path}: {error_type}",
            path=str(path),
            error_type=type(exc).__name__,
        )
        return None

    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        logger.warning(
            "No se pudo cargar textos de seguimiento desde {path}: {error_type}",
            path=str(path),
            error_type=type(exc).__name__,
        )
        return None

    version = parsed.get("version")
    if not isinstance(version, str) or not version.strip():
        logger.warning(
            "No se pudo cargar textos de seguimiento desde {path}: {error_type}",
            path=str(path),
            error_type="MissingVersionError",
        )
        return None

    texts: dict[str, dict[str, str]] = {}
    reasons_list: list[str] = []

    for key, val in parsed.items():
        if key == "version" or not isinstance(val, dict):
            continue
        cleaned_table: dict[str, str] = {}
        for subkey, subval in val.items():
            if isinstance(subval, str) and subval.strip():
                cleaned_table[str(subkey)] = subval
        if cleaned_table:
            texts[key] = cleaned_table
            reasons_list.append(key)

    return FollowupTexts(
        version=version.strip(),
        reasons=tuple(reasons_list),
        _texts=texts,
    )


def render(text: str, *, name: str, commercial: str) -> str:
    """Sustituye SOLO {nombre} y {comercial} con str.replace; cualquier otra llave queda intacta."""
    clean_name = _sanitize_string(name, _DEFAULT_CLIENT_NAME)
    clean_commercial = _sanitize_string(commercial, _DEFAULT_COMMERCIAL_NAME)
    return text.replace("{nombre}", clean_name).replace("{comercial}", clean_commercial)


def footer(sender_name: str) -> str:
    """Pie fijo de todo mensaje comercial (VCRM-069), sin enlaces ni URLs."""
    clean_sender = _sanitize_string(sender_name, _DEFAULT_SENDER_NAME)
    return f"{clean_sender}\n{_UNSUB_PHRASE}"


def auth_request_body(
    notice: str,
    version: str,
    processors: Sequence[str],
    sender_name: str,
) -> str:
    """Cuerpo de la solicitud de autorización de tratamiento de datos (VCRM-068, 148, 149)."""
    n = notice.strip()
    if not n:
        raise ValueError("notice no puede estar vacío o contener solo espacios")

    v = version.strip()
    if not v:
        raise ValueError("version no puede estar vacía o contener solo espacios")

    cleaned_procs = [p.strip() for p in processors if isinstance(p, str) and p.strip()]
    if not cleaned_procs:
        raise ValueError("processors no puede estar vacío")

    clean_sender = _sanitize_string(sender_name, _DEFAULT_SENDER_NAME)
    procs_text = ", ".join(cleaned_procs)

    lines = [
        "Hola,",
        "",
        f"Le escribe {clean_sender}, de Kaisen AI.",
        f"Aviso de privacidad, versión {v}.",
        f"Utilizamos como encargados del tratamiento: {procs_text}.",
        "",
        "Para otorgar su autorización, responda a este correo indicando que acepta.",
        f"{_UNSUB_PHRASE}",
        "",
        "---",
        "",
        n,
        "",
        footer(clean_sender),
    ]
    return "\n".join(lines)


__all__ = [
    "FollowupTexts",
    "auth_request_body",
    "footer",
    "load_followup_texts",
    "render",
]
