"""Flujo de cierre: /oferta, ✅/❌, entrega al abogado y comandos del abogado (spec 004 C1)."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crm_support import FakeClock, FakeTelegram
from jerico.crm import closing_repo as crepo
from jerico.crm import repo
from jerico.crm.bot import CrmBot
from jerico.crm.closing_flow import (
    NO_BASIS,
    NO_LAWYER,
    NOT_ACCEPTED,
    OFFER_EXAMPLE,
    PKG_CANCEL,
    PKG_SEND,
    ClosingContext,
    OfferError,
    OfferInput,
    parse_offer,
    register_closing,
)
from jerico.crm.db import CrmDatabase
from jerico.crm.model import LeadState, Role, User
from jerico.crm.parsing import build_callback
from jerico.crm.ports import Update

START = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
CTO_TG, COM_TG, COM2_TG, LAW_TG = 1000, 2000, 2001, 3000
OFFER = (
    "/oferta {lead}; moneda COP; pago 50 % anticipo; linea Chatbot x1 @12000000; "
    "linea Soporte x2 @500.000; vigencia 2026-04-30; condiciones Soporte 8x5"
)


@pytest.fixture
def db(tmp_path: Path) -> Iterator[CrmDatabase]:
    database = CrmDatabase(tmp_path / "crm.db")
    yield database
    database.close()


@pytest.fixture
def tg() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def users(db: CrmDatabase) -> dict[str, User]:
    with db.tx() as tx:
        return {
            "cto": repo.insert_user(
                tx, telegram_id=CTO_TG, role=Role.CTO, email="c@k.co", now=START
            ),
            "com": repo.insert_user(
                tx, telegram_id=COM_TG, role=Role.COMMERCIAL, email="m@k.co", now=START
            ),
            "com2": repo.insert_user(
                tx, telegram_id=COM2_TG, role=Role.COMMERCIAL, email="m2@k.co", now=START
            ),
            "law": repo.insert_user(
                tx, telegram_id=LAW_TG, role=Role.LAWYER, email="law@k.co", now=START
            ),
        }


def _bot(db: CrmDatabase, tg: FakeTelegram, *, dry_run: bool = True) -> CrmBot:
    bot = CrmBot(db, tg, FakeClock(START).now)
    register_closing(bot, ClosingContext(dry_run=dry_run))
    return bot


def _lead(db: CrmDatabase, owner: User, **fields: str) -> int:
    base = {
        "client_type": "empresa",
        "name": "Ana Pérez",
        "company": "Distribuciones Andina SAS",
        "doc_type": "NIT",
        "doc_number": "900123456",
        "legal_rep": "Carlos Gómez",
        "phone_e164": "+573001234567",
        "email": "contacto@andina.co",
        "service": "Chatbot de ventas",
        "agreed_value": "12.000.000 COP",
        "start_term": "1 de abril",
    }
    with db.tx() as tx:
        lead_id = repo.insert_lead(
            tx,
            assigned_user_id=owner.id,
            state=LeadState.ACCEPTED,
            now=START,
            fields={**base, **fields},
        )
        tx.execute(
            "UPDATE crm_leads SET auth_status='authorized', ever_accepted=1 WHERE id=?", (lead_id,)
        )
    return lead_id


_UID = iter(range(1, 10_000))


def _say(bot: CrmBot, tg_id: int, text: str) -> None:
    asyncio.run(
        bot.process_update(
            Update(
                update_id=next(_UID), user_id=tg_id, chat_id=tg_id, chat_type="private", text=text
            )
        )
    )


def _press(bot: CrmBot, tg_id: int, data: str) -> None:
    asyncio.run(
        bot.process_update(
            Update(
                update_id=next(_UID),
                user_id=tg_id,
                chat_id=tg_id,
                chat_type="private",
                callback_data=data,
                callback_id="cb",
            )
        )
    )


def _texts(tg: FakeTelegram, chat: int) -> list[str]:
    return [s.text for s in tg.sent if s.chat_id == chat]


def _count(db: CrmDatabase, sql: str) -> int:
    with db.read() as conn:
        return int(conn.execute(sql).fetchone()[0])


def _ref(lead_id: int) -> str:
    return f"L-{lead_id:04d}"


# --- parse_offer --------------------------------------------------------------------------


def test_parse_offer_ok() -> None:
    parsed = parse_offer(OFFER.format(lead="L-0042"))
    assert isinstance(parsed, OfferInput)
    assert parsed.lead_id == 42 and parsed.currency == "COP"
    assert parsed.lines == (("Chatbot", 1, 12_000_000), ("Soporte", 2, 500_000))
    assert parsed.valid_until == "2026-04-30" and parsed.special_conditions == "Soporte 8x5"


@pytest.mark.parametrize(
    "text",
    [
        "/oferta",
        "/oferta xyz; pago contado; linea A x1 @1",
        "/oferta L-0001; linea A x1 @1",  # falta pago
        "/oferta L-0001; pago contado",  # falta línea
        "/oferta L-0001; pago contado; linea A x0 @1",
        "/oferta L-0001; pago contado; linea A x1 @abc",
        "/oferta L-0001; pago contado; linea A x1 @1; moneda PESOS",
        "/oferta L-0001; pago contado; linea A x1 @1; vigencia mañana",
        "/oferta L-0001; pago contado; linea A x1 @1; regalo sorpresa",
    ],
)
def test_parse_offer_errors_explain_and_show_an_example(text: str) -> None:
    parsed = parse_offer(text)
    assert isinstance(parsed, OfferError) and parsed.message


def test_parse_offer_defaults_currency_and_tolerates_empty_segments() -> None:
    parsed = parse_offer("/oferta L-0001; pago contado; ; linea A x1 @1.000; condiciones")
    assert isinstance(parsed, OfferInput)
    assert parsed.currency == "COP" and parsed.special_conditions is None
    assert OFFER_EXAMPLE.startswith("/oferta")


# --- Armado y confirmación ------------------------------------------------------------------


def test_vcrmc03_offer_builds_a_draft_and_asks_for_confirmation(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    bot = _bot(db, tg)
    _say(bot, COM_TG, OFFER.format(lead=_ref(lead_id)))
    sent = tg.sent[-1]
    assert sent.chat_id == COM_TG and "Total: 13.000.000 COP" in sent.text
    labels = [button.text for row in sent.buttons or [] for button in row]
    assert labels == ["✅ Enviar al abogado", "❌ Cancelar"]
    with db.read() as conn:
        pkg = crepo.live_package(conn, lead_id)
    assert pkg is not None and pkg.status == "draft"
    assert _count(db, "SELECT COUNT(*) FROM crm_outbox WHERE kind='package_delivery'") == 0


def test_vcrmc03_nothing_goes_out_without_the_tick(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    bot = _bot(db, tg)
    _say(bot, COM_TG, OFFER.format(lead=_ref(lead_id)))
    assert _count(db, "SELECT COUNT(*) FROM crm_outbox") == 0
    with db.read() as conn:
        pkg = crepo.live_package(conn, lead_id)
    assert pkg is not None
    _press(bot, COM_TG, build_callback(PKG_CANCEL, str(pkg.id)))
    with db.read() as conn:
        assert crepo.live_package(conn, lead_id) is None
        assert crepo.get_package(conn, pkg.id).status == "cancelled"  # type: ignore[union-attr]
    assert _count(db, "SELECT COUNT(*) FROM crm_outbox") == 0


def _draft(db: CrmDatabase, tg: FakeTelegram, bot: CrmBot, lead_id: int, who: int = COM_TG) -> int:
    _say(bot, who, OFFER.format(lead=_ref(lead_id)))
    with db.read() as conn:
        pkg = crepo.live_package(conn, lead_id)
    assert pkg is not None
    return pkg.id


def test_vcrmc20_confirmed_package_reaches_the_lawyer_by_both_channels(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    bot = _bot(db, tg, dry_run=False)
    pid = _draft(db, tg, bot, lead_id)
    _press(bot, COM_TG, build_callback(PKG_SEND, str(pid)))
    with db.read() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM crm_outbox ORDER BY id").fetchall()]
        contract = crepo.contract_for_package(conn, pid)
        pkg = crepo.get_package(conn, pid)
    assert {(r["channel"], r["recipient_user_id"]) for r in rows} == {
        ("telegram", users["law"].id),
        ("email", users["law"].id),
    }
    assert pkg is not None and pkg.status == "sent" and pkg.confirmed_by == users["com"].id
    assert contract is not None and contract.status == "package_sent"
    email = next(r for r in rows if r["channel"] == "email")
    assert email["subject"] == f"Paquete de cierre {_ref(lead_id)} (v1)"
    assert f"paquete-{_ref(lead_id)}-v1.md" in email["body"]
    assert "Distribuciones Andina SAS" in email["body"]


def test_vcrmc22_dry_run_redirects_the_telegram_copy_to_the_cto(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    bot = _bot(db, tg, dry_run=True)
    pid = _draft(db, tg, bot, lead_id)
    _press(bot, COM_TG, build_callback(PKG_SEND, str(pid)))
    with db.read() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM crm_outbox").fetchall()]
    telegram = [r for r in rows if r["channel"] == "telegram"]
    assert [r["recipient_user_id"] for r in telegram] == [users["cto"].id]
    assert telegram[0]["body"].startswith("[DRY_RUN → abogado]")
    assert "DRY_RUN" in _texts(tg, COM_TG)[-1]


def test_idempotent_double_press_sends_once(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    bot = _bot(db, tg, dry_run=False)
    pid = _draft(db, tg, bot, lead_id)
    data = build_callback(PKG_SEND, str(pid))
    _press(bot, COM_TG, data)
    _press(bot, COM_TG, data)
    assert _count(db, "SELECT COUNT(*) FROM crm_outbox WHERE kind='package_delivery'") == 2
    assert _count(db, "SELECT COUNT(*) FROM crm_contracts") == 1


def test_vcrmc21_no_active_lawyer_means_nothing_leaves(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    with db.tx() as tx:
        tx.execute("UPDATE crm_users SET active=0 WHERE role='lawyer'")
    lead_id = _lead(db, users["com"])
    bot = _bot(db, tg)
    pid = _draft(db, tg, bot, lead_id)
    _press(bot, COM_TG, build_callback(PKG_SEND, str(pid)))
    assert _texts(tg, COM_TG)[-1] == NO_LAWYER
    assert _count(db, "SELECT COUNT(*) FROM crm_outbox") == 0
    with db.read() as conn:
        assert crepo.get_package(conn, pid).status == "draft"  # type: ignore[union-attr]


def test_vcrmc02_incomplete_handoff_blocks_the_package(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"], email="")
    with db.tx() as tx:
        tx.execute("UPDATE crm_leads SET email=NULL WHERE id=?", (lead_id,))
    bot = _bot(db, tg)
    _say(bot, COM_TG, OFFER.format(lead=_ref(lead_id)))
    assert "Faltan datos del cliente" in tg.sent[-1].text and "correo" in tg.sent[-1].text
    assert _count(db, "SELECT COUNT(*) FROM crm_packages") == 0


def test_vcrmp03_no_authorization_blocks_until_the_lawyer_confirms_a_basis(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    with db.tx() as tx:
        tx.execute("UPDATE crm_leads SET auth_status='unauthorized' WHERE id=?", (lead_id,))
    bot = _bot(db, tg)
    _say(bot, COM_TG, OFFER.format(lead=_ref(lead_id)))
    assert tg.sent[-1].text == NO_BASIS
    _say(bot, LAW_TG, f"/basejuridica {_ref(lead_id)}")
    _say(bot, COM_TG, OFFER.format(lead=_ref(lead_id)))
    assert "Total:" in tg.sent[-1].text
    with db.read() as conn:
        pkg = crepo.live_package(conn, lead_id)
    assert pkg is not None and pkg.legal_basis == "lawyer_confirmed"


def test_only_accepted_leads_have_packages(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    with db.tx() as tx:
        tx.execute("UPDATE crm_leads SET state='contacted' WHERE id=?", (lead_id,))
    _say(_bot(db, tg), COM_TG, OFFER.format(lead=_ref(lead_id)))
    assert tg.sent[-1].text == NOT_ACCEPTED


def test_vcrmc04_editing_after_sending_supersedes_and_cancels_the_contract(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    bot = _bot(db, tg, dry_run=False)
    first = _draft(db, tg, bot, lead_id)
    _press(bot, COM_TG, build_callback(PKG_SEND, str(first)))
    _say(bot, COM_TG, OFFER.format(lead=_ref(lead_id)).replace("12000000", "13000000"))
    with db.read() as conn:
        old = crepo.get_package(conn, first)
        new = crepo.live_package(conn, lead_id)
        old_contract = crepo.contract_for_package(conn, first)
    assert old is not None and old.status == "superseded"
    assert new is not None and new.version == 2 and new.status == "draft"
    assert old_contract is not None and old_contract.status == "cancelled"


def test_stale_data_between_draft_and_tick_is_refused(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    bot = _bot(db, tg, dry_run=False)
    pid = _draft(db, tg, bot, lead_id)
    with db.tx() as tx:
        tx.execute("UPDATE crm_leads SET service='Otro servicio' WHERE id=?", (lead_id,))
    _press(bot, COM_TG, build_callback(PKG_SEND, str(pid)))
    assert "cambiaron" in tg.sent[-1].text
    assert _count(db, "SELECT COUNT(*) FROM crm_outbox") == 0


# --- Permisos -----------------------------------------------------------------------------


def test_foreign_commercial_and_lawyer_cannot_manage_the_package(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    bot = _bot(db, tg)
    _say(bot, COM2_TG, OFFER.format(lead=_ref(lead_id)))
    _say(bot, LAW_TG, OFFER.format(lead=_ref(lead_id)))
    assert _count(db, "SELECT COUNT(*) FROM crm_packages") == 0
    pid = _draft(db, tg, bot, lead_id)
    _press(bot, COM2_TG, build_callback(PKG_SEND, str(pid)))
    _press(bot, LAW_TG, build_callback(PKG_SEND, str(pid)))
    _press(bot, COM2_TG, build_callback(PKG_CANCEL, str(pid)))
    with db.read() as conn:
        assert crepo.get_package(conn, pid).status == "draft"  # type: ignore[union-attr]
    assert _count(db, "SELECT COUNT(*) FROM crm_outbox") == 0


def test_cto_can_manage_any_package(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    bot = _bot(db, tg, dry_run=False)
    pid = _draft(db, tg, bot, lead_id, who=CTO_TG)
    _press(bot, CTO_TG, build_callback(PKG_SEND, str(pid)))
    with db.read() as conn:
        assert crepo.get_package(conn, pid).status == "sent"  # type: ignore[union-attr]


def test_dead_or_malformed_buttons_say_the_proposal_is_closed(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    bot = _bot(db, tg)
    _press(bot, COM_TG, build_callback(PKG_SEND, "999"))
    _press(bot, COM_TG, build_callback(PKG_CANCEL, "abc"))
    assert [t for t in _texts(tg, COM_TG)] == ["Esa propuesta ya no está pendiente."] * 2


# --- Abogado: /casos y /paquete -------------------------------------------------------------


def test_vcrmr01_lawyer_lists_only_sent_cases(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    sent_lead = _lead(db, users["com"])
    draft_lead = _lead(db, users["com"], name="Beatriz Ruiz")
    bot = _bot(db, tg, dry_run=False)
    _press(bot, COM_TG, build_callback(PKG_SEND, str(_draft(db, tg, bot, sent_lead))))
    _draft(db, tg, bot, draft_lead)
    _say(bot, LAW_TG, "/casos")
    text = _texts(tg, LAW_TG)[-1]
    assert _ref(sent_lead) in text and "package_sent" in text and _ref(draft_lead) not in text
    _say(bot, COM_TG, "/casos")  # no es del comercial
    assert (
        "casos" not in _texts(tg, COM_TG)[-1].lower() or "permiso" in _texts(tg, COM_TG)[-1].lower()
    )


def test_vcrmr01_empty_cases(db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]) -> None:
    _say(_bot(db, tg), LAW_TG, "/casos")
    assert _texts(tg, LAW_TG) == ["No tienes casos con paquete enviado."]


def test_vcrmr02_lawyer_reads_the_package_but_not_unsent_or_unknown_ones(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    sent_lead = _lead(db, users["com"])
    draft_lead = _lead(db, users["com"])
    never = _lead(db, users["com"])
    with db.tx() as tx:
        tx.execute("UPDATE crm_leads SET ever_accepted=0 WHERE id=?", (never,))
    bot = _bot(db, tg, dry_run=False)
    _press(bot, COM_TG, build_callback(PKG_SEND, str(_draft(db, tg, bot, sent_lead))))
    _draft(db, tg, bot, draft_lead)
    _say(bot, LAW_TG, f"/paquete {_ref(sent_lead)}")
    assert "Total: 13.000.000 COP" in _texts(tg, LAW_TG)[-1]
    _say(bot, LAW_TG, f"/paquete {_ref(draft_lead)}")
    assert (
        "no tiene un paquete enviado" in _texts(tg, LAW_TG)[-1]
        or "no tiene" in _texts(tg, LAW_TG)[-1]
    )
    _say(bot, LAW_TG, f"/paquete {_ref(never)}")
    assert "Total" not in _texts(tg, LAW_TG)[-1]
    _say(bot, LAW_TG, "/paquete")
    assert "Indica el caso" in _texts(tg, LAW_TG)[-1]
    _say(bot, COM_TG, f"/paquete {_ref(sent_lead)}")
    assert "Total: 13.000.000 COP" in _texts(tg, COM_TG)[-1]
    _say(bot, COM_TG, f"/paquete {_ref(draft_lead)}")
    assert "no tiene un paquete" in _texts(tg, COM_TG)[-1]


def test_basejuridica_requires_the_lawyer_and_a_known_lead(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    bot = _bot(db, tg)
    _say(bot, COM_TG, f"/basejuridica {_ref(lead_id)}")
    _say(bot, LAW_TG, "/basejuridica")
    with db.read() as conn:
        assert repo.get_meta(conn, f"legal_basis_confirmed:{lead_id}") is None
    _say(bot, LAW_TG, f"/basejuridica {_ref(lead_id)}")
    with db.read() as conn:
        assert repo.get_meta(conn, f"legal_basis_confirmed:{lead_id}") == str(users["law"].id)


# --- Ramas límite ---------------------------------------------------------------------------


def test_offer_command_reports_parse_errors_and_unknown_leads(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    bot = _bot(db, tg)
    _say(bot, COM_TG, "/oferta")
    assert "Ejemplo" in tg.sent[-1].text
    _say(bot, COM_TG, OFFER.format(lead="L-9999"))
    assert tg.sent[-1].text == "No encontré ese lead entre los que puedes gestionar."


def test_offer_with_an_oversized_description_is_reported_not_crashed(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    _say(_bot(db, tg), COM_TG, f"/oferta {_ref(lead_id)}; pago contado; linea {'x' * 400} x1 @5")
    assert "300" in tg.sent[-1].text or "caracteres" in tg.sent[-1].text


def test_lead_that_leaves_accepted_before_the_tick_is_refused(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    bot = _bot(db, tg, dry_run=False)
    pid = _draft(db, tg, bot, lead_id)
    with db.tx() as tx:
        tx.execute("UPDATE crm_leads SET state='rejected' WHERE id=?", (lead_id,))
    _press(bot, COM_TG, build_callback(PKG_SEND, str(pid)))
    assert tg.sent[-1].text == NOT_ACCEPTED and _count(db, "SELECT COUNT(*) FROM crm_outbox") == 0


def test_handoff_data_removed_before_the_tick_is_stale(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    bot = _bot(db, tg, dry_run=False)
    pid = _draft(db, tg, bot, lead_id)
    with db.tx() as tx:
        tx.execute("UPDATE crm_leads SET email=NULL WHERE id=?", (lead_id,))
    _press(bot, COM_TG, build_callback(PKG_SEND, str(pid)))
    assert "cambiaron" in tg.sent[-1].text


def test_idempotency_key_already_claimed_blocks_a_second_delivery(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    from jerico.crm.idempotency import claim, make_key

    lead_id = _lead(db, users["com"])
    bot = _bot(db, tg, dry_run=False)
    pid = _draft(db, tg, bot, lead_id)
    with db.tx() as tx:
        assert claim(tx, make_key("package_send", lead_id, "v1"), START)
    _press(bot, COM_TG, build_callback(PKG_SEND, str(pid)))
    assert tg.sent[-1].text == "Esa propuesta ya no está pendiente."
    assert _count(db, "SELECT COUNT(*) FROM crm_outbox") == 0


def test_cases_skip_packages_of_leads_that_never_were_accepted(
    db: CrmDatabase, tg: FakeTelegram, users: dict[str, User]
) -> None:
    lead_id = _lead(db, users["com"])
    bot = _bot(db, tg, dry_run=False)
    _press(bot, COM_TG, build_callback(PKG_SEND, str(_draft(db, tg, bot, lead_id))))
    with db.tx() as tx:
        tx.execute("UPDATE crm_leads SET ever_accepted=0 WHERE id=?", (lead_id,))
    _say(bot, LAW_TG, "/casos")
    assert _texts(tg, LAW_TG)[-1] == "No tienes casos con paquete enviado."
