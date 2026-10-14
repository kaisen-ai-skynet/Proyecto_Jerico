"""Pruebas unitarias de los adaptadores de marketing multicanal (Fase 2 - M4).

Cubre:
- Adaptador base y comportamiento DRY_RUN.
- EmailAdapter: tokens de marca, enlace opt-out, dirección fiscal, idempotencia.
- WhatsAppCloudAdapter: Cloud API oficial Meta, plantillas HSM, validación E.164.
- MetaAdsAdapter: estado PAUSED mandatorio, guardarraíl Lean de presupuesto, aprobación CTO.
- SocialOrganicAdapter: copies orgánicos y guiones 9:16 con hook, desarrollo, CTA y outro.
- Integración en OrquestadorMarketing con despacho a través de adaptadores.
"""

from decimal import Decimal

import pytest

from jerico.marketing.adaptadores.base import (
    AdaptadorCanalBase,
    ResultadoDespacho,
)
from jerico.marketing.adaptadores.email_adapter import EmailAdapter
from jerico.marketing.adaptadores.meta_ads_adapter import MetaAdsAdapter
from jerico.marketing.adaptadores.social_organic_adapter import SocialOrganicAdapter
from jerico.marketing.adaptadores.whatsapp_cloud_adapter import WhatsAppCloudAdapter
from jerico.marketing.orquestador import OrquestadorMarketing
from jerico.marketing.perfeccionador import PerfeccionadorMarketing
from jerico.schemas.marketing import (
    CampanaMarketing,
    CanalMarketing,
    ClasificacionCampana,
    EstadoCampana,
    IdeaInput,
    MetaAdConfig,
    Trato,
)


def _crear_campana_prueba(
    canal: CanalMarketing = CanalMarketing.CORREO,
    presupuesto: Decimal = Decimal("0.00"),
    aprobado: bool = True,
) -> CampanaMarketing:
    """Helper para instanciar una campaña válida de prueba."""
    meta_config = (
        MetaAdConfig(
            objetivo="MESSAGES",
            gasto_autorizado_usd=presupuesto,
            status="PAUSED",
            call_to_action="WHATSAPP_MESSAGE",
        )
        if canal == CanalMarketing.META_ADS
        else None
    )

    campana = CampanaMarketing(
        id="CAMP-20261014-TEST",
        nombre="Campaña Test Adaptadores",
        clasificacion_campana=ClasificacionCampana.C1,
        canal=canal,
        trato=Trato.USTED,
        copy_principal=(
            "Optimice sus flujos operativos sin fricción técnica. "
            "Da el paso. Nosotros respondemos."
        ),
        presupuesto_estimado_usd=presupuesto,
        gasto_autorizado_usd=presupuesto if aprobado else Decimal("0.00"),
        estado=EstadoCampana.APROBADA if aprobado else EstadoCampana.EN_REVISION,
        idempotency_key="idemp_test_key_sha256_mock_12345678",
        aprobado_por="cto" if aprobado else None,
        dry_run=True,
        meta_ad_config=meta_config,
    )
    return campana


# ---------------------------------------------------------------------------
# 1. Tests del Adaptador Base
# ---------------------------------------------------------------------------


def test_adaptador_base_no_instanciable_directamente() -> None:
    """Verifica que AdaptadorCanalBase es una clase abstracta."""
    with pytest.raises(TypeError):
        AdaptadorCanalBase()  # type: ignore[abstract]


def test_adaptador_base_calculo_idempotencia() -> None:
    """Verifica el cálculo determinista de llave de idempotencia SHA-256."""
    adaptador = EmailAdapter(dry_run=True)
    key1 = adaptador.calcular_idempotency_key("CAMP-01", "cliente@kaizen.com", "hash123")
    key2 = adaptador.calcular_idempotency_key("CAMP-01", "cliente@kaizen.com", "hash123")
    key3 = adaptador.calcular_idempotency_key("CAMP-01", "otro@kaizen.com", "hash123")

    assert key1 == key2
    assert key1 != key3
    assert len(key1) == 64


# ---------------------------------------------------------------------------
# 2. Tests de EmailAdapter
# ---------------------------------------------------------------------------


