# Memoria de opencode — Fase 4, Frente 2

## Misión
Implementar `docs/SPEC_JERICO_V2.md` siguiendo sus ocho PRs, con un commit local por PR, sin push. El spec se leyó completo antes de modificar código. Mantener `./scripts/verify.sh` verde con cobertura global mínima del 89% después de cada PR. Identidad: Santiago Gonzalez <kaisen.ai.santiago.cto@gmail.com>.

## PRs completados
- PR 1 — SQLite WAL, esquema transaccional, pool de lectura y escáner `/proc` para lockowners. Commit `8dc4a07`.
- PR 2 — PromptBuilder inmutable por hash SHA-256, ensamblado de mensajes transitorios y extracción de usage/cache tokens. Commit `7a60174`.
- PR 3 — AgentTurnLoop de máximo 8 iteraciones, leases SQLite cross-engine, retry/cancel de llamadas async, dispatch seguro y persistencia atómica de rondas; REST delega en el loop. Commit `65515ef`.
- PR 4 — detección >80%, poda determinista de tools antiguas y resumen estructurado con fallback seguro; cola dinámica en user content, prompt system y últimos 10 mensajes persistidos byte-estables. Commit `362ddf7`. Verify: 238 tests, cobertura total 92%.
- PR 5 — registro TTL, posturas, aprobación y entornos aislados. Commit `9fb0628`. Verify: 245 tests, cobertura 92,29%.
- PR 6 — loader/linter de skills y recomendaciones del curator sin mutación automática. Commit `062c422`. Verify: 251 tests, cobertura 92,41%.
- PR 7 — FTS5 trigram y herramienta de búsqueda limitada a la sesión. Commit `6302962`. Verify: 255 tests, cobertura 92,76%.
- PR 8 — gateway REST/Siri/Telegram/CLI, stream de respuestas completadas, scheduler cancelable y jobs de watchdog/sincronización/mantenimiento/backup; compatibilidad API validada. Commit `815957c`. Verify: 268 tests, cobertura 92,95%.

## Estado
- PR 1 a PR 8 completados y verificados; todos los commits son locales, sin push.
- Árbol de trabajo de código limpio tras PR 1; existe `docs/architecture/` sin trackear y ajeno, no modificar ni agregar.
- Este archivo es memoria local y no se agrega a git.

## Pendientes / preguntas para CTO
- Ninguna decisión bloqueante encontrada en PR 1. Las dudas razonables del spec se anotarán en el reporte final sin inventar decisiones.

## Invocación del orquestador
Trabajo completo hasta PR 8. PR 5 mantiene abierta la decisión de sandbox Docker vs subprocess local; no habilitar acceso al socket Docker sin decisión del CTO. PR 6 mantiene abierta la política de autonomía del curator; no auto-archivar sin decisión. PR 8 mantiene pendiente el canal de aprobación interactiva; el gateway no añade escrituras nuevas. No tocar `.agents/` salvo esta memoria, `docs/SPEC_JERICO_V2.md`, `docs/architecture/` ni archivos sin trackear ajenos.
