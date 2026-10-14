"""F2-T25 — Barrido único de seguimiento.

Requisitos: VCRM-028, 034, 038, 160, 169 y 170 (plan-f2 D-1, D-2 y D-9).

Un solo job cada minuto: activa F2 una vez, consulta el buzón, expira, genera y entrega. Cada
paso va aislado para que el fallo de uno no frene a los demás, y todo es idempotente ante
repeticiones.
"""

import asyncio
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from crm_support import FakeEmailSender, FakeInbox, FakeTelegram, make_settings
from f2_support import (
    COM_TG,
    CTO_TG,
    EMAIL,
    KEYS,
    NOW,
    make_inbound,
    make_lead,
    make_sent,
)
from jerico.crm import gate, repo, sweep
from jerico.crm.config import default_params
from jerico.crm.db import CrmDatabase
from jerico.crm.model import Cadence, LeadState, Role
from jerico.crm.timeutil import to_iso

SENT = "<s@kaisen.test>"


def full_settings(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "imap_host": "imap.example.invalid",
        "imap_username": "buzon@kaisen.test",
        "imap_password": "secreto-no-real",
        "smtp_host": "smtp.example.invalid",
        "smtp_port": 465,
        "smtp_from": "crm@kaisen.test",
    }
    return make_settings(**{**base, **overrides})


class Env:
    def __init__(self, tmp_path: Path, settings: Any = None) -> None:
        self.db = CrmDatabase(tmp_path / "crm.db")
        self.tg = FakeTelegram()
        self.email = FakeEmailSender()
        self.inbox = FakeInbox()
        self.settings = settings or full_settings()
        with self.db.tx() as tx:
            self.cto = repo.insert_user(
                tx, telegram_id=CTO_TG, role=Role.CTO, email="c@k.co", now=NOW
            )
            self.com = repo.insert_user(
                tx, telegram_id=COM_TG, role=Role.COMMERCIAL, email="m@k.co", now=NOW
            )
        self.ctx = sweep.SweepContext(
            db=self.db,
            telegram=self.tg,
            email=self.email,
            inbox=self.inbox,
            settings=self.settings,
            params=default_params(),
            keys=KEYS,
        )

    def run(self, now: Any = NOW) -> None:
        asyncio.run(sweep.followup_sweep(self.ctx, now))

    def meta(self, key: str) -> str | None:
        with self.db.read() as conn:
            return repo.get_meta(conn, key)

    def activate(self) -> None:
        with self.db.tx() as tx:
            repo.set_meta(tx, "f2_activated_at", to_iso(NOW))

    def texts_to(self, chat: int) -> list[str]:
        return [s.text for s in self.tg.sent if s.chat_id == chat]

    def close(self) -> None:
        self.db.close()


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    e = Env(tmp_path)
    yield e
    e.close()


def due_cadence(env: Env, lead_id: int, at: Any = NOW) -> None:
    with env.db.tx() as tx:
        repo.upsert_cadence(
            tx,
            Cadence(
                lead_id,
                "precio",
                30,
                3,
                next_action_at=to_iso(at),
                started_at=to_iso(NOW),
                updated_at=to_iso(NOW),
            ),
        )


# --- Activación (VCRM-160) -----------------------------------------------------------------


