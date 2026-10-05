"""Tests de la exportación de datos del titular y de la bitácora (T20b).

Requisitos: VCRM-074, 075, 165, 166 (decisión K-5).
"""

import asyncio
import hashlib
import io
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from crm_support import FakeClock, FakeTelegram, SentTelegram
from jerico.crm import compliance, repo
from jerico.crm.bot import CrmBot
from jerico.crm.db import CrmDatabase
from jerico.crm.files import LocalFileStore
from jerico.crm.model import AuditAction, AuthStatus, EventKind, LeadState, Role, User
from jerico.crm.ports import Update

START = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
CTO_TG = 1000
COM_TG = 2000
LAW_TG = 3000
KEY = "clave-actual"
NAME = "Zuleima Centinela"
PHONE = "+573001234567"
EMAIL = "ana@empresa.co"
NOTE = "nota-centinela-xyz"
DOC = compliance.EXPORT_DOC


@pytest.fixture
def db(tmp_path: Path) -> Iterator[CrmDatabase]:
    database = CrmDatabase(tmp_path / "crm.db")
    yield database
    database.close()


@pytest.fixture
def tg() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def store(tmp_path: Path) -> LocalFileStore:
    return LocalFileStore(tmp_path / "files")


def _bot(db: CrmDatabase, tg: FakeTelegram, store: LocalFileStore | None, **kwargs: Any) -> CrmBot:
    return CrmBot(db, tg, FakeClock(START).now, fingerprint_keys=(KEY,), files=store, **kwargs)


@pytest.fixture
def bot(db: CrmDatabase, tg: FakeTelegram, store: LocalFileStore) -> CrmBot:
    return _bot(db, tg, store)


@pytest.fixture
def users(db: CrmDatabase) -> dict[str, User]:
    with db.tx() as tx:
        return {
            "cto": repo.insert_user(
                tx, telegram_id=CTO_TG, role=Role.CTO, email="cto@k.co", now=START
            ),
            "com": repo.insert_user(
                tx, telegram_id=COM_TG, role=Role.COMMERCIAL, email="com@k.co", now=START
            ),
            "law": repo.insert_user(
                tx, telegram_id=LAW_TG, role=Role.LAWYER, email="law@k.co", now=START
            ),
        }


_next_update = iter(range(1, 10_000))


def _msg(user_tg: int, text: str) -> Update:
    return Update(
        update_id=next(_next_update),
        user_id=user_tg,
        chat_id=user_tg,
        chat_type="private",
        text=text,
    )


def run(bot: CrmBot, u: Update) -> None:
    asyncio.run(bot.process_update(u))


def _lead(db: CrmDatabase, user_id: int, state: LeadState = LeadState.NUEVO) -> int:
    with db.tx() as tx:
        return repo.insert_lead(
            tx,
            assigned_user_id=user_id,
            state=state,
            now=START,
            fields={"name": NAME, "phone_e164": PHONE, "email": EMAIL},
        )


def _attach(
    db: CrmDatabase,
    store: LocalFileStore,
    lead_id: int,
    author: int,
    content: bytes,
    kind: str = "photo",
) -> tuple[int, str]:
    tmp = store.new_tmp_path(".bin")
    tmp.write_bytes(content)
    key = store.save_atomic(lead_id, tmp)
    with db.tx() as tx:
        att_id = repo.insert_attachment(
            tx,
            lead_id=lead_id,
            kind=kind,
            author_user_id=author,
            at=START,
            storage_key=key,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )
    return att_id, key


def _documents(tg: FakeTelegram) -> list[SentTelegram]:
    return [s for s in tg.sent if s.document is not None]


def _zip(item: SentTelegram) -> zipfile.ZipFile:
    assert item.content is not None
    archive = zipfile.ZipFile(io.BytesIO(item.content))
    assert archive.testzip() is None  # abrible por sí solo
    return archive


def _tmp_entries(store: LocalFileStore) -> list[Path]:
    tmp = store.base_dir / "tmp"
    return list(tmp.iterdir()) if tmp.exists() else []


def _full_lead(db: CrmDatabase, store: LocalFileStore, users: dict[str, User]) -> int:
    lead_id = _lead(db, users["com"].id, LeadState.ACEPTADO)
    ev_id, _ = _attach(db, store, lead_id, users["com"].id, b"firma-pdf", kind="authorization")
    with db.tx() as tx:
        repo.insert_note(tx, lead_id=lead_id, author_user_id=users["com"].id, body=NOTE, at=START)
        repo.add_event(
            tx,
            lead_id=lead_id,
            kind=EventKind.FIELD,
            actor_user_id=users["com"].id,
            at=START,
            field="company",
            old_value=None,
            new_value="ACME SAS",
        )
        repo.insert_consent(
            tx,
            lead_id=lead_id,
            status=AuthStatus.AUTORIZADA,
            medium="documento_o_captura",
            at=START,
            actor_user_id=users["com"].id,
            attachment_id=ev_id,
        )
    return lead_id


# --- Permisos (VCRM-074: solo el CTO) ----------------------------------------------------


