"""Scripts de operación de kaisen-server (spec 003, SRV-01..SRV-15).

Corren los scripts reales de `scripts/servidor/` con `docker`, `age` y `curl` falsos
en el PATH: ningún test toca Docker, la red ni secretos reales.
"""
# ruff: noqa: S603, S607  # los tests lanzan a propósito los scripts del repo y binarios del PATH

import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts" / "servidor"
CRM_VOLUME = SCRIPTS / "crm_volume.py"
AGE_HEADER = b"age-encryption.org/v1\n"
TOKEN = "123456:TOKEN-DE-PRUEBA-NO-REAL"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="requiere bash")

FAKE_DOCKER = r"""#!/usr/bin/env python3
import os, subprocess, sys
state = os.environ["FAKE_STATE_DIR"]
volume = os.path.join(state, "volume")
args = sys.argv[1:]
with open(os.path.join(state, "docker_calls.log"), "a") as log:
    log.write(" ".join(args) + "\n")
status_file = os.path.join(state, "status")

def status():
    return open(status_file).read().strip() if os.path.exists(status_file) else None

def run_python(py_args, mount):
    mapped = [volume if a == mount else a for a in py_args]
    sys.exit(subprocess.run([sys.executable, *mapped]).returncode)

cmd = args[0]
if cmd == "info":
    sys.exit(int(os.environ.get("FAKE_INFO_EXIT", "0")))
if cmd == "inspect":
    if status() is None:
        print("Error: No such object: jerico-crm", file=sys.stderr); sys.exit(1)
    fmt = args[args.index("-f") + 1]
    print(os.environ.get("FAKE_IMAGE", "jerico-crm:0.2.0") if "Config.Image" in fmt else status())
elif cmd == "exec":
    if not (status() or "").startswith("running"):
        print("Error: container is not running", file=sys.stderr); sys.exit(1)
    i = args.index("python")
    run_python(args[i + 1:], "/app/crm-data")
elif cmd == "run":
    if set(args) & set(os.environ.get("FAKE_RUN_FAIL", "").split(",")):
        print("docker falso: fallo forzado", file=sys.stderr); sys.exit(1)
    spec = args[args.index("-v") + 1]
    i = args.index("python")
    run_python(args[i + 1:], spec.split(":", 1)[1])
elif cmd == "stop":
    open(status_file, "w").write("exited none")
elif cmd == "start":
    open(status_file, "w").write(os.environ.get("FAKE_START_STATUS", "running healthy"))
else:
    print(f"docker falso: comando no soportado {args}", file=sys.stderr); sys.exit(3)
"""

FAKE_AGE = r"""#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
HEADER = b"age-encryption.org/v1\n"
out = args[args.index("-o") + 1]
rest = [a for i, a in enumerate(args) if a not in ("-d", "-R", "-i", "-o")
        and (i == 0 or args[i - 1] not in ("-R", "-i", "-o"))]
data = open(rest[0], "rb").read() if rest else sys.stdin.buffer.read()
if "-d" in args:
    if not os.path.exists(args[args.index("-i") + 1]) or not data.startswith(HEADER):
        print("age: no identity matched", file=sys.stderr); sys.exit(1)
    open(out, "wb").write(data[len(HEADER):])
else:
    recipients = args[args.index("-R") + 1]
    if not os.path.exists(recipients):
        sys.exit(1)
    open(out, "wb").write(HEADER + data)
"""

FAKE_CURL = r"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
stdin = sys.stdin.read() if "-K" in args else ""
channel = "telegram" if "api.telegram.org" in stdin else "smtp"
upload = {}
for flag, value in zip(args, args[1:]):
    if flag == "--upload-file":
        upload[flag] = open(value).read()
    elif flag == "--data-urlencode" and "@" in value:
        upload[flag] = open(value.split("@", 1)[1]).read()
with open(os.environ["FAKE_CURL_LOG"], "a") as log:
    record = {"argv": args, "stdin": stdin, "channel": channel, "files": upload}
    log.write(json.dumps(record) + "\n")
