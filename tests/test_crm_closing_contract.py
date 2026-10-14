"""Contrato y firma: subida, devolución, forma especial, envío a firma y resultado (spec 004 C2)."""

import asyncio
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from crm_support import FakeClock, FakeEmailSender, FakeTelegram
from jerico.crm import closing_repo as crepo
from jerico.crm import repo
from jerico.crm.bot import CrmBot
from jerico.crm.closing_contract import (
    BAD_FILE,
    HASH_CHANGED,
    NO_SIGNATURE,
    SIGN_NO,
    SIGN_OK,
    SIGN_UNAVAILABLE,
    WRONG_STATE,
    contract_sweep,
    register_contract,
)
from jerico.crm.closing_flow import ClosingContext, register_closing
from jerico.crm.db import CrmDatabase
from jerico.crm.files import LocalFileStore
from jerico.crm.model import LeadState, Role, User
from jerico.crm.parsing import build_callback
from jerico.crm.ports import FileRef, Update
from jerico.crm.signature import DryRunSignature, SignatureError, SignRequest, SignStatus
from jerico.crm.team import DENIED

START = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
CTO_TG, COM_TG, COM2_TG, LAW_TG = 1000, 2000, 2001, 3000
PDF = b"%PDF-1.7 contrato de prueba"
OFFER = "/oferta {lead}; pago contado; linea Chatbot x1 @12000000"


class FakeSign:
    def __init__(self) -> None:
        self.sent: list[SignRequest] = []
        self.fail: SignatureError | None = None
        self.state = "pending"
        self.status_error: SignatureError | None = None

    async def send(self, req: SignRequest) -> str:
        if self.fail is not None:
            raise self.fail
        self.sent.append(req)
        return f"sub-{req.contract_id}"

    async def status(self, external_id: str) -> SignStatus:
        if self.status_error is not None:
            raise self.status_error
        if self.state == "completed":
            return SignStatus("completed", b"%PDF firmado", b"%PDF auditoria")
        return SignStatus(self.state)  # type: ignore[arg-type]


