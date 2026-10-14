"""Bot del abogado (@Jericoo_law_bot): acceso, /start, descarga, entrega automática (spec 004)."""

import asyncio
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crm_support import FakeClock, FakeEmailSender, FakeTelegram, make_settings
from jerico.crm import closing_repo as crepo
from jerico.crm import repo
from jerico.crm.bot import CrmBot
from jerico.crm.closing_contract import register_contract
from jerico.crm.closing_flow import ClosingContext, contract_route, register_closing
from jerico.crm.config import parse_allowed_ids
from jerico.crm.db import CrmDatabase
from jerico.crm.dryrun import DryRunEmailSender
from jerico.crm.files import LocalFileStore
from jerico.crm.legal_bot import build_legal_bot
from jerico.crm.model import LeadState, Role
from jerico.crm.outbox import OutboxWorker
from jerico.crm.parsing import build_callback
from jerico.crm.ports import FileRef, Update

START = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
CTO_TG, COM_TG, LAW_TG, STRANGER_TG = 1000, 2000, 3000, 9999
PDF = b"%PDF-1.7 contrato final"
OFFER = "/oferta {lead}; pago contado; linea Chatbot x1 @12000000{route}"


class Env:
    def __init__(
        self, tmp_path: Path, *, dry_run: bool = False, allowed: str = str(LAW_TG)
    ) -> None:
        self.db = CrmDatabase(tmp_path / "crm.db")
        self.main_tg = FakeTelegram()
        self.legal_tg = FakeTelegram()
        self.clock = FakeClock(START)
        self.store = LocalFileStore(tmp_path / "files")
        self.inner_mail = FakeEmailSender()
        self.mail = DryRunEmailSender(self.inner_mail, "cto@k.co") if dry_run else self.inner_mail
        self.ctx = ClosingContext(
            dry_run=dry_run,
            files=self.store,
            telegram=self.main_tg,
            email=self.mail,  # type: ignore[arg-type]
            clock=self.clock.now,
        )
        self.main = CrmBot(self.db, self.main_tg, self.clock.now, files=self.store)
        register_closing(self.main, self.ctx)
        register_contract(self.main, self.db, self.ctx)
        settings = make_settings(legal_allowed_ids=allowed)
        self.legal = build_legal_bot(
            self.db, self.legal_tg, self.clock.now, settings, self.ctx, self.store
        )
        with self.db.tx() as tx:
            self.cto = repo.insert_user(
                tx, telegram_id=CTO_TG, role=Role.CTO, email="cto@k.co", now=START
            )
            self.com = repo.insert_user(
                tx, telegram_id=COM_TG, role=Role.COMMERCIAL, email="com@k.co", now=START
            )
            self.law = repo.insert_user(
                tx, telegram_id=LAW_TG, role=Role.LAWYER, email="law@k.co", now=START
            )
        self.uid = 0

    def lead(self, **extra: str) -> int:
        fields = {
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
            **extra,
        }
        with self.db.tx() as tx:
            lead_id = repo.insert_lead(
                tx, assigned_user_id=self.com.id, state=LeadState.ACCEPTED, now=START, fields=fields
            )
            tx.execute(
                "UPDATE crm_leads SET auth_status='authorized', ever_accepted=1 WHERE id=?",
                (lead_id,),
            )
        return lead_id

    def _update(self, tg_id: int, **kw: object) -> Update:
        self.uid += 1
        return Update(update_id=self.uid, user_id=tg_id, chat_id=tg_id, chat_type="private", **kw)  # type: ignore[arg-type]

    def say(self, bot: CrmBot, tg_id: int, text: str) -> None:
        asyncio.run(bot.process_update(self._update(tg_id, text=text)))

    def press(self, bot: CrmBot, tg_id: int, data: str) -> None:
        asyncio.run(bot.process_update(self._update(tg_id, callback_data=data, callback_id="c")))

    def upload(self, content: bytes = PDF, tg_id: int = LAW_TG) -> None:
        fid = f"f{self.uid}"
        self.legal_tg.files[fid] = content
        asyncio.run(
            self.legal.process_update(
                self._update(tg_id, file=FileRef(file_id=fid, size=len(content), kind="document"))
            )
        )

    def sent_package(self, lead_id: int, route: str = "") -> None:
        self.say(self.main, COM_TG, OFFER.format(lead=f"L-{lead_id:04d}", route=route))
        with self.db.read() as conn:
            pid = crepo.live_package(conn, lead_id).id  # type: ignore[union-attr]
        self.press(self.main, COM_TG, build_callback("pkgok", str(pid)))

    def texts(self, tg: FakeTelegram, chat: int) -> list[str]:
        return [s.text for s in tg.sent if s.chat_id == chat]

    def docs(self, tg: FakeTelegram, chat: int) -> list[object]:
        return [s for s in tg.sent if s.chat_id == chat and s.document is not None]

    def close(self) -> None:
        self.db.close()


