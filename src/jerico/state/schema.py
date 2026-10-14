import sqlite3

from jerico.state.fts import initialize_fts

SCHEMA_VERSION = 3

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS system_prompts (
    prompt_hash TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    system_prompt_hash TEXT NOT NULL REFERENCES system_prompts(prompt_hash),
    model TEXT NOT NULL,
    parent_session_id TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
    user_id INTEGER,
    role TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, role);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool')),
    content TEXT NOT NULL,
    tool_calls_json TEXT,
    tool_call_id TEXT,
    reasoning TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session_id_id ON messages(session_id, id);

CREATE TABLE IF NOT EXISTS session_model_usage (
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0 CHECK (prompt_tokens >= 0),
    completion_tokens INTEGER NOT NULL DEFAULT 0 CHECK (completion_tokens >= 0),
    cached_tokens INTEGER NOT NULL DEFAULT 0 CHECK (cached_tokens >= 0),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (session_id, model)
);

CREATE TABLE IF NOT EXISTS session_leases (
    session_id TEXT PRIMARY KEY,
    owner_token TEXT NOT NULL,
    expires_at REAL NOT NULL,
    acquired_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_session_leases_expiry ON session_leases(expires_at);

CREATE TABLE IF NOT EXISTS session_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_session_summaries_session ON session_summaries(session_id);
"""


def initialize_schema(connection: sqlite3.Connection) -> None:
    """Create the initial schema idempotently and set the SQLite user version."""
    current = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if current > SCHEMA_VERSION:
        raise RuntimeError(f"database schema {current} is newer than supported {SCHEMA_VERSION}")
    connection.executescript(SCHEMA_SQL)
    # Ensure user_id and role exist on pre-existing sessions tables
    cursor = connection.execute("PRAGMA table_info(sessions)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    if "user_id" not in existing_cols:
        connection.execute("ALTER TABLE sessions ADD COLUMN user_id INTEGER")
    if "role" not in existing_cols:
        connection.execute("ALTER TABLE sessions ADD COLUMN role TEXT")
    initialize_fts(connection)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
