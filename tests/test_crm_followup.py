import re
from datetime import timedelta
from pathlib import Path

import pytest
from loguru import logger

from f2_support import COM_TG, CTO_TG, KEYS, NOW, make_lead
from jerico.crm import delivery, followup, repo
from jerico.crm.db import CrmDatabase
from jerico.crm.fingerprint import fingerprint
from jerico.crm.followup_text import (
    FollowupTexts,
    auth_request_body,
    footer,
    load_followup_texts,
    render,
)
from jerico.crm.inbound import extract_new_text, has_stop_keyword
from jerico.crm.model import AuthStatus, Cadence, LeadState, ProposalKind, Role, User
from jerico.crm.timeutil import to_iso

REAL_CADENCES_PATH = Path("src/jerico/crm/resources/cadences.toml")
REAL_AVISO_PATH = Path("src/jerico/crm/resources/aviso-privacidad.md")


# --- 1) Carga de TOML y lookup (VCRM-161) --------------------------------------------------


def test_vcrm161_sin_texto_devuelve_none(tmp_path: Path) -> None:
    toml_content = """version = "v1"

[precio]
subject = "Precio o presupuesto"
"1" = "Texto paso 1"
"2" = ""
"3" = "   "
"""
    p = tmp_path / "cadences.toml"
    p.write_text(toml_content, encoding="utf-8")
    loaded = load_followup_texts(p)
    assert loaded is not None
    assert loaded.version == "v1"
    # Motivo ausente
    assert loaded.lookup("inexistente", 1) is None
    assert loaded.subject("inexistente") is None
    # Paso ausente
    assert loaded.lookup("precio", 99) is None
    # Paso vacío o solo espacios cuenta como ausente
    assert loaded.lookup("precio", 2) is None
    assert loaded.lookup("precio", 3) is None
    # Paso con contenido
    assert loaded.lookup("precio", 1) == "Texto paso 1"
    assert loaded.subject("precio") == "Precio o presupuesto"


def test_vcrm161_archivo_inexistente_retorna_none_con_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    no_file = tmp_path / "no_existe.toml"
    sink_messages: list[str] = []
    handler_id = logger.add(sink_messages.append, level="WARNING")
    try:
        loaded = load_followup_texts(no_file)
        assert loaded is None
        assert any("no_existe.toml" in msg for msg in sink_messages)
    finally:
        logger.remove(handler_id)


def test_vcrm161_toml_invalido_retorna_none_sin_filtrar_contenido_en_logs(tmp_path: Path) -> None:
    marcador = "SECRETO_CONFIDENCIAL_12345"
    p = tmp_path / "corrupto.toml"
    p.write_text(f"version = 'v1'\n[invalido\nclave = '{marcador}'", encoding="utf-8")

    sink_messages: list[str] = []
    handler_id = logger.add(sink_messages.append, level="WARNING")
    try:
        loaded = load_followup_texts(p)
        assert loaded is None
        assert any("corrupto.toml" in msg for msg in sink_messages)
        # NINGÚN mensaje de log debe contener el marcador del archivo ni trazas con contenido
        for msg in sink_messages:
            assert marcador not in msg
    finally:
        logger.remove(handler_id)


def test_vcrm161_archivo_sin_version_retorna_none(tmp_path: Path) -> None:
    p = tmp_path / "sin_version.toml"
    p.write_text("[precio]\nsubject = 'Hola'\n'1' = 'Texto'", encoding="utf-8")

    sink_messages: list[str] = []
    handler_id = logger.add(sink_messages.append, level="WARNING")
    try:
        loaded = load_followup_texts(p)
        assert loaded is None
        assert any("sin_version.toml" in msg for msg in sink_messages)
    finally:
        logger.remove(handler_id)


def test_vcrm161_archivo_no_utf8_retorna_none(tmp_path: Path) -> None:
    p = tmp_path / "bad_encoding.toml"
    p.write_bytes(b"version = 'v1'\n[precio]\nsubject = \xff\xfe\n")

    sink_messages: list[str] = []
    handler_id = logger.add(sink_messages.append, level="WARNING")
    try:
        loaded = load_followup_texts(p)
        assert loaded is None
        assert any("bad_encoding.toml" in msg for msg in sink_messages)
    finally:
        logger.remove(handler_id)


