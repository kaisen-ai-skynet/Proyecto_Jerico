"""Base propia del CRM: SQLite WAL, escritor serializado y esquema versionado (plan §3).

Regla obligatoria: ningún bloque `with db.tx()` contiene un `await`; toda E/S de red
ocurre antes o después de la transacción.
"""

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from jerico.crm.migrate import migrate_if_needed

BUSY_TIMEOUT_MS = 60_000
SCHEMA_VERSION = 2

_DDL: tuple[str, ...] = (
    "CREATE TABLE IF NOT EXISTS crm_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS crm_users (
  id INTEGER PRIMARY KEY,
  telegram_id BIGINT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('commercial','cto','lawyer')),
  email TEXT NOT NULL,
  active SMALLINT NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, deactivated_at TEXT
)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_users_active_tg ON crm_users (telegram_id) "
    "WHERE active = 1",
    """CREATE TABLE IF NOT EXISTS crm_leads (
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
)""",
    "CREATE INDEX IF NOT EXISTS ix_leads_phone ON crm_leads (phone_e164)",
    "CREATE INDEX IF NOT EXISTS ix_leads_email ON crm_leads (email)",
    "CREATE INDEX IF NOT EXISTS ix_leads_assigned "
    "ON crm_leads (assigned_user_id, last_interaction_at)",
    """CREATE TABLE IF NOT EXISTS crm_lead_events (
  id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES crm_leads(id),
  kind TEXT NOT NULL CHECK (kind IN ('state','field','reassign','titular_request')),
  field TEXT, old_value TEXT, new_value TEXT, reason TEXT, reason_text TEXT,
  actor_user_id INTEGER NOT NULL, at TEXT NOT NULL
)""",
    "CREATE TABLE IF NOT EXISTS crm_notes (id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL, "
    "author_user_id INTEGER NOT NULL, body TEXT NOT NULL, at TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS crm_attachments (
  id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('photo','document','voice','authorization')),
  author_user_id INTEGER NOT NULL, at TEXT NOT NULL,
  storage_key TEXT NOT NULL, size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, deleted_at TEXT
)""",
    """CREATE TABLE IF NOT EXISTS crm_consents (
  id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL, status TEXT NOT NULL, medium TEXT NOT NULL,
  at TEXT NOT NULL, actor_user_id INTEGER NOT NULL, notice_version TEXT, purposes TEXT,
  attachment_id INTEGER
)""",
    "CREATE TABLE IF NOT EXISTS crm_suppression "
    "(fingerprint TEXT PRIMARY KEY, at TEXT NOT NULL, medium TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS crm_titular_requests (
  id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('inquiry','claim','unclassified')),
  medium TEXT NOT NULL, received_on TEXT NOT NULL, due_on TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','overdue','attended')),
  registered_by INTEGER NOT NULL, registered_at TEXT NOT NULL,
  last_escalation_on TEXT, attended_by INTEGER, attended_at TEXT,
  inbound_id INTEGER
)""",
    """CREATE TABLE IF NOT EXISTS crm_outbox (
  id INTEGER PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL, critical SMALLINT NOT NULL,
  channel TEXT NOT NULL CHECK (channel IN ('telegram','email')),
  recipient_user_id INTEGER NOT NULL, lead_id INTEGER, origin_outbox_id INTEGER,
  subject TEXT, body TEXT,
  status TEXT NOT NULL CHECK (status IN ('pending','delivered','failed')),
  attempts SMALLINT NOT NULL DEFAULT 0, first_attempt_at TEXT, next_attempt_at TEXT,
  last_error TEXT, provider_message_id TEXT, created_at TEXT NOT NULL
)""",
    "CREATE INDEX IF NOT EXISTS ix_outbox_due ON crm_outbox (status, next_attempt_at)",
    """CREATE TABLE IF NOT EXISTS crm_alerts (
  id INTEGER PRIMARY KEY, lead_id INTEGER, kind TEXT NOT NULL, outbox_id INTEGER,
  request_id INTEGER, created_at TEXT NOT NULL, resolved_by INTEGER, resolved_at TEXT
)""",
    """CREATE TABLE IF NOT EXISTS crm_audit (
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, actor TEXT NOT NULL,
  action TEXT NOT NULL, lead_id INTEGER, outcome TEXT NOT NULL, detail_code TEXT
)""",
    "CREATE TABLE IF NOT EXISTS crm_processed_updates "
    "(update_id BIGINT PRIMARY KEY, processed_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS crm_pending_inputs (user_id INTEGER PRIMARY KEY, "
    "kind TEXT NOT NULL, lead_id INTEGER, data TEXT, expires_at TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS crm_confirmations (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('accept','retract','authorization_question')),
  lead_id INTEGER NOT NULL, user_id INTEGER NOT NULL, reason TEXT, reason_text TEXT,
  status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL, resolved_at TEXT
)""",
    """CREATE TABLE IF NOT EXISTS crm_retention_notices (
  lead_id INTEGER NOT NULL, clock_start TEXT NOT NULL, kind TEXT NOT NULL,
  sent_at TEXT NOT NULL, PRIMARY KEY (lead_id, clock_start, kind)
)""",
    """CREATE TABLE IF NOT EXISTS crm_cadences (
  lead_id INTEGER PRIMARY KEY REFERENCES crm_leads(id),
  reason TEXT NOT NULL,
  interval_days INTEGER NOT NULL,
  total_steps INTEGER NOT NULL,
  steps_done INTEGER NOT NULL DEFAULT 0,
  sent_count INTEGER NOT NULL DEFAULT 0,
  next_action_at TEXT,
  last_sent_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('active','paused','completed','stopped')),
  started_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS crm_proposals (
  id INTEGER PRIMARY KEY,
  lead_id INTEGER NOT NULL REFERENCES crm_leads(id),
  kind TEXT NOT NULL CHECK (kind IN ('followup','auth_request')),
  step INTEGER,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','approved','sent','failed','cancelled','expired','blocked')),
  current_version INTEGER NOT NULL DEFAULT 1,
  approver_user_id INTEGER NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  resolved_at TEXT,
  resolved_by INTEGER
)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_proposals_followup_step "
    "ON crm_proposals (lead_id, step) WHERE kind = 'followup'",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_proposals_open_auth_request "
    "ON crm_proposals (lead_id) WHERE kind = 'auth_request' AND status IN ('pending','approved')",
    """CREATE TABLE IF NOT EXISTS crm_proposal_versions (
  proposal_id INTEGER NOT NULL REFERENCES crm_proposals(id),
  version INTEGER NOT NULL,
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  author_user_id INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (proposal_id, version)
)""",
    """CREATE TABLE IF NOT EXISTS crm_sends (
  id INTEGER PRIMARY KEY,
  proposal_id INTEGER NOT NULL UNIQUE REFERENCES crm_proposals(id),
  version INTEGER NOT NULL,
  approved_hash TEXT NOT NULL,
  approved_by INTEGER NOT NULL,
  approved_at TEXT NOT NULL,
  scheduled_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('scheduled','sent','failed','cancelled')),
  attempts INTEGER NOT NULL DEFAULT 0,
  first_attempt_at TEXT,
  next_attempt_at TEXT,
  rfc_message_id TEXT,
  last_error TEXT,
  sent_at TEXT,
  lead_id INTEGER NOT NULL REFERENCES crm_leads(id),
  week_start TEXT NOT NULL
)""",
    "CREATE INDEX IF NOT EXISTS ix_sends_lead_week_status "
    "ON crm_sends (lead_id, week_start, status)",
    """CREATE TABLE IF NOT EXISTS crm_inbound (
  id INTEGER PRIMARY KEY,
  rfc_message_id TEXT NOT NULL UNIQUE,
  uid INTEGER,
  received_at TEXT NOT NULL,
  sender_fp TEXT NOT NULL,
  lead_id INTEGER REFERENCES crm_leads(id),
  association TEXT NOT NULL CHECK (association IN ('thread','sender','token','none')),
  classification TEXT NOT NULL
    CHECK (classification IN (
      'stop_keyword','stop_header','auth_candidate','review','unassociated'
    )),
  new_text TEXT,
  decision TEXT NOT NULL DEFAULT 'pending'
    CHECK (decision IN ('pending','confirmed','rejected','n/a')),
  decided_by INTEGER,
  decided_at TEXT
)""",
    "INSERT INTO crm_meta (key, value) VALUES ('schema_version', '2') ON CONFLICT (key) DO NOTHING",
)

