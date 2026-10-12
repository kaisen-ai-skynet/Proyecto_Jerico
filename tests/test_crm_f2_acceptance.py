"""Pruebas de aceptación de punta a punta de la Fase 2 (F2-T29; plan-f2 §7).

Recorre el sistema completo como producto real con `CrmApp`, `CrmBot`, `run_followup_job`,
el reloj simulado y los dobles de red y buzón. Sin red ni dependencias externas.
Requisitos cubiertos: VCRM-018, 029, 036, 068, 102, 119, 120, 141, 148, 170.
"""

import asyncio
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from crm_support import (
    FakeClock,
    FakeEmailSender,
    FakeInbox,
    FakeRunner,
    FakeTelegram,
    make_settings,
)
from f2_support import (
    EMAIL,
    NOW,
    make_inbound,
    make_lead,
    make_proposal,
    make_sent,
)
from jerico.crm import delivery, repo, timeutil
from jerico.crm.app import CrmApp
from jerico.crm.db import CrmDatabase
from jerico.crm.fingerprint import fingerprint
from jerico.crm.model import (
    Cadence,
    LeadState,
    Proposal,
    ProposalKind,
    ProposalStatus,
    Role,
    Send,
    User,
)
from jerico.crm.ports import InboxError, Update
from jerico.crm.timeutil import to_iso

CTO_TG = 1000
COM_TG = 2000
SECRET_TOKEN = "123:token-super-secreto"
SECRET_KEY = "clave-hmac-secreta"


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.tg = FakeTelegram()
        self.mail = FakeEmailSender()
        self.runner = FakeRunner()
        self.inbox = FakeInbox()
        self.clock = FakeClock(NOW)
        self.update_ids = iter(range(1, 1_000_000))

        settings = make_settings(
            telegram_bot_token=SECRET_TOKEN,
            fingerprint_key=SECRET_KEY,
            seed_cto_telegram_id=str(CTO_TG),
            seed_cto_email="cto@k.co",
            data_dir=tmp_path / "crm-data",
            imap_host="imap.example.invalid",
            imap_username="buzon@kaisen.test",
            imap_password="secreto-imap-no-real",
            smtp_host="smtp.example.invalid",
            smtp_port=465,
            smtp_from="crm@kaisen.test",
        )
        self.app = CrmApp(
            settings,
            telegram=self.tg,
            email=self.mail,
            runner=self.runner,
            clock=self.clock.now,
            inbox=self.inbox,
        )

    async def start(self) -> User:
        await self.app.startup()
        with self.app.db.tx() as tx:
            self.com = repo.insert_user(
                tx,
                telegram_id=COM_TG,
                role=Role.COMMERCIAL,
                email="com@k.co",
                now=self.clock.now(),
            )
        return self.com

    async def press(self, user_tg: int, data: str) -> list[str]:
        before = len(self.tg.sent)
        update = Update(
            update_id=next(self.update_ids),
            user_id=user_tg,
            chat_id=user_tg,
            chat_type="private",
            callback_id="cb",
            callback_data=data,
        )
        await self.app.bot.process_update(update)
        return [s.text for s in self.tg.sent[before:]]

    async def say(self, user_tg: int, text: str) -> list[str]:
        before = len(self.tg.sent)
        update = Update(
            update_id=next(self.update_ids),
            user_id=user_tg,
            chat_id=user_tg,
            chat_type="private",
            text=text,
        )
        await self.app.bot.process_update(update)
        return [s.text for s in self.tg.sent[before:]]

    def last_buttons(self) -> list[tuple[str, str]]:
        if not self.tg.sent:
            return []
        last = self.tg.sent[-1]
        return [(b.text, b.callback_data) for row in (last.buttons or []) for b in row]

    def close(self) -> None:
        self.app.close()


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    e = Env(tmp_path)
    yield e
    e.close()


def all_proposals(db: CrmDatabase) -> list[Proposal]:
    with db.read() as conn:
        return [
            p
            for r in conn.execute("SELECT id FROM crm_proposals ORDER BY id").fetchall()
            if (p := repo.get_proposal(conn, r[0])) is not None
        ]


def all_sends(db: CrmDatabase) -> list[Send]:
    with db.read() as conn:
        return [
            s
            for r in conn.execute("SELECT id FROM crm_sends ORDER BY id").fetchall()
            if (s := repo.get_send(conn, r[0])) is not None
        ]


# --- Flujos de aceptación de Fase 2 -----------------------------------------------------------