def test_vcrm160_activacion_desde_ahora_una_sola_vez(env: Env) -> None:
    authorized = make_lead(env.db, env.com, state=LeadState.REJECTED)
    unauthorized = make_lead(
        env.db,
        env.com,
        state=LeadState.REJECTED,
        email="b@cliente.test",
        phone_e164="+573004443322",
    )
    with env.db.tx() as tx:
        repo.update_lead(tx, authorized, {"reject_reason": "precio"}, now=NOW)
        repo.update_lead(tx, unauthorized, {"auth_status": "unauthorized"}, now=NOW)
        tx.execute("DELETE FROM crm_consents WHERE lead_id = ?", (unauthorized,))
    assert env.meta("f2_activated_at") is None

    env.run(NOW)

    assert env.meta("f2_activated_at") == to_iso(NOW)
    with env.db.read() as conn:
        cadence = repo.get_cadence(conn, authorized)
        lead = repo.get_lead(conn, authorized)
        assert repo.get_cadence(conn, unauthorized) is None  # sin autorización: no entra
        assert repo.get_lead(conn, unauthorized).state == "rejected"  # type: ignore[union-attr]
    assert cadence is not None and cadence.next_action_at == to_iso(NOW + timedelta(days=30))
    assert lead is not None and lead.state == "nurturing"

    env.run(NOW + timedelta(days=1))  # no se vuelve a activar ni se duplica nada
    assert env.meta("f2_activated_at") == to_iso(NOW)
    with env.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM crm_cadences").fetchone()[0] == 1


def test_d9_f2_deshabilitada_si_falta_configuracion_y_avisa_una_vez(tmp_path: Path) -> None:
    env = Env(tmp_path, make_settings())  # sin buzón IMAP ni correo de salida
    lead_id = make_lead(env.db, env.com, state=LeadState.REJECTED)
    due_cadence(env, lead_id)

    env.run(NOW)
    env.run(NOW + timedelta(minutes=1))

    assert env.meta("f2_activated_at") is None
    assert env.inbox.fetches == [] and env.email.attempts == []  # no lee, no genera, no envía
    notices = env.texts_to(CTO_TG)
    assert len(notices) == 1 and "JERICO_CRM_IMAP_HOST" in notices[0]
    with env.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM crm_proposals").fetchone()[0] == 0
    env.close()


def test_d9_el_aviso_se_repite_si_cambia_lo_que_falta(tmp_path: Path) -> None:
    env = Env(tmp_path, make_settings())
    env.run(NOW)
    env.ctx = sweep.SweepContext(**{**env.ctx.__dict__, "settings": make_settings(imap_host="h")})
    env.run(NOW + timedelta(minutes=1))
    assert len(env.texts_to(CTO_TG)) == 2  # distinta lista de faltantes: otro aviso
    env.close()


# --- Generación y entrega ------------------------------------------------------------------


def test_vcrm028_barrido_repetido_idempotente(env: Env) -> None:
    env.activate()
    lead_id = make_lead(env.db, env.com)
    due_cadence(env, lead_id)

    env.run(NOW)
    env.run(NOW)
    env.run(NOW + timedelta(minutes=1))

    with env.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM crm_proposals").fetchone()[0] == 1
    presented = [s for s in env.tg.sent if s.chat_id == COM_TG and s.buttons]
    assert len(presented) == 1  # un solo aviso al aprobador, con sus botones ✅/❌
    assert [b.text for row in presented[0].buttons or [] for b in row] == ["✅", "❌"]


def test_vcrm038_reintento_al_minuto(env: Env) -> None:
    env.activate()
    lead_id = make_lead(env.db, env.com)
    due_cadence(env, lead_id)
    env.run(NOW)  # genera la propuesta
    with env.db.read() as conn:
        pid = conn.execute("SELECT id FROM crm_proposals").fetchone()[0]
    with env.db.tx() as tx:
        gate.approve(tx, env.com, pid, 1, NOW, KEYS)
    env.email.fail_next(EMAIL, 1)

    env.run(NOW)  # intento 1 (minuto 0): falla
    assert len(env.email.attempts) == 1 and env.email.sent == []
    env.run(NOW + timedelta(seconds=30))  # aún no toca
    assert len(env.email.attempts) == 1
    env.run(NOW + timedelta(minutes=1))  # intento 2: sale

    assert len(env.email.sent) == 1 and len(env.email.attempts) == 2
    with env.db.read() as conn:
        cadence = repo.get_cadence(conn, lead_id)
    assert cadence is not None and cadence.steps_done == 1 and cadence.sent_count == 1


