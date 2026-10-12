import re
from pathlib import Path

import pytest
from loguru import logger

from jerico.crm.followup_text import (
    FollowupTexts,
    auth_request_body,
    footer,
    load_followup_texts,
    render,
)
from jerico.crm.inbound import extract_new_text, has_stop_keyword

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