def test_email_adapter_render_y_despacho_dry_run() -> None:
    """Verifica renderizado con tokens Kaizen, enlace opt-out y dirección fiscal."""
    adapter = EmailAdapter(dry_run=True)
    campana = _crear_campana_prueba(canal=CanalMarketing.CORREO)

    resultado = adapter.despachar(campana, destinatario="gerencia@cliente.com")

    assert isinstance(resultado, ResultadoDespacho)
    assert resultado.exitoso is True
    assert resultado.dry_run is True
    assert resultado.canal == CanalMarketing.CORREO
    assert resultado.destinatario == "gerencia@cliente.com"

    html = resultado.detalles.get("html_body", "")
    assert "https://kaizen.com.co/baja" in html
    assert "Bogotá, Colombia" in html
    assert "#14100C" in html or "#A8481F" in html
    assert "Da el paso. Nosotros respondemos." in html


def test_email_adapter_rechaza_correo_invalido() -> None:
    """Verifica que EmailAdapter rechaza direcciones sin formato de correo."""
    adapter = EmailAdapter(dry_run=True)
    campana = _crear_campana_prueba(canal=CanalMarketing.CORREO)

    with pytest.raises(ValueError, match="correo electrónico válid"):
        adapter.despachar(campana, destinatario="cliente_invalido_sin_arroba")


# ---------------------------------------------------------------------------
# 3. Tests de WhatsAppCloudAdapter
# ---------------------------------------------------------------------------


def test_whatsapp_cloud_adapter_despacho_dry_run_exitoso() -> None:
    """Verifica el uso estricto de Meta Cloud API con plantillas HSM en formato E.164."""
    adapter = WhatsAppCloudAdapter(dry_run=True)
    campana = _crear_campana_prueba(canal=CanalMarketing.WHATSAPP_OFICIAL)

    resultado = adapter.despachar(campana, destinatario="+573001234567")

    assert resultado.exitoso is True
    assert resultado.dry_run is True
    assert resultado.canal == CanalMarketing.WHATSAPP_OFICIAL
    assert resultado.destinatario == "+573001234567"

    detalles = resultado.detalles
    assert detalles.get("messaging_product") == "whatsapp"
    assert detalles.get("template", {}).get("name") is not None
    assert "wamid." in detalles.get("mock_message_id", "")
    assert "CANCELAR" in detalles.get("opt_out_instruccion", "")


def test_whatsapp_cloud_adapter_rechaza_telefono_invalido() -> None:
    """Verifica rechazo de números que no cumplan el estándar telefónico internacional."""
    adapter = WhatsAppCloudAdapter(dry_run=True)
    campana = _crear_campana_prueba(canal=CanalMarketing.WHATSAPP_OFICIAL)

    with pytest.raises(ValueError, match="número de teléfono E.164 válido"):
        adapter.despachar(campana, destinatario="123")


def test_whatsapp_cloud_adapter_rechaza_librerias_no_oficiales() -> None:
    """Verifica que no se admiten proveedores no oficiales de WhatsApp."""
    with pytest.raises(ValueError, match="Solo se permite Meta Cloud API oficial"):
        WhatsAppCloudAdapter(dry_run=True, api_provider="evolution_api")


# ---------------------------------------------------------------------------
# 4. Tests de MetaAdsAdapter
# ---------------------------------------------------------------------------


def test_meta_ads_adapter_crea_anuncio_en_paused_sin_gasto() -> None:
    """Verifica que toda campaña publicitaria nace en PAUSED y con presupuesto validado."""
    adapter = MetaAdsAdapter(dry_run=True)
    campana = _crear_campana_prueba(
        canal=CanalMarketing.META_ADS,
        presupuesto=Decimal("10.00"),
        aprobado=True,
    )

    resultado = adapter.despachar(campana, destinatario="act_123456789")

    assert resultado.exitoso is True
    assert resultado.dry_run is True
    assert resultado.canal == CanalMarketing.META_ADS

    detalles = resultado.detalles
    assert detalles.get("status") == "PAUSED"
    assert detalles.get("objective") in ["MESSAGES", "OUTCOME_TRAFFIC"]
    assert Decimal(str(detalles.get("daily_budget_usd"))) == Decimal("10.00")
    assert detalles.get("campaign_id", "").startswith("act_mock_")


