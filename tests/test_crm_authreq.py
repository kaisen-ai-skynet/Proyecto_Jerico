"""F2-T19 y T20 — Solicitud de autorización por correo y confirmación de la respuesta.

Requisitos: VCRM-068, 148, 149 (solicitud) y VCRM-119, 121, 141, 142, 143 (confirmación).
La autorización es lo que habilita todo el contacto comercial: aquí se prueba que nunca se registre
sola, que la decida únicamente quien corresponde y que no se pueda registrar dos veces.
"""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from crm_support import FakeEmailSender, make_settings
from f2_support import (
    COM_TG,
    CTO_TG,
    EMAIL,
    KEYS,
    NOW,
    UNSUB_ADDR,
    make_inbound,
    make_lead,
    make_sent,
)
from jerico.crm import authreq, delivery, gate, replies, repo
from jerico.crm.config import default_params
from jerico.crm.db import CrmDatabase
from jerico.crm.fingerprint import fingerprint
from jerico.crm.model import (
    SYSTEM_USER_ID,
    LeadState,
    Outgoing,
    ProposalKind,
    ProposalStatus,
    Role,
    User,
)
from jerico.crm.timeutil import to_iso

LAW_TG, OTHER_TG = 3000, 2100
SENT_ID = "<auth1@kaisen.test>"


@pytest.fixture
def db(tmp_path: Path) -> Iterator[CrmDatabase]:
    database = CrmDatabase(tmp_path / "crm.db")
    with database.tx() as tx:
        repo.set_meta(tx, "f2_activated_at", to_iso(NOW))
    yield database
    database.close()


@pytest.fixture
def users(db: CrmDatabase) -> dict[str, User]:
    with db.tx() as tx:
        return {
            "cto": repo.insert_user(tx, telegram_id=CTO_TG, role=Role.CTO, email="c@k.co", now=NOW),
            "com": repo.insert_user(
                tx, telegram_id=COM_TG, role=Role.COMMERCIAL, email="m@k.co", now=NOW
            ),
            "other": repo.insert_user(
                tx, telegram_id=OTHER_TG, role=Role.COMMERCIAL, email="o@k.co", now=NOW
            ),
            "law": repo.insert_user(
                tx, telegram_id=LAW_TG, role=Role.LAWYER, email="l@k.co", now=NOW
            ),
        }


def unauthorized_lead(db: CrmDatabase, user: User, **fields: Any) -> int:
    state = fields.pop("state", LeadState.CONTACTED)
    reject_reason = fields.pop("reject_reason", None)
    lead_id = make_lead(db, user, state=state, **fields)
    with db.tx() as tx:
        changes: dict[str, Any] = {"auth_status": "unauthorized"}
        if reject_reason is not None:
            changes["reject_reason"] = reject_reason
        repo.update_lead(tx, lead_id, changes, now=NOW)
        tx.execute("DELETE FROM crm_consents WHERE lead_id = ?", (lead_id,))
    return lead_id


def request(
    db: CrmDatabase, actor: User, lead_id: int, settings: Any = None, now: Any = NOW
) -> list[Outgoing]:
    with db.tx() as tx:
        return authreq.request_authorization(
            tx, actor, lead_id, now, KEYS, settings or make_settings(), "Kaisen AI"
        )


def texts(out: list[Outgoing]) -> str:
    return "\n".join(o.text for o in out)


def labels(out: list[Outgoing]) -> list[str]:
    return [label for o in out for row in o.buttons for label, _ in row]


def proposals(db: CrmDatabase) -> list[Any]:
    with db.read() as conn:
        return [
            repo.get_proposal(conn, r[0])
            for r in conn.execute("SELECT id FROM crm_proposals ORDER BY id")
        ]


