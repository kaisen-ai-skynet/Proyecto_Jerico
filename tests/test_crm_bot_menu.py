"""Tests del menú de comandos en los bots de Telegram (setMyCommands y setChatMenuButton).

Requisitos:
(1) Cada comando registrado lleva descripción corta en español y roles autorizados.
(2) Al arrancar, jerico-crm llama setMyCommands en ambos bots:
    - scope all_private_chats con los comandos del comercial
    - scope chat por cada usuario activo según su rol (cto ve todos; abogado en el bot legal)
    - setChatMenuButton type commands
    - Al dar de alta o baja un usuario se actualiza su menú.
(3) Si Telegram falla, se registra y el bot sigue (nunca bloquea el arranque).
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from crm_support import FakeClock, FakeEmailSender, FakeRunner, FakeTelegram, make_settings
from jerico.crm import repo
from jerico.crm.app import CrmApp
from jerico.crm.model import Role
from jerico.crm.ports import Update
from jerico.crm.telegram import HttpxTelegramClient

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
CTO_TG = 1000
COM_TG = 2000
LAW_TG = 3000


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
        legal_allowed_ids=str(LAW_TG),
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


def test_command_registration_has_description_and_roles(tmp_path: Path):
    app, _, _ = _build_app(tmp_path)
    # Bot principal: cada comando tiene descripción en español y roles válidos
    assert len(app.bot.commands) > 0
    for cmd in app.bot.commands.values():
        assert cmd.name.islower()
        assert len(cmd.description) >= 3, f"Comando {cmd.name} sin descripción válida"
        assert len(cmd.roles) >= 1, f"Comando {cmd.name} sin roles asignados"
        assert all(isinstance(r, Role) for r in cmd.roles)

    # Comandos comerciales presentes
    com_cmds = [c["command"] for c in app.bot.commands_for_role(Role.COMMERCIAL)]
    assert "nuevo" in com_cmds
    assert "lista" in com_cmds
    assert "ver" in com_cmds
    assert "nota" in com_cmds
    assert "editar" in com_cmds
    assert "seguimiento" in com_cmds
    assert "pedirautorizacion" in com_cmds
    assert "oferta" in com_cmds
    assert "firma" in com_cmds

    # Comandos CTO incluyen comerciales y extras de gestión
    cto_cmds = [c["command"] for c in app.bot.commands_for_role(Role.CTO)]
    for c in com_cmds:
        assert c in cto_cmds
    assert "alta" in cto_cmds
    assert "baja_usuario" in cto_cmds
    assert "reasignar" in cto_cmds
    assert "suprimir" in cto_cmds
    assert "exportar" in cto_cmds

    # Bot legal tiene comandos de abogado
    assert app.legal_bot is not None
    law_cmds = [c["command"] for c in app.legal_bot.commands_for_role(Role.LAWYER)]
    assert "start" in law_cmds
    assert "casos" in law_cmds
    assert "paquete" in law_cmds
    assert "descargar" in law_cmds
    assert "subircontrato" in law_cmds
    assert "devolver" in law_cmds


@pytest.mark.asyncio
async def test_startup_synchronizes_menus_in_both_bots(tmp_path: Path):
    app, tg, legal_tg = _build_app(tmp_path)
    await app.startup()

    # 1. Bot principal: setMyCommands con scope all_private_chats (comercial)
    all_private_calls = [
        call for call in tg.my_commands if call[1] == {"type": "all_private_chats"}
    ]
    assert len(all_private_calls) == 1
    cmds_all_private = [c["command"] for c in all_private_calls[0][0]]
    assert "nuevo" in cmds_all_private
    assert "lista" in cmds_all_private
    assert "alta" not in cmds_all_private  # Alta es solo de CTO

    # 2. Bot principal: setChatMenuButton type commands
    assert (None, {"type": "commands"}) in tg.menu_buttons or any(
        btn[1] == {"type": "commands"} for btn in tg.menu_buttons
    )

    # 3. Bot principal: scope chat para el CTO activo (con extras)
    cto_calls = [call for call in tg.my_commands if call[1] == {"type": "chat", "chat_id": CTO_TG}]
    assert len(cto_calls) >= 1
    cmds_cto = [c["command"] for c in cto_calls[0][0]]
    assert "alta" in cmds_cto
    assert "nuevo" in cmds_cto

    # 4. Bot legal: setChatMenuButton y setMyCommands
    assert any(btn[1] == {"type": "commands"} for btn in legal_tg.menu_buttons)
    law_calls = [call for call in legal_tg.my_commands]
    assert len(law_calls) >= 1


@pytest.mark.asyncio
async def test_alta_and_baja_usuario_updates_menu(tmp_path: Path):
    app, tg, legal_tg = _build_app(tmp_path)
    await app.startup()

    tg.my_commands.clear()
    legal_tg.my_commands.clear()
    tg.deleted_commands.clear()
    legal_tg.deleted_commands.clear()

    # Dar de alta un comercial
    update_alta_com = Update(
        update_id=1,
        chat_id=CTO_TG,
        user_id=CTO_TG,
        text=f"/alta comercial; {COM_TG}; com@kaisen.la",
        chat_type="private",
    )
    await app.bot.process_update(update_alta_com)

    # Debe haberse actualizado el menú del nuevo comercial
    com_calls = [call for call in tg.my_commands if call[1] == {"type": "chat", "chat_id": COM_TG}]
    assert len(com_calls) >= 1
    cmds_com = [c["command"] for c in com_calls[0][0]]
    assert "nuevo" in cmds_com
    assert "alta" not in cmds_com

    # Dar de alta un abogado
    update_alta_law = Update(
        update_id=2,
        chat_id=CTO_TG,
        user_id=CTO_TG,
        text=f"/alta abogado; {LAW_TG}; abog@kaisen.la",
        chat_type="private",
    )
    await app.bot.process_update(update_alta_law)

    # En el bot legal debe haberse actualizado el menú del abogado
    law_calls = [
        call for call in legal_tg.my_commands if call[1] == {"type": "chat", "chat_id": LAW_TG}
    ]
    assert len(law_calls) >= 1

    # Dar de baja al comercial
    update_baja = Update(
        update_id=3,
        chat_id=CTO_TG,
        user_id=CTO_TG,
        text=f"/baja_usuario {COM_TG}",
        chat_type="private",
    )
    await app.bot.process_update(update_baja)

    # Se debe haber eliminado o reseteado su menú personalizado
    assert {"type": "chat", "chat_id": COM_TG} in tg.deleted_commands or any(
        call[1] == {"type": "chat", "chat_id": COM_TG} and call[0] == [] for call in tg.my_commands
    )


@pytest.mark.asyncio
async def test_telegram_failure_does_not_block_startup_or_commands(tmp_path: Path):
    app, tg, legal_tg = _build_app(tmp_path)
    # Forzamos fallo de Telegram en comandos de menú
    tg.fail_commands(True)
    legal_tg.fail_commands(True)

    # El arranque no se bloquea ni lanza excepción
    await app.startup()

    # Operación de alta sigue funcionando en BD aunque Telegram falle
    update_alta = Update(
        update_id=1,
        chat_id=CTO_TG,
        user_id=CTO_TG,
        text=f"/alta comercial; {COM_TG}; com@kaisen.la",
        chat_type="private",
    )
    await app.bot.process_update(update_alta)

    with app.db.read() as conn:
        user = repo.active_user_by_telegram(conn, COM_TG)
        assert user is not None
        assert user.email == "com@kaisen.la"


@pytest.mark.asyncio
async def test_httpx_telegram_client_menu_methods():
    def ok_handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content.decode("utf-8"))
        if "setMyCommands" in request.url.path:
            assert "commands" in data
            return httpx.Response(200, json={"ok": True, "result": True})
        if "deleteMyCommands" in request.url.path:
            return httpx.Response(200, json={"ok": True, "result": True})
        if "setChatMenuButton" in request.url.path:
            assert data["menu_button"]["type"] == "commands"
            return httpx.Response(200, json={"ok": True, "result": True})
        return httpx.Response(404)

    client = HttpxTelegramClient("123:TOKEN", transport=httpx.MockTransport(ok_handler))
    assert await client.set_my_commands([{"command": "test", "description": "desc"}]) is True
    assert await client.delete_my_commands(scope={"type": "default"}) is True
    assert await client.set_chat_menu_button(chat_id=123, menu_button={"type": "commands"}) is True
    assert await client.set_chat_menu_button() is True

    def fail_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "Bad Request"})

    bad_client = HttpxTelegramClient("123:TOKEN", transport=httpx.MockTransport(fail_handler))
    assert await bad_client.set_my_commands([]) is False
    assert await bad_client.delete_my_commands() is False
    assert await bad_client.set_chat_menu_button() is False


@pytest.mark.asyncio
async def test_bot_start_and_ayuda_commands(tmp_path: Path):
    app, tg, legal_tg = _build_app(tmp_path)
    await app.startup()

    # Dar de alta comercial y abogado
    with app.db.tx() as tx:
        repo.insert_user(
            tx, telegram_id=COM_TG, role=Role.COMMERCIAL, email="com@kaisen.la", now=NOW
        )
        repo.insert_user(tx, telegram_id=LAW_TG, role=Role.LAWYER, email="law@kaisen.la", now=NOW)

    tg.sent.clear()
    legal_tg.sent.clear()

    # 1. Comercial escribe /start al bot principal
    u_start = Update(
        update_id=101, chat_id=COM_TG, user_id=COM_TG, text="/start", chat_type="private"
    )
    await app.bot.process_update(u_start)
    assert len(tg.sent) >= 1
    assert "Bienvenido" in tg.sent[-1].text or "com@kaisen.la" in tg.sent[-1].text

    # 2. Comercial escribe /ayuda al bot principal
    u_help = Update(
        update_id=102, chat_id=COM_TG, user_id=COM_TG, text="/ayuda", chat_type="private"
    )
    await app.bot.process_update(u_help)
    reply_help = tg.sent[-1].text
    assert "Comandos disponibles" in reply_help
    assert "/nuevo" in reply_help
    assert "/lista" in reply_help
    assert "/alta" not in reply_help  # Alta es del CTO

    # 3. Abogado escribe /ayuda al bot legal
    assert app.legal_bot is not None
    u_law_help = Update(
        update_id=103, chat_id=LAW_TG, user_id=LAW_TG, text="/ayuda", chat_type="private"
    )
    await app.legal_bot.process_update(u_law_help)
    law_reply = legal_tg.sent[-1].text
    assert "Comandos disponibles" in law_reply
    assert "/casos" in law_reply
    assert "/asistente" in law_reply


@pytest.mark.asyncio
async def test_completeness_of_all_commands_and_menus(tmp_path: Path):
    """Requisito 5: Todo comando registrado aparece en el menú del rol correspondiente,

    y ningún comando del menú deja de estar registrado ni responde 'Orden no reconocida'.
    """
    app, tg, legal_tg = _build_app(tmp_path)
    await app.startup()

    with app.db.tx() as tx:
        repo.insert_user(
            tx, telegram_id=COM_TG, role=Role.COMMERCIAL, email="com@kaisen.la", now=NOW
        )
        repo.insert_user(tx, telegram_id=LAW_TG, role=Role.LAWYER, email="law@kaisen.la", now=NOW)

    from jerico.crm.bot import UNKNOWN_COMMAND
    from jerico.crm.team import DENIED

    # Verificar para cada bot y rol
    bots_and_users = [
        (app.bot, COM_TG, Role.COMMERCIAL, tg),
        (app.bot, CTO_TG, Role.CTO, tg),
        (app.legal_bot, LAW_TG, Role.LAWYER, legal_tg),
        (app.legal_bot, CTO_TG, Role.CTO, legal_tg),
    ]

    update_seq = 200
    for bot, uid, role, fake_tg in bots_and_users:
        assert bot is not None
        menu_cmds = bot.commands_for_role(role)
        menu_cmd_names = {c["command"] for c in menu_cmds}

        # 1. Todo comando del bot que permite este rol DEBE estar en el menú
        for cmd_entry in bot.commands.values():
            if role in cmd_entry.roles or (role == Role.CTO and cmd_entry.roles):
                assert cmd_entry.name in menu_cmd_names, (
                    f"Comando {cmd_entry.name} permitido para {role} no aparece en el menú de {bot}"
                )

        # 2. Ningún comando del menú responde 'Orden no reconocida' o 'Permiso denegado'
        for cmd_item in menu_cmds:
            cmd_name = cmd_item["command"]
            assert cmd_name in bot.commands, (
                f"Comando {cmd_name} en menú pero no registrado en {bot}"
            )
            fake_tg.sent.clear()
            update_seq += 1
            u = Update(
                update_id=update_seq,
                chat_id=uid,
                user_id=uid,
                text=f"/{cmd_name}",
                chat_type="private",
            )
            await bot.process_update(u)
            assert len(fake_tg.sent) >= 1, f"Comando /{cmd_name} para {role} no generó respuesta"
            last_text = fake_tg.sent[-1].text
            assert UNKNOWN_COMMAND not in last_text, (
                f"Comando /{cmd_name} para {role} respondió 'Orden no reconocida'"
            )
            assert DENIED not in last_text, (
                f"Comando /{cmd_name} para {role} respondió 'No tiene permiso'"
            )
