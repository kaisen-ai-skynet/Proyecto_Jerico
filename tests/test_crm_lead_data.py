"""Tests de notas, adjuntos y edición con historial (VCRM-007, 008, 009, 080–083, 109, 112)."""

import asyncio
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from crm_support import FakeClock, FakeTelegram
from jerico.crm import leads, repo
from jerico.crm.bot import CrmBot
from jerico.crm.db import CrmDatabase
from jerico.crm.files import MAX_ATTACHMENT_BYTES, LocalFileStore
from jerico.crm.fingerprint import fingerprint
from jerico.crm.model import AuditAction, AuditDetail, AuditOutcome, LeadState, Role, User
from jerico.crm.parsing import EDITABLE, build_callback
from jerico.crm.permissions import Action, authorize
from jerico.crm.ports import FileKind, FileRef, Update
from jerico.crm.timeutil import to_iso

START = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
CTO_TG = 1000
COM_TG = 2000
COM2_TG = 2100
LAW_TG = 3000
KEY = "clave-actual"
OLD_KEY = "clave-previa"


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


@pytest.fixture
def bot(db: CrmDatabase, tg: FakeTelegram, store: LocalFileStore) -> CrmBot:
    return CrmBot(db, tg, FakeClock(START).now, fingerprint_keys=(KEY, OLD_KEY), files=store)


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
            "com2": repo.insert_user(
                tx, telegram_id=COM2_TG, role=Role.COMMERCIAL, email="com2@k.co", now=START
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


def _file(
    user_tg: int,
    caption: str | None,
    file_id: str,
    kind: FileKind = "document",
    size: int | None = None,
    chat_type: str = "private",
) -> Update:
    return Update(
        update_id=next(_next_update),
        user_id=user_tg,
        chat_id=user_tg,
        chat_type=chat_type,
        caption=caption,
        file=FileRef(file_id=file_id, size=size, kind=kind),
    )


def run(bot: CrmBot, u: Update) -> None:
    asyncio.run(bot.process_update(u))


def _lead(db: CrmDatabase, user_id: int | None, **fields: str | None) -> int:
    base: dict[str, str | None] = {"name": "Ana Pérez", "phone_e164": "+573001234567"}
    base.update(fields)
    with db.tx() as tx:
        return repo.insert_lead(
            tx, assigned_user_id=user_id, state=LeadState.NEW, now=START, fields=base
        )


def _rows(db: CrmDatabase, sql: str) -> list[dict[str, Any]]:
    with db.read() as conn:
        return [dict(r) for r in conn.execute(sql).fetchall()]


def _stored_files(store: LocalFileStore) -> list[Path]:
    if not store.base_dir.exists():
        return []
    return [p for p in store.base_dir.rglob("*") if p.is_file()]


def _last_audit(db: CrmDatabase) -> dict[str, Any]:
    with db.read() as conn:
        return dict(repo.audit_rows(conn)[-1])


# --- Notas (VCRM-009) -------------------------------------------------------------------


def test_vcrm009_note_with_author_and_date(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id)
    run(bot, _msg(COM_TG, "/nota L-0001; Llamar el martes; pidió propuesta"))
    notes = _rows(db, "SELECT * FROM crm_notes")
    assert len(notes) == 1
    assert notes[0]["lead_id"] == lead_id
    assert notes[0]["author_user_id"] == users["com"].id
    assert notes[0]["body"] == "Llamar el martes; pidió propuesta"
    assert notes[0]["at"] == to_iso(START)
    assert "L-0001" in tg.sent[-1].text
    assert "Nota" in tg.sent[-1].text


def test_vcrm009_cto_can_note_any_lead(
    bot: CrmBot, db: CrmDatabase, users: dict[str, User]
) -> None:
    _lead(db, users["com"].id)
    run(bot, _msg(CTO_TG, "/nota L-1; Revisado"))
    assert _rows(db, "SELECT author_user_id FROM crm_notes") == [
        {"author_user_id": users["cto"].id}
    ]


@pytest.mark.parametrize("text", ["/nota", "/nota L-0001", "/nota L-0001;  ", "/nota x; hola"])
def test_vcrm009_note_bad_format(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User], text: str
) -> None:
    _lead(db, users["com"].id)
    run(bot, _msg(COM_TG, text))
    assert _rows(db, "SELECT * FROM crm_notes") == []
    assert leads.EXAMPLE_NOTE in tg.sent[-1].text


