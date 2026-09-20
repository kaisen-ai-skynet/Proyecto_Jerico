# 🗺️ Inventario y Mapa Completo de Rutas: Jarvis ➔ Jericó

Este documento consolida la ubicación exacta y el contexto de todos los archivos, repositorios, respaldos, infraestructura y especificaciones técnicas relacionadas con el ecosistema de **Jarvis**, **Proyecto Jericó** y la infraestructura de **Kaisen AI**.

---

## 1. 🤖 Contexto: Jarvis Actual (Operativo / Legado / Pausa)
Ecosistema utilizado históricamente, basado en 25 flujos de n8n, scripts de host en el servidor y bot de Telegram.

### A. Respaldos de Flujos n8n Locales (JSON)
* **Directorio Contenedor:** `~/Kaisen_AI/01_Proyectos/Kaisen_AI/kaisen-respaldos/jarvis-backups/`
* **Flujos Principales de Conversación / Router:**
  * `Jarvis-Conversacion.bak-final-1707.json` (Versión final consolidada)
  * `Jarvis-Conversacion.bak-tier1-1937.json` (Router dinámico Flash / Pro)
  * `Jarvis-Conversacion.bak-redsiri-1946.json` (Integración Siri + Redis)
  * `Jarvis-Conversacion.bak-ytadmin-20260807-1740.json` (YouTrack admin integration)
  * `Jarvis-Conversacion.bak-server-preytadmin-20260807-1922.json`
  * `Jarvis-Conversacion.bak-siri-1155.json`
  * `Jarvis-Conversacion.bak-supa-1819.json`
  * `Jarvis-Conversacion.bak-fixya-1955.json`
  * `Jarvis-Conversacion.bak-infra-1725.json`
  * `Jarvis-Conversacion.bak-lat-1934.json`
  * Flujos por fases: `Jarvis-Conversacion.json.bak-fase1`, `Jarvis-Conversacion.json.bak-fase2`, `Jarvis-Conversacion.json.bak-fase4`, `Jarvis-Conversacion.bak-fase34-1514.json`, `Jarvis-Conversacion.bak-f8-1825.json`.
* **Flujos Especializados / Servicios:**
  * `Jarvis-FinAudit.bak-20260727-1706.json` (Auditor financiero nocturno 9 PM / Notion DB-07)
  * `Jarvis-GHWrite.bak-1825.json` (Escritura en repositorios GitHub)
  * `Jarvis-Opus.bak-f9-1830.json` (Procesamiento complejo con Claude Opus)
  * `Jarvis-PlanNoche.bak-2224.json` (Planificador nocturno 8:30 PM / Modo Cueva DB-02)
* **Respaldo Global del Ecosistema:**
  * `skynet-agency-local-backup-2026-07-08.zip` (Respaldo integral comprimido)

### B. Documentación Operativa y de Control
* **Protocolo de Pausa (2026-08-16):** `~/Kaisen_AI/01_Proyectos/Seguros_Bolivar/jp_seguros_n8n/PAUSA-JARVIS-2026-08-16.md`
* **Informe Antigravity P0-3 (Guardrail de Pausa):** `~/Kaisen_AI/01_Proyectos/Kaisen_AI/kaisen ai/ANTIGRAVITY/entregables/P0-3/pausa-jarvis.md`
* **Plantilla de Mensajes para Telegram:** `~/Kaisen_AI/01_Proyectos/Kaisen_AI/kaisen-despliegues/mensaje-para-jarvis.md`
* **Auditoría de Estado Completo (2026-08-07):** `~/Kaisen_AI/01_Proyectos/Kaisen_AI/reportes/kaisen-estado-completo-2026-08-07.md`
* **Voz Local Windows (PowerShell):** `C:\Users\Usuario\Jarvis\Jarvis-Voz.ps1` (Voz Microsoft Raul WinRT)

### C. Servidor de Producción (`ssh servidor` o `kaisenai@100.79.169.121`)
* **Scripts en el Host (`/home/kaisenai/`):**
  * `/home/kaisenai/jarvis-salud.sh` (Activo en cron cada 5 min — Soporte vital de n8n y cloudflared).
  * `/home/kaisenai/jarvis-metrics.py` (Pausado en crontab).
  * `/home/kaisenai/jarvis-auto-deploy.sh` (Pausado en crontab).
  * `/home/kaisenai/jarvis-pausa-2026-08-16.txt` (Lista con los IDs de los 25 flujos pausados).
  * `/home/kaisenai/crontab.bak-2026-08-16` (Crontab de respaldo original).
* **Contenedores Docker Activos:**
  * `skynet-n8n-1` (Instancia donde están registrados los flujos)
  * `skynet-n8n-worker-1` (Worker en modo cola)
  * `skynet-redis-1` (Queue mode y llaves `jarvis:recordados`)
  * `skynet-postgres-1` (PostgreSQL de n8n)
  * `jarvis-renderer` (Microservicio interno de renderizado de imágenes de workflows)
  * `skynet-cloudflared-1` (Túnel hacia `n8n.getkaisen.com`)

---

## 2. 🏛️ Contexto: Proyecto Jericó (Planeación y Desarrollo Propio)
Nuevo asistente inteligente de Kaisen AI, con arquitectura desacoplada y orientada a servicios.