# --- 2) Renderizado y saneamiento de nombres ----------------------------------------------


def test_render_sustituye_marcadores_sin_formatear_otras_llaves() -> None:
    template = "Hola {nombre}, soy {comercial}. Esto es {otro_marcador} y {x}."
    result = render(template, name="Ana", commercial="Carlos")
    assert result == "Hola Ana, soy Carlos. Esto es {otro_marcador} y {x}."


def test_render_seguro_con_llaves_en_valores_no_reexpande() -> None:
    template = "Hola {nombre}, firma {comercial}."
    # El nombre contiene marcadores que romperían con str.format o re-sustitución recursiva
    result = render(template, name="{nombre}{x}", commercial="{comercial}")
    assert result == "Hola {nombre}{x}, firma {comercial}."


def test_render_sanea_controles_y_saltos_y_aplica_defaults() -> None:
    # Categoría Cc (\n, \r, \t, etc.) y Cf (caracteres de control de formato)
    name_con_control = "Ana\n\rP\u200bp\t"
    comm_con_control = "Carlos\r\n\x00CTO"
    result = render(
        "Hola {nombre}, soy {comercial}.", name=name_con_control, commercial=comm_con_control
    )
    assert "\n" not in result.split(",")[0]
    assert "\r" not in result
    assert "\x00" not in result
    assert "\u200b" not in result

    # Valores vacíos o solo controles reciben los defaults
    result_default = render("Hola {nombre}, soy {comercial}.", name="   \n  ", commercial="\x00\r")
    assert result_default == "Hola cliente, soy el equipo de Kaisen AI."


# --- 3) Pie comercial (VCRM-069) ----------------------------------------------------------


def test_vcrm069_pie_con_baja_sin_enlaces() -> None:
    f = footer("Carlos Gómez")
    assert "Carlos Gómez" in f
    assert "Responda BAJA para no recibir más mensajes." in f
    assert "http" not in f.lower()
    assert "www" not in f.lower()

    # Cada cosa en su propia línea
    lines = [line.strip() for line in f.splitlines() if line.strip()]
    assert "Carlos Gómez" in lines
    assert "Responda BAJA para no recibir más mensajes." in lines

    # Remitente vacío recibe fallback Kaisen AI
    f_empty = footer("   \n\x00")
    assert "Kaisen AI" in f_empty
    assert "Responda BAJA para no recibir más mensajes." in f_empty


# --- 4) Solicitud de autorización (VCRM-068, 148, 149) ------------------------------------


def test_vcrm148_incluye_aviso_y_encargados() -> None:
    notice = "Aviso legal de prueba..."
    body = auth_request_body(
        notice=notice,
        version="1.0",
        processors=["Telegram", "Google"],
        sender_name="Carlos",
    )
    assert "Carlos" in body
    assert "Utilizamos como encargados del tratamiento: Telegram, Google" in body
    assert "Aviso de privacidad, versión 1.0" in body
    assert "indicando que acepta" in body
    assert "Responda BAJA para no recibir más mensajes." in body
    assert "---" in body
    assert notice in body
    assert footer("Carlos") in body
    assert "http" not in body.lower()
    assert "www" not in body.lower()


def test_vcrm149_sin_aviso_no_se_prepara() -> None:
    with pytest.raises(ValueError):
        auth_request_body(notice="", version="1.0", processors=["Google"], sender_name="Carlos")
    with pytest.raises(ValueError):
        auth_request_body(notice="   ", version="1.0", processors=["Google"], sender_name="Carlos")
    with pytest.raises(ValueError):
        auth_request_body(notice="Aviso", version="", processors=["Google"], sender_name="Carlos")
    with pytest.raises(ValueError):
        auth_request_body(
            notice="Aviso", version="   ", processors=["Google"], sender_name="Carlos"
        )
    with pytest.raises(ValueError):
        auth_request_body(notice="Aviso", version="1.0", processors=[], sender_name="Carlos")
    with pytest.raises(ValueError):
        auth_request_body(
            notice="Aviso", version="1.0", processors=["   ", ""], sender_name="Carlos"
        )


# --- 5) Archivo real cadences.toml --------------------------------------------------------


