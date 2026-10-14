"""Pruebas TDD de Plantillas de Marca Kaizen (Spec 008 - Frente F5).

Verifica:
(a) Formato estándar de la ficha de lead y mensajes de bot con identidad Kaizen.
(b) Plantillas canónicas de cotización y mensajes de correo y WhatsApp bajo marca.
(c) Flujo en bot: el comercial crea plantillas (/plantilla nueva, /plantillas), pasan por linter
    y quedan pendientes de aprobación del CTO (/aprobarplantilla, /rechazarplantilla).
(d) Precios de cotización extraídos determinísticamente del catálogo (006), nunca manuales.
"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crm_support import FakeClock, FakeTelegram, make_lead
from jerico.crm import repo
from jerico.crm.bot import CrmBot
from jerico.crm.db import CrmDatabase
from jerico.crm.model import LeadState, Role, User
from jerico.crm.ports import Update
from jerico.crm.team import DENIED
from jerico.marketing.bot import register_marketing_commands
from jerico.marketing.linter import LinterMarcaKaizen
from jerico.marketing.plantillas import (
    EstadoPlantilla,
    GestorPlantillasMarca,
    TipoPlantilla,
    formatear_ficha_lead_marca,
    formatear_mensaje_bot_marca,
    renderizar_plantilla_cotizacion,
)
from jerico.schemas.marketing import CanalMarketing, Trato

START = datetime(2026, 10, 14, 10, 0, 0, tzinfo=UTC)
CTO_TG = 1000
COM_TG = 2000


@pytest.fixture
def db(tmp_path: Path) -> Iterator[CrmDatabase]:
    database = CrmDatabase(tmp_path / "crm_plantillas.db")
    yield database
    database.close()


@pytest.fixture
def tg() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(START)


@pytest.fixture
def gestor() -> GestorPlantillasMarca:
    # Retorna un gestor nuevo y limpio con plantillas canónicas precargadas
    return GestorPlantillasMarca()


@pytest.fixture
def bot(
    db: CrmDatabase,
    tg: FakeTelegram,
    clock: FakeClock,
    gestor: GestorPlantillasMarca,
) -> CrmBot:
    b = CrmBot(db, tg, clock.now)
    register_marketing_commands(b, gestor_plantillas=gestor)
    return b


@pytest.fixture
def users(db: CrmDatabase) -> tuple[User, User]:
    with db.tx() as tx:
        cto = repo.insert_user(
            tx, telegram_id=CTO_TG, role=Role.CTO, email="cto@kaizen.com", now=START
        )
        com = repo.insert_user(
            tx, telegram_id=COM_TG, role=Role.COMMERCIAL, email="com@kaizen.com", now=START
        )
    return cto, com


def _msg(update_id: int, user_tg: int, text: str) -> Update:
    return Update(
        update_id=update_id,
        user_id=user_tg,
        chat_id=user_tg,
        chat_type="private",
        text=text,
    )


# ---------------------------------------------------------------------------
# 1. Pruebas de Formato de Marca (Ficha y Mensajes) (a)
# ---------------------------------------------------------------------------


def test_formato_estandar_ficha_lead_marca() -> None:
    """Verifica que la ficha de lead con formato de marca cumple la identidad Kaizen."""
    lead = make_lead(
        id=42,
        assigned_user_id=1,
        state=LeadState.CONTACTED,
        name="Carlos Mendoza",
        phone_e164="+573001234567",
        email="carlos@empresa.com",
        company="Distribuciones del Valle",
        client_type="persona jurídica",
        doc_type="NIT",
        doc_number="900123456-1",
        legal_rep="Carlos Mendoza",
        service="Software operativo",
        agreed_value="Estándar",
        start_term="1 mes",
        auth_status="authorized",
        registered_at=START.isoformat(),
        last_interaction_at=START.isoformat(),
    )
    card = formatear_ficha_lead_marca(lead, commercial="comercial@kaizen.com")

    # Reglas de marca Kaizen
    assert "Kaizen" in card
    assert "Kaisen" not in card
    assert "Kaizen AI" not in card
    assert "📋 FICHA DE PROSPECTO" in card
    assert "Distribuciones del Valle" in card
    assert "Carlos Mendoza" in card
    assert "Método Kaizen" in card
    assert "01 Entender" in card
    assert "02 Diseñar" in card
    assert "03 Construir" in card
    assert "04 Adoptar" in card
    assert "Da el paso. Nosotros respondemos." in card


def test_formato_mensaje_bot_marca() -> None:
    """Verifica la estructura institucional y sobria de los mensajes del bot."""
    msg = formatear_mensaje_bot_marca(
        titulo="Alerta Operativa",
        cuerpo="Se ha recibido una nueva solicitud de diagnóstico.",
        nivel="info",
    )
    assert "Kaizen" in msg
    assert "Alerta Operativa" in msg
    assert "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" in msg


# ---------------------------------------------------------------------------
# 2. Pruebas de Plantillas Canónicas y Linter (b)
# ---------------------------------------------------------------------------


def test_plantillas_canonicas_cumplen_linter(gestor: GestorPlantillasMarca) -> None:
    """Verifica que todas las plantillas canónicas predefinidas pasan el linter de marca."""
    linter = LinterMarcaKaizen()
    plantillas = gestor.listar_plantillas(estado=EstadoPlantilla.APROBADA)
    assert len(plantillas) >= 3

    for p in plantillas:
        res = linter.validar(copy=p.contenido, canal=p.canal, trato=p.trato)
        assert res.valido, f"Plantilla canónica '{p.nombre}' falló el linter: {res.errores}"


# ---------------------------------------------------------------------------
# 3. Pruebas de Cotización Determinista desde Catálogo 006 (d)
# ---------------------------------------------------------------------------


def test_precios_de_plantilla_provienen_de_catalogo_006(gestor: GestorPlantillasMarca) -> None:
    """Verifica que la cotización extrae precios del catálogo (006) y rechaza manuales."""
    plantilla_cot = gestor.obtener_plantilla("PLANT-COTIZACION")
    assert plantilla_cot is not None

    # Cotización del plan estándar
    texto_cotizado = renderizar_plantilla_cotizacion(
        plantilla=plantilla_cot,
        plan_id="estandar",
        cliente_nombre="Dra. Jimena Gómez",
        empresa="Servicios Médicos SAS",
        version="0.1.0",
    )

    assert "Servicios Médicos SAS" in texto_cotizado
    assert "Dra. Jimena Gómez" in texto_cotizado
    # Precios oficiales del catálogo 0.1.0: 3,220,000 COP y 322,000 COP
    assert "3.220.000" in texto_cotizado or "3220000" in texto_cotizado
    assert "322.000" in texto_cotizado or "322000" in texto_cotizado
    assert "COP" in texto_cotizado
    assert "Primero entendemos. Después construimos." in texto_cotizado
    assert "Da el paso. Nosotros respondemos." in texto_cotizado

    # Plan inexistente debe fallar con ValueError
    with pytest.raises(ValueError):
        renderizar_plantilla_cotizacion(
            plantilla=plantilla_cot,
            plan_id="plan_inventado_no_valido",
            cliente_nombre="Test",
            empresa="Test SA",
            version="0.1.0",
        )


# ---------------------------------------------------------------------------
# 4. Flujo de Creación y Gobernanza HITL de Plantillas (c)
# ---------------------------------------------------------------------------


def test_comercial_crea_plantilla_valida_queda_pendiente(gestor: GestorPlantillasMarca) -> None:
    """Un comercial crea una plantilla que cumple el linter y queda pendiente de aprobación."""
    contenido_valido = (
        "Estimado cliente, en Kaizen entendemos cómo trabaja su empresa antes de construir. "
        "Le proponemos una sesión de diagnóstico operativo de 30 minutos sin costo. "
        "Da el paso. Nosotros respondemos."
    )
    nueva = gestor.crear_plantilla(
        nombre="Invitación Diagnóstico Pyme",
        tipo=TipoPlantilla.CORREO_CLIENTE,
        canal=CanalMarketing.CORREO,
        trato=Trato.USTED,
        contenido=contenido_valido,
        creado_por="comercial@kaizen.com",
    )

    assert nueva.estado == EstadoPlantilla.PENDIENTE_APROBACION
    assert nueva.aprobado_por is None
    assert nueva.id.startswith("PLANT-")


def test_comercial_crea_plantilla_invalida_rechazada_por_linter(
    gestor: GestorPlantillasMarca,
) -> None:
    """Una plantilla con palabras prohibidas o nombre incorrecto es rechazada de inmediato."""
    contenido_invalido = (
        "Somos Kaisen AI y ofrecemos una solución disruptiva y revolucionaria "
        "para que recuperes el timón de tu negocio."
    )
    with pytest.raises(ValueError) as exc:
        gestor.crear_plantilla(
            nombre="Campaña Agresiva",
            tipo=TipoPlantilla.CORREO_CLIENTE,
            canal=CanalMarketing.CORREO,
            trato=Trato.USTED,
            contenido=contenido_invalido,
            creado_por="comercial@kaizen.com",
        )
    assert "linter" in str(exc.value).lower()


def test_cto_aprueba_y_rechaza_plantilla(gestor: GestorPlantillasMarca) -> None:
    """Solo el rol CTO puede aprobar o rechazar plantillas."""
    contenido = (
        "Hola, en Kaizen te ayudamos a organizar la operación de tu negocio paso a paso. "
        "Escríbeme para agendar tu diagnóstico. Da el paso. Nosotros respondemos."
    )
    plantilla = gestor.crear_plantilla(
        nombre="WhatsApp Rápido",
        tipo=TipoPlantilla.WHATSAPP_CLIENTE,
        canal=CanalMarketing.WHATSAPP_OFICIAL,
        trato=Trato.TU,
        contenido=contenido,
        creado_por="comercial@kaizen.com",
    )

    # Comercial no puede aprobar
    with pytest.raises(PermissionError):
        gestor.aprobar_plantilla(plantilla.id, usuario_rol="commercial")

    # CTO aprueba
    aprobada = gestor.aprobar_plantilla(plantilla.id, usuario_rol="cto")
    assert aprobada.estado == EstadoPlantilla.APROBADA
    assert aprobada.aprobado_por == "cto"


# ---------------------------------------------------------------------------
# 5. Integración con @Jericoo_bot (Comandos Telegram)
# ---------------------------------------------------------------------------


def test_comandos_bot_plantillas_flujo_completo(
    bot: CrmBot,
    tg: FakeTelegram,
    users: tuple[User, User],
    gestor: GestorPlantillasMarca,
) -> None:
    """Verifica los comandos /plantillas, /plantilla nueva, /aprobarplantilla y rechazo."""
    cto, com = users

    # 1. Comercial consulta /plantillas
    asyncio.run(bot.process_update(_msg(1, com.telegram_id, "/plantillas")))
    assert "Plantillas de Marca Kaizen" in tg.sent[-1].text
    assert "PLANT-COTIZACION" in tg.sent[-1].text

    # 2. Comercial crea una plantilla nueva válida
    cmd_crear = (
        "/plantilla nueva Seguimiento Pyme | correo | usted | "
        "Estimado gerente, en Kaizen entendemos sus procesos antes de implementar software. "
        "Da el paso. Nosotros respondemos."
    )
    asyncio.run(bot.process_update(_msg(2, com.telegram_id, cmd_crear)))
    assert "creada exitosamente" in tg.sent[-1].text.lower()
    assert "pendiente de aprobación" in tg.sent[-1].text.lower()

    # Extraer ID
    id_linea = [line for line in tg.sent[-1].text.splitlines() if "ID:" in line][0]
    plantilla_id = id_linea.split("ID:")[1].strip()

    # 3. Comercial intenta aprobarla (debe ser denegado por rol)
    asyncio.run(bot.process_update(_msg(3, com.telegram_id, f"/aprobarplantilla {plantilla_id}")))
    assert tg.sent[-1].text == DENIED

    # 4. CTO consulta /plantillas y ve la plantilla pendiente
    asyncio.run(bot.process_update(_msg(4, cto.telegram_id, "/plantillas")))
    assert plantilla_id in tg.sent[-1].text
    assert "Pendiente" in tg.sent[-1].text

    # 5. CTO aprueba la plantilla
    asyncio.run(bot.process_update(_msg(5, cto.telegram_id, f"/aprobarplantilla {plantilla_id}")))
    assert "aprobada" in tg.sent[-1].text.lower()
    plantilla_obj = gestor.obtener_plantilla(plantilla_id)
    assert plantilla_obj is not None
    assert plantilla_obj.estado == EstadoPlantilla.APROBADA

    # 6. Comercial crea otra plantilla y CTO la rechaza
    cmd_crear_2 = (
        "/plantilla nueva Rechazo Demo | correo | usted | "
        "Estimado cliente, en Kaizen le presentamos nuestra propuesta formal. "
        "Da el paso. Nosotros respondemos."
    )
    asyncio.run(bot.process_update(_msg(6, com.telegram_id, cmd_crear_2)))
    id_linea_2 = [line for line in tg.sent[-1].text.splitlines() if "ID:" in line][0]
    plantilla_id_2 = id_linea_2.split("ID:")[1].strip()

    asyncio.run(
        bot.process_update(
            _msg(
                7,
                cto.telegram_id,
                f"/rechazarplantilla {plantilla_id_2} No se alinea al trimestre",
            )
        )
    )
    assert "rechazada" in tg.sent[-1].text.lower()
    plantilla_rechazada = gestor.obtener_plantilla(plantilla_id_2)
    assert plantilla_rechazada is not None
    assert plantilla_rechazada.estado == EstadoPlantilla.RECHAZADA
