"""Tests de autorización con evidencia, baja y lista de supresión (T19).

Requisitos: VCRM-065, 070, 071, 095, 138, 139, 164.
"""

import asyncio
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from crm_support import FakeClock, FakeEmailSender, FakeTelegram
from jerico.crm import compliance, repo
from jerico.crm.bot import CrmBot
from jerico.crm.db import CrmDatabase
from jerico.crm.files import MAX_ATTACHMENT_BYTES, LocalFileStore
from jerico.crm.fingerprint import fingerprint
from jerico.crm.model import AuditAction, AuthStatus, Channel, LeadState, Role, User
from jerico.crm.outbox import OutboxWorker, enqueue_critical
from jerico.crm.ports import FileKind, FileRef, Update
from jerico.crm.timeutil import to_iso

START = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
CTO_TG = 1000
COM_TG = 2000
COM2_TG = 2100
LAW_TG = 3000
KEY = "clave-actual"
OLD_KEY = "clave-previa"
PHONE = "+573001234567"
EMAIL = "ana@empresa.co"
NEW_LEAD = "/nuevo Ana Pérez; 300 123 4567; ana@empresa.co; Empresa SAS; Plan anual"


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


def _cb(user_tg: int, data: str) -> Update:
    uid = next(_next_update)
    return Update(
        update_id=uid,
        user_id=user_tg,
        chat_id=user_tg,
        chat_type="private",
        callback_data=data,
        callback_id=f"cb{uid}",
    )


def _file(user_tg: int, file_id: str, kind: FileKind, size: int | None = None) -> Update:
    return Update(
        update_id=next(_next_update),
        user_id=user_tg,
        chat_id=user_tg,
        chat_type="private",
        file=FileRef(file_id=file_id, size=size, kind=kind),
    )


def run(bot: CrmBot, u: Update) -> None:
    asyncio.run(bot.process_update(u))


def _lead(
    db: CrmDatabase, user_id: int | None, state: LeadState = LeadState.NEW, **fields: Any
) -> int:
    base: dict[str, Any] = {"name": "Ana Pérez", "phone_e164": PHONE, "email": EMAIL}
    base.update(fields)
    with db.tx() as tx:
        return repo.insert_lead(tx, assigned_user_id=user_id, state=state, now=START, fields=base)


def _authorized_lead(
    db: CrmDatabase,
    user_id: int | None,
    *,
    consent_status: AuthStatus = AuthStatus.AUTHORIZED,
    auth_status: AuthStatus = AuthStatus.AUTHORIZED,
    **fields: Any,
) -> int:
    """Lead con `auth_status` y su evidencia de consentimiento (configurables)."""
    lead_id = _lead(db, user_id, **fields)
    with db.tx() as tx:
        repo.update_lead(tx, lead_id, {"auth_status": auth_status.value}, now=START)
        repo.insert_consent(
            tx,
            lead_id=lead_id,
            status=consent_status,
            medium="correo",
            at=START,
            actor_user_id=user_id or 1,
        )
    return lead_id


def _rows(db: CrmDatabase, sql: str) -> list[dict[str, Any]]:
    with db.read() as conn:
        return [dict(r) for r in conn.execute(sql).fetchall()]


def _lead_row(db: CrmDatabase, lead_id: int) -> dict[str, Any]:
    return _rows(db, f"SELECT * FROM crm_leads WHERE id = {lead_id}")[0]  # noqa: S608


def _authorize_with_file(bot: CrmBot, tg: FakeTelegram, user_tg: int, kind: FileKind) -> None:
    tg.files["ev1"] = b"firma del titular"
    run(bot, _msg(user_tg, "/autorizacion L-0001"))
    run(bot, _file(user_tg, "ev1", kind))


# --- Autorización con evidencia (VCRM-065, 138) ------------------------------------------


