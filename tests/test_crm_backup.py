"""T23 — Respaldo nocturno cifrado fuera de la máquina (VCRM-097, 098; plan §8.6)."""

import asyncio
import io
import sqlite3
import tarfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from crm_support import FakeEmailSender, FakeRunner, FakeTelegram
from jerico.crm import backup, repo
from jerico.crm.db import CrmDatabase
from jerico.crm.model import Role
from jerico.crm.ports import CommandResult
from jerico.crm.timeutil import to_iso

NOW = datetime(2026, 3, 2, 8, 0, 5, tzinfo=UTC)
CTO_TG = 1000
COM_TG = 2000
NAME = "crm-20260302T080005Z.tar.gz.age"
REMOTE = "oci:jerico-backups/crm"


@pytest.fixture
def db(tmp_path: Path) -> Iterator[CrmDatabase]:
    database = CrmDatabase(tmp_path / "crm.db")
    with database.tx() as tx:
        repo.insert_user(tx, telegram_id=CTO_TG, role=Role.CTO, email="cto@k.co", now=NOW)
        repo.insert_user(tx, telegram_id=COM_TG, role=Role.COMMERCIAL, email="com@k.co", now=NOW)
    yield database
    database.close()


@pytest.fixture
def attachments(tmp_path: Path) -> Path:
    base = tmp_path / "attachments"
    (base / "7").mkdir(parents=True)
    (base / "7" / "evidencia.png").write_bytes(b"evidencia-autorizacion")
    (base / "7" / "propuesta.pdf").write_bytes(b"adjunto-pdf")
    return base


def _run(
    db: CrmDatabase,
    tg: FakeTelegram,
    runner: Any,
    tmp_path: Path,
    attachments: Path,
    email: FakeEmailSender | None = None,
    **overrides: Any,
) -> bool:
    kwargs: dict[str, Any] = {
        "attachments_dir": attachments,
        "work_dir": tmp_path / "work",
        "recipient": "age1publica",
        "remote": REMOTE,
        "retention_days": 30,
    }
    kwargs.update(overrides)
    mail = email if email is not None else FakeEmailSender()
    return asyncio.run(backup.run_backup(db, tg, mail, runner, NOW, **kwargs))


def _last_ok(db: CrmDatabase) -> str | None:
    with db.read() as conn:
        return repo.get_meta(conn, backup.LAST_OK_KEY)


def test_vcrm097_backup_name_uses_utc_timestamp() -> None:
    bogota = NOW.astimezone(timezone(timedelta(hours=-5)))
    assert backup.backup_name(bogota) == NAME


def test_vcrm097_snapshot_includes_db_attachments_and_evidence(
    db: CrmDatabase, tmp_path: Path, attachments: Path
) -> None:
    with db.tx() as tx:
        repo.set_meta(tx, "marca", "consistente")
    runner, tg = FakeRunner(), FakeTelegram()
    assert _run(db, tg, runner, tmp_path, attachments) is True
    with tarfile.open(fileobj=io.BytesIO(runner.inputs["age"]), mode="r:gz") as tar:
        names = set(tar.getnames())
        assert {"crm.db", "attachments/7/evidencia.png", "attachments/7/propuesta.pdf"} <= names
        member = tar.extractfile("attachments/7/evidencia.png")
        assert member is not None and member.read() == b"evidencia-autorizacion"
        tar.extract("crm.db", tmp_path / "out", filter="data")
    snap = sqlite3.connect(tmp_path / "out" / "crm.db")
    try:
        assert snap.execute("SELECT value FROM crm_meta WHERE key='marca'").fetchone() == (
            "consistente",
        )
    finally:
        snap.close()
    assert tg.sent == []


def test_vcrm097_exact_argv_for_encrypt_upload_and_listing(
    db: CrmDatabase, tmp_path: Path, attachments: Path
) -> None:
    runner = FakeRunner()
    assert _run(db, FakeTelegram(), runner, tmp_path, attachments)
    age, copy, lsf = runner.calls
    assert age[:5] == ["age", "--encrypt", "--recipient", "age1publica", "--output"]
    assert age[5].endswith(NAME) and age[6].endswith(".tar.gz") and len(age) == 7
    assert copy == ["rclone", "copyto", age[5], f"{REMOTE}/{NAME}"]
    assert lsf == ["rclone", "lsf", REMOTE]


