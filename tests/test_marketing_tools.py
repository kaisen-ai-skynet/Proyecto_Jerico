"""Pruebas unitarias de las herramientas y comandos de bot para marketing (Spec 008, M6).

Cubre:
- Comandos de bot expuestos para @Jericoo_bot: /proponer_campana, /aprobar, /rechazar, /listar.
- Verificación estricta de permisos de rol: solo el rol 'cto' puede aprobar o autorizar presupuesto.
- Herramientas BaseTool registrables en el subsistema de tools de Jericó.
- Parser de texto de comandos de Telegram con respuestas human-readable.
"""

from decimal import Decimal

import pytest

from jerico.marketing.orquestador import OrquestadorMarketing
from jerico.marketing.perfeccionador import PerfeccionadorMarketing
from jerico.schemas.marketing import (
    CanalMarketing,
    EstadoCampana,
    IdeaInput,
    Trato,
)
from jerico.tools import REGISTRY, get_tool
from jerico.tools.marketing import (
    MARKETING_TOOLS,
    comando_aprobar_campana,
    comando_despachar_campana,
    comando_listar_campanas_pendientes,
    comando_proponer_campana,
    comando_rechazar_campana,
    despachar_comando_telegram,
)


@pytest.fixture
def orquestador_marketing() -> OrquestadorMarketing:
    """Fixture para un orquestador limpio en modo DRY_RUN."""
    perfeccionador = PerfeccionadorMarketing()
    return OrquestadorMarketing(perfeccionador=perfeccionador, dry_run=True)


# ---------------------------------------------------------------------------
# 1. Tests de BaseTool y Registry
# ---------------------------------------------------------------------------


def test_marketing_tools_definicion_y_registro() -> None:
    """Verifica que las herramientas de marketing cumplen el contrato BaseTool."""
    nombres_esperados = {
        "marketing_proponer_campana",
        "marketing_aprobar_campana",
        "marketing_rechazar_campana",
        "marketing_listar_pendientes",
        "marketing_despachar_campana",
    }

    assert {tool.name for tool in MARKETING_TOOLS} == nombres_esperados

    for tool in MARKETING_TOOLS:
        assert get_tool(tool.name) is not None
        assert tool.name in REGISTRY

    # Readonly vs Writes
    prop = get_tool("marketing_proponer_campana")
    assert prop is not None and prop.readonly is True

    aprob = get_tool("marketing_aprobar_campana")
    assert aprob is not None and aprob.readonly is False

    rech = get_tool("marketing_rechazar_campana")
    assert rech is not None and rech.readonly is False


# ---------------------------------------------------------------------------
# 2. Tests de Comandos Funcionales
# ---------------------------------------------------------------------------


def test_comando_proponer_campana_genera_preview(
    orquestador_marketing: OrquestadorMarketing,
) -> None:
    """Verifica la proposición de campañas y generación de vista previa."""
    resultado = comando_proponer_campana(
        orquestador=orquestador_marketing,
        usuario_rol="comercial",
        texto_idea="Automatización de contratos con firma digital y alertas por WhatsApp.",
        canal="correo",
        trato="usted",
        nombre="Campaña Contratos 2026",
    )

    assert resultado["ok"] is True
    assert "campana_id" in resultado
    assert "vista_previa" in resultado
    assert "/aprobar" in str(resultado["vista_previa"])

    campana = orquestador_marketing.obtener_campana(str(resultado["campana_id"]))
    assert campana.estado == EstadoCampana.EN_REVISION


def test_comando_aprobar_campana_exige_rol_cto(
    orquestador_marketing: OrquestadorMarketing,
) -> None:
    """Verifica que solo el rol 'cto' puede aprobar campañas (R17)."""
    idea = IdeaInput(
        id="IDEA-20261014-TEST-TOOLS",
        texto="Revisión legal de flujos y contratos.",
        autor="Santiago",
    )
    campana = orquestador_marketing.proponer_campana(
        idea=idea,
        canal=CanalMarketing.CORREO,
        trato=Trato.USTED,
        nombre="Revisión Legal",
    )

    # Intento de aprobación por usuario no CTO debe fallar
    res_no_cto = comando_aprobar_campana(
        orquestador=orquestador_marketing,
        usuario_rol="comercial",
        campana_id=campana.id,
        gasto_usd=Decimal("5.00"),
    )
    assert res_no_cto["ok"] is False
    assert "Solo el rol 'cto'" in str(res_no_cto["error"])

    # Aprobación válida por el CTO
    res_cto = comando_aprobar_campana(
        orquestador=orquestador_marketing,
        usuario_rol="cto",
        campana_id=campana.id,
        gasto_usd=Decimal("5.00"),
    )
    assert res_cto["ok"] is True
    campana_aprobada = orquestador_marketing.obtener_campana(campana.id)
    assert campana_aprobada.estado == EstadoCampana.APROBADA
    assert campana_aprobada.aprobado_por == "cto"
    assert campana_aprobada.gasto_autorizado_usd == Decimal("5.00")


