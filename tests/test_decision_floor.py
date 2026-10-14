"""Pruebas de T04: Conjunto permitido y piso por clase (VJT-001 a 008, 010a, 022, 023, 024, 037)."""

import pytest

from jerico.decision.floor import allowed_options, apply_floor, mas_restrictiva
from jerico.decision.policy import PolicyKind, load_policy
from jerico.decision.state import DataClass


@pytest.fixture
def policy():
    return load_policy()


def test_mas_restrictiva_jerarquia():
    """Entre dos clases de datos gana la más restrictiva (VJT-022)."""
    assert mas_restrictiva(DataClass.SIN_DATOS_PERSONALES, DataClass.CON_DATOS_PERSONALES) == (
        DataClass.CON_DATOS_PERSONALES
    )
    assert (
        mas_restrictiva(DataClass.SEUDONIMIZADO_VERIFICADO, DataClass.SIN_DATOS_PERSONALES)
        == DataClass.SEUDONIMIZADO_VERIFICADO
    )
    assert (
        mas_restrictiva(DataClass.SEUDONIMIZADO_VERIFICADO, DataClass.CON_DATOS_PERSONALES)
        == DataClass.CON_DATOS_PERSONALES
    )


def test_contexto_sin_marca_sin_texto_libre_es_con_datos_personales():
    """Un contexto sin marca explícita se trata como con_datos_personales (VJT-023)."""

    class ContextoSinMarca:
        clase_datos = DataClass.SEUDONIMIZADO_VERIFICADO
        sin_texto_libre = False

    ctx = ContextoSinMarca()
    spec = PolicyKind(
        kind="test",
        clase="C",
        base="m1",
        opciones=["m1", "m2"],
        clase_datos=DataClass.SEUDONIMIZADO_VERIFICADO,
    )
    dc = mas_restrictiva(spec.clase_datos, ctx)
    assert dc == DataClass.CON_DATOS_PERSONALES


def test_con_datos_personales_nunca_admite_deepseek(policy):
    """allowed_options con con_datos_personales nunca incluye deepseek-chat (VJT-024)."""
    spec = policy.par("modelo_asistente", "borrador")
    allowed = allowed_options(spec, data_class=DataClass.CON_DATOS_PERSONALES)
    assert "deepseek-chat" not in allowed
    assert "gpt-6-luna" in allowed


def test_allowed_options_con_una_sola_opcion(policy):
    """Para tareas actuales con datos personales hay solo una opción permitida (VJT-008)."""
    spec = policy.par("modelo_asistente", "resumen_lead")
    allowed = allowed_options(spec, data_class=DataClass.CON_DATOS_PERSONALES)
    assert allowed == ["gpt-6-luna"]


def test_apply_floor_clase_a_siempre_base():
    """Clase A siempre devuelve la base, sin importar qué sugiera Jev (VJT-003)."""
    opcion, motivo = apply_floor(
        clase="A",
        orden=None,
        base="mantener_orden",
        jev_option="contactar_hoy",
        allowed=["mantener_orden", "contactar_hoy"],
    )
    assert opcion == "mantener_orden"
    assert "clase_a" in motivo


def test_apply_floor_fuera_de_permitidas():
    """Si Jev devuelve una opción fuera de permitidas, aplica la base (VJT-002)."""
    opcion, motivo = apply_floor(
        clase="C",
        orden=None,
        base="gpt-6-luna",
        jev_option="modelo_prohibido",
        allowed=["gpt-6-luna"],
    )
    assert opcion == "gpt-6-luna"
    assert motivo == "fuera_de_permitidas"


def test_apply_floor_clase_b_solo_sube():
    """Clase B solo permite opciones iguales o más exigentes que la base (VJT-004)."""
    orden = ["conceptual", "herramienta", "humano"]
    base = "herramienta"
    allowed = ["conceptual", "herramienta", "humano"]

    # Intentar bajar a 'conceptual' debe rebotar a 'herramienta'
    opcion, motivo = apply_floor("B", orden, base, "conceptual", allowed)
    assert opcion == "herramienta"
    assert "piso" in motivo

    # Mantener base
    opcion, motivo = apply_floor("B", orden, base, "herramienta", allowed)
    assert opcion == "herramienta"

    # Subir a 'humano' sí se permite
    opcion, motivo = apply_floor("B", orden, base, "humano", allowed)
    assert opcion == "humano"
    assert "piso_cumplido" in motivo


def test_apply_floor_clase_c_enrutado():
    """Clase C aplica la opción de Jev si está permitida (VJT-005)."""
    allowed = ["gemini-3.8-flash", "gpt-6-luna"]
    base = "gpt-6-luna"

    opcion, motivo = apply_floor("C", None, base, "gemini-3.8-flash", allowed)
    assert opcion == "gemini-3.8-flash"
    assert "enrutado_valido" in motivo


def test_apply_floor_sin_orden_o_clase_desconocida():
    """Valida comportamiento de apply_floor ante orden incompleto o clase no estándar."""
    # Clase B sin orden -> devuelve base
    opcion, motivo = apply_floor("B", None, "base1", "op2", ["base1", "op2"])
    assert opcion == "base1"
    assert motivo == "sin_orden"

    # Clase desconocida -> devuelve base
    opcion, motivo = apply_floor("X", None, "base1", "op2", ["base1", "op2"])
    assert opcion == "base1"
    assert motivo == "clase_desconocida"


def test_allowed_options_fallback_base():
    """allowed_options devuelve la base si las opciones quedan vacías."""
    spec = PolicyKind(
        kind="test",
        clase="C",
        base="modelo_base",
        opciones=["modelo_base", "deepseek-chat"],
        modelos_aptos_datos_personales=["modelo_base"],
        clase_datos=DataClass.CON_DATOS_PERSONALES,
    )
    res = allowed_options(spec, data_class="con_datos_personales")
    assert res == ["modelo_base"]
