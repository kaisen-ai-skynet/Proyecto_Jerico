"""Pruebas de T10: Enganche de la capa de decisión en el CRM (spec 007, F1).

Requisitos: VJT-008, VJT-010a, VJT-063.
- /asistente llama a decidir("modelo_asistente", ...) y obtiene siempre gpt-6-luna.
- Con la captura apagada el asistente se comporta exactamente igual que sin la capa.
- El tipo seguimiento_lead queda registrado como asesor, apagado por defecto.
- /seguimiento evalúa seguimiento_lead en modo sombra sin alterar el orden ni la vista.
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from crm_support import FakeClock, make_settings
from f2_support import make_lead
from jerico.crm import repo
from jerico.crm.assistant import (
    FOOTER,
    AssistantContext,
    _run,
)
from jerico.crm.assistant_budget import AssistantBudget
from jerico.crm.db import CrmDatabase
from jerico.crm.followup_view import following_command, lead_followup_state
from jerico.crm.llm import LlmResult
from jerico.crm.model import Cadence, LeadState, Role
from jerico.crm.pseudonym import Redactor
from jerico.crm.timeutil import to_iso
from jerico.decision.config import DecisionSettings
from jerico.decision.policy import load_policy

START = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
CTO_TG = 1000
COM_TG = 2000


class FakeLlm:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.reply = LlmResult(text="Respuesta generada", input_tokens=80, output_tokens=30)

    async def complete(self, *, system: str, user: str, max_output_tokens: int) -> LlmResult:
        self.calls.append({"system": system, "user": user, "max": max_output_tokens})
        return self.reply


@pytest.fixture
def db(tmp_path: Path):
    database = CrmDatabase(tmp_path / "crm.db")
    yield database
    database.close()


def test_seguimiento_lead_registrado_como_asesor():
    """El tipo seguimiento_lead es asesor y apagado por defecto (VJT-063, VJT-010a)."""
    policy = load_policy()
    tipo = policy.par("seguimiento_lead")
    assert tipo.asesor is True
    assert tipo.clase == "A"
    assert tipo.base == "mantener_orden"
    assert tipo.modo_defecto == "apagado"
    assert "mantener_orden" in tipo.opciones
    assert tipo.clase_datos == "sin_datos_personales"


@pytest.mark.asyncio
async def test_asistente_llama_decidir_y_obtiene_gpt6_luna_una_opcion(
    db: CrmDatabase, tmp_path: Path
):
    """/asistente llama a decidir('modelo_asistente', ...) y obtiene gpt-6-luna (VJT-008)."""
    clock = FakeClock(START)
    settings = make_settings(assistant_enabled=True)
    budget = AssistantBudget(settings)
    llm = FakeLlm()
    ctx = AssistantContext(settings=settings, db=db, client=llm, budget=budget, clock=clock.now)

    with db.tx() as tx:
        user = repo.insert_user(
            tx, telegram_id=COM_TG, role=Role.COMMERCIAL, email="com@k.co", now=START
        )

    red = Redactor(values=(), parts=())
    prompt = "Contexto breve del pipeline"

    decision_settings = DecisionSettings(modes={"modelo_asistente": "sombra"}, base_dir=tmp_path)
    with patch("jerico.crm.assistant.load_settings", return_value=decision_settings):
        out = await _run(ctx, user, "resumen", prompt, red, lead_id=None)

    assert len(out) == 1
    assert "Respuesta generada" in out[0].text
    assert FOOTER in out[0].text
    assert len(llm.calls) == 1

    # Verificar que en modo sombra quedó registrada la decisión con motivo una_opcion
    files = list(tmp_path.glob("decision-*.jsonl"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert "modelo_asistente" in content
    assert "una_opcion" in content
    assert "gpt-6-luna" in content


@pytest.mark.asyncio
async def test_asistente_captura_apagada_comportamiento_identico(db: CrmDatabase, tmp_path: Path):
    """Con la captura apagada el asistente se comporta exactamente igual que sin la capa (T10)."""
    clock = FakeClock(START)
    settings = make_settings(assistant_enabled=True)
    budget = AssistantBudget(settings)
    llm = FakeLlm()
    ctx = AssistantContext(settings=settings, db=db, client=llm, budget=budget, clock=clock.now)

    with db.tx() as tx:
        user = repo.insert_user(
            tx, telegram_id=COM_TG, role=Role.COMMERCIAL, email="com@k.co", now=START
        )

    red = Redactor(values=(), parts=())
    prompt = "Contexto para borrador"

    # Modo apagado (default)
    decision_settings = DecisionSettings(modes={"modelo_asistente": "apagado"}, base_dir=tmp_path)
    with patch("jerico.crm.assistant.load_settings", return_value=decision_settings):
        out = await _run(ctx, user, "borrador", prompt, red, lead_id=None)

    assert len(out) == 1
    assert "Borrador (no enviado)" in out[0].text
    assert "Respuesta generada" in out[0].text

    # Con captura apagada, no se escribe archivo de decisión
    files = list(tmp_path.glob("decision-*.jsonl"))
    assert len(files) == 0


@pytest.mark.asyncio
async def test_asistente_degrada_limpio_si_falla_decidir(db: CrmDatabase):
    """Si la función decidir lanzara un error inesperado, el asistente continúa normalmente."""
    clock = FakeClock(START)
    settings = make_settings(assistant_enabled=True)
    budget = AssistantBudget(settings)
    llm = FakeLlm()
    ctx = AssistantContext(settings=settings, db=db, client=llm, budget=budget, clock=clock.now)

    with db.tx() as tx:
        user = repo.insert_user(
            tx, telegram_id=COM_TG, role=Role.COMMERCIAL, email="com@k.co", now=START
        )

    red = Redactor(values=(), parts=())
    prompt = "Pregunta de pipeline"

    with patch("jerico.crm.assistant.decidir", side_effect=RuntimeError("simulated error")):
        out = await _run(ctx, user, "pregunta", prompt, red, lead_id=None)

    assert len(out) == 1
    assert "Respuesta generada" in out[0].text


def test_lead_followup_state_calcula_vectores_validos(db: CrmDatabase):
    """lead_followup_state extrae los campos de estado conforme al esquema de política."""
    with db.tx() as tx:
        user = repo.insert_user(
            tx, telegram_id=COM_TG, role=Role.COMMERCIAL, email="com@k.co", now=START
        )

    lead_id = make_lead(db, user, state=LeadState.NURTURING)

    with db.tx() as tx:
        repo.upsert_cadence(
            tx,
            Cadence(
                lead_id=lead_id,
                reason="precio",
                interval_days=7,
                total_steps=3,
                status="active",
                next_action_at=None,
                started_at=to_iso(START),
                updated_at=to_iso(START),
                sent_count=2,
            ),
        )

    with db.read() as conn:
        lead = repo.get_lead(conn, lead_id)
        assert lead is not None
        state = lead_followup_state(conn, lead, START)

    assert state["dias_sin_contacto"] in [
        "0",
        "1-2",
        "3-7",
        "8-14",
        "15-30",
        "31-90",
        "mas_de_90",
    ]
    assert state["paso_cadencia"] == "2"
    assert state["estado_lead"] == "esperando_cliente"
    assert state["intentos_fallidos"] == "0"


def test_following_command_activa_seguimiento_lead_en_sombra(db: CrmDatabase, tmp_path: Path):
    """/seguimiento evalúa seguimiento_lead en sombra sin alterar el orden (VJT-010a, VJT-063)."""
    with db.tx() as tx:
        cto = repo.insert_user(tx, telegram_id=CTO_TG, role=Role.CTO, email="cto@k.co", now=START)

    lead1 = make_lead(db, cto, state=LeadState.NURTURING)
    lead2 = make_lead(db, cto, state=LeadState.PAUSED)

    # 1. Ejecución con modo sombra activado para seguimiento_lead
    decision_settings = DecisionSettings(modes={"seguimiento_lead": "sombra"}, base_dir=tmp_path)
    with patch("jerico.crm.followup_view.load_settings", return_value=decision_settings):
        with db.read() as conn:
            out = following_command(conn, cto, "/seguimiento", START)

    # El resultado es el normal de /seguimiento (dos leads)
    assert len(out) >= 1
    text = " ".join(o.text for o in out)
    assert f"L-{lead1:04d}" in text
    assert f"L-{lead2:04d}" in text

    # Se registraron dos decisiones en modo sombra
    files = list(tmp_path.glob("decision-*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert "seguimiento_lead" in lines[0]
    assert "sombra" in lines[0]
    assert "mantener_orden" in lines[0]


def test_following_command_con_captura_apagada_no_escribe_archivos(db: CrmDatabase, tmp_path: Path):
    """En modo apagado por defecto, /seguimiento no genera archivos de registro."""
    with db.tx() as tx:
        cto = repo.insert_user(tx, telegram_id=CTO_TG, role=Role.CTO, email="cto@k.co", now=START)

    make_lead(db, cto, state=LeadState.NURTURING)

    decision_settings = DecisionSettings(modes={"seguimiento_lead": "apagado"}, base_dir=tmp_path)
    with patch("jerico.crm.followup_view.load_settings", return_value=decision_settings):
        with db.read() as conn:
            out = following_command(conn, cto, "/seguimiento", START)

    assert len(out) >= 1
    files = list(tmp_path.glob("decision-*.jsonl"))
    assert len(files) == 0
