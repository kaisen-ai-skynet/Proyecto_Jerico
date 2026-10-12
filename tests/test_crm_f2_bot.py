"""F2-T21 y T24 — Botones y comando de la fase 2 llevados por el bot real (`CrmBot`).

Requisitos: VCRM-020, 022..024, 026, 029..035, 038, 068, 119, 141..143, 149 y 153.
Cada botón solo traduce a una función de servicio ya probada; aquí se comprueba el cableado, que
un argumento inválido no haga nada y que una persona sin permiso quede denegada y auditada.
"""

import asyncio
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from crm_support import FakeClock, FakeEmailSender, FakeTelegram, make_settings
from f2_support import (
    COM_TG,
    CTO_TG,
    EMAIL,
    KEYS,
    NOW,
    UNSUB_ADDR,
    make_inbound,
    make_lead,
    make_proposal,
    make_sent,
)
from jerico.crm import delivery, f2_bot, replies, repo
from jerico.crm.bot import INVALID_BUTTON, CrmBot
from jerico.crm.config import default_params
from jerico.crm.db import CrmDatabase
from jerico.crm.f2_bot import F2Context
from jerico.crm.model import Cadence, LeadState, ProposalKind, ProposalStatus, Role
from jerico.crm.ports import Update
from jerico.crm.timeutil import to_iso

OTHER_TG, LAW_TG = 2100, 3000
_ids = iter(range(1, 1_000_000))


