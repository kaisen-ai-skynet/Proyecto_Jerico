"""Plantillas de Marca Kaizen para atención comercial y cotizaciones (Spec 008, Frente F5).

Aplica las directrices de GUIA_MARCA.md y tokens.json:
- Formato estándar de ficha de lead y mensajes de bot con tono y emojis autorizados.
- Plantillas canónicas de propuesta/cotización, correo formal y WhatsApp.
- Integración determinista con el catálogo de precios (Spec 006) sin valores arbitrarios manuales.
- Gobernanza HITL: creación por el comercial sujeta a validación por linter y aprobación del CTO.
"""

import re
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field

from jerico.crm.handoff import name_or_company
from jerico.crm.model import Lead
from jerico.crm.render import NO_VALUE, auth_label, state_label
from jerico.marketing.linter import TAGLINE_OFICIAL, LinterMarcaKaizen
from jerico.schemas.marketing import CanalMarketing, Trato
from jerico.tools.catalogo import ConsultarCatalogoTool


class TipoPlantilla(StrEnum):
    """Categorías funcionales de plantillas de marca."""

    FICHA_LEAD = "ficha_lead"
    COTIZACION = "cotizacion"
    CORREO_CLIENTE = "correo_cliente"
    WHATSAPP_CLIENTE = "whatsapp_cliente"
    MENSAJE_BOT = "mensaje_bot"


class EstadoPlantilla(StrEnum):
    """Ciclo de vida de aprobación de plantillas (HITL)."""

    PENDIENTE_APROBACION = "pendiente_aprobacion"
    APROBADA = "aprobada"
    RECHAZADA = "rechazada"


class PlantillaMarca(BaseModel):
    """Definición formal de una plantilla de comunicación con clientes."""

    id: str
    nombre: str
    tipo: TipoPlantilla
    canal: CanalMarketing
    trato: Trato
    contenido: str
    variables: list[str] = Field(default_factory=list)
    estado: EstadoPlantilla = EstadoPlantilla.PENDIENTE_APROBACION
    creado_por: str = "comercial"
    aprobado_por: str | None = None
    fecha_creacion: datetime = Field(default_factory=lambda: datetime.now(UTC))
    fecha_aprobacion: datetime | None = None
    motivo_rechazo: str | None = None


# ---------------------------------------------------------------------------
# 1. Formato estándar de la Ficha de Lead y Mensajes del Bot (a)
# ---------------------------------------------------------------------------


def formatear_ficha_lead_marca(
    lead: Lead,
    commercial: str = "",
) -> str:
    """Genera la ficha del lead con la estructura estándar y tono sobrio de Kaizen."""
    nombre = name_or_company(lead) or NO_VALUE
    empresa = lead.company or NO_VALUE
    telefono = lead.phone_e164 or NO_VALUE
    correo = lead.email or NO_VALUE
    estado = state_label(lead.state)
    autorizacion = auth_label(lead.auth_status)
    ejecutivo = commercial or "sin asignar"

    lineas = [
        "📋 FICHA DE PROSPECTO — Kaizen (F1)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"👤 Nombre: {nombre}",
        f"🏢 Empresa: {empresa}",
        f"📞 Teléfono: {telefono}",
        f"✉️ Correo: {correo}",
        f"⚖️ Estado: {estado} | Autorización: {autorizacion}",
        f"💼 Comercial: {ejecutivo}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🧭 Método Kaizen:",
        "  • 01 Entender y depurar (Diagnóstico operativo)",
        "  • 02 Diseñar el sistema a la medida",
        "  • 03 Construir y probar por etapas verificables",
        "  • 04 Adoptar y mejorar con respaldo y soporte real",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        TAGLINE_OFICIAL,
    ]
    return "\n".join(lineas)


def formatear_mensaje_bot_marca(
    titulo: str,
    cuerpo: str,
    nivel: str = "info",
) -> str:
    """Estructura sobria institucional para avisos de @Jericoo_bot."""
    icono = "🔔" if nivel == "info" else ("⚠️" if nivel == "alerta" else "ℹ️")
    return "\n".join(
        [
            f"{icono} [Kaizen] {titulo}",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            cuerpo.strip(),
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ]
    )


# ---------------------------------------------------------------------------
# 2. Plantillas canónicas pre-cargadas (b)
# ---------------------------------------------------------------------------

_COTIZACION_CANONICA = (
    "Estimado(a) {cliente_nombre},\n\n"
    "En Kaizen llevamos a su empresa del papel al futuro. "
    "Primero entendemos. Después construimos.\n\n"
    "Con base en el diagnóstico de su operación, presentamos nuestra propuesta formal para "
    "{empresa}:\n\n"
    "Etapas del Método Kaizen:\n"
    "• 01 Entender y depurar: diagnóstico operativo y levantamiento de flujos reales.\n"
    "• 02 Diseñar el sistema: arquitectura modular sin dependencia de hojas sueltas.\n"
    "• 03 Construir y probar: desarrollo por fases con entregables verificables.\n"
    "• 04 Adoptar y mejorar: acompañamiento continuo con un equipo que responde.\n\n"
    "Propuesta Económica (Catálogo Oficial Kaizen):\n"
    "• Plan seleccionado: {plan_nombre}\n"
    "• Inversión de implementación: {precio_implementacion} {moneda}\n"
    "• Soporte y evolución: {mensualidad_soporte}\n"
    "• Régimen fiscal: {iva_nota}\n"
    "{aviso_borrador}\n\n"
    "Términos de pago: 50% de anticipo al inicio y 50% contra entrega. "
    "Mensualidades mes vencido.\n\n"
    f"{TAGLINE_OFICIAL}"
)

