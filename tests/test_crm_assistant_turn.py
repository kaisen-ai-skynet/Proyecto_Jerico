"""Pruebas de integración del bucle de agente y memoria persistente (Spec 005 - Fase A1)."""

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from crm_support import FakeClock, FakeEmailSender, FakeRunner, FakeTelegram, make_settings
from jerico.crm.app import CrmApp
from jerico.crm.assistant import AssistantContext, handle
from jerico.crm.assistant_budget import AssistantBudget
from jerico.crm.assistant_memory import AccessDeniedError, AssistantMemory
from jerico.crm.bot import CrmBot
from jerico.crm.db import CrmDatabase
from jerico.crm.llm import LlmResult
from jerico.crm.model import Outgoing, Role, User


def _run_deferred(bot: CrmBot) -> list[Outgoing]:
    coro = cast(Coroutine[Any, Any, list[Outgoing]], bot._deferred.pop()())
    return asyncio.run(coro)



@pytest.fixture
def fake_now() -> datetime:
    return datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def test_assistant_persists_turn_in_memory(tmp_path: Path, fake_now: datetime) -> None:
    settings = make_settings(
        data_dir=str(tmp_path),
        assistant_enabled=True,
        assistant_api_key="sk-test",
    )
    db = CrmDatabase(tmp_path / "crm.db")
    with db.tx() as tx:
        tx.execute(
            "INSERT INTO crm_users(id, telegram_id, role, email, active, created_at) "
            "VALUES (10, 1001, 'commercial', 'com1@kaisen.la', 1, ?)",
            (fake_now.isoformat(),),
        )

    mem_file = tmp_path / "assistant_memory.db"
    mem = AssistantMemory(mem_file)

    mock_llm = AsyncMock()
    mock_llm.complete.return_value = LlmResult(
        text="Pipeline sano: 1 lead activo.",
        input_tokens=50,
        output_tokens=15,
    )

    ctx = AssistantContext(
        settings=settings,
        db=db,
        client=mock_llm,
        budget=AssistantBudget(settings),
        clock=lambda: fake_now,
        memory=mem,
    )

    bot = CrmBot(db, FakeTelegram(), lambda: fake_now)
    cmd = handle(ctx, bot)

    user = User(
        id=10,
        telegram_id=1001,
        role="commercial",
        email="com1@kaisen.la",
        active=1,
        created_at=fake_now.isoformat(),
        deactivated_at=None,
    )

    # Ejecuta el comando en el bot
    with db.tx() as tx:
        out = cmd(tx, user, "/asistente pregunta ¿cómo va el pipeline?", fake_now)

    assert len(out) == 1
    assert "Consultando" in out[0].text

    # El bot tiene un job diferido
    assert len(bot._deferred) == 1
    res = _run_deferred(bot)
    assert len(res) == 1
    assert "Pipeline sano" in res[0].text

    # Verificamos que el turno quedó persistido en la memoria del asistente
    history = mem.get_transcript(
        session_id="crm:user:10:pregunta",
        user_id=10,
        role=Role.COMMERCIAL.value,
    )
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert "Pregunta:" in history[0]["content"]
    assert history[1]["role"] == "assistant"
    assert "Pipeline sano" in history[1]["content"]

    mem.close()


def test_crm_app_initializes_assistant_memory(tmp_path: Path) -> None:
    """Verifica que CrmApp monta AssistantMemory sobre su data_dir de forma transparente."""
    settings = make_settings(
        data_dir=str(tmp_path),
        assistant_enabled=True,
        assistant_api_key="sk-test",
    )
    app = CrmApp(
        settings,
        telegram=FakeTelegram(),
        email=FakeEmailSender(),
        runner=FakeRunner(),
        clock=FakeClock(datetime(2026, 10, 14, 12, 0, tzinfo=UTC)).now,
    )
    assert hasattr(app, "assistant_memory")
    assert isinstance(app.assistant_memory, AssistantMemory)
    assert (tmp_path / "assistant_memory.db").exists()
    app.assistant_memory.close()