@pytest.mark.asyncio
async def test_vcrm018_flujo_rechazo_a_primer_envio(env: Env) -> None:
    com = await env.start()
    # 1. Lead con autorización vigente asignado al comercial
    lead_id = make_lead(env.app.db, com, state=LeadState.CONTACTED)
    with env.app.db.read() as conn:
        lead = repo.get_lead(conn, lead_id)
        assert lead is not None and lead.auth_status == "authorized"

    # 2. El comercial lo rechaza con motivo "precio" por el botón de motivo
    out_reject = await env.press(COM_TG, f"v1:motivo:{lead_id}:precio")
    assert any("cadencia iniciada" in t.lower() or "rechazado" in t.lower() for t in out_reject)

    with env.app.db.read() as conn:
        lead = repo.get_lead(conn, lead_id)
        assert lead is not None and lead.state == "nurturing"
        cad = repo.get_cadence(conn, lead_id)
        assert cad is not None
        assert cad.reason == "precio"
        assert cad.interval_days == 30
        assert cad.status == "active"
        assert cad.steps_done == 0

    # 3. Avanza 30 días y corre el barrido
    env.clock.advance(days=30)
    await env.app.run_followup_job()

    # 4. El comercial recibe la propuesta con ✅/❌ y NO sale correo
    assert len(env.mail.sent) == 0
    props = all_proposals(env.app.db)
    assert len(props) == 1
    prop = props[0]
    assert prop.lead_id == lead_id
    assert prop.kind == ProposalKind.FOLLOWUP.value
    assert prop.status == ProposalStatus.PENDING.value

    buttons = env.last_buttons()
    assert any(b[0] == "✅" for b in buttons)
    assert any(b[0] == "❌" for b in buttons)

    # 5. El comercial pulsa ✅
    cb_ok = f"v1:gok:{prop.id}:1"
    await env.press(COM_TG, cb_ok)
    await asyncio.sleep(0.05)
    if not env.mail.sent:
        await env.app.run_followup_job()

    # 6. Sale exactamente un correo al lead con List-Unsubscribe y pie legal
    assert len(env.mail.sent) == 1
    sent_mail = env.mail.sent[0]
    assert sent_mail.to == EMAIL
    assert "List-Unsubscribe" in sent_mail.headers
    assert "Responda BAJA para no recibir más mensajes." in sent_mail.body

    # 7. La cadencia avanza al paso 2 con próxima acción a +30 días
    with env.app.db.read() as conn:
        cad = repo.get_cadence(conn, lead_id)
        assert cad is not None
        assert cad.steps_done == 1
        assert cad.sent_count == 1
        assert cad.next_action_at is not None
        next_dt = timeutil.from_iso(cad.next_action_at)
        assert next_dt == env.clock.now() + timedelta(days=30)


@pytest.mark.asyncio
async def test_vcrm141_flujo_solicitud_respuesta_confirmacion_cadencia(env: Env) -> None:
    com = await env.start()
    # 1. Lead rechazado SIN autorización
    with env.app.db.tx() as tx:
        lead_id = repo.insert_lead(
            tx,
            assigned_user_id=com.id,
            state=LeadState.REJECTED,
            now=env.clock.now(),
            fields={
                "name": "Carlos Ruiz",
                "phone_e164": "+573009998877",
                "email": "carlos@cliente.test",
            },
        )
        repo.update_lead(
            tx,
            lead_id,
            {"reject_reason": "precio", "auth_status": "unauthorized"},
            now=env.clock.now(),
        )

    with env.app.db.read() as conn:
        assert repo.get_cadence(conn, lead_id) is None

    # 2. /pedirautorizacion L-n
    await env.say(COM_TG, f"/pedirautorizacion L-{lead_id:04d}")
    props = all_proposals(env.app.db)
    assert len(props) == 1
    prop = props[0]
    assert prop.kind == ProposalKind.AUTH_REQUEST.value
    assert prop.status == ProposalStatus.PENDING.value

    # 3. El comercial pulsa ✅ -> sale la solicitud con aviso y encargados
    await env.press(COM_TG, f"v1:gok:{prop.id}:1")
    await asyncio.sleep(0.05)
    if not env.mail.sent:
        await env.app.run_followup_job()

    assert len(env.mail.sent) == 1
    req_email = env.mail.sent[0]
    assert req_email.to == "carlos@cliente.test"
    assert "aviso de privacidad" in req_email.body.lower()

    # 4. El cliente responde por correo (FakeInbox) aceptando
    env.inbox.add(
        make_inbound(
            101,
            "Sí, autorizo el contacto comercial.",
            sender="carlos@cliente.test",
            in_reply_to="<1@fake.test>",
            when=env.clock.now(),
        )
    )

    # 5. El barrido la propone al comercial con ✅/❌ sin registrar nada
    env.clock.advance(minutes=10)
    await env.app.run_followup_job()

    with env.app.db.read() as conn:
        lead = repo.get_lead(conn, lead_id)
        assert lead is not None and lead.auth_status == "unauthorized"
        assert repo.lead_consents(conn, lead_id) == []
        (inbound,) = repo.list_inbound(conn)
        assert inbound.classification == "auth_candidate"
        assert inbound.decision == "pending"

    buttons = env.last_buttons()
    assert any(b[1] == f"v1:aok:{inbound.id}" for b in buttons)

    # 6. El comercial pulsa ✅ -> autorización registrada y cadencia arranca
    out_auth_ok = await env.press(COM_TG, f"v1:aok:{inbound.id}")
    assert any("autorización registrada" in t.lower() for t in out_auth_ok)

    with env.app.db.read() as conn:
        lead = repo.get_lead(conn, lead_id)
        assert lead is not None
        assert lead.auth_status == "authorized"
        assert lead.state == "nurturing"
        (consent,) = repo.lead_consents(conn, lead_id)
        assert consent["status"] == "authorized"
        assert consent["medium"] == "respuesta al correo confirmada por el comercial"
        cad = repo.get_cadence(conn, lead_id)
        assert cad is not None
        assert cad.status == "active"

    # 7. Segunda pulsación ✅ responde «ya fue procesada» y no duplica
    out_second = await env.press(COM_TG, f"v1:aok:{inbound.id}")
    assert any("ya fue procesada" in t.lower() for t in out_second)

    with env.app.db.read() as conn:
        assert len(repo.lead_consents(conn, lead_id)) == 1