def test_archivo_real_cadences_toml() -> None:
    assert REAL_CADENCES_PATH.exists()
    texts = load_followup_texts(REAL_CADENCES_PATH)
    assert texts is not None
    assert texts.version == "v1"

    expected_reasons = ("precio", "momento", "proveedor", "no_interesado", "otro")
    assert set(expected_reasons).issubset(set(texts.reasons))

    for reason in expected_reasons:
        subj = texts.subject(reason)
        assert subj is not None and subj.strip()
        for step in (1, 2, 3):
            step_text = texts.lookup(reason, step)
            assert step_text is not None and step_text.strip()
            # Sin URLs ni enlaces
            assert "http" not in step_text.lower()
            assert "www" not in step_text.lower()
            # Únicos marcadores permitidos son {nombre} y {comercial}
            markers = set(re.findall(r"\{([^}]+)\}", step_text))
            assert markers.issubset({"nombre", "comercial"}), (
                f"Marcadores inesperados en {reason}:{step}: {markers}"
            )


# --- 6) Guarda de integración con inbound.py ----------------------------------------------


def test_guarda_footer_no_dispara_baja() -> None:
    f = footer("Kaisen AI")
    new_text = extract_new_text(f)
    assert has_stop_keyword(new_text) is False


def test_guarda_auth_request_aviso_limpio_no_dispara_baja() -> None:
    notice_limpio = "Este es un aviso de privacidad de prueba sin la palabra aislada de stop."
    body = auth_request_body(
        notice=notice_limpio,
        version="1.0",
        processors=["Telegram", "Google"],
        sender_name="Kaisen AI",
    )
    new_text = extract_new_text(body)
    assert has_stop_keyword(new_text) is False


def test_followup_texts_dataclass_congelada() -> None:
    from dataclasses import FrozenInstanceError

    t = FollowupTexts(version="v1", reasons=("precio",), _texts={"precio": {"1": "hola"}})
    assert t.version == "v1"
    assert t.reasons == ("precio",)
    with pytest.raises(FrozenInstanceError):
        t.version = "v2"  # type: ignore[misc]


def test_guarda_auth_request_aviso_real_no_dispara_baja() -> None:
    assert REAL_AVISO_PATH.exists()
    notice_real = REAL_AVISO_PATH.read_text(encoding="utf-8")
    body = auth_request_body(
        notice=notice_real,
        version="1.0",
        processors=["Telegram", "Google"],
        sender_name="Kaisen AI",
    )
    new_text = extract_new_text(body)
    # El aviso real, reproducido sin citar, no puede contar como una baja del cliente.
    assert has_stop_keyword(new_text) is False


# ==============================================================================================
# F2-T13: Generación de propuestas de seguimiento sin envío (VCRM-027, 028, 039, 067, 161)
# ==============================================================================================

SAMPLE_TEXTS = FollowupTexts(
    version="v1",
    reasons=("precio", "momento"),
    _texts={
        "precio": {
            "subject": "Seguimiento sobre precios",
            "1": "Hola {nombre}, te contacto de {comercial} sobre precios.",
            "2": "Hola {nombre}, segundo paso.",
            "3": "Hola {nombre}, tercer paso.",
        },
        "momento": {
            "subject": "Seguimiento sobre el momento",
            "1": "Hola {nombre}, momento oportuno.",
        },
    },
)


def _setup_f2_db(tmp_path: Path, *, active: bool = True) -> tuple[CrmDatabase, User, User]:
    db = CrmDatabase(tmp_path / "f2_followup.db")
    with db.tx() as tx:
        cto = repo.insert_user(tx, telegram_id=CTO_TG, role=Role.CTO, email="cto@k.ai", now=NOW)
        com = repo.insert_user(
            tx, telegram_id=COM_TG, role=Role.COMMERCIAL, email="com@k.ai", now=NOW
        )
        if active:
            repo.set_meta(tx, "f2_activated_at", to_iso(NOW))
    return db, cto, com