def test_multiple_turns_and_isolation_across_commercials(
    tmp_path: Path, fake_now: datetime
) -> None:
    """Verifica turnos secuenciales en la misma sesión y aislamiento absoluto con otro comercial."""
    settings = make_settings(
        data_dir=str(tmp_path),
        assistant_enabled=True,
        assistant_api_key="sk-test",
    )
    db = CrmDatabase(tmp_path / "crm.db")
    with db.tx() as tx:
        tx.execute(
            "INSERT INTO crm_users(id, telegram_id, role, email, active, created_at) "
            "VALUES (10, 1001, 'commercial', 'com1@kaisen.la', 1, ?)",
            (fake_now.isoformat(),),
        )
        tx.execute(
            "INSERT INTO crm_users(id, telegram_id, role, email, active, created_at) "
            "VALUES (20, 2002, 'commercial', 'com2@kaisen.la', 1, ?)",
            (fake_now.isoformat(),),
        )

    mem_file = tmp_path / "assistant_memory.db"
    mem = AssistantMemory(mem_file)

    mock_llm = AsyncMock()
    mock_llm.complete.side_effect = [
        LlmResult(text="Respuesta 1: Tienes 3 leads.", input_tokens=40, output_tokens=10),
        LlmResult(text="Respuesta 2: Uno cerró ayer.", input_tokens=42, output_tokens=12),
        LlmResult(
            text="Respuesta de Comercial 2: Tu pipeline está vacío.",
            input_tokens=30,
            output_tokens=10,
        ),
    ]

    ctx = AssistantContext(
        settings=settings,
        db=db,
        client=mock_llm,
        budget=AssistantBudget(settings),
        clock=lambda: fake_now,
        memory=mem,
    )

    bot = CrmBot(db, FakeTelegram(), lambda: fake_now)
    cmd = handle(ctx, bot)

    u1 = User(
        id=10,
        telegram_id=1001,
        role="commercial",
        email="com1@kaisen.la",
        active=1,
        created_at=fake_now.isoformat(),
        deactivated_at=None,
    )
    u2 = User(
        id=20,
        telegram_id=2002,
        role="commercial",
        email="com2@kaisen.la",
        active=1,
        created_at=fake_now.isoformat(),
        deactivated_at=None,
    )

    # Turno 1 Comercial 1
    with db.tx() as tx:
        cmd(tx, u1, "/asistente pregunta ¿cuántos leads tengo?", fake_now)
    _run_deferred(bot)

    # Turno 2 Comercial 1
    with db.tx() as tx:
        cmd(tx, u1, "/asistente pregunta ¿cuándo cerró el último?", fake_now)
    _run_deferred(bot)

    # Turno 1 Comercial 2
    with db.tx() as tx:
        cmd(tx, u2, "/asistente pregunta ¿cómo va mi meta?", fake_now)
    _run_deferred(bot)


    # Comercial 1 debe tener 4 mensajes (2 turnos) en su sesión
    t1 = mem.get_transcript("crm:user:10:pregunta", user_id=10, role="commercial")
    assert len(t1) == 4
    assert "Respuesta 1" in t1[1]["content"]
    assert "Respuesta 2" in t1[3]["content"]

    # Comercial 2 debe tener 2 mensajes (1 turno) en su propia sesión
    t2 = mem.get_transcript("crm:user:20:pregunta", user_id=20, role="commercial")
    assert len(t2) == 2
    assert "Respuesta de Comercial 2" in t2[1]["content"]

    # Comercial 2 intenta consultar la sesión de Comercial 1 -> AccessDeniedError
    with pytest.raises(AccessDeniedError):
        mem.get_transcript("crm:user:10:pregunta", user_id=20, role="commercial")

    # Listar sesiones de Comercial 2 -> No incluye la de Comercial 1
    sessions_u2 = mem.list_sessions_for_user(user_id=20, role="commercial")
    assert len(sessions_u2) == 1
    assert sessions_u2[0].session_id == "crm:user:20:pregunta"

    mem.close()


def test_app_restart_preserves_conversation(tmp_path: Path, fake_now: datetime) -> None:
    """Criterio de salida: reiniciar el servicio preserva la conversación."""
    settings = make_settings(
        data_dir=str(tmp_path),
        assistant_enabled=True,
        assistant_api_key="sk-test",
    )
    clock = FakeClock(fake_now)

    # Instancia 1 de CrmApp
    app1 = CrmApp(
        settings,
        telegram=FakeTelegram(),
        email=FakeEmailSender(),
        runner=FakeRunner(),
        clock=clock.now,
    )
    with app1.db.tx() as tx:
        tx.execute(
            "INSERT INTO crm_users(id, telegram_id, role, email, active, created_at) "
            "VALUES (10, 1001, 'commercial', 'com1@kaisen.la', 1, ?)",
            (fake_now.isoformat(),),
        )

    mock_llm = AsyncMock()
    mock_llm.complete.return_value = LlmResult(
        text="Persistencia verificada",
        input_tokens=25,
        output_tokens=10,
    )
    app1.assistant_llm = mock_llm

    # Re-registramos con el mock
    ctx1 = AssistantContext(
        settings=settings,
        db=app1.db,
        client=mock_llm,
        budget=AssistantBudget(settings),
        clock=clock.now,
        memory=app1.assistant_memory,
    )
    cmd1 = handle(ctx1, app1.bot)
    u1 = User(
        id=10,
        telegram_id=1001,
        role="commercial",
        email="com1@kaisen.la",
        active=1,
        created_at=fake_now.isoformat(),
        deactivated_at=None,
    )

    with app1.db.tx() as tx:
        cmd1(tx, u1, "/asistente pregunta ¿funciona?", fake_now)
    _run_deferred(app1.bot)

    # Cerramos la primera instancia (simula parada del servicio)
    app1.close()

    # Instancia 2 de CrmApp (simula arranque tras parada)
    app2 = CrmApp(
        settings,
        telegram=FakeTelegram(),
        email=FakeEmailSender(),
        runner=FakeRunner(),
        clock=clock.now,
    )
    history = app2.assistant_memory.get_transcript(
        "crm:user:10:pregunta",
        user_id=10,
        role="commercial",
    )
    assert len(history) == 2
    assert "¿funciona?" in history[0]["content"]
    assert "Persistencia verificada" in history[1]["content"]
    app2.close()
