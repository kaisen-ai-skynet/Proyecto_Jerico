# Memoria de Agente (agy) — Proyecto Jericó

**Agente:** Antigravity (agy)  
**Rol:** Ingeniero de Arquitectura de Sistemas (Kaisen AI)  
**CTO:** Santiago Gonzalez  
**Fecha:** 29/09/2026  
**Frente:** Fase 4 · Frente 1 — SPEC_JERICO_V2 (Análisis Hermes → Jericó)  

---

## 1. Misión
Elaborar la especificación técnica y arquitectónica canónica de **Jericó v2** (`docs/SPEC_JERICO_V2.md`) tomando como referencia e inspiración el repositorio de **Hermes Agent** (Nous Research), garantizando la evolución de Jericó desde un servicio REST síncrono (v0.2.0) a un AI-OS agéntico autónomo, soberano y económico, manteniendo rigurosamente los invariantes de Kaisen AI (modelos pineados sin alias flotantes, Oracle Free Tier A1, cobertura $\ge 89\%$, cero frameworks monolíticos externos).

---

## 2. Insumos Utilizados
1. **Repositorio de Hermes Agent (`/home/janty-mr/.hermes/hermes-agent`):**
   - Invariantes y gobernanza: `AGENTS.md` (reglas de prompt caching y cintura estrecha *narrow waist*), `README.md`.
   - Bucle de turnos y orquestación: `agent/conversation_loop.py`, `agent/turn_*.py` (`turn_preflight.py`, `turn_request_assembly.py`, `turn_api_call.py`, `turn_tool_round.py`, `turn_context_compaction.py`, `turn_recovery.py`, `turn_finalizer.py`).
   - Herramientas y cintura estrecha: `toolsets.py` (`_HERMES_CORE_TOOLS`, toolsets por postura), `tools/registry.py` (`check_fn` con TTL cache), `tools/environments/` (`local.py`, `docker.py`).
   - Persistencia relacional: `hermes_state.py`, `hermes_state_wal.py`, `hermes_state_schema.py`, `hermes_state_lockowners.py` (diagnóstico en `/proc/<pid>/fd`), `hermes_state_fts.py` (FTS5 trigram).
   - Habilidades y curación: `skills/` (formato canónico `SKILL.md`), `agent/curator.py` (bucle por inactividad >2h, ciclo 7 días, transiciones `active` $\to$ `stale` $\to$ `archived`).
   - Pasarela omnicanal y tareas de fondo: `gateway/run.py`, `cron/scheduler.py`, `cron/jobs.py`.
   - Documentación técnica interna: `website/docs/developer-guide/` (`context-compression-and-caching.md`, `agent-loop.md`, `tools-runtime.md`, `creating-skills.md`, `cron-internals.md`, `session-storage.md`).
2. **Análisis Previo:** `docs/architecture/hermes_master_architecture.md`.
3. **Estado de Jericó (v0.2.0):**
   - Código fuente: `src/jerico/**` (`api.py`, `router.py`, `llm_client.py`, `memory.py`, `redis_backends.py`, `tools/**`, `config.py`).
   - Suite de pruebas y verificación: `scripts/verify.sh` (173 tests pasando, cobertura global 89%).
   - Especificaciones y decisiones: `docs/spec/ARQUITECTURA.md`, `docs/spec/EL_COMO_ARQUITECTURA_Y_PLAN.md`, `docs/decisiones/*`.

---