if channel in os.environ.get("FAKE_CURL_FAIL", "").split(","):
    sys.exit(22)
if channel == "telegram":
    print('{"ok":true,"result":{}}')
"""

FAKE_NOTIFY = """#!/usr/bin/env bash
printf '%s\\n---\\n' "$*" >> "$FAKE_NOTIFY_LOG"
exit "${FAKE_NOTIFY_EXIT:-0}"
"""


def _write_exec(path: Path, content: str) -> Path:
    path.write_text(content)
    path.chmod(0o755)
    return path


def make_db(directory: Path) -> sqlite3.Connection:
    """SQLite en WAL con el esquema mínimo; deja la conexión abierta (WAL sin volcar)."""
    directory.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(directory / "crm.db")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE crm_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO crm_meta VALUES ('schema_version', '2')")
    conn.execute("CREATE TABLE crm_leads (id INTEGER PRIMARY KEY, name TEXT)")
    conn.executemany("INSERT INTO crm_leads (name) VALUES (?)", [("Ana",), ("Luis",)])
    conn.commit()
    return conn


class Env:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.home = tmp / "home"
        self.home.mkdir()
        self.state = tmp / "docker"
        self.volume = self.state / "volume"
        self.volume.mkdir(parents=True)
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        _write_exec(bin_dir / "docker", FAKE_DOCKER)
        _write_exec(bin_dir / "age", FAKE_AGE)
        _write_exec(bin_dir / "curl", FAKE_CURL)
        self.notify = _write_exec(tmp / "notify_fake.sh", FAKE_NOTIFY)
        self.notify_log = tmp / "notify.log"
        self.curl_log = tmp / "curl.log"
        self.backup_dir = tmp / "backups"
        self.recipients = tmp / "recipients.txt"
        self.recipients.write_text("age1" + "qyqszqgp" * 7 + "qyqs3290gq\n")
        self.identity = tmp / "identity.agekey"
        self.identity.write_text("# llave de prueba\n")
        self.env_file = tmp / "jerico.env"
        self.env_file.write_text(
            f"JERICO_CRM_TELEGRAM_BOT_TOKEN={TOKEN}\nJERICO_CRM_SEED_CTO_TELEGRAM_ID=4242\n"
        )
        self.vars = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(self.home),
            "TMPDIR": str(tmp),
            "LANG": "C.UTF-8",
            "FAKE_STATE_DIR": str(self.state),
            "FAKE_CURL_LOG": str(self.curl_log),
            "FAKE_NOTIFY_LOG": str(self.notify_log),
            "BACKUP_CONFIG": "/dev/null",
            "BACKUP_DIR": str(self.backup_dir),
            "AGE_RECIPIENTS_FILE": str(self.recipients),
            "ENV_FILE": str(self.env_file),
            "NOTIFY": str(self.notify),
            "STATE_FILE": str(tmp / "health.state"),
        }

    def set_status(self, status: str | None) -> None:
        path = self.state / "status"
        if status is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(status)

    def run(self, script: str, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SCRIPTS / script), *args],
            env={**self.vars, **extra},
            capture_output=True,
            text=True,
            timeout=60,
        )

    def notices(self) -> list[str]:
        if not self.notify_log.exists():
            return []
        return [n.strip() for n in self.notify_log.read_text().split("---\n") if n.strip()]

    def curl_calls(self) -> list[dict[str, object]]:
        if not self.curl_log.exists():
            return []
        return [json.loads(line) for line in self.curl_log.read_text().splitlines()]

    def docker_calls(self) -> list[str]:
        log = self.state / "docker_calls.log"
        return log.read_text().splitlines() if log.exists() else []


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


@pytest.fixture
def live_db(env: Env) -> Iterator[sqlite3.Connection]:
    conn = make_db(env.volume)
    (env.volume / "heartbeat").touch()
    (env.volume / "attachments").mkdir()
    (env.volume / "attachments" / "cotizacion.pdf").write_bytes(b"%PDF-1.4 prueba")
    env.set_status("running healthy")
    yield conn
    conn.close()


def _members(tar_path: Path) -> set[str]:
    with tarfile.open(tar_path) as tar:
        return {m.name.removeprefix("./") for m in tar.getmembers()}


def _pack(volume: Path, dest: Path, **env: str) -> subprocess.CompletedProcess[bytes]:
    with dest.open("wb") as out:
        return subprocess.run(
            [sys.executable, str(CRM_VOLUME), "pack", str(volume)],
            stdout=out,
            stderr=subprocess.PIPE,
            env={**os.environ, **env},
            timeout=60,
        )


# ---------------------------------------------------------------- crm_volume.py (T01)


def test_pack_consistent_snapshot_with_wal_and_attachments(
    env: Env, live_db: sqlite3.Connection, tmp_path: Path
) -> None:
    assert (env.volume / "crm.db-wal").stat().st_size > 0  # los datos siguen en el WAL
    dest = tmp_path / "out.tar"
    result = _pack(env.volume, dest)
    assert result.returncode == 0, result.stderr
    names = _members(dest)
    assert "crm.db" in names
    assert "attachments/cotizacion.pdf" in names
    assert not names & {"heartbeat", "crm.db-wal", "crm.db-shm"}
    with tarfile.open(dest) as tar:
        tar.extract("crm.db", tmp_path / "x", filter="data")
    snap = sqlite3.connect(tmp_path / "x" / "crm.db")
    assert snap.execute("SELECT count(*) FROM crm_leads").fetchone() == (2,)
    snap.close()


def test_pack_cleans_its_temp_dir(env: Env, live_db: sqlite3.Connection, tmp_path: Path) -> None:
    work = tmp_path / "ctmp"
    work.mkdir()
    assert _pack(env.volume, tmp_path / "out.tar", TMPDIR=str(work)).returncode == 0
    assert list(work.iterdir()) == []


def test_pack_fails_without_database(env: Env, tmp_path: Path) -> None:
    result = _pack(env.volume, tmp_path / "out.tar")
    assert result.returncode != 0
    assert b"crm.db" in result.stderr


def test_unpack_restores_and_rejects_path_traversal(
    env: Env, live_db: sqlite3.Connection, tmp_path: Path
) -> None:
    archive = tmp_path / "ok.tar"
    _pack(env.volume, archive)
    target = tmp_path / "restored"
    target.mkdir()
    (target / "viejo.txt").write_text("se borra")
    with archive.open("rb") as src:
        ok = subprocess.run(
            [sys.executable, str(CRM_VOLUME), "unpack", str(target)], stdin=src, timeout=60
        )
    assert ok.returncode == 0
    assert (target / "crm.db").exists() and (target / "attachments" / "cotizacion.pdf").exists()
    assert not (target / "viejo.txt").exists()

    evil = tmp_path / "evil.tar"
    payload = tmp_path / "payload"
    payload.write_text("x")
    with tarfile.open(evil, "w") as tar:
        tar.add(payload, arcname="../escape.txt")
    with evil.open("rb") as src:
        bad = subprocess.run(
            [sys.executable, str(CRM_VOLUME), "unpack", str(target)],
            stdin=src,
            capture_output=True,
            timeout=60,
        )
    assert bad.returncode != 0
    assert not (tmp_path / "escape.txt").exists()


def test_verify_reports_and_detects_missing_tables(
    env: Env, live_db: sqlite3.Connection, tmp_path: Path
) -> None:
    archive = tmp_path / "ok.tar"
    _pack(env.volume, archive)
    ok = subprocess.run(
        [sys.executable, str(CRM_VOLUME), "verify", str(archive)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert ok.returncode == 0, ok.stderr
    assert "integrity_check: ok" in ok.stdout
    assert "crm_leads: 2" in ok.stdout
    assert "schema_version: 2" in ok.stdout

    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    sqlite3.connect(bad_dir / "crm.db").execute("CREATE TABLE otra (x)").connection.close()
    bad = tmp_path / "bad.tar"
    with tarfile.open(bad, "w") as tar:
        tar.add(bad_dir / "crm.db", arcname="crm.db")
    result = subprocess.run(
        [sys.executable, str(CRM_VOLUME), "verify", str(bad)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert "crm_meta" in result.stderr


# ---------------------------------------------------------------- notify_cto.sh (T02)


def test_notify_telegram_keeps_token_out_of_argv(env: Env) -> None:
    result = env.run("notify_cto.sh", "jerico-crm: unhealthy")
    assert result.returncode == 0, result.stderr
    (call,) = env.curl_calls()
    assert call["channel"] == "telegram"
    assert TOKEN not in " ".join(call["argv"])  # type: ignore[arg-type]
    assert TOKEN in call["stdin"]  # type: ignore[operator]
    assert "chat_id=4242" in call["argv"]  # type: ignore[operator]
    assert "jerico-crm: unhealthy" in call["files"]["--data-urlencode"]  # type: ignore[index]
    assert TOKEN not in result.stdout + result.stderr


def test_notify_falls_back_to_smtp(env: Env) -> None:
    env.env_file.write_text(
        env.env_file.read_text()
        + "JERICO_CRM_SEED_CTO_EMAIL=cto@example.com\nJERICO_CRM_SMTP_HOST=smtp.example.com\n"
        "JERICO_CRM_SMTP_PORT=465\nJERICO_CRM_SMTP_SECURITY=ssl\n"
        "JERICO_CRM_SMTP_USERNAME=bot@example.com\nJERICO_CRM_SMTP_PASSWORD='clave secreta'\n"
        "JERICO_CRM_SMTP_FROM=bot@example.com\n"
    )
    result = env.run("notify_cto.sh", "fallo X", FAKE_CURL_FAIL="telegram")
    assert result.returncode == 0, result.stderr
    telegram, smtp = env.curl_calls()
    assert smtp["channel"] == "smtp"
    argv = " ".join(smtp["argv"])  # type: ignore[arg-type]
    assert "smtps://smtp.example.com:465" in argv
    assert "clave secreta" not in argv and "clave secreta" in smtp["stdin"]  # type: ignore[operator]
    body = smtp["files"]["--upload-file"]  # type: ignore[index]
    assert "To: cto@example.com" in body and "fallo X" in body


def test_notify_env_inline_comment_and_quotes(env: Env) -> None:
    env.env_file.write_text(
        f'JERICO_CRM_TELEGRAM_BOT_TOKEN="{TOKEN}"  # bot de ventas\n'
        "JERICO_CRM_SEED_CTO_TELEGRAM_ID=4242 # CTO\n"
    )
    assert env.run("notify_cto.sh", "x").returncode == 0
    (call,) = env.curl_calls()
    assert f"bot{TOKEN}/sendMessage" in call["stdin"]  # type: ignore[operator]
    assert "chat_id=4242" in call["argv"]  # type: ignore[operator]


def test_notify_fails_when_every_channel_fails(env: Env) -> None:
    result = env.run("notify_cto.sh", "x", FAKE_CURL_FAIL="telegram,smtp")
    assert result.returncode != 0


def test_notify_never_executes_env_file(env: Env, tmp_path: Path) -> None:
    pwned = tmp_path / "pwned"
    env.env_file.write_text(
        f"JERICO_CRM_TELEGRAM_BOT_TOKEN={TOKEN}\nJERICO_CRM_SEED_CTO_TELEGRAM_ID=4242\n"
        f"JERICO_CRM_SMTP_HOST=$(touch {pwned})\n"
    )
    env.run("notify_cto.sh", "x")
    assert not pwned.exists()


def test_notify_requires_env_file(env: Env) -> None:
    result = env.run("notify_cto.sh", "x", ENV_FILE=str(env.tmp / "no-existe.env"))
    assert result.returncode != 0
    assert env.curl_calls() == []


# ---------------------------------------------------------------- backup_crm.sh (T03)


def _backups(env: Env) -> list[Path]:
    return sorted(env.backup_dir.glob("crm-*.tar.age"))


def test_backup_creates_encrypted_archive(env: Env, live_db: sqlite3.Connection) -> None:
    result = env.run("backup_crm.sh")
    assert result.returncode == 0, result.stderr + result.stdout
    (archive,) = _backups(env)
    assert archive.read_bytes().startswith(AGE_HEADER)
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    assert stat.S_IMODE(env.backup_dir.stat().st_mode) == 0o700
    leftovers = [p.name for p in env.backup_dir.iterdir() if not p.name.endswith(".tar.age")]
    assert set(leftovers) <= {".lock"}
    plain = env.tmp / "plain.tar"
    plain.write_bytes(archive.read_bytes()[len(AGE_HEADER) :])
    assert "crm.db" in _members(plain)
    assert env.notices() == []


@pytest.mark.parametrize(
    "content", ["", "AGE-SECRET-KEY-1QQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQ\n"]
)
def test_backup_rejects_bad_recipients(env: Env, live_db: sqlite3.Connection, content: str) -> None:
    env.recipients.write_text(content)
    result = env.run("backup_crm.sh")
    assert result.returncode != 0
    assert _backups(env) == []


def test_backup_fails_and_notifies_when_container_down(env: Env) -> None:
    make_db(env.volume).close()
    env.set_status("exited none")
    result = env.run("backup_crm.sh")
    assert result.returncode != 0
    assert _backups(env) == []
    assert any("backup" in n.lower() for n in env.notices())


def test_backup_of_stopped_container_when_allowed(env: Env) -> None:
    make_db(env.volume).close()
    env.set_status("exited none")
    result = env.run("backup_crm.sh", ALLOW_STOPPED="1")
    assert result.returncode == 0, result.stderr
    (archive,) = _backups(env)
    assert archive.read_bytes().startswith(AGE_HEADER)
    assert any(c.startswith("run --rm -v jerico_crm_data:/data") for c in env.docker_calls())
    assert env.notices() == []


def test_backup_error_survives_failed_notice(env: Env) -> None:
    env.set_status(None)
    result = env.run("backup_crm.sh", FAKE_NOTIFY_EXIT="1")
    assert result.returncode != 0


def _stamp(days_ago: float) -> str:
    when = datetime.now(UTC) - timedelta(days=days_ago)
    return when.strftime("crm-%Y%m%dT%H%M%SZ.tar.age")


@pytest.mark.parametrize(("retention", "old_age", "deleted"), [("14", 20, True), ("60", 40, True)])
def test_backup_retention(
    env: Env, live_db: sqlite3.Connection, retention: str, old_age: int, deleted: bool
) -> None:
    env.backup_dir.mkdir(mode=0o700)
    old = env.backup_dir / _stamp(old_age)
    recent = env.backup_dir / _stamp(2)
    foreign = env.backup_dir / "notas.txt"
    for path in (old, recent, foreign):
        path.write_bytes(AGE_HEADER)
    result = env.run("backup_crm.sh", RETENTION_DAYS=retention)
    assert result.returncode == 0, result.stderr
    assert old.exists() is not deleted
    assert recent.exists() and foreign.exists()
    assert len(_backups(env)) == 2


def test_backup_retention_includes_pre_restore(env: Env, live_db: sqlite3.Connection) -> None:
    env.backup_dir.mkdir(mode=0o700)
    old = env.backup_dir / _stamp(20).replace("crm-", "pre-restore-")
    recent = env.backup_dir / _stamp(1).replace("crm-", "pre-restore-")
    for path in (old, recent):
        path.write_bytes(AGE_HEADER)
    assert env.run("backup_crm.sh").returncode == 0
    assert not old.exists() and recent.exists()


def test_backup_unexpected_error_notifies(env: Env, live_db: sqlite3.Connection) -> None:
    env.backup_dir.mkdir(mode=0o700)
    (env.backup_dir / ".lock").mkdir()  # no se puede abrir el lock: error inesperado
    result = env.run("backup_crm.sh")
    assert result.returncode != 0
    assert any("backup" in n.lower() for n in env.notices())


def test_backup_single_instance(env: Env, live_db: sqlite3.Connection) -> None:
    env.backup_dir.mkdir(mode=0o700)
    lock = env.backup_dir / ".lock"
    holder = subprocess.Popen(["flock", str(lock), "sleep", "30"])
    try:
        time.sleep(0.3)
        result = env.run("backup_crm.sh")
    finally:
        holder.kill()
        holder.wait()
    assert result.returncode != 0
    assert "en curso" in result.stderr
    assert _backups(env) == []


# ---------------------------------------------------------------- restore_crm.sh (T04)


def _make_backup(env: Env) -> Path:
    assert env.run("backup_crm.sh").returncode == 0
    return _backups(env)[-1]


def test_restore_verify(env: Env, live_db: sqlite3.Connection) -> None:
    archive = _make_backup(env)
    result = env.run("restore_crm.sh", "verify", str(archive), str(env.identity))
    assert result.returncode == 0, result.stderr
    assert "RESTAURACIÓN VERIFICADA" in result.stdout
    assert list(env.tmp.glob("jerico-restore-*")) == []


def test_restore_verify_fails_on_garbage(env: Env) -> None:
    bad = env.tmp / "crm-20261013T000000Z.tar.age"
    bad.write_bytes(AGE_HEADER + b"no es un tar")
    result = env.run("restore_crm.sh", "verify", str(bad), str(env.identity))
    assert result.returncode != 0


def test_restore_apply_requires_confirm(env: Env, live_db: sqlite3.Connection) -> None:
    archive = _make_backup(env)
    before = len(env.docker_calls())
    result = env.run("restore_crm.sh", "apply", str(archive), str(env.identity))
    assert result.returncode == 0
    assert "CONFIRM=1" in result.stdout
    assert not any(c.startswith(("stop", "run", "start")) for c in env.docker_calls()[before:])


def test_restore_apply_replaces_volume(env: Env, live_db: sqlite3.Connection) -> None:
    archive = _make_backup(env)
    live_db.execute("INSERT INTO crm_leads (name) VALUES ('posterior al backup')")
    live_db.commit()
    live_db.close()
    result = env.run("restore_crm.sh", "apply", str(archive), str(env.identity), CONFIRM="1")
    assert result.returncode == 0, result.stderr + result.stdout
    calls = env.docker_calls()
    assert any(c.startswith("stop jerico-crm") for c in calls)
    assert calls[-1].startswith("inspect")
    assert any(c.startswith("start jerico-crm") for c in calls)
    restored = sqlite3.connect(env.volume / "crm.db")
    assert restored.execute("SELECT count(*) FROM crm_leads").fetchone() == (2,)
    restored.close()
    (pre,) = env.backup_dir.glob("pre-restore-*.tar.age")
    assert pre.read_bytes().startswith(AGE_HEADER)


def test_restore_apply_pre_restore_keeps_corrupt_db(env: Env, live_db: sqlite3.Connection) -> None:
    archive = _make_backup(env)
    live_db.close()
    (env.volume / "crm.db").write_bytes(b"base corrupta")  # el motivo típico de restaurar
    result = env.run("restore_crm.sh", "apply", str(archive), str(env.identity), CONFIRM="1")
    assert result.returncode == 0, result.stderr + result.stdout
    (pre,) = env.backup_dir.glob("pre-restore-*.tar.age")
    plain = env.tmp / "pre.tar"
    plain.write_bytes(pre.read_bytes()[len(AGE_HEADER) :])
    with tarfile.open(plain) as tar:
        assert tar.extractfile("./crm.db").read() == b"base corrupta"  # type: ignore[union-attr]


def test_restore_apply_aborts_if_pre_restore_fails(env: Env, live_db: sqlite3.Connection) -> None:
    archive = _make_backup(env)
    live_db.execute("INSERT INTO crm_leads (name) VALUES ('no se pierde')")
    live_db.commit()
    result = env.run(
        "restore_crm.sh",
        "apply",
        str(archive),
        str(env.identity),
        CONFIRM="1",
        FAKE_RUN_FAIL="pack-raw",
    )
    assert result.returncode != 0
    assert env.docker_calls()[-1].startswith("start jerico-crm")  # vuelve a arrancar
    count = live_db.execute("SELECT count(*) FROM crm_leads").fetchone()
    assert count == (3,)  # el volumen no se tocó
    assert list(env.backup_dir.glob("pre-restore-*")) == []


def test_restore_apply_reports_failed_unpack(env: Env, live_db: sqlite3.Connection) -> None:
    archive = _make_backup(env)
    result = env.run(
        "restore_crm.sh",
        "apply",
        str(archive),
        str(env.identity),
        CONFIRM="1",
        FAKE_RUN_FAIL="unpack",
    )
    assert result.returncode != 0
    assert "pre-restore-" in result.stderr  # dice dónde está la copia previa
    assert not any(c.startswith("start") for c in env.docker_calls())


def test_restore_apply_health_timeout(env: Env, live_db: sqlite3.Connection) -> None:
    archive = _make_backup(env)
    result = env.run(
        "restore_crm.sh",
        "apply",
        str(archive),
        str(env.identity),
        CONFIRM="1",
        FAKE_START_STATUS="running unhealthy",
        HEALTH_WAIT_S="0",
    )
    assert result.returncode != 0
    assert "healthy" in result.stderr


@pytest.mark.skipif(shutil.which("age") is None, reason="age real no instalado")
def test_round_trip_with_real_age(env: Env, live_db: sqlite3.Connection) -> None:
    real_bin = env.tmp / "realbin"
    real_bin.mkdir()
    (real_bin / "age").symlink_to(shutil.which("age"))  # type: ignore[arg-type]
    identity = env.tmp / "real.agekey"
    subprocess.run(["age-keygen", "-o", str(identity)], check=True, capture_output=True)
    pub = subprocess.run(
        ["age-keygen", "-y", str(identity)], check=True, capture_output=True, text=True
    )
    env.recipients.write_text(pub.stdout)
    path = f"{real_bin}{os.pathsep}{env.vars['PATH']}"
    assert env.run("backup_crm.sh", PATH=path).returncode == 0
    archive = _backups(env)[-1]
    result = env.run("restore_crm.sh", "verify", str(archive), str(identity), PATH=path)
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------- healthwatch_crm.sh (T05)

T0 = 1_800_000_000


def _watch(env: Env, minutes: float, status: str | None) -> subprocess.CompletedProcess[str]:
    env.set_status(status)
    return env.run("healthwatch_crm.sh", NOW_EPOCH=str(int(T0 + minutes * 60)))


def test_watch_healthy_is_silent(env: Env) -> None:
    assert _watch(env, 0, "running healthy").returncode == 0
    assert env.notices() == []


def test_watch_alerts_once_then_reminds(env: Env) -> None:
    _watch(env, 0, "running healthy")
    _watch(env, 5, "running unhealthy")
    assert len(env.notices()) == 1
    assert "unhealthy" in env.notices()[0]
    _watch(env, 10, "running unhealthy")
    assert len(env.notices()) == 1
    _watch(env, 66, "running unhealthy")
    assert len(env.notices()) == 2


def test_watch_recovery_notice_with_duration(env: Env) -> None:
    _watch(env, 0, "running healthy")
    _watch(env, 5, "exited none")
    _watch(env, 35, "running healthy")
    notices = env.notices()
    assert len(notices) == 2
    assert "recuperado" in notices[1].lower() and "30 min" in notices[1]


def test_watch_starting_grace(env: Env) -> None:
    _watch(env, 0, "running starting")
    _watch(env, 5, "running starting")
    assert env.notices() == []
    _watch(env, 12, "running starting")
    assert len(env.notices()) == 1


def test_watch_missing_container(env: Env) -> None:
    result = _watch(env, 0, None)
    assert result.returncode == 0
    assert "no existe" in env.notices()[0]


def test_watch_keeps_alert_state_when_notice_fails(env: Env) -> None:
    _watch(env, 0, "running healthy")
    env.set_status("running unhealthy")
    failed = env.run("healthwatch_crm.sh", NOW_EPOCH=str(T0 + 300), FAKE_NOTIFY_EXIT="1")
    assert failed.returncode != 0
    _watch(env, 10, "running unhealthy")  # reintenta en la siguiente pasada
    assert len(env.notices()) == 2


# ---------------------------------------------------------------- offsite_oci.sh (copia fuera)

FAKE_OCI = r"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
store = os.environ["FAKE_OCI_STORE"]
os.makedirs(store, exist_ok=True)
with open(os.path.join(os.path.dirname(store), "oci_calls.log"), "a") as log:
    log.write(" ".join(args) + "\n")
if os.environ.get("FAKE_OCI_FAIL"):
    print("ServiceError: fallo forzado", file=sys.stderr); sys.exit(1)
def opt(name):
    return args[args.index(name) + 1]
if args[:3] == ["os", "object", "list"]:
    prefix = opt("--prefix") if "--prefix" in args else ""
    names = sorted("crm/" + n for n in os.listdir(store))
    print(json.dumps([n for n in names if n.startswith(prefix)]))
elif args[:3] == ["os", "object", "put"]:
    data = open(opt("--file"), "rb").read()
    open(os.path.join(store, opt("--name").split("/", 1)[1]), "wb").write(data)
elif args[:3] == ["os", "object", "delete"]:
    os.remove(os.path.join(store, opt("--name").split("/", 1)[1]))
else:
    print(f"oci falso: no soportado {args}", file=sys.stderr); sys.exit(3)
"""