def test_vcrm097_expired_backups_pure_with_legal_cap() -> None:
    names = [
        "crm-20260131T080000Z.tar.gz.age",  # 30 días + 5 s: vencido
        "crm-20260201T080005Z.tar.gz.age",  # 29 días: se conserva
        "crm-20260101T080000Z.tar.gz.age",  # vencido
        "otro-archivo.txt",
        "crm-malformado.tar.gz.age",
        NAME,
    ]
    assert backup.expired_backups(names, NOW, 30) == [
        "crm-20260131T080000Z.tar.gz.age",
        "crm-20260101T080000Z.tar.gz.age",
    ]
    # Tope legal: 45 días configurados se aplican como 30.
    assert backup.expired_backups(names, NOW, 45) == backup.expired_backups(names, NOW, 30)
    assert backup.expired_backups(names, NOW, 40) != []
    assert backup.expired_backups(["crm-20260215T080000Z.tar.gz.age"], NOW, 10) == [
        "crm-20260215T080000Z.tar.gz.age"
    ]


def test_vcrm097_deletes_expired_with_rclone_deletefile(
    db: CrmDatabase, tmp_path: Path, attachments: Path
) -> None:
    runner = FakeRunner()
    runner.listing = ["crm-20260101T080000Z.tar.gz.age", "crm-20260220T080000Z.tar.gz.age", NAME]
    assert _run(db, FakeTelegram(), runner, tmp_path, attachments)
    assert runner.calls[3:] == [
        ["rclone", "deletefile", f"{REMOTE}/crm-20260101T080000Z.tar.gz.age"]
    ]


def test_vcrm097_success_updates_last_ok_and_cleans_temporaries(
    db: CrmDatabase, tmp_path: Path, attachments: Path
) -> None:
    assert _run(db, FakeTelegram(), FakeRunner(), tmp_path, attachments)
    assert _last_ok(db) == to_iso(NOW)
    assert list((tmp_path / "work").iterdir()) == []


@pytest.mark.parametrize(
    ("prog", "sub", "step"),
    [
        ("age", "--encrypt", "cifrado"),
        ("rclone", "copyto", "transferencia"),
        ("rclone", "lsf", "eliminación por vencimiento"),
        ("rclone", "deletefile", "eliminación por vencimiento"),
    ],
)
def test_vcrm098_step_failure_notifies_cto_with_cause_and_last_ok(
    db: CrmDatabase, tmp_path: Path, attachments: Path, prog: str, sub: str, step: str
) -> None:
    previous = NOW - timedelta(days=1)
    with db.tx() as tx:
        repo.set_meta(tx, backup.LAST_OK_KEY, to_iso(previous))
    runner = FakeRunner()
    runner.listing = ["crm-20260101T080000Z.tar.gz.age"]
    runner.fail(prog, sub, 3)
    tg = FakeTelegram()
    assert _run(db, tg, runner, tmp_path, attachments) is False
    assert [m.chat_id for m in tg.sent] == [CTO_TG]
    text = tg.sent[0].text
    assert step in text and "código 3" in text and "01/03/2026 03:00" in text
    assert "error simulado" not in text
    assert _last_ok(db) == to_iso(previous)
    assert list((tmp_path / "work").iterdir()) == []