@pytest.mark.parametrize("kind", ["photo", "document"])
def test_vcrm065_vcrm138_evidence_after_command_registers_authorization(
    bot: CrmBot,
    tg: FakeTelegram,
    db: CrmDatabase,
    store: LocalFileStore,
    users: dict[str, User],
    kind: FileKind,
) -> None:
    lead_id = _lead(db, users["com"].id)
    run(bot, _msg(COM_TG, "/autorizacion L-0001"))
    assert "Adjunte" in tg.sent[-1].text
    tg.files["ev1"] = b"firma del titular"
    run(bot, _file(COM_TG, "ev1", kind))
    attachments = _rows(db, "SELECT * FROM crm_attachments")
    assert len(attachments) == 1
    att = attachments[0]
    assert (att["lead_id"], att["kind"], att["author_user_id"]) == (
        lead_id,
        "authorization",
        users["com"].id,
    )
    assert att["sha256"] == hashlib.sha256(b"firma del titular").hexdigest()
    with store.open(att["storage_key"]) as fh:
        assert fh.read() == b"firma del titular"
    consents = _rows(db, "SELECT * FROM crm_consents")
    assert len(consents) == 1
    consent = consents[0]
    assert consent["lead_id"] == lead_id
    assert consent["status"] == AuthStatus.AUTHORIZED
    assert consent["medium"] == compliance.AUTH_MEDIUM
    assert consent["actor_user_id"] == users["com"].id
    assert consent["at"] == to_iso(START)
    assert consent["attachment_id"] == att["id"]
    assert consent["notice_version"] is None and consent["purposes"] is None  # J-04
    assert _lead_row(db, lead_id)["auth_status"] == AuthStatus.AUTHORIZED
    assert "autorizada" in tg.sent[-1].text
    assert "L-0001" in tg.sent[-1].text


def test_vcrm138_evidence_after_yes_button_registers_authorization(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    run(bot, _msg(COM_TG, NEW_LEAD))
    run(bot, _cb(COM_TG, "v1:conf:1:si"))
    tg.files["ev1"] = b"captura"
    run(bot, _file(COM_TG, "ev1", "photo"))
    assert _lead_row(db, 1)["auth_status"] == AuthStatus.AUTHORIZED
    assert [r["kind"] for r in _rows(db, "SELECT kind FROM crm_attachments")] == ["authorization"]
    assert len(_rows(db, "SELECT * FROM crm_consents")) == 1


def test_vcrm138_cto_may_register_authorization_on_any_lead(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id)
    _authorize_with_file(bot, tg, CTO_TG, "document")
    assert _lead_row(db, lead_id)["auth_status"] == AuthStatus.AUTHORIZED
    assert (
        _rows(db, "SELECT actor_user_id FROM crm_consents")[0]["actor_user_id"] == users["cto"].id
    )


# --- Medios no válidos (VCRM-139) -----------------------------------------------------------


def test_vcrm139_text_instead_of_file_is_not_registered(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id)
    run(bot, _msg(COM_TG, "/autorizacion L-0001"))
    run(bot, _msg(COM_TG, "El titular aceptó por teléfono"))
    assert _lead_row(db, lead_id)["auth_status"] == AuthStatus.UNAUTHORIZED
    assert _rows(db, "SELECT * FROM crm_consents") == []
    assert _rows(db, "SELECT * FROM crm_attachments") == []
    assert tg.sent[-1].text.startswith(compliance.NOT_REGISTERED)
    assert compliance.VALID_MEDIA in tg.sent[-1].text


def test_vcrm139_voice_note_is_not_registered(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, store: LocalFileStore, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id)
    _authorize_with_file(bot, tg, COM_TG, "voice")
    assert _lead_row(db, lead_id)["auth_status"] == AuthStatus.UNAUTHORIZED
    assert _rows(db, "SELECT * FROM crm_consents") == []
    assert _rows(db, "SELECT * FROM crm_attachments") == []
    assert compliance.VALID_MEDIA in tg.sent[-1].text
    assert not store.base_dir.exists() or not any(p.is_file() for p in store.base_dir.rglob("*"))


def test_vcrm139_failed_download_is_not_registered(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id)
    run(bot, _msg(COM_TG, "/autorizacion L-0001"))
    run(bot, _file(COM_TG, "inexistente", "document"))  # el doble no tiene el archivo
    assert _lead_row(db, lead_id)["auth_status"] == AuthStatus.UNAUTHORIZED
    assert _rows(db, "SELECT * FROM crm_consents") == []
    assert compliance.NOT_REGISTERED in tg.sent[-1].text


def test_vcrm139_too_large_file_is_not_registered(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id)
    run(bot, _msg(COM_TG, "/autorizacion L-0001"))
    run(bot, _file(COM_TG, "grande", "document", size=MAX_ATTACHMENT_BYTES + 1))
    assert _lead_row(db, lead_id)["auth_status"] == AuthStatus.UNAUTHORIZED
    assert "20 MB" in tg.sent[-1].text
    assert compliance.NOT_REGISTERED in tg.sent[-1].text


def test_vcrm139_revoked_status_is_kept_when_medium_is_invalid(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id)
    with db.tx() as tx:
        repo.update_lead(tx, lead_id, {"auth_status": AuthStatus.REVOKED.value}, now=START)
    run(bot, _msg(COM_TG, "/autorizacion L-0001"))
    run(bot, _msg(COM_TG, "sí acepta"))
    assert _lead_row(db, lead_id)["auth_status"] == AuthStatus.REVOKED


@pytest.mark.parametrize(
    "text", ["/autorizacion", "/autorizacion 42", "/autorizacion L-0001 extra"]
)
def test_authorization_command_bad_format(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User], text: str
) -> None:
    _lead(db, users["com"].id)
    run(bot, _msg(COM_TG, text))
    assert "Formato no válido" in tg.sent[-1].text
    with db.read() as conn:
        assert repo.get_pending_input(conn, users["com"].id, START) is None