* **Repositorio Git Principal:**
  * Ruta local: `~/Kaisen_AI/01_Proyectos/Proyecto_Jerico/`
  * Remote Git: `https://github.com/kaisen-ai-skynet/Proyecto_Jerico.git`
  * Rama: `main`
  * Identidad Git: `Santiago Gonzalez <kaisen.ai.santiago.cto@gmail.com>`
  * Documentación en el repo:
    * `README.md` (Visión y presentación del proyecto)
    * `docs/ARQUITECTURA.md` (Diseño de microservicios y hoja de ruta)
    * `docs/ESPECIFICACIONES_TECNICAS.md` (Esquemas de Notion, YouTrack y red)
    * `docs/bocetos/README.md` (Directorio interno de bocetos)
* **Carpeta de Bocetos y Prototipos Rápidos:**
  * `~/Kaisen_AI/01_Proyectos/Boceto_jerico/` (Este directorio de trabajo)
* **Documentación Viva en Obsidian (Bóveda Kaisen AI):**
  * Nota de Proyecto: `~/Kaisen_AI/02_Obsidian_Kaisen/01_Proyectos/Proyecto_Jerico.md`
  * Centro de Operaciones: `~/Kaisen_AI/02_Obsidian_Kaisen/00_DASHBOARD_EMPRESA.md`
* **Entornos de Desarrollo y Worktrees:**
  * `~/Kaisen_AI/01_Proyectos/copilot-worktrees/`

---

## 3. ⚙️ Contexto: Especificaciones Técnicas Transversales
Bases de conocimiento, herramientas de agentes, credenciales y protocolos operativos.

### A. Paquetes de Skills de Agentes y Prompts
* **Paquete de Skill Operativa de Jarvis (38 tools):**
  * `~/Kaisen_AI/01_Proyectos/Claude_IA/claude-skills-zips/jarvis-ops.zip` (contiene `jarvis-ops/SKILL.md`)
* **Doctrina de Seguimiento y Disciplina (Modo Cueva):**
  * `~/Kaisen_AI/01_Proyectos/Claude_IA/claude-skills-nuevas/seguimiento-personal.zip`
* **Estrategias de Optimización y Selección de Modelos:**
  * `~/Kaisen_AI/01_Proyectos/Claude_IA/claude-skills-nuevas/ahorro-tokens.zip`
* **Operaciones de Agentes de Código Jules:**
  * `~/Kaisen_AI/01_Proyectos/Claude_IA/claude-skills-zips/jules-ops.zip`
* **Estructura de Tarifas y Propuestas:**
  * `~/Kaisen_AI/01_Proyectos/Claude_IA/claude-skills-zips/kaisen-propuestas.zip`

### B. Esquemas de Base de Datos (Notion Segundo Cerebro)
* **Página Padre:** `e59a8560-3ffc-40fe-9d98-abff1c4b7561`
* **DB-01 SANCTUM:** `6006c308-5caf-4fa9-b67b-a4fbcd4acec4` (Devocional matutino)
* **DB-02 MODO CUEVA:** `1ffa5bed-6d24-417c-a62b-ae9087ed113c` (Hábitos, 40 días, integridad)
* **DB-03 SOMPAN:** `3e16469a-d55e-46e8-aa45-c89642818f22` (Visión)
* **DB-04 KAISEN.AI/SKYNET:** `76591789-bfcd-4de3-a8cf-1131beed9d9e` (Clientes y entregables)
* **DB-05 INCUBADORA:** `ebf3b948-6790-4781-a3dc-31b18a0624e2` (Proyectos I+D)
* **DB-07 FINANZAS:** `3a5d70da-1b09-8111-90af-ce8a3b437d6e` (Auditoría financiera Personal vs Kaisen)

### C. Infraestructura, Red y Credenciales
* **Topología de Red e Infraestructura:** `~/Kaisen_AI/00_Infraestructura/INFRASTRUCTURE.md`
* **Matriz de Migración de Credenciales:** `~/Kaisen_AI/00_Infraestructura/CREDENTIAL-MIGRATION-MATRIX.md`
* **Inventario de Secretos:** `~/Kaisen_AI/00_Infraestructura/MIGRATION-SECRETS-INVENTORY.txt`
* **Guía de Conexión:** `~/Kaisen_AI/00_Infraestructura/README_CONEXION_SERVIDOR.md`
* **Clave de Encriptación n8n:** `~/Kaisen_AI/01_Proyectos/Kaisen_AI/secretos/n8n-encryption-key-2026-08-16.asc`
* **Credenciales Google OAuth Maps:** `~/Kaisen_AI/01_Proyectos/Kaisen_AI/secretos/google_oauth_maps_credentials.json`
* **SSH Key Servidor:** `~/.ssh/id_ed25519`

### D. Gobernanza y Reglas de Agentes
* `~/AGENTS.md` (Directrices globales de Antigravity)
* `~/GEMINI.md` (Reglas del espacio de trabajo)
* `~/Kaisen_AI/01_Proyectos/Skynet/skynet-infra/CLAUDE.md` (Reglas de Claude Code / Skynet)
