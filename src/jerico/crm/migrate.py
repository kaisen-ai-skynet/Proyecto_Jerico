"""Migración de esquema v1 → v2: valores de dominio en inglés (VCRM-171, plan-f2 §2).

Se ejecuta con el servicio detenido, antes de cualquier consulta de negocio:
1. copia previa `<db>.pre-v2.bak` con la API de respaldo de `sqlite3` y `integrity_check`;
2. una única transacción `BEGIN IMMEDIATE`: verifica que no haya valores fuera del mapa,
   actualiza columnas, reconstruye las tablas con `CHECK`/`DEFAULT` v2, comprueba claves foráneas
   y sube `schema_version` a 2;
3. cualquier error deshace todo y la base queda en v1 intacta.

El DDL v2 de las tablas reconstruidas está congelado aquí (una migración no debe cambiar si
`db.py` evoluciona). Idempotente: con `schema_version = 2` no hace nada.
No hay migración descendente.
"""

import sqlite3
from pathlib import Path

STATE_MAP = {
    "nuevo": "new",
    "contactado": "contacted",
    "aceptado": "accepted",
    "rechazado": "rejected",
    "en_nutricion": "nurturing",
    "pausado": "paused",
    "reactivado": "reactivated",
    "ganado": "won",
    "perdido": "lost",
    "baja": "opted_out",
}
AUTH_MAP = {
    "sin_autorizacion": "unauthorized",
    "autorizada": "authorized",
    "revocada": "revoked",
}
OUTBOX_MAP = {"pendiente": "pending", "entregada": "delivered", "fallida": "failed"}
REQUEST_TYPE_MAP = {"consulta": "inquiry", "reclamo": "claim"}
REQUEST_STATUS_MAP = {"abierta": "open", "vencida": "overdue", "atendida": "attended"}
CONFIRMATION_MAP = {"pendiente": "pending", "confirmada": "confirmed", "cancelada": "cancelled"}

_MAX_VALUE_CHARS = 40

_LEADS_V2 = """CREATE TABLE crm_leads__v2 (
  id INTEGER PRIMARY KEY,
  assigned_user_id INTEGER REFERENCES crm_users(id),
  state TEXT NOT NULL,
  name TEXT, phone_e164 TEXT, email TEXT, company TEXT,
  client_type TEXT, doc_type TEXT, doc_number TEXT, legal_rep TEXT,
  service TEXT, agreed_value TEXT, start_term TEXT,
  reject_reason TEXT, reject_text TEXT, rejection_is_retraction SMALLINT NOT NULL DEFAULT 0,
  auth_status TEXT NOT NULL DEFAULT 'unauthorized',
  ever_accepted SMALLINT NOT NULL DEFAULT 0,
  registered_at TEXT NOT NULL, last_interaction_at TEXT NOT NULL,
  accepted_exit_at TEXT,
  won_at TEXT, final_state_at TEXT,
  legal_hold_basis TEXT, commercial_block SMALLINT NOT NULL DEFAULT 0,
  suppressed_at TEXT, suppression_cause TEXT
)"""
_OUTBOX_V2 = """CREATE TABLE crm_outbox__v2 (
  id INTEGER PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL, critical SMALLINT NOT NULL,
  channel TEXT NOT NULL CHECK (channel IN ('telegram','email')),
  recipient_user_id INTEGER NOT NULL, lead_id INTEGER, origin_outbox_id INTEGER,
  subject TEXT, body TEXT,
  status TEXT NOT NULL CHECK (status IN ('pending','delivered','failed')),
  attempts SMALLINT NOT NULL DEFAULT 0, first_attempt_at TEXT, next_attempt_at TEXT,
  last_error TEXT, provider_message_id TEXT, created_at TEXT NOT NULL
)"""
_REQUESTS_V2 = """CREATE TABLE crm_titular_requests__v2 (
  id INTEGER PRIMARY KEY, lead_id INTEGER,
  type TEXT NOT NULL CHECK (type IN ('inquiry','claim','unclassified')),
  medium TEXT NOT NULL, received_on TEXT NOT NULL, due_on TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','overdue','attended')),
  registered_by INTEGER NOT NULL, registered_at TEXT NOT NULL,
  last_escalation_on TEXT, attended_by INTEGER, attended_at TEXT,
  inbound_id INTEGER
)"""
_CONFIRMATIONS_V2 = """CREATE TABLE crm_confirmations__v2 (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('accept','retract','authorization_question')),
  lead_id INTEGER NOT NULL, user_id INTEGER NOT NULL, reason TEXT, reason_text TEXT,
  status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL, resolved_at TEXT
)"""