@pytest.mark.parametrize("who", [COM_TG, LAW_TG])
def test_vcrm074_only_the_cto_can_export(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User], who: int
) -> None:
    _lead(db, users["com"].id)
    run(bot, _msg(who, "/exportar L-0001"))
    assert _documents(tg) == []
    assert tg.sent[-1].chat_id == who
    with db.read() as conn:
        actions = [r["action"] for r in repo.audit_rows(conn)]
    assert AuditAction.LEAD_EXPORTED.value not in actions
    assert AuditAction.PERMISSION_DENIED.value in actions


def test_vcrm074_invalid_format_and_unknown_lead(
    bot: CrmBot, tg: FakeTelegram, users: dict[str, User]
) -> None:
    run(bot, _msg(CTO_TG, "/exportar cosa"))
    assert "Formato no válido" in tg.sent[-1].text
    run(bot, _msg(CTO_TG, "/exportar L-0099"))
    assert "no existe" in tg.sent[-1].text
    assert _documents(tg) == []


def test_vcrm074_without_file_store_nothing_is_exported(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    _lead(db, users["com"].id)
    run(_bot(db, tg, None), _msg(CTO_TG, "/exportar L-0001"))
    assert _documents(tg) == []
    assert "almacén" in tg.sent[-1].text


# --- Exportación en una parte (VCRM-074) -------------------------------------------------


def test_vcrm074_zip_with_readable_document_and_live_attachments_to_cto_chat(
    bot: CrmBot,
    tg: FakeTelegram,
    db: CrmDatabase,
    store: LocalFileStore,
    users: dict[str, User],
) -> None:
    lead_id = _full_lead(db, store, users)
    photo_id, _ = _attach(db, store, lead_id, users["com"].id, b"foto-bytes")
    gone_id, _ = _attach(db, store, lead_id, users["com"].id, b"borrado")
    with db.tx() as tx:
        tx.execute(
            "UPDATE crm_attachments SET deleted_at = '2026-03-01T00:00:00Z' WHERE id = ?",
            (gone_id,),
        )
    run(bot, _msg(CTO_TG, "/exportar L-0001"))
    docs = _documents(tg)
    assert len(docs) == 1
    sent = docs[0]
    assert sent.chat_id == CTO_TG
    assert sent.document is not None and sent.document.name == "export_L-0001.zip"
    archive = _zip(sent)
    names = archive.namelist()
    assert names[0] == DOC
    text = archive.read(DOC).decode("utf-8")
    for expected in (
        NAME,
        PHONE,
        EMAIL,
        NOTE,
        "Handoff",
        "Historial",
        "ACME SAS",
        "Autorizaciones",
        "autorizada",
        "documento_o_captura",
    ):
        assert expected in text
    members = {n: archive.read(n) for n in names if n != DOC}
    assert sorted(members.values()) == [b"firma-pdf", b"foto-bytes"]
    assert not any(n.startswith(f"adjuntos/{gone_id}_") for n in members)
    assert any(n.startswith(f"adjuntos/{photo_id}_") for n in members)
    assert _tmp_entries(store) == []


def test_vcrm074_temp_file_removed_when_the_send_fails(
    bot: CrmBot,
    tg: FakeTelegram,
    db: CrmDatabase,
    store: LocalFileStore,
    users: dict[str, User],
) -> None:
    _full_lead(db, store, users)
    tg.fail_document(1)
    run(bot, _msg(CTO_TG, "/exportar L-0001"))
    assert _documents(tg) == []
    assert _tmp_entries(store) == []
    assert "No se entregaron" in tg.sent[-1].text
    assert tg.sent[-1].chat_id == CTO_TG


def test_vcrm074_temp_file_removed_when_building_the_zip_fails(
    bot: CrmBot,
    tg: FakeTelegram,
    db: CrmDatabase,
    store: LocalFileStore,
    users: dict[str, User],
) -> None:
    lead_id = _lead(db, users["com"].id)
    _, key = _attach(db, store, lead_id, users["com"].id, b"foto")
    store.delete(key)  # el archivo desaparece del almacén: no se puede leer
    run(bot, _msg(CTO_TG, "/exportar L-0001"))
    assert _documents(tg) == []
    assert _tmp_entries(store) == []
    assert "No se entregaron" in tg.sent[-1].text


# --- Reparto en partes (VCRM-166; decisión K-5) ------------------------------------------


def test_vcrm166_plan_export_parts_single_part_when_it_fits() -> None:
    parts = compliance.plan_export_parts(100, [(1, 200), (2, 300)], limit=10_000, margin=1_000)
    assert parts == [[DOC, 1, 2]]


def test_vcrm166_plan_export_parts_small_limit() -> None:
    sizes = {3: 400, 1: 500, 2: 300, 4: 900, 5: 100}
    limit, margin = 1_200, 200
    parts = compliance.plan_export_parts(300, list(sizes.items()), limit=limit, margin=margin)
    assert parts[0][0] == DOC
    assert all(DOC not in p for p in parts[1:])
    flat = [i for p in parts for i in p if i != DOC]
    assert sorted(flat) == [1, 2, 3, 4, 5] and len(flat) == len(set(flat))
    assert flat == sorted(flat)  # orden de id
    for k, part in enumerate(parts):
        size = (300 if k == 0 else 0) + sum(sizes[int(i)] for i in part if i != DOC)
        assert size <= limit - margin
    assert parts == [[DOC, 1], [2, 3], [4, 5]]


def test_vcrm166_plan_export_parts_is_deterministic() -> None:
    items = [(2, 600), (1, 600), (3, 600)]
    first = compliance.plan_export_parts(10, items, limit=1_500, margin=100)
    assert first == compliance.plan_export_parts(10, list(reversed(items)), limit=1_500, margin=100)


def test_vcrm166_large_export_is_sent_in_numbered_self_contained_parts(
    db: CrmDatabase, tg: FakeTelegram, store: LocalFileStore, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id)
    blobs = {}
    for k in range(3):
        content = bytes([65 + k]) * 3_000
        att_id, _ = _attach(db, store, lead_id, users["com"].id, content)
        blobs[att_id] = content
    bot = _bot(db, tg, store, export_limit=5_500, export_margin=500)
    run(bot, _msg(CTO_TG, "/exportar L-0001"))
    docs = _documents(tg)
    n = len(docs)
    assert n == 3
    seen: dict[str, int] = {}
    for k, item in enumerate(docs, start=1):
        assert item.chat_id == CTO_TG
        assert item.document is not None
        assert item.document.name == f"export_L-0001_parte_{k}_de_{n}.zip"
        assert f"Parte {k} de {n}" in item.text
        archive = _zip(item)
        assert (DOC in archive.namelist()) == (k == 1)
        for name in archive.namelist():
            if name != DOC:
                assert name not in seen
                seen[name] = k
                att_id = int(name.split("/")[1].split("_")[0])
                assert archive.read(name) == blobs[att_id]
    assert len(seen) == 3
    index = _zip(docs[0]).read(DOC).decode("utf-8")
    for name, k in seen.items():
        assert f"{name} · parte {k} de {n}" in index
    assert _tmp_entries(store) == []


def test_vcrm166_failed_part_does_not_stop_the_rest_and_cto_is_told(
    db: CrmDatabase, tg: FakeTelegram, store: LocalFileStore, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id)
    for k in range(3):
        _attach(db, store, lead_id, users["com"].id, bytes([65 + k]) * 3_000)
    bot = _bot(db, tg, store, export_limit=5_500, export_margin=500)
    tg.fail_document(2)
    run(bot, _msg(CTO_TG, "/exportar L-0001"))
    names = [d.document.name for d in _documents(tg) if d.document is not None]
    assert names == ["export_L-0001_parte_1_de_3.zip", "export_L-0001_parte_3_de_3.zip"]
    assert tg.sent[-1].chat_id == CTO_TG
    assert "No se entregaron: 2 de 3" in tg.sent[-1].text
    assert _tmp_entries(store) == []


# --- Evidencia reducida (VCRM-165) -------------------------------------------------------


def test_vcrm165_reduced_evidence_appears_only_as_minimal_fingerprint(
    bot: CrmBot,
    tg: FakeTelegram,
    db: CrmDatabase,
    store: LocalFileStore,
    users: dict[str, User],
) -> None:
    _full_lead(db, store, users)
    run(bot, _msg(CTO_TG, "/suprimir L-0001"))
    run(bot, _msg(CTO_TG, "/exportar L-0001"))
    archive = _zip(_documents(tg)[-1])
    assert archive.namelist() == [DOC]
    text = archive.read(DOC).decode("utf-8")
    assert hashlib.sha256(b"firma-pdf").hexdigest() in text
    assert "9 bytes" in text and "huella mínima" in text
    for secret in (NAME, PHONE, EMAIL, NOTE):
        assert secret not in text


# --- Bitácora (VCRM-075) -----------------------------------------------------------------


def test_vcrm075_audit_log_records_creation_update_export_and_suppression(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    run(bot, _msg(CTO_TG, f"/nuevo {NAME}; 300 123 4567; {EMAIL}"))
    run(bot, _msg(CTO_TG, "/editar L-0001; empresa; ACME SAS"))
    run(bot, _msg(CTO_TG, "/exportar L-0001"))
    run(bot, _msg(CTO_TG, "/suprimir L-0001"))
    with db.read() as conn:
        rows = repo.audit_rows(conn)
    wanted = [
        AuditAction.LEAD_CREATED,
        AuditAction.LEAD_UPDATED,
        AuditAction.LEAD_EXPORTED,
        AuditAction.LEAD_SUPPRESSED,
    ]
    for action in wanted:
        hits = [r for r in rows if r["action"] == action.value]
        assert hits, action
        row = hits[0]
        assert row["actor"] == f"user:{users['cto'].id}"
        assert row["lead_id"] == 1
        assert row["at"] == "2026-03-02T15:00:00Z"
    dump = repr(rows)
    for secret in (NAME, "3001234567", EMAIL, "ACME SAS"):
        assert secret not in dump
