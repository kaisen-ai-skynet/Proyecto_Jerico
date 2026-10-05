"""Huella HMAC-SHA-256 del contacto normalizado con rotación de clave (VCRM-095, 088). Pura."""

import hashlib
import hmac
from collections.abc import Collection, Iterable


def fingerprint(key: str | bytes, normalized: str) -> str:
    """Huella hexadecimal de un contacto ya normalizado (E.164 o correo en minúsculas)."""
    key_bytes = key.encode("utf-8") if isinstance(key, str) else key
    if not key_bytes:
        raise ValueError("fingerprint key must not be empty")
    return hmac.new(key_bytes, normalized.encode("utf-8"), hashlib.sha256).hexdigest()


def matches(fp_set: Collection[str], normalized: str, keys: Iterable[str | bytes]) -> bool:
    """True si la huella del contacto con la clave actual o alguna previa está en `fp_set`."""
    return any(fingerprint(key, normalized) in fp_set for key in keys)