class Env:
    def __init__(self, tmp_path: Path, settings: Any = None) -> None:
        self.db = CrmDatabase(tmp_path / "crm.db")
        self.tg = FakeTelegram()
        self.clock = FakeClock(NOW)
        self.kicks = 0
        with self.db.tx() as tx:
            repo.set_meta(tx, "f2_activated_at", to_iso(NOW))
            self.users = {
                "cto": repo.insert_user(
                    tx, telegram_id=CTO_TG, role=Role.CTO, email="c@k.co", now=NOW
                ),
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
        self.bot = CrmBot(
            self.db, self.tg, self.clock.now, fingerprint_keys=KEYS, params=default_params()
        )
        f2_bot.register_f2(
            self.bot,
            F2Context(
                keys=KEYS,
                params=default_params(),
                settings=settings or make_settings(),
                sender_name="Kaisen AI",
                kick_delivery=self._kick,
            ),
        )

    def _kick(self) -> None:
        self.kicks += 1

    def press(self, who: str, data: str) -> list[str]:
        """Pulsa un botón y devuelve los textos que el bot respondió en esa interacción."""
        before = len(self.tg.sent)
        user = self.users[who]
        update = Update(
            update_id=next(_ids),
            user_id=user.telegram_id,
            chat_id=user.telegram_id,
            chat_type="private",
            callback_id="cb",
            callback_data=data,
        )
        asyncio.run(self.bot.process_update(update))
        return [s.text for s in self.tg.sent[before:]]

    def say(self, who: str, text: str) -> list[str]:
        before = len(self.tg.sent)
        user = self.users[who]
        update = Update(
            update_id=next(_ids),
            user_id=user.telegram_id,
            chat_id=user.telegram_id,
            chat_type="private",
            text=text,
        )
        asyncio.run(self.bot.process_update(update))
        return [s.text for s in self.tg.sent[before:]]

    def labels_of_last(self) -> list[str]:
        last = self.tg.sent[-1]
        return [b.text for row in (last.buttons or []) for b in row]

    def close(self) -> None:
        self.db.close()


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    e = Env(tmp_path)
    yield e
    e.close()


def joined(texts: list[str]) -> str:
    return "\n".join(texts)


def waiting_cadence(env: Env, lead_id: int, steps_done: int = 0) -> None:
    """Cadencia a la espera de la decisión del aprobador (la deja así `generate_due`)."""
    with env.db.tx() as tx:
        repo.upsert_cadence(
            tx,
            Cadence(
                lead_id,
                "precio",
                30,
                3,
                steps_done=steps_done,
                next_action_at=None,
                started_at=to_iso(NOW),
                updated_at=to_iso(NOW),
            ),
        )


# --- Gate -----------------------------------------------------------------------------------


def test_vcrm029_boton_ok_aprueba_programa_y_pide_el_envio(env: Env) -> None:
    lead_id = make_lead(env.db, env.users["com"])
    pid = make_proposal(env.db, lead_id, env.users["com"])

    out = env.press("com", f"v1:gok:{pid}:1")

    assert "Aprobado" in joined(out)
    with env.db.read() as conn:
        send = repo.get_send_by_proposal(conn, pid)
    assert send is not None and send.status == "scheduled"
    assert env.kicks == 1  # dentro de franja y cupo: primer intento en línea


def test_vcrm030_doble_pulsacion_en_dos_updates(env: Env) -> None:
    lead_id = make_lead(env.db, env.users["com"])
    pid = make_proposal(env.db, lead_id, env.users["com"])
    env.press("com", f"v1:gok:{pid}:1")

    again = env.press("com", f"v1:gok:{pid}:1")
    reject_after = env.press("com", f"v1:gno:{pid}:1")

    assert "ya fue procesada" in joined(again) and "ya fue procesada" in joined(reject_after)
    assert env.kicks == 1
    with env.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM crm_sends").fetchone()[0] == 1


def test_vcrm031_rechazo_ofrece_opciones_y_cancelar_consume_el_paso(env: Env) -> None:
    lead_id = make_lead(env.db, env.users["com"])
    pid = make_proposal(env.db, lead_id, env.users["com"])
    waiting_cadence(env, lead_id)

    env.press("com", f"v1:gno:{pid}:1")
    assert env.labels_of_last() == ["Cancelar envío", "Reescribir"]
    out = env.press("com", f"v1:gcan:{pid}")

    assert "cancelado" in joined(out).lower()
    with env.db.read() as conn:
        cadence = repo.get_cadence(conn, lead_id)
        proposal = repo.get_proposal(conn, pid)
    assert proposal is not None and proposal.status == ProposalStatus.CANCELLED
    assert cadence is not None and cadence.steps_done == 1  # la cadencia saltó al paso siguiente
    assert cadence.next_action_at == to_iso(NOW + timedelta(days=30))


def test_vcrm033_reescribir_por_texto_libre(env: Env) -> None:
    lead_id = make_lead(env.db, env.users["com"])
    pid = make_proposal(env.db, lead_id, env.users["com"])

    asked = env.press("com", f"v1:grew:{pid}")
    assert "texto nuevo" in joined(asked)
    retry = env.say("com", "   ")  # texto vacío: sigue esperando
    assert "no válido" in joined(retry).lower()
    presented = env.say("com", "Hola Ana, texto reescrito.")

    assert "versión 2" in joined(presented) and "texto reescrito" in joined(presented)
    assert env.labels_of_last() == ["✅", "❌"]
    with env.db.read() as conn:
        proposal = repo.get_proposal(conn, pid)
        assert repo.get_pending_input(conn, env.users["com"].id, NOW) is None
    assert proposal is not None and proposal.current_version == 2
    stale = env.press("com", f"v1:gok:{pid}:1")
    assert "reemplazada" in joined(stale)


@pytest.mark.parametrize("who", ["other", "law"])
def test_vcrm035_boton_de_quien_no_decide_se_deniega_y_se_audita(env: Env, who: str) -> None:
    lead_id = make_lead(env.db, env.users["com"])
    pid = make_proposal(env.db, lead_id, env.users["com"])

    for data in (f"v1:gok:{pid}:1", f"v1:gno:{pid}:1", f"v1:gcan:{pid}", f"v1:grew:{pid}"):
        assert "permiso" in joined(env.press(who, data)).lower()

    assert env.kicks == 0
    with env.db.read() as conn:
        assert repo.get_send_by_proposal(conn, pid) is None
        denied = [a for a in repo.audit_rows(conn) if a["action"] == "permission_denied"]
    assert len(denied) == 4


def test_botones_con_argumentos_invalidos_no_hacen_nada(env: Env) -> None:
    for data in ("v1:gok:x:1", "v1:gok:1", "v1:gcan:a", "v1:aok:z", "v1:rbaja:", "v1:cpausar:q"):
        assert INVALID_BUTTON in joined(env.press("com", data)), data
    assert env.kicks == 0


# --- Envío fallido ---------------------------------------------------------------------------


def failed_send(env: Env, lead_id: int, address: str = EMAIL) -> int:
    pid = make_proposal(env.db, lead_id, env.users["com"])
    with env.db.tx() as tx:
        proposal = repo.get_proposal(tx, pid)
        version = repo.get_proposal_version(tx, pid, 1)
        lead = repo.get_lead(tx, lead_id)
        assert proposal and version and lead
        delivery.schedule_send(
            tx,
            proposal=proposal,
            version=version,
            lead=lead,
            approved_by=env.users["com"].id,
            now=NOW,
        )
    email = FakeEmailSender()
    email.fail_next(address, 3)
    for minutes in (0, 1, 5):
        asyncio.run(
            delivery.deliver_due(
                env.db,
                email,
                NOW + timedelta(minutes=minutes),
                default_params(),
                KEYS,
                unsub_address=UNSUB_ADDR,
            )
        )
    with env.db.read() as conn:
        send = repo.get_send_by_proposal(conn, pid)
    assert send is not None and send.status == "failed"
    return pid


def test_vcrm038_reintentar_un_envio_fallido(env: Env) -> None:
    lead_id = make_lead(env.db, env.users["com"])
    pid = failed_send(env, lead_id)
    assert "permiso" in joined(env.press("other", f"v1:freint:{pid}")).lower()
    assert env.kicks == 0

    out = env.press("com", f"v1:freint:{pid}")

    assert "Reintento programado" in joined(out) and env.kicks == 1
    with env.db.read() as conn:
        send = repo.get_send_by_proposal(conn, pid)
    assert send is not None and (send.status, send.attempts) == ("scheduled", 0)
    assert "ya fue procesada" in joined(env.press("com", f"v1:freint:{pid}"))  # ya no está fallido


def test_vcrm038_cancelar_un_envio_fallido_consume_el_paso(env: Env) -> None:
    lead_id = make_lead(env.db, env.users["com"])
    waiting_cadence(env, lead_id)
    pid = failed_send(env, lead_id)
    assert "permiso" in joined(env.press("law", f"v1:fcancel:{pid}")).lower()

    out = env.press("com", f"v1:fcancel:{pid}")

    assert "Envío cancelado" in joined(out)
    with env.db.read() as conn:
        cadence = repo.get_cadence(conn, lead_id)
    assert cadence is not None and cadence.steps_done == 1
    assert "ya fue procesada" in joined(env.press("com", f"v1:fcancel:{pid}"))


# --- Autorización por correo -----------------------------------------------------------------


def candidate(env: Env) -> tuple[int, int]:
    lead_id = make_lead(env.db, env.users["com"], state=LeadState.CONTACTED)
    with env.db.tx() as tx:
        repo.update_lead(tx, lead_id, {"auth_status": "unauthorized"}, now=NOW)
        tx.execute("DELETE FROM crm_consents WHERE lead_id = ?", (lead_id,))
    make_sent(
        env.db,
        lead_id,
        env.users["com"],
        "<a@kaisen.test>",
        kind=ProposalKind.AUTH_REQUEST,
        step=None,
    )
    with env.db.tx() as tx:
        replies.process_message(
            tx,
            make_inbound(1, "Sí, autorizo.", in_reply_to="<a@kaisen.test>"),
            NOW,
            default_params(),
            KEYS,
        )
        inbound = repo.list_inbound(tx)[0]
    return lead_id, inbound.id


def test_vcrm141_botones_de_autorizacion(env: Env) -> None:
    lead_id, inbound_id = candidate(env)
    assert "permiso" in joined(env.press("other", f"v1:aok:{inbound_id}")).lower()

    out = env.press("com", f"v1:aok:{inbound_id}")

    assert "Autorización registrada" in joined(out)
    assert "ya fue procesada" in joined(env.press("com", f"v1:ano:{inbound_id}"))
    with env.db.read() as conn:
        assert repo.get_lead(conn, lead_id).auth_status == "authorized"  # type: ignore[union-attr]


def test_vcrm142_boton_no_deja_el_lead_sin_autorizacion(env: Env) -> None:
    lead_id, inbound_id = candidate(env)

    out = env.press("com", f"v1:ano:{inbound_id}")

    assert "no se tomó como autorización" in joined(out)
    with env.db.read() as conn:
        assert repo.get_lead(conn, lead_id).auth_status == "unauthorized"  # type: ignore[union-attr]


def test_vcrm068_comando_pedir_autorizacion(env: Env) -> None:
    lead_id = make_lead(env.db, env.users["com"], state=LeadState.CONTACTED)
    with env.db.tx() as tx:
        repo.update_lead(tx, lead_id, {"auth_status": "unauthorized"}, now=NOW)
        tx.execute("DELETE FROM crm_consents WHERE lead_id = ?", (lead_id,))

    assert "Formato no válido" in joined(env.say("com", "/pedirautorizacion"))
    assert "Formato no válido" in joined(env.say("com", "/pedirautorizacion abc"))
    assert "permiso" in joined(env.say("other", "/pedirautorizacion L-0001")).lower()
    out = env.say("com", "/pedirautorizacion L-0001")

    assert "Autorización para el tratamiento" in joined(
        out
    ) or "Solicitud de autorización" in joined(out)
    assert env.labels_of_last() == ["✅", "❌"]
    with env.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM crm_proposals").fetchone()[0] == 1


def test_vcrm149_comando_sin_configuracion_informa(tmp_path: Path) -> None:
    broken = Env(tmp_path, make_settings(privacy_notice_file=tmp_path / "no-existe.md"))
    lead_id = make_lead(broken.db, broken.users["com"], state=LeadState.CONTACTED)
    with broken.db.tx() as tx:
        repo.update_lead(tx, lead_id, {"auth_status": "unauthorized"}, now=NOW)
        tx.execute("DELETE FROM crm_consents WHERE lead_id = ?", (lead_id,))

    out = broken.say("com", "/pedirautorizacion L-0001")

    assert "Falta la configuración" in joined(out)
    with broken.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM crm_proposals").fetchone()[0] == 0
    broken.close()


# --- Respuestas «por clasificar» ---------------------------------------------------------------


def review(env: Env) -> tuple[int, int]:
    lead_id = make_lead(env.db, env.users["com"])
    make_sent(env.db, lead_id, env.users["com"], "<s@kaisen.test>")
    with env.db.tx() as tx:
        replies.process_message(
            tx,
            make_inbound(1, "Tengo una duda", in_reply_to="<s@kaisen.test>"),
            NOW,
            default_params(),
            KEYS,
        )
        (request,) = repo.titular_requests(tx)
    return lead_id, request.id


def test_vcrm153_boton_aplicar_baja(env: Env) -> None:
    lead_id, request_id = review(env)
    assert "permiso" in joined(env.press("law", f"v1:rbaja:{request_id}")).lower()

    out = env.press("com", f"v1:rbaja:{request_id}")

    assert "Baja aplicada" in joined(out)
    with env.db.read() as conn:
        assert repo.get_lead(conn, lead_id).state == "opted_out"  # type: ignore[union-attr]


def test_vcrm153_botones_registrar_consulta_o_reclamo(env: Env) -> None:
    _lead, request_id = review(env)

    asked = env.press("com", f"v1:rclas:{request_id}")
    assert "¿Qué tipo" in joined(asked) and env.labels_of_last() == ["Consulta", "Reclamo"]
    out = env.press("com", f"v1:rrec:{request_id}")

    assert "reclamo" in joined(out).lower()
    with env.db.read() as conn:
        assert repo.get_titular_request(conn, request_id).type == "claim"  # type: ignore[union-attr]
    assert "ya fue procesada" in joined(env.press("com", f"v1:rcon:{request_id}"))


def test_vcrm153_boton_sin_solicitud(env: Env) -> None:
    _lead, request_id = review(env)
    assert "cerrada" in joined(env.press("com", f"v1:rsin:{request_id}")).lower()


# --- Cadencia: ficha y aviso de cadencia completada --------------------------------------------


def nurturing_with_cadence(env: Env) -> int:
    lead_id = make_lead(env.db, env.users["com"])
    with env.db.tx() as tx:
        repo.upsert_cadence(
            tx,
            Cadence(
                lead_id,
                "precio",
                30,
                3,
                next_action_at=to_iso(NOW + timedelta(days=30)),
                started_at=to_iso(NOW),
                updated_at=to_iso(NOW),
            ),
        )
    return lead_id


def state_of(env: Env, lead_id: int) -> str:
    with env.db.read() as conn:
        lead = repo.get_lead(conn, lead_id)
    assert lead is not None
    return lead.state


def test_vcrm020_botones_de_cadencia(env: Env) -> None:
    lead_id = nurturing_with_cadence(env)
    assert "permiso" in joined(env.press("other", f"v1:cpausar:{lead_id}")).lower()

    assert "pausada" in joined(env.press("com", f"v1:cpausar:{lead_id}"))
    assert state_of(env, lead_id) == "paused"
    assert "reanudada" in joined(env.press("com", f"v1:creanudar:{lead_id}"))
    assert state_of(env, lead_id) == "nurturing"
    assert "semanal" in joined(env.press("com", f"v1:cfrec7:{lead_id}"))
    with env.db.read() as conn:
        assert repo.get_cadence(conn, lead_id).interval_days == 7  # type: ignore[union-attr]
    assert "mensual" in joined(env.press("com", f"v1:cfrec30:{lead_id}"))
    with env.db.read() as conn:
        assert repo.get_cadence(conn, lead_id).interval_days == 30  # type: ignore[union-attr]
    assert "reactivado" in joined(env.press("com", f"v1:creactivar:{lead_id}"))
    assert state_of(env, lead_id) == "reactivated"


def test_vcrm026_boton_marcar_perdido(env: Env) -> None:
    lead_id = nurturing_with_cadence(env)
    assert "permiso" in joined(env.press("law", f"v1:cperdido:{lead_id}")).lower()

    out = env.press("com", f"v1:cperdido:{lead_id}")

    assert state_of(env, lead_id) == "lost" and out


# --- Vista /seguimiento (F2-T22, VCRM-025) -----------------------------------------------------


def test_vcrm025_vista_seguimiento_visibilidad(env: Env) -> None:
    lead_com = nurturing_with_cadence(env)
    lead_other = make_lead(env.db, env.users["other"], state=LeadState.NURTURING)
    with env.db.tx() as tx:
        repo.upsert_cadence(
            tx,
            Cadence(
                lead_other,
                "momento",
                7,
                3,
                next_action_at=to_iso(NOW + timedelta(days=7)),
                started_at=to_iso(NOW),
                updated_at=to_iso(NOW),
            ),
        )

    # Abogado no tiene acceso (plan-f2 §5.9; spec §4.4)
    out_law = env.say("law", "/seguimiento")
    assert "permiso" in joined(out_law).lower() or "denegad" in joined(out_law).lower()

    # Comercial solo ve el suyo
    out_com = env.say("com", "/seguimiento")
    text_com = joined(out_com)
    assert f"L-{lead_com:04d}" in text_com
    assert f"L-{lead_other:04d}" not in text_com

    # CTO ve ambos
    out_cto = env.say("cto", "/seguimiento")
    text_cto = joined(out_cto)
    assert f"L-{lead_com:04d}" in text_cto
    assert f"L-{lead_other:04d}" in text_cto


def test_vcrm025_incluye_motivo_frecuencia_proxima_y_envios(env: Env) -> None:
    lead_id = nurturing_with_cadence(env)
    out = env.say("com", "/seguimiento")
    text = joined(out)
    assert f"L-{lead_id:04d}" in text
    assert "Precio o presupuesto" in text
    assert "mensual" in text
    assert "0 envíos" in text

    # Cambiar a pausada
    with env.db.tx() as tx:
        repo.update_lead(tx, lead_id, {"state": LeadState.PAUSED.value}, now=NOW)
        repo.upsert_cadence(
            tx,
            Cadence(
                lead_id,
                "precio",
                30,
                3,
                status="paused",
                next_action_at=None,
                started_at=to_iso(NOW),
                updated_at=to_iso(NOW),
            ),
        )
    out_paused = env.say("com", "/seguimiento")
    assert "pausada" in joined(out_paused)


def test_vcrm025_vista_vacia(env: Env) -> None:
    out = env.say("com", "/seguimiento")
    assert "No hay leads en seguimiento." in joined(out)


def test_vcrm025_no_muestra_suprimidos_ni_otros_estados(env: Env) -> None:
    make_lead(env.db, env.users["com"], state=LeadState.NEW)
    make_lead(env.db, env.users["com"], state=LeadState.CONTACTED)
    make_lead(env.db, env.users["com"], state=LeadState.ACCEPTED)
    make_lead(env.db, env.users["com"], state=LeadState.LOST)
    make_lead(env.db, env.users["com"], state=LeadState.OPTED_OUT)
    sup_id = nurturing_with_cadence(env)
    with env.db.tx() as tx:
        repo.update_lead(tx, sup_id, {"suppressed_at": to_iso(NOW)}, now=NOW)

    out = env.say("com", "/seguimiento")
    assert "No hay leads en seguimiento." in joined(out)


def test_vcrm025_sin_datos_personales(env: Env) -> None:
    lead_id = nurturing_with_cadence(env)
    out = env.say("com", "/seguimiento")
    text = joined(out)
    assert f"L-{lead_id:04d}" in text
    assert "Ana Pérez" not in text
    assert "+573001112233" not in text
    assert EMAIL not in text


# --- Botones de cadencia en la ficha (F2-T23, VCRM-020, 022..024) -----------------------------


def test_vcrm020_ficha_muestra_botones_pausar_y_frecuencia(env: Env) -> None:
    lead_id = nurturing_with_cadence(env)
    env.say("com", f"/ver L-{lead_id:04d}")
    labels = env.labels_of_last()
    assert "Pausar" in labels
    assert "Reactivar" in labels
    assert "Frecuencia semanal" in labels
    assert "Frecuencia mensual" in labels
    assert "Perdido" in labels


def test_vcrm022_ficha_muestra_boton_reanudar(env: Env) -> None:
    lead_id = nurturing_with_cadence(env)
    with env.db.tx() as tx:
        repo.update_lead(tx, lead_id, {"state": LeadState.PAUSED.value}, now=NOW)
    env.say("com", f"/ver L-{lead_id:04d}")
    labels = env.labels_of_last()
    assert "Reanudar" in labels
    assert "Reactivar" in labels
    assert "Pausar" not in labels
    assert "Frecuencia semanal" not in labels


def test_vcrm024_ficha_rechazado_muestra_reactivar(env: Env) -> None:
    lead_id = make_lead(env.db, env.users["com"], state=LeadState.REJECTED)
    env.say("com", f"/ver L-{lead_id:04d}")
    labels = env.labels_of_last()
    assert "Reactivar" in labels
    assert "Pausar" not in labels
    assert "Reanudar" not in labels


def test_vcrm020_ficha_f2_inactiva_sin_botones_cadencia(env: Env) -> None:
    lead_id = nurturing_with_cadence(env)
    with env.db.tx() as tx:
        tx.execute("DELETE FROM crm_meta WHERE key = 'f2_activated_at'")
    env.say("com", f"/ver L-{lead_id:04d}")
    labels = env.labels_of_last()
    assert "Pausar" not in labels
    assert "Reactivar" not in labels
    assert "Frecuencia semanal" not in labels


def test_vcrm025_casos_cadencia_seguimiento(env: Env) -> None:
    # 1. Lead sin cadencia
    lead_nocad = make_lead(env.db, env.users["com"], state=LeadState.NURTURING)
    # 2. Cadencia con intervalo distinto (14 días) y completada
    lead_comp = make_lead(env.db, env.users["com"], state=LeadState.NURTURING)
    # 3. Cadencia a la espera de decisión (next_action_at is None)
    lead_wait = make_lead(env.db, env.users["com"], state=LeadState.NURTURING)

    with env.db.tx() as tx:
        repo.upsert_cadence(
            tx,
            Cadence(
                lead_comp,
                "precio",
                14,
                3,
                status="completed",
                next_action_at=None,
                started_at=to_iso(NOW),
                updated_at=to_iso(NOW),
            ),
        )
        repo.upsert_cadence(
            tx,
            Cadence(
                lead_wait,
                "precio",
                7,
                3,
                status="active",
                next_action_at=None,
                started_at=to_iso(NOW),
                updated_at=to_iso(NOW),
            ),
        )

    out = env.say("com", "/seguimiento")
    text = joined(out)
    assert f"L-{lead_nocad:04d} · sin cadencia" in text
    assert f"L-{lead_comp:04d}" in text and "cada 14 días" in text and "completada" in text
    assert f"L-{lead_wait:04d}" in text and "a la espera de decisión" in text

    # Ficha del lead sin cadencia no tiene botones de pausar
    env.say("com", f"/ver L-{lead_nocad:04d}")
    assert "Pausar" not in env.labels_of_last()


def test_vcrm020_cadence_buttons_estados_y_permisos(env: Env) -> None:
    from jerico.crm import followup_view

    with env.db.read() as conn:
        lead_com = repo.get_lead(conn, nurturing_with_cadence(env))
        assert lead_com is not None

        # Comercial ajeno denegado
        other_user = env.users["other"]
        assert followup_view.cadence_buttons(conn, other_user, lead_com) == ()

        # Lead en NEW no tiene botones de cadencia
        lead_new_id = make_lead(env.db, env.users["com"], state=LeadState.NEW)
        lead_new = repo.get_lead(conn, lead_new_id)
        assert lead_new is not None
        assert followup_view.cadence_buttons(conn, env.users["com"], lead_new) == ()
