"""F2-T15 — Programación y entrega con guardas y reintentos.

Requisitos: VCRM-029, 036, 037, 038, 072, 076, 100 y 101.

Último control antes de contactar al titular: aquí se prueba que nada sale sin aprobación exacta,
fuera de franja, sobre el cupo semanal, a quien ya no corresponde o con reintentos fuera de plan.
"""

import sqlite3
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from crm_support import FakeEmailSender
from f2_support import (
    BODY,
    COM_TG,
    CTO_TG,
    EMAIL,
    KEYS,
    NOW,
    SUBJECT,
    UNSUB_ADDR,
    bog,
    make_lead,
    make_proposal,
)
from jerico.crm import delivery, repo
from jerico.crm.config import default_params
from jerico.crm.db import CrmDatabase
from jerico.crm.fingerprint import fingerprint
from jerico.crm.inbound import verify_unsub_token
from jerico.crm.model import (
    AuthStatus,
    Lead,
    LeadState,
    Outgoing,
    ProposalKind,
    ProposalStatus,
    Role,
    SendStatus,
    User,
)
from jerico.crm.sendwindow import week_start
from jerico.crm.timeutil import to_iso


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
        }


def approve(
    db: CrmDatabase, proposal_id: int, user: User, now: datetime = NOW
) -> delivery.Scheduled:
    with db.tx() as tx:
        proposal = repo.get_proposal(tx, proposal_id)
        assert proposal is not None
        version = repo.get_proposal_version(tx, proposal_id, proposal.current_version)
        lead = repo.get_lead(tx, proposal.lead_id)
        assert version is not None and lead is not None
        return delivery.schedule_send(
            tx, proposal=proposal, version=version, lead=lead, approved_by=user.id, now=now
        )


async def run_due(
    db: CrmDatabase,
    email: FakeEmailSender,
    now: datetime = NOW,
    hook: Any = None,
) -> list[Outgoing]:
    return await delivery.deliver_due(
        db,
        email,
        now,
        default_params(),
        KEYS,
        unsub_address=UNSUB_ADDR,
        on_step_consumed=hook,
    )


def send_of(db: CrmDatabase, proposal_id: int) -> Any:
    with db.read() as conn:
        return repo.get_send_by_proposal(conn, proposal_id)


def proposal_status(db: CrmDatabase, proposal_id: int) -> str:
    with db.read() as conn:
        proposal = repo.get_proposal(conn, proposal_id)
    assert proposal is not None
    return str(proposal.status)


