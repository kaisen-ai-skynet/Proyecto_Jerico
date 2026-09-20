# Prompt: generar README.md de Jericó (pegar en Copilot Chat)

Genera `README.md` para Proyecto Jericó (AI-OS + Secretaria Ejecutiva Kaisen AI, greenfield desde cero).

Contexto:
- Visión Full AI-OS 5 fases, pero v0 = CLI Typer + API FastAPI + Telegram/Siri en Oracle Free Tier.
- Stack v2: Python 3.12/FastAPI, `GLM-5.3-Flash` (~$0.075/$0.25 x 1M, router/comercial/actas) + `DeepSeek-V4.1-Flash` thinking+FIM (código), Gemini AI Studio solo bootstrap. Ambos OpenAI-compatibles.
- Voz clonada propia: faster-whisper STT + Fish S1-mini TTS (v0 CPU), Fish S2/XTTS v2 en v1. Sin Gemini Live API. `voices/` fuera del repo + consentimiento.
- Datos: PG16 + Redis7 nuevos en Oracle. Notion solo vista. `100.79.169.121` en quarantine.
- Quarantine estricta: `Boceto_jerico/` es spec solo-lectura. No copiar JSONs n8n ni `jarvis-*.sh`.

El README debe tener:
1. Visión 9 pilares (1 línea c/u).
2. Tabla stack v2 con costos.
3. Arquitectura: 1 agente + 5 prompts, TokenRouter L0/L1/L2, `jerico-voice` aparte.
4. Estructura del repo (ver `docs/ESTRUCTURA_Y_RUTAS.md`).
5. Quickstart: `cp .env.example .env`, `pip install -e .`, `python -m jerico "..."`, `pytest -q`, `docker compose up`.
6. Roadmap Fase 0 Oracle → Fase 5 retiro Jarvis.
7. Guardrails: confirmación writes, RBAC `ADMIN_ID`, voces con consentimiento.

Tono técnico, español, sin inventar Next/Tauri/Celery/Live API en v0.