def test_meta_ads_adapter_rechaza_sin_aprobacion_cto() -> None:
    """Verifica que un anuncio pagado no puede despacharse sin aprobación del CTO."""
    adapter = MetaAdsAdapter(dry_run=True)
    campana = _crear_campana_prueba(
        canal=CanalMarketing.META_ADS,
        presupuesto=Decimal("5.00"),
        aprobado=False,
    )

    with pytest.raises(PermissionError, match="aprobada formalmente por el CTO"):
        adapter.despachar(campana, destinatario="act_123456789")


def test_meta_ads_adapter_rechaza_gasto_superior_a_presupuesto_lean() -> None:
    """Verifica el guardarraíl presupuestal Lean mensual (≤ 25 USD)."""
    adapter = MetaAdsAdapter(dry_run=True)
    campana = _crear_campana_prueba(
        canal=CanalMarketing.META_ADS,
        presupuesto=Decimal("30.00"),
        aprobado=True,
    )

    with pytest.raises(ValueError, match="excede el tope mensual Lean"):
        adapter.despachar(campana, destinatario="act_123456789")


# ---------------------------------------------------------------------------
# 5. Tests de SocialOrganicAdapter
# ---------------------------------------------------------------------------


def test_social_organic_adapter_formatea_copy_instagram() -> None:
    """Verifica formateo con hashtags de marca y menciones sin nombres prohibidos."""
    adapter = SocialOrganicAdapter(dry_run=True)
    campana = _crear_campana_prueba(canal=CanalMarketing.INSTAGRAM)

    resultado = adapter.despachar(campana, destinatario="@kaizen_oficial")

    assert resultado.exitoso is True
    assert resultado.canal == CanalMarketing.INSTAGRAM
    detalles = resultado.detalles
    assert "#Kaizen" in detalles.get("post_text", "")
    assert "#AI" not in detalles.get("post_text", "")
    assert "Kaisen" not in detalles.get("post_text", "")


def test_social_organic_adapter_estructura_guion_9x16() -> None:
    """Verifica estructura técnica de guion 9:16 con hook, desarrollo, CTA y outro."""
    adapter = SocialOrganicAdapter(dry_run=True)
    campana = _crear_campana_prueba(canal=CanalMarketing.INSTAGRAM)
    campana.activo_multimedia_uri = "assets/video_base.mp4"

    guion = adapter.generar_guion_tecnico_9x16(campana)

    assert "hook" in guion
    assert "desarrollo" in guion
    assert "llamado_al_metodo" in guion
    assert guion["outro"]["asset"] == "outro_9x16.png"
    assert "Da el paso. Nosotros respondemos." in guion["outro"]["tagline"]


# ---------------------------------------------------------------------------
# 6. Tests de Integración Orquestador + Adaptadores
# ---------------------------------------------------------------------------


def test_orquestador_despacha_usando_adaptadores() -> None:
    """Verifica que el orquestador delega el despacho al adaptador correspondiente."""
    perfeccionador = PerfeccionadorMarketing()
    orquestador = OrquestadorMarketing(perfeccionador=perfeccionador, dry_run=True)

    idea = IdeaInput(
        id="IDEA-20261014-TEST-ADAPTADORES",
        texto=(
            "Diagnóstico operativo inicial: auditoría de procesos para detectar pérdidas de tiempo."
        ),
        autor="Santiago Gonzalez",
        origen="telegram",
    )

    campana = orquestador.proponer_campana(
        idea=idea,
        canal=CanalMarketing.CORREO,
        trato=Trato.USTED,
        nombre="Diagnóstico Operativo Inicial",
    )
    orquestador.aprobar_campana(campana.id, usuario_rol="cto")

    # Despachar usando el adaptador de correo
    resultado = orquestador.despachar_campana(
        campana.id,
        destinatario="prospecto@empresa.com",
    )

    assert resultado["status"] == "simulado_dry_run"
    assert resultado["canal"] == CanalMarketing.CORREO.value
    assert "detalles_adaptador" in resultado
    assert "html_body" in resultado["detalles_adaptador"]

    # Intentar despachar dos veces debe fallar por idempotencia
    with pytest.raises(ValueError, match="Despacho duplicado bloqueado por idempotencia"):
        orquestador.despachar_campana(campana.id, destinatario="prospecto@empresa.com")