@pytest.fixture
def oci_env(env: Env) -> Env:
    _write_exec(env.tmp / "bin" / "oci", FAKE_OCI)
    env.vars["FAKE_OCI_STORE"] = str(env.tmp / "oci" / "store")
    env.vars["OCI_BUCKET"] = "jerico-backups"
    env.backup_dir.mkdir(mode=0o700)
    return env


def _remote(env: Env) -> set[str]:
    store = Path(env.vars["FAKE_OCI_STORE"])
    return set(os.listdir(store)) if store.exists() else set()


def test_offsite_uploads_missing_encrypted_backups(oci_env: Env) -> None:
    env = oci_env
    a, b = env.backup_dir / _stamp(2), env.backup_dir / _stamp(1)
    for p in (a, b):
        p.write_bytes(AGE_HEADER + b"x")
    (env.backup_dir / "crm-20260101T000000Z.tar.age.partial").write_bytes(b"plano")
    assert env.run("offsite_oci.sh").returncode == 0
    assert _remote(env) == {a.name, b.name}
    calls = (env.tmp / "oci" / "oci_calls.log").read_text()
    assert calls.count("object put") == 2
    assert env.run("offsite_oci.sh").returncode == 0  # idempotente
    assert (env.tmp / "oci" / "oci_calls.log").read_text().count("object put") == 2


