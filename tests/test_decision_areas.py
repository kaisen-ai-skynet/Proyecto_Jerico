"""Pruebas de T02: Contenido de la política v1 y reglas por área.

Cubre requisitos VJT-003, VJT-007, VJT-009, VJT-010a, VJT-024, VJT-060 a VJT-063.
"""

from jerico.decision.policy import load_policy


def test_catalogo_financiero_nunca_calcula_precios():
    """Ningún tipo de precios/finanzas ofrece la opción de calcularlos (VJT-060)."""
    policy = load_policy()
    tipo_fin = policy.par("ruta_consulta_financiera")

    # Opciones permitidas no pueden incluir 'calcular' o 'calcular_precios'
    for opcion in tipo_fin.opciones:
        assert "calcular" not in opcion.lower()

    # Base debe ser la herramienta determinista
    assert tipo_fin.base == "herramienta"
    # Orden solo permite subir a humano: conceptual < herramienta < humano
    assert tipo_fin.orden_exigencia == ["conceptual", "herramienta", "humano"]


def test_marketing_nunca_publica_ni_gasta():
    """Ningún tipo de marketing ofrece publicar o gastar directamente (VJT-007, VJT-061)."""
    policy = load_policy()
    tipo_mkt = policy.par("riesgo_pieza")

    for opcion in tipo_mkt.opciones:
        assert "publicar" not in opcion.lower()
        assert "gastar" not in opcion.lower()

    # Base es alto (siempre aprobación humana)
    assert tipo_mkt.base == "alto"
    assert tipo_mkt.orden_exigencia == ["bajo", "moderado", "alto"]


def test_contratos_firma_y_bajas_no_figuran_como_consultables():
    """Contratos, firma y bajas no figuran como tipos consultables a Jev (VJT-062)."""
    policy = load_policy()
    prohibidos = ["contrato", "firma", "baja", "supresion", "autorizacion_datos"]
    for tipo_nombre in policy.tipos:
        for p in prohibidos:
            assert p not in tipo_nombre.lower(), f"Prohibido en política: {tipo_nombre}"


def test_seguimiento_lead_es_asesor():
    """El tipo seguimiento_lead es asesor y su salida nunca se aplica (VJT-010a, VJT-063)."""
    policy = load_policy()
    tipo_lead = policy.par("seguimiento_lead")
    assert tipo_lead.asesor is True
    assert tipo_lead.modo_defecto == "apagado"


def test_con_datos_personales_solo_admite_modelos_aptos():
    """con_datos_personales nunca admite modelos no autorizados (VJT-024)."""
    policy = load_policy()
    # Para borrador o resumen_lead con datos personales:
    par_borrador = policy.par("modelo_asistente", "borrador")
    # Los modelos aptos para datos personales en la política actual
    assert "deepseek-chat" not in par_borrador.modelos_aptos_datos_personales
    assert "gpt-6-luna" in par_borrador.modelos_aptos_datos_personales


def test_tabla_tarea_clase_coincide_con_spec():
    """La tabla tarea -> clase de modelo_asistente coincide con la de la spec §4."""
    policy = load_policy()

    t_resumen = policy.par("modelo_asistente", "resumen_lead")
    assert t_resumen.clase == "C"
    assert t_resumen.clase_datos == "con_datos_personales"

    t_cifras = policy.par("modelo_asistente", "cifras_agregadas")
    assert t_cifras.clase == "C"
    assert t_cifras.clase_datos == "con_datos_personales"

    t_borrador = policy.par("modelo_asistente", "borrador")
    assert t_borrador.clase == "B"
    assert t_borrador.clase_datos == "con_datos_personales"

    t_web = policy.par("modelo_asistente", "generar_web_app")
    assert t_web.clase == "C"
    assert t_web.clase_datos == "sin_datos_personales"