@pytest.mark.asyncio
async def test_vcrm102_flujo_baja_cancela_pendientes(env: Env) -> None:
    com = await env.start()
    lead_id = make_lead(env.app.db, com, state=LeadState.NURTURING)
    with env.app.db.tx() as tx:
        repo.upsert_cadence(
            tx,
            Cadence(
                lead_id,
                "precio",
                30,
                3,
                steps_done=1,
                sent_count=1,
                next_action_at=to_iso(env.clock.now() + timedelta(days=30)),
                started_at=to_iso(env.clock.now()),
                updated_at=to_iso(env.clock.now()),
            ),
        )

    # Envío previo registrado con Message-ID <1@fake.test>
    make_sent(env.app.db, lead_id, com, "<1@fake.test>", step=1)

    # Propuesta pendiente (step 2)
    prop_pending_id = make_proposal(env.app.db, lead_id, com, step=2)

    # Propuesta aprobada con envío programado (step 3)
    prop_sched_id = make_proposal(env.app.db, lead_id, com, step=3)
    with env.app.db.tx() as tx:
        v = repo.get_proposal_version(tx, prop_sched_id, 1)
        assert v is not None
        send_id = repo.insert_send(
            tx,
            proposal_id=prop_sched_id,
            version=1,
            approved_hash=v.content_hash,
            approved_by=com.id,
            approved_at=env.clock.now(),
            scheduled_at=env.clock.now() + timedelta(days=2),
            lead_id=lead_id,
            week_start=delivery.week_start(env.clock.now()),
        )
        repo.update_proposal(tx, prop_sched_id, status="approved", resolved_at=env.clock.now())

    # Cliente responde «BAJA» por correo
    env.inbox.add(
        make_inbound(
            201,
            "Por favor, BAJA de sus comunicaciones.",
            sender=EMAIL,
            in_reply_to="<1@fake.test>",
            when=env.clock.now(),
        )
    )

    # Barrido
    env.clock.advance(minutes=10)
    await env.app.run_followup_job()

    with env.app.db.read() as conn:
        # Lead en baja
        lead = repo.get_lead(conn, lead_id)
        assert lead is not None and lead.state == "opted_out"

        # Propuestas pendientes y programadas canceladas
        p_pend = repo.get_proposal(conn, prop_pending_id)
        assert p_pend is not None and p_pend.status == "cancelled"
        p_sched = repo.get_proposal(conn, prop_sched_id)
        assert p_sched is not None and p_sched.status == "cancelled"

        # Envíos programados cancelados
        s_sched = repo.get_send(conn, send_id)
        assert s_sched is not None and s_sched.status == "cancelled"

        # Cadencia detenida
        cad = repo.get_cadence(conn, lead_id)
        assert cad is not None and cad.status == "stopped"

        # Contacto figura en la lista de supresión (solo huella)
        assert repo.any_suppressed(conn, [fingerprint(env.app.keys[0], EMAIL.lower())])

    # Comercial recibe aviso de «Baja aplicada»
    sent_tg_texts = [s.text for s in env.tg.sent if s.chat_id == COM_TG]
    assert any("baja aplicada" in t.lower() for t in sent_tg_texts)

    # Titular NO recibe ningún acuse (mail.sent sigue vacío)
    assert len(env.mail.sent) == 0

    # Avanza el reloj y corre más barridos -> NO sale ningún correo después
    env.clock.advance(days=15)
    await env.app.run_followup_job()
    env.clock.advance(days=30)
    await env.app.run_followup_job()
    assert len(env.mail.sent) == 0