def test_offsite_refuses_unencrypted_file(oci_env: Env) -> None:
    env = oci_env
    (env.backup_dir / _stamp(1)).write_bytes(b"SQLite format 3 en claro")
    result = env.run("offsite_oci.sh")
    assert result.returncode != 0
    assert _remote(env) == set()
    assert env.notices()


def test_offsite_prunes_remote_beyond_retention(oci_env: Env) -> None:
    env = oci_env
    store = Path(env.vars["FAKE_OCI_STORE"])
    store.mkdir(parents=True)
    old, keep = _stamp(40), _stamp(5)
    (store / old).write_bytes(AGE_HEADER)
    (store / keep).write_bytes(AGE_HEADER)
    (store / "otro.txt").write_bytes(b"")
    (env.backup_dir / keep).write_bytes(AGE_HEADER)
    assert env.run("offsite_oci.sh", REMOTE_RETENTION_DAYS="60").returncode == 0  # tope 30
    assert _remote(env) == {keep, "otro.txt"}


def test_offsite_failure_notifies(oci_env: Env) -> None:
    env = oci_env
    (env.backup_dir / _stamp(1)).write_bytes(AGE_HEADER)
    result = env.run("offsite_oci.sh", FAKE_OCI_FAIL="1")
    assert result.returncode != 0
    assert any("fuera" in n.lower() for n in env.notices())
