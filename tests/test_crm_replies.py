"""F2-T18 — Procesamiento de respuestas entrantes.

Requisitos: VCRM-102, 103, 119, 120, 122, 124, 153, 169 y 170.

Aquí se prueba lo más delicado de F2: una respuesta puede dar de baja a un titular de inmediato, o
no debe hacerlo nunca por error. Lo que no se pueda asociar a un lead va a revisión humana.
"""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from crm_support import FakeInbox
from f2_support import (
    COM_TG,
    CTO_TG,
    EMAIL,
    KEYS,
    NOW,
    make_inbound,
    make_lead,
    make_proposal,
    make_sent,
)
from jerico.crm import compliance, replies, repo
from jerico.crm.config import default_params
from jerico.crm.db import CrmDatabase
from jerico.crm.fingerprint import fingerprint
from jerico.crm.inbound import make_unsub_token
from jerico.crm.model import (
    SYSTEM_USER_ID,
    Cadence,
    LeadState,
    Outgoing,
    ProposalKind,
    ProposalStatus,
    RequestType,
    Role,
    User,
)
from jerico.crm.ports import InboundMessage, InboxError
from jerico.crm.render import short_id
from jerico.crm.timeutil import local_date, to_iso

PHONE = "+573001112233"
SENT_ID = "<sent1@kaisen.test>"


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


def process(db: CrmDatabase, msg: InboundMessage, now: Any = NOW) -> list[Outgoing]:
    with db.tx() as tx:
        return replies.process_message(tx, msg, now, default_params(), KEYS)


def lead_row(db: CrmDatabase, lead_id: int) -> dict[str, Any]:
    with db.read() as conn:
        return dict(conn.execute("SELECT * FROM crm_leads WHERE id = ?", (lead_id,)).fetchone())


def inbound_rows(db: CrmDatabase) -> list[Any]:
    with db.read() as conn:
        return repo.list_inbound(conn)


def labels(out: list[Outgoing]) -> list[str]:
    return [label for o in out for row in o.buttons for label, _ in row]


def chats(out: list[Outgoing]) -> set[int]:
    return {o.chat_id for o in out}


def texts(out: list[Outgoing]) -> str:
    return "\n".join(o.text for o in out)


def fp_suppressed(db: CrmDatabase, contact: str, key: str = KEYS[0]) -> bool:
    with db.read() as conn:
        return repo.any_suppressed(conn, [fingerprint(key, contact)])


# --- VCRM-102 / 120: baja por la palabra clave -------------------------------------------------