class Hook:
    """Doble de `followup.on_step_consumed`: registra con qué resultado se consumió el paso."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, str, datetime, datetime | None]] = []

    def __call__(
        self,
        conn: sqlite3.Connection,
        lead_id: int,
        outcome: str,
        now: datetime,
        sent_at: datetime | None,
    ) -> list[Outgoing]:
        self.calls.append((lead_id, outcome, now, sent_at))
        return []


def test_content_hash_es_estable_y_sensible_al_contenido() -> None:
    assert delivery.content_hash("a", "b") == delivery.content_hash("a", "b")
    assert delivery.content_hash("a", "b") != delivery.content_hash("a", "b ")
    assert delivery.content_hash("a\nb", "c") != delivery.content_hash("a", "b\nc")
    assert len(delivery.content_hash("a", "b")) == 64


@pytest.mark.asyncio
async def test_vcrm029_aprobar_envia_y_programa_siguiente(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])
    scheduled = approve(db, proposal_id, users["com"])
    assert scheduled.slot == NOW and scheduled.deferred_by is None  # dentro de franja y de cupo
    email, hook = FakeEmailSender(), Hook()

    out = await run_due(db, email, hook=hook)

    (sent,) = email.sent
    assert (sent.to, sent.subject, sent.body) == (EMAIL, SUBJECT, BODY)
    token = f"{scheduled.send_id}."
    header = sent.headers["List-Unsubscribe"]
    assert header.startswith(f"<mailto:{UNSUB_ADDR}?subject=") and header.endswith(">")
    raw_token = header.split("BAJA%20")[1].rstrip(">")
    assert raw_token.startswith(token)
    assert verify_unsub_token(raw_token, KEYS) == scheduled.send_id
    assert sent.headers["Auto-Submitted"] == "no"
    row = send_of(db, proposal_id)
    assert row.status == SendStatus.SENT and row.rfc_message_id == "<1@fake.test>"
    assert row.attempts == 1 and row.sent_at == to_iso(NOW)
    assert proposal_status(db, proposal_id) == ProposalStatus.SENT
    assert hook.calls == [(lead_id, "sent", NOW, NOW)]  # la cadencia programa el siguiente paso
    assert [o.chat_id for o in out] == [COM_TG]  # el aprobador recibe la confirmación
    assert "Ana" not in out[0].text  # sin datos personales en los avisos


@pytest.mark.asyncio
async def test_vcrm029_no_reenvia_lo_ya_enviado(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = make_lead(db, users["com"])
    approve(db, make_proposal(db, lead_id, users["com"]), users["com"])
    email = FakeEmailSender()
    await run_due(db, email)
    await run_due(db, email, NOW + timedelta(minutes=10))
    assert len(email.sent) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["paused", "opted_out", "revoked", "suppressed", "blocked"])
async def test_vcrm037_estado_cambia_cancela_por_estado(
    db: CrmDatabase, users: dict[str, User], change: str
) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])
    approve(db, proposal_id, users["com"])
    with db.tx() as tx:
        if change == "paused":
            repo.update_lead(tx, lead_id, {"state": "paused"}, now=NOW)
        elif change == "opted_out":
            repo.update_lead(tx, lead_id, {"state": "opted_out"}, now=NOW)
        elif change == "revoked":
            repo.update_lead(tx, lead_id, {"auth_status": "revoked"}, now=NOW)
            repo.insert_consent(
                tx,
                lead_id=lead_id,
                status=AuthStatus.REVOKED,
                medium="correo",
                at=NOW,
                actor_user_id=users["com"].id,
            )
        elif change == "suppressed":
            repo.add_suppression(tx, fingerprint(KEYS[0], EMAIL), at=NOW, medium="correo")
        else:
            repo.update_lead(tx, lead_id, {"commercial_block": 1}, now=NOW)
    email, hook = FakeEmailSender(), Hook()

    out = await run_due(db, email, hook=hook)

    assert email.attempts == [] and hook.calls == []  # ni se intentó ni avanzó la cadencia
    assert send_of(db, proposal_id).status == SendStatus.CANCELLED
    assert proposal_status(db, proposal_id) == ProposalStatus.BLOCKED
    assert [o.chat_id for o in out] == [COM_TG] and "cancelado por estado" in out[0].text


@pytest.mark.asyncio
async def test_vcrm037_solicitud_solo_suprimido(db: CrmDatabase, users: dict[str, User]) -> None:
    # Una solicitud de autorización se envía aunque el lead no esté «en nutrición» ni autorizado.
    lead_id = make_lead(db, users["com"], state=LeadState.CONTACTED)
    with db.tx() as tx:
        repo.update_lead(tx, lead_id, {"auth_status": "unauthorized"}, now=NOW)
    proposal_id = make_proposal(
        db, lead_id, users["com"], kind=ProposalKind.AUTH_REQUEST, step=None
    )
    approve(db, proposal_id, users["com"])
    email = FakeEmailSender()
    await run_due(db, email)
    assert len(email.sent) == 1

    # Pero si su contacto está en la lista de supresión, no sale.
    other = make_lead(
        db, users["com"], state=LeadState.CONTACTED, email="otra@cliente.test", phone_e164=None
    )
    with db.tx() as tx:
        repo.update_lead(tx, other, {"auth_status": "unauthorized"}, now=NOW)
    pid = make_proposal(db, other, users["com"], kind=ProposalKind.AUTH_REQUEST, step=None)
    approve(db, pid, users["com"], NOW + timedelta(days=7))
    with db.tx() as tx:
        repo.add_suppression(tx, fingerprint(KEYS[0], "otra@cliente.test"), at=NOW, medium="correo")
    email2 = FakeEmailSender()
    out = await run_due(db, email2, NOW + timedelta(days=7))
    assert email2.attempts == [] and send_of(db, pid).status == SendStatus.CANCELLED
    assert "cancelado por estado" in out[0].text


@pytest.mark.asyncio
async def test_vcrm036_hash_distinto_falla_cerrado(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])
    approve(db, proposal_id, users["com"])
    with db.tx() as tx:  # alguien altera el texto aprobado después del ✅
        tx.execute("UPDATE crm_proposal_versions SET body = body || ' (editado)'")
    email, hook = FakeEmailSender(), Hook()

    out = await run_due(db, email, hook=hook)

    assert email.attempts == [] and hook.calls == []
    row = send_of(db, proposal_id)
    assert row.status == SendStatus.FAILED and row.last_error == "content_mismatch"
    assert proposal_status(db, proposal_id) == ProposalStatus.FAILED
    assert "no coincide" in out[0].text


@pytest.mark.asyncio
async def test_vcrm038_tres_intentos_0_1_5(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])
    approve(db, proposal_id, users["com"])
    email, hook = FakeEmailSender(), Hook()
    email.fail_next(EMAIL, 3)

    assert await run_due(db, email, NOW, hook) == []  # intento 1 (minuto 0): sin aviso aún
    row = send_of(db, proposal_id)
    assert (row.attempts, row.status) == (1, SendStatus.SCHEDULED)
    assert row.next_attempt_at == to_iso(NOW + timedelta(minutes=1))

    await run_due(db, email, NOW + timedelta(seconds=30), hook)  # aún no toca
    assert len(email.attempts) == 1

    assert await run_due(db, email, NOW + timedelta(minutes=1), hook) == []  # intento 2
    assert send_of(db, proposal_id).next_attempt_at == to_iso(NOW + timedelta(minutes=5))

    out = await run_due(db, email, NOW + timedelta(minutes=5), hook)  # intento 3: falla
    assert len(email.attempts) == 3
    row = send_of(db, proposal_id)
    assert (row.attempts, row.status) == (3, SendStatus.FAILED)
    assert proposal_status(db, proposal_id) == ProposalStatus.FAILED
    assert hook.calls == []  # la cadencia NO avanza hasta que alguien decida
    (notice,) = out
    assert notice.chat_id == COM_TG
    labels = [label for row_ in notice.buttons for label, _ in row_]
    assert labels == ["Reintentar", "Cancelar"]

    await run_due(db, email, NOW + timedelta(minutes=30), hook)  # no vuelve a intentar
    assert len(email.attempts) == 3


@pytest.mark.asyncio
async def test_vcrm038_un_acierto_tras_un_fallo_cuenta_como_enviado(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])
    approve(db, proposal_id, users["com"])
    email, hook = FakeEmailSender(), Hook()
    email.fail_next(EMAIL, 1)
    await run_due(db, email, NOW, hook)

    await run_due(db, email, NOW + timedelta(minutes=1), hook)

    assert len(email.sent) == 1 and send_of(db, proposal_id).attempts == 2
    assert hook.calls == [(lead_id, "sent", NOW + timedelta(minutes=1), NOW + timedelta(minutes=1))]


@pytest.mark.asyncio
async def test_vcrm038_sin_intentos_fuera_de_franja(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])
    approve(db, proposal_id, users["com"], bog(14, 18, 58))
    email, hook = FakeEmailSender(), Hook()
    email.fail_next(EMAIL, 2)

    # Calendario 0/1/5 desde las 18:58: intentos a las 18:58, 18:59 y 19:03 (fuera de franja).
    assert await run_due(db, email, bog(14, 18, 58), hook) == []
    out = await run_due(db, email, bog(14, 18, 59), hook)

    row = send_of(db, proposal_id)
    assert (row.attempts, row.status) == (2, SendStatus.FAILED)  # el tercero no se intentará
    assert "franja" in out[0].text and hook.calls == []
    await run_due(db, email, bog(14, 19, 3), hook)
    assert len(email.attempts) == 2  # nunca se intenta fuera de franja


@pytest.mark.asyncio
async def test_vcrm038_el_siguiente_intento_fuera_de_franja_marca_fallido_ya(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])
    approve(db, proposal_id, users["com"], bog(14, 18, 59))
    email = FakeEmailSender()
    email.fail_next(EMAIL, 1)

    out = await run_due(db, email, bog(14, 18, 59))  # reintento a las 19:00: fuera de franja

    assert len(email.attempts) == 1
    assert send_of(db, proposal_id).status == SendStatus.FAILED
    assert out and "franja" in out[0].text


@pytest.mark.asyncio
async def test_vcrm072_un_envio_vencido_fuera_de_franja_se_difiere_sin_intentar(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])
    approve(db, proposal_id, users["com"])  # programado para ahora (10:00)
    email = FakeEmailSender()

    await run_due(db, email, bog(14, 20, 0))  # el barrido llega a las 20:00: fuera de franja

    assert email.attempts == []
    row = send_of(db, proposal_id)
    assert row.status == SendStatus.SCHEDULED
    assert row.next_attempt_at == to_iso(bog(15, 7, 0))


def test_vcrm100_aprobar_fuera_de_franja_difiere_e_informa(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])

    scheduled = approve(db, proposal_id, users["com"], bog(14, 20, 0))

    assert scheduled.slot == bog(15, 7, 0) and scheduled.deferred_by == "window"
    row = send_of(db, proposal_id)
    assert row.scheduled_at == to_iso(bog(15, 7, 0)) and row.next_attempt_at == row.scheduled_at
    assert row.week_start == to_iso(week_start(bog(15, 7, 0)))
    assert proposal_status(db, proposal_id) == ProposalStatus.APPROVED
    assert "jueves" in delivery.deferral_text(scheduled).lower()


def test_vcrm101_excedente_semanal_difiere(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = make_lead(db, users["com"])
    first = make_proposal(db, lead_id, users["com"], step=1)
    approve(db, first, users["com"])  # ocupa el cupo de la semana del 12/10
    second = make_proposal(db, lead_id, users["com"], step=2)

    scheduled = approve(db, second, users["com"], NOW + timedelta(hours=1))

    assert scheduled.slot == bog(19, 7, 0) and scheduled.deferred_by == "weekly"
    assert "lunes" in delivery.deferral_text(scheduled).lower()


def test_vcrm101_el_cupo_es_por_lead(db: CrmDatabase, users: dict[str, User]) -> None:
    a = make_lead(db, users["com"])
    b = make_lead(db, users["com"], email="b@cliente.test", phone_e164="+573005550000")
    approve(db, make_proposal(db, a, users["com"]), users["com"])
    scheduled = approve(db, make_proposal(db, b, users["com"]), users["com"])
    assert scheduled.slot == NOW and scheduled.deferred_by is None


@pytest.mark.asyncio
async def test_vcrm037_guarda_se_reevalua_en_cada_intento(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])
    approve(db, proposal_id, users["com"])
    email, hook = FakeEmailSender(), Hook()
    email.fail_next(EMAIL, 1)
    await run_due(db, email, NOW, hook)  # intento 1 falla
    with db.tx() as tx:  # entre intentos, el titular pide la baja
        repo.add_suppression(tx, fingerprint(KEYS[0], EMAIL), at=NOW, medium="correo")

    out = await run_due(db, email, NOW + timedelta(minutes=1), hook)

    assert len(email.attempts) == 1  # el segundo intento no se hizo
    assert send_of(db, proposal_id).status == SendStatus.CANCELLED
    assert "cancelado por estado" in out[0].text and hook.calls == []


@pytest.mark.asyncio
async def test_vcrm036_sin_correo_o_sin_aprobacion_no_se_envia(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    sin_correo = make_lead(db, users["com"], email=None)
    pid = make_proposal(db, sin_correo, users["com"])
    approve(db, pid, users["com"])
    cancelada = make_lead(db, users["com"], email="c@cliente.test", phone_e164="+573009990000")
    cid = make_proposal(db, cancelada, users["com"])
    approve(db, cid, users["com"])
    with db.tx() as tx:  # la propuesta se canceló (p. ej. al pausar) pero su envío quedó programado
        repo.update_proposal(tx, cid, status="cancelled")
    email = FakeEmailSender()

    out = await run_due(db, email)

    assert email.attempts == []
    assert (
        send_of(db, pid).status == SendStatus.FAILED and send_of(db, pid).last_error == "no_email"
    )
    assert send_of(db, cid).status == SendStatus.CANCELLED
    assert len(out) == 1  # solo la falta de correo avisa; lo cancelado en silencio no


@pytest.mark.asyncio
async def test_vcrm038_canal_sin_configurar_falla_sin_reintentos(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])
    approve(db, proposal_id, users["com"])
    email = FakeEmailSender(configured=False)

    out = await run_due(db, email)

    row = send_of(db, proposal_id)
    assert row.status == SendStatus.FAILED and row.attempts == 1  # permanente: no se reintenta
    assert out and [label for r in out[0].buttons for label, _ in r] == ["Reintentar", "Cancelar"]


@pytest.mark.asyncio
async def test_vcrm038_reintentar_y_cancelar_un_envio_fallido(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])
    approve(db, proposal_id, users["com"])
    email, hook = FakeEmailSender(), Hook()
    email.fail_next(EMAIL, 3)
    for minutes in (0, 1, 5):
        await run_due(db, email, NOW + timedelta(minutes=minutes), hook)
    assert send_of(db, proposal_id).status == SendStatus.FAILED

    with db.tx() as tx:  # «Reintentar»: nuevo calendario desde ahora
        ok = delivery.retry_failed(tx, proposal_id, NOW + timedelta(hours=1))
    assert ok is True
    row = send_of(db, proposal_id)
    assert (row.status, row.attempts, row.first_attempt_at) == (SendStatus.SCHEDULED, 0, None)
    assert proposal_status(db, proposal_id) == ProposalStatus.APPROVED
    await run_due(db, email, NOW + timedelta(hours=1), hook)
    assert len(email.sent) == 1 and hook.calls[-1][1] == "sent"

    # «Cancelar» sobre otro fallido consume el paso.
    other = make_lead(db, users["com"], email="d@cliente.test", phone_e164="+573004440000")
    pid = make_proposal(db, other, users["com"])
    approve(db, pid, users["com"], NOW + timedelta(days=7))
    email.fail_next("d@cliente.test", 3)
    for minutes in (0, 1, 5):
        await run_due(db, email, NOW + timedelta(days=7, minutes=minutes), hook)
    with db.tx() as tx:
        out = delivery.cancel_failed(tx, pid, NOW + timedelta(days=8), on_step_consumed=hook)
    assert hook.calls[-1][:2] == (other, "cancelled") and out == []
    assert send_of(db, pid).status == SendStatus.CANCELLED
    assert proposal_status(db, pid) == ProposalStatus.CANCELLED


def test_retry_y_cancel_ignoran_lo_que_no_esta_fallido(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])
    approve(db, proposal_id, users["com"])  # programado, no fallido
    with db.tx() as tx:
        assert delivery.retry_failed(tx, proposal_id, NOW) is False
        assert delivery.retry_failed(tx, 9999, NOW) is False
        assert delivery.cancel_failed(tx, proposal_id, NOW, on_step_consumed=None) == []
    assert send_of(db, proposal_id).status == SendStatus.SCHEDULED


def test_guard_distingue_seguimiento_y_solicitud(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = make_lead(db, users["com"], state=LeadState.CONTACTED)
    followup = make_proposal(db, lead_id, users["com"])
    auth = make_proposal(db, lead_id, users["com"], kind=ProposalKind.AUTH_REQUEST, step=None)
    with db.read() as conn:
        lead: Lead = repo.get_lead(conn, lead_id)  # type: ignore[assignment]
        fp = repo.get_proposal(conn, followup)
        ap = repo.get_proposal(conn, auth)
        assert fp is not None and ap is not None
        assert delivery.guard(conn, lead, fp, KEYS) is False  # seguimiento exige «en nutrición»
        assert delivery.guard(conn, lead, ap, KEYS) is True  # la solicitud no


def test_vcrm072_fechas_con_festivo_extraordinario(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])
    with db.tx() as tx:
        proposal = repo.get_proposal(tx, proposal_id)
        version = repo.get_proposal_version(tx, proposal_id, 1)
        lead = repo.get_lead(tx, lead_id)
        assert proposal and version and lead
        scheduled = delivery.schedule_send(
            tx,
            proposal=proposal,
            version=version,
            lead=lead,
            approved_by=users["com"].id,
            now=bog(14, 20, 0),
            extra_holidays=frozenset({date(2026, 10, 15)}),  # jueves extraordinario
        )
    assert scheduled.slot == bog(16, 7, 0)
    assert "viernes" in delivery.deferral_text(scheduled).lower()


@pytest.mark.asyncio
async def test_vcrm101_el_cupo_se_recomprueba_al_entregar(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    first = make_proposal(db, lead_id, users["com"], step=1)
    second = make_proposal(db, lead_id, users["com"], step=2)
    approve(db, first, users["com"])
    # Un segundo envío llega a la misma semana por una vía que no pasó por `schedule_send`.
    with db.tx() as tx:
        version = repo.get_proposal_version(tx, second, 1)
        assert version is not None
        repo.insert_send(
            tx,
            proposal_id=second,
            version=1,
            approved_hash=version.content_hash,
            approved_by=users["com"].id,
            approved_at=NOW,
            scheduled_at=NOW,
            lead_id=lead_id,
            week_start=week_start(NOW),
            next_attempt_at=NOW,
        )
        repo.update_proposal(tx, second, status=ProposalStatus.APPROVED)
    email = FakeEmailSender()

    await run_due(db, email)

    assert len(email.sent) == 1  # solo uno de los dos sale esta semana
    sent_rows = [send_of(db, first), send_of(db, second)]
    assert sorted(r.status for r in sent_rows) == [SendStatus.SCHEDULED, SendStatus.SENT]
    deferred = next(r for r in sent_rows if r.status == SendStatus.SCHEDULED)
    assert deferred.next_attempt_at == to_iso(
        bog(19, 7, 0)
    )  # primera franja de la semana siguiente
    assert deferred.week_start == to_iso(week_start(bog(19, 7, 0)))


@pytest.mark.asyncio
async def test_avisos_van_al_comercial_o_al_cto_si_el_aprobador_ya_no_esta_activo(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])
    approve(db, proposal_id, users["com"])
    with db.tx() as tx:
        tx.execute(
            "UPDATE crm_users SET active = 0, deactivated_at = ? WHERE id = ?",
            (to_iso(NOW), users["com"].id),
        )
    email = FakeEmailSender()

    out = await run_due(db, email)

    assert [o.chat_id for o in out] == [CTO_TG]  # el comercial ya no está: lo recibe el CTO


@pytest.mark.asyncio
async def test_vcrm036_datos_incompletos_falla_cerrado(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    proposal_id = make_proposal(db, lead_id, users["com"])
    approve(db, proposal_id, users["com"])
    with db.tx() as tx:
        tx.execute("DELETE FROM crm_proposal_versions")
    email = FakeEmailSender()

    assert await run_due(db, email) == []

    assert email.attempts == []
    row = send_of(db, proposal_id)
    assert row.status == SendStatus.FAILED and row.last_error == "missing_data"