def test_comando_rechazar_campana_exige_rol_cto(
    orquestador_marketing: OrquestadorMarketing,
) -> None:
    """Verifica que el rechazo de campañas exige rol CTO."""
    idea = IdeaInput(
        id="IDEA-20261014-TEST-RECHAZO",
        texto="Idea fuera de foco.",
        autor="Comercial",
    )
    campana = orquestador_marketing.proponer_campana(
        idea=idea,
        canal=CanalMarketing.CORREO,
        trato=Trato.USTED,
        nombre="Campaña Inadecuada",
    )

    # Intento de rechazo por comercial debe fallar
    res_no_cto = comando_rechazar_campana(
        orquestador=orquestador_marketing,
        usuario_rol="comercial",
        campana_id=campana.id,
        motivo="No alineado",
    )
    assert res_no_cto["ok"] is False

    # Rechazo por CTO debe tener éxito
    res_cto = comando_rechazar_campana(
        orquestador=orquestador_marketing,
        usuario_rol="cto",
        campana_id=campana.id,
        motivo="Copy requiere reformulación integral",
    )
    assert res_cto["ok"] is True
    campana_rechazada = orquestador_marketing.obtener_campana(campana.id)
    assert campana_rechazada.estado == EstadoCampana.RECHAZADA


def test_comando_listar_campanas_pendientes(
    orquestador_marketing: OrquestadorMarketing,
) -> None:
    """Verifica listado de campañas en espera de aprobación."""
    res_vacio = comando_listar_campanas_pendientes(orquestador_marketing, usuario_rol="cto")
    assert res_vacio["total"] == 0

    idea = IdeaInput(
        id="IDEA-20261014-TEST-LISTAR",
        texto="Optimización de logística y almacenes.",
        autor="CTO",
    )
    campana = orquestador_marketing.proponer_campana(
        idea=idea,
        canal=CanalMarketing.CORREO,
        trato=Trato.USTED,
        nombre="Logística Kaizen",
    )

    res_con_items = comando_listar_campanas_pendientes(orquestador_marketing, usuario_rol="cto")
    assert res_con_items["total"] == 1
    assert res_con_items["pendientes"][0]["id"] == campana.id


def test_comando_despachar_campana(
    orquestador_marketing: OrquestadorMarketing,
) -> None:
    """Verifica el comando de despacho validando estado previo de aprobación."""
    idea = IdeaInput(
        id="IDEA-20261014-TEST-DESPACHO",
        texto="Lanzamiento de radar de vencimientos.",
        autor="CTO",
    )
    campana = orquestador_marketing.proponer_campana(
        idea=idea,
        canal=CanalMarketing.CORREO,
        trato=Trato.USTED,
        nombre="Radar de Vencimientos",
    )

    # Despachar sin aprobar debe fallar
    res_fallo = comando_despachar_campana(
        orquestador=orquestador_marketing,
        usuario_rol="cto",
        campana_id=campana.id,
    )
    assert res_fallo["ok"] is False

    # Aprobar y luego despachar
    comando_aprobar_campana(
        orquestador=orquestador_marketing,
        usuario_rol="cto",
        campana_id=campana.id,
        gasto_usd=Decimal("0.00"),
    )

    res_exito = comando_despachar_campana(
        orquestador=orquestador_marketing,
        usuario_rol="cto",
        campana_id=campana.id,
        destinatario="director@cliente.com",
    )
    assert res_exito["ok"] is True
    assert res_exito["resultado"]["status"] == "simulado_dry_run"


# ---------------------------------------------------------------------------
# 3. Tests del Parser de Comandos de Telegram
# ---------------------------------------------------------------------------


def test_despachar_comando_telegram_parser(
    orquestador_marketing: OrquestadorMarketing,
) -> None:
    """Verifica la interpretación de comandos textuales tipo Telegram."""
    # 1. Proponer
    msg_prop = despachar_comando_telegram(
        "/proponer_campana Idea para optimizar compras públicas",
        usuario_rol="cto",
        orquestador=orquestador_marketing,
    )
    assert "🟢" in msg_prop or "CAMP-" in msg_prop

    # Extraer id generado
    lineas = msg_prop.splitlines()
    campana_id = ""
    for linea in lineas:
        if "/aprobar " in linea:
            campana_id = linea.split("/aprobar ")[1].strip().split()[0]
            break
    assert campana_id.startswith("CAMP-")

    # 2. Listar
    msg_list = despachar_comando_telegram(
        "/listar_campanas",
        usuario_rol="cto",
        orquestador=orquestador_marketing,
    )
    assert campana_id in msg_list

    # 3. Aprobar
    msg_aprob = despachar_comando_telegram(
        f"/aprobar {campana_id} 5.00",
        usuario_rol="cto",
        orquestador=orquestador_marketing,
    )
    assert "✅" in msg_aprob

    # 4. Despachar
    msg_desp = despachar_comando_telegram(
        f"/despachar {campana_id} contacto@empresa.com",
        usuario_rol="cto",
        orquestador=orquestador_marketing,
    )
    assert "🚀" in msg_desp or "simulado" in msg_desp.lower()

    # 5. Comando desconocido
    msg_desc = despachar_comando_telegram(
        "/comando_inexistente",
        usuario_rol="cto",
        orquestador=orquestador_marketing,
    )
    assert "Comando de marketing no reconocido" in msg_desc