@pytest.mark.asyncio
async def test_vcrm036_nada_sale_sin_aprobacion(env: Env) -> None:
    com = await env.start()
    lead_id = make_lead(env.app.db, com, state=LeadState.NURTURING)
    with env.app.db.tx() as tx:
        repo.upsert_cadence(
            tx,
            Cadence(
                lead_id,
                "precio",
                30,
                3,
                steps_done=0,
                sent_count=0,
                next_action_at=to_iso(env.clock.now() + timedelta(days=30)),
                started_at=to_iso(env.clock.now()),
                updated_at=to_iso(env.clock.now()),
            ),
        )

    # Avanzar 30 días -> barrido genera propuesta paso 1
    env.clock.advance(days=30)
    await env.app.run_followup_job()

    props = all_proposals(env.app.db)
    assert len(props) == 1
    assert props[0].status == "pending"

    # Nadie pulsa ✅. FakeEmailSender.attempts debe seguir vacío
    assert len(env.mail.attempts) == 0

    # Avanzar 48 horas sin respuesta -> expira propuesta paso 1 y salta a paso 2
    env.clock.advance(hours=49)
    await env.app.run_followup_job()

    with env.app.db.read() as conn:
        p1 = repo.get_proposal(conn, props[0].id)
        assert p1 is not None and p1.status == "expired"

    assert len(env.mail.attempts) == 0

    # Avanzar 30 días más -> barrido genera propuesta paso 2
    env.clock.advance(days=30)
    await env.app.run_followup_job()

    proposals2 = [p for p in all_proposals(env.app.db) if p.status == "pending"]
    assert len(proposals2) == 1
    prop_step2 = proposals2[0]

    # Sigue sin salir nada
    assert len(env.mail.attempts) == 0

    # Ahora aprobamos SOLO la propuesta del paso 2
    await env.press(COM_TG, f"v1:gok:{prop_step2.id}:1")
    await asyncio.sleep(0.05)
    if not env.mail.sent:
        await env.app.run_followup_job()

    # Cada correo enviado corresponde a una propuesta aprobada
    assert len(env.mail.sent) == 1
    sends = all_sends(env.app.db)
    assert len(sends) == 1
    send = sends[0]
    assert send.status == "sent"
    assert send.proposal_id == prop_step2.id
    with env.app.db.read() as conn:
        prop = repo.get_proposal(conn, prop_step2.id)
        assert prop is not None and prop.status == "sent"

    # Ninguna propuesta sin aprobar tiene envío
    unapproved_props = [p for p in all_proposals(env.app.db) if p.id != prop_step2.id]
    for up in unapproved_props:
        assert up.status != "sent"
        assert not any(s.proposal_id == up.id for s in sends)


@pytest.mark.asyncio
async def test_vcrm170_buzon_falla_aviso_unico_cto_y_recupera(env: Env) -> None:
    com = await env.start()
    lead_id = make_lead(env.app.db, com, state=LeadState.NURTURING)
    make_sent(env.app.db, lead_id, com, "<1@fake.test>", step=1)

    # El buzón falla durante varios barridos
    for _ in range(3):
        env.inbox.fail_next(InboxError("IMAP connection timed out"))

    # Primer barrido fallido -> CTO recibe aviso
    env.clock.advance(minutes=10)
    await env.app.run_followup_job()

    cto_texts = [s.text for s in env.tg.sent if s.chat_id == CTO_TG and "buzón" in s.text.lower()]
    assert len(cto_texts) == 1

    # Siguientes barridos fallidos -> NO repite el aviso al CTO (aviso único)
    env.clock.advance(minutes=10)
    await env.app.run_followup_job()
    env.clock.advance(minutes=10)
    await env.app.run_followup_job()

    cto_texts_after = [
        s.text for s in env.tg.sent if s.chat_id == CTO_TG and "buzón" in s.text.lower()
    ]
    assert len(cto_texts_after) == 1

    # El buzón se recupera y trae un mensaje de baja
    env.inbox.add(
        make_inbound(
            301,
            "BAJA",
            sender=EMAIL,
            in_reply_to="<1@fake.test>",
            when=env.clock.now(),
        )
    )
    env.clock.advance(minutes=10)
    await env.app.run_followup_job()

    # El mensaje se procesa sin perderse y el lead pasa a baja
    with env.app.db.read() as conn:
        lead = repo.get_lead(conn, lead_id)
        assert lead is not None and lead.state == "opted_out"
