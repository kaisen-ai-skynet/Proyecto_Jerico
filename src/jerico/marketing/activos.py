"""Integración y gestión de activos de marca y técnicos (kz-activos) para Jericó.

Conecta con el catálogo maestro de activos de Kaizen
(~/Kaisen_AI/01_Proyectos/Kaizen_Activos/CATALOGO.md)
y los activos visuales y audiovisuales oficiales (logos, tokens, outro 9:16).
"""

from typing import Any

_LOGO_BASE = "04_Recursos/Fuentes/assets/Marca_Kaizen/logo"

# Catálogo canónico de activos técnicos reutilizables de Kaizen
CATALOGO_ACTIVOS_TECNICOS: dict[str, dict[str, str]] = {
    "ACT-CRM-01": {
        "id": "ACT-CRM-01",
        "nombre": "Jerico CRM Sales Core",
        "categoria": "CRM",
        "stack": "Python 3.12, FastAPI, SQLite WAL / PostgreSQL 16, Pydantic",
        "descripcion": "Gestión de prospectos, cadencias, ciclo de ventas y asistente.",
    },
    "ACT-CRM-04": {
        "id": "ACT-CRM-04",
        "nombre": "Motor Determinista de Oportunidades y Venta Cruzada",
        "categoria": "CRM",
        "stack": "Python 3, SQL relacional",
        "descripcion": "Identificación de necesidades para activación de campañas C1 a C5.",
    },
    "ACT-IA-01": {
        "id": "ACT-IA-01",
        "nombre": "Arquitectura de Agente Telegram e IA Local",
        "categoria": "Automatización IA",
        "stack": "Telegram Bot API, n8n / Python Gateway, Docker",
        "descripcion": "Canal de interacción con el CTO y recepción de aprobación humana.",
    },
    "ACT-IA-03": {
        "id": "ACT-IA-03",
        "nombre": "Suite de Prompts Reutilizables de Negocio e Ingeniería",
        "categoria": "Automatización IA",
        "stack": "Markdown, metaprompting estructurado",
        "descripcion": "Directivas inmutables y perfiles para redacción de marketing.",
    },
    "ACT-CON-01": {
        "id": "ACT-CON-01",
        "nombre": "Esquema de Cifrado PII en Base de Datos (Ley 1581)",
        "categoria": "Conocimiento",
        "stack": "PostgreSQL pgcrypto / SQL",
        "descripcion": "Cifrado de datos personales de prospectos en reposo.",
    },
    "ACT-CON-02": {
        "id": "ACT-CON-02",
        "nombre": "Constitución Innegociable y Protocolo EARS (SDD)",
        "categoria": "Conocimiento",
        "stack": "Markdown, EARS, SDD",
        "descripcion": "Estándares constitucionales para desarrollo agéntico.",
    },
    "ACT-CON-03": {
        "id": "ACT-CON-03",
        "nombre": "Metodología y Plantillas de Intake de Clientes",
        "categoria": "Conocimiento",
        "stack": "Markdown, plantillas de arquitectura",
        "descripcion": "Estructura estandarizada para captura de requisitos y diagnóstico.",
    },
}

TOKENS_COLOR: dict[str, str] = {
    "noche": "#14100C",
    "papel": "#FFFFFF",
    "oxido": "#A8481F",
    "tinta": "#17120D",
    "oxido_vivo": "#CD7041",
    "oro": "#B8862B",
    "papel_suave": "#F8F4ED",
    "papel_calido": "#EEE5D6",
    "noche_suave": "#201A14",
    "tinta_suave": "#62584D",
    "linea": "#E6DED2",
    "verde_azulado": "#2B6E63",
    "pizarra": "#3D5A73",
    "ciruela": "#6B3F5E",
}

LOGOS_OFICIALES: dict[str, str] = {
    "logo_horizontal_noche": f"{_LOGO_BASE}/logo_horizontal_noche.png",
    "logo_horizontal_papel": f"{_LOGO_BASE}/logo_horizontal_papel.png",
    "simbolo_color": f"{_LOGO_BASE}/simbolo_color.png",
    "simbolo_sobre_noche": f"{_LOGO_BASE}/simbolo_sobre_noche.png",
    "simbolo_mono_negro": f"{_LOGO_BASE}/simbolo_mono_negro.png",
    "simbolo_mono_blanco_sobre_noche": f"{_LOGO_BASE}/simbolo_mono_blanco_sobre_noche.png",
    "outro_9x16": f"{_LOGO_BASE}/outro_9x16.png",
}


class GestorActivosKaizen:
    """Gestor de activos de marca y técnicos reutilizables."""

    def obtener_activo_tecnico(self, activo_id: str) -> dict[str, Any] | None:
        """Devuelve los metadatos de un componente del catálogo de activos."""
        return CATALOGO_ACTIVOS_TECNICOS.get(activo_id)

    def obtener_ruta_logo(self, nombre_logo: str) -> str | None:
        """Devuelve la ruta canónica del logotipo o símbolo solicitado."""
        return LOGOS_OFICIALES.get(nombre_logo)

    def obtener_tokens_color(self) -> dict[str, str]:
        """Devuelve los tokens de color oficiales."""
        return dict(TOKENS_COLOR)
