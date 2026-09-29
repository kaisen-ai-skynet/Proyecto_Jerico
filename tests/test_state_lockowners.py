from pathlib import Path

from jerico.state import lockowners
from jerico.state.lockowners import scan_database_lockowners


def _fake_process(root: Path, pid: str, database_file: Path) -> None:
    process = root / pid
    fd = process / "fd"
    fd.mkdir(parents=True)
    (process / "cmdline").write_bytes(b"python\0worker.py\0")
    (process / "status").write_text("Name:\tpython\nUid:\t1000\t1000\t1000\t1000\n")
    (fd / "7").symlink_to(database_file)


def test_detecta_procesos_que_tienen_fd_del_db_wal_y_shm(tmp_path, monkeypatch):
    db = tmp_path / "state.db"
    wal = Path(f"{db}-wal")
    shm = Path(f"{db}-shm")
    proc = tmp_path / "proc"
    proc.mkdir()
    _fake_process(proc, "100", db)
    _fake_process(proc, "200", wal)
    _fake_process(proc, "300", shm)
    (proc / "self").mkdir()
    monkeypatch.setattr(lockowners, "PROC_ROOT", proc)

    holders = scan_database_lockowners(db)

    assert [holder.pid for holder in holders] == [100, 200, 300]
    assert all(holder.command == "python worker.py" for holder in holders)
    assert all(holder.username for holder in holders)
    assert all(holder.descriptor.endswith("/fd/7") for holder in holders)


def test_sin_proc_o_sin_fd_matches_devuelve_lista_vacia(tmp_path, monkeypatch):
    db = tmp_path / "state.db"
    proc = tmp_path / "proc"
    proc.mkdir()
    _fake_process(proc, "100", tmp_path / "other.db")
    (proc / "200").mkdir()
    monkeypatch.setattr(lockowners, "PROC_ROOT", proc)
    assert scan_database_lockowners(db) == []


def test_root_proc_inaccesible_se_degrada_a_lista_vacia(tmp_path, monkeypatch):
    monkeypatch.setattr(lockowners, "PROC_ROOT", tmp_path / "missing")
    assert scan_database_lockowners(tmp_path / "state.db") == []


def test_identidad_no_disponible_se_reporta_como_unknown(tmp_path, monkeypatch):
    db = tmp_path / "state.db"
    proc = tmp_path / "proc"
    process = proc / "4321"
    (process / "fd").mkdir(parents=True)
    (process / "fd" / "4").symlink_to(db)
    monkeypatch.setattr(lockowners, "PROC_ROOT", proc)
    holder = scan_database_lockowners(db)[0]
    assert holder.pid == 4321
    assert holder.username == "unknown"
    assert holder.command == "unknown"