SCHEMA_SQL = ";\n".join(_DDL) + ";\n"


class CrmDatabase:
    """Una conexión escritora protegida por `RLock`; las lecturas usan la misma conexión."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        migrate_if_needed(self.path)  # VCRM-171: una base v1 se migra antes de cualquier consulta
        self._lock = threading.RLock()
        conn = sqlite3.connect(
            str(self.path),
            timeout=BUSY_TIMEOUT_MS / 1000,
            isolation_level=None,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        self._conn: sqlite3.Connection | None = conn
        try:
            mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if str(mode).lower() != "wal":  # pragma: no cover - depende del sistema de archivos
                raise RuntimeError(f"SQLite no habilitó WAL: {mode}")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            with self.tx() as tx:
                for statement in _DDL:
                    tx.execute(statement)
                row = tx.execute(
                    "SELECT value FROM crm_meta WHERE key = 'schema_version'"
                ).fetchone()
                if row["value"] != str(SCHEMA_VERSION):
                    raise RuntimeError(
                        f"schema_version {row['value']} no soportada (esperada {SCHEMA_VERSION})"
                    )
        except Exception:
            self.close()
            raise

    def _require(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("CrmDatabase cerrada")
        return self._conn

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Transacción `BEGIN IMMEDIATE`; *commit* al salir, *rollback* ante excepción."""
        conn = self._require()
        with self._lock:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.rollback()
                raise
            conn.commit()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """Lecturas sobre la misma conexión, serializadas con el escritor."""
        conn = self._require()
        with self._lock:
            yield conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
