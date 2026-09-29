import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from jerico.state import StateEngine
from jerico.state.db import BUSY_TIMEOUT_MS


def test_inicializa_wal_pragmas_esquema_y_pool(tmp_path):
    path = tmp_path / "nested" / "jerico_state.db"
    engine = StateEngine(path, read_pool_size=3)
    try:
        assert path.exists()
        assert engine._writer is not None
        assert engine._writer.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert engine._writer.execute("PRAGMA synchronous").fetchone()[0] == 1
        assert engine._writer.execute("PRAGMA busy_timeout").fetchone()[0] == BUSY_TIMEOUT_MS
        assert engine._writer.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert engine._writer.execute("PRAGMA user_version").fetchone()[0] == 1
        assert engine._read_pool.qsize() == 3
        engine.initialize_database(path)
    finally:
        engine.close()


def test_transcript_usa_pool_de_lectura_concurrente(tmp_path):
    engine = StateEngine(tmp_path / "state.db", read_pool_size=4)
    try:
        engine.get_or_create_session("s", "system", "model")
        engine.append_message("s", "user", "hola")
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: engine.get_session_transcript("s"), range(50)))
        assert all(len(messages) == 1 for messages in results)
        assert engine._read_pool.qsize() == 4
    finally:
        engine.close()


def test_ciclo_de_vida_y_guardas(tmp_path):
    with pytest.raises(ValueError, match="read_pool_size"):
        StateEngine(read_pool_size=0)

    engine = StateEngine()
    with pytest.raises(RuntimeError, match="inicializa"):
        engine.get_or_create_session("s", "system", "model")
    engine.initialize_database(tmp_path / "one.db")
    with pytest.raises(RuntimeError, match="otra ruta"):
        engine.initialize_database(tmp_path / "two.db")
    engine.close()
    with pytest.raises(RuntimeError, match="inicializa"):
        engine.get_session_transcript("s")


def test_esquema_idempotente_a_nivel_de_archivo(tmp_path):
    path = Path(tmp_path / "state.db")
    first = StateEngine(path)
    first.close()
    second = StateEngine(path)
    try:
        with sqlite3.connect(path) as connection:
            names = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        assert {"system_prompts", "sessions", "messages", "session_model_usage"} <= names
    finally:
        second.close()


def test_no_migra_una_db_con_version_futura(tmp_path):
    path = tmp_path / "future.db"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=999")
    with pytest.raises(RuntimeError, match="newer than supported"):
        StateEngine(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 999
        tables = connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
    assert tables == 0


def test_operational_error_locked_activa_diagnostico(tmp_path, monkeypatch):
    import sqlite3

    import jerico.state.db as db_module

    engine = StateEngine(tmp_path / "state.db")
    scanned = []
    monkeypatch.setattr(
        db_module,
        "scan_database_lockowners",
        lambda path: scanned.append(path) or [],
    )
    try:
        engine._diagnose_operational_error(sqlite3.OperationalError("database is locked"))
        engine._diagnose_operational_error(sqlite3.OperationalError("syntax error"))
        assert scanned == [engine.db_path]
    finally:
        engine.close()
