---
tipo: proyecto
estado: en planeacion
creado: "20/09/2026 13:37"
modificado: "20/09/2026 15:25"
tags:
  - kaisen
  - ia
  - asistente
  - jerico
  - core
  - ai-os
---

# 🤖 Proyecto: Jericó (AI-OS y Secretaria Ejecutiva Central de Kaisen AI)

* **Ubicación en Disco:** `~/Kaisen_AI/01_Proyectos/Proyecto_Jerico`
* **Directorio de Bocetos y Diseño:** `~/Kaisen_AI/01_Proyectos/Boceto_jerico`
* **Repositorio Remoto:** `https://github.com/kaisen-ai-skynet/Proyecto_Jerico.git`
* **Sudo Supremo / CTO:** Santiago Gonzalez (`kaisen.ai.santiago.cto@gmail.com`)
* **Estado:** En planeación activa / Especificación de ingeniería y boceto maestro
* **Predecesor:** Jarvis (Ecosistema de 25 flujos n8n + scripts host en `100.79.169.121`, pausado el 16/08/2026)

---

## 🎯 1. Visión Holística: Los 9 Pilares de Jericó

**Jericó** es concebido como el **Sistema Operativo Inteligente (AI-OS) y Secretaria Ejecutiva Central de Kaisen AI**. No es un simple chatbot, sino una entidad omnipresente que cohesiona a todas las áreas de la compañía:

1. **Secretaría Comercial y Frontline de Clientes:** Interactúa con prospectos en tiempo real, califica necesidades y despacha resúmenes inmediatos al área comercial, administrativa, técnica y al CTO.
2. **Interfaz Visual y Presencia Silenciosa:** Dashboard interactivo propio (Next.js / WebSockets) con agentes trabajando 24/7 en segundo plano.
3. **Voz Continua y Streaming Bidireccional:** Invocación inmediata ("Hey Jericó" / Push-to-Talk) y conversación fluida con cada miembro del equipo (Gemini Live API, latencia <500 ms).
4. **Dev & Code Agent Autónomo:** Asistente técnico que genera código, resuelve bugs, investiga librerías e indaga servicios pasados y futuros de Kaisen AI.
5. **Marketing, Leads y Factoría de Demos:** Estructuración de campañas de marketing, prospección activa y generación ultrarrápida de demos interactivas para clientes.
6. **Arquitectura y SysAdmin Remoto:** Control del servidor `100.79.169.121`, monitoreo de contenedores Docker, organización de bases de datos y orquestación de migraciones.
7. **Redactor Institucional y Estratega:** Redacción de informes formales, actas de entrega, propuestas comerciales y custodia viva de Obsidian y YouTrack.
8. **Seguridad y Jerarquía RBAC ("SUDO SUPREMO"):** Santiago González tiene facultades de control y override absoluto desde su máquina local (`janty`). Permisos segmentados para el equipo.
9. **Contexto Masivo y Enrutado Inteligente:** Memoria distribuida (Redis + PostgreSQL + RAG vectorial en bóvedas de Obsidian) con Token Router (Gemini Flash para baja latencia / modelos superiores para razonamiento complejo).

---

## 🔍 2. Auditoría de Jarvis v1.0: ¿Qué SÍ Vale la Pena y qué NO?

### 🏆 QUÉ SÍ VALE LA PENA (Rescatar e Integrar):
* **Catálogo de 38 Herramientas (`jarvis-ops`):** Endpoints y lógica de negocio comprobada para YouTrack Cloud, Google Calendar, Notion, GitHub y Docker. Se reescriben como clases Python tipadas (`Pydantic`).
* **Esquemas de Notion y PostgreSQL:** `DB-01 Sanctum`, `DB-02 Modo Cueva`, `DB-07 Finanzas` y esquemas de clientes (`segurosbolivar-db`, `mundodeoro-db`).
* **Token Router:** Clasificación rápida de complejidad con Gemini Flash para reducir latencia y costo.
* **Protocolo de Confirmación Obligatoria:** Autorización explícita antes de cualquier mutación de datos.
* **Red Tailscale y Aislamiento:** Servidor `100.79.169.121` con contenedores de base de datos aislados por cliente.

### ❌ QUÉ NO VALE LA PENA (Desechar y Sustituir):
* **El Monolito de JSONs en n8n:** Fragilidad extrema, nula capacidad de pruebas unitarias y latencia acumulada. n8n vuelve a su rol de webhook auxiliar secundario.
* **Scripts ingenuos en Crontab:** Sustitución de `jarvis-salud.sh` (que reiniciaba Cloudflare 288 veces/día) por un daemon de monitoreo con validación de códigos HTTP reales.
* **Monocanal de Telegram:** Reemplazado por una interfaz visual rica (Dashboard Web) combinada con streaming de voz en tiempo real.
* **Agente Único Generalista:** Reemplazado por una constelación de micro-agentes especializados.

---

## 🚀 3. Documentación Completa en el Directorio de Boceto

Todos los detalles técnicos, inventarios de rutas y planes de arquitectura se encuentran documentados en:
📂 `~/Kaisen_AI/01_Proyectos/Boceto_jerico/`

* [`ORGANIZACION_IDEAS_Y_VISION.md`](./ORGANIZACION_IDEAS_Y_VISION.md): Detalle exhaustivo de los 9 pilares de Santiago.
* [`ANALISIS_CRITICO_JARVIS_VS_JERICO.md`](./ANALISIS_CRITICO_JARVIS_VS_JERICO.md): Auditoría completa, lecciones aprendidas y veredicto.
* [`EL_COMO_ARQUITECTURA_Y_PLAN.md`](./EL_COMO_ARQUITECTURA_Y_PLAN.md): Stack técnico (FastAPI, Gemini Live API, Next.js, Redis, Postgres) y roadmap en 5 fases.
* [`MAPA_RUTAS_INVENTARIO.md`](./MAPA_RUTAS_INVENTARIO.md): Ubicación física de cada archivo, flujo y respaldo.

---
> 🕒 **Última modificación:** 20/09/2026 15:25 (Agente Antigravity)