def test_vcrm009_note_missing_lead(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    run(bot, _msg(COM_TG, "/nota L-0099; hola"))
    assert _rows(db, "SELECT * FROM crm_notes") == []
    assert "L-0099" in tg.sent[-1].text
    assert "no existe" in tg.sent[-1].text


def test_vcrm009_lawyer_cannot_note(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    _lead(db, users["com"].id)
    run(bot, _msg(LAW_TG, "/nota L-1; hola"))
    assert _rows(db, "SELECT * FROM crm_notes") == []
    assert "No tiene permiso" in tg.sent[-1].text


# --- Adjuntos (VCRM-007, 008) -----------------------------------------------------------


@pytest.mark.parametrize("kind", ["photo", "document", "voice"])
def test_vcrm007_attachment_saved_with_kind_author_date(
    bot: CrmBot,
    tg: FakeTelegram,
    db: CrmDatabase,
    store: LocalFileStore,
    users: dict[str, User],
    kind: FileKind,
) -> None:
    lead_id = _lead(db, users["com"].id)
    tg.files["f1"] = b"contenido"
    run(bot, _file(COM_TG, "L-0001 contrato", "f1", kind=kind, size=9))
    rows = _rows(db, "SELECT * FROM crm_attachments")
    assert len(rows) == 1
    row = rows[0]
    assert (row["lead_id"], row["kind"], row["author_user_id"]) == (
        lead_id,
        kind,
        users["com"].id,
    )
    assert row["at"] == to_iso(START)
    assert row["size_bytes"] == 9
    assert row["sha256"] == hashlib.sha256(b"contenido").hexdigest()
    with store.open(row["storage_key"]) as fh:
        assert fh.read() == b"contenido"
    assert [p.parent.name for p in _stored_files(store)] == [str(lead_id)]
    assert "L-0001" in tg.sent[-1].text
    assert "Adjunto" in tg.sent[-1].text


def test_vcrm008_too_large_declared_is_not_downloaded(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, store: LocalFileStore, users: dict[str, User]
) -> None:
    _lead(db, users["com"].id)
    run(bot, _file(COM_TG, "L-0001", "big", size=MAX_ATTACHMENT_BYTES + 1))
    assert _rows(db, "SELECT * FROM crm_attachments") == []
    assert _stored_files(store) == []
    assert "20 MB" in tg.sent[-1].text


def test_vcrm008_too_large_on_download(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, store: LocalFileStore, users: dict[str, User]
) -> None:
    _lead(db, users["com"].id)
    tg.files["big"] = b"x" * (MAX_ATTACHMENT_BYTES + 1)
    run(bot, _file(COM_TG, "L-0001", "big"))
    assert _rows(db, "SELECT * FROM crm_attachments") == []
    assert _stored_files(store) == []
    assert "20 MB" in tg.sent[-1].text


def test_vcrm008_failed_download(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, store: LocalFileStore, users: dict[str, User]
) -> None:
    _lead(db, users["com"].id)
    run(bot, _file(COM_TG, "L-0001", "missing"))
    assert _rows(db, "SELECT * FROM crm_attachments") == []
    assert _stored_files(store) == []
    assert "descargar" in tg.sent[-1].text


@pytest.mark.parametrize("caption", [None, "contrato", "L-0099"])
def test_vcrm008_missing_or_unknown_lead(
    bot: CrmBot,
    tg: FakeTelegram,
    db: CrmDatabase,
    store: LocalFileStore,
    users: dict[str, User],
    caption: str | None,
) -> None:
    _lead(db, users["com"].id)
    tg.files["f1"] = b"contenido"
    run(bot, _file(COM_TG, caption, "f1"))
    assert _rows(db, "SELECT * FROM crm_attachments") == []
    assert _stored_files(store) == []
    assert "No se guardó" in tg.sent[-1].text


def test_vcrm008_insert_failure_leaves_no_file(
    bot: CrmBot,
    tg: FakeTelegram,
    db: CrmDatabase,
    store: LocalFileStore,
    users: dict[str, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _lead(db, users["com"].id)
    tg.files["f1"] = b"contenido"

    def boom(*args: object, **kwargs: object) -> int:
        raise RuntimeError("disco")

    monkeypatch.setattr(repo, "insert_attachment", boom)
    run(bot, _file(COM_TG, "L-0001", "f1"))
    assert _rows(db, "SELECT * FROM crm_attachments") == []
    assert _stored_files(store) == []


def test_vcrm008_file_from_unknown_user_or_group_is_discarded(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, store: LocalFileStore, users: dict[str, User]
) -> None:
    _lead(db, users["com"].id)
    tg.files["f1"] = b"contenido"
    run(bot, _file(9999, "L-0001", "f1"))
    run(bot, _file(COM_TG, "L-0001", "f1", chat_type="group"))
    assert _rows(db, "SELECT * FROM crm_attachments") == []
    assert _stored_files(store) == []


def test_vcrm008_duplicate_update_discards_download(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, store: LocalFileStore, users: dict[str, User]
) -> None:
    _lead(db, users["com"].id)
    tg.files["f1"] = b"contenido"
    u = _file(COM_TG, "L-0001", "f1")
    run(bot, u)
    run(bot, u)
    assert len(_rows(db, "SELECT * FROM crm_attachments")) == 1
    assert len(_stored_files(store)) == 1


def test_file_without_store_is_not_recognized(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    plain = CrmBot(db, tg, FakeClock(START).now)
    _lead(db, users["com"].id)
    tg.files["f1"] = b"contenido"
    run(plain, _file(COM_TG, "L-0001", "f1"))
    assert _rows(db, "SELECT * FROM crm_attachments") == []
    assert "no reconocida" in tg.sent[-1].text


# --- Edición (VCRM-080 a 083, 112) ------------------------------------------------------


def test_vcrm080_edit_records_history(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id, email="ana@empresa.co")
    run(bot, _msg(COM_TG, "/editar L-0001; correo; Ana.Perez@Empresa.co"))
    with db.read() as conn:
        lead = repo.get_lead(conn, lead_id)
        events = repo.lead_events(conn, lead_id)
    assert lead is not None and lead.email == "ana.perez@empresa.co"
    assert len(events) == 1
    ev = events[0]
    assert (ev.kind, ev.field, ev.old_value, ev.new_value) == (
        "field",
        "correo",
        "ana@empresa.co",
        "ana.perez@empresa.co",
    )
    assert (ev.actor_user_id, ev.at) == (users["com"].id, to_iso(START))
    assert _last_audit(db)["action"] == AuditAction.LEAD_UPDATED
    assert "L-0001" in tg.sent[-1].text
    assert "actualizado" in tg.sent[-1].text


@pytest.mark.parametrize(
    ("command", "column", "expected"),
    [
        ("/editar L-1; nombre; Ana María", "name", "Ana María"),
        ("/editar L-1; teléfono; 310 555 0000", "phone_e164", "+573105550000"),
        ("/editar L-1; empresa; ACME SAS", "company", "ACME SAS"),
        ("/editar L-1; tipo; Empresa", "client_type", "empresa"),
        ("/editar L-1; representante; Luis Gómez", "legal_rep", "Luis Gómez"),
        ("/editar L-1; servicio; Asesoría", "service", "Asesoría"),
        ("/editar L-1; valor; 5.000.000 COP", "agreed_value", "5.000.000 COP"),
        ("/editar L-1; plazo; 2026-04-01", "start_term", "2026-04-01"),
    ],
)
def test_vcrm080_cto_edits_each_field(
    bot: CrmBot, db: CrmDatabase, users: dict[str, User], command: str, column: str, expected: str
) -> None:
    lead_id = _lead(db, users["com"].id)
    run(bot, _msg(CTO_TG, command))
    with db.read() as conn:
        lead = repo.get_lead(conn, lead_id)
        events = repo.lead_events(conn, lead_id)
    assert lead is not None and getattr(lead, column) == expected
    assert events[-1].new_value == expected
    assert events[-1].actor_user_id == users["cto"].id


def test_vcrm080_edit_document_sets_type_and_number(
    bot: CrmBot, db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id)
    run(bot, _msg(COM_TG, "/editar L-1; documento; NIT 900123456-7"))
    with db.read() as conn:
        lead = repo.get_lead(conn, lead_id)
        events = repo.lead_events(conn, lead_id)
    assert lead is not None and (lead.doc_type, lead.doc_number) == ("NIT", "900123456-7")
    assert (events[-1].field, events[-1].old_value, events[-1].new_value) == (
        "documento",
        None,
        "NIT 900123456-7",
    )


@pytest.mark.parametrize(
    "command",
    ["/editar L-0099; correo; a@b.co", "/editar L-0001; estado; ganado", "/editar", "/editar x; y"],
)
def test_vcrm081_missing_lead_or_not_editable_lists_fields(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User], command: str
) -> None:
    _lead(db, users["com"].id)
    run(bot, _msg(COM_TG, command))
    with db.read() as conn:
        assert repo.lead_events(conn, 1) == []
    reply = tg.sent[-1].text
    assert all(field in reply for field in EDITABLE)


def test_vcrm081_missing_lead_states_cause(
    bot: CrmBot, tg: FakeTelegram, users: dict[str, User]
) -> None:
    run(bot, _msg(COM_TG, "/editar L-0099; correo; a@b.co"))
    assert "L-0099 no existe" in tg.sent[-1].text


@pytest.mark.parametrize(
    ("command", "field"),
    [("/editar L-1; telefono; 123", "telefono"), ("/editar L-1; correo; sin-arroba", "correo")],
)
def test_vcrm082_invalid_phone_or_email(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User], command: str, field: str
) -> None:
    _lead(db, users["com"].id)
    run(bot, _msg(COM_TG, command))
    with db.read() as conn:
        lead = repo.get_lead(conn, 1)
        assert repo.lead_events(conn, 1) == []
    assert lead is not None and lead.phone_e164 == "+573001234567"
    assert field in tg.sent[-1].text


def test_vcrm083_duplicate_visible_shows_id(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    _lead(db, users["com"].id)
    _lead(db, users["com"].id, phone_e164="+573109998877")
    run(bot, _msg(COM_TG, "/editar L-2; telefono; 300 123 4567"))
    with db.read() as conn:
        lead = repo.get_lead(conn, 2)
    assert lead is not None and lead.phone_e164 == "+573109998877"
    assert "L-0001" in tg.sent[-1].text
    assert "coincide" in tg.sent[-1].text


def test_vcrm083_duplicate_hidden_omits_id(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    _lead(db, users["com2"].id, email="otro@empresa.co", phone_e164=None)
    _lead(db, users["com"].id)
    run(bot, _msg(COM_TG, "/editar L-2; correo; OTRO@empresa.co"))
    with db.read() as conn:
        lead = repo.get_lead(conn, 2)
    assert lead is not None and lead.email is None
    assert "coincide" in tg.sent[-1].text
    assert "L-0001" not in tg.sent[-1].text


def test_vcrm083_same_lead_or_lost_lead_is_not_duplicate(
    bot: CrmBot, db: CrmDatabase, users: dict[str, User]
) -> None:
    with db.tx() as tx:
        repo.insert_lead(
            tx,
            assigned_user_id=users["com"].id,
            state=LeadState.LOST,
            now=START,
            fields={"name": "Viejo", "email": "nuevo@empresa.co"},
        )
    _lead(db, users["com"].id)
    run(bot, _msg(COM_TG, "/editar L-2; telefono; 300 123 4567"))
    run(bot, _msg(COM_TG, "/editar L-2; correo; nuevo@empresa.co"))
    with db.read() as conn:
        lead = repo.get_lead(conn, 2)
        events = repo.lead_events(conn, 2)
    assert lead is not None and lead.email == "nuevo@empresa.co"
    assert len(events) == 2


@pytest.mark.parametrize("key", [KEY, OLD_KEY])
def test_vcrm083_suppressed_fingerprint(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User], key: str
) -> None:
    _lead(db, users["com"].id)
    with db.tx() as tx:
        tx.execute(
            "INSERT INTO crm_suppression (fingerprint, at, medium) VALUES (?, ?, ?)",
            (fingerprint(key, "baja@empresa.co"), to_iso(START), "telegram"),
        )
    run(bot, _msg(COM_TG, "/editar L-1; correo; baja@empresa.co"))
    with db.read() as conn:
        lead = repo.get_lead(conn, 1)
    assert lead is not None and lead.email is None
    assert "no ser contactado" in tg.sent[-1].text


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("/editar L-1; tipo; cooperativa", "persona natural"),
        ("/editar L-1; documento; RUT 123", "pasaporte"),
        ("/editar L-1; tipo;", "vacío"),
        ("/editar L-1; servicio;  ", "vacío"),
    ],
)
def test_vcrm112_invalid_handoff_values(
    bot: CrmBot,
    tg: FakeTelegram,
    db: CrmDatabase,
    users: dict[str, User],
    command: str,
    expected: str,
) -> None:
    _lead(db, users["com"].id)
    run(bot, _msg(COM_TG, command))
    with db.read() as conn:
        assert repo.lead_events(conn, 1) == []
    assert expected in tg.sent[-1].text
    assert "No se modificó" in tg.sent[-1].text


def test_vcrm112_empty_non_handoff_value_asks_for_value(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    _lead(db, users["com"].id)
    run(bot, _msg(COM_TG, "/editar L-1; nombre;"))
    with db.read() as conn:
        assert repo.lead_events(conn, 1) == []
    assert "valor" in tg.sent[-1].text


def test_lawyer_cannot_edit(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    _lead(db, users["com"].id)
    run(bot, _msg(LAW_TG, "/editar L-1; nombre; Otro"))
    with db.read() as conn:
        assert repo.lead_events(conn, 1) == []
    assert "No tiene permiso" in tg.sent[-1].text


# --- Lead ajeno (VCRM-109) --------------------------------------------------------------


def _assert_no_access(tg: FakeTelegram, db: CrmDatabase, lead_id: int) -> None:
    reply = tg.sent[-1].text
    assert "no tiene acceso a ese lead" in reply
    assert "Ana" not in reply and "+57" not in reply
    audit = _last_audit(db)
    assert (audit["action"], audit["outcome"], audit["lead_id"], audit["detail_code"]) == (
        AuditAction.PERMISSION_DENIED,
        AuditOutcome.DENIED,
        lead_id,
        AuditDetail.FOREIGN_LEAD,
    )


def test_vcrm109_foreign_note_denied(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com2"].id)
    run(bot, _msg(COM_TG, "/nota L-1; hola"))
    assert _rows(db, "SELECT * FROM crm_notes") == []
    _assert_no_access(tg, db, lead_id)


def test_vcrm109_foreign_edit_denied(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com2"].id)
    run(bot, _msg(COM_TG, "/editar L-1; nombre; Otro"))
    with db.read() as conn:
        lead = repo.get_lead(conn, lead_id)
    assert lead is not None and lead.name == "Ana Pérez"
    _assert_no_access(tg, db, lead_id)


def test_vcrm109_foreign_attachment_denied(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, store: LocalFileStore, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com2"].id)
    tg.files["f1"] = b"contenido"
    run(bot, _file(COM_TG, "L-0001", "f1"))
    assert _rows(db, "SELECT * FROM crm_attachments") == []
    assert _stored_files(store) == []
    _assert_no_access(tg, db, lead_id)


def test_vcrm109_foreign_record_denied(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com2"].id)
    run(
        bot,
        Update(
            update_id=next(_next_update),
            user_id=COM_TG,
            chat_id=COM_TG,
            chat_type="private",
            callback_id="cb",
            callback_data=build_callback("abrir", str(lead_id)),
        ),
    )
    _assert_no_access(tg, db, lead_id)


@pytest.mark.parametrize(
    "action", [Action.CONTACT_REJECT, Action.ACCEPT, Action.MARK_LOST, Action.REGISTER_OPT_OUT]
)
def test_vcrm109_foreign_state_change_denied(
    db: CrmDatabase, users: dict[str, User], action: Action
) -> None:
    lead_id = _lead(db, users["com2"].id)
    with db.tx() as tx:
        lead = repo.get_lead(tx, lead_id)
        assert lead is not None
        decision = authorize(users["com"], action, lead)
        assert decision.denial == "foreign_lead"
        out = leads.deny_lead(tx, users["com"], decision, lead_id, START)
    assert [o.chat_id for o in out] == [COM_TG]
    assert "no tiene acceso a ese lead" in out[0].text
    assert _last_audit(db)["detail_code"] == AuditDetail.FOREIGN_LEAD


def test_leads_add_attachment_file_abogado_denegado(
    db: CrmDatabase, store: LocalFileStore, users: dict[str, User], tmp_path: Path
) -> None:
    lead_id = _lead(db, users["com"].id)
    temp_file = tmp_path / "temp.pdf"
    temp_file.write_bytes(b"data")
    prefetched = leads.Prefetched(
        kind="document",
        path=temp_file,
        result=leads.DownloadResult(ok=True, size=4),
    )
    with db.tx() as tx:
        out = leads.add_attachment(tx, users["law"], f"L-{lead_id:04d}", prefetched, store, START)
    assert len(out) == 1
    assert "No tiene permiso" in out[0].text


def test_leads_requested_field_sin_separador_retorna_none() -> None:
    assert leads._requested_field("/editar L-0001") is None
