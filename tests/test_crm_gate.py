"""F2-T14 — Gate ✅/❌: aprobar, rechazar, cancelar, reescribir y expirar (P-09, OBJ-2).

Requisitos: VCRM-029 (hasta programar), 030, 031, 032, 033, 034, 035, 036 y 099.
"""

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from f2_support import BODY, COM_TG, CTO_TG, KEYS, NOW, SUBJECT, bog, make_lead, make_proposal
from jerico.crm import delivery, gate, repo
from jerico.crm.db import CrmDatabase
from jerico.crm.model import (
    LeadState,
    Outgoing,
    Proposal,
    ProposalKind,
    ProposalStatus,
    Role,
    SendStatus,
    User,
)
from jerico.crm.timeutil import to_iso

OTHER_TG, LAW_TG = 2100, 3000


@pytest.fixture
def db(tmp_path: Path) -> Iterator[CrmDatabase]:
    database = CrmDatabase(tmp_path / "crm.db")
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


class Hook:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def __call__(
        self,
        conn: sqlite3.Connection,
        lead_id: int,
        outcome: str,
        now: datetime,
        sent_at: datetime | None,
    ) -> list[Outgoing]:
        self.calls.append((lead_id, outcome))
        return []


def proposal_of(db: CrmDatabase, proposal_id: int) -> Proposal:
    with db.read() as conn:
        proposal = repo.get_proposal(conn, proposal_id)
    assert proposal is not None
    return proposal


def do_approve(
    db: CrmDatabase,
    actor: User,
    proposal_id: int,
    version: int = 1,
    now: datetime = NOW,
) -> gate.GateOutcome:
    with db.tx() as tx:
        return gate.approve(tx, actor, proposal_id, version, now, KEYS)


def texts(out: list[Outgoing]) -> str:
    return "\n".join(o.text for o in out)


def labels(out: list[Outgoing]) -> list[str]:
    return [label for o in out for row in o.buttons for label, _ in row]


def test_presentar_muestra_lo_que_se_enviara_con_ok_y_no(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])

    with db.read() as conn:
        out = gate.present(conn, proposal_id)

    assert [o.chat_id for o in out] == [COM_TG]
    assert SUBJECT in out[0].text and BODY in out[0].text  # el aprobador ve el texto exacto
    assert labels(out) == ["✅", "❌"]
    assert out[0].buttons[0][0][1] == f"v1:gok:{proposal_id}:1"
    assert out[0].buttons[0][1][1] == f"v1:gno:{proposal_id}:1"


def test_presentar_un_texto_largo_lo_parte_sin_recortarlo(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    long_body = "\n".join(f"Línea {i} con texto de relleno." for i in range(400))
    proposal_id = make_proposal(db, lead_id, users["com"], body=long_body)
    with db.read() as conn:
        out = gate.present(conn, proposal_id)
    assert len(out) > 1 and all(len(o.text) <= 4096 for o in out)
    assert "".join(o.text for o in out).count("Línea ") == 400  # nada se pierde
    assert labels(out[:-1]) == [] and labels(out[-1:]) == ["✅", "❌"]  # botones al final


def test_vcrm036_hash_aprobado_se_guarda_y_programa(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])

    outcome = do_approve(db, users["com"], proposal_id)

    assert outcome.deliver_now is True  # dentro de franja y de cupo: primer intento en línea
    with db.read() as conn:
        send = repo.get_send_by_proposal(conn, proposal_id)
        proposal = repo.get_proposal(conn, proposal_id)
    assert send is not None and proposal is not None
    assert send.approved_hash == delivery.content_hash(SUBJECT, BODY)
    assert (send.approved_by, send.status) == (users["com"].id, SendStatus.SCHEDULED)
    assert proposal.status == ProposalStatus.APPROVED
    assert "Aprobado" in texts(outcome.out)


def test_vcrm100_aprobar_fuera_de_franja_difiere_e_informa(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])

    outcome = do_approve(db, users["com"], proposal_id, now=bog(14, 20, 0))

    assert outcome.deliver_now is False
    assert "jueves" in texts(outcome.out).lower() and "franja" in texts(outcome.out)


def test_vcrm030_doble_pulsacion(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])
    do_approve(db, users["com"], proposal_id)

    again = do_approve(db, users["com"], proposal_id)
    rejected_after = gate_reject(db, users["com"], proposal_id)

    assert "ya fue procesada" in texts(again.out) and again.deliver_now is False
    assert "ya fue procesada" in texts(rejected_after)
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM crm_sends").fetchone()[0] == 1


def gate_reject(
    db: CrmDatabase, actor: User, proposal_id: int, version: int = 1, now: datetime = NOW
) -> list[Outgoing]:
    with db.tx() as tx:
        return gate.reject(tx, actor, proposal_id, version, now)


