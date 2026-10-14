"""Idempotencia determinista de acciones externas (Plan Maestro §4).

Toda acción que cambia estado o sale a un tercero (enviar al abogado, enviar a firma, crear un
lead desde un correo) reserva primero una clave determinista: la segunda vez no se repite."""

import sqlite3
from datetime import datetime

from jerico.crm.timeutil import to_iso


def make_key(scope: str, *parts: object) -> str:
    if not scope:
        raise ValueError("la clave de idempotencia exige un ámbito")
    return ":".join([scope, *(str(part) for part in parts)])


def claim(conn: sqlite3.Connection, key: str, now: datetime) -> bool:
    """True solo la primera vez que se reserva `key` (dentro de la transacción del llamador)."""
    scope = key.split(":", 1)[0]
    row = conn.execute(
        "INSERT INTO crm_idempotency (key, scope, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT DO NOTHING RETURNING key",
        (key, scope, to_iso(now)),
    ).fetchone()
    return row is not None
