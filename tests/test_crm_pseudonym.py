"""Seudonimización antes de enviar a OpenAI (VCRM-A10..A13; Ley 1581)."""

import pytest

from crm_support import make_lead
from jerico.crm.pseudonym import Redactor

LEAD = make_lead(
    name="Ana María Pérez",
    company="Distribuciones Andina SAS",
    legal_rep="Carlos Gómez",
    phone_e164="+573001234567",
    email="ana.perez@andina.co",
    doc_number="1020304050",
)


def test_vcrma10_known_values_become_markers() -> None:
    red = Redactor.for_lead(LEAD)
    out = red.scrub(
        "Ana María Pérez de Distribuciones Andina SAS, rep. Carlos Gómez, "
        "tel +573001234567, ana.perez@andina.co, CC 1020304050"
    )
    for secret in ("Ana", "Pérez", "Andina", "Carlos", "Gómez", "3001234567", "@", "1020304050"):
        assert secret not in out
    assert "[CLIENTE]" in out and "[EMPRESA]" in out and "[REPRESENTANTE]" in out


def test_vcrma10_name_parts_and_case_are_caught() -> None:
    red = Redactor.for_lead(LEAD)
    out = red.scrub("hablé con ana ayer; PEREZ pidió precio. Maria dijo que sí")
    assert "ana" not in out.lower().replace("[cliente]", "")
    assert "perez" not in out.lower()
    assert "maria" not in out.lower()


@pytest.mark.parametrize(
    "raw",
    [
        "llámame al 300 123 4567",
        "cel: 3001234567",
        "+57 (310) 555-12-34",
        "cédula 79123456",
        "escríbeme a otra.persona@gmail.com",
        "mira https://empresa.co/x?id=9",
        "www.empresa.co",
    ],
)
def test_vcrma12_patterns_are_scrubbed_in_free_text(raw: str) -> None:
    out = Redactor.for_lead(make_lead(name=None, email=None, phone_e164=None)).scrub(raw)
    assert not any(ch.isdigit() for ch in out.replace("[", "").replace("]", "")) or "[" in out
    assert "@" not in out and "http" not in out and "www" not in out
    assert "3001234567" not in out.replace(" ", "")
    assert "79123456" not in out


def test_dates_and_small_numbers_survive() -> None:
    out = Redactor.for_lead(make_lead(name=None)).scrub(
        "reunión 13/10/2026, 3 llamadas, 2026-10-13"
    )
    assert "13/10/2026" in out and "2026-10-13" in out and "3 llamadas" in out


def test_vcrma13_restore_puts_values_back_only_locally() -> None:
    red = Redactor.for_lead(LEAD)
    assert red.restore("Hola [CLIENTE], de [EMPRESA]") == (
        "Hola Ana María Pérez, de Distribuciones Andina SAS"
    )
    assert red.restore("sin marcadores") == "sin marcadores"


def test_lead_without_personal_values_is_safe() -> None:
    red = Redactor.for_lead(make_lead(name=None, email=None, phone_e164=None))
    assert red.scrub("texto neutro") == "texto neutro"
    assert red.restore("[CLIENTE]") == "[CLIENTE]"


def test_short_name_parts_are_not_scrubbed_but_full_value_is() -> None:
    red = Redactor.for_lead(make_lead(name="Li Wu"))
    out = red.scrub("Li Wu llamó; el li... de lista")
    assert "Li Wu" not in out
    assert "lista" in out  # no rompe palabras por partes de 2 letras


def test_restore_is_not_fooled_by_user_text_with_markers() -> None:
    red = Redactor.for_lead(LEAD)
    out = red.scrub("el texto trae [CLIENTE] literal")
    assert red.restore(out).count("Ana María Pérez") <= 1