_CORREO_CANONICO = (
    "Estimado(a) {cliente_nombre},\n\n"
    "En Kaizen entendemos cómo trabaja su empresa antes de proponer cualquier solución técnica.\n\n"
    "Si su operación aún depende de hojas de cálculo dispersas, memoria de pocas personas "
    "y mensajes de chat, le proponemos dar el paso hacia un sistema del que respondemos "
    "con nombre propio.\n\n"
    "Le invitamos a una sesión de diagnóstico operativo de 30 minutos, sin costo ni compromiso.\n\n"
    "Primero entendemos. Después construimos.\n"
    f"{TAGLINE_OFICIAL}"
)

_WHATSAPP_CANONICO = (
    "Hola {cliente_nombre}, ¿cómo estás? Te escribo de parte del equipo de Kaizen.\n\n"
    "Sabemos lo desgastante que es coordinar la operación de tu negocio entre chats y notas "
    "sueltas. En Kaizen te ayudamos a centralizar tu información por etapas con un sistema "
    "que tu equipo sí usa.\n\n"
    "¿Tienes 15 minutos esta semana para una llamada corta de diagnóstico?\n\n"
    f"{TAGLINE_OFICIAL}"
)


PLANTILLAS_CANONICAS: list[PlantillaMarca] = [
    PlantillaMarca(
        id="PLANT-COTIZACION",
        nombre="Propuesta de Sistema Operativo Kaizen",
        tipo=TipoPlantilla.COTIZACION,
        canal=CanalMarketing.CORREO,
        trato=Trato.USTED,
        contenido=_COTIZACION_CANONICA,
        variables=[
            "cliente_nombre",
            "empresa",
            "plan_nombre",
            "precio_implementacion",
            "mensualidad_soporte",
            "moneda",
            "iva_nota",
            "aviso_borrador",
        ],
        estado=EstadoPlantilla.APROBADA,
        creado_por="sistema",
        aprobado_por="cto",
    ),
    PlantillaMarca(
        id="PLANT-CORREO",
        nombre="Diagnóstico Operativo Inicial Kaizen",
        tipo=TipoPlantilla.CORREO_CLIENTE,
        canal=CanalMarketing.CORREO,
        trato=Trato.USTED,
        contenido=_CORREO_CANONICO,
        variables=["cliente_nombre"],
        estado=EstadoPlantilla.APROBADA,
        creado_por="sistema",
        aprobado_por="cto",
    ),
    PlantillaMarca(
        id="PLANT-WHATSAPP",
        nombre="Contacto Inicial WhatsApp Kaizen",
        tipo=TipoPlantilla.WHATSAPP_CLIENTE,
        canal=CanalMarketing.WHATSAPP_OFICIAL,
        trato=Trato.TU,
        contenido=_WHATSAPP_CANONICO,
        variables=["cliente_nombre"],
        estado=EstadoPlantilla.APROBADA,
        creado_por="sistema",
        aprobado_por="cto",
    ),
]


# ---------------------------------------------------------------------------
# 3. Integración con Catálogo de Precios (006) (d)
# ---------------------------------------------------------------------------


def _formatear_pesos(valor: int | Decimal) -> str:
    """Formatea valores monetarios en pesos colombianos con separador de miles."""
    return f"${int(valor):,}".replace(",", ".")


def renderizar_plantilla_cotizacion(
    plantilla: PlantillaMarca,
    plan_id: str,
    cliente_nombre: str,
    empresa: str,
    version: str = "",
) -> str:
    """Inyecta los datos de un plan extraído determinísticamente del catálogo en la plantilla."""
    tool = ConsultarCatalogoTool()
    res = tool._execute(plan_id=plan_id, version=version or "0.1.0")
    if not res.get("ok"):
        raise ValueError(f"Error al cotizar plan '{plan_id}' desde el catálogo: {res.get('error')}")

    cotizacion = res.get("cotizacion", {})
    lines = cotizacion.get("lines", [])
    if not lines:
        raise ValueError(
            f"El plan '{plan_id}' no contiene líneas de precio válidas en el catálogo."
        )

    imp_line = lines[0]
    precio_imp = _formatear_pesos(imp_line.get("unit_price", 0))

    soporte_txt = "No incluye soporte mensual"
    if len(lines) > 1:
        sop_line = lines[1]
        soporte_txt = f"{_formatear_pesos(sop_line.get('unit_price', 0))} COP/mes"

    aviso_borrador = ""
    if res.get("aviso"):
        aviso_borrador = f"⚠️ Nota: {res['aviso']}"

    nombre_plan = plan_id.capitalize()
    return plantilla.contenido.format(
        cliente_nombre=cliente_nombre,
        empresa=empresa,
        plan_nombre=nombre_plan,
        precio_implementacion=precio_imp,
        mensualidad_soporte=soporte_txt,
        moneda=cotizacion.get("currency", "COP"),
        iva_nota="IVA (19%) excluido, se suma al facturar",
        aviso_borrador=aviso_borrador,
    )


