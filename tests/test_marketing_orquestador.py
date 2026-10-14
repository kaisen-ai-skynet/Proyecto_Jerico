"""Pruebas unitarias para el orquestador de marketing y flujo HITL (Spec 008, M3-M5)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from jerico.marketing.activos import GestorActivosKaizen
from jerico.marketing.orquestador import OrquestadorMarketing
from jerico.marketing.perfeccionador import PerfeccionadorMarketing
from jerico.schemas.marketing import (
    CanalMarketing,
    ClasificacionCampana,
    EstadoCampana,
    IdeaInput,
    Trato,
)


def test_gestor_activos_resuelve_catalogo_y_logos() -> None:
    gestor = GestorActivosKaizen()
    # Verificar activos técnicos del catálogo Kaizen_Activos
    act_crm = gestor.obtener_activo_tecnico("ACT-CRM-01")
    assert act_crm is not None
    assert "Jerico CRM" in act_crm["nombre"]

    act_prompts = gestor.obtener_activo_tecnico("ACT-IA-03")
    assert act_prompts is not None
    assert "Prompts" in act_prompts["nombre"]

    # Verificar logos
    assert gestor.obtener_ruta_logo("logo_horizontal_noche") is not None
    assert gestor.obtener_ruta_logo("outro_9x16") is not None


def test_perfeccionador_clasifica_y_estructura_campana() -> None:
    perfeccionador = PerfeccionadorMarketing()

    # Idea sobre entender antes de programar -> debe clasificar C1
    idea = IdeaInput(
        id="IDEA-001",
        texto="Muchos negocios operan en cuadernos y desorden. Antes de software debemos entender.",
        autor="cto",
        creado_en=datetime.now(UTC),
    )
    campana = perfeccionador.estructurar_campana(
        idea=idea,
        canal=CanalMarketing.CORREO,
        trato=Trato.USTED,
        nombre="C1 Diagnóstico Operativo",
    )

    assert campana.clasificacion_campana == ClasificacionCampana.C1
    assert campana.canal == CanalMarketing.CORREO
    assert campana.trato == Trato.USTED
    assert "Kaizen" in campana.copy_principal
    assert "Da el paso. Nosotros respondemos." in campana.copy_principal
    assert campana.idempotency_key is not None


def test_perfeccionador_configura_meta_ads_en_paused_sin_gasto() -> None:
    perfeccionador = PerfeccionadorMarketing()
    idea = IdeaInput(
        id="IDEA-002",
        texto="Anuncio para PYMES que buscan pasar del papel al sistema.",
        autor="cto",
    )
    campana = perfeccionador.estructurar_campana(
        idea=idea,
        canal=CanalMarketing.META_ADS,
        trato=Trato.TU,
        nombre="Anuncio Click-to-WhatsApp",
        presupuesto_usd=Decimal("5.00"),
    )

    assert campana.canal == CanalMarketing.META_ADS
    assert campana.meta_ad_config is not None
    assert campana.meta_ad_config.status == "PAUSED"
    assert campana.meta_ad_config.gasto_autorizado_usd == Decimal("0.00")
    assert campana.gasto_autorizado_usd == Decimal("0.00")


def test_orquestador_flujo_hitl_completo_con_aprobacion_cto() -> None:
    orquestador = OrquestadorMarketing(dry_run=True)
    idea = IdeaInput(
        id="IDEA-101",
        texto="Lanzar campaña en WhatsApp oficial a prospectos de prueba.",
        autor="cto",
    )

    # 1. Proponer campaña -> queda EN_REVISION
    campana = orquestador.proponer_campana(
        idea=idea,
        canal=CanalMarketing.WHATSAPP_OFICIAL,
        trato=Trato.TU,
        nombre="WhatsApp Reactivación",
    )
    assert campana.estado == EstadoCampana.EN_REVISION

    # 2. Generar preview para Telegram
    preview = orquestador.generar_preview_telegram(campana.id)
    assert "PROPUESTA DE CAMPAÑA" in preview
    assert "/aprobar" in preview
    assert "/rechazar" in preview

    # 3. No se puede despachar sin aprobación
    with pytest.raises(PermissionError, match="no ha sido aprobada"):
        orquestador.despachar_campana(campana.id)

    # 4. Aprobación por parte de usuario no-CTO debe fallar
    with pytest.raises(PermissionError, match="Solo el rol 'cto' puede aprobar"):
        orquestador.aprobar_campana(campana.id, usuario_rol="comercial")

    # 5. Aprobación por el CTO
    campana_aprobada = orquestador.aprobar_campana(campana.id, usuario_rol="cto")
    assert campana_aprobada.estado == EstadoCampana.APROBADA
    assert campana_aprobada.aprobado_por == "cto"

    # 6. Despacho en DRY_RUN simulado
    resultado = orquestador.despachar_campana(campana.id)
    assert resultado["status"] == "simulado_dry_run"
    assert resultado["canal"] == CanalMarketing.WHATSAPP_OFICIAL.value
    assert orquestador.obtener_campana(campana.id).estado == EstadoCampana.DESPACHADA


def test_orquestador_rechazo_por_cto() -> None:
    orquestador = OrquestadorMarketing()
    idea = IdeaInput(id="IDEA-102", texto="Prueba de rechazo", autor="cto")
    campana = orquestador.proponer_campana(
        idea=idea,
        canal=CanalMarketing.CORREO,
        trato=Trato.USTED,
        nombre="Campaña descartada",
    )

    campana_rechazada = orquestador.rechazar_campana(
        campana.id,
        usuario_rol="cto",
        motivo="Enfoque de mensaje no prioritario para esta semana",
    )
    assert campana_rechazada.estado == EstadoCampana.RECHAZADA

    # Intentar despachar una campaña rechazada debe fallar
    with pytest.raises(PermissionError, match="no ha sido aprobada"):
        orquestador.despachar_campana(campana.id)


def test_orquestador_guardarail_presupuesto_meta_ads() -> None:
    orquestador = OrquestadorMarketing()
    idea = IdeaInput(id="IDEA-103", texto="Anuncio con sobrecosto", autor="cto")
    campana = orquestador.proponer_campana(
        idea=idea,
        canal=CanalMarketing.META_ADS,
        trato=Trato.TU,
        nombre="Anuncio Excedido",
        presupuesto_usd=Decimal("50.00"),  # Supera los 25 USD de Plan Maestro §6
    )

    # Intentar aprobar con presupuesto superior a 25 USD debe ser rechazado
    with pytest.raises(ValueError, match="excede el tope mensual lean"):
        orquestador.aprobar_campana(
            campana.id,
            usuario_rol="cto",
            gasto_autorizado_usd=Decimal("50.00"),
        )

    # Con presupuesto prudente (ej. 5 USD) debe aprobarse
    campana_ok = orquestador.aprobar_campana(
        campana.id,
        usuario_rol="cto",
        gasto_autorizado_usd=Decimal("5.00"),
    )
    assert campana_ok.gasto_autorizado_usd == Decimal("5.00")
    assert campana_ok.meta_ad_config is not None
    assert campana_ok.meta_ad_config.gasto_autorizado_usd == Decimal("5.00")
