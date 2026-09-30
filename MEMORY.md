# MEMORY.md — Proyecto Jericó AI-OS
Memoria consolidada de arquitectura e implementación (Fases 1 a 4). Máximo ~50 líneas.

## Estado actual
- Versión: Jericó v2 AI-OS en desarrollo. Especificación canónica en `docs/SPEC_JERICO_V2.md`.
- Hitos completados: PR 1 a PR 8 finalizados y verificados con 268 tests y 92.95% de cobertura.
- Componentes funcionales: SQLite WAL, PromptBuilder SHA-256, AgentTurnLoop (max 8 iters),
  compactación de contexto >80%, registry TTL con posturas, curator linter, FTS5 trigram,
  gateway omnicanal (REST/Siri/Telegram/CLI) con scheduler y watchdog.
- Última sincronización: 30/09/2026 (Consolidación de memorias preexistentes agy y opencode).

## Decisiones (y por qué)
- Arquitectura inspirada en Hermes Agent: Adopción de cintura estrecha y turn loop sin monolitos.
- SQLite WAL con pool de lectura: Concurrencia segura sin saturar recursos en OCI A1 Free Tier.
- Zero-Trust Tailscale: Binds estrictos en `127.0.0.1:8000` y Docker Compose para servicios internos.
- Worktrees aislados para CI: Correcciones de formato aisladas de ramas activas de desarrollo.

## Aprendizajes y errores a evitar
- Pre-commit trailing whitespace: Cuidar espacios al final de línea en markdown (`.pre-commit-config.yaml`).
- Autonomía del curator: No auto-archivar skills sin decisión explícita del CTO.
- Sandboxing: Mantener procesos en subprocesos locales hasta definir política de socket Docker.

## Próximos pasos
1. Validar canal de aprobación interactiva del gateway sin introducir escrituras no controladas.
2. Resolver con el CTO la política de acceso a Docker socket para herramientas de sandbox.
3. Mantener `./scripts/verify.sh` en verde en cada interacción.

---
> 🕒 **Última modificación:** 30/09/2026 17:45 (Agente Antigravity · Orquestador-Arquitecto)
