"""Pruebas TDD de los comandos de marketing para @Jericoo_bot con FakeTelegram.

Verifica:
- Registro de comandos vía bot.register_command:
  /campana, /campanas, /aprobarcampana, /rechazarcampana, /despachar.
- Restricción estricta solo para el rol CTO (VCRM-086 / deny).
- Descripciones cortas en español de cada comando.
- Flujo completo de proponer -> listar -> aprobar -> despachar en DRY_RUN e idempotencia.
"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from crm_support import FakeClock, FakeTelegram
from jerico.crm import repo
from jerico.crm.bot import CrmBot
from jerico.crm.db import CrmDatabase
from jerico.crm.model import Role, User
from jerico.crm.ports import Update
from jerico.crm.team import DENIED
from jerico.marketing.bot import (
    MARKETING_COMMAND_DESCRIPTIONS,
    register_marketing_commands,
)
from jerico.marketing.orquestador import OrquestadorMarketing
from jerico.schemas.marketing import EstadoCampana

START = datetime(2026, 10, 14, 9, 0, 0, tzinfo=UTC)

CTO_TG = 1000
COM_TG = 2000


@pytest.fixture
def db(tmp_path: Path) -> Iterator[CrmDatabase]:
    database = CrmDatabase(tmp_path / "crm_marketing.db")

    yield database
    database.close()


@pytest.fixture
def tg() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(START)


@pytest.fixture
def orquestador() -> OrquestadorMarketing:
    return OrquestadorMarketing(dry_run=True)


@pytest.fixture
def bot(
    db: CrmDatabase,
    tg: FakeTelegram,
    clock: FakeClock,
    orquestador: OrquestadorMarketing,
) -> CrmBot:
    b = CrmBot(db, tg, clock.now)
    register_marketing_commands(b, orquestador=orquestador)
    return b


@pytest.fixture
def users(db: CrmDatabase) -> tuple[User, User]:
    with db.tx() as tx:
        cto = repo.insert_user(
            tx, telegram_id=CTO_TG, role=Role.CTO, email="cto@kaizen.com", now=START
        )
        com = repo.insert_user(
            tx, telegram_id=COM_TG, role=Role.COMMERCIAL, email="com@kaizen.com", now=START
        )
    return cto, com


def _msg(update_id: int, user_tg: int, text: str) -> Update:
    return Update(
        update_id=update_id,
        user_id=user_tg,
        chat_id=user_tg,
        chat_type="private",
        text=text,
    )


def test_comandos_registrados_y_descripciones(bot: CrmBot) -> None:
    """Verifica que los 5 comandos están registrados con descripciones cortas en español."""
    comandos_esperados = {
        "campana",
        "campanas",
        "aprobarcampana",
        "rechazarcampana",
        "despachar",
    }
    for cmd in comandos_esperados:
        assert cmd in bot._commands
        assert cmd in MARKETING_COMMAND_DESCRIPTIONS
        assert len(MARKETING_COMMAND_DESCRIPTIONS[cmd]) > 10
        assert "CTO" in MARKETING_COMMAND_DESCRIPTIONS[cmd]


def test_no_cto_denegado(bot: CrmBot, tg: FakeTelegram, users: tuple[User, User]) -> None:
    """Verifica que usuarios con rol distinto de CTO son denegados en todos los comandos."""
    _, com = users
    comandos = [
        "/campana Idea de prueba",
        "/campanas",
        "/aprobarcampana CAMP-123",
        "/rechazarcampana CAMP-123 Inadecuado",
        "/despachar CAMP-123",
    ]

    for i, cmd in enumerate(comandos, start=1):
        asyncio.run(bot.process_update(_msg(i, com.telegram_id, cmd)))
        assert tg.sent[-1].text == DENIED


def test_flujo_campana_proponer_listar_aprobar_despachar(
    bot: CrmBot,
    tg: FakeTelegram,
    users: tuple[User, User],
    orquestador: OrquestadorMarketing,
) -> None:
    """Flujo completo de ciclo de vida de campaña por Telegram bajo rol CTO."""
    cto, _ = users

    # 1. /campanas cuando no hay ninguna
    asyncio.run(bot.process_update(_msg(1, cto.telegram_id, "/campanas")))
    assert "No hay campañas pendientes" in tg.sent[-1].text

    # 2. /campana sin texto da uso
    asyncio.run(bot.process_update(_msg(2, cto.telegram_id, "/campana")))
    assert "Uso:" in tg.sent[-1].text

    # 3. Proponer campaña válida
    asyncio.run(
        bot.process_update(
            _msg(
                3,
                cto.telegram_id,
                "/campana Automatización de contratos con firma digital y alertas por WhatsApp",
            )
        )
    )
    assert "PROPUESTA DE CAMPAÑA" in tg.sent[-1].text
    assert "DRY_RUN SIMULADO" in tg.sent[-1].text

    # Extraer ID de la campaña
    id_linea = [line for line in tg.sent[-1].text.splitlines() if "ID:" in line][0]
    campana_id = id_linea.split("ID:")[1].strip()

    # 4. /campanas lista la campaña creada
    asyncio.run(bot.process_update(_msg(4, cto.telegram_id, "/campanas")))
    assert campana_id in tg.sent[-1].text
    assert "Campañas Pendientes" in tg.sent[-1].text

    # 5. /despachar sin estar aprobada falla
    asyncio.run(bot.process_update(_msg(5, cto.telegram_id, f"/despachar {campana_id}")))
    assert "no ha sido aprobada" in tg.sent[-1].text

    # 6. /aprobarcampana autoriza la campaña
    asyncio.run(bot.process_update(_msg(6, cto.telegram_id, f"/aprobarcampana {campana_id} 10.00")))
    assert "aprobada" in tg.sent[-1].text.lower()
    campana = orquestador.obtener_campana(campana_id)
    assert campana.estado == EstadoCampana.APROBADA
    assert campana.gasto_autorizado_usd == Decimal("10.00")

    # 7. /despachar ejecuta el despacho en DRY_RUN
    asyncio.run(
        bot.process_update(
            _msg(7, cto.telegram_id, f"/despachar {campana_id} gerencia@cliente.com")
        )
    )
    assert "despachada" in tg.sent[-1].text.lower()
    assert campana_id in tg.sent[-1].text

    campana_post = orquestador.obtener_campana(campana_id)
    assert campana_post.estado == EstadoCampana.DESPACHADA

    # 8. Reintento de despacho bloqueado por idempotencia
    asyncio.run(
        bot.process_update(
            _msg(8, cto.telegram_id, f"/despachar {campana_id} gerencia@cliente.com")
        )
    )
    assert "idempotencia" in tg.sent[-1].text.lower()


def test_rechazarcampana(
    bot: CrmBot,
    tg: FakeTelegram,
    users: tuple[User, User],
    orquestador: OrquestadorMarketing,
) -> None:
    """Verifica que el CTO puede rechazar una campaña indicando el motivo."""
    cto, _ = users

    # Proponer campaña
    asyncio.run(bot.process_update(_msg(1, cto.telegram_id, "/campana Campaña para rechazar")))
    id_linea = [line for line in tg.sent[-1].text.splitlines() if "ID:" in line][0]
    campana_id = id_linea.split("ID:")[1].strip()

    # Rechazar
    asyncio.run(
        bot.process_update(
            _msg(2, cto.telegram_id, f"/rechazarcampana {campana_id} Copy no alineado")
        )
    )
    assert "rechazada" in tg.sent[-1].text.lower()
    assert "Copy no alineado" in tg.sent[-1].text

    campana = orquestador.obtener_campana(campana_id)
    assert campana.estado == EstadoCampana.RECHAZADA
