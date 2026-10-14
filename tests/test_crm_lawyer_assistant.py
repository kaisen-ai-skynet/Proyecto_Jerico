"""Tests del asistente IA para el rol abogado en @Jericoo_law_bot.

Requisitos:
(1) Resumen del paquete de un caso: /asistente resumen L-n
(2) Borrador de cláusula o contrato a partir del paquete: /asistente clausula L-n <instrucción>,
    rotulado «Borrador (no enviado)» y nunca enviado a nadie automáticamente.
(3) Pregunta libre: /asistente pregunta <texto>
Reutiliza el asistente existente (gpt-6-luna, seudonimización, topes, auditoría):
el abogado SOLO ve casos que le llegaron por el flujo F2, nunca otros leads.
Datos personales: el LLM recibe el paquete seudonimizado.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from crm_support import (
    FakeClock,
    FakeEmailSender,
    FakeLlm,
    FakeRunner,
    FakeTelegram,
    make_settings,
)
from jerico.crm import closing_repo as crepo
from jerico.crm import repo
from jerico.crm.app import CrmApp
from jerico.crm.closing_flow import build_package
from jerico.crm.closing_model import LegalBasis, PackageStatus
from jerico.crm.model import LeadState, Role
from jerico.crm.ports import Update

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
CTO_TG = 1000
COM_TG = 2000
LAW_TG = 3000


def _build_app(
    tmp_path: Path, llm: FakeLlm | None = None, **overrides: Any
) -> tuple[CrmApp, FakeTelegram, FakeTelegram]:
    tg = FakeTelegram()
    legal_tg = FakeTelegram()
    settings = make_settings(
        telegram_bot_token="123:token-main",
        legal_bot_token="123:token-legal",
        fingerprint_key="clave-secreta",
        seed_cto_telegram_id=str(CTO_TG),
        seed_cto_email="cto@kaisen.la",
        data_dir=str(tmp_path / "crm-data"),
        legal_allowed_ids=str(LAW_TG),
        assistant_enabled=True,
        **overrides,
    )
    clock = FakeClock(NOW)
    app = CrmApp(
        settings,
        telegram=tg,
        email=FakeEmailSender(),
        runner=FakeRunner(),
        clock=clock.now,
        assistant_llm=llm or FakeLlm(reply="Respuesta legal del asistente"),
        legal_telegram=legal_tg,
    )
    return app, tg, legal_tg


def _setup_f2_case(app: CrmApp) -> int:
    """Crea un lead con paquete enviado al abogado (flujo F2)."""
    with app.db.tx() as tx:
        if repo.active_user_by_telegram(tx, LAW_TG) is None:
            repo.insert_user(
                tx,
                telegram_id=LAW_TG,
                role=Role.LAWYER,
                email="abogado@kaisen.la",
                now=NOW,
            )
        lead_id = repo.insert_lead(
            tx,
            assigned_user_id=None,
            state=LeadState.ACCEPTED,
            now=NOW,
            fields={
                "name": "Empresa Cliente SAS",
                "company": "Cliente SAS",
                "email": "contacto@cliente.co",
                "phone_e164": "+573001234567",
                "client_type": "empresa",
                "doc_type": "NIT",
                "doc_number": "900123456-1",
                "legal_rep": "Juan Pérez",
                "service": "Consultoría IA",
                "agreed_value": "10000000",
                "start_term": "15 días",
            },
        )
        tx.execute(
            "UPDATE crm_leads SET ever_accepted = 1 WHERE id = ?",
            (lead_id,),
        )
        lead = repo.get_lead(tx, lead_id)
        assert lead is not None
        offer = crepo.insert_offer(
            tx,
            lead_id=lead.id,
            currency="COP",
            payment_terms="50% anticipo, 50% contra entrega",
            valid_until="2026-10-14",
            special_conditions="Ninguna",
            created_by=1,
            lines=[("Consultoría IA", 1, 10_000_000)],
            now=NOW,
        )
        built = build_package(lead, offer, version=1, legal_basis=LegalBasis.AUTHORIZATION, now=NOW)
        from jerico.crm.closing_flow import content_hash

        chash = content_hash(built)
        package = crepo.insert_package(
            tx,
            lead_id=lead.id,
            offer_id=offer.id,
            content_hash=chash,
            legal_basis=LegalBasis.AUTHORIZATION.value,
            created_by=1,
            now=NOW,
        )
        assert package is not None
        crepo.set_package_status(tx, package.id, PackageStatus.SENT, now=NOW)
        return lead.id


@pytest.mark.asyncio
async def test_lawyer_assistant_resumen(tmp_path: Path):
    fake_llm = FakeLlm(
        reply=(
            "Resumen: Paquete con objeto Consultoría IA para [EMPRESA]. Base legal consentimiento."
        )
    )
    app, _, legal_tg = _build_app(tmp_path, llm=fake_llm)
    await app.startup()
    lead_id = _setup_f2_case(app)

    update = Update(
        update_id=1,
        chat_id=LAW_TG,
        user_id=LAW_TG,
        text=f"/asistente resumen L-{lead_id:04d}",
        chat_type="private",
    )
    assert app.legal_bot is not None
    await app.legal_bot.process_update(update)

    # 1. El LLM recibió el paquete seudonimizado (no con los datos en claro)
    assert len(fake_llm.calls) == 1
    call = fake_llm.calls[0]
    call_user = str(call["user"])
    assert "Cliente SAS" not in call_user
    assert "[EMPRESA]" in call_user or "[CLIENTE]" in call_user

    # 2. La respuesta enviada al abogado restaura el nombre real
    sent_texts = [m.text for m in legal_tg.sent if m.chat_id == LAW_TG]
    assert any("Cliente SAS" in t for t in sent_texts)
    assert any("Generado por IA" in t for t in sent_texts)


@pytest.mark.asyncio
async def test_lawyer_assistant_clausula(tmp_path: Path):
    fake_llm = FakeLlm(reply="Cláusula Quinta: Confidencialidad estricta para [EMPRESA].")
    app, _, legal_tg = _build_app(tmp_path, llm=fake_llm)
    await app.startup()
    lead_id = _setup_f2_case(app)

    update = Update(
        update_id=2,
        chat_id=LAW_TG,
        user_id=LAW_TG,
        text=f"/asistente clausula L-{lead_id:04d} redactar cláusula de confidencialidad",
        chat_type="private",
    )
    assert app.legal_bot is not None
    await app.legal_bot.process_update(update)

    sent_texts = [m.text for m in legal_tg.sent if m.chat_id == LAW_TG]
    assert any("Borrador (no enviado)" in t for t in sent_texts)
    assert any("Cliente SAS" in t for t in sent_texts)
    assert any("Generado por IA" in t for t in sent_texts)


@pytest.mark.asyncio
async def test_lawyer_assistant_pregunta(tmp_path: Path):
    fake_llm = FakeLlm(reply="Tienes 1 caso activo con paquete enviado.")
    app, _, legal_tg = _build_app(tmp_path, llm=fake_llm)
    await app.startup()
    _setup_f2_case(app)

    update = Update(
        update_id=3,
        chat_id=LAW_TG,
        user_id=LAW_TG,
        text="/asistente pregunta ¿cuántos casos tengo pendientes?",
        chat_type="private",
    )
    assert app.legal_bot is not None
    await app.legal_bot.process_update(update)

    assert len(fake_llm.calls) == 1
    sent_texts = [m.text for m in legal_tg.sent if m.chat_id == LAW_TG]
    assert any("Tienes 1 caso activo" in t for t in sent_texts)


@pytest.mark.asyncio
async def test_lawyer_cannot_access_non_f2_lead(tmp_path: Path):
    app, _, legal_tg = _build_app(tmp_path)
    await app.startup()
    # Lead normal sin paquete F2
    with app.db.tx() as tx:
        repo.insert_user(
            tx, telegram_id=LAW_TG, role=Role.LAWYER, email="abogado@kaisen.la", now=NOW
        )
        other_id = repo.insert_lead(
            tx,
            assigned_user_id=None,
            state=LeadState.ACCEPTED,
            now=NOW,
            fields={"name": "Otro Lead", "company": "Otro SAS"},
        )

    update = Update(
        update_id=4,
        chat_id=LAW_TG,
        user_id=LAW_TG,
        text=f"/asistente resumen L-{other_id:04d}",
        chat_type="private",
    )
    assert app.legal_bot is not None
    await app.legal_bot.process_update(update)

    sent_texts = [m.text for m in legal_tg.sent if m.chat_id == LAW_TG]
    assert any("No encontré ese caso" in t for t in sent_texts)
