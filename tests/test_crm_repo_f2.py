"""Tests de la API del repositorio para Fase 2 (F2-T10).

Cubre cadencias, propuestas, versiones de propuesta, envíos y correos entrantes.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jerico.crm import repo
from jerico.crm.db import CrmDatabase
from jerico.crm.model import (
    Cadence,
    CadenceStatus,
    InboundAssociation,
    InboundClassification,
    InboundDecision,
    LeadState,
    ProposalKind,
    ProposalStatus,
    Role,
    SendStatus,
)
from jerico.crm.timeutil import to_iso

NOW = datetime(2026, 10, 11, 10, 0, 0, tzinfo=UTC)
WEEK_START = datetime(2026, 10, 5, 0, 0, 0, tzinfo=UTC)


@pytest.fixture
def db(tmp_path: Path) -> CrmDatabase:
    database = CrmDatabase(tmp_path / "crm_f2.db")
    return database


@pytest.fixture
def lead_and_user(db: CrmDatabase) -> tuple[int, int]:
    with db.tx() as conn:
        user = repo.insert_user(
            conn, telegram_id=999, role=Role.COMMERCIAL, email="com@k.co", now=NOW
        )
        lead_id = repo.insert_lead(
            conn,
            assigned_user_id=user.id,
            state=LeadState.ACCEPTED,
            now=NOW,
            fields={"name": "Cliente F2", "email": "cliente@k.co"},
        )
    return lead_id, user.id


# --- Cadencias ----------------------------------------------------------------------------


def test_cadence_crud_and_due(db: CrmDatabase, lead_and_user: tuple[int, int]) -> None:
    lead_id, _ = lead_and_user
    cad = Cadence(
        lead_id=lead_id,
        reason="precio",
        interval_days=30,
        total_steps=3,
        steps_done=0,
        sent_count=0,
        next_action_at=to_iso(NOW),
        last_sent_at=None,
        status=CadenceStatus.ACTIVE.value,
        started_at=to_iso(NOW),
        updated_at=to_iso(NOW),
    )
    with db.tx() as conn:
        assert repo.get_cadence(conn, lead_id) is None
        repo.upsert_cadence(conn, cad)
        found = repo.get_cadence(conn, lead_id)
        assert found is not None
        assert found.lead_id == lead_id
        assert found.reason == "precio"
        assert found.status == CadenceStatus.ACTIVE.value

        # Update con columna válida
        repo.update_cadence(conn, lead_id, steps_done=1, sent_count=1)
        up = repo.get_cadence(conn, lead_id)
        assert up is not None and up.steps_done == 1 and up.sent_count == 1

        # Error con columna desconocida
        with pytest.raises(ValueError, match="columna no permitida"):
            repo.update_cadence(conn, lead_id, campo_inventado="x")

        # due_cadences con límite exacto de fecha
        due = repo.due_cadences(conn, NOW)
        assert len(due) == 1 and due[0].lead_id == lead_id

        past = repo.due_cadences(conn, NOW - timedelta(seconds=1))
        assert len(past) == 0

        # Cadencia pausada no es due
        repo.update_cadence(conn, lead_id, status=CadenceStatus.PAUSED.value)
        assert len(repo.due_cadences(conn, NOW)) == 0


# --- Propuestas y versiones ---------------------------------------------------------------


def test_proposal_crud_versions_and_pending(
    db: CrmDatabase, lead_and_user: tuple[int, int]
) -> None:
    lead_id, user_id = lead_and_user
    with db.tx() as conn:
        expires = NOW + timedelta(hours=48)
        p_id = repo.insert_proposal(
            conn,
            lead_id=lead_id,
            kind=ProposalKind.FOLLOWUP,
            step=1,
            approver_user_id=user_id,
            expires_at=expires,
            created_at=NOW,
        )
        assert p_id is not None

        # Insert duplicado de followup en mismo lead y paso devuelve None (VCRM-028)
        assert (
            repo.insert_proposal(
                conn,
                lead_id=lead_id,
                kind=ProposalKind.FOLLOWUP,
                step=1,
                approver_user_id=user_id,
                expires_at=expires,
                created_at=NOW,
            )
            is None
        )

        p = repo.get_proposal(conn, p_id)
        assert p is not None
        assert p.id == p_id
        assert p.kind == ProposalKind.FOLLOWUP.value
        assert p.step == 1
        assert p.status == ProposalStatus.PENDING.value

        # Versiones
        repo.add_proposal_version(
            conn,
            proposal_id=p_id,
            version=1,
            subject="Asunto 1",
            body="Cuerpo 1",
            content_hash="hash1",
            author_user_id=user_id,
            created_at=NOW,
        )
        ver = repo.get_proposal_version(conn, p_id, 1)
        assert ver is not None
        assert ver.subject == "Asunto 1"
        assert ver.content_hash == "hash1"
        assert repo.get_proposal_version(conn, p_id, 2) is None

        # Update propuesta
        repo.update_proposal(conn, p_id, status=ProposalStatus.APPROVED.value, current_version=2)
        up = repo.get_proposal(conn, p_id)
        assert up is not None
        assert up.status == ProposalStatus.APPROVED.value
        assert up.current_version == 2

        with pytest.raises(ValueError, match="columna no permitida"):
            repo.update_proposal(conn, p_id, columna_invalida=123)

        # pending_proposals
        p2_id = repo.insert_proposal(
            conn,
            lead_id=lead_id,
            kind=ProposalKind.FOLLOWUP,
            step=2,
            approver_user_id=user_id,
            expires_at=NOW + timedelta(hours=2),
            created_at=NOW,
        )
        assert p2_id is not None
        # Al expirar en +2h, en NOW + 1h no está vencida
        assert len(repo.pending_proposals(conn, NOW + timedelta(hours=1))) == 0
        # En NOW + 2h sí está vencida
        assert len(repo.pending_proposals(conn, NOW + timedelta(hours=2))) == 1


def test_open_auth_request(db: CrmDatabase, lead_and_user: tuple[int, int]) -> None:
    lead_id, user_id = lead_and_user
    with db.tx() as conn:
        assert repo.open_auth_request(conn, lead_id) is None

        p_id = repo.insert_proposal(
            conn,
            lead_id=lead_id,
            kind=ProposalKind.AUTH_REQUEST,
            step=None,
            approver_user_id=user_id,
            expires_at=NOW + timedelta(hours=48),
            created_at=NOW,
        )
        assert p_id is not None
        open_req = repo.open_auth_request(conn, lead_id)
        assert open_req is not None and open_req.id == p_id

        # Una vez resuelta (ej. sent o cancelled), ya no está abierta
        repo.update_proposal(conn, p_id, status=ProposalStatus.SENT.value)
        assert repo.open_auth_request(conn, lead_id) is None


# --- Envíos -------------------------------------------------------------------------------


def test_send_crud_due_and_week_count(db: CrmDatabase, lead_and_user: tuple[int, int]) -> None:
    lead_id, user_id = lead_and_user
    with db.tx() as conn:
        p_id = repo.insert_proposal(
            conn,
            lead_id=lead_id,
            kind=ProposalKind.FOLLOWUP,
            step=1,
            approver_user_id=user_id,
            expires_at=NOW + timedelta(hours=48),
            created_at=NOW,
        )
        assert p_id is not None

        send_id = repo.insert_send(
            conn,
            proposal_id=p_id,
            version=1,
            approved_hash="hash_aprobado",
            approved_by=user_id,
            approved_at=NOW,
            scheduled_at=NOW,
            lead_id=lead_id,
            week_start=WEEK_START,
            next_attempt_at=NOW,
        )
        assert send_id > 0

        send = repo.get_send(conn, send_id)
        assert send is not None
        assert send.proposal_id == p_id
        assert send.status == SendStatus.SCHEDULED.value

        by_prop = repo.get_send_by_proposal(conn, p_id)
        assert by_prop is not None and by_prop.id == send_id

        # due_sends
        assert len(repo.due_sends(conn, NOW)) == 1
        assert len(repo.due_sends(conn, NOW - timedelta(seconds=1))) == 0

        # count_sends_in_week cuenta scheduled y sent
        assert repo.count_sends_in_week(conn, lead_id, WEEK_START) == 1
        assert repo.count_sends_in_week(conn, lead_id, WEEK_START + timedelta(days=7)) == 0

        # update_send
        repo.update_send(
            conn,
            send_id,
            status=SendStatus.SENT.value,
            rfc_message_id="<msg1@k.co>",
            sent_at=to_iso(NOW),
        )
        assert repo.get_send_by_message_id(conn, "<msg1@k.co>") is not None
        assert repo.get_send_by_message_id(conn, "<otro@k.co>") is None

        # Sigue contando como enviado esa semana
        assert repo.count_sends_in_week(conn, lead_id, WEEK_START) == 1

        # Cancelado no cuenta
        repo.update_send(conn, send_id, status=SendStatus.CANCELLED.value)
        assert repo.count_sends_in_week(conn, lead_id, WEEK_START) == 0

        with pytest.raises(ValueError, match="columna no permitida"):
            repo.update_send(conn, send_id, bad_col=1)


# --- Entrantes ----------------------------------------------------------------------------


def test_inbound_crud_and_list(db: CrmDatabase, lead_and_user: tuple[int, int]) -> None:
    lead_id, _ = lead_and_user
    with db.tx() as conn:
        inbound_id = repo.insert_inbound(
            conn,
            rfc_message_id="<inbound1@mail.com>",
            uid=101,
            received_at=NOW,
            sender_fp="fp_sha256",
            lead_id=lead_id,
            association=InboundAssociation.THREAD,
            classification=InboundClassification.AUTH_CANDIDATE,
            new_text="Acepto los términos",
        )
        assert inbound_id is not None

        # Idempotencia por rfc_message_id (VCRM-169)
        assert (
            repo.insert_inbound(
                conn,
                rfc_message_id="<inbound1@mail.com>",
                uid=102,
                received_at=NOW,
                sender_fp="fp_sha256",
                lead_id=lead_id,
                association=InboundAssociation.THREAD,
                classification=InboundClassification.AUTH_CANDIDATE,
                new_text="Duplicado",
            )
            is None
        )

        item = repo.get_inbound(conn, inbound_id)
        assert item is not None
        assert item.rfc_message_id == "<inbound1@mail.com>"
        assert item.classification == InboundClassification.AUTH_CANDIDATE.value
        assert item.decision == InboundDecision.PENDING.value

        # list_inbound con filtros
        assert len(repo.list_inbound(conn)) == 1
        assert len(repo.list_inbound(conn, decision=InboundDecision.PENDING)) == 1
        assert len(repo.list_inbound(conn, decision=InboundDecision.CONFIRMED)) == 0
        assert len(repo.list_inbound(conn, lead_id=lead_id)) == 1
        assert len(repo.list_inbound(conn, lead_id=99999)) == 0

        # update_inbound
        repo.update_inbound(conn, inbound_id, decision=InboundDecision.CONFIRMED.value)
        up = repo.get_inbound(conn, inbound_id)
        assert up is not None and up.decision == InboundDecision.CONFIRMED.value

        with pytest.raises(ValueError, match="columna no permitida"):
            repo.update_inbound(conn, inbound_id, columna_falsa="no")


def test_repo_f2_edge_cases_and_update_types(
    db: CrmDatabase, lead_and_user: tuple[int, int]
) -> None:
    lead_id, user_id = lead_and_user
    with db.tx() as conn:
        # Cadence: update sin campos es no-op; update con datetime y StrEnum
        repo.update_cadence(conn, lead_id)
        cad = Cadence(
            lead_id=lead_id,
            reason="precio",
            interval_days=30,
            total_steps=3,
            status=CadenceStatus.ACTIVE.value,
            started_at=to_iso(NOW),
            updated_at=to_iso(NOW),
        )
        repo.upsert_cadence(conn, cad)
        repo.update_cadence(conn, lead_id, next_action_at=NOW, status=CadenceStatus.PAUSED)
        found_cad = repo.get_cadence(conn, lead_id)
        assert found_cad is not None and found_cad.status == CadenceStatus.PAUSED.value

        # Proposal: update sin campos es no-op; update con datetime y StrEnum.
        # Insert con FK inválida captura IntegrityError y devuelve None.
        p_id = repo.insert_proposal(
            conn,
            lead_id=lead_id,
            kind=ProposalKind.FOLLOWUP,
            step=1,
            approver_user_id=user_id,
            expires_at=NOW,
            created_at=NOW,
        )
        assert p_id is not None
        repo.update_proposal(conn, p_id)
        repo.update_proposal(conn, p_id, expires_at=NOW, status=ProposalStatus.APPROVED)
        found_prop = repo.get_proposal(conn, p_id)
        assert found_prop is not None and found_prop.status == ProposalStatus.APPROVED.value
        # FK inválida en proposal
        assert (
            repo.insert_proposal(
                conn,
                lead_id=999999,
                kind=ProposalKind.FOLLOWUP,
                step=99,
                approver_user_id=user_id,
                expires_at=NOW,
                created_at=NOW,
            )
            is None
        )

        # Send: update sin campos es no-op; update con datetime y StrEnum
        s_id = repo.insert_send(
            conn,
            proposal_id=p_id,
            version=1,
            approved_hash="hash",
            approved_by=user_id,
            approved_at=NOW,
            scheduled_at=NOW,
            lead_id=lead_id,
            week_start=WEEK_START,
        )
        repo.update_send(conn, s_id)
        repo.update_send(conn, s_id, sent_at=NOW, status=SendStatus.SENT)
        found_send = repo.get_send(conn, s_id)
        assert found_send is not None and found_send.status == SendStatus.SENT.value

        # Inbound: update sin campos es no-op; update con datetime y StrEnum; insert con FK inválida
        in_id = repo.insert_inbound(
            conn,
            rfc_message_id="<edge@msg>",
            uid=1,
            received_at=NOW,
            sender_fp="fp",
            lead_id=lead_id,
            association=InboundAssociation.NONE,
            classification=InboundClassification.REVIEW,
            new_text="txt",
        )
        assert in_id is not None
        repo.update_inbound(conn, in_id)
        repo.update_inbound(conn, in_id, decided_at=NOW, decision=InboundDecision.REJECTED)
        found_inb = repo.get_inbound(conn, in_id)
        assert found_inb is not None and found_inb.decision == InboundDecision.REJECTED.value
        assert (
            repo.insert_inbound(
                conn,
                rfc_message_id="<badfk@msg>",
                uid=2,
                received_at=NOW,
                sender_fp="fp",
                lead_id=999999,
                association=InboundAssociation.NONE,
                classification=InboundClassification.REVIEW,
                new_text="txt",
            )
            is None
        )
