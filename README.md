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

## Desarrollo y acceso a la API

Con Docker Compose, el puerto `8000` se publica solo en `127.0.0.1`; la API queda accesible desde el mismo host en `http://127.0.0.1:8000` y no se expone directamente a la LAN. Dentro del contenedor, Jericó escucha en `0.0.0.0:8000` para que Docker pueda reenviar las conexiones.

Si más adelante necesitas acceso desde la LAN o Tailscale, cambia en `docker-compose.yml` la IP de enlace de `ports` por la IP concreta de esa interfaz, conservando el formato `IP_DEL_HOST:8000:8000`. Por ejemplo, usa la IP LAN del servidor (`192.168.1.20:8000:8000`) o su IP Tailscale, que puedes consultar con `tailscale ip -4` (`100.x.y.z:8000:8000`). Evita `8000:8000` o `0.0.0.0:8000:8000`, que publican el puerto en todas las interfaces. Reinicia con `docker compose up -d` y limita también el acceso con el firewall y un `JERICO_API_TOKEN` fuerte en `.env`.
