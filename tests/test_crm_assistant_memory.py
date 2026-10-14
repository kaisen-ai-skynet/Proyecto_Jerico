"""Pruebas de memoria persistente del asistente de Jericó (Spec 005 - Fase A1).

Criterios de salida verificados:
1. Reiniciar el servicio no pierde la conversación (persistencia en SQLite WAL).
2. Aislamiento por usuario y rol (un comercial nunca ve la memoria de otro comercial ni del CTO).
3. Invariante de prompt de sistema inmutable por hash SHA-256.
4. Resúmenes de compactación persistidos en la sesión.
"""

from pathlib import Path

import pytest

from jerico.crm.assistant_memory import (
    AccessDeniedError,
    AssistantMemory,
    AssistantSessionRecord,
)
from jerico.crm.model import Role


def test_session_creation_and_attributes(tmp_path: Path) -> None:
    db_file = tmp_path / "assistant_state.db"
    mem = AssistantMemory(db_file)

    session = mem.get_or_create_session(
        session_id="crm:10:resumen",
        user_id=10,
        role=Role.COMMERCIAL.value,
        system_prompt="Eres un asistente comercial.",
        model="gpt-6-luna",
    )
    assert isinstance(session, AssistantSessionRecord)
    assert session.session_id == "crm:10:resumen"
    assert session.user_id == 10
    assert session.role == Role.COMMERCIAL.value
    assert session.model == "gpt-6-luna"
    assert len(session.system_prompt_hash) == 64  # SHA-256


def test_system_prompt_immutability(tmp_path: Path) -> None:
    db_file = tmp_path / "assistant_state.db"
    mem = AssistantMemory(db_file)

    mem.get_or_create_session(
        session_id="crm:10:resumen",
        user_id=10,
        role=Role.COMMERCIAL.value,
        system_prompt="Prompt base inmutable",
        model="gpt-6-luna",
    )

    # Intentar cambiar el prompt de sistema en la misma sesión debe fallar
    with pytest.raises(ValueError, match="inmutable"):
        mem.get_or_create_session(
            session_id="crm:10:resumen",
            user_id=10,
            role=Role.COMMERCIAL.value,
            system_prompt="Prompt alterado",
            model="gpt-6-luna",
        )


def test_retains_history_after_service_restart(tmp_path: Path) -> None:
    """Criterio de salida 1: reiniciar el servicio no pierde la conversación."""
    db_file = tmp_path / "assistant_state.db"

    # Instancia 1 del servicio
    mem1 = AssistantMemory(db_file)
    mem1.get_or_create_session(
        session_id="crm:10:chat",
        user_id=10,
        role=Role.COMMERCIAL.value,
        system_prompt="Prompt base",
        model="gpt-6-luna",
    )
    mem1.record_turn(
        session_id="crm:10:chat",
        user_id=10,
        role=Role.COMMERCIAL.value,
        user_prompt="¿Cuál es el estado de L-0001?",
        assistant_response="L-0001 está en contacto inicial.",
        model="gpt-6-luna",
        prompt_tokens=45,
        completion_tokens=20,
    )
    mem1.close()

    # Instancia 2 del servicio (simula reinicio completo)
    mem2 = AssistantMemory(db_file)
    history = mem2.get_transcript(
        session_id="crm:10:chat",
        user_id=10,
        role=Role.COMMERCIAL.value,
    )

    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "¿Cuál es el estado de L-0001?"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "L-0001 está en contacto inicial."

    usage = mem2.get_usage("crm:10:chat", "gpt-6-luna")
    assert usage is not None
    assert usage["prompt_tokens"] == 45
    assert usage["completion_tokens"] == 20
    mem2.close()


