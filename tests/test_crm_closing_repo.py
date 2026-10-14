"""Pruebas del repositorio de cierre, contrato, firma y buzones (Spec 004)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jerico.crm.closing_model import (
    CandidateStatus,
    ContractStatus,
    LegalBasis,
    PackageStatus,
)
from jerico.crm.closing_repo import (
    active_mailboxes,
    contract_for_package,
    contracts_with_status,
    expired_contracts,
    get_candidate,
    get_contract,
    get_offer,
    get_package,
    insert_candidate,
    insert_contract,
    insert_offer,
    insert_package,
    insert_signature,
    latest_offer,
    live_package,
    mailbox_for_user,
    packages_sent,
    pending_candidates,
    purge_expired_candidates,
    set_candidate_status,
    set_mailbox_ok,
    set_package_status,
    signature_by_external,
    update_contract,
    update_signature,
    upsert_mailbox,
)
from jerico.crm.db import CrmDatabase
from jerico.crm.model import LeadState, Role
from jerico.crm.repo import insert_lead, insert_user

NOW = datetime(2026, 10, 13, 14, 0, tzinfo=UTC)


@pytest.fixture
def db(tmp_path: Path) -> Iterator[CrmDatabase]:
    database = CrmDatabase(tmp_path / "crm.db")
    yield database
    database.close()


@pytest.fixture
def base_data(db: CrmDatabase) -> tuple[int, int, int]:
    """Crea un usuario comercial, un usuario abogado y un lead base."""
    with db.tx() as tx:
        com = insert_user(tx, telegram_id=1001, role=Role.COMMERCIAL, email="com@k.co", now=NOW)
        law = insert_user(tx, telegram_id=1002, role=Role.LAWYER, email="law@k.co", now=NOW)
        lead_id = insert_lead(
            tx,
            assigned_user_id=com.id,
            state=LeadState.ACCEPTED,
            now=NOW,
            fields={
                "name": "Empresa Cliente SAS",
                "phone_e164": "+573001112233",
                "email": "cliente@empresa.co",
                "company": "Empresa Cliente SAS",
            },
        )
        return com.id, law.id, lead_id


def test_insert_and_get_offer(db: CrmDatabase, base_data: tuple[int, int, int]) -> None:
    com_id, _, lead_id = base_data
    lines = [
        ("Consultoría IA", 1, 10_000_000),
        ("Soporte Mensual", 3, 2_000_000),
    ]

    with db.tx() as tx:
        # Oferta 1 (valid_until como datetime)
        valid_until_dt = NOW + timedelta(days=15)
        offer1 = insert_offer(
            tx,
            lead_id=lead_id,
            currency="COP",
            payment_terms="50% anticipo, 50% entrega",
            valid_until=valid_until_dt,
            special_conditions="Incluye 2 revisiones",
            created_by=com_id,
            now=NOW,
            lines=lines,
        )
        assert offer1.id > 0
        assert offer1.lead_id == lead_id
        assert offer1.version == 1
        assert offer1.currency == "COP"
        assert len(offer1.lines) == 2
        assert offer1.lines[0].position == 1
        assert offer1.lines[0].description == "Consultoría IA"
        assert offer1.lines[0].quantity == 1
        assert offer1.lines[0].unit_price == 10_000_000
        assert offer1.lines[1].position == 2

        # Oferta 2 para el mismo lead (version incremental = 2, valid_until str)
        offer2 = insert_offer(
            tx,
            lead_id=lead_id,
            currency="COP",
            payment_terms="Contado",
            valid_until="2026-12-31T23:59:59Z",
            special_conditions=None,
            created_by=com_id,
            now=NOW,
            lines=[("Licencia Anual", 1, 15_000_000)],
        )
        assert offer2.version == 2

        # get_offer
        fetched = get_offer(tx, offer1.id)
        assert fetched is not None
        assert fetched.id == offer1.id
        assert fetched.version == 1
        assert len(fetched.lines) == 2

        # get_offer inexistente
        assert get_offer(tx, 9999) is None

        # latest_offer
        latest = latest_offer(tx, lead_id)
        assert latest is not None
        assert latest.id == offer2.id
        assert latest.version == 2

        # latest_offer para lead sin ofertas
        assert latest_offer(tx, 9999) is None


def test_insert_and_get_package_and_live_constraint(
    db: CrmDatabase, base_data: tuple[int, int, int]
) -> None:
    com_id, _, lead_id = base_data
    with db.tx() as tx:
        offer = insert_offer(
            tx,
            lead_id=lead_id,
            currency="COP",
            payment_terms="Contado",
            valid_until=None,
            special_conditions=None,
            created_by=com_id,
            now=NOW,
            lines=[("Servicio", 1, 1_000_000)],
        )

        # 1er paquete vivo (draft)
        pkg1 = insert_package(
            tx,
            lead_id=lead_id,
            offer_id=offer.id,
            content_hash="hash_v1",
            legal_basis=LegalBasis.AUTHORIZATION,
            created_by=com_id,
            now=NOW,
        )
        assert pkg1 is not None
        assert pkg1.lead_id == lead_id
        assert pkg1.version == 1
        assert pkg1.status == PackageStatus.DRAFT.value
        assert pkg1.legal_basis == "authorization"

        # Intento de insertar 2do paquete cuando pkg1 sigue vivo -> None por ux_packages_live
        pkg_conflict = insert_package(
            tx,
            lead_id=lead_id,
            offer_id=offer.id,
            content_hash="hash_v2",
            legal_basis=LegalBasis.LAWYER_CONFIRMED,
            created_by=com_id,
            now=NOW,
        )
        assert pkg_conflict is None

        # live_package
        live = live_package(tx, lead_id)
        assert live is not None
        assert live.id == pkg1.id

        # get_package
        assert get_package(tx, pkg1.id) is not None
        assert get_package(tx, 9999) is None


def test_package_status_transitions_and_packages_sent(
    db: CrmDatabase, base_data: tuple[int, int, int]
) -> None:
    com_id, law_id, lead_id = base_data
    with db.tx() as tx:
        offer = insert_offer(
            tx,
            lead_id=lead_id,
            currency="COP",
            payment_terms="50/50",
            valid_until=None,
            special_conditions=None,
            created_by=com_id,
            now=NOW,
            lines=[("Item", 1, 100)],
        )
        pkg = insert_package(
            tx,
            lead_id=lead_id,
            offer_id=offer.id,
            content_hash="h1",
            legal_basis=LegalBasis.AUTHORIZATION,
            created_by=com_id,
            now=NOW,
        )
        assert pkg is not None

        # Confirmar paquete
        set_package_status(tx, pkg.id, PackageStatus.CONFIRMED, confirmed_by=com_id)
        p_conf = get_package(tx, pkg.id)
        assert p_conf is not None
        assert p_conf.status == "confirmed"
        assert p_conf.confirmed_by == com_id
        assert p_conf.sent_at is None

        # Enviar paquete al abogado (sent_at como datetime)
        sent_time = NOW + timedelta(minutes=5)
        set_package_status(tx, pkg.id, PackageStatus.SENT, sent_at=sent_time)
        p_sent = get_package(tx, pkg.id)
        assert p_sent is not None
        assert p_sent.status == "sent"
        assert p_sent.sent_at is not None

        # packages_sent
        sent_list = packages_sent(tx)
        assert len(sent_list) == 1
        assert sent_list[0].id == pkg.id

        # Cancelar paquete para permitir nueva versión
        set_package_status(tx, pkg.id, PackageStatus.CANCELLED)
        assert live_package(tx, lead_id) is None

        # Ahora sí se permite nuevo paquete (versión 2)
        pkg2 = insert_package(
            tx,
            lead_id=lead_id,
            offer_id=offer.id,
            content_hash="h2",
            legal_basis="authorization",
            created_by=com_id,
            now=NOW,
        )
        assert pkg2 is not None
        assert pkg2.version == 2


def test_insert_and_update_contract(db: CrmDatabase, base_data: tuple[int, int, int]) -> None:
    com_id, law_id, lead_id = base_data
    with db.tx() as tx:
        offer = insert_offer(
            tx,
            lead_id=lead_id,
            currency="COP",
            payment_terms="Contado",
            valid_until=None,
            special_conditions=None,
            created_by=com_id,
            now=NOW,
            lines=[("Prod", 1, 500)],
        )
        pkg = insert_package(
            tx,
            lead_id=lead_id,
            offer_id=offer.id,
            content_hash="h1",
            legal_basis=LegalBasis.AUTHORIZATION,
            created_by=com_id,
            now=NOW,
        )
        assert pkg is not None

        # insert_contract
        contract = insert_contract(tx, package_id=pkg.id, now=NOW)
        assert contract is not None
        assert contract.package_id == pkg.id
        assert contract.status == ContractStatus.PACKAGE_SENT.value

        # Intento de 2do contrato vivo para el mismo paquete -> None por ux_contracts_live
        assert insert_contract(tx, package_id=pkg.id, now=NOW) is None

        # contract_for_package y get_contract
        c_fetched = contract_for_package(tx, pkg.id)
        assert c_fetched is not None
        assert c_fetched.id == contract.id
        assert get_contract(tx, contract.id) is not None
        assert get_contract(tx, 9999) is None
        assert contract_for_package(tx, 9999) is None

        # update_contract con columnas válidas
        exp_dt = NOW + timedelta(days=15)
        update_contract(
            tx,
            contract.id,
            status=ContractStatus.CONTRACT_UPLOADED,
            file_path="/data/contratos/c1.pdf",
            sha256="abc123sha",
            uploaded_by=law_id,
            expires_at=exp_dt,
        )
        updated = get_contract(tx, contract.id)
        assert updated is not None
        assert updated.status == "contract_uploaded"
        assert updated.file_path == "/data/contratos/c1.pdf"
        assert updated.sha256 == "abc123sha"
        assert updated.uploaded_by == law_id
        assert updated.expires_at is not None

        # update_contract con lista vacía
        update_contract(tx, contract.id)

        # update_contract con columna prohibida -> ValueError
        with pytest.raises(ValueError, match="columna no permitida"):
            update_contract(tx, contract.id, columna_inventada="hack")


def test_contracts_with_status_and_expired(
    db: CrmDatabase, base_data: tuple[int, int, int]
) -> None:
    com_id, _, lead_id = base_data
    with db.tx() as tx:
        offer = insert_offer(
            tx,
            lead_id=lead_id,
            currency="COP",
            payment_terms="Contado",
            valid_until=None,
            special_conditions=None,
            created_by=com_id,
            now=NOW,
            lines=[("Item", 1, 10)],
        )
        pkg = insert_package(
            tx,
            lead_id=lead_id,
            offer_id=offer.id,
            content_hash="h",
            legal_basis="authorization",
            created_by=com_id,
            now=NOW,
        )
        assert pkg is not None
        c1 = insert_contract(tx, package_id=pkg.id, now=NOW)
        assert c1 is not None

        # Estado inicial package_sent
        assert len(contracts_with_status(tx, ContractStatus.PACKAGE_SENT)) == 1
        assert len(contracts_with_status(tx, "signed")) == 0

        # Poner en sent_for_signature con expires_at en el pasado
        past_exp = NOW - timedelta(days=1)
        update_contract(
            tx,
            c1.id,
            status=ContractStatus.SENT_FOR_SIGNATURE,
            expires_at=past_exp,
        )

        expired = expired_contracts(tx, NOW)
        assert len(expired) == 1
        assert expired[0].id == c1.id

        # Si expires_at estuviera en el futuro, no aparece en expired
        future_exp = NOW + timedelta(days=5)
        update_contract(tx, c1.id, expires_at=future_exp)
        assert len(expired_contracts(tx, NOW)) == 0


def test_insert_and_update_signature(db: CrmDatabase, base_data: tuple[int, int, int]) -> None:
    com_id, _, lead_id = base_data
    with db.tx() as tx:
        offer = insert_offer(
            tx,
            lead_id=lead_id,
            currency="COP",
            payment_terms="Contado",
            valid_until=None,
            special_conditions=None,
            created_by=com_id,
            now=NOW,
            lines=[("A", 1, 1)],
        )
        pkg = insert_package(
            tx,
            lead_id=lead_id,
            offer_id=offer.id,
            content_hash="h",
            legal_basis="authorization",
            created_by=com_id,
            now=NOW,
        )
        assert pkg is not None
        c = insert_contract(tx, package_id=pkg.id, now=NOW)
        assert c is not None

        # Insert signature
        sig = insert_signature(
            tx,
            contract_id=c.id,
            provider="signwell",
            external_id="ext_doc_123",
            status="sent",
            now=NOW,
        )
        assert sig.id > 0
        assert sig.provider == "signwell"
        assert sig.external_id == "ext_doc_123"
        assert sig.status == "sent"

        # signature_by_external
        by_ext = signature_by_external(tx, "signwell", "ext_doc_123")
        assert by_ext is not None
        assert by_ext.id == sig.id
        assert signature_by_external(tx, "signwell", "no_existe") is None

        # update_signature
        now_signed = NOW + timedelta(hours=2)
        update_signature(
            tx,
            sig.id,
            status="completed",
            now=now_signed,
            evidence_path="/data/evidence/ev1.pdf",
            evidence_sha256="sha_evidence_123",
        )
        sig_updated = signature_by_external(tx, "signwell", "ext_doc_123")
        assert sig_updated is not None
        assert sig_updated.status == "completed"
        assert sig_updated.evidence_path == "/data/evidence/ev1.pdf"
        assert sig_updated.evidence_sha256 == "sha_evidence_123"


def test_mailbox_operations(db: CrmDatabase, base_data: tuple[int, int, int]) -> None:
    com_id, _, _ = base_data
    with db.tx() as tx:
        # Upsert inicial
        mb = upsert_mailbox(
            tx,
            user_id=com_id,
            address="comercial@kaisen.ai",
            secret_env="JERICO_MAILBOX_COM_PASSWORD",
        )
        assert mb.user_id == com_id
        assert mb.address == "comercial@kaisen.ai"
        assert mb.active == 1
        assert mb.last_ok_at is None

        # mailbox_for_user y active_mailboxes
        assert mailbox_for_user(tx, com_id) is not None
        assert mailbox_for_user(tx, 9999) is None
        assert len(active_mailboxes(tx)) == 1

        # set_mailbox_ok
        set_mailbox_ok(tx, mb.id, NOW)
        mb_ok = mailbox_for_user(tx, com_id)
        assert mb_ok is not None
        assert mb_ok.last_ok_at is not None

        # Re-upsert (actualiza dirección y secreto sin duplicar)
        mb2 = upsert_mailbox(
            tx,
            user_id=com_id,
            address="nuevo_comercial@kaisen.ai",
            secret_env="JERICO_MAILBOX_COM_PASSWORD_V2",
        )
        assert mb2.id == mb.id
        assert mb2.address == "nuevo_comercial@kaisen.ai"
        assert len(active_mailboxes(tx)) == 1


def test_candidates_insert_pending_status_and_purge(
    db: CrmDatabase, base_data: tuple[int, int, int]
) -> None:
    com_id, _, lead_id = base_data
    with db.tx() as tx:
        mb = upsert_mailbox(
            tx,
            user_id=com_id,
            address="c@k.co",
            secret_env="P",
        )

        rec_time = NOW - timedelta(days=2)
        exp_time = NOW - timedelta(minutes=1)

        # 1er candidato
        cand1 = insert_candidate(
            tx,
            mailbox_id=mb.id,
            message_id="<msg001@client.co>",
            sender_email="prospecto1@empresa.co",
            sender_name="Carlos Cliente",
            subject="Cotización Agente IA",
            received_at=rec_time,
            expires_at=exp_time,
        )
        assert cand1 is not None
        assert cand1.status == CandidateStatus.PENDING.value

        # Conflicto (mismo mailbox_id y message_id) -> None
        cand_dup = insert_candidate(
            tx,
            mailbox_id=mb.id,
            message_id="<msg001@client.co>",
            sender_email="otro@empresa.co",
            received_at=rec_time,
            expires_at=exp_time,
        )
        assert cand_dup is None

        # 2do candidato (a descartar)
        cand2 = insert_candidate(
            tx,
            mailbox_id=mb.id,
            message_id="<msg002@spam.co>",
            sender_email="spam@spam.co",
            received_at=rec_time,
            expires_at=exp_time,
        )
        assert cand2 is not None

        # 3er candidato (registrado)
        cand3 = insert_candidate(
            tx,
            mailbox_id=mb.id,
            message_id="<msg003@lead.co>",
            sender_email="lead_reg@empresa.co",
            received_at=rec_time,
            expires_at=exp_time,
        )
        assert cand3 is not None

        # 4to candidato (no expirado)
        cand4 = insert_candidate(
            tx,
            mailbox_id=mb.id,
            message_id="<msg004@fresh.co>",
            sender_email="fresh@fresh.co",
            received_at=NOW,
            expires_at=NOW + timedelta(days=7),
        )
        assert cand4 is not None

        # get_candidate
        assert get_candidate(tx, cand1.id) is not None
        assert get_candidate(tx, 9999) is None

        # pending_candidates
        assert pending_candidates(tx, []) == []
        pending = pending_candidates(tx, [mb.id])
        assert len(pending) == 4

        # Cambiar estados
        set_candidate_status(tx, cand2.id, CandidateStatus.DISCARDED)
        set_candidate_status(tx, cand3.id, CandidateStatus.REGISTERED, lead_id=lead_id)

        c2_updated = get_candidate(tx, cand2.id)
        assert c2_updated is not None
        assert c2_updated.status == "discarded"

        c3_updated = get_candidate(tx, cand3.id)
        assert c3_updated is not None
        assert c3_updated.status == "registered"
        assert c3_updated.lead_id == lead_id

        # Purga de candidatos expirados:
        # cand1 (pending, vencido) -> borrado
        # cand2 (discarded, vencido) -> borrado
        # cand3 (registered, vencido) -> NO borrado, pero se anonimiza
        # (sender_email='', sender_name='', subject='')
        # cand4 (pending, no vencido) -> permanece intacto
        purged_count = purge_expired_candidates(tx, NOW)
        assert purged_count == 2

        assert get_candidate(tx, cand1.id) is None
        assert get_candidate(tx, cand2.id) is None

        c3_anon = get_candidate(tx, cand3.id)
        assert c3_anon is not None
        assert c3_anon.status == "registered"
        assert c3_anon.sender_email == ""
        assert c3_anon.sender_name == ""
        assert c3_anon.subject == ""

        c4_alive = get_candidate(tx, cand4.id)
        assert c4_alive is not None
        assert c4_alive.sender_email == "fresh@fresh.co"