class Env:
    def __init__(
        self, tmp_path: Path, *, dry_run: bool, signature: object | None, files: bool = True
    ) -> None:
        self.db = CrmDatabase(tmp_path / "crm.db")
        self.tg = FakeTelegram()
        self.clock = FakeClock(START)
        self.store = LocalFileStore(tmp_path / "files")
        self.mail = FakeEmailSender()
        self.ctx = ClosingContext(
            dry_run=dry_run,
            files=self.store if files else None,
            signature=signature,  # type: ignore[arg-type]
            validity_days=15,
            telegram=self.tg,
            email=self.mail,
            clock=self.clock.now,
        )
        self.bot = CrmBot(self.db, self.tg, self.clock.now, files=self.store)
        register_closing(self.bot, self.ctx)
        register_contract(self.bot, self.db, self.ctx)
        with self.db.tx() as tx:
            self.cto = repo.insert_user(
                tx, telegram_id=CTO_TG, role=Role.CTO, email="c@k.co", now=START
            )
            self.com = repo.insert_user(
                tx, telegram_id=COM_TG, role=Role.COMMERCIAL, email="m@k.co", now=START
            )
            self.com2 = repo.insert_user(
                tx, telegram_id=COM2_TG, role=Role.COMMERCIAL, email="m2@k.co", now=START
            )
            self.law = repo.insert_user(
                tx, telegram_id=LAW_TG, role=Role.LAWYER, email="l@k.co", now=START
            )
        self.uid = 0

    def lead(self, owner: User | None = None) -> int:
        owner = owner or self.com
        with self.db.tx() as tx:
            lead_id = repo.insert_lead(
                tx,
                assigned_user_id=owner.id,
                state=LeadState.ACCEPTED,
                now=START,
                fields={
                    "client_type": "empresa",
                    "name": "Ana Pérez",
                    "company": "Andina SAS",
                    "doc_type": "NIT",
                    "doc_number": "900123456",
                    "legal_rep": "Carlos Gómez",
                    "phone_e164": "+573001234567",
                    "email": "contacto@andina.co",
                    "service": "Chatbot",
                    "agreed_value": "12.000.000 COP",
                    "start_term": "abril",
                },
            )
            tx.execute(
                "UPDATE crm_leads SET auth_status='authorized', ever_accepted=1 WHERE id=?",
                (lead_id,),
            )
        return lead_id

    def update(self, tg_id: int, **kw: object) -> Update:
        self.uid += 1
        return Update(update_id=self.uid, user_id=tg_id, chat_id=tg_id, chat_type="private", **kw)  # type: ignore[arg-type]

    def say(self, tg_id: int, text: str) -> None:
        asyncio.run(self.bot.process_update(self.update(tg_id, text=text)))

    def press(self, tg_id: int, data: str) -> None:
        asyncio.run(
            self.bot.process_update(self.update(tg_id, callback_data=data, callback_id="cb"))
        )

    def send_file(self, tg_id: int, content: bytes, *, kind: str = "document") -> None:
        file_id = f"f{self.uid}"
        self.tg.files[file_id] = content
        asyncio.run(
            self.bot.process_update(
                self.update(tg_id, file=FileRef(file_id=file_id, size=len(content), kind=kind))  # type: ignore[arg-type]
            )
        )

    def texts(self, chat: int) -> list[str]:
        return [s.text for s in self.tg.sent if s.chat_id == chat]

    def outbox(self, kind: str) -> list[dict[str, object]]:
        with self.db.read() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM crm_outbox WHERE kind=?", (kind,))]

    def contract(self, lead_id: int):  # type: ignore[no-untyped-def]
        with self.db.read() as conn:
            row = conn.execute(
                "SELECT id FROM crm_packages WHERE lead_id=? ORDER BY id DESC LIMIT 1", (lead_id,)
            ).fetchone()
            return crepo.contract_for_package(conn, int(row["id"]))

    def sent_package(self, lead_id: int) -> None:
        self.say(COM_TG, OFFER.format(lead=f"L-{lead_id:04d}"))
        with self.db.read() as conn:
            pid = crepo.live_package(conn, lead_id).id  # type: ignore[union-attr]
        self.press(COM_TG, build_callback("pkgok", str(pid)))

    def uploaded(self, lead_id: int) -> None:
        self.sent_package(lead_id)
        self.say(LAW_TG, f"/subircontrato L-{lead_id:04d}")
        self.send_file(LAW_TG, PDF)

    def close(self) -> None:
        self.db.close()


@pytest.fixture
def make_env(tmp_path: Path) -> Iterator[object]:
    made: list[Env] = []

    def build(
        *, dry_run: bool = False, signature: object | None = "default", files: bool = True
    ) -> Env:
        sig = FakeSign() if signature == "default" else signature
        env = Env(tmp_path, dry_run=dry_run, signature=sig, files=files)
        made.append(env)
        return env

    yield build
    for env in made:
        env.close()


def _ref(lead_id: int) -> str:
    return f"L-{lead_id:04d}"


# --- Subida del contrato (abogado) ------------------------------------------------------------


