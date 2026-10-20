# Jericó

<p align="center">
  <img src="https://raw.githubusercontent.com/kaisen-ai-skynet/Proyecto_Jerico/main/docs/marca/assets/logo/logo_horizontal_noche.png" alt="Jericó logo" width="420" />
</p>

<p align="center">
  <strong>IA para negocio, decisiones y automatización operativa.</strong>
</p>

<p align="center">
  <a href="https://github.com/kaisen-ai-skynet/Proyecto_Jerico">
    <img alt="GitHub Repo" src="https://img.shields.io/badge/GitHub-Repo-181717?logo=github&logoColor=white" />
  </a>
  <a href="#">
    <img alt="Python" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white" />
  </a>
  <a href="#">
    <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white" />
  </a>
  <a href="#">
    <img alt="Docker" src="https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white" />
  </a>
</p>

---

## ¿Qué es Jericó?

Jericó es un proyecto de IA orientado a automatizar procesos reales de negocio y operación, con foco en ventas, CRM, lead qualification, seguimiento comercial, cotización, marketing y coordinación de decisiones.

No es un chatbot genérico. Es una base técnica para construir un asistente inteligente que pueda:

- entender contexto del cliente
- clasificar leads
- tomar decisiones de routing
- preparar propuestas y seguimiento
- automatizar tareas repetitivas
- operar en varios canales con una capa de infraestructura robusta

---

## Problema que resuelve

Muchas empresas tienen datos, oportunidades y procesos repetitivos, pero no cuentan con una capa inteligente que los convierta en decisiones y acciones concretas.

Jericó intenta cerrar ese hueco con una arquitectura modular pensada para:

- gestionar clientes y oportunidades
- orquestar asistencias internas
- automatizar acciones comerciales y operativas
- mantener trazabilidad del proceso
- reducir fricción entre personas, reglas y sistemas

---

## Capacidades principales

### CRM y automatización comercial
- gestión de leads
- flujo de seguimiento y follow-up
- cierre de contratos y documentos
- cadencia comercial
- gestión de contexto por cliente

### Motor de decisiones
- routing inteligente
- evaluación de contexto
- decisiones orientadas a negocio
- control de estados y transiciones

### Marketing y generación de contenido
- plantillas y mensajes de marketing
- validación de campañas
- adaptadores para distintos canales
- generación de contenido orientada a conversión

### Catálogo y cotización
- reglas de precios
- versionado del catálogo
- cotización y validación
- soporte para productos y paquetes

### Gateway y capa operativa
- API y servicios de negocio
- integración con distintos backends y canales
- memoria, contexto y coordinación
- soporte para interfaces de texto y voz

### Infraestructura y despliegue
- Docker / Docker Compose
- scripts de despliegue
- configuración por entorno
- preparación para entornos productivos y VPS

---

## Stack tecnológico

- Python 3.12+
- FastAPI
- Pydantic
- Typer
- Redis
- Docker / Docker Compose
- PostgreSQL (en despliegue/operación)
- OpenAI-compatible integrations
- infraestructura modular para servicios de negocio y automatización

---

## Estructura del repositorio

```text
.
├── src/jerico/                 # Código principal del proyecto
│   ├── crm/                   # CRM, leads, seguimiento, cierre, contratos
│   ├── marketing/             # marketing, campañas, plantillas, validación
│   ├── catalogo/              # precios, cotización y catálogo
│   ├── decision/              # decisiones, routing y lógica operativa
│   ├── gateway/               # plataformas y entrypoints
│   ├── voice/                 # audio y voz
│   ├── web/                   # web / contexto / interfaces
│   ├── tools/                 # herramientas y adaptadores
│   └── ...
├── docs/                      # arquitectura, despliegue y especificaciones
├── specs/                     # especificaciones técnicas y funcionales
├── tests/                     # suite de pruebas
├── deploy/                    # despliegue y soporte operacional
├── scripts/                   # automatizaciones y utilidades
├── schemas/                   # JSON Schemas
├── catalogo/                  # catálogo y precios
├── docker-compose.yml
├── docker-compose.prod.yml
├── pyproject.toml
├── Dockerfile
├── .env.example
├── README.md
└── ...
```

---

## Inicio rápido

### Requisitos

- Python 3.12+
- Docker y Docker Compose
- acceso a un proveedor de IA o gateway compatible

### Instalación

```bash
cp .env.example .env
pip install -e .
```

### Ejecutar la CLI

```bash
python -m jerico ask --verbose "Necesito ayuda con un lead"
```

### Ejecutar tests

```bash
pytest -q
```

### Ejecutar con Docker

```bash
docker compose up
```

---

## Arquitectura

Jericó sigue un enfoque modular con separación clara entre:

- entrada de datos y canales
- coordinación y contexto
- lógica de negocio y toma de decisiones
- almacenamiento y trazabilidad
- infraestructura y despliegue

La idea es que cada capa pueda evolucionar sin romper el sistema completo.

---

## Casos de uso

- automatización de atención comercial
- cualificación de leads
- seguimiento de clientes
- cotización y propuestas
- asistentes para ventas y operación
- orquestación multi-canal
- procesos con decisiones basadas en contexto

---

## Visión del proyecto

Jericó no busca ser solo un asistente conversacional; busca ser una base para sistemas de IA útiles en contexto real de negocio.

El proyecto refleja una construcción orientada a:

- arquitectura real
- modularidad
- escalabilidad
- pruebas
- documentación técnica
- despliegue reproducible
- separación clara de responsabilidades

---

## Documentación

El repositorio incluye documentación técnica y de decisión, entre otras:

- `docs/ARQUITECTURA.md`
- `docs/ESPECIFICACIONES_TECNICAS.md`
- `docs/ESTRUCTURA_Y_RUTAS.md`
- `docs/spec/`
- `specs/`

---

## Estado del proyecto

El proyecto está en evolución y se enfoca en construir una base sólida para automatización inteligente aplicada a negocio y operación.

---

## Contacto

- GitHub: https://github.com/kaisen-ai-skynet
- Perfil de portfolio: [agrega aquí tu LinkedIn / portfolio / correo]

---

## Nota importante sobre licencia

Este repositorio se comparte como proyecto técnico y de portfolio. Si lo vas a publicar más ampliamente con fines profesionales, conviene definir una licencia explícita antes de usarlo como proyecto open source.

---

<p align="center">
  <strong>Jericó</strong><br>
  IA para negocio, decisiones y automatización operativa.
</p>