# Índices de las tablas reconstruidas (se pierden con el DROP).
_INDEXES_V2 = (
    "CREATE INDEX IF NOT EXISTS ix_leads_phone ON crm_leads (phone_e164)",
    "CREATE INDEX IF NOT EXISTS ix_leads_email ON crm_leads (email)",
    "CREATE INDEX IF NOT EXISTS ix_leads_assigned "
    "ON crm_leads (assigned_user_id, last_interaction_at)",
    "CREATE INDEX IF NOT EXISTS ix_outbox_due ON crm_outbox (status, next_attempt_at)",
)

# Valores permitidos por columna en v1 (R-M1: cualquier otro aborta la migración).
_KNOWN_VALUES: tuple[tuple[str, str, str, dict[str, str]], ...] = (
    ("crm_leads", "state", "", STATE_MAP),
    ("crm_leads", "auth_status", "", AUTH_MAP),
    ("crm_lead_events", "old_value", "kind = 'state'", STATE_MAP),
    ("crm_lead_events", "new_value", "kind = 'state'", STATE_MAP),
    ("crm_consents", "status", "", AUTH_MAP),
    ("crm_outbox", "status", "", OUTBOX_MAP),
    ("crm_titular_requests", "type", "", REQUEST_TYPE_MAP),
    ("crm_titular_requests", "status", "", REQUEST_STATUS_MAP),
    ("crm_confirmations", "status", "", CONFIRMATION_MAP),
)


class MigrationError(RuntimeError):
    """La migración no se aplicó; la base queda en v1 sin cambios."""


def _case(column: str, mapping: dict[str, str]) -> str:
    whens = " ".join(f"WHEN '{old}' THEN '{new}'" for old, new in mapping.items())
    return f"CASE {column} {whens} ELSE {column} END"