def test_vcrm098_snapshot_failure_notifies_and_cleans(
    db: CrmDatabase, tmp_path: Path, attachments: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(source: Path, dest: Path) -> None:
        dest.write_bytes(b"parcial")
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(backup, "_snapshot", broken)
    runner, tg = FakeRunner(), FakeTelegram()
    assert _run(db, tg, runner, tmp_path, attachments) is False
    assert runner.calls == []
    assert "generación" in tg.sent[0].text and "OperationalError" in tg.sent[0].text
    assert "ninguno" in tg.sent[0].text
    assert list((tmp_path / "work").iterdir()) == []


@pytest.mark.parametrize(
    ("override", "variable"),
    [
        ({"recipient": None}, "JERICO_CRM_BACKUP_AGE_RECIPIENT"),
        ({"remote": ""}, "JERICO_CRM_BACKUP_REMOTE"),
    ],
)
def test_vcrm098_missing_configuration_notifies_cto(
    db: CrmDatabase, tmp_path: Path, attachments: Path, override: dict[str, Any], variable: str
) -> None:
    runner, tg = FakeRunner(), FakeTelegram()
    assert _run(db, tg, runner, tmp_path, attachments, **override) is False
    assert runner.calls == []
    assert "configuración" in tg.sent[0].text and variable in tg.sent[0].text
    assert _last_ok(db) is None


def test_vcrm098_missing_binary_is_a_failure(
    db: CrmDatabase, tmp_path: Path, attachments: Path
) -> None:
    class MissingBinary(FakeRunner):
        async def run(self, argv: list[str], timeout_s: float) -> CommandResult:
            self.calls.append(argv)
            return CommandResult(returncode=127, stderr_tail="age: no encontrado")

    tg = FakeTelegram()
    assert _run(db, tg, MissingBinary(), tmp_path, attachments) is False
    assert "cifrado" in tg.sent[0].text and "código 127" in tg.sent[0].text


def test_vcrm098_undelivered_notice_is_recorded_as_failed(
    db: CrmDatabase, tmp_path: Path, attachments: Path
) -> None:
    runner, tg = FakeRunner(), FakeTelegram()
    runner.fail("rclone", "copyto")
    tg.fail_next(CTO_TG)
    assert _run(db, tg, runner, tmp_path, attachments) is False
    with db.read() as conn:
        rows = conn.execute("SELECT kind, status FROM crm_outbox").fetchall()
    assert [tuple(r) for r in rows] == [(backup.NOTICE_KIND, "failed")]


def test_vcrm098_failure_notifies_cto_by_email_too(
    db: CrmDatabase, tmp_path: Path, attachments: Path
) -> None:
    previous = NOW - timedelta(days=1)
    with db.tx() as tx:
        repo.set_meta(tx, backup.LAST_OK_KEY, to_iso(previous))
    runner, tg, mail = FakeRunner(), FakeTelegram(), FakeEmailSender()
    runner.fail("rclone", "copyto", 3)
    assert _run(db, tg, runner, tmp_path, attachments, email=mail) is False
    assert [m.to for m in mail.sent] == ["cto@k.co"]
    sent = mail.sent[0]
    assert "respaldo" in sent.subject.lower()
    assert "transferencia" in sent.body and "código 3" in sent.body
    assert "01/03/2026 03:00" in sent.body
    assert [m.chat_id for m in tg.sent] == [CTO_TG]


def test_vcrm098_success_sends_no_email(db: CrmDatabase, tmp_path: Path, attachments: Path) -> None:
    mail = FakeEmailSender()
    assert _run(db, FakeTelegram(), FakeRunner(), tmp_path, attachments, email=mail)
    assert mail.attempts == [] and mail.sent == []


def test_vcrm098_undelivered_email_notice_is_recorded_as_failed(
    db: CrmDatabase, tmp_path: Path, attachments: Path
) -> None:
    runner, tg = FakeRunner(), FakeTelegram()
    runner.fail("rclone", "copyto")
    mail = FakeEmailSender(configured=False)
    assert _run(db, tg, runner, tmp_path, attachments, email=mail) is False
    assert [m.chat_id for m in tg.sent] == [CTO_TG]
    with db.read() as conn:
        rows = conn.execute("SELECT kind, channel, status, last_error FROM crm_outbox").fetchall()
    assert [tuple(r) for r in rows] == [
        (backup.NOTICE_KIND, "email", "failed", "mailbox_not_configured")
    ]


def test_snapshot_uses_read_only_connection(db: CrmDatabase, tmp_path: Path) -> None:
    dest = tmp_path / "snap.db"
    backup._snapshot(db.path, dest)
    assert dest.exists()
    with pytest.raises(sqlite3.OperationalError):
        backup._snapshot(tmp_path / "inexistente.db", tmp_path / "x.db")


def test_subprocess_runner_success_timeout_and_missing_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Proc:
        def __init__(self, delay: float) -> None:
            self.delay = delay
            self.returncode: int | None = None
            self.killed = False

        async def communicate(self) -> tuple[bytes, bytes]:
            await asyncio.sleep(self.delay)
            self.returncode = 0
            return b"a\nb\n", b"x" * 600

        def kill(self) -> None:
            self.killed = True

        async def wait(self) -> int:
            return -9

    procs: list[Proc] = []

    async def fake_exec(*argv: str, **kwargs: Any) -> Proc:
        if argv[0] == "ausente":
            raise FileNotFoundError(argv[0])
        procs.append(Proc(float(argv[1])))
        return procs[-1]

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    runner = backup.SubprocessRunner()
    ok = asyncio.run(runner.run(["prog", "0"], timeout_s=5))
    assert ok.returncode == 0 and ok.stdout == "a\nb\n" and len(ok.stderr_tail) == 500
    slow = asyncio.run(runner.run(["prog", "1"], timeout_s=0.01))
    assert slow.returncode == 124 and procs[-1].killed
    missing = asyncio.run(runner.run(["ausente", "x"], timeout_s=1))
    assert missing.returncode == 127