def test_vcrm102_baja_por_respuesta_inmediata(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = make_lead(db, users["com"])
    make_sent(db, lead_id, users["com"], SENT_ID)
    pending = make_proposal(db, lead_id, users["com"], step=2)  # un seguimiento aún sin decidir
    with db.tx() as tx:
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

    out = process(db, make_inbound(1, "baja por favor", in_reply_to=SENT_ID))

    row = lead_row(db, lead_id)
    assert (row["state"], row["auth_status"]) == ("opted_out", "revoked")
    assert fp_suppressed(db, EMAIL) and fp_suppressed(db, PHONE)  # solo huellas (VCRM-095)
    with db.read() as conn:
        consent = repo.lead_consents(conn, lead_id)[-1]
        event = conn.execute(
            "SELECT * FROM crm_lead_events WHERE lead_id = ? AND kind = 'state' "
            "ORDER BY id DESC LIMIT 1",
            (lead_id,),
        ).fetchone()
        cadence = repo.get_cadence(conn, lead_id)
        proposal = repo.get_proposal(conn, pending)
    assert (consent["status"], consent["medium"]) == ("revoked", "respuesta al correo")
    assert consent["actor_user_id"] == SYSTEM_USER_ID  # la aplicó el sistema, no un usuario
    assert (event["new_value"], event["actor_user_id"]) == ("opted_out", SYSTEM_USER_ID)
    assert cadence is not None and cadence.status == "stopped"
    assert proposal is not None and proposal.status == ProposalStatus.CANCELLED
    (inbound,) = inbound_rows(db)
    assert (inbound.classification, inbound.association, inbound.decision) == (
        "stop_keyword",
        "thread",
        "n/a",
    )
    assert chats(out) == {COM_TG} and "Baja aplicada" in texts(out)
    assert short_id(lead_id) in texts(out) and labels(out) == []


def test_vcrm102_sin_acuse_al_titular(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = make_lead(db, users["com"])
    make_sent(db, lead_id, users["com"], SENT_ID)
    with db.read() as conn:
        before = conn.execute("SELECT COUNT(*) FROM crm_sends").fetchone()[0]

    process(db, make_inbound(1, "BAJA", in_reply_to=SENT_ID))

    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM crm_sends").fetchone()[0] == before
        assert (
            conn.execute("SELECT COUNT(*) FROM crm_outbox WHERE channel = 'email'").fetchone()[0]
            == 0
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM crm_proposals WHERE kind = 'ack'").fetchone()[0] == 0
        )


def test_vcrm102_la_cita_y_el_pie_no_cuentan_como_baja(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    make_sent(db, lead_id, users["com"], SENT_ID)
    body = (
        "Me interesa, hablemos.\n"
        "\n"
        "> Kaisen AI\n"
        "> Responda BAJA para no recibir más mensajes.\n"
        "Responda BAJA para no recibir más mensajes.\n"
    )

    process(db, make_inbound(1, body, in_reply_to=SENT_ID))

    assert lead_row(db, lead_id)["state"] == "nurturing"  # no se dio de baja
    assert inbound_rows(db)[0].classification == "review"


def test_vcrm102_lineas_reproducidas_del_mensaje_enviado_no_cuentan(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    sent_body = (
        "Hola Ana,\nSi no desea más mensajes escriba la palabra BAJA en su respuesta.\nSaludos"
    )
    make_sent(db, lead_id, users["com"], SENT_ID, body=sent_body)
    reply = (
        "Gracias, lo reviso.\nSi no desea más mensajes escriba la palabra BAJA en su respuesta.\n"
    )

    process(db, make_inbound(1, reply, in_reply_to=SENT_ID))

    assert lead_row(db, lead_id)["state"] == "nurturing"
    assert inbound_rows(db)[0].new_text == "Gracias, lo reviso."


def test_vcrm120_baja_en_respuesta_a_solicitud_no_propone_autorizacion(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"], state=LeadState.CONTACTED)
    with db.tx() as tx:
        repo.update_lead(tx, lead_id, {"auth_status": "unauthorized"}, now=NOW)
    make_sent(db, lead_id, users["com"], SENT_ID, kind=ProposalKind.AUTH_REQUEST, step=None)

    out = process(db, make_inbound(1, "Acepto, pero mejor BAJA, gracias", in_reply_to=SENT_ID))

    assert lead_row(db, lead_id)["state"] == "opted_out"
    assert inbound_rows(db)[0].classification == "stop_keyword"
    assert "✅" not in labels(out) and "Baja aplicada" in texts(out)
    with db.read() as conn:
        assert repo.lead_consents(conn, lead_id)[-1]["status"] == "revoked"  # prevalece la baja


# --- VCRM-119: la respuesta a una solicitud se propone, no se registra ---------------------------


def test_vcrm119_propone_sin_registrar(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = make_lead(db, users["com"], state=LeadState.REJECTED)
    with db.tx() as tx:
        repo.update_lead(tx, lead_id, {"auth_status": "unauthorized"}, now=NOW)
    make_sent(db, lead_id, users["com"], SENT_ID, kind=ProposalKind.AUTH_REQUEST, step=None)
    with db.read() as conn:
        consents_before = len(repo.lead_consents(conn, lead_id))

    out = process(db, make_inbound(1, "Sí, los autorizo.", in_reply_to=SENT_ID))

    (inbound,) = inbound_rows(db)
    assert (inbound.classification, inbound.decision) == ("auth_candidate", "pending")
    assert lead_row(db, lead_id)["auth_status"] == "unauthorized"  # nada se registra aún
    with db.read() as conn:
        assert len(repo.lead_consents(conn, lead_id)) == consents_before
        assert repo.titular_requests(conn) == []
    assert chats(out) == {COM_TG} and labels(out) == ["✅", "❌"]
    assert out[0].buttons[0][0][1] == f"v1:aok:{inbound.id}"
    assert out[0].buttons[0][1][1] == f"v1:ano:{inbound.id}"
    assert "Sí, los autorizo." in texts(out) and "hilo" in texts(out)


def test_respuesta_normal_a_un_lead_ya_autorizado_no_es_candidata(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])  # autorizado
    make_sent(db, lead_id, users["com"], SENT_ID, kind=ProposalKind.AUTH_REQUEST, step=None)
    process(db, make_inbound(1, "Gracias", in_reply_to=SENT_ID))
    assert inbound_rows(db)[0].classification == "review"


# --- VCRM-103 / 153: revisión humana ------------------------------------------------------------


def test_vcrm103_respuesta_a_revision_del_comercial(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    make_sent(db, lead_id, users["com"], SENT_ID)

    out = process(db, make_inbound(1, "Me interesa, hablemos.", in_reply_to=SENT_ID))

    assert lead_row(db, lead_id)["state"] == "nurturing"  # sin cambiar de estado
    (inbound,) = inbound_rows(db)
    assert (inbound.classification, inbound.association) == ("review", "thread")
    with db.read() as conn:
        (request,) = repo.titular_requests(conn)
    assert request.type == "unclassified" and request.lead_id == lead_id
    assert request.medium == "respuesta al correo" and request.inbound_id == inbound.id
    assert request.registered_by == SYSTEM_USER_ID and request.status == "open"
    assert chats(out) == {COM_TG}
    assert labels(out) == ["Aplicar baja", "Registrar consulta o reclamo", "Sin solicitud"]
    assert "Me interesa, hablemos." in texts(out)


def test_vcrm153_botones_y_fecha_limite_15_dias_habiles(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    make_sent(db, lead_id, users["com"], SENT_ID)
    friday = NOW + timedelta(days=2)  # viernes 16/10/2026, 10:00 Bogotá

    out = process(db, make_inbound(1, "Tengo una duda", in_reply_to=SENT_ID, when=friday), friday)

    with db.read() as conn:
        (request,) = repo.titular_requests(conn)
    assert request.received_on == local_date(friday).isoformat() == "2026-10-16"
    # 15 días hábiles desde el siguiente día hábil, saltando el festivo del lunes 2/11.
    assert request.due_on == "2026-11-09"
    callbacks = [cb for o in out for row in o.buttons for _, cb in row]
    assert callbacks == [
        f"v1:rbaja:{request.id}",
        f"v1:rclas:{request.id}",
        f"v1:rsin:{request.id}",
    ]
    assert "09/11/2026" in texts(out)


def test_el_texto_mostrado_es_plano_acotado_y_sin_control(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    make_sent(db, lead_id, users["com"], SENT_ID)
    hostile = "Hola\x1b[31m <b>negrita</b> ‮galimatías\n" + ("x" * 3000)

    out = process(db, make_inbound(1, hostile, in_reply_to=SENT_ID))

    shown = out[0].text
    assert "\x1b" not in shown and "‮" not in shown
    assert len(shown) < 2200 and shown.count("x") <= 1500


# --- VCRM-122: no asociables -----------------------------------------------------------------


def test_vcrm122_no_asociable_al_cto(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = make_lead(db, users["com"])

    out = process(db, make_inbound(1, "¿Quién es usted?", sender="desconocido@otro.test"))

    (inbound,) = inbound_rows(db)
    assert (inbound.classification, inbound.association, inbound.lead_id) == (
        "unassociated",
        "none",
        None,
    )
    assert lead_row(db, lead_id)["state"] == "nurturing"  # ningún lead cambia
    with db.read() as conn:
        (request,) = repo.titular_requests(conn)
        assert repo.lead_consents(conn, lead_id)[-1]["status"] == "authorized"
    assert request.lead_id is None and request.type == "unclassified"
    assert request.inbound_id == inbound.id
    assert chats(out) == {CTO_TG} and "sin lead asociado" in texts(out)
    assert labels(out) == ["Sin solicitud"]


def test_vcrm122_varios_leads_por_huella_no_asociable(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    make_lead(db, users["com"])
    make_lead(db, users["com"], phone_e164="+573009998877")  # mismo correo, otro lead

    out = process(db, make_inbound(1, "Hola"))  # sin hilo

    assert inbound_rows(db)[0].association == "none" and chats(out) == {CTO_TG}


def test_asociacion_por_remitente_con_un_unico_lead(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])

    out = process(db, make_inbound(1, "Hola, ¿siguen con la propuesta?", sender=EMAIL.upper()))

    (inbound,) = inbound_rows(db)
    assert (inbound.association, inbound.lead_id) == ("sender", lead_id)
    assert chats(out) == {COM_TG} and "huella del remitente" in texts(out)


def test_el_hilo_tiene_prioridad_sobre_el_remitente(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    a = make_lead(db, users["com"])
    b = make_lead(db, users["com"], email="b@cliente.test", phone_e164="+573004443322")
    make_sent(db, b, users["com"], SENT_ID)

    process(db, make_inbound(1, "Hola", sender=EMAIL, in_reply_to=SENT_ID))

    assert inbound_rows(db)[0].lead_id == b and a != b


def test_hilo_que_apunta_a_dos_leads_distintos_no_se_asocia(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    a = make_lead(db, users["com"])
    b = make_lead(db, users["com"], email="b@cliente.test", phone_e164="+573004443322")
    make_sent(db, a, users["com"], "<a@kaisen.test>")
    make_sent(db, b, users["com"], "<b@kaisen.test>", step=1)
    msg = make_inbound(1, "Hola", sender="x@y.test", in_reply_to="<a@kaisen.test>")
    ambiguous = InboundMessage(
        **{**msg.__dict__, "references": ("<a@kaisen.test>", "<b@kaisen.test>")}
    )

    process(db, ambiguous)

    assert inbound_rows(db)[0].association == "none"


# --- VCRM-124: cabecera de baja -------------------------------------------------------------


def test_vcrm124_cabecera_aplica_baja_sin_palabra_clave(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    send_id = make_sent(db, lead_id, users["com"], SENT_ID)
    token = make_unsub_token(send_id, KEYS[0])

    out = process(db, make_inbound(1, "", subject=f"BAJA {token}", sender="otro@correo.test"))

    assert lead_row(db, lead_id)["state"] == "opted_out"  # aunque escriba desde otro correo
    (inbound,) = inbound_rows(db)
    assert (inbound.classification, inbound.association) == ("stop_header", "token")
    with db.read() as conn:
        assert repo.lead_consents(conn, lead_id)[-1]["medium"] == "cabecera de baja del correo"
    assert "Baja aplicada" in texts(out)


def test_vcrm124_el_token_firmado_con_una_clave_anterior_sigue_valiendo(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    send_id = make_sent(db, lead_id, users["com"], SENT_ID)
    token = make_unsub_token(send_id, "clave-anterior")
    with db.tx() as tx:
        replies.process_message(
            tx,
            make_inbound(1, "", subject=f"BAJA {token}"),
            NOW,
            default_params(),
            (KEYS[0], "clave-anterior"),
        )
    assert lead_row(db, lead_id)["state"] == "opted_out"


@pytest.mark.parametrize(
    "bad", ["1.000000000000000000000000", "999.abcdefabcdefabcdefabcdef", "no-es-token"]
)
def test_vcrm124_token_invalido_es_no_asociable(
    db: CrmDatabase, users: dict[str, User], bad: str
) -> None:
    lead_id = make_lead(db, users["com"])
    make_sent(db, lead_id, users["com"], SENT_ID)

    # Aunque el remitente SÍ sea el del lead y cite el hilo, un token inválido no aplica nada.
    out = process(db, make_inbound(1, "", subject=f"BAJA {bad}", in_reply_to=SENT_ID))

    assert lead_row(db, lead_id)["state"] == "nurturing"
    (inbound,) = inbound_rows(db)
    assert (inbound.classification, inbound.association, inbound.lead_id) == (
        "unassociated",
        "none",
        None,
    )
    assert chats(out) == {CTO_TG}


def test_vcrm124_token_de_otra_clave_es_no_asociable(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    send_id = make_sent(db, lead_id, users["com"], SENT_ID)
    token = make_unsub_token(send_id, "otra-clave")

    process(db, make_inbound(1, "", subject=f"BAJA {token}"))

    assert lead_row(db, lead_id)["state"] == "nurturing"
    assert inbound_rows(db)[0].classification == "unassociated"


def test_baja_repetida_es_idempotente(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = make_lead(db, users["com"])
    make_sent(db, lead_id, users["com"], SENT_ID)
    process(db, make_inbound(1, "baja", in_reply_to=SENT_ID))
    with db.read() as conn:
        consents = len(repo.lead_consents(conn, lead_id))

    again = process(db, make_inbound(2, "baja otra vez", in_reply_to=SENT_ID))

    assert lead_row(db, lead_id)["state"] == "opted_out"
    with db.read() as conn:
        assert len(repo.lead_consents(conn, lead_id)) == consents  # no duplica revocatorias
    assert "ya estaba en baja" in texts(again)


# --- VCRM-169 / 170: sondeo -----------------------------------------------------------------


def test_vcrm169_mensaje_una_sola_vez(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = make_lead(db, users["com"])
    make_sent(db, lead_id, users["com"], SENT_ID)
    msg = make_inbound(1, "Tengo una duda", in_reply_to=SENT_ID)

    assert process(db, msg)
    assert process(db, msg) == []  # el mismo Message-ID no se procesa de nuevo

    assert len(inbound_rows(db)) == 1
    with db.read() as conn:
        assert len(repo.titular_requests(conn)) == 1


async def poll(db: CrmDatabase, inbox: FakeInbox, now: Any) -> list[Outgoing]:
    return await replies.poll_and_process(db, inbox, now, default_params(), KEYS)


def meta(db: CrmDatabase, key: str) -> str | None:
    with db.read() as conn:
        return repo.get_meta(conn, key)


@pytest.mark.asyncio
async def test_vcrm169_el_sondeo_respeta_el_periodo_y_avanza_el_uid(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    make_sent(db, lead_id, users["com"], SENT_ID)
    inbox = FakeInbox(
        [
            make_inbound(1, "Duda uno", in_reply_to=SENT_ID),
            make_inbound(2, "Duda dos", in_reply_to=SENT_ID),
        ],
        uidvalidity=9,
    )

    out = await poll(db, inbox, NOW)
    assert len(inbound_rows(db)) == 2 and out
    assert (meta(db, "imap_uidvalidity"), meta(db, "imap_last_uid")) == ("9", "2")

    assert await poll(db, inbox, NOW + timedelta(minutes=4)) == []  # aún no toca (5 min)
    assert len(inbox.fetches) == 1
    await poll(db, inbox, NOW + timedelta(minutes=5))
    assert inbox.fetches == [(None, 0), (9, 2)]  # continúa desde el último UID procesado


@pytest.mark.asyncio
async def test_vcrm170_fallo_avisa_una_vez_y_recupera_sin_perder(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id = make_lead(db, users["com"])
    make_sent(db, lead_id, users["com"], SENT_ID)
    inbox = FakeInbox()
    inbox.fail_next(InboxError("imap_error:OSError"))
    inbox.fail_next(InboxError("imap_error:OSError"))

    first = await poll(db, inbox, NOW)  # falla: avisa al CTO
    assert chats(first) == {CTO_TG} and "buzón" in texts(first).lower()
    assert "OSError" in texts(first) and meta(db, "imap_failing") == "1"
    inbox.add(make_inbound(1, "Mientras caído", in_reply_to=SENT_ID))
    assert await poll(db, inbox, NOW + timedelta(minutes=5)) == []  # sigue fallando: sin otro aviso

    await poll(db, inbox, NOW + timedelta(minutes=10))  # se recupera

    assert meta(db, "imap_failing") == "0"
    assert len(inbound_rows(db)) == 1  # el mensaje llegado durante la caída no se perdió
    assert meta(db, "imap_last_uid") == "1"
    # Un fallo nuevo después de recuperarse vuelve a avisar (otro episodio).
    inbox.fail_next(InboxError("imap_error:TimeoutError"))
    again = await poll(db, inbox, NOW + timedelta(minutes=15))
    assert chats(again) == {CTO_TG}


@pytest.mark.asyncio
async def test_vcrm169_si_el_lote_falla_a_medias_no_se_pierde_nada(
    db: CrmDatabase, users: dict[str, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    lead_id = make_lead(db, users["com"])
    make_sent(db, lead_id, users["com"], SENT_ID)
    inbox = FakeInbox(
        [make_inbound(1, "Uno", in_reply_to=SENT_ID), make_inbound(2, "Dos", in_reply_to=SENT_ID)]
    )
    real = replies.process_message
    calls = {"n": 0}

    def flaky(*args: Any, **kwargs: Any) -> list[Outgoing]:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("fallo inesperado")
        return real(*args, **kwargs)

    monkeypatch.setattr(replies, "process_message", flaky)
    with pytest.raises(RuntimeError):
        await poll(db, inbox, NOW)
    assert inbound_rows(db) == [] and meta(db, "imap_last_uid") is None  # todo el lote se deshizo

    monkeypatch.setattr(replies, "process_message", real)
    await poll(db, inbox, NOW + timedelta(minutes=5))
    assert len(inbound_rows(db)) == 2 and meta(db, "imap_last_uid") == "2"


@pytest.mark.asyncio
async def test_sondeo_con_buzon_vacio_no_hace_nada(db: CrmDatabase) -> None:
    inbox = FakeInbox()
    assert await poll(db, inbox, NOW) == []
    assert meta(db, "imap_last_poll_at") == to_iso(NOW)


def test_apply_opt_out_exige_claves_de_huella(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id = make_lead(db, users["com"])
    with db.tx() as tx:
        lead = repo.get_lead(tx, lead_id)
        assert lead is not None
        with pytest.raises(ValueError, match="fingerprint keys"):
            compliance.apply_opt_out(
                tx,
                lead,
                medium="respuesta al correo",
                now=NOW,
                keys=(),
                actor_user_id=SYSTEM_USER_ID,
                audit_actor="system",
            )
    assert lead_row(db, lead_id)["state"] == "nurturing"  # sin claves no se toca nada


# --- VCRM-153: decisiones del usuario sobre una respuesta «por clasificar» ------------------------


def review_case(
    db: CrmDatabase, users: dict[str, User], **lead_fields: Any
) -> tuple[int, int, int]:
    """Lead autorizado en nutrición con una respuesta en revisión: (lead, solicitud, correo)."""
    lead_id = make_lead(db, users["com"], **lead_fields)
    make_sent(db, lead_id, users["com"], SENT_ID)
    process(db, make_inbound(1, "Quiero reclamar por el cobro.", in_reply_to=SENT_ID))
    with db.read() as conn:
        (request,) = repo.titular_requests(conn)
        (inbound,) = repo.list_inbound(conn)
    return lead_id, request.id, inbound.id


def request_row(db: CrmDatabase, request_id: int) -> Any:
    with db.read() as conn:
        req = repo.get_titular_request(conn, request_id)
    assert req is not None
    return req


def inbound_decision(db: CrmDatabase, inbound_id: int) -> Any:
    with db.read() as conn:
        found = repo.get_inbound(conn, inbound_id)
    assert found is not None
    return found


def test_vcrm153_aplicar_baja_desde_la_revision(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id, request_id, inbound_id = review_case(db, users)
    later = NOW + timedelta(hours=2)

    with db.tx() as tx:
        out = replies.apply_review_baja(tx, users["com"], request_id, later, KEYS)

    assert lead_row(db, lead_id)["state"] == "opted_out"
    with db.read() as conn:
        consent = repo.lead_consents(conn, lead_id)[-1]
    assert consent["medium"] == "respuesta al correo confirmada por un usuario"
    assert consent["actor_user_id"] == users["com"].id  # lo decidió una persona, no el sistema
    req = request_row(db, request_id)
    assert (req.status, req.attended_by, req.attended_at) == (
        "attended",
        users["com"].id,
        to_iso(later),
    )
    decision = inbound_decision(db, inbound_id)
    assert (decision.decision, decision.decided_by) == ("confirmed", users["com"].id)
    assert "Baja aplicada" in texts(out)


def test_vcrm153_registrar_consulta_o_reclamo_reclasifica_con_su_plazo(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    _lead, request_id, inbound_id = review_case(db, users)
    options = replies_options(db, users["com"], request_id)
    assert [label for o in options for r in o.buttons for label, _ in r] == ["Consulta", "Reclamo"]

    with db.tx() as tx:
        out = replies.classify_review(
            tx, users["com"], request_id, RequestType.INQUIRY, NOW, default_params()
        )

    req = request_row(db, request_id)
    assert req.type == "inquiry" and req.status == "open"
    assert req.due_on == "2026-10-28"  # 10 días hábiles desde el día hábil siguiente al 14/10
    assert inbound_decision(db, inbound_id).decision == "confirmed"
    assert "consulta" in texts(out).lower() and "28/10/2026" in texts(out)

    other = review_case_second(db, users)
    with db.tx() as tx:
        replies.classify_review(tx, users["com"], other, RequestType.CLAIM, NOW, default_params())
    assert request_row(db, other).due_on == "2026-11-05"  # 15 días hábiles (festivo 2/11)


def replies_options(db: CrmDatabase, actor: User, request_id: int) -> list[Outgoing]:
    with db.tx() as tx:
        return replies.classify_options(tx, actor, request_id, NOW)


def review_case_second(db: CrmDatabase, users: dict[str, User]) -> int:
    lead_id = make_lead(db, users["com"], email="seg@cliente.test", phone_e164="+573006665544")
    make_sent(db, lead_id, users["com"], "<seg@kaisen.test>")
    process(
        db, make_inbound(2, "Otra duda", sender="seg@cliente.test", in_reply_to="<seg@kaisen.test>")
    )
    with db.read() as conn:
        return max(r.id for r in repo.titular_requests(conn))


def test_vcrm153_sin_solicitud_la_cierra(db: CrmDatabase, users: dict[str, User]) -> None:
    lead_id, request_id, inbound_id = review_case(db, users)

    with db.tx() as tx:
        out = replies.close_review(tx, users["com"], request_id, NOW)

    assert request_row(db, request_id).status == "attended"
    assert inbound_decision(db, inbound_id).decision == "rejected"
    assert lead_row(db, lead_id)["state"] == "nurturing"  # no cambia nada del lead
    assert "cerrada" in texts(out).lower()


def test_vcrm153_cada_decision_se_toma_una_sola_vez(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id, request_id, _ = review_case(db, users)
    with db.tx() as tx:
        replies.close_review(tx, users["com"], request_id, NOW)
        again = replies.close_review(tx, users["com"], request_id, NOW)
        baja = replies.apply_review_baja(tx, users["com"], request_id, NOW, KEYS)
        clasif = replies.classify_review(
            tx, users["com"], request_id, RequestType.CLAIM, NOW, default_params()
        )
    for out in (again, baja, clasif):
        assert "ya fue procesada" in texts(out)
    assert lead_row(db, lead_id)["state"] == "nurturing"  # la baja tardía no se aplicó


def test_vcrm153_solo_el_comercial_del_lead_o_el_cto_deciden(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id, request_id, _ = review_case(db, users)
    with db.tx() as tx:
        other = repo.insert_user(
            tx, telegram_id=2100, role=Role.COMMERCIAL, email="o@k.co", now=NOW
        )
        law = repo.insert_user(tx, telegram_id=3000, role=Role.LAWYER, email="l@k.co", now=NOW)
    for actor in (other, law):
        with db.tx() as tx:
            for out in (
                replies.apply_review_baja(tx, actor, request_id, NOW, KEYS),
                replies.close_review(tx, actor, request_id, NOW),
                replies.classify_options(tx, actor, request_id, NOW),
                replies.classify_review(
                    tx, actor, request_id, RequestType.CLAIM, NOW, default_params()
                ),
            ):
                assert "permiso" in texts(out).lower()
    assert (
        request_row(db, request_id).status == "open"
        and lead_row(db, lead_id)["state"] == "nurturing"
    )
    with db.read() as conn:
        assert len([a for a in repo.audit_rows(conn) if a["action"] == "permission_denied"]) == 8
    with db.tx() as tx:  # el CTO siempre puede
        assert "cerrada" in texts(replies.close_review(tx, users["cto"], request_id, NOW)).lower()


def test_vcrm153_una_respuesta_sin_lead_no_admite_baja(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    process(db, make_inbound(1, "¿Quién es?", sender="nadie@otro.test"))
    with db.read() as conn:
        (request,) = repo.titular_requests(conn)
    with db.tx() as tx:
        assert "permiso" in texts(replies.close_review(tx, users["com"], request.id, NOW)).lower()
        baja = replies.apply_review_baja(tx, users["cto"], request.id, NOW, KEYS)
    assert "sin lead" in texts(baja).lower()
    assert request_row(db, request.id).status == "open"
    with db.tx() as tx:
        assert "cerrada" in texts(replies.close_review(tx, users["cto"], request.id, NOW)).lower()


def test_vcrm153_solicitud_inexistente_o_de_otro_tipo(
    db: CrmDatabase, users: dict[str, User]
) -> None:
    lead_id, request_id, _ = review_case(db, users)
    with db.tx() as tx:
        assert "no existe" in texts(replies.close_review(tx, users["com"], 999, NOW))
        assert "no existe" in texts(replies.classify_options(tx, users["com"], 999, NOW))
        manual = repo.insert_titular_request(
            tx,
            lead_id=lead_id,
            kind=RequestType.INQUIRY,
            medium="llamada",
            received_on="2026-10-14",
            due_on="2026-10-28",
            registered_by=users["com"].id,
            now=NOW,
        )
        # Una solicitud registrada a mano no es «por clasificar»: estos botones no le aplican.
        assert "ya fue procesada" in texts(replies.close_review(tx, users["com"], manual, NOW))