def _read_version(conn: sqlite3.Connection) -> str:
    try:
        row = conn.execute("SELECT value FROM crm_meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.Error as exc:
        raise MigrationError("la base no tiene crm_meta/schema_version") from exc
    if row is None:
        raise MigrationError("la base no tiene schema_version")
    return str(row[0])


def _integrity_ok(path: Path) -> bool:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    finally:
        conn.close()


def _backup(conn: sqlite3.Connection, path: Path) -> Path:
    bak = path.with_name(path.name + ".pre-v2.bak")
    bak.unlink(missing_ok=True)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    dst = sqlite3.connect(bak)
    try:
        conn.backup(dst)
    finally:
        dst.close()
    if not _integrity_ok(bak):
        bak.unlink(missing_ok=True)
        raise MigrationError("la copia previa no pasó integrity_check; la base no se tocó")
    return bak


def _unknown_values(conn: sqlite3.Connection) -> list[str]:
    """`tabla.columna=valor` fuera del mapa; el valor se trunca (sin datos personales)."""
    found: list[str] = []
    for table, column, extra, mapping in _KNOWN_VALUES:
        marks = ",".join("?" for _ in mapping)
        where = f"{column} IS NOT NULL AND {column} NOT IN ({marks})"
        if extra:
            where += f" AND {extra}"
        rows = conn.execute(
            f"SELECT DISTINCT {column} FROM {table} WHERE {where}",  # noqa: S608 - nombres fijos
            tuple(mapping),
        ).fetchall()
        found.extend(f"{table}.{column}={str(r[0])[:_MAX_VALUE_CHARS]!r}" for r in rows)
    return found


def _rebuild(
    conn: sqlite3.Connection, table: str, ddl: str, mapping: dict[str, dict[str, str]]
) -> None:
    """Procedimiento de 12 pasos de SQLite: crear nueva, copiar con CASE, borrar, renombrar."""
    columns = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    selected = ", ".join(_case(c, mapping[c]) if c in mapping else c for c in columns)
    conn.execute(ddl)
    conn.execute(
        f"INSERT INTO {table}__v2 ({', '.join(columns)}) SELECT {selected} FROM {table}"  # noqa: S608
    )
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {table}__v2 RENAME TO {table}")


def _apply(conn: sqlite3.Connection) -> None:
    unknown = _unknown_values(conn)
    if unknown:
        raise MigrationError("valores fuera del mapa v1: " + ", ".join(unknown))

    _rebuild(conn, "crm_leads", _LEADS_V2, {"state": STATE_MAP, "auth_status": AUTH_MAP})
    for column in ("old_value", "new_value"):
        conn.execute(
            f"UPDATE crm_lead_events SET {column} = {_case(column, STATE_MAP)} "  # noqa: S608
            "WHERE kind = 'state'"
        )
    conn.execute(f"UPDATE crm_consents SET status = {_case('status', AUTH_MAP)}")  # noqa: S608
    # Referencia al correo que sirvió de evidencia de la autorización (VCRM-141); va al final,
    # igual que en una base nueva, para que ambos esquemas coincidan.
    conn.execute("ALTER TABLE crm_consents ADD COLUMN evidence_inbound_id INTEGER")
    _rebuild(conn, "crm_outbox", _OUTBOX_V2, {"status": OUTBOX_MAP})
    _rebuild(
        conn,
        "crm_titular_requests",
        _REQUESTS_V2,
        {"type": REQUEST_TYPE_MAP, "status": REQUEST_STATUS_MAP},
    )
    _rebuild(conn, "crm_confirmations", _CONFIRMATIONS_V2, {"status": CONFIRMATION_MAP})
    for statement in _INDEXES_V2:
        conn.execute(statement)

    if conn.execute("PRAGMA foreign_key_check").fetchall():
        raise MigrationError("foreign_key_check no quedó vacío; se deshace la migración")
    conn.execute("UPDATE crm_meta SET value = '2' WHERE key = 'schema_version'")


def migrate_v1_to_v2(path: Path) -> None:
    """Migra la base en `path` de v1 a v2; no hace nada si ya está en v2."""
    path = Path(path)
    conn = sqlite3.connect(str(path), isolation_level=None)
    try:
        version = _read_version(conn)
        if version == "2":
            return
        if version != "1":
            raise MigrationError(f"schema_version {version} no migrable a 2")
        _backup(conn, path)
        conn.execute("PRAGMA foreign_keys=OFF")  # requisito del procedimiento de reconstrucción
        conn.execute("BEGIN IMMEDIATE")
        try:
            _apply(conn)
            conn.execute("COMMIT")
        except BaseException as exc:
            conn.execute("ROLLBACK")
            if isinstance(exc, MigrationError):
                raise
            if isinstance(exc, sqlite3.Error):
                raise MigrationError(f"la migración falló y se deshizo: {exc}") from exc
            raise
    finally:
        conn.close()


def current_version(path: Path) -> str | None:
    """`schema_version` de la base en `path`; `None` si no existe, está vacía o no es del CRM."""
    path = Path(path)
    if not path.exists():
        return None
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT value FROM crm_meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return None if row is None else str(row[0])


def migrate_if_needed(path: Path) -> bool:
    """Migra a v2 solo si la base existe y está en v1; devuelve si migró (o `MigrationError`)."""
    if current_version(path) != "1":
        return False
    migrate_v1_to_v2(path)
    return True