def test_vcrm027_genera_propuesta_al_vencer(tmp_path: Path) -> None:
    """VCRM-027: genera propuesta con versión 1, hash, pie legal y boutons ✅/❌."""
    db, cto, com = _setup_f2_db(tmp_path)

    # 1. Caso lead con comercial asignado
    l1 = make_lead(db, com, state=LeadState.NURTURING, name="Ana Pérez", email="ana@cliente.test")
    cad1 = Cadence(
        lead_id=l1,
        reason="precio",
        interval_days=30,
        total_steps=3,
        steps_done=0,
        sent_count=0,
        next_action_at=to_iso(NOW),
        last_sent_at=None,
        status="active",
        started_at=to_iso(NOW),
        updated_at=to_iso(NOW),
    )
    with db.tx() as tx:
        repo.upsert_cadence(tx, cad1)
        out = followup.generate_due(tx, NOW, KEYS, SAMPLE_TEXTS, "Kaisen AI")

        # Verificar propuesta creada
        p1 = repo.get_proposal(tx, 1)
        assert p1 is not None
        assert p1.lead_id == l1
        assert p1.kind == ProposalKind.FOLLOWUP.value
        assert p1.step == 1
        assert p1.approver_user_id == com.id
        assert p1.expires_at == to_iso(NOW + timedelta(hours=48))

        # Versión 1
        v1 = repo.get_proposal_version(tx, p1.id, 1)
        assert v1 is not None
        assert v1.subject == "Seguimiento sobre precios"
        assert "Hola Ana Pérez" in v1.body
        assert "Kaisen AI" in v1.body
        assert "Responda BAJA para no recibir más mensajes." in v1.body
        assert "{nombre}" not in v1.body
        assert "{comercial}" not in v1.body
        assert v1.content_hash == delivery.content_hash(v1.subject, v1.body)
        assert v1.author_user_id == com.id

        # Cadencia queda esperando decisión (next_action_at is None)
        c1_updated = repo.get_cadence(tx, l1)
        assert c1_updated is not None
        assert c1_updated.next_action_at is None

        # Mensajes de presentación hacia el comercial
        assert len(out) >= 1
        assert all(msg.chat_id == com.telegram_id for msg in out)
        assert any(len(msg.buttons) > 0 for msg in out)

    # 2. Caso lead sin comercial asignado: el aprobador es el CTO
    l2 = make_lead(
        db, com, state=LeadState.NURTURING, name="Carlos Gómez", email="carlos@cliente.test"
    )
    cad2 = Cadence(
        lead_id=l2,
        reason="momento",
        interval_days=30,
        total_steps=3,
        steps_done=0,
        sent_count=0,
        next_action_at=to_iso(NOW),
        last_sent_at=None,
        status="active",
        started_at=to_iso(NOW),
        updated_at=to_iso(NOW),
    )
    with db.tx() as tx:
        repo.update_lead(tx, l2, {"assigned_user_id": None}, now=NOW)
        repo.upsert_cadence(tx, cad2)
        out2 = followup.generate_due(tx, NOW, KEYS, SAMPLE_TEXTS, "Kaisen AI")

        p2 = repo.get_proposal(tx, 2)
        assert p2 is not None
        assert p2.approver_user_id == cto.id
        assert any(msg.chat_id == cto.telegram_id for msg in out2)
    db.close()


def test_vcrm028_barrido_repetido_no_duplica(tmp_path: Path) -> None:
    """VCRM-028: barridos repetidos no duplican propuestas."""
    db, cto, com = _setup_f2_db(tmp_path)
    l1 = make_lead(db, com, state=LeadState.NURTURING, email="ana@cliente.test")
    cad = Cadence(
        lead_id=l1,
        reason="precio",
        interval_days=30,
        total_steps=3,
        steps_done=0,
        sent_count=0,
        next_action_at=to_iso(NOW),
        last_sent_at=None,
        status="active",
        started_at=to_iso(NOW),
        updated_at=to_iso(NOW),
    )
    with db.tx() as tx:
        repo.upsert_cadence(tx, cad)
        out1 = followup.generate_due(tx, NOW, KEYS, SAMPLE_TEXTS, "Kaisen AI")
        assert len(out1) > 0

        # Segundo barrido en el mismo instante
        out2 = followup.generate_due(tx, NOW, KEYS, SAMPLE_TEXTS, "Kaisen AI")
        assert out2 == []
        assert repo.get_proposal(tx, 2) is None
    db.close()