# ---------------------------------------------------------------------------
# 4. Gestor de Plantillas de Marca (c)
# ---------------------------------------------------------------------------


class GestorPlantillasMarca:
    """Almacena, valida y administra plantillas de marca bajo protocolo HITL."""

    def __init__(self, linter: LinterMarcaKaizen | None = None) -> None:
        self.linter = linter or LinterMarcaKaizen()
        self._plantillas: dict[str, PlantillaMarca] = {}
        for p in PLANTILLAS_CANONICAS:
            self._plantillas[p.id] = p.model_copy()
        self._contador = len(self._plantillas) + 1

    def obtener_plantilla(self, plantilla_id: str) -> PlantillaMarca | None:
        return self._plantillas.get(plantilla_id)

    def listar_plantillas(
        self,
        estado: EstadoPlantilla | None = None,
        usuario_rol: str = "comercial",
    ) -> list[PlantillaMarca]:
        plantillas = list(self._plantillas.values())
        if estado is not None:
            plantillas = [p for p in plantillas if p.estado == estado]
        return plantillas

    def crear_plantilla(
        self,
        nombre: str,
        tipo: TipoPlantilla,
        canal: CanalMarketing,
        trato: Trato,
        contenido: str,
        creado_por: str = "comercial",
    ) -> PlantillaMarca:
        """Crea una nueva plantilla validándola previamente con el linter de marca."""
        # Validación con LinterMarcaKaizen
        res_linter = self.linter.validar(copy=contenido, canal=canal, trato=trato)
        if not res_linter.valido:
            errores_str = "; ".join(e.mensaje for e in res_linter.errores)
            raise ValueError(f"Plantilla rechazada por el linter de marca: {errores_str}")

        pid = f"PLANT-{self._contador:03d}"
        self._contador += 1

        estado = (
            EstadoPlantilla.APROBADA
            if creado_por.lower() == "cto"
            else EstadoPlantilla.PENDIENTE_APROBACION
        )
        aprobado = "cto" if creado_por.lower() == "cto" else None
        fecha_aprob = datetime.now(UTC) if creado_por.lower() == "cto" else None

        # Identificar variables {var}
        variables = list(set(re.findall(r"\{([a-zA-Z0-9_]+)\}", contenido)))

        plantilla = PlantillaMarca(
            id=pid,
            nombre=nombre.strip(),
            tipo=tipo,
            canal=canal,
            trato=trato,
            contenido=contenido.strip(),
            variables=variables,
            estado=estado,
            creado_por=creado_por,
            aprobado_por=aprobado,
            fecha_aprobacion=fecha_aprob,
        )
        self._plantillas[pid] = plantilla
        return plantilla

    def aprobar_plantilla(
        self,
        plantilla_id: str,
        usuario_rol: str,
    ) -> PlantillaMarca:
        """Aprueba formalmente una plantilla. Exclusivo para el rol CTO."""
        if usuario_rol.lower() != "cto":
            raise PermissionError("Solo el rol 'cto' puede aprobar plantillas de marca.")

        plantilla = self.obtener_plantilla(plantilla_id)
        if plantilla is None:
            raise KeyError(f"Plantilla con ID '{plantilla_id}' no encontrada.")

        plantilla.estado = EstadoPlantilla.APROBADA
        plantilla.aprobado_por = "cto"
        plantilla.fecha_aprobacion = datetime.now(UTC)
        return plantilla

    def rechazar_plantilla(
        self,
        plantilla_id: str,
        usuario_rol: str,
        motivo: str = "Rechazada por el CTO",
    ) -> PlantillaMarca:
        """Rechaza una plantilla. Exclusivo para el rol CTO."""
        if usuario_rol.lower() != "cto":
            raise PermissionError("Solo el rol 'cto' puede rechazar plantillas de marca.")

        plantilla = self.obtener_plantilla(plantilla_id)
        if plantilla is None:
            raise KeyError(f"Plantilla con ID '{plantilla_id}' no encontrada.")

        plantilla.estado = EstadoPlantilla.RECHAZADA
        plantilla.motivo_rechazo = motivo
        return plantilla


_GLOBAL_GESTOR_PLANTILLAS: GestorPlantillasMarca | None = None


def obtener_gestor_plantillas() -> GestorPlantillasMarca:
    """Devuelve o inicializa la instancia singleton del gestor de plantillas."""
    global _GLOBAL_GESTOR_PLANTILLAS
    if _GLOBAL_GESTOR_PLANTILLAS is None:
        _GLOBAL_GESTOR_PLANTILLAS = GestorPlantillasMarca()
    return _GLOBAL_GESTOR_PLANTILLAS
