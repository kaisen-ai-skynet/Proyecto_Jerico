import hashlib
import json
import queue
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

from jerico.state.lockowners import scan_database_lockowners
from jerico.state.messages import MessageRecord, SessionRecord
from jerico.state.schema import initialize_schema

BUSY_TIMEOUT_MS = 60_000
DEFAULT_READ_POOL_SIZE = 4


class StateEngine:
    """Transactional SQLite WAL state with a serialized writer and read pool."""

    def __init__(
        self, db_path: Path | None = None, *, read_pool_size: int = DEFAULT_READ_POOL_SIZE
    ):
        if read_pool_size < 1:
            raise ValueError("read_pool_size debe ser al menos 1")
        self.db_path: Path | None = None
        self.read_pool_size = read_pool_size
        self._writer: sqlite3.Connection | None = None
        self._read_pool: queue.LifoQueue[sqlite3.Connection] = queue.LifoQueue()
        self._write_lock = threading.RLock()
        if db_path is not None:
            self.initialize_database(db_path)

    def initialize_database(self, db_path: Path) -> None:
        path = Path(db_path).expanduser().resolve()
        if self._writer is not None:
            if path == self.db_path:
                return
            raise RuntimeError("StateEngine ya está inicializado con otra ruta")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = path
        writer = self._connect()
        readers: list[sqlite3.Connection] = []
        try:
            mode = writer.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if str(mode).lower() != "wal":
                raise RuntimeError(f"SQLite no habilitó WAL: {mode}")
            initialize_schema(writer)
            for _ in range(self.read_pool_size):
                readers.append(self._connect())
        except Exception:
            for reader in readers:
                reader.close()
            writer.close()
            self.db_path = None
            raise
        self._writer = writer
        for reader in readers:
            self._read_pool.put(reader)

    def _connect(self) -> sqlite3.Connection:
        if self.db_path is None:
            raise RuntimeError("inicializa StateEngine antes de usarlo")
        connection = sqlite3.connect(
            str(self.db_path),
            timeout=BUSY_TIMEOUT_MS / 1000,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._require_writer()
        with self._write_lock:
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except Exception as exc:
                if connection.in_transaction:
                    connection.rollback()
                self._diagnose_operational_error(exc)
                raise

    @contextmanager
    def _reader(self) -> Iterator[sqlite3.Connection]:
        if self._writer is None:
            raise RuntimeError("inicializa StateEngine antes de usarlo")
        connection = self._read_pool.get()
        try:
            yield connection
        except sqlite3.OperationalError as exc:
            self._diagnose_operational_error(exc)
            raise
        finally:
            self._read_pool.put(connection)

    def _require_writer(self) -> sqlite3.Connection:
        if self._writer is None:
            raise RuntimeError("inicializa StateEngine antes de usarlo")
        return self._writer

    def _diagnose_operational_error(self, error: Exception) -> None:
        if not isinstance(error, sqlite3.OperationalError) or not any(
            signal in str(error).lower() for signal in ("locked", "busy")
        ):
            return
        if self.db_path is None:
            return
        holders = scan_database_lockowners(self.db_path)
        logger.error(
            "SQLite lock contention at {}: {}",
            self.db_path,
            [f"pid={h.pid} user={h.username} cmd={h.command}" for h in holders],
        )

    def get_or_create_session(
        self,
        session_id: str,
        system_prompt: str,
        model: str,
        parent_session_id: str | None = None,
    ) -> SessionRecord:
        now = _now()
        prompt_hash = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row is not None:
                if row["system_prompt_hash"] != prompt_hash:
                    raise ValueError("system prompt inmutable durante la sesión")
                connection.execute(
                    "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                    (now, session_id),
                )
            else:
                connection.execute(
                    "INSERT OR IGNORE INTO system_prompts(prompt_hash, content, created_at) "
                    "VALUES (?, ?, ?)",
                    (prompt_hash, system_prompt, now),
                )
                connection.execute(
                    "INSERT INTO sessions(session_id, system_prompt_hash, model, "
                    "parent_session_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (session_id, prompt_hash, model, parent_session_id, now, now),
                )
            result = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return _session_record(result)

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        tool_calls: list[dict[str, object]] | None = None,
        tool_call_id: str | None = None,
        reasoning: str | None = None,
    ) -> int:
        return self.append_messages(
            session_id,
            [
                {
                    "role": role,
                    "content": content,
                    "tool_calls": tool_calls,
                    "tool_call_id": tool_call_id,
                    "reasoning": reasoning,
                }
            ],
        )[0]

    def append_messages(self, session_id: str, messages: list[dict[str, object]]) -> list[int]:
        if not messages:
            return []
        with self._transaction() as connection:
            ids: list[int] = []
            for message in messages:
                role = message.get("role")
                content = message.get("content")
                tool_calls = message.get("tool_calls")
                if not isinstance(role, str) or not isinstance(content, str):
                    raise ValueError("cada mensaje requiere role y content string")
                if tool_calls is not None and not isinstance(tool_calls, list):
                    raise ValueError("tool_calls debe ser una lista")
                cursor = connection.execute(
                    "INSERT INTO messages(session_id, role, content, tool_calls_json, "
                    "tool_call_id, reasoning, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        session_id,
                        role,
                        content,
                        json.dumps(tool_calls, ensure_ascii=False)
                        if tool_calls is not None
                        else None,
                        message.get("tool_call_id"),
                        message.get("reasoning"),
                        _now(),
                    ),
                )
                if cursor.lastrowid is None:
                    raise RuntimeError("SQLite no devolvió id para el mensaje insertado")
                ids.append(int(cursor.lastrowid))
            connection.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (_now(), session_id),
            )
            return ids

    def get_session_transcript(
        self, session_id: str, limit: int | None = None
    ) -> list[MessageRecord]:
        if limit is not None and limit < 0:
            raise ValueError("limit no puede ser negativo")
        sql = (
            "SELECT id, session_id, role, content, tool_calls_json, tool_call_id, "
            "reasoning, created_at FROM messages WHERE session_id = ? ORDER BY id"
        )
        parameters: tuple[object, ...] = (session_id,)
        if limit is not None:
            sql += " LIMIT ?"
            parameters += (limit,)
        with self._reader() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [_message_record(row) for row in rows]

    def record_usage(
        self,
        session_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cached_tokens: int = 0,
    ) -> None:
        counts = (prompt_tokens, completion_tokens, cached_tokens)
        if any(count < 0 for count in counts):
            raise ValueError("los contadores de tokens no pueden ser negativos")
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO session_model_usage(session_id, model, prompt_tokens, "
                "completion_tokens, cached_tokens, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(session_id, model) DO UPDATE SET "
                "prompt_tokens = prompt_tokens + excluded.prompt_tokens, "
                "completion_tokens = completion_tokens + excluded.completion_tokens, "
                "cached_tokens = cached_tokens + excluded.cached_tokens, "
                "updated_at = excluded.updated_at",
                (session_id, model, *counts, _now()),
            )

    def get_usage(self, session_id: str, model: str) -> dict[str, int] | None:
        with self._reader() as connection:
            row = connection.execute(
                "SELECT prompt_tokens, completion_tokens, cached_tokens "
                "FROM session_model_usage WHERE session_id = ? AND model = ?",
                (session_id, model),
            ).fetchone()
        if row is None:
            return None
        return {
            "prompt_tokens": int(row["prompt_tokens"]),
            "completion_tokens": int(row["completion_tokens"]),
            "cached_tokens": int(row["cached_tokens"]),
        }

    def try_acquire_session_lease(
        self, session_id: str, owner_token: str, lease_seconds: float
    ) -> bool:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds debe ser positivo")
        now = time.time()
        with self._transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO session_leases(session_id, owner_token, expires_at, acquired_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET "
                "owner_token = excluded.owner_token, expires_at = excluded.expires_at, "
                "acquired_at = excluded.acquired_at WHERE session_leases.expires_at <= ?",
                (session_id, owner_token, now + lease_seconds, now, now),
            )
            return cursor.rowcount == 1

    def release_session_lease(self, session_id: str, owner_token: str) -> bool:
        with self._transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM session_leases WHERE session_id = ? AND owner_token = ?",
                (session_id, owner_token),
            )
            return cursor.rowcount == 1

    def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None
        while True:
            try:
                self._read_pool.get_nowait().close()
            except queue.Empty:
                break

    def __enter__(self) -> "StateEngine":
        if self._writer is None:
            raise RuntimeError("StateEngine no está inicializado")
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _session_record(row: sqlite3.Row) -> SessionRecord:
    return SessionRecord(
        session_id=row["session_id"],
        system_prompt_hash=row["system_prompt_hash"],
        model=row["model"],
        parent_session_id=row["parent_session_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _message_record(row: sqlite3.Row) -> MessageRecord:
    raw_tool_calls = row["tool_calls_json"]
    return MessageRecord(
        id=int(row["id"]),
        session_id=row["session_id"],
        role=row["role"],
        content=row["content"],
        tool_calls=json.loads(raw_tool_calls) if raw_tool_calls is not None else None,
        tool_call_id=row["tool_call_id"],
        reasoning=row["reasoning"],
        created_at=row["created_at"],
    )