def test_authorization_command_unknown_lead(
    bot: CrmBot, tg: FakeTelegram, users: dict[str, User]
) -> None:
    run(bot, _msg(COM_TG, "/autorizacion L-0099"))
    assert "no existe" in tg.sent[-1].text


@pytest.mark.parametrize("who", [COM2_TG, LAW_TG])
def test_authorization_command_denied_for_foreign_lead_or_lawyer(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User], who: int
) -> None:
    _lead(db, users["com"].id)
    run(bot, _msg(who, "/autorizacion L-0001"))
    assert "No tiene permiso" in tg.sent[-1].text
    with db.read() as conn:
        assert repo.audit_rows(conn)[-1]["action"] == AuditAction.PERMISSION_DENIED
        assert repo.get_pending_input(conn, users["com2"].id, START) is None


def test_evidence_denied_if_lead_reassigned_meanwhile(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id)
    run(bot, _msg(COM_TG, "/autorizacion L-0001"))
    with db.tx() as tx:
        repo.set_assignee(tx, lead_id, users["com2"].id)
    tg.files["ev1"] = b"x"
    run(bot, _file(COM_TG, "ev1", "document"))
    assert "No tiene permiso" in tg.sent[-1].text
    assert _rows(db, "SELECT * FROM crm_consents") == []
    assert _rows(db, "SELECT * FROM crm_attachments") == []