@pytest.fixture
def make_env(tmp_path: Path) -> Iterator[object]:
    made: list[Env] = []

    def build(**kw: object) -> Env:
        env = Env(tmp_path, **kw)  # type: ignore[arg-type]
        made.append(env)
        return env

    yield build
    for env in made:
        env.close()


def _ref(lead_id: int) -> str:
    return f"L-{lead_id:04d}"


# --- Configuración ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "valid", "rejected"),
    [
        ("", set(), 0),
        ("123", {123}, 0),
        (" 123 , 456 ,", {123, 456}, 0),
        ("123,abc,-5,0,4.5", {123}, 4),
    ],
)
def test_parse_allowed_ids(raw: str, valid: set[int], rejected: int) -> None:
    ids, bad = parse_allowed_ids(raw)
    assert ids == valid and len(bad) == rejected
    assert all("abc" not in b for b in bad)  # nunca se repite el valor


# --- Acceso -----------------------------------------------------------------------------------


def test_stranger_start_gets_only_their_id_and_nothing_else(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    env.say(env.legal, STRANGER_TG, "/start")
    env.say(env.legal, STRANGER_TG, "/casos")
    texts = env.texts(env.legal_tg, STRANGER_TG)
    assert len(texts) == 1 and str(STRANGER_TG) in texts[0] and "CTO" in texts[0]
    with env.db.read() as conn:
        denied = conn.execute(
            "SELECT COUNT(*) FROM crm_audit WHERE action='access_denied'"
        ).fetchone()[0]
    assert denied == 2


def test_registration_mode_with_no_allowed_ids_lets_nobody_in(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(allowed="")
    env.say(env.legal, LAW_TG, "/start")  # ya está en la tabla, pero aún no en la lista blanca
    env.say(env.legal, LAW_TG, "/casos")
    texts = env.texts(env.legal_tg, LAW_TG)
    assert len(texts) == 1 and "Tu ID de Telegram es" in texts[0]


def test_allowed_but_not_registered_as_lawyer_is_still_denied(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(allowed=f"{LAW_TG},{STRANGER_TG}")
    env.say(env.legal, STRANGER_TG, "/casos")
    assert env.texts(env.legal_tg, STRANGER_TG) == []


def test_registered_commercial_cannot_use_the_legal_bot_even_if_allowed(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(allowed=f"{LAW_TG},{COM_TG}")
    lead_id = env.lead()
    env.sent_package(lead_id)
    env.say(env.legal, COM_TG, "/casos")
    assert "L-" not in " ".join(env.texts(env.legal_tg, COM_TG))


def test_authorized_lawyer_gets_help_and_the_minimal_command_set(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    env.say(env.legal, LAW_TG, "/start")
    assert "/subircontrato" in env.texts(env.legal_tg, LAW_TG)[-1]
    env.say(env.legal, LAW_TG, "/lista")  # los comandos de ventas no existen en este bot
    env.say(env.legal, LAW_TG, "/nuevo Ana")
    assert (
        env.texts(env.legal_tg, LAW_TG)[-2:]
        == ["Orden no reconocida. Revisa que el comando esté bien escrito."] * 2
    )


# --- Lectura y descarga -----------------------------------------------------------------------


def test_lawyer_reads_downloads_and_sees_the_case_list(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id = env.lead()
    env.sent_package(lead_id)
    env.say(env.legal, LAW_TG, "/casos")
    assert _ref(lead_id) in env.texts(env.legal_tg, LAW_TG)[-1]
    env.say(env.legal, LAW_TG, f"/paquete {_ref(lead_id)}")
    assert "Total: 12.000.000 COP" in env.texts(env.legal_tg, LAW_TG)[-1]
    env.say(env.legal, LAW_TG, f"/descargar {_ref(lead_id)}")
    (doc,) = env.docs(env.legal_tg, LAW_TG)
    assert doc.document.name == f"paquete-{_ref(lead_id)}-v1.md"  # type: ignore[attr-defined]
    assert b"Total: 12.000.000 COP" in doc.content  # type: ignore[attr-defined]
    assert not doc.document.exists()  # type: ignore[attr-defined]  # el temporal se borra


def test_download_edge_cases(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id = env.lead()
    env.say(env.legal, LAW_TG, "/descargar")
    env.say(env.legal, LAW_TG, f"/descargar {_ref(lead_id)}")  # sin paquete enviado
    assert env.texts(env.legal_tg, LAW_TG)[-1] == "Ese caso no tiene un paquete enviado."
    assert "Indica el caso" in env.texts(env.legal_tg, LAW_TG)[-2]
    env.sent_package(lead_id)
    env.say(env.main, COM_TG, f"/descargar {_ref(lead_id)}")  # no existe en el bot principal
    assert env.docs(env.main_tg, COM_TG) == []


def test_download_without_file_store_says_it_could_not_send(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id = env.lead()
    env.sent_package(lead_id)
    object.__setattr__(env.ctx, "files", None)
    env.say(env.legal, LAW_TG, f"/descargar {_ref(lead_id)}")
    assert "No pude enviarte el archivo" in env.texts(env.legal_tg, LAW_TG)[-1]


# --- Entrega automática del contrato ------------------------------------------------------------


def test_upload_delivers_the_file_to_the_commercial_by_default(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id = env.lead()
    env.sent_package(lead_id)
    env.say(env.legal, LAW_TG, f"/subircontrato {_ref(lead_id)}")
    env.upload()
    (doc,) = env.docs(env.main_tg, COM_TG)
    assert doc.content == PDF and doc.document.name == f"contrato-{_ref(lead_id)}.pdf"  # type: ignore[attr-defined]
    assert env.inner_mail.attachments == []  # por defecto NO va al cliente
    assert "enviado al comercial" in env.texts(env.legal_tg, LAW_TG)[-1]
    assert hashlib.sha256(PDF).hexdigest()[:12] in " ".join(env.texts(env.legal_tg, LAW_TG))


def test_route_cliente_also_emails_the_client_and_dry_run_redirects_to_the_cto(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(dry_run=True)
    lead_id = env.lead()
    env.sent_package(lead_id, route="; entrega cliente")
    with env.db.read() as conn:
        assert contract_route(conn, lead_id) == "cliente"
    env.say(env.legal, LAW_TG, f"/subircontrato {_ref(lead_id)}")
    env.upload()
    (mail,) = env.inner_mail.attachments
    assert mail.to == "cto@k.co" and mail.subject.startswith("[DRY_RUN → contacto@andina.co]")
    assert mail.content == PDF and mail.filename == f"contrato-{_ref(lead_id)}.pdf"
    assert "enviado al cliente por correo" in env.texts(env.legal_tg, LAW_TG)[-1]
    assert len(env.docs(env.main_tg, COM_TG)) == 1  # el comercial siempre lo recibe


def test_route_cliente_without_dry_run_goes_to_the_real_address(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(dry_run=False)
    lead_id = env.lead()
    env.sent_package(lead_id, route="; entrega cliente")
    env.say(env.legal, LAW_TG, f"/subircontrato {_ref(lead_id)}")
    env.upload()
    assert [m.to for m in env.inner_mail.attachments] == ["contacto@andina.co"]


def test_same_file_is_delivered_once_but_a_new_version_is_delivered_again(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id = env.lead()
    env.sent_package(lead_id)
    for content in (PDF, PDF, PDF + b" v2"):
        env.say(env.legal, LAW_TG, f"/subircontrato {_ref(lead_id)}")
        env.upload(content)
    assert [d.content for d in env.docs(env.main_tg, COM_TG)] == [PDF, PDF + b" v2"]  # type: ignore[attr-defined]


def test_failed_deliveries_release_the_key_and_tell_the_lawyer(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id = env.lead()
    env.sent_package(lead_id, route="; entrega cliente")
    env.inner_mail.fail_next("contacto@andina.co")
    env.main_tg.fail_next(COM_TG)
    env.say(env.legal, LAW_TG, f"/subircontrato {_ref(lead_id)}")
    env.upload()
    last = env.texts(env.legal_tg, LAW_TG)[-1]
    assert "el comercial no recibió el archivo" in last and "no pude enviarlo al cliente" in last
    env.say(env.legal, LAW_TG, f"/subircontrato {_ref(lead_id)}")
    env.upload()  # el mismo archivo se puede reintentar
    assert "enviado al comercial" in env.texts(env.legal_tg, LAW_TG)[-1]
    assert [m.to for m in env.inner_mail.attachments] == ["contacto@andina.co"]


def test_missing_channels_are_reported_not_crashed(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id = env.lead()
    env.sent_package(lead_id, route="; entrega cliente")
    object.__setattr__(env.ctx, "telegram", None)
    object.__setattr__(env.ctx, "email", None)
    env.say(env.legal, LAW_TG, f"/subircontrato {_ref(lead_id)}")
    env.upload()
    last = env.texts(env.legal_tg, LAW_TG)[-1]
    assert "sin canal" in last and "no pude enviarlo al cliente" in last


def test_client_delivery_is_skipped_when_the_lead_is_no_longer_open(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id = env.lead()
    env.sent_package(lead_id, route="; entrega cliente")
    with env.db.tx() as tx:
        tx.execute("UPDATE crm_leads SET commercial_block=1 WHERE id=?", (lead_id,))
    env.say(env.legal, LAW_TG, f"/subircontrato {_ref(lead_id)}")
    env.upload()
    assert env.inner_mail.attachments == [] and len(env.docs(env.main_tg, COM_TG)) == 1


def test_invalid_delivery_choice_is_explained(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id = env.lead()
    env.say(env.main, COM_TG, OFFER.format(lead=_ref(lead_id), route="; entrega whatsapp"))
    assert "«comercial» o «cliente»" in env.texts(env.main_tg, COM_TG)[-1]


# --- Avisos al abogado por su propio bot ---------------------------------------------------------


def test_outbox_sends_lawyer_notices_through_the_legal_bot(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id = env.lead()
    env.sent_package(lead_id)  # encola Telegram para el abogado (dry_run=False)
    worker = OutboxWorker(
        env.db, env.main_tg, env.inner_mail, env.clock.now, lawyer_telegram=env.legal_tg
    )
    asyncio.run(worker.deliver_due())
    assert any("Paquete de cierre" in t for t in env.texts(env.legal_tg, LAW_TG))
    assert env.texts(env.main_tg, LAW_TG) == []
    assert [m.to for m in env.inner_mail.sent] == ["law@k.co"]


def test_outbox_without_a_legal_bot_keeps_using_the_main_bot(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id = env.lead()
    env.sent_package(lead_id)
    asyncio.run(OutboxWorker(env.db, env.main_tg, env.inner_mail, env.clock.now).deliver_due())
    assert any("Paquete de cierre" in t for t in env.texts(env.main_tg, LAW_TG))


def test_download_of_a_lead_that_never_reached_acceptance_is_denied(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    lead_id = env.lead()
    with env.db.tx() as tx:
        tx.execute("UPDATE crm_leads SET ever_accepted=0 WHERE id=?", (lead_id,))
    env.say(env.legal, LAW_TG, f"/descargar {_ref(lead_id)}")
    assert env.docs(env.legal_tg, LAW_TG) == []