def test_vcrm028_reinicio_no_duplica(tmp_path: Path) -> None:
    """VCRM-028: si tras reinicio la cadencia vuelve a tener next_action_at, no duplica."""
    db, cto, com = _setup_f2_db(tmp_path)
    l1 = make_lead(db, com, state=LeadState.NURTURING, email="ana@cliente.test")
    cad = Cadence(
        lead_id=l1,
        reason="precio",
        interval_days=30,
        total_steps=3,
        steps_done=0,
        sent_count=0,
        next_action_at=to_iso(NOW),
        last_sent_at=None,
        status="active",
        started_at=to_iso(NOW),
        updated_at=to_iso(NOW),
    )
    with db.tx() as tx:
        repo.upsert_cadence(tx, cad)
        followup.generate_due(tx, NOW, KEYS, SAMPLE_TEXTS, "Kaisen AI")

        # Simular reinicio que restaura next_action_at <= NOW
        repo.update_cadence(tx, l1, next_action_at=to_iso(NOW))
        out_restart = followup.generate_due(tx, NOW, KEYS, SAMPLE_TEXTS, "Kaisen AI")
        assert out_restart == []
        assert repo.get_proposal(tx, 2) is None
    db.close()


def test_vcrm161_sin_texto_no_avanza_y_avisa_una_vez(tmp_path: Path) -> None:
    """VCRM-161: texts=None o motivo sin ese paso avisa al CTO UNA SOLA VEZ y no avanza."""
    db, cto, com = _setup_f2_db(tmp_path)
    l1 = make_lead(db, com, state=LeadState.NURTURING, email="ana@cliente.test")
    cad = Cadence(
        lead_id=l1,
        reason="inexistente",
        interval_days=30,
        total_steps=3,
        steps_done=0,
        sent_count=0,
        next_action_at=to_iso(NOW),
        last_sent_at=None,
        status="active",
        started_at=to_iso(NOW),
        updated_at=to_iso(NOW),
    )
    with db.tx() as tx:
        repo.upsert_cadence(tx, cad)

        # 1. Llamada con motivo sin texto
        out1 = followup.generate_due(tx, NOW, KEYS, SAMPLE_TEXTS, "Kaisen AI")
        assert len(out1) == 1
        assert out1[0].chat_id == cto.telegram_id
        assert "inexistente" in out1[0].text
        # No se creó propuesta y cadencia no avanzó
        assert repo.get_proposal(tx, 1) is None
        c_status = repo.get_cadence(tx, l1)
        assert c_status is not None and c_status.steps_done == 0

        # Segunda llamada: no duplica aviso al CTO
        out2 = followup.generate_due(tx, NOW, KEYS, SAMPLE_TEXTS, "Kaisen AI")
        assert out2 == []

    # 2. Caso texts=None con otro motivo (crear lead fuera de tx)
    l2 = make_lead(db, com, state=LeadState.NURTURING, email="carlos@cliente.test")
    cad2 = Cadence(
        lead_id=l2,
        reason="precio",
        interval_days=30,
        total_steps=3,
        steps_done=0,
        sent_count=0,
        next_action_at=to_iso(NOW),
        last_sent_at=None,
        status="active",
        started_at=to_iso(NOW),
        updated_at=to_iso(NOW),
    )
    with db.tx() as tx:
        repo.upsert_cadence(tx, cad2)
        out_notext1 = followup.generate_due(tx, NOW, KEYS, None, "Kaisen AI")
        assert len(out_notext1) == 1
        assert out_notext1[0].chat_id == cto.telegram_id
        out_notext2 = followup.generate_due(tx, NOW, KEYS, None, "Kaisen AI")
        assert out_notext2 == []
    db.close()


def test_vcrm039_sin_correo_avisa(tmp_path: Path) -> None:
    """VCRM-039: lead sin correo avisa una sola vez por paso y no crea propuesta."""
    db, cto, com = _setup_f2_db(tmp_path)
    l1 = make_lead(db, com, state=LeadState.NURTURING, email="")
    cad = Cadence(
        lead_id=l1,
        reason="precio",
        interval_days=30,
        total_steps=3,
        steps_done=0,
        sent_count=0,
        next_action_at=to_iso(NOW),
        last_sent_at=None,
        status="active",
        started_at=to_iso(NOW),
        updated_at=to_iso(NOW),
    )
    with db.tx() as tx:
        repo.upsert_cadence(tx, cad)
        out1 = followup.generate_due(tx, NOW, KEYS, SAMPLE_TEXTS, "Kaisen AI")
        assert len(out1) == 1
        assert out1[0].chat_id == com.telegram_id
        assert "correo" in out1[0].text.lower()
        assert repo.get_proposal(tx, 1) is None

        # Segunda llamada: no duplica el aviso
        out2 = followup.generate_due(tx, NOW, KEYS, SAMPLE_TEXTS, "Kaisen AI")
        assert out2 == []
    db.close()