def test_vcrm031_rechazo_ofrece_opciones(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = make_lead(db, users["com"])
    followup = make_proposal(db, lead_id, users["com"])

    out = gate_reject(db, users["com"], followup)

    assert labels(out) == ["Cancelar envío", "Reescribir"]
    assert proposal_of(db, followup).status == ProposalStatus.PENDING  # aún no se resolvió
    # La solicitud de autorización es texto legal: solo se puede cancelar, no reescribir.
    other = make_lead(db, users["com"], email="b@cliente.test", phone_e164="+573005550000")
    auth = make_proposal(db, other, users["com"], kind=ProposalKind.AUTH_REQUEST, step=None)
    assert labels(gate_reject(db, users["com"], auth)) == ["Cancelar envío"]


def test_vcrm032_cancelar_salta_paso(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])
    hook = Hook()

    with db.tx() as tx:
        out = gate.cancel(tx, users["com"], proposal_id, NOW, on_step_consumed=hook)

    proposal = proposal_of(db, proposal_id)
    assert proposal.status == ProposalStatus.CANCELLED
    assert (proposal.resolved_by, proposal.resolved_at) == (users["com"].id, to_iso(NOW))
    assert hook.calls == [(lead_id, "cancelled")]  # la cadencia pasa al paso siguiente
    assert "cancelado" in texts(out).lower()
    with db.read() as conn:
        assert repo.get_send_by_proposal(conn, proposal_id) is None  # nada que enviar
    with db.tx() as tx:  # cancelar de nuevo no repite el efecto
        again = gate.cancel(tx, users["com"], proposal_id, NOW, on_step_consumed=hook)
    assert "ya fue procesada" in texts(again) and len(hook.calls) == 1


def test_vcrm033_reescribir_nueva_version_reinicia_plazo(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])
    later = NOW + timedelta(hours=30)

    with db.tx() as tx:
        asked = gate.start_rewrite(tx, users["com"], proposal_id, later)
    assert "texto" in texts(asked).lower()
    with db.tx() as tx:
        out = gate.submit_rewrite(
            tx, users["com"], "Hola Ana,\nTexto nuevo.\x00", later, sender_name="Kaisen AI"
        )

    with db.read() as conn:
        proposal = repo.get_proposal(conn, proposal_id)
        v1 = repo.get_proposal_version(conn, proposal_id, 1)
        v2 = repo.get_proposal_version(conn, proposal_id, 2)
        assert repo.get_pending_input(conn, users["com"].id, later) is None  # ya se consumió
    assert proposal is not None and v1 is not None and v2 is not None
    assert proposal.current_version == 2 and proposal.status == ProposalStatus.PENDING
    assert proposal.expires_at == to_iso(later + timedelta(hours=48))  # D-6: reinicia el plazo
    assert v1.body == BODY  # la versión anterior se conserva
    assert v2.body.startswith("Hola Ana,\nTexto nuevo.") and "\x00" not in v2.body
    assert "Responda BAJA para no recibir más mensajes." in v2.body  # el pie legal se reañade
    assert v2.subject == SUBJECT and v2.content_hash == delivery.content_hash(v2.subject, v2.body)
    assert out[-1].buttons[0][0][1] == f"v1:gok:{proposal_id}:2"  # ✅ de la versión nueva
    assert labels(out) == ["✅", "❌"]
    # Todavía no se envió nada: hace falta una nueva pulsación de ✅.
    with db.read() as conn:
        assert repo.get_send_by_proposal(conn, proposal_id) is None


def test_vcrm033_reescribir_rechaza_texto_vacio_o_excesivo(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])
    with db.tx() as tx:
        gate.start_rewrite(tx, users["com"], proposal_id, NOW)
    for bad in ("   \n ", "x" * 3001):
        with db.tx() as tx:
            out = gate.submit_rewrite(tx, users["com"], bad, NOW, sender_name="Kaisen AI")
        assert out and "no válido" in texts(out).lower()
        with db.read() as conn:
            assert (
                repo.get_pending_input(conn, users["com"].id, NOW) is not None
            )  # puede reintentar
            assert repo.get_proposal_version(conn, proposal_id, 2) is None
    with db.tx() as tx:  # sin entrada pendiente el texto no es para el gate
        assert gate.submit_rewrite(tx, users["other"], "hola", NOW, sender_name="Kaisen AI") == []


def test_vcrm099_aprobar_version_obsoleta(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])
    with db.tx() as tx:
        gate.start_rewrite(tx, users["com"], proposal_id, NOW)
        gate.submit_rewrite(tx, users["com"], "Texto nuevo", NOW, sender_name="Kaisen AI")

    stale = do_approve(db, users["com"], proposal_id, version=1)

    assert stale.deliver_now is False
    assert "reemplazada" in texts(stale.out) and "versión vigente: 2" in texts(stale.out)
    with db.read() as conn:
        assert repo.get_send_by_proposal(conn, proposal_id) is None
    assert do_approve(db, users["com"], proposal_id, version=2).deliver_now is True