# --- T19: solicitud -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vcrm068_solicitud_pasa_por_gate_y_solo_sale_tras_ok(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = unauthorized_lead(db, users["com"])

    out = request(db, users["com"], lead_id)

    (proposal,) = proposals(db)
    assert proposal.kind == ProposalKind.AUTH_REQUEST and proposal.status == ProposalStatus.PENDING
    assert proposal.step is None and proposal.approver_user_id == users["com"].id
    assert labels(out) == ["✅", "❌"]  # el aprobador debe decidir
    email = FakeEmailSender()
    await delivery.deliver_due(db, email, NOW, default_params(), KEYS, unsub_address=UNSUB_ADDR)
    assert email.attempts == []  # nada sale antes del ✅ (P-09)

    with db.tx() as tx:
        outcome = gate.approve(tx, users["com"], proposal.id, 1, NOW, KEYS)
    assert outcome.deliver_now is True
    await delivery.deliver_due(db, email, NOW, default_params(), KEYS, unsub_address=UNSUB_ADDR)

    (sent,) = email.sent
    assert sent.to == EMAIL and "List-Unsubscribe" in sent.headers
    assert "Responda BAJA para no recibir más mensajes." in sent.body
    with db.read() as conn:
        assert repo.get_proposal(conn, proposal.id).status == ProposalStatus.SENT  # type: ignore[union-attr]


