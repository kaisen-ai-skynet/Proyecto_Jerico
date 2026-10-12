"""VCRM-102, 120, 124 (parte pura): texto nuevo, palabra «BAJA» y token de baja (plan-f2 §5.7)."""

import pytest

from jerico.crm.inbound import (
    DISPLAY_LIMIT,
    extract_new_text,
    has_stop_keyword,
    make_unsub_token,
    parse_unsub_subject,
    plain_excerpt,
    unsub_subject,
    verify_unsub_token,
)

KEY = b"clave-de-prueba-no-real"
OLD_KEY = b"clave-anterior-no-real"


@pytest.mark.parametrize(
    "text",
    [
        "baja",
        "Baja.",
        "BAJA",
        "BÁJA",  # con tilde
        "Por favor, dé de baja mi correo",
        "baja!",
        "quiero la baja, gracias",
        "(baja)",
        "NO MÁS MENSAJES\nbaja",
    ],
)
def test_vcrm102_palabra_completa_sin_tildes(text: str) -> None:
    assert has_stop_keyword(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "trabajamos juntos",
        "bajamos el precio",
        "subajar",
        "bajar",
        "bajas ventas",
        "",
        "hola",
        "ba ja",
    ],
)
def test_vcrm102_no_es_palabra_completa(text: str) -> None:
    assert has_stop_keyword(text) is False


def test_vcrm102_falso_positivo_temporada_baja_aceptado() -> None:
    # Riesgo conocido y aceptado por el CTO (spec 4.5): se honra la baja antes que retrasarla.
    assert has_stop_keyword("estamos en temporada baja, escríbame luego") is True


def test_vcrm102_cita_no_cuenta() -> None:
    body = (
        "Gracias, lo reviso esta semana.\n"
        "\n"
        "> Si no desea recibir más mensajes, responda BAJA.\n"
        "> Saludos\n"
    )
    assert extract_new_text(body) == "Gracias, lo reviso esta semana."
    assert has_stop_keyword(extract_new_text(body)) is False


def test_vcrm102_cita_espanol_y_pie_de_correo_original() -> None:
    body = (
        "Me interesa, hablemos.\n"
        "\n"
        "El lun, 12 oct 2026 a las 10:00, Kaisen AI <crm@example.invalid> escribió:\n"
        "Hola Ana, le escribo de nuevo.\n"
        "Responda BAJA para no recibir más mensajes.\n"
    )
    assert extract_new_text(body) == "Me interesa, hablemos."


def test_vcrm102_cita_ingles_con_cabecera_partida() -> None:
    body = (
        "Please remove me. baja\n"
        "\n"
        "On Mon, Oct 12, 2026 at 10:00 AM Kaisen AI\n"
        "<crm@example.invalid> wrote:\n"
        "> Hola\n"
    )
    assert extract_new_text(body) == "Please remove me. baja"
    assert has_stop_keyword(extract_new_text(body)) is True


@pytest.mark.parametrize(
    "marker",
    [
        "-----Original Message-----",
        "-----Mensaje original-----",
        "---------- Forwarded message ---------",
        "---------- Mensaje reenviado ----------",
    ],
)
def test_vcrm102_marcadores_de_original_y_reenvio(marker: str) -> None:
    body = f"Recibido, gracias.\n\n{marker}\nDe: Kaisen AI\nResponda BAJA para no recibir más\n"
    assert extract_new_text(body) == "Recibido, gracias."


def test_vcrm102_bloque_de_cabeceras_de_outlook() -> None:
    body = (
        "Sí, avancemos.\n"
        "\n"
        "De: Kaisen AI <crm@example.invalid>\n"
        "Enviado el: lunes, 12 de octubre de 2026 10:00\n"
        "Para: Ana\n"
        "Asunto: Seguimiento\n"
        "\n"
        "Responda BAJA para no recibir más mensajes.\n"
    )
    assert extract_new_text(body) == "Sí, avancemos."


def test_vcrm102_respuesta_intercalada_conserva_texto_nuevo() -> None:
    body = (
        "> ¿Le interesa la propuesta?\n"
        "Sí, me interesa.\n"
        "> ¿Cuándo hablamos?\n"
        "El jueves, por favor.\n"
    )
    assert extract_new_text(body) == "Sí, me interesa.\nEl jueves, por favor."