def test_vcrm034_expira_a_las_48h(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = make_lead(db, users["com"])
    followup = make_proposal(db, lead_id, users["com"])
    other = make_lead(db, users["com"], email="b@cliente.test", phone_e164="+573005550000")
    auth = make_proposal(db, other, users["com"], kind=ProposalKind.AUTH_REQUEST, step=None)
    hook = Hook()
    deadline = NOW + timedelta(hours=48)

    with db.tx() as tx:
        assert gate.expire_due(tx, deadline - timedelta(seconds=1), on_step_consumed=hook) == []
    with db.tx() as tx:
        out = gate.expire_due(tx, deadline, on_step_consumed=hook)

    assert proposal_of(db, followup).status == ProposalStatus.EXPIRED
    assert proposal_of(db, auth).status == ProposalStatus.EXPIRED
    assert hook.calls == [(lead_id, "expired")]  # solo el seguimiento consume un paso (D-7)
    assert len(out) == 2 and all("expir" in o.text.lower() for o in out)
    with db.tx() as tx:  # idempotente
        assert gate.expire_due(tx, deadline + timedelta(hours=1), on_step_consumed=hook) == []


def test_vcrm034_aprobar_tras_expirar(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])

    outcome = do_approve(db, users["com"], proposal_id, now=NOW + timedelta(hours=49))

    assert outcome.deliver_now is False and "expiró" in texts(outcome.out)
    assert proposal_of(db, proposal_id).status == ProposalStatus.EXPIRED
    with db.read() as conn:
        assert repo.get_send_by_proposal(conn, proposal_id) is None
    again = do_approve(db, users["com"], proposal_id, now=NOW + timedelta(hours=50))
    assert "expiró" in texts(again.out)  # ✅ tardío no la revive


@pytest.mark.parametrize("who", ["other", "law"])
def test_vcrm035_no_aprobador_audita(db: CrmDatabase, users: dict[str, User], who: str) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])
    actor = users[who]

    approved = do_approve(db, actor, proposal_id)
    rejected = gate_reject(db, actor, proposal_id)
    with db.tx() as tx:
        cancelled = gate.cancel(tx, actor, proposal_id, NOW, on_step_consumed=None)
        rewrite = gate.start_rewrite(tx, actor, proposal_id, NOW)

    assert approved.deliver_now is False
    for out in (approved.out, rejected, cancelled, rewrite):
        assert "permiso" in texts(out).lower()
    assert proposal_of(db, proposal_id).status == ProposalStatus.PENDING
    with db.read() as conn:
        denied = [a for a in repo.audit_rows(conn) if a["action"] == "permission_denied"]
        assert len(denied) == 4 and denied[0]["actor"] == f"user:{actor.id}"
        assert repo.get_send_by_proposal(conn, proposal_id) is None
        assert repo.get_pending_input(conn, actor.id, NOW) is None


def test_el_cto_puede_aprobar_cualquier_propuesta(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])  # aprobador: el comercial

    outcome = do_approve(db, users["cto"], proposal_id)

    assert outcome.deliver_now is True
    with db.read() as conn:
        send = repo.get_send_by_proposal(conn, proposal_id)
    assert send is not None and send.approved_by == users["cto"].id


def test_aprobar_con_el_lead_ya_no_apto_bloquea_la_propuesta(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])
    with db.tx() as tx:
        repo.update_lead(tx, lead_id, {"state": LeadState.PAUSED.value}, now=NOW)

    outcome = do_approve(db, users["com"], proposal_id)

    assert outcome.deliver_now is False and "cancelado por estado" in texts(outcome.out)
    assert proposal_of(db, proposal_id).status == ProposalStatus.BLOCKED
    with db.read() as conn:
        assert repo.get_send_by_proposal(conn, proposal_id) is None


def test_propuesta_inexistente_responde_sin_romper(db: CrmDatabase, users: dict[str, User]) -> None:
    assert "no existe" in texts(do_approve(db, users["com"], 999).out)
    assert "no existe" in texts(gate_reject(db, users["com"], 999))
    with db.tx() as tx:
        assert "no existe" in texts(gate.cancel(tx, users["com"], 999, NOW, on_step_consumed=None))
        assert "no existe" in texts(gate.start_rewrite(tx, users["com"], 999, NOW))
    with db.read() as conn:
        assert gate.present(conn, 999) == []


