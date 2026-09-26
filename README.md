# 🛡️ Proyecto Jericó — AI-OS Kaisen AI (greenfield)

> Spec canónica: `docs/spec/` (v2, migrada desde `Boceto_jerico/` el 23/09/2026; el boceto queda como puntero inverso). Nota viva: `~/Kaisen_AI/02_Obsidian_Kaisen/01_Proyectos/Proyecto_Jerico.md`.

Modelos por env, no fijos en código: L0 local, L1 operativo, L2 código, L3 finanzas/legal. Gateway OpenAI-compatible (OpenRouter o claves directas). Voz: whisper + Fish/XTTS, muestras fuera del repo. Infra: Oracle ARM64, red `jerico_net`.

## Estructura y rutas

Ver `docs/ESTRUCTURA_Y_RUTAS.md` (índice único, sin duplicados).

## Reglas Copilot

- `/.github/muse-instructions.md` — se carga solo en Copilot.
- `/.github/prompts/generar-readme.prompt.md` — prompt para regenerar este README.

## Documentación actualizable

El repositorio incluye un prompt reutilizable en `/.github/prompts/generar-readme.prompt.md` para mantener este README alineado con el estado real del proyecto, sin inventar funcionalidades ni comandos no verificados.

## Quickstart v0

`cp .env.example .env`, `pip install -e .`, `python -m jerico ask --verbose "..."`, `pytest -q`, `docker compose up`.

