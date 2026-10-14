"""Tests de alta guiada para desconocidos (Requisito 7).

Requisitos:
- Hoy un desconocido que escribe a @Jericoo_bot o @Jericoo_law_bot recibe silencio.
- Si un desconocido envía /start:
  - Le responde una sola vez «Hola, tu solicitud de acceso fue enviada al administrador»
  - Envía al CTO (2099727924) un mensaje con nombre, @usuario e ID de Telegram y botones:
    «Alta comercial», «Alta abogado» y «Ignorar».
  - Al pulsar Alta, pide el correo y ejecuta el mismo flujo de /alta (con auditoría).
  - Si es abogado, además debe poder entrar al bot legal
    (actualiza la lista permitida en base de datos, no en el .env).
  - Límite: una solicitud por ID cada 24 h.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from crm_support import FakeClock, FakeEmailSender, FakeRunner, FakeTelegram, make_settings
from jerico.crm import repo
from jerico.crm.app import CrmApp
from jerico.crm.model import AuditAction, AuditOutcome, Role
from jerico.crm.ports import Update

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
CTO_TG = 2099727924
UNKNOWN_TG = 777888999


def _build_app(tmp_path: Path, **overrides: Any) -> tuple[CrmApp, FakeTelegram, FakeTelegram]:
    tg = FakeTelegram()
    legal_tg = FakeTelegram()
    settings = make_settings(
        telegram_bot_token="123:token-main",
        legal_bot_token="123:token-legal",
        fingerprint_key="clave-secreta",
        seed_cto_telegram_id=str(CTO_TG),
        seed_cto_email="cto@kaisen.la",
        data_dir=str(tmp_path / "crm-data"),
        legal_allowed_ids="",
        **overrides,
    )
    clock = FakeClock(NOW)
    app = CrmApp(
        settings,
        telegram=tg,
        email=FakeEmailSender(),
        runner=FakeRunner(),
        clock=clock.now,
        legal_telegram=legal_tg,
    )
    return app, tg, legal_tg


@pytest.mark.asyncio
async def test_unknown_user_non_start_receives_silence(tmp_path: Path):
    app, tg, _ = _build_app(tmp_path)
    await app.startup()

    tg.sent.clear()
    update = Update(
        update_id=1,
        chat_id=UNKNOWN_TG,
        user_id=UNKNOWN_TG,
        text="Hola, quiero ver clientes",
        chat_type="private",
    )
    await app.bot.process_update(update)

    # Silencio total hacia el desconocido y hacia el CTO
    assert len(tg.sent) == 0


@pytest.mark.asyncio
async def test_unknown_user_start_guided_alta_flow(tmp_path: Path):
    app, tg, legal_tg = _build_app(tmp_path)
    await app.startup()

    tg.sent.clear()
    # 1. Desconocido envía /start
    update = Update(
        update_id=2,
        chat_id=UNKNOWN_TG,
        user_id=UNKNOWN_TG,
        text="/start",
        chat_type="private",
        user_name="Carlos Pérez",
        username="carlosp",
    )
    await app.bot.process_update(update)

    # Desconocido recibe confirmación
    reply_to_unknown = [m for m in tg.sent if m.chat_id == UNKNOWN_TG]
    assert len(reply_to_unknown) == 1
    assert "Hola, tu solicitud de acceso fue enviada al administrador" in reply_to_unknown[0].text

    # CTO recibe mensaje con datos y botones
    msg_to_cto = [m for m in tg.sent if m.chat_id == CTO_TG]
    assert len(msg_to_cto) == 1
    assert "Carlos Pérez" in msg_to_cto[0].text
    assert "@carlosp" in msg_to_cto[0].text
    assert str(UNKNOWN_TG) in msg_to_cto[0].text
    assert msg_to_cto[0].buttons is not None

    buttons = [b for row in msg_to_cto[0].buttons for b in row]
    btn_labels = [b.text for b in buttons]
    assert "Alta comercial" in btn_labels
    assert "Alta abogado" in btn_labels
    assert "Ignorar" in btn_labels


@pytest.mark.asyncio
async def test_unknown_user_rate_limit_24h(tmp_path: Path):
    app, tg, _ = _build_app(tmp_path)
    await app.startup()

    # Primera solicitud
    update1 = Update(
        update_id=10,
        chat_id=UNKNOWN_TG,
        user_id=UNKNOWN_TG,
        text="/start",
        chat_type="private",
    )
    await app.bot.process_update(update1)
    assert len([m for m in tg.sent if m.chat_id == UNKNOWN_TG]) == 1

    tg.sent.clear()
    # Segunda solicitud a las 2 horas -> silencio
    update2 = Update(
        update_id=11,
        chat_id=UNKNOWN_TG,
        user_id=UNKNOWN_TG,
        text="/start",
        chat_type="private",
    )
    await app.bot.process_update(update2)
    assert len(tg.sent) == 0


@pytest.mark.asyncio
async def test_cto_alta_abogado_guided_grants_legal_bot_access(tmp_path: Path):
    app, tg, legal_tg = _build_app(tmp_path)
    await app.startup()

    # Desconocido pide acceso
    update_start = Update(
        update_id=20,
        chat_id=UNKNOWN_TG,
        user_id=UNKNOWN_TG,
        text="/start",
        chat_type="private",
        user_name="Dra. Gómez",
    )
    await app.bot.process_update(update_start)

    msg_to_cto = [m for m in tg.sent if m.chat_id == CTO_TG][-1]
    assert msg_to_cto.buttons is not None
    alta_law_btn = [b for row in msg_to_cto.buttons for b in row if b.text == "Alta abogado"][0]

    # CTO pulsa "Alta abogado"
    cb_update = Update(
        update_id=21,
        chat_id=CTO_TG,
        user_id=CTO_TG,
        callback_id="cb-1",
        callback_data=alta_law_btn.callback_data,
        chat_type="private",
    )
    await app.bot.process_update(cb_update)

    # Bot le pide el correo al CTO
    last_msg = tg.sent[-1]
    assert last_msg.chat_id == CTO_TG
    assert "correo" in last_msg.text.lower()

    # CTO responde con el correo
    email_update = Update(
        update_id=22,
        chat_id=CTO_TG,
        user_id=CTO_TG,
        text="abogada.gomez@kaisen.la",
        chat_type="private",
    )
    await app.bot.process_update(email_update)

    # 1. El usuario quedó registrado en BD con rol abogado
    with app.db.read() as conn:
        lawyer = repo.active_user_by_telegram(conn, UNKNOWN_TG)
        assert lawyer is not None
        assert lawyer.role == Role.LAWYER
        assert lawyer.email == "abogada.gomez@kaisen.la"

        # 2. Se auditó la acción
        audits = repo.audit_rows(conn)
        assert any(
            a["action"] == AuditAction.USER_ADDED.value and a["outcome"] == AuditOutcome.OK.value
            for a in audits
        )

    # 3. La abogada ahora puede entrar a @Jericoo_law_bot
    # (aunque legal_allowed_ids del .env estuviera vacío)
    assert app.legal_bot is not None
    legal_update = Update(
        update_id=23,
        chat_id=UNKNOWN_TG,
        user_id=UNKNOWN_TG,
        text="/start",
        chat_type="private",
    )
    await app.legal_bot.process_update(legal_update)
    sent_legal = [m for m in legal_tg.sent if m.chat_id == UNKNOWN_TG]
    assert len(sent_legal) >= 1
    # No es silencio ni error de acceso no autorizado
    reply_text = sent_legal[0].text
    assert any(t in reply_text for t in ("ID de Telegram", "Bienvenido", "casos"))