def test_vcrm067_sin_autorizacion_no_genera(tmp_path: Path) -> None:
    """VCRM-067: leads sin autorización vigente o suprimidos no generan propuestas."""
    db, cto, com = _setup_f2_db(tmp_path)
    # Lead con autorización revocada
    l_revoked = make_lead(db, com, state=LeadState.NURTURING, email="rev@cliente.test")
    # Lead suprimido
    l_supp = make_lead(db, com, state=LeadState.NURTURING, email="supp@cliente.test")

    with db.tx() as tx:
        repo.update_lead(tx, l_revoked, {"auth_status": AuthStatus.REVOKED.value}, now=NOW)
        fp = fingerprint(KEYS[0], "supp@cliente.test")
        repo.add_suppression(tx, fp, at=NOW, medium="correo")

        c1 = Cadence(
            lead_id=l_revoked,
            reason="precio",
            interval_days=30,
            total_steps=3,
            steps_done=0,
            sent_count=0,
            next_action_at=to_iso(NOW),
            last_sent_at=None,
            status="active",
            started_at=to_iso(NOW),
            updated_at=to_iso(NOW),
        )
        c2 = Cadence(
            lead_id=l_supp,
            reason="precio",
            interval_days=30,
            total_steps=3,
            steps_done=0,
            sent_count=0,
            next_action_at=to_iso(NOW),
            last_sent_at=None,
            status="active",
            started_at=to_iso(NOW),
            updated_at=to_iso(NOW),
        )
        repo.upsert_cadence(tx, c1)
        repo.upsert_cadence(tx, c2)

        out = followup.generate_due(tx, NOW, KEYS, SAMPLE_TEXTS, "Kaisen AI")
        assert out == []
        assert repo.get_proposal(tx, 1) is None
    db.close()


