from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from crm_support import make_settings
from jerico.api import app
from jerico.crm.assistant import AssistantContext
from jerico.crm.assistant_budget import AssistantBudget
from jerico.crm.assistant_memory import AssistantMemory
from jerico.crm.db import CrmDatabase
from jerico.crm.llm import LlmResult
from jerico.crm.model import LeadState, ProposalKind
from jerico.crm.repo import add_proposal_version, insert_lead, insert_proposal
from jerico.web import set_web_context

AUTH_CTO = {"X-User-ID": "1", "Authorization": "Bearer test-api-token"}
AUTH_COM1 = {"X-User-ID": "10", "Authorization": "Bearer test-api-token"}
AUTH_COM2 = {"X-User-ID": "20", "Authorization": "Bearer test-api-token"}


@pytest.fixture
def fake_now() -> datetime:
    return datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


@pytest.fixture
def web_env(tmp_path: Path, fake_now: datetime):
    settings = make_settings(
        data_dir=str(tmp_path),
        assistant_enabled=True,
        assistant_api_key="sk-test",
    )
    db = CrmDatabase(tmp_path / "crm.db")
    with db.tx() as tx:
        # CTO
        tx.execute(
            "INSERT INTO crm_users(id, telegram_id, role, email, active, created_at) "
            "VALUES (1, 999, 'cto', 'cto@kaisen.la', 1, ?)",
            (fake_now.isoformat(),),
        )
        # Commercial 1
        tx.execute(
            "INSERT INTO crm_users(id, telegram_id, role, email, active, created_at) "
            "VALUES (10, 1001, 'commercial', 'com1@kaisen.la', 1, ?)",
            (fake_now.isoformat(),),
        )
        # Commercial 2
        tx.execute(
            "INSERT INTO crm_users(id, telegram_id, role, email, active, created_at) "
            "VALUES (20, 1002, 'commercial', 'com2@kaisen.la', 1, ?)",
            (fake_now.isoformat(),),
        )

    mem = AssistantMemory(tmp_path / "assistant_memory.db")
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = LlmResult(
        text="Respuesta del asistente web.",
        input_tokens=40,
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
    set_web_context(ctx)
    client = TestClient(app)
    return client, db, ctx, mock_llm


def test_pwa_manifest_service_worker_and_shell(web_env):
    client, _, _, _ = web_env
    manifest_resp = client.get("/manifest.json")
    assert manifest_resp.status_code == 200
    manifest = manifest_resp.json()
    assert manifest["short_name"] == "Jericó"
    assert manifest["display"] == "standalone"

    sw_resp = client.get("/sw.js")
    assert sw_resp.status_code == 200
    assert "addEventListener" in sw_resp.text

    shell_resp = client.get("/")
    assert shell_resp.status_code == 200
    assert "Jericó PWA" in shell_resp.text or "Jerico PWA" in shell_resp.text


def test_web_auth_failure_for_missing_or_deactivated_user(web_env):
    client, db, _, _ = web_env
    # Missing headers
    resp = client.get("/api/v1/web/leads")
    assert resp.status_code == 401

    # User does not exist
    resp = client.get("/api/v1/web/leads", headers={"X-User-ID": "9999"})
    assert resp.status_code == 401

    # Deactivated user
    with db.tx() as tx:
        tx.execute("UPDATE crm_users SET active = 0 WHERE id = 10")
    resp = client.get("/api/v1/web/leads", headers=AUTH_COM1)
    assert resp.status_code == 403


def test_web_leads_isolation_commercial_vs_cto(web_env, fake_now: datetime):
    client, db, _, _ = web_env
    with db.tx() as tx:
        lead1_id = insert_lead(
            tx,
            assigned_user_id=10,
            state=LeadState.ACCEPTED,
            now=fake_now,
            fields={
                "name": "Lead Uno",
                "email": "lead1@empresa.com",
                "phone_e164": "+573001112233",
                "company": "Empresa 1",
            },
        )
        lead2_id = insert_lead(
            tx,
            assigned_user_id=20,
            state=LeadState.ACCEPTED,
            now=fake_now,
            fields={
                "name": "Lead Dos",
                "email": "lead2@empresa.com",
                "phone_e164": "+573004445566",
                "company": "Empresa 2",
            },
        )

    # Commercial 1 only sees lead 1
    resp1 = client.get("/api/v1/web/leads", headers=AUTH_COM1)
    assert resp1.status_code == 200
    leads1 = resp1.json()["leads"]
    assert len(leads1) == 1
    assert leads1[0]["id"] == lead1_id

    # Commercial 2 only sees lead 2
    resp2 = client.get("/api/v1/web/leads", headers=AUTH_COM2)
    assert resp2.status_code == 200
    leads2 = resp2.json()["leads"]
    assert len(leads2) == 1
    assert leads2[0]["id"] == lead2_id

    # CTO sees both leads
    resp_cto = client.get("/api/v1/web/leads", headers=AUTH_CTO)
    assert resp_cto.status_code == 200
    leads_cto = resp_cto.json()["leads"]
    assert len(leads_cto) >= 2


def test_web_chat_endpoint(web_env):
    client, _, ctx, mock_llm = web_env
    resp = client.post(
        "/api/v1/web/chat",
        headers=AUTH_COM1,
        json={"prompt": "¿cómo está el pipeline de ventas?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "Respuesta del asistente web." in data["answer"]
    assert data["input_tokens"] == 40
    assert data["output_tokens"] == 15

    # Memory persistence verification
    transcript = ctx.memory.get_transcript(
        "crm:user:10:web_chat",
        user_id=10,
        role="commercial",
    )
    assert len(transcript) == 2
    assert "¿cómo está el pipeline" in transcript[0]["content"]
    assert "Respuesta del asistente web." in transcript[1]["content"]


def test_web_approvals_list_and_decide(web_env, fake_now: datetime):
    client, db, _, _ = web_env
    with db.tx() as tx:
        lead_id = insert_lead(
            tx,
            assigned_user_id=10,
            state=LeadState.ACCEPTED,
            now=fake_now,
            fields={
                "name": "Lead Propuesta",
                "email": "propuesta@empresa.com",
                "phone_e164": "+573009998877",
                "company": "Empresa Propuesta",
            },
        )
        prop_id = insert_proposal(
            tx,
            lead_id=lead_id,
            kind=ProposalKind.FOLLOWUP,
            step=1,
            approver_user_id=10,
            expires_at=fake_now + timedelta(hours=48),
            created_at=fake_now,
        )
        assert prop_id is not None
        add_proposal_version(
            tx,
            proposal_id=prop_id,
            version=1,
            subject="Seguimiento comercial",
            body="Cuerpo de seguimiento",
            content_hash="hash123",
            author_user_id=10,
            created_at=fake_now,
        )

    # List approvals
    resp = client.get("/api/v1/web/approvals", headers=AUTH_COM1)
    assert resp.status_code == 200
    approvals = resp.json()["approvals"]
    assert len(approvals) == 1
    assert approvals[0]["id"] == prop_id

    # Approve proposal
    appr_resp = client.post(f"/api/v1/web/approvals/{prop_id}/approve", headers=AUTH_COM1)
    assert appr_resp.status_code == 200
    assert appr_resp.json()["status"] == "approved"

    # Verify no more pending
    resp_empty = client.get("/api/v1/web/approvals", headers=AUTH_COM1)
    assert len(resp_empty.json()["approvals"]) == 0


def test_web_consumption_endpoint(web_env):
    client, _, _, _ = web_env
    resp = client.get("/api/v1/web/consumption", headers=AUTH_COM1)
    assert resp.status_code == 200
    data = resp.json()
    assert "daily_token_cap" in data
    assert "tokens_used_today" in data
    assert "calls_today" in data
    assert "user_daily_calls" in data
