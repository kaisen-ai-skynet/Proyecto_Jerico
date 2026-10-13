"""Pruebas adversariales de fuga de datos personales del asistente comercial (Ley 1581)."""

import unicodedata

import pytest

from crm_support import make_lead
from jerico.crm.pseudonym import Redactor

LEAD = make_lead(
    name="Ana María Pérez Gómez",
    company="Soluciones Andina S.A.S.",
    legal_rep="Carlos Andrés Ramírez Castro",
    phone_e164="+573001234567",
    email="ana.perez@andina.com.co",
    doc_number="1020304050",
)

SECRETS = (
    "Ana",
    "María",
    "Maria",
    "Pérez",
    "Perez",
    "Gómez",
    "Gomez",
    "Soluciones",
    "Andina",
    "Carlos",
    "Andrés",
    "Andres",
    "Ramírez",
    "Ramirez",
    "Castro",
    "3001234567",
    "+573001234567",
    "ana.perez@andina.com.co",
    "1020304050",
)

LEAK_CASES = [
    # 1. Mayúsculas / minúsculas
    pytest.param("mayus_nombre", "ANA MARÍA PÉREZ GÓMEZ", id="mayus_nombre"),
    pytest.param("minus_nombre", "ana maría pérez gómez", id="minus_nombre"),
    pytest.param("mayus_empresa", "SOLUCIONES ANDINA", id="mayus_empresa"),
    pytest.param("minus_rep", "carlos andrés ramírez castro", id="minus_rep"),
    # 2. Tildes ausentes o añadidas
    pytest.param("sin_tildes_nombre", "Ana Maria Perez Gomez", id="sin_tildes_nombre"),
    pytest.param("sin_tildes_rep", "Carlos Andres Ramirez Castro", id="sin_tildes_rep"),
    pytest.param("tildes_anadidas_empresa", "Ándina", id="tildes_anadidas_empresa"),
    # 3. Espacios dobles
    pytest.param("espacios_dobles_nombre", "Ana  María  Pérez  Gómez", id="espacios_dobles_nombre"),
    pytest.param("espacios_dobles_empresa", "Soluciones  Andina", id="espacios_dobles_empresa"),
    # 4. Nombre en 'Apellido, Nombre'
    pytest.param("apellido_nombre_cliente", "Pérez Gómez, Ana María", id="apellido_nombre_cliente"),
    pytest.param(
        "apellido_nombre_rep",
        "Ramírez Castro, Carlos Andrés",
        id="apellido_nombre_rep",
    ),
    pytest.param("solo_apellidos_cliente", "Pérez Gómez", id="solo_apellidos_cliente"),
    # 5. Teléfono con espacios/guiones/paréntesis/+57/sin prefijo
    pytest.param("tel_espacios", "+57 300 123 4567", id="tel_espacios"),
    pytest.param("tel_guiones", "300-123-4567", id="tel_guiones"),
    pytest.param("tel_parentesis", "(+57) (300) 123-4567", id="tel_parentesis"),
    pytest.param("tel_sin_prefijo", "3001234567", id="tel_sin_prefijo"),
    pytest.param("tel_e164_exacto", "+573001234567", id="tel_e164_exacto"),
    # 6. Correo con mayúsculas o con '+tag'
    pytest.param("correo_mayus", "ANA.PEREZ@ANDINA.COM.CO", id="correo_mayus"),
    pytest.param("correo_plus_tag", "ana.perez+ventas@andina.com.co", id="correo_plus_tag"),
    pytest.param("correo_tag_mayus", "ANA.PEREZ+PROMO@ANDINA.COM.CO", id="correo_tag_mayus"),
    # 7. Documento con puntos (1.020.304.050)
    pytest.param("doc_con_puntos", "1.020.304.050", id="doc_con_puntos"),
    pytest.param("doc_con_espacios", "1 020 304 050", id="doc_con_espacios"),
    pytest.param("doc_prefijo_cc", "CC 1.020.304.050", id="doc_prefijo_cc"),
    # 8. URLs con datos
    pytest.param(
        "url_con_correo_y_tel",
        "https://ejemplo.com/contacto?mail=ana.perez@andina.com.co&t=3001234567",
        id="url_con_correo_y_tel",
    ),
    pytest.param("url_con_doc", "https://portal.co/verificar/1020304050", id="url_con_doc"),
    pytest.param(
        "url_sin_esquema",
        "andina.com.co/perfil/AnaPerez",
        id="url_sin_esquema",
    ),
    # 9. Texto en medio de palabras
    pytest.param(
        "medio_palabra_prefijo",
        "prePérez",
        id="medio_palabra_prefijo",
    ),
    pytest.param(
        "medio_palabra_sufijo",
        "Pérezoso",
        id="medio_palabra_sufijo",
    ),
    pytest.param(
        "medio_palabra_compuesta",
        "empresaAndina",
        id="medio_palabra_compuesta",
    ),
    pytest.param(
        "medio_palabra_rep",
        "superCarlos",
        id="medio_palabra_rep",
    ),
    # 10. Marcadores falsos '[CLIENTE]' en la entrada
    pytest.param(
        "marcador_falso_prefijo",
        "[CLIENTE]Ana María Pérez",
        id="marcador_falso_prefijo",
    ),
    pytest.param(
        "marcador_falso_intercalado",
        "Ana [CLIENTE] María Pérez",
        id="marcador_falso_intercalado",
    ),
    # 11. Unicode (NFD/NFC)
    pytest.param(
        "unicode_nfd_cliente",
        unicodedata.normalize("NFD", "María Pérez"),
        id="unicode_nfd_cliente",
    ),
    pytest.param(
        "unicode_nfd_rep",
        unicodedata.normalize("NFD", "Carlos Andrés Ramírez"),
        id="unicode_nfd_rep",
    ),
    # 12. Saltos de línea
    pytest.param("salto_linea_nombre", "Ana María\nPérez Gómez", id="salto_linea_nombre"),
    pytest.param("salto_linea_crlf", "Ana María\r\nPérez Gómez", id="salto_linea_crlf"),
    pytest.param("salto_linea_doc", "1020\n304050", id="salto_linea_doc"),
]


@pytest.mark.parametrize(("case_id", "input_text"), LEAK_CASES)
def test_scrub_sin_fuga_de_datos_personales(case_id: str, input_text: str) -> None:
    redactor = Redactor.for_lead(LEAD)
    output = redactor.scrub(input_text)
    norm_output = unicodedata.normalize("NFC", output).lower()

    leaked = [
        secret for secret in SECRETS if unicodedata.normalize("NFC", secret).lower() in norm_output
    ]
    assert leaked == [], f"Fuga de datos personales en '{case_id}': {leaked} en '{output}'"