def test_vcrm102_pie_reproducido_sin_cita_no_cuenta() -> None:
    # Clientes que contestan sin citar pero dejan nuestro pie en el cuerpo (falso positivo grave).
    body = "Gracias.\nKaisen AI - Responda BAJA para no recibir más mensajes.\n"
    assert extract_new_text(body) == "Gracias."
    assert has_stop_keyword(extract_new_text(body)) is False


def test_vcrm102_pie_no_oculta_una_baja_real() -> None:
    body = "baja por favor\nResponda BAJA para no recibir más mensajes.\n"
    assert has_stop_keyword(extract_new_text(body)) is True


def test_vcrm102_texto_nuevo_vacio_y_saltos_de_linea() -> None:
    assert extract_new_text("") == ""
    assert extract_new_text("> solo cita\n> otra") == ""
    assert extract_new_text("\r\nhola\r\n> x\r\n") == "hola"


def test_vcrm124_token_valido_e_invalido() -> None:
    token = make_unsub_token(1234, KEY)
    assert verify_unsub_token(token, [KEY]) == 1234
    assert verify_unsub_token(token, [b"otra-clave"]) is None
    assert verify_unsub_token(token, []) is None
    # Rotación: el token firmado con una clave anterior sigue siendo válido mientras se conserve.
    old = make_unsub_token(7, OLD_KEY)
    assert verify_unsub_token(old, [KEY, OLD_KEY]) == 7
    # Determinista y solo con caracteres seguros para un asunto de correo.
    assert make_unsub_token(1234, KEY) == token
    assert all(c in "0123456789abcdef." for c in token)
    assert make_unsub_token(1235, KEY) != token
    # Acepta la clave como texto igual que fingerprint.py.
    assert verify_unsub_token(make_unsub_token(5, "clave-texto"), ["clave-texto"]) == 5


def test_vcrm124_token_manipulado() -> None:
    token = make_unsub_token(1234, KEY)
    send_id, mac = token.split(".")
    flipped = mac[:-1] + ("0" if mac[-1] != "0" else "1")
    for tampered in (
        f"1235.{mac}",  # otro envío con la firma de este
        f"{send_id}.{flipped}",  # firma alterada
        f"{send_id}.{mac[:-2]}",  # firma truncada
        f"{send_id}.{mac}ab",  # firma alargada
        f"{send_id}.{mac.upper()}",  # mayúsculas: no canónico
        f"{send_id}",  # sin firma
        f".{mac}",  # sin envío
        f"-1.{mac}",
        f"0{send_id}.{mac}",  # ceros a la izquierda: no canónico
        f"{send_id}.{mac}.extra",
        f"{send_id} .{mac}",
        "",
        "x" * 500,
    ):
        assert verify_unsub_token(tampered, [KEY]) is None, tampered


def test_vcrm124_asunto_de_baja() -> None:
    token = make_unsub_token(42, KEY)
    assert unsub_subject(token) == f"BAJA {token}"
    assert parse_unsub_subject(f"BAJA {token}") == token
    assert parse_unsub_subject(f"  baja   {token}  ") == token
    assert parse_unsub_subject("BAJA") is None
    assert (
        parse_unsub_subject(f"Re: BAJA {token}") is None
    )  # solo el asunto generado por la cabecera
    assert parse_unsub_subject(f"BAJA {token} más cosas") is None
    assert parse_unsub_subject("") is None


def test_vcrm102_extracto_texto_plano_truncado_sin_control() -> None:
    assert plain_excerpt("hola\x00 mundo\x1b[31m\x07") == "hola mundo[31m"
    assert plain_excerpt("a\u202eb\u200bc") == "abc"  # sin control de dirección ni ancho cero
    assert plain_excerpt("línea 1\nlínea 2\tcon tab") == "línea 1\nlínea 2\tcon tab"
    long = "a" * (DISPLAY_LIMIT + 50)
    out = plain_excerpt(long)
    assert len(out) == DISPLAY_LIMIT
    assert out.endswith("…")
    assert plain_excerpt("a" * DISPLAY_LIMIT) == "a" * DISPLAY_LIMIT


@pytest.mark.parametrize("bad", [-1, True, "7", 1.5])
def test_vcrm124_make_token_rechaza_id_invalido(bad: object) -> None:
    with pytest.raises(ValueError, match="send_id"):
        make_unsub_token(bad, KEY)  # type: ignore[arg-type]