def test_vcrm148_incluye_aviso_version_y_encargados(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = unauthorized_lead(db, users["com"])
    request(db, users["com"], lead_id, make_settings(data_processors="Telegram, Google, Zoho"))

    with db.read() as conn:
        version = repo.get_proposal_version(conn, proposals(db)[0].id, 1)
    assert version is not None
    assert "Telegram, Google, Zoho" in version.body
    assert "versión 1.0" in version.body
    assert "Ley 1581 de 2012" in version.body  # el aviso completo, no solo una referencia
    assert "responda" in version.body.lower() and "BAJA" in version.body
    assert version.content_hash == delivery.content_hash(version.subject, version.body)
    assert "Kaisen AI" in version.subject


def test_vcrm149_sin_aviso_no_prepara_y_responde(
    db: CrmDatabase, users: dict[str, User], tmp_path: Path
) -> None:
    lead_id = unauthorized_lead(db, users["com"])
    for settings in (
        make_settings(privacy_notice_file=tmp_path / "no-existe.md"),
        make_settings(privacy_notice_version="  "),
        make_settings(data_processors=" , "),
    ):
        out = request(db, users["com"], lead_id, settings)
        assert "falta" in texts(out).lower() and "configuración" in texts(out).lower()
        assert labels(out) == []
    assert proposals(db) == []


@pytest.mark.parametrize("why", ["suppressed", "opted_out", "revoked"])
def test_vcrm068_lead_suprimido_no_prepara(
    db: CrmDatabase, users: dict[str, User], why: str
) -> None:
    lead_id = unauthorized_lead(db, users["com"])
    with db.tx() as tx:
        if why == "suppressed":
            repo.add_suppression(tx, fingerprint(KEYS[0], EMAIL), at=NOW, medium="correo")
        elif why == "opted_out":
            repo.update_lead(tx, lead_id, {"state": "opted_out"}, now=NOW)
        else:
            repo.update_lead(tx, lead_id, {"auth_status": "revoked"}, now=NOW)

    out = request(db, users["com"], lead_id)

    assert proposals(db) == [] and "no se puede" in texts(out).lower()


@pytest.mark.asyncio
async def test_vcrm068_cuenta_en_cupo_semanal(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = unauthorized_lead(db, users["com"])
    # Un contacto ya enviado esta semana agota el cupo del lead (VCRM-076).
    make_sent(db, lead_id, users["com"], "<antes@kaisen.test>")
    request(db, users["com"], lead_id)
    (_, auth) = proposals(db)

    with db.tx() as tx:
        outcome = gate.approve(tx, users["com"], auth.id, 1, NOW + timedelta(hours=1), KEYS)

    assert outcome.deliver_now is False and "lunes" in texts(outcome.out).lower()


def test_solicitud_respeta_permisos_y_precondiciones(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = unauthorized_lead(db, users["com"])
    for actor in (users["law"], users["other"]):  # abogado y comercial ajeno
        assert "permiso" in texts(request(db, actor, lead_id)).lower()
    assert proposals(db) == []

    assert "no existe" in texts(request(db, users["com"], 999))
    sin_correo = unauthorized_lead(db, users["com"], email=None, phone_e164="+573007776655")
    assert "correo" in texts(request(db, users["com"], sin_correo)).lower()
    ya = make_lead(db, users["com"], email="ya@cliente.test", phone_e164="+573003332211")
    assert "ya cuenta" in texts(request(db, users["com"], ya))

    assert labels(request(db, users["cto"], lead_id))  # el CTO sí puede, con aprobador = comercial
    assert "abierta" in texts(request(db, users["com"], lead_id))  # ya hay una pendiente
    assert len(proposals(db)) == 1

    with db.tx() as tx:  # tras expirar se puede pedir otra (D-7)
        gate.expire_due(tx, NOW + timedelta(hours=49), on_step_consumed=None)
    assert labels(request(db, users["com"], lead_id, now=NOW + timedelta(hours=50)))
    assert len(proposals(db)) == 2


def test_solicitud_requiere_f2_activa(tmp_path: Path) -> None:
    database = CrmDatabase(tmp_path / "inactiva.db")
    with database.tx() as tx:
        com = repo.insert_user(
            tx, telegram_id=COM_TG, role=Role.COMMERCIAL, email="m@k.co", now=NOW
        )
    lead_id = unauthorized_lead(database, com)
    out = request(database, com, lead_id)
    assert "fase 2" in texts(out).lower() and proposals(database) == []
    database.close()


def test_el_aprobador_es_el_cto_si_el_lead_no_tiene_comercial(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = unauthorized_lead(db, users["com"])
    with db.tx() as tx:
        repo.update_lead(tx, lead_id, {"assigned_user_id": None}, now=NOW)

    out = request(db, users["cto"], lead_id)

    assert proposals(db)[0].approver_user_id == users["cto"].id
    assert {o.chat_id for o in out} == {CTO_TG}


# --- T20: confirmación de la respuesta ---------------------------------------------------------


def candidate(db: CrmDatabase, users: dict[str, User], **fields: Any) -> tuple[int, int]:
    """Lead sin autorización, con solicitud enviada y una respuesta propuesta como autorización."""
    lead_id = unauthorized_lead(db, users["com"], **fields)
    make_sent(
        db,
        lead_id,
        users["com"],
        SENT_ID,
        kind=ProposalKind.AUTH_REQUEST,
        step=None,
        body="Aviso de privacidad, versión 1.7\nResponda BAJA para no recibir más mensajes.",
    )
    with db.tx() as tx:
        replies.process_message(
            tx,
            make_inbound(1, "Sí, los autorizo.", in_reply_to=SENT_ID),
            NOW,
            default_params(),
            KEYS,
        )
        inbound = repo.list_inbound(tx)[0]
    assert inbound.classification == "auth_candidate"
    return lead_id, inbound.id


def confirm(db: CrmDatabase, actor: User, inbound_id: int, now: Any = NOW) -> list[Outgoing]:
    with db.tx() as tx:
        return authreq.confirm(tx, actor, inbound_id, now, KEYS)


def decline(db: CrmDatabase, actor: User, inbound_id: int, now: Any = NOW) -> list[Outgoing]:
    with db.tx() as tx:
        return authreq.decline(tx, actor, inbound_id, now)


def lead_state(db: CrmDatabase, lead_id: int) -> dict[str, Any]:
    with db.read() as conn:
        return dict(conn.execute("SELECT * FROM crm_leads WHERE id = ?", (lead_id,)).fetchone())


def test_vcrm119_propone_sin_registrar(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id, inbound_id = candidate(db, users)
    assert lead_state(db, lead_id)["auth_status"] == "unauthorized"
    with db.read() as conn:
        assert repo.lead_consents(conn, lead_id) == []
        assert repo.get_inbound(conn, inbound_id).decision == "pending"  # type: ignore[union-attr]


def test_vcrm141_confirma_registra_con_evidencia(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id, inbound_id = candidate(db, users)
    later = NOW + timedelta(hours=3)

    out = confirm(db, users["com"], inbound_id, later)

    assert lead_state(db, lead_id)["auth_status"] == "authorized"
    with db.read() as conn:
        (consent,) = repo.lead_consents(conn, lead_id)
        inbound = repo.get_inbound(conn, inbound_id)
    assert consent["status"] == "authorized"
    assert consent["medium"] == "respuesta al correo confirmada por el comercial"
    assert consent["actor_user_id"] == users["com"].id and consent["at"] == to_iso(later)
    assert consent["notice_version"] == "1.7"  # la versión del aviso que se ENVIÓ, no la actual
    assert "finalidades" in consent["purposes"].lower()
    assert consent["evidence_inbound_id"] == inbound_id
    assert inbound is not None and inbound.decision == "confirmed"
    assert (inbound.decided_by, inbound.decided_at) == (users["com"].id, to_iso(later))
    assert "autorización registrada" in texts(out).lower()


def test_vcrm141_solo_el_comercial_del_lead_decide(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id, inbound_id = candidate(db, users)
    for actor in (users["other"], users["law"], users["cto"]):
        out = confirm(db, actor, inbound_id)
        assert "permiso" in texts(out).lower()
        assert "permiso" in texts(decline(db, actor, inbound_id)).lower()
    assert lead_state(db, lead_id)["auth_status"] == "unauthorized"
    with db.read() as conn:
        assert repo.get_inbound(conn, inbound_id).decision == "pending"  # type: ignore[union-attr]
        denied = [a for a in repo.audit_rows(conn) if a["action"] == "permission_denied"]
    assert len(denied) == 6


def test_vcrm141_si_el_lead_no_tiene_comercial_decide_el_cto(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id, inbound_id = candidate(db, users)
    with db.tx() as tx:
        repo.update_lead(tx, lead_id, {"assigned_user_id": None}, now=NOW)
    assert "autorización registrada" in texts(confirm(db, users["cto"], inbound_id)).lower()


def test_vcrm142_rechaza_no_registra_y_deja_historial(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id, inbound_id = candidate(db, users)
    later = NOW + timedelta(minutes=30)

    out = decline(db, users["com"], inbound_id, later)

    assert lead_state(db, lead_id)["auth_status"] == "unauthorized"
    with db.read() as conn:
        assert repo.lead_consents(conn, lead_id) == []
        inbound = repo.get_inbound(conn, inbound_id)
        event = conn.execute(
            "SELECT * FROM crm_lead_events WHERE lead_id = ? AND field = 'authorization_reply'",
            (lead_id,),
        ).fetchone()
    assert inbound is not None and inbound.decision == "rejected"
    assert (inbound.decided_by, inbound.decided_at) == (users["com"].id, to_iso(later))
    assert event["actor_user_id"] == users["com"].id and event["new_value"] == "rejected"
    assert event["at"] == to_iso(later) and "no se registró" in texts(out).lower()


def test_vcrm143_doble_pulsacion(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id, inbound_id = candidate(db, users)
    confirm(db, users["com"], inbound_id)

    again = confirm(db, users["com"], inbound_id)
    other = decline(db, users["com"], inbound_id)

    assert "ya fue procesada" in texts(again) and "ya fue procesada" in texts(other)
    with db.read() as conn:
        assert len(repo.lead_consents(conn, lead_id)) == 1  # no se duplica la autorización
        assert repo.get_inbound(conn, inbound_id).decision == "confirmed"  # type: ignore[union-attr]
    # Y a la inversa: una respuesta ya rechazada no puede confirmarse después.
    lead2, inbound2 = candidate_second(db, users)
    decline(db, users["com"], inbound2)
    assert "ya fue procesada" in texts(confirm(db, users["com"], inbound2))
    assert lead_state(db, lead2)["auth_status"] == "unauthorized"


def candidate_second(db: CrmDatabase, users: dict[str, User]) -> tuple[int, int]:
    lead_id = unauthorized_lead(
        db, users["com"], email="dos@cliente.test", phone_e164="+573001239999"
    )
    make_sent(
        db, lead_id, users["com"], "<auth2@kaisen.test>", kind=ProposalKind.AUTH_REQUEST, step=None
    )
    with db.tx() as tx:
        replies.process_message(
            tx,
            make_inbound(
                2, "Autorizo", sender="dos@cliente.test", in_reply_to="<auth2@kaisen.test>"
            ),
            NOW,
            default_params(),
            KEYS,
        )
        inbound = next(i for i in repo.list_inbound(tx) if i.lead_id == lead_id)
    return lead_id, inbound.id


def test_vcrm121_confirmar_en_rejected_inicia_cadencia(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id, inbound_id = candidate(db, users, state=LeadState.REJECTED, reject_reason="precio")

    out = confirm(db, users["com"], inbound_id)

    row = lead_state(db, lead_id)
    assert (row["state"], row["auth_status"]) == ("nurturing", "authorized")
    with db.read() as conn:
        cadence = repo.get_cadence(conn, lead_id)
    assert cadence is not None and cadence.status == "active" and cadence.reason == "precio"
    assert "cadencia" in texts(out).lower()


def test_confirmar_con_el_lead_ya_en_baja_no_registra(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id, inbound_id = candidate(db, users)
    with db.tx() as tx:
        repo.update_lead(tx, lead_id, {"state": "opted_out", "auth_status": "revoked"}, now=NOW)

    out = confirm(db, users["com"], inbound_id)

    assert "baja" in texts(out).lower() and "no se registró" in texts(out).lower()
    with db.read() as conn:
        assert repo.lead_consents(conn, lead_id) == []
        assert repo.get_inbound(conn, inbound_id).decision == "rejected"  # type: ignore[union-attr]


def test_confirmar_una_respuesta_que_no_es_candidata_o_no_existe(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    assert "no existe" in texts(confirm(db, users["com"], 999))
    assert "no existe" in texts(decline(db, users["com"], 999))
    lead_id = make_lead(db, users["com"])
    make_sent(db, lead_id, users["com"], SENT_ID)
    with db.tx() as tx:
        replies.process_message(
            tx, make_inbound(1, "Hola", in_reply_to=SENT_ID), NOW, default_params(), KEYS
        )
        inbound = repo.list_inbound(tx)[0]
    assert inbound.classification == "review"
    out = confirm(db, users["com"], inbound.id)
    assert "no es una respuesta propuesta" in texts(out)
    assert SYSTEM_USER_ID == 0


def test_solicitud_sin_aprobador_activo_no_se_prepara(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = unauthorized_lead(db, users["com"])
    with db.tx() as tx:
        tx.execute("UPDATE crm_users SET active = 0 WHERE role IN ('commercial', 'cto')")
    out = request(db, users["cto"], lead_id)
    assert "aprobador" in texts(out).lower() and proposals(db) == []


def test_una_respuesta_sin_lead_no_se_puede_confirmar(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    with db.tx() as tx:
        replies.process_message(
            tx,
            make_inbound(1, "¿Quién es?", sender="nadie@otro.test"),
            NOW,
            default_params(),
            KEYS,
        )
        inbound = repo.list_inbound(tx)[0]
    out = confirm(db, users["cto"], inbound.id)
    assert "no está asociada" in texts(out)
    assert "no está asociada" in texts(decline(db, users["cto"], inbound.id))