## 3. Decisiones Clave de Arquitectura
1. **Invariante de Prompt Caching:** El *system prompt* es estrictamente inmutable byte por byte durante toda la sesión; se deduplica por hash SHA-256 en base de datos. Instrucciones dinámicas, contexto temporal y memorias se inyectan como mensajes efímeros `user` o `tool`.
2. **Cintura Estrecha (*Narrow Waist*):** No sobrecargar el esquema base enviado al LLM. Integraciones opcionales ingresan vía compuerta `check_fn` con TTL o subconjuntos por postura operativa (`coding`, `ops`, `personal`, `default`).
3. **Patrón Facade + Siblings:** El ciclo de turnos agéntico se descompone en módulos especializados (`turn_preflight`, `turn_request_assembly`, `turn_api_call`, `turn_tool_round`, `turn_context_compaction`, `turn_finalizer`) evitando archivos monolíticos.
4. **Persistencia SQLite WAL Local:** Se adopta `jerico_state.db` con pragmas WAL de alto rendimiento y diagnóstico forense de bloqueos (`/proc/<pid>/fd`) para eliminar la dependencia de servicios externos en Oracle Free Tier A1.
5. **Compresión de Contexto en Dos Capas:** Poda zero-cost (truncado de salidas de tools pasadas) + resumen auxiliar estructurado con `glm-5.3-flash`, preservando los últimos 10 turnos y el linaje genealógico de sesión (`parent_session_id`).
6. **Protocolo Santiago Integrado:** Operaciones de herramientas con `readonly=False` requieren confirmación explícita (`confirm=True`) interceptada a nivel de gateway antes de invocar entornos locales o Docker.
7. **Curador por Inactividad:** Tarea de fondo que evalúa el ciclo de vida de habilidades solo tras periodos de inactividad de usuario (>2h), evitando consumo de cómputo en caliente.

---

## 4. Estado Actual
- **Fase 4 · Frente 1:** COMPLETADO.
- Entregable único: `docs/SPEC_JERICO_V2.md` creado, validado y commiteado localmente.
- Baseline de tests: 173/173 tests pasando, 89% de cobertura, ruff y mypy limpios.
- Árbol de trabajo limpio (salvo archivos preexistentes sin trackear en `docs/architecture/` y arnés `.agents/`).

---

## 5. Pendientes para el Orquestador y Próximas Fases
1. **Revisión del CTO:** Resolver las 5 preguntas abiertas planteadas en la Sección 8 de `docs/SPEC_JERICO_V2.md`.
2. **Apertura de Sprints de Implementación:** Ejecución secuencial de los 8 PRs definidos en la especificación:
   - PR 1: Motor de Persistencia SQLite WAL y Diagnóstico Forense de Bloqueos (`jerico.state`).
   - PR 2: Invariante de Prompt Caching e Inmutabilidad del System Prompt (`jerico.agent.prompt_builder`).
   - PR 3: Bucle de Turnos Agéntico Modular Facade + Siblings (`jerico.agent.turn_*`).
   - PR 4: Compresión de Contexto en Dos Capas (`jerico.agent.turn_context_compaction`).
   - PR 5: Tool Registry de Cintura Estrecha, `check_fn` y Entornos Sandboxed (`jerico.tools`).
   - PR 6: Sistema de Habilidades `SKILL.md` y Curador por Inactividad (`jerico.skills`).
   - PR 7: Memoria Episódica con Búsqueda FTS5 Trigram (`jerico.state.fts`).
   - PR 8: Omni-Gateway Unificado (Telegram, Siri, CLI, REST) y Cron Scheduler (`jerico.gateway`).

---

## 6. Cómo Invoca el Orquestador (Comando Headless)
Para reanudar o consultar la memoria de este agente en modo headless:
```bash
# Invocar Antigravity CLI en modo headless apuntando al workspace de Jericó
agy run --dir /home/janty-mr/Kaisen_AI/01_Proyectos/Proyecto_Jerico \
  --prompt "Continuar con Fase 4 Frente 1 / Fase 5 según directrices de .agents/agy/MEMORIA.md"
```
Para auditar el estado del arnés y entregable:
```bash
cd /home/janty-mr/Kaisen_AI/01_Proyectos/Proyecto_Jerico
git log -1 --stat
cat docs/SPEC_JERICO_V2.md | head -n 35
```