def test_reescribir_no_aplica_a_solicitudes_ni_a_propuestas_cerradas(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    auth = make_proposal(db, lead_id, users["com"], kind=ProposalKind.AUTH_REQUEST, step=None)
    with db.tx() as tx:
        out = gate.start_rewrite(tx, users["com"], auth, NOW)
    assert "no se puede reescribir" in texts(out)
    with db.read() as conn:
        assert repo.get_pending_input(conn, users["com"].id, NOW) is None

    followup = make_proposal(db, lead_id, users["com"])
    with db.tx() as tx:
        gate.cancel(tx, users["com"], followup, NOW, on_step_consumed=None)
        assert "ya fue procesada" in texts(gate.start_rewrite(tx, users["com"], followup, NOW))


def test_reescribir_se_cierra_si_la_propuesta_cambia_antes_del_texto(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])

    # La cancelan (p. ej. desde otro dispositivo) mientras se espera el texto nuevo.
    with db.tx() as tx:
        gate.start_rewrite(tx, users["com"], proposal_id, NOW)
        gate.cancel(tx, users["cto"], proposal_id, NOW, on_step_consumed=None)
        out = gate.submit_rewrite(tx, users["com"], "Texto", NOW, sender_name="Kaisen AI")
    assert "ya fue procesada" in texts(out)
    with db.read() as conn:
        assert repo.get_pending_input(conn, users["com"].id, NOW) is None
        assert repo.get_proposal_version(conn, proposal_id, 2) is None

    # Se vence el plazo mientras se escribe: no se crea versión y la propuesta expira.
    second = make_proposal(db, lead_id, users["com"], step=2)
    hook = Hook()
    started = NOW + timedelta(hours=47, minutes=45)
    later = NOW + timedelta(hours=48, minutes=5)  # la entrada (30 min) sigue vigente; el gate no
    with db.tx() as tx:
        gate.start_rewrite(tx, users["com"], second, started)
        out = gate.submit_rewrite(
            tx, users["com"], "Texto", later, sender_name="Kaisen AI", on_step_consumed=hook
        )
    assert "expiró" in texts(out) and hook.calls == [(lead_id, "expired")]
    assert proposal_of(db, second).status == ProposalStatus.EXPIRED

    # El usuario deja de estar autorizado mientras tanto.
    third = make_proposal(db, lead_id, users["com"], step=3)
    with db.tx() as tx:
        gate.start_rewrite(tx, users["com"], third, NOW)
        tx.execute("UPDATE crm_users SET active = 0 WHERE id = ?", (users["com"].id,))
        refreshed = repo.get_user(tx, users["com"].id)
        assert refreshed is not None
        denied = gate.submit_rewrite(tx, refreshed, "Texto", NOW, sender_name="Kaisen AI")
    assert "permiso" in texts(denied)
    with db.read() as conn:
        assert repo.get_pending_input(conn, users["com"].id, NOW) is None


def test_rechazar_versiones_viejas_o_propuestas_vencidas_o_cerradas(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])
    with db.tx() as tx:
        gate.start_rewrite(tx, users["com"], proposal_id, NOW)
        gate.submit_rewrite(tx, users["com"], "Texto nuevo", NOW, sender_name="Kaisen AI")

    assert "reemplazada" in texts(gate_reject(db, users["com"], proposal_id, version=1))

    hook = Hook()
    with db.tx() as tx:
        out = gate.reject(
            tx, users["com"], proposal_id, 2, NOW + timedelta(hours=49), on_step_consumed=hook
        )
    assert "expiró" in texts(out) and hook.calls == [(lead_id, "expired")]
    assert "expiró" in texts(gate_reject(db, users["com"], proposal_id, version=2))


def test_vcrm033_si_el_bot_ya_consumio_la_entrada_un_texto_invalido_la_repone(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    """El bot borra la entrada pendiente antes de llamar al gate y se la pasa explícita."""
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])
    with db.tx() as tx:
        gate.start_rewrite(tx, users["com"], proposal_id, NOW)
        pending = repo.get_pending_input(tx, users["com"].id, NOW)
        assert pending is not None
        repo.clear_pending_input(tx, users["com"].id)  # lo que hace CrmBot._route

        out = gate.submit_rewrite(
            tx, users["com"], "  ", NOW, sender_name="Kaisen AI", pending=pending
        )

        assert "no válido" in texts(out).lower()
        assert repo.get_pending_input(tx, users["com"].id, NOW) is not None  # puede reintentar
        ok = gate.submit_rewrite(
            tx, users["com"], "Texto bueno", NOW, sender_name="Kaisen AI", pending=pending
        )
    assert labels(ok) == ["✅", "❌"] and proposal_of(db, proposal_id).current_version == 2


def test_may_decide_es_publica_y_coherente_con_las_reglas(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    proposal = proposal_of(db, make_proposal(db, lead_id, users["com"]))
    assert gate.may_decide(users["com"], proposal) is True  # su aprobador
    assert gate.may_decide(users["cto"], proposal) is True  # el CTO siempre
    assert gate.may_decide(users["other"], proposal) is False
    assert gate.may_decide(users["law"], proposal) is False