def test_isolation_between_two_commercials(tmp_path: Path) -> None:
    """Criterio de salida 2: prueba de aislamiento entre dos comerciales."""
    db_file = tmp_path / "assistant_state.db"
    mem = AssistantMemory(db_file)

    # Comercial A crea sesión y registra conversación
    mem.get_or_create_session(
        session_id="crm:comercial_a:resumen",
        user_id=101,
        role=Role.COMMERCIAL.value,
        system_prompt="Prompt A",
        model="gpt-6-luna",
    )
    mem.record_turn(
        session_id="crm:comercial_a:resumen",
        user_id=101,
        role=Role.COMMERCIAL.value,
        user_prompt="Datos confidenciales del lead de Comercial A",
        assistant_response="Resumen confidencial A",
        model="gpt-6-luna",
    )

    # Comercial B crea su propia sesión
    mem.get_or_create_session(
        session_id="crm:comercial_b:resumen",
        user_id=102,
        role=Role.COMMERCIAL.value,
        system_prompt="Prompt B",
        model="gpt-6-luna",
    )

    # Comercial B intenta acceder al historial de Comercial A -> DENEGADO
    with pytest.raises(AccessDeniedError, match="acceso denegado"):
        mem.get_transcript(
            session_id="crm:comercial_a:resumen",
            user_id=102,
            role=Role.COMMERCIAL.value,
        )

    # Comercial B intenta registrar un mensaje en la sesión de Comercial A -> DENEGADO
    with pytest.raises(AccessDeniedError, match="acceso denegado"):
        mem.record_turn(
            session_id="crm:comercial_a:resumen",
            user_id=102,
            role=Role.COMMERCIAL.value,
            user_prompt="Inyección de mensaje",
            assistant_response="Respuesta no autorizada",
            model="gpt-6-luna",
        )

    # Listar sesiones: Comercial B NO ve la sesión de Comercial A
    sessions_b = mem.list_sessions_for_user(user_id=102, role=Role.COMMERCIAL.value)
    session_ids_b = [s.session_id for s in sessions_b]
    assert "crm:comercial_b:resumen" in session_ids_b
    assert "crm:comercial_a:resumen" not in session_ids_b


def test_commercial_cannot_access_cto_sessions(tmp_path: Path) -> None:
    """Aislamiento estricto: el comercial nunca ve la del CTO."""
    db_file = tmp_path / "assistant_state.db"
    mem = AssistantMemory(db_file)

    mem.get_or_create_session(
        session_id="crm:cto:estrategia",
        user_id=1,
        role=Role.CTO.value,
        system_prompt="Estrategia CTO",
        model="gpt-6-luna",
    )
    mem.record_turn(
        session_id="crm:cto:estrategia",
        user_id=1,
        role=Role.CTO.value,
        user_prompt="Métricas de facturación global",
        assistant_response="Ingresos proyectados...",
        model="gpt-6-luna",
    )

    # Comercial intenta leer la sesión del CTO
    with pytest.raises(AccessDeniedError, match="acceso denegado"):
        mem.get_transcript(
            session_id="crm:cto:estrategia",
            user_id=101,
            role=Role.COMMERCIAL.value,
        )

    # Comercial lista sus sesiones: no debe aparecer la del CTO
    sessions = mem.list_sessions_for_user(user_id=101, role=Role.COMMERCIAL.value)
    assert all(s.session_id != "crm:cto:estrategia" for s in sessions)


def test_session_compaction_summary_lifecycle(tmp_path: Path) -> None:
    """Persistencia de resúmenes de compactación de contexto."""
    db_file = tmp_path / "assistant_state.db"
    mem = AssistantMemory(db_file)

    mem.get_or_create_session(
        session_id="crm:10:compact",
        user_id=10,
        role=Role.COMMERCIAL.value,
        system_prompt="Prompt base",
        model="gpt-6-luna",
    )

    assert mem.get_latest_summary("crm:10:compact") is None

    mem.save_summary(
        "crm:10:compact",
        "Resumen del historial: el lead pide cotización de software.",
    )
    summary = mem.get_latest_summary("crm:10:compact")
    assert summary == "Resumen del historial: el lead pide cotización de software."
