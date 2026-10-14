"""Pruebas unitarias para el linter de marca de Kaizen (Spec 008, M2)."""

from jerico.marketing.linter import LinterMarcaKaizen
from jerico.schemas.marketing import CanalMarketing, Trato


def test_linter_aprueba_copy_valido_en_usted() -> None:
    linter = LinterMarcaKaizen()
    copy = (
        "Estimado gerente, en Kaizen entendemos primero su operación antes de construir.\n"
        "Da el paso. Nosotros respondemos."
    )
    res = linter.validar(copy=copy, canal=CanalMarketing.CORREO, trato=Trato.USTED)
    assert res.valido is True
    assert len(res.errores) == 0
    assert res.nombre_valido is True
    assert res.tagline_valido is True


def test_linter_aprueba_copy_valido_en_tu() -> None:
    linter = LinterMarcaKaizen()
    copy = (
        "¿Tu operación sigue atrapada en cuadernos y chats?\n"
        "En Kaizen ordenamos tu proceso con el Método Kaizen.\n"
        "Da el paso. Nosotros respondemos."
    )
    res = linter.validar(copy=copy, canal=CanalMarketing.WHATSAPP_OFICIAL, trato=Trato.TU)
    assert res.valido is True
    assert len(res.errores) == 0


def test_linter_rechaza_nombres_prohibidos() -> None:
    linter = LinterMarcaKaizen()

    # Kaisen con S
    res1 = linter.validar(
        "Somos Kaisen y ordenamos tu negocio.",
        CanalMarketing.INSTAGRAM,
        Trato.TU,
    )
    assert res1.valido is False
    assert any("Kaisen" in err.mensaje for err in res1.errores)

    # Kaizen AI
    res2 = linter.validar(
        "En Kaizen AI construimos software.",
        CanalMarketing.CORREO,
        Trato.USTED,
    )
    assert res2.valido is False
    assert any("AI" in err.mensaje for err in res2.errores)

    # Kaizen.ai
    res3 = linter.validar("Visita Kaizen.ai hoy.", CanalMarketing.INSTAGRAM, Trato.TU)
    assert res3.valido is False


def test_linter_detecta_mezcla_de_trato() -> None:
    linter = LinterMarcaKaizen()
    # Mezcla "su operación" (usted) con "escríbeme tu duda" (tú)
    copy = "Entendemos su operación en Kaizen. Escríbeme tu duda al chat."
    res = linter.validar(copy, CanalMarketing.WHATSAPP_OFICIAL, Trato.TU)
    assert res.valido is False
    assert any("mezcla" in err.mensaje.lower() for err in res.errores)


def test_linter_rechaza_palabras_prohibidas() -> None:
    linter = LinterMarcaKaizen()
    copy = "Una solución disruptiva y revolucionaria para la transformación digital."
    res = linter.validar(copy, CanalMarketing.CORREO, Trato.USTED)
    assert res.valido is False
    mensajes = " ".join(err.mensaje for err in res.errores)
    assert "disruptiva" in mensajes
    assert "revolucionaria" in mensajes
    assert "transformación digital" in mensajes


def test_linter_rechaza_tagline_alterado() -> None:
    linter = LinterMarcaKaizen()
    copy = "Den el paso. Nosotros respondemos."
    res = linter.validar(copy, CanalMarketing.INSTAGRAM, Trato.TU)
    assert res.valido is False
    assert any("tagline" in err.mensaje.lower() for err in res.errores)


def test_linter_valida_contraste_tokens() -> None:
    linter = LinterMarcaKaizen()

    # Combinación ilegal: Óxido vivo (#CD7041) sobre Papel (#FFFFFF)
    res_invalido = linter.validar_contraste(color_texto="#CD7041", color_fondo="#FFFFFF")
    assert res_invalido.valido is False
    assert any("contraste" in err.mensaje.lower() for err in res_invalido.errores)

    # Combinación ilegal: Oro (#B8862B) sobre Papel suave (#F8F4ED)
    res_invalido_oro = linter.validar_contraste(color_texto="#B8862B", color_fondo="#F8F4ED")
    assert res_invalido_oro.valido is False

    # Combinación legal: Óxido (#A8481F) sobre Papel (#FFFFFF)
    res_valido = linter.validar_contraste(color_texto="#A8481F", color_fondo="#FFFFFF")
    assert res_valido.valido is True
