# 🛡️ Proyecto Jericó — AI-OS Kaisen AI (greenfield)

> Spec canónica: `~/Kaisen_AI/01_Proyectos/Boceto_jerico/` (v2 20/09/2026). Nota viva: `~/Kaisen_AI/02_Obsidian_Kaisen/01_Proyectos/Proyecto_Jerico.md`.

Stack v2: `GLM-5.3-Flash` (router/comercial) + `DeepSeek-V4.1-Flash` (código) + voz clonada propia (whisper + Fish/XTTS). Gemini AI Studio solo bootstrap. Infra v0: Oracle Free Tier limpio.

## Estructura y rutas

Ver `docs/ESTRUCTURA_Y_RUTAS.md` (índice único, sin duplicados).

## Reglas Copilot

- `/.github/muse-instructions.md` — se carga solo en Copilot.
- `/.github/prompts/generar-readme.prompt.md` — prompt para regenerar este README.

## Documentación actualizable

El repositorio incluye un prompt reutilizable en `/.github/prompts/generar-readme.prompt.md` para mantener este README alineado con el estado real del proyecto, sin inventar funcionalidades ni comandos no verificados.

## Quickstart v0

`cp .env.example .env`, `pip install -e .`, `python -m jerico "..."`, `pytest -q`, `docker compose up`.