def test_vcrm034_el_barrido_expira_las_propuestas_y_avanza_la_cadencia(env: Env) -> None:
    env.activate()
    lead_id = make_lead(env.db, env.com)
    due_cadence(env, lead_id)
    env.run(NOW)
    before = len(env.texts_to(COM_TG))

    env.run(NOW + timedelta(hours=48, minutes=1))

    with env.db.read() as conn:
        proposal = conn.execute("SELECT status FROM crm_proposals").fetchone()[0]
        cadence = repo.get_cadence(conn, lead_id)
    assert proposal == "expired"
    assert cadence is not None and cadence.steps_done == 1
    assert len(env.texts_to(COM_TG)) > before and "expiró" in env.texts_to(COM_TG)[-1]


# --- Buzón ------------------------------------------------------------------------------------


def test_vcrm169_periodo_de_consulta_respetado(env: Env) -> None:
    env.activate()
    env.run(NOW)
    env.run(NOW + timedelta(minutes=1))
    env.run(NOW + timedelta(minutes=4))
    assert len(env.inbox.fetches) == 1
    env.run(NOW + timedelta(minutes=5))
    assert len(env.inbox.fetches) == 2


def test_vcrm102_el_barrido_aplica_una_baja_recibida_por_correo(env: Env) -> None:
    env.activate()
    lead_id = make_lead(env.db, env.com)
    make_sent(env.db, lead_id, env.com, SENT)
    env.inbox.add(make_inbound(1, "baja", in_reply_to=SENT))

    env.run(NOW)

    with env.db.read() as conn:
        assert repo.get_lead(conn, lead_id).state == "opted_out"  # type: ignore[union-attr]
    assert "Baja aplicada" in env.texts_to(COM_TG)[-1]


def test_vcrm170_fallo_de_un_paso_no_detiene_los_otros(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    env.activate()
    lead_id = make_lead(env.db, env.com)
    due_cadence(env, lead_id)
    env.inbox.fail_next(RuntimeError("fallo inesperado del buzón con secreto-no-real"))

    env.run(NOW)

    with env.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM crm_proposals").fetchone()[0] == 1  # siguió
    assert "secreto-no-real" not in caplog.text  # el log lleva el tipo de error, no su texto


def test_el_fallo_al_avisar_por_telegram_se_registra_sin_cuerpo(env: Env) -> None:
    env.activate()
    lead_id = make_lead(env.db, env.com)
    due_cadence(env, lead_id)
    env.tg.fail_next(COM_TG, 1)

    env.run(NOW)

    with env.db.read() as conn:
        rows = conn.execute("SELECT * FROM crm_outbox WHERE status = 'failed'").fetchall()
    assert len(rows) == 1 and rows[0]["body"] is None  # sin datos personales


# --- Primer intento en línea (D-3) --------------------------------------------------------------


def test_deliver_now_envia_lo_aprobado_sin_esperar_al_barrido(env: Env) -> None:
    env.activate()
    lead_id = make_lead(env.db, env.com)
    due_cadence(env, lead_id)
    env.run(NOW)
    with env.db.read() as conn:
        pid = conn.execute("SELECT id FROM crm_proposals").fetchone()[0]
    with env.db.tx() as tx:
        gate.approve(tx, env.com, pid, 1, NOW, KEYS)

    asyncio.run(sweep.deliver_now(env.ctx, NOW))

    assert len(env.email.sent) == 1
    with env.db.read() as conn:
        assert repo.get_proposal(conn, pid).status == "sent"  # type: ignore[union-attr]


def test_deliver_now_no_hace_nada_si_f2_no_esta_activa(tmp_path: Path) -> None:
    env = Env(tmp_path)
    asyncio.run(sweep.deliver_now(env.ctx, NOW))
    assert env.email.attempts == []
    env.close()


def test_deliver_now_no_hace_nada_si_faltan_ajustes_f2(tmp_path: Path) -> None:
    env = Env(tmp_path, settings=make_settings())
    asyncio.run(sweep.deliver_now(env.ctx, NOW))
    assert env.email.attempts == []
    env.close()