def test_vcrmc10_lawyer_uploads_the_contract_and_stakeholders_are_told(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id = env.lead()
    env.sent_package(lead_id)
    env.say(LAW_TG, f"/subircontrato {_ref(lead_id)}")
    assert "PDF o DOCX" in env.texts(LAW_TG)[-1]
    env.send_file(LAW_TG, PDF)
    contract = env.contract(lead_id)
    digest = hashlib.sha256(PDF).hexdigest()
    assert contract.status == "contract_uploaded" and contract.sha256 == digest
    assert contract.uploaded_by == env.law.id and contract.file_path
    with env.store.open(contract.file_path) as handle:
        assert handle.read() == PDF
    notified = {r["recipient_user_id"] for r in env.outbox("contract_uploaded")}
    assert notified == {env.com.id, env.cto.id}
    assert any(digest[:12] in text for text in env.texts(LAW_TG))


def test_docx_files_are_accepted_and_other_files_rejected(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id = env.lead()
    env.sent_package(lead_id)
    env.say(LAW_TG, f"/subircontrato {_ref(lead_id)}")
    env.send_file(LAW_TG, b"MZ\x90\x00 ejecutable")
    assert env.texts(LAW_TG)[-1] == BAD_FILE
    assert env.contract(lead_id).status == "package_sent"
    env.say(LAW_TG, f"/subircontrato {_ref(lead_id)}")
    env.send_file(LAW_TG, b"PK\x03\x04 docx")
    assert env.contract(lead_id).status == "contract_uploaded"


def test_photo_instead_of_document_and_missing_file_are_refused(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id = env.lead()
    env.sent_package(lead_id)
    env.say(LAW_TG, f"/subircontrato {_ref(lead_id)}")
    env.send_file(LAW_TG, PDF, kind="photo")
    assert env.texts(LAW_TG)[-1] == BAD_FILE
    env.say(LAW_TG, f"/subircontrato {_ref(lead_id)}")
    env.say(LAW_TG, "ya lo subo")  # texto en vez de archivo
    assert "Necesito el contrato" in env.texts(LAW_TG)[-1]
    assert env.contract(lead_id).status == "package_sent"


def test_download_failure_is_reported_and_nothing_is_saved(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id = env.lead()
    env.sent_package(lead_id)
    env.say(LAW_TG, f"/subircontrato {_ref(lead_id)}")
    asyncio.run(
        env.bot.process_update(
            env.update(LAW_TG, file=FileRef(file_id="inexistente", size=10, kind="document"))
        )
    )
    assert "No pude descargar" in env.texts(LAW_TG)[-1]
    assert env.contract(lead_id).file_path is None


def test_replacing_the_contract_deletes_the_old_file_and_requires_new_approval(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id = env.lead()
    env.uploaded(lead_id)
    first = env.contract(lead_id).file_path
    env.say(LAW_TG, f"/subircontrato {_ref(lead_id)}")
    env.send_file(LAW_TG, PDF + b" v2")
    second = env.contract(lead_id)
    assert second.file_path != first and second.approved_by is None
    with pytest.raises(Exception):  # noqa: B017,PT011 - el archivo anterior ya no existe
        env.store.open(first).read()  # type: ignore[arg-type]


def test_only_the_lawyer_handles_contracts_and_only_sent_packages(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id = env.lead()
    env.say(LAW_TG, f"/subircontrato {_ref(lead_id)}")  # sin paquete enviado
    assert env.texts(LAW_TG)[-1] == "Ese caso no tiene un paquete enviado esperando contrato."
    env.sent_package(lead_id)
    for who in (COM_TG, CTO_TG, COM2_TG):
        env.say(who, f"/subircontrato {_ref(lead_id)}")
        env.say(who, f"/devolver {_ref(lead_id)} motivo")
        env.say(who, f"/formaespecial {_ref(lead_id)}")
    assert env.contract(lead_id).status == "package_sent"
    assert (
        env.texts(COM2_TG)[-1] == "No tienes acceso a ese lead." or DENIED in env.texts(COM2_TG)[-1]
    )


# --- Devolución y forma especial -----------------------------------------------------------


def test_vcrmc11_return_cancels_the_contract_and_reopens_the_package(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id = env.lead()
    env.sent_package(lead_id)
    env.say(LAW_TG, f"/devolver {_ref(lead_id)}")
    assert "Indica el motivo" in env.texts(LAW_TG)[-1]
    env.say(LAW_TG, f"/devolver {_ref(lead_id)} falta la cláusula de confidencialidad")
    contract = env.contract(lead_id)
    assert contract.status == "cancelled" and "confidencialidad" in (contract.return_reason or "")
    with env.db.read() as conn:
        assert crepo.live_package(conn, lead_id) is None
    assert any("confidencialidad" in str(r["body"]) for r in env.outbox("contract_returned"))
    env.say(COM_TG, OFFER.format(lead=_ref(lead_id)))  # puede regenerar el paquete
    with env.db.read() as conn:
        assert crepo.live_package(conn, lead_id).version == 2  # type: ignore[union-attr]


def test_vcrmf03_special_form_stops_the_flow(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id = env.lead()
    env.uploaded(lead_id)
    env.say(LAW_TG, f"/formaespecial {_ref(lead_id)}")
    assert env.contract(lead_id).status == "special_form"
    env.say(COM_TG, f"/firma {_ref(lead_id)}")
    assert "estado" in env.texts(COM_TG)[-1]
    assert env.outbox("contract_special_form")


# --- Aprobación y envío a firma -------------------------------------------------------------


def test_vcrmc12_tick_sends_the_exact_uploaded_file_to_signature(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    sign: FakeSign = env.ctx.signature  # type: ignore[assignment]
    lead_id = env.lead()
    env.uploaded(lead_id)
    env.say(COM_TG, f"/firma {_ref(lead_id)}")
    prompt = env.tg.sent[-1]
    assert hashlib.sha256(PDF).hexdigest()[:12] in prompt.text
    assert [b.text for row in prompt.buttons or [] for b in row] == [
        "✅ Enviar a firma",
        "❌ Cancelar",
    ]
    contract = env.contract(lead_id)
    assert sign.sent == []  # nada sale antes del ✅
    env.press(COM_TG, build_callback(SIGN_OK, str(contract.id)))
    assert [r.document for r in sign.sent] == [PDF]
    request = sign.sent[0]
    assert request.signer_email == "contacto@andina.co" and request.signer_name == "Carlos Gómez"
    assert request.document_name == f"contrato-{_ref(lead_id)}.pdf"
    after = env.contract(lead_id)
    assert after.status == "sent_for_signature" and after.approved_by == env.com.id
    assert after.expires_at is not None and after.expires_at > "2026-03-16"
    assert "enviado a firma" in env.texts(COM_TG)[-1]
    with env.db.read() as conn:
        signature = crepo.signature_for_contract(conn, contract.id)
    assert signature is not None and signature.external_id == f"sub-{contract.id}"


def test_double_press_sends_once(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    sign: FakeSign = env.ctx.signature  # type: ignore[assignment]
    lead_id = env.lead()
    env.uploaded(lead_id)
    contract = env.contract(lead_id)
    env.press(COM_TG, build_callback(SIGN_OK, str(contract.id)))
    env.press(COM_TG, build_callback(SIGN_OK, str(contract.id)))
    assert len(sign.sent) == 1


def test_vcrmc12_a_file_changed_on_disk_is_not_sent(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    sign: FakeSign = env.ctx.signature  # type: ignore[assignment]
    lead_id = env.lead()
    env.uploaded(lead_id)
    contract = env.contract(lead_id)
    (env.store.base_dir / contract.file_path).write_bytes(b"%PDF-1.7 ALTERADO")  # type: ignore[operator]
    env.press(COM_TG, build_callback(SIGN_OK, str(contract.id)))
    assert env.texts(COM_TG)[-1] == HASH_CHANGED and sign.sent == []
    assert env.contract(lead_id).status == "contract_uploaded"


def test_provider_failure_keeps_the_contract_retryable(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    sign: FakeSign = env.ctx.signature  # type: ignore[assignment]
    lead_id = env.lead()
    env.uploaded(lead_id)
    contract = env.contract(lead_id)
    sign.fail = SignatureError("http")
    env.press(COM_TG, build_callback(SIGN_OK, str(contract.id)))
    assert env.texts(COM_TG)[-1] == SIGN_UNAVAILABLE
    assert env.contract(lead_id).status == "contract_uploaded"
    sign.fail = None
    env.press(COM_TG, build_callback(SIGN_OK, str(contract.id)))  # reintento permitido
    assert len(sign.sent) == 1 and env.contract(lead_id).status == "sent_for_signature"


def test_cancel_button_changes_nothing(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id = env.lead()
    env.uploaded(lead_id)
    env.press(COM_TG, build_callback(SIGN_NO, str(env.contract(lead_id).id)))
    assert "cancelado" in env.texts(COM_TG)[-1]
    assert env.contract(lead_id).status == "contract_uploaded"


def test_permissions_on_signature_actions(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    sign: FakeSign = env.ctx.signature  # type: ignore[assignment]
    lead_id = env.lead()
    env.uploaded(lead_id)
    contract = env.contract(lead_id)
    for who in (COM2_TG, LAW_TG):
        env.say(who, f"/firma {_ref(lead_id)}")
        env.press(who, build_callback(SIGN_OK, str(contract.id)))
        env.press(who, build_callback(SIGN_NO, str(contract.id)))
    assert sign.sent == [] and env.contract(lead_id).status == "contract_uploaded"
    env.press(CTO_TG, build_callback(SIGN_OK, str(contract.id)))  # el CTO sí puede
    assert len(sign.sent) == 1


def test_guards_before_signature(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id = env.lead()
    env.sent_package(lead_id)
    env.say(COM_TG, f"/firma {_ref(lead_id)}")  # aún sin contrato subido
    assert "estado" in env.texts(COM_TG)[-1]
    env.say(LAW_TG, f"/subircontrato {_ref(lead_id)}")
    env.send_file(LAW_TG, PDF)
    with env.db.tx() as tx:
        tx.execute("UPDATE crm_leads SET email=NULL WHERE id=?", (lead_id,))
    env.say(COM_TG, f"/firma {_ref(lead_id)}")
    assert "no tiene correo" in env.texts(COM_TG)[-1]
    with env.db.tx() as tx:
        tx.execute(
            "UPDATE crm_leads SET email='a@b.co', suppressed_at='2026-03-01T00:00:00Z' WHERE id=?",
            (lead_id,),
        )
    env.say(COM_TG, f"/firma {_ref(lead_id)}")
    assert "ya no admite envíos" in env.texts(COM_TG)[-1]
    env.press(COM_TG, build_callback(SIGN_OK, str(env.contract(lead_id).id)))
    assert "ya no admite envíos" in env.texts(COM_TG)[-1]


def test_without_a_signature_provider_the_flow_stops_before_sending(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(signature=None)
    lead_id = env.lead()
    env.uploaded(lead_id)
    env.say(COM_TG, f"/firma {_ref(lead_id)}")
    assert env.texts(COM_TG)[-1] == NO_SIGNATURE
    env.press(COM_TG, build_callback(SIGN_OK, str(env.contract(lead_id).id)))
    assert env.texts(COM_TG)[-1] == NO_SIGNATURE
    assert env.contract(lead_id).status == "contract_uploaded"


def test_malformed_buttons_are_closed(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    env.press(COM_TG, build_callback(SIGN_OK, "999"))
    env.press(COM_TG, build_callback(SIGN_NO, "abc"))
    assert env.texts(COM_TG) == ["Esa solicitud ya no está pendiente."] * 2


# --- DRY_RUN ---------------------------------------------------------------------------------


def test_dry_run_never_reaches_the_provider_and_can_be_simulated_by_the_cto(make_env) -> None:  # type: ignore[no-untyped-def]
    real = FakeSign()
    env = make_env(dry_run=True, signature=DryRunSignature(real))
    lead_id = env.lead()
    env.uploaded(lead_id)
    contract = env.contract(lead_id)
    env.say(COM_TG, f"/firma {_ref(lead_id)}")
    assert "DRY_RUN" in env.tg.sent[-1].text
    env.press(COM_TG, build_callback(SIGN_OK, str(contract.id)))
    assert real.sent == [] and "[DRY_RUN]" in env.texts(COM_TG)[-1]
    assert env.contract(lead_id).status == "sent_for_signature"
    env.say(COM_TG, f"/firmaprueba {_ref(lead_id)}")  # no es del comercial
    assert env.contract(lead_id).status == "sent_for_signature"
    env.say(CTO_TG, f"/firmaprueba {_ref(lead_id)}")
    assert env.contract(lead_id).status == "signed"
    assert "Firma simulada" in env.texts(CTO_TG)[-1]
    env.say(CTO_TG, f"/firmaprueba {_ref(lead_id)}")  # ya firmado
    assert "estado" in env.texts(CTO_TG)[-1]


def test_firmaprueba_is_disabled_outside_dry_run(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(dry_run=False)
    lead_id = env.lead()
    env.uploaded(lead_id)
    env.say(CTO_TG, f"/firmaprueba {_ref(lead_id)}")
    assert env.texts(CTO_TG)[-1] == DENIED


# --- Resultado de la firma y vencimiento -----------------------------------------------------


def _sent_for_signature(env: Env) -> tuple[int, int]:
    lead_id = env.lead()
    env.uploaded(lead_id)
    contract = env.contract(lead_id)
    env.press(COM_TG, build_callback(SIGN_OK, str(contract.id)))
    return lead_id, contract.id


def test_vcrmc15_completed_signature_is_archived_and_everyone_is_told(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    sign: FakeSign = env.ctx.signature  # type: ignore[assignment]
    lead_id, contract_id = _sent_for_signature(env)
    sign.state = "completed"
    asyncio.run(contract_sweep(env.db, env.ctx, START + timedelta(minutes=10)))
    contract = env.contract(lead_id)
    assert contract.status == "signed" and contract.signed_at is not None
    with env.db.read() as conn:
        signature = crepo.signature_for_contract(conn, contract_id)
    assert signature is not None and signature.status == "completed"
    assert signature.evidence_sha256 == hashlib.sha256(b"%PDF firmado").hexdigest()
    with env.store.open(signature.evidence_path) as handle:  # type: ignore[arg-type]
        assert handle.read() == b"%PDF firmado"
    assert {r["recipient_user_id"] for r in env.outbox("contract_signed")} == {
        env.com.id,
        env.cto.id,
    }
    assert "ganado" in str(env.outbox("contract_signed")[0]["body"])


def test_polling_is_throttled_and_pending_changes_nothing(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    sign: FakeSign = env.ctx.signature  # type: ignore[assignment]
    lead_id, _ = _sent_for_signature(env)
    asyncio.run(contract_sweep(env.db, env.ctx, START + timedelta(minutes=10)))
    sign.state = "completed"
    asyncio.run(
        contract_sweep(env.db, env.ctx, START + timedelta(minutes=11))
    )  # <5 min: no consulta
    assert env.contract(lead_id).status == "sent_for_signature"
    asyncio.run(contract_sweep(env.db, env.ctx, START + timedelta(minutes=16)))
    assert env.contract(lead_id).status == "signed"


@pytest.mark.parametrize(("state", "expected"), [("declined", "declined"), ("expired", "expired")])
def test_declined_or_expired_by_the_provider(make_env, state: str, expected: str) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    sign: FakeSign = env.ctx.signature  # type: ignore[assignment]
    lead_id, _ = _sent_for_signature(env)
    sign.state = state
    asyncio.run(contract_sweep(env.db, env.ctx, START + timedelta(minutes=10)))
    assert env.contract(lead_id).status == expected
    assert env.outbox(f"contract_{state}")


def test_provider_errors_while_polling_are_swallowed(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    sign: FakeSign = env.ctx.signature  # type: ignore[assignment]
    lead_id, _ = _sent_for_signature(env)
    sign.status_error = SignatureError("network")
    asyncio.run(contract_sweep(env.db, env.ctx, START + timedelta(minutes=10)))
    assert env.contract(lead_id).status == "sent_for_signature"


def test_vcrmc14_unsigned_contract_expires_after_the_validity_window(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id, _ = _sent_for_signature(env)
    asyncio.run(contract_sweep(env.db, env.ctx, START + timedelta(days=14)))
    assert env.contract(lead_id).status == "sent_for_signature"
    asyncio.run(contract_sweep(env.db, env.ctx, START + timedelta(days=16)))
    assert env.contract(lead_id).status == "expired"
    assert {r["recipient_user_id"] for r in env.outbox("contract_expired")} == {
        env.com.id,
        env.cto.id,
    }


def test_sweep_without_provider_still_expires_contracts(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(signature=None)
    asyncio.run(contract_sweep(env.db, env.ctx, START + timedelta(days=30)))


def test_completed_status_without_documents_does_not_close_the_contract(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    sign: FakeSign = env.ctx.signature  # type: ignore[assignment]
    lead_id, _ = _sent_for_signature(env)

    async def broken(external_id: str) -> SignStatus:
        return SignStatus("completed")  # sin documento firmado

    sign.status = broken  # type: ignore[method-assign]
    asyncio.run(contract_sweep(env.db, env.ctx, START + timedelta(minutes=10)))
    assert env.contract(lead_id).status in ("sent_for_signature", "expired")


# --- Ramas límite ----------------------------------------------------------------------------


def test_commands_without_a_case_ask_for_it(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    env.say(LAW_TG, "/subircontrato")
    assert "Indica el caso" in env.texts(LAW_TG)[-1]


def test_actions_after_signature_was_sent_are_out_of_state(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id, _ = _sent_for_signature(env)
    for command in ("/subircontrato", "/devolver", "/formaespecial"):
        env.say(LAW_TG, f"{command} {_ref(lead_id)} motivo")
        assert env.texts(LAW_TG)[-1] == WRONG_STATE
    assert env.contract(lead_id).status == "sent_for_signature"


def test_upload_after_the_package_was_replaced_is_refused(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id = env.lead()
    env.sent_package(lead_id)
    env.say(LAW_TG, f"/subircontrato {_ref(lead_id)}")
    env.say(COM_TG, OFFER.format(lead=_ref(lead_id)))  # el comercial rehace el paquete
    env.send_file(LAW_TG, PDF)
    assert env.texts(LAW_TG)[-1] == "Ese caso no tiene un paquete enviado esperando contrato."


def test_upload_after_special_form_is_out_of_state(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id = env.lead()
    env.sent_package(lead_id)
    env.say(LAW_TG, f"/subircontrato {_ref(lead_id)}")
    with env.db.tx() as tx:
        tx.execute("UPDATE crm_contracts SET status='special_form'")
    env.send_file(LAW_TG, PDF)
    assert env.texts(LAW_TG)[-1] == WRONG_STATE


def test_upload_without_a_file_store_fails_cleanly(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(files=False)
    lead_id = env.lead()
    env.sent_package(lead_id)
    env.say(LAW_TG, f"/subircontrato {_ref(lead_id)}")
    env.send_file(LAW_TG, PDF)
    assert "No pude descargar" in env.texts(LAW_TG)[-1]


def test_cancel_button_with_an_unknown_contract_is_closed(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    env.press(COM_TG, build_callback(SIGN_NO, "999"))
    assert env.texts(COM_TG) == ["Esa solicitud ya no está pendiente."]


def test_firmaprueba_with_unknown_case(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(dry_run=True, signature=DryRunSignature())
    env.say(CTO_TG, "/firmaprueba L-9999")
    assert "Indica el caso" in env.texts(CTO_TG)[-1]


def test_an_already_claimed_signature_key_blocks_a_second_send(make_env) -> None:  # type: ignore[no-untyped-def]
    from jerico.crm.idempotency import claim, make_key

    env = make_env()
    sign: FakeSign = env.ctx.signature  # type: ignore[assignment]
    lead_id = env.lead()
    env.uploaded(lead_id)
    contract = env.contract(lead_id)
    with env.db.tx() as tx:
        assert claim(tx, make_key("signature_send", contract.id), START)
    env.press(COM_TG, build_callback(SIGN_OK, str(contract.id)))
    assert env.texts(COM_TG)[-1] == "Esa solicitud ya no está pendiente." and sign.sent == []
