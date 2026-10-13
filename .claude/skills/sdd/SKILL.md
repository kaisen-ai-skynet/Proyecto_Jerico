---
name: sdd
description: "Protocolo SDD (Spec-Driven Development) del «Proyecto Jericó» y cuándo usarlo: constitución → spec → clarificación → plan → tareas → implementación TDD → validación, con EARS en español, gates de aprobación humana y artefactos en specs/; sirve para funcionalidad nueva, cambios, incidentes y creación desde cero, y define qué produce cada agente del equipo."
argument-hint: "[petición]"
---

# SDD — Spec-Driven Development (spec-anchored)

## Qué es

Metodología donde la especificación formal del comportamiento **precede y gobierna** la implementación y su validación. Enfoque adoptado: **spec-anchored** — la spec es un artefacto vivo que se actualiza para guiar la evolución del software (no se descarta tras el primer código).

## Uso en Claude Code

- **Sesión de coordinación:** `claude --agent coordinator` abre la sesión como coordinador: único interlocutor con el humano; conduce fases y gates, y delega en los subagentes con la herramienta **Agent** (solo puede lanzar a planner, implementer y reviewer).
- **Invocación directa:** `/sdd <petición>` invoca este protocolo en cualquier sesión; quien lo invoca actúa como coordinador y delega con la herramienta **Agent**.
- **Subagentes:** `planner` (redacta constitución, spec, plan y tareas), `implementer` (una tarea por invocación, TDD estricto), `reviewer` (solo lectura y verificación; veredicto binario); se lanzan con la herramienta **Agent** y el coordinador solo puede lanzar a estos tres.
- **Guardianes (hooks PreToolUse):** las escrituras del `planner` están limitadas a `specs/**` y `docs/constitution.md` (`guard-planner.sh`); los comandos destructivos (`rm`, `sudo`, `git push`, `git reset --hard`, `pkill`/`kill`) están bloqueados (`guard-bash.sh`). Si un guardián bloquea, no se busca otro camino: se reporta al coordinador.

## Cuándo usarla

- Cualquier trabajo de ingeniería: funcionalidad nueva, cambio/actualización, corrección de defectos, creación desde cero o sobre código existente.
- SIEMPRE al inicio de un flujo con el equipo SDD (coordinator → planner → implementer → reviewer).
- NO para: preguntas triviales, cambios de una línea sin riesgo, exploraciones desechables tipo spike.

## Artefactos y estructura

```
docs/constitution.md          # Principios innegociables (≤15 líneas), una vez por proyecto
specs/NNN-nombre/
  ├── spec.md                 # QUÉ y POR QUÉ (sin código ni rutas de archivo)
  ├── plan.md                 # CÓMO técnico (archivos, funciones puras, pseudocódigo, tests)
  └── tasks.md                # Tareas atómicas (≤20–30 min) con «Hecho cuando:»
```

## EARS en español (criterios de aceptación)

- **Evento:** `CUANDO <evento>, EL SISTEMA <respuesta>`
- **Error/Excepción:** `SI <condición no deseada>, ENTONCES EL SISTEMA <respuesta>`
- **Estado:** `MIENTRAS <estado>, EL SISTEMA <respuesta>`
- **Permanente:** `EL SISTEMA <comportamiento permanente>`

Reglas: cada requisito se mapea 1:1 a un caso de prueba; los casos de error se contemplan explícitamente; cero adjetivos subjetivos («rápido», «bonito» → criterios medibles).

## Flujo en 7 pasos

1. **Constitución** (`docs/constitution.md`): principios innegociables del proyecto (simplicidad, primacía de la spec, tests sin dependencias externas, integridad de datos, idioma). Se crea una vez.
2. **Especificación** (`spec.md`): entrevista de clarificación (máx. 5 preguntas, de una en una) y requisitos en EARS. Solo qué y por qué. → Gate: **aprobación humana**.
3. **Clarificación**: auditoría QA del spec (ambigüedades, contradicciones, casos límite, choques con la constitución) antes de planificar.
4. **Plan** (`plan.md`): archivos, funciones puras (parámetro «hoy» para el tiempo), pseudocódigo, decisiones con alternativas descartadas, estrategia de pruebas. → Gate: **aprobación humana**.
5. **Tareas** (`tasks.md`): atómicas (≤20–30 min), en orden de dependencias, cada una con requisitos cubiertos y «Hecho cuando: <verificable>».
6. **Implementación**: TDD estricto, **una tarea a la vez**: tests primero (rojo) → código (verde) → verificación → **detención obligatoria**.
7. **Validación**: recorrido requisito por requisito contra los tests + verificación visual/consola si hay UI. Veredicto binario del reviewer: `APROBADO` / `CAMBIOS NECESARIOS`.

## Variantes

- **Cambio / actualización de software existente:** la petición se trata como *delta* sobre la spec vigente; se actualiza spec (spec-anchored), plan y tareas afectados, y se repite el ciclo 6–7.
- **Incidente / depuración:** primero reproducir; luego causa raíz (skill `systematic-debugging`: sin fix sin investigación); test que falla primero; fix mínimo; validación. Prohibido el «parche rápido».
- **Creación desde cero:** ciclo completo 1→7.
- **Creación sobre algo existente:** igual que cambio; la spec describe el resultado final, no solo el diff.

## Reglas TDD

- Tests ANTES del código; deben fallar por la razón correcta.
- Un requisito ↔ al menos un test; casos de error incluidos.
- Cambios mínimos y atómicos; nada de refactors «de paso» sin spec.
- «Hecho cuando:» se cumple con evidencia, no con opinión.

## Roles del equipo (quién produce qué)

- **coordinator** (agente de sesión; `claude --agent coordinator`): conduce fases, gates y transferencia de contexto; único interlocutor humano; no edita nada (sin herramientas Write/Edit/Bash: delega siempre).
- **planner** (subagente): lee y redacta constitución/spec/plan/tareas; solo escribe en `specs/` y `docs/constitution.md` (el guardián lo hace cumplir a nivel de motor).
- **implementer** (subagente): una tarea por invocación, TDD estricto, se detiene y reporta.
- **reviewer** (subagente): clarificación QA + validación requisito por requisito; solo lectura; veredicto binario.

## Prohibiciones

- Código o rutas de archivo dentro de `spec.md`; adjetivos subjetivos en requisitos.
- Avanzar de fase sin los gates de aprobación humana.
- Fixes sin causa raíz; tests sin requisito; commits/push no autorizados.

## Criterio de finalización

La validación termina con veredicto `APROBADO` del reviewer y aprobación humana del resultado; la spec queda actualizada como fuente viva.