def test_followup_generate_due_edge_cases(tmp_path: Path) -> None:
    """Cubre F2 inactiva, estado pausado, múltiples cadencias y saneamiento de nombre."""
    # 1. F2 inactiva devuelve []
    db_off, cto, com = _setup_f2_db(tmp_path / "off", active=False)
    l_off = make_lead(db_off, com, state=LeadState.NURTURING, email="off@cliente.test")
    c_off = Cadence(
        lead_id=l_off,
        reason="precio",
        interval_days=30,
        total_steps=3,
        steps_done=0,
        sent_count=0,
        next_action_at=to_iso(NOW),
        last_sent_at=None,
        status="active",
        started_at=to_iso(NOW),
        updated_at=to_iso(NOW),
    )
    with db_off.tx() as tx:
        repo.upsert_cadence(tx, c_off)
        assert followup.generate_due(tx, NOW, KEYS, SAMPLE_TEXTS, "Kaisen AI") == []
    db_off.close()

    # 2. Lead en PAUSED no genera
    db, cto, com = _setup_f2_db(tmp_path / "main", active=True)
    l_paused = make_lead(db, com, state=LeadState.PAUSED, email="p@cliente.test")
    c_paused = Cadence(
        lead_id=l_paused,
        reason="precio",
        interval_days=30,
        total_steps=3,
        steps_done=0,
        sent_count=0,
        next_action_at=to_iso(NOW),
        last_sent_at=None,
        status="active",
        started_at=to_iso(NOW),
        updated_at=to_iso(NOW),
    )
    with db.tx() as tx:
        repo.upsert_cadence(tx, c_paused)
        assert followup.generate_due(tx, NOW, KEYS, SAMPLE_TEXTS, "Kaisen AI") == []

    # 3. Múltiples cadencias: una con fallo (sin email) y otra válida con company
    l_no_mail = make_lead(db, com, state=LeadState.NURTURING, email="")
    l_company = make_lead(
        db,
        com,
        state=LeadState.NURTURING,
        name="",
        company="Empresa XYZ\n{malicioso}",
        email="empresa@cliente.test",
    )
    c_no_mail = Cadence(
        lead_id=l_no_mail,
        reason="precio",
        interval_days=30,
        total_steps=3,
        steps_done=0,
        sent_count=0,
        next_action_at=to_iso(NOW),
        last_sent_at=None,
        status="active",
        started_at=to_iso(NOW),
        updated_at=to_iso(NOW),
    )
    c_company = Cadence(
        lead_id=l_company,
        reason="precio",
        interval_days=30,
        total_steps=3,
        steps_done=0,
        sent_count=0,
        next_action_at=to_iso(NOW),
        last_sent_at=None,
        status="active",
        started_at=to_iso(NOW),
        updated_at=to_iso(NOW),
    )
    with db.tx() as tx:
        repo.upsert_cadence(tx, c_no_mail)
        repo.upsert_cadence(tx, c_company)
        out_batch = followup.generate_due(tx, NOW, KEYS, SAMPLE_TEXTS, "Kaisen AI")
        # Debe contener el aviso de falta de email Y la presentación de la propuesta para l_company
        assert any("correo" in msg.text.lower() for msg in out_batch)
        p_comp = repo.get_proposal(tx, 1)
        assert p_comp is not None and p_comp.lead_id == l_company
        v_comp = repo.get_proposal_version(tx, p_comp.id, 1)
        assert v_comp is not None
        assert "Empresa XYZ{malicioso}" in v_comp.body

    # 4. Sin destinatario comercial ni CTO activo: se salta sin error
    db_no_user, _, com_tmp = _setup_f2_db(tmp_path / "nouser", active=True)
    l_orphan = make_lead(db_no_user, com_tmp, state=LeadState.NURTURING, email="orp@cliente.test")
    c_orphan = Cadence(
        lead_id=l_orphan,
        reason="precio",
        interval_days=30,
        total_steps=3,
        steps_done=0,
        sent_count=0,
        next_action_at=to_iso(NOW),
        last_sent_at=None,
        status="active",
        started_at=to_iso(NOW),
        updated_at=to_iso(NOW),
    )
    with db_no_user.tx() as tx:
        tx.execute("UPDATE crm_users SET active = 0")
        repo.upsert_cadence(tx, c_orphan)
        assert followup.generate_due(tx, NOW, KEYS, SAMPLE_TEXTS, "Kaisen AI") == []
    db_no_user.close()
    db.close()


def test_vcrm022_reanudar_tras_pausar_permite_una_propuesta_nueva_del_mismo_paso(
    tmp_path: Path,
) -> None:
    """Pausar cancela la propuesta abierta SIN avanzar el paso; al reanudar debe poder generarse
    otra para ese mismo paso (la cancelada no puede dejar la cadencia atascada)."""
    db, _cto, com = _setup_f2_db(tmp_path)
    lead_id = make_lead(db, com, state=LeadState.NURTURING, email="ana@cliente.test")
    cad = Cadence(
        lead_id=lead_id,
        reason="precio",
        interval_days=30,
        total_steps=3,
        next_action_at=to_iso(NOW),
        status="active",
        started_at=to_iso(NOW),
        updated_at=to_iso(NOW),
    )
    with db.tx() as tx:
        repo.upsert_cadence(tx, cad)
        assert followup.generate_due(tx, NOW, KEYS, SAMPLE_TEXTS, "Kaisen AI")
        followup.pause(tx, com, lead_id, NOW + timedelta(hours=1))
        followup.resume(tx, com, lead_id, NOW + timedelta(hours=2))
        later = NOW + timedelta(days=31)

        again = followup.generate_due(tx, later, KEYS, SAMPLE_TEXTS, "Kaisen AI")

        rows = tx.execute(
            "SELECT step, status FROM crm_proposals WHERE lead_id = ? ORDER BY id", (lead_id,)
        ).fetchall()
    assert again, "la cadencia reanudada quedó atascada: no generó la propuesta del paso"
    assert [(r["step"], r["status"]) for r in rows] == [(1, "cancelled"), (1, "pending")]
    # Y sigue siendo idempotente: un nuevo barrido no crea una tercera.
    with db.tx() as tx:
        assert followup.generate_due(tx, later, KEYS, SAMPLE_TEXTS, "Kaisen AI") == []
        assert tx.execute("SELECT COUNT(*) FROM crm_proposals").fetchone()[0] == 2
    db.close()