def test_evidence_without_file_store_is_not_registered(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    bot = CrmBot(db, tg, FakeClock(START).now, fingerprint_keys=(KEY,))
    lead_id = _lead(db, users["com"].id)
    tg.files["ev1"] = b"x"
    run(bot, _msg(COM_TG, "/autorizacion L-0001"))
    run(bot, _file(COM_TG, "ev1", "document"))
    assert _lead_row(db, lead_id)["auth_status"] == AuthStatus.UNAUTHORIZED
    assert compliance.VALID_MEDIA in tg.sent[-1].text


# --- Baja (VCRM-070, 095, 164) -----------------------------------------------------------


def test_vcrm070_opt_out_applies_immediately(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, store: LocalFileStore, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id, state=LeadState.CONTACTED)
    _authorize_with_file(bot, tg, COM_TG, "document")
    evidence_before = _rows(db, "SELECT * FROM crm_attachments")
    consent_before = _rows(db, "SELECT * FROM crm_consents")
    with db.tx() as tx:
        repo.create_confirmation(
            tx, kind="accept", lead_id=lead_id, user_id=users["com"].id, now=START
        )
        repo.set_pending_input(
            tx, user_id=users["com2"].id, kind="reject_other", now=START, lead_id=lead_id
        )

    run(bot, _msg(COM_TG, "/baja L-0001; llamada telefónica"))

    lead = _lead_row(db, lead_id)
    assert lead["state"] == LeadState.OPTED_OUT
    assert lead["final_state_at"] == to_iso(START)
    assert lead["auth_status"] == AuthStatus.REVOKED
    # Lista de supresión: solo huella, fecha y medio; nunca el contacto en claro (VCRM-095).
    suppression = _rows(db, "SELECT * FROM crm_suppression ORDER BY fingerprint")
    assert {r["fingerprint"] for r in suppression} == {
        fingerprint(KEY, PHONE),
        fingerprint(KEY, EMAIL),
    }
    assert all(r["at"] == to_iso(START) for r in suppression)
    assert all(r["medium"] == "llamada telefónica" for r in suppression)
    dump = repr(suppression)
    assert PHONE not in dump and EMAIL not in dump and "3001234567" not in dump
    # Confirmaciones y entradas pendientes canceladas.
    statuses = [r["status"] for r in _rows(db, "SELECT status FROM crm_confirmations")]
    assert statuses == ["cancelled"]
    with db.read() as conn:
        assert repo.get_pending_input(conn, users["com2"].id, START) is None
    # Registro con fecha y medio: consentimiento «revocada» y evento de estado.
    consents = _rows(db, "SELECT * FROM crm_consents ORDER BY id")
    assert consents[0] == consent_before[0]  # evidencia previa intacta (VCRM-164)
    revoked = consents[1]
    assert revoked["status"] == AuthStatus.REVOKED
    assert revoked["medium"] == "llamada telefónica"
    assert revoked["at"] == to_iso(START)
    assert revoked["actor_user_id"] == users["com"].id
    events = _rows(db, "SELECT * FROM crm_lead_events WHERE kind = 'state'")
    assert (events[-1]["old_value"], events[-1]["new_value"]) == ("contacted", "opted_out")
    # La evidencia de autorización (registro y archivo) sigue intacta (VCRM-164).
    assert _rows(db, "SELECT * FROM crm_attachments") == evidence_before
    with store.open(evidence_before[0]["storage_key"]) as fh:
        assert fh.read() == b"firma del titular"
    assert "baja" in tg.sent[-1].text and "L-0001" in tg.sent[-1].text
    with db.read() as conn:
        assert repo.audit_rows(conn)[-1]["action"] == AuditAction.LEAD_UPDATED


def test_vcrm070_opt_out_with_only_phone_adds_one_fingerprint(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    _lead(db, users["com"].id, email=None)
    run(bot, _msg(CTO_TG, "/baja L-0001; correo"))
    assert [r["fingerprint"] for r in _rows(db, "SELECT * FROM crm_suppression")] == [
        fingerprint(KEY, PHONE)
    ]


def test_vcrm070_repeated_opt_out_is_rejected(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    _lead(db, users["com"].id)
    run(bot, _msg(COM_TG, "/baja L-0001; llamada"))
    run(bot, _msg(COM_TG, "/baja L-0001; llamada"))
    assert "No se aplicó" in tg.sent[-1].text
    assert len(_rows(db, "SELECT * FROM crm_consents")) == 1


def test_vcrm070_opt_out_shared_fingerprint_is_not_duplicated(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    _lead(db, users["com"].id)
    _lead(db, users["com"].id)
    run(bot, _msg(COM_TG, "/baja L-0001; llamada"))
    run(bot, _msg(COM_TG, "/baja L-0002; correo"))
    assert len(_rows(db, "SELECT * FROM crm_suppression")) == 2
    assert _lead_row(db, 2)["state"] == LeadState.OPTED_OUT


@pytest.mark.parametrize("text", ["/baja", "/baja L-0001", "/baja L-0001;", "/baja 7; llamada"])
def test_opt_out_bad_format(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User], text: str
) -> None:
    _lead(db, users["com"].id)
    run(bot, _msg(COM_TG, text))
    assert "Formato no válido" in tg.sent[-1].text
    assert _lead_row(db, 1)["state"] == LeadState.NEW


def test_opt_out_unknown_lead(bot: CrmBot, tg: FakeTelegram, users: dict[str, User]) -> None:
    run(bot, _msg(COM_TG, "/baja L-0042; llamada"))
    assert "no existe" in tg.sent[-1].text


@pytest.mark.parametrize("who", [COM2_TG, LAW_TG])
def test_opt_out_denied_without_permission(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User], who: int
) -> None:
    _lead(db, users["com"].id, state=LeadState.CONTACTED)
    run(bot, _msg(who, "/baja L-0001; llamada"))
    assert "No tiene permiso" in tg.sent[-1].text
    assert _lead_row(db, 1)["state"] == LeadState.CONTACTED
    assert _rows(db, "SELECT * FROM crm_suppression") == []


def test_opt_out_blocks_new_registration_of_same_contact(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    _lead(db, users["com"].id)
    run(bot, _msg(COM_TG, "/baja L-0001; llamada"))
    run(bot, _msg(COM2_TG, NEW_LEAD))
    assert "solicitó no ser contactado" in tg.sent[-1].text


# --- Guarda de contacto comercial (VCRM-071) ----------------------------------------------


def _lead_of(conn: Any, lead_id: int) -> Any:
    lead = repo.get_lead(conn, lead_id)
    assert lead is not None
    return lead


def test_vcrm067_guarda_exige_autorizacion(db: CrmDatabase, users: dict[str, User]) -> None:
    authorized = _authorized_lead(db, users["com"].id)
    unauthorized = _lead(db, users["com"].id, phone_e164="+573009990000", email="otro@x.co")
    # «autorizada» sin evidencia de consentimiento tampoco vale (VCRM-067: autorización vigente).
    no_evidence = _lead(db, users["com"].id, phone_e164="+573008880000", email="sin@x.co")
    with db.tx() as tx:
        repo.update_lead(tx, no_evidence, {"auth_status": AuthStatus.AUTHORIZED.value}, now=START)
    with db.read() as conn:
        keys = (KEY, OLD_KEY)
        assert compliance.may_contact_commercially(conn, _lead_of(conn, authorized), keys) is True
        assert (
            compliance.may_contact_commercially(conn, _lead_of(conn, unauthorized), keys) is False
        )
        assert compliance.may_contact_commercially(conn, _lead_of(conn, no_evidence), keys) is False


def test_vcrm067_revocada_niega(db: CrmDatabase, users: dict[str, User]) -> None:
    # Revocada: el estado del lead y la última fila de consentimiento lo dicen.
    revoked = _authorized_lead(
        db, users["com"].id, auth_status=AuthStatus.REVOKED, consent_status=AuthStatus.REVOKED
    )
    # Estado inconsistente: el lead sigue «autorizada» pero lo último registrado es una revocatoria.
    stale = _authorized_lead(
        db,
        users["com"].id,
        consent_status=AuthStatus.REVOKED,
        phone_e164="+573007770000",
        email="rev@x.co",
    )
    with db.read() as conn:
        for lead_id in (revoked, stale):
            lead = _lead_of(conn, lead_id)
            assert compliance.may_contact_commercially(conn, lead, (KEY,)) is False
            # Quien revocó no recibe una nueva solicitud de autorización.
            assert compliance.may_request_authorization(conn, lead, (KEY,)) is False


def test_vcrm067_solicitud_no_exige_autorizacion(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = _lead(db, users["com"].id)
    with db.read() as conn:
        lead = _lead_of(conn, lead_id)
        assert compliance.may_contact_commercially(conn, lead, (KEY,)) is False
        assert compliance.may_request_authorization(conn, lead, (KEY,)) is True


def test_vcrm071_may_contact_true_for_clean_authorized_lead(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = _authorized_lead(db, users["com"].id)
    with db.read() as conn:
        lead = _lead_of(conn, lead_id)
        assert compliance.may_contact_commercially(conn, lead, (KEY, OLD_KEY)) is True
        assert compliance.may_request_authorization(conn, lead, (KEY, OLD_KEY)) is True


def test_vcrm071_suppressed_fingerprint_blocks_other_lead(
    bot: CrmBot, tg: FakeTelegram, db: CrmDatabase, users: dict[str, User]
) -> None:
    _lead(db, users["com"].id)
    other = _authorized_lead(db, users["com2"].id, phone_e164=None)  # mismo correo, otro lead
    run(bot, _msg(COM_TG, "/baja L-0001; llamada"))
    with db.read() as conn:
        lead = repo.get_lead(conn, other)
        assert lead is not None and lead.state == LeadState.NEW
        assert compliance.may_contact_commercially(conn, lead, (KEY, OLD_KEY)) is False
        assert compliance.may_request_authorization(conn, lead, (KEY, OLD_KEY)) is False


def test_vcrm071_fingerprint_with_previous_key_still_blocks(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = _authorized_lead(db, users["com"].id, email=None)
    with db.tx() as tx:
        repo.add_suppression(tx, fingerprint(OLD_KEY, PHONE), at=START, medium="llamada")
    with db.read() as conn:
        lead = repo.get_lead(conn, lead_id)
        assert lead is not None
        assert compliance.may_contact_commercially(conn, lead, (KEY, OLD_KEY)) is False
        assert compliance.may_request_authorization(conn, lead, (KEY, OLD_KEY)) is False


@pytest.mark.parametrize(
    "changes",
    [
        {"state": LeadState.OPTED_OUT.value},
        {"commercial_block": 1},
        {"suppressed_at": to_iso(START)},
    ],
)
def test_vcrm071_baja_block_or_suppressed_lead_cannot_be_contacted(
    db: CrmDatabase, users: dict[str, User], changes: dict[str, Any]
) -> None:
    lead_id = _authorized_lead(db, users["com"].id, phone_e164=None, email=None)
    with db.tx() as tx:
        repo.update_lead(tx, lead_id, changes, now=START)
    with db.read() as conn:
        lead = repo.get_lead(conn, lead_id)
        assert lead is not None
        assert compliance.may_contact_commercially(conn, lead, (KEY,)) is False
        assert compliance.may_request_authorization(conn, lead, (KEY,)) is False


# --- Correos solo a usuarios autorizados ---------------------------------------------------


def test_system_email_only_goes_to_authorized_users(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"].id)
    with db.tx() as tx:
        for user in users.values():
            enqueue_critical(
                tx,
                kind="prueba",
                channel=Channel.EMAIL,
                recipient_user_id=user.id,
                lead_id=lead_id,
                subject="Lead",
                body=f"Lead L-0001 ({EMAIL})",
                key=f"k{user.id}",
                now=START,
            )
        enqueue_critical(  # destinatario inexistente: nunca se resuelve al correo del lead
            tx,
            kind="prueba",
            channel=Channel.EMAIL,
            recipient_user_id=lead_id + 999,
            lead_id=lead_id,
            subject="Lead",
            body="x",
            key="k-x",
            now=START,
        )
    mail = FakeEmailSender()
    worker = OutboxWorker(db, FakeTelegram(), mail, FakeClock(START).now)
    asyncio.run(worker.deliver_due())
    allowed = {u.email for u in users.values()}
    assert mail.attempts
    assert {m.to for m in mail.attempts} <= allowed
    assert EMAIL not in {m.to for m in mail.attempts}
