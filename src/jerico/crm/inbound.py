"""Respuestas entrantes: texto nuevo, palabra «BAJA» y token de baja (plan-f2 §5.7).

Requisitos: VCRM-102, 120 y 124.

Módulo puro, sin E/S. La baja se honra de inmediato y sin confirmación humana (J-06), por eso el
texto que se evalúa es solo el redactado por el remitente: nunca el contenido citado ni el pie
«responda BAJA» de nuestros propios mensajes.
"""

import hashlib
import hmac
import re
import unicodedata
from collections.abc import Iterable

DISPLAY_LIMIT = 1500  # caracteres que se muestran al comercial (plan-f2 §5.7)

_TOKEN_RE = re.compile(r"(\d{1,12})\.([0-9a-f]{24})")
_SUBJECT_RE = re.compile(r"\s*BAJA\s+(\S+)\s*", re.IGNORECASE)
_STOP_RE = re.compile(r"(?<!\w)baja(?!\w)")
_ORIGINAL_MARKER_RE = re.compile(
    r"\s*-{2,}\s*"
    r"(?:original message|mensaje original|forwarded message|mensaje reenviado)"
    r"\s*-{2,}\s*",
    re.IGNORECASE,
)
_WROTE_RE = re.compile(r"(?:wrote|escribi[óo])\s*:\s*$", re.IGNORECASE)
_HEADER_FROM_RE = re.compile(r"\s*(?:De|From)\s*:", re.IGNORECASE)
_HEADER_DATE_RE = re.compile(r"\s*(?:Enviado(?: el)?|Sent|Fecha|Date)\s*:", re.IGNORECASE)
_FOOTER_PHRASE = "responda baja"  # pie fijo de nuestros mensajes (VCRM-069)
_WRAPPED_HEADER_LINES = 3  # «On … wrote:» puede venir partido en hasta 3 líneas
_OUTLOOK_LOOKAHEAD = 4
_MIN_ORIGINAL_LINE = 12  # líneas más cortas podrían ser la propia respuesta del cliente


def _fold(text: str) -> str:
    """Minúsculas y sin tildes (NFKD)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def has_stop_keyword(text: str) -> bool:
    """«BAJA» como palabra completa, sin distinguir mayúsculas ni tildes (spec 4.5)."""
    return _STOP_RE.search(_fold(text)) is not None


def _starts_reply_header(lines: list[str], i: int) -> bool:
    first = lines[i].lstrip()
    if _ORIGINAL_MARKER_RE.fullmatch(lines[i]):
        return True
    if first[:3].lower() in ("on ", "el "):
        for j in range(i, min(i + _WRAPPED_HEADER_LINES, len(lines))):
            if _WROTE_RE.search(" ".join(line.strip() for line in lines[i : j + 1])):
                return True
    if _HEADER_FROM_RE.match(lines[i]):
        window = lines[i + 1 : i + 1 + _OUTLOOK_LOOKAHEAD]
        return any(_HEADER_DATE_RE.match(line) for line in window)
    return False


def _normalized(line: str) -> str:
    return " ".join(_fold(line).split())


def _original_lines(original: str | None) -> frozenset[str]:
    """Líneas de nuestro mensaje lo bastante largas para no confundirse con texto del cliente."""
    if not original:
        return frozenset()
    normalized = (_normalized(line) for line in original.splitlines())
    return frozenset(line for line in normalized if len(line) >= _MIN_ORIGINAL_LINE)


def extract_new_text(body: str, original: str | None = None) -> str:
    """Texto redactado por el remitente: sin citas `>`, sin lo que sigue a «El … escribió:» /
    «On … wrote:» / «Original Message» / cabeceras de Outlook, sin el pie de nuestro mensaje y,
    si se conoce el `original` que le enviamos, sin las líneas que reprodujo tal cual."""
    ours = _original_lines(original)
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    kept: list[str] = []
    for i, line in enumerate(lines):
        if _starts_reply_header(lines, i):
            break
        if line.lstrip().startswith(">"):
            continue
        if _FOOTER_PHRASE in _fold(line) or _normalized(line) in ours:
            continue
        kept.append(line.rstrip())
    return "\n".join(kept).strip()


def _key_bytes(key: str | bytes) -> bytes:
    return key if isinstance(key, bytes) else key.encode("utf-8")


def _mac(key: str | bytes, send_id: int) -> str:
    digest = hmac.new(_key_bytes(key), f"unsub:{send_id}".encode(), hashlib.sha256)
    return digest.hexdigest()[:24]


def make_unsub_token(send_id: int, key: str | bytes) -> str:
    """`<id de envío>.<HMAC-SHA256 truncado a 96 bits>` con prefijo de dominio `unsub:`."""
    if isinstance(send_id, bool) or not isinstance(send_id, int) or send_id < 0:
        raise ValueError("send_id debe ser un entero no negativo")
    return f"{send_id}.{_mac(key, send_id)}"


def verify_unsub_token(token: str, keys: Iterable[str | bytes]) -> int | None:
    """Id de envío si el token es canónico y su firma vale para alguna clave; si no, `None`."""
    match = _TOKEN_RE.fullmatch(token)
    if match is None:
        return None
    raw_id, mac = match.groups()
    send_id = int(raw_id)
    if str(send_id) != raw_id:  # sin ceros a la izquierda: un único texto por envío
        return None
    valid = False
    for key in keys:
        valid |= hmac.compare_digest(mac, _mac(key, send_id))
    return send_id if valid else None


def unsub_subject(token: str) -> str:
    """Asunto del correo de baja generado por la cabecera `List-Unsubscribe`."""
    return f"BAJA {token}"


def parse_unsub_subject(subject: str) -> str | None:
    """Token de un asunto exactamente «BAJA <token>»; `None` en cualquier otro caso."""
    match = _SUBJECT_RE.fullmatch(subject)
    return match.group(1) if match else None


def plain_excerpt(text: str, limit: int = DISPLAY_LIMIT) -> str:
    """Texto plano para mostrar: sin caracteres de control ni de formato Unicode, truncado."""
    cleaned = "".join(c for c in text if c in "\n\t" or unicodedata.category(c) not in ("Cc", "Cf"))
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"
