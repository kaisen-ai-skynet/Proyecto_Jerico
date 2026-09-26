# Muse instructions — Proyecto Jericó

Stack base: Python 3.12, FastAPI, Pydantic v2, Typer, Loguru, Pytest.
El modelo no está fijado en código. Niveles por env: L0 local, L1 operativo, L2 código, L3 finanzas/legal. Gateway OpenAI-compatible compartido (OpenRouter u otro) o credenciales por nivel.
Pin de versión: prohibido `-latest` y `-preview`. No inventar IDs de modelo.
No meter LangGraph, Celery, Next.js ni Live API hasta que una fase los necesite. El horizonte de modelos sí está abierto.
Tools: `BaseTool`, read-only por defecto. Writes exigen `confirm=True` + audit JSONL.
Voz: interfaz lista (`faster-whisper` / TTS). `voices/` fuera del repo, con consentimiento.
Infra: Oracle ARM64 + red propia `jerico_net`. No asumir `100.79.169.121` (quarantine).
Spec canónica: `docs/spec/`. No duplicarla.
Responder con código + pytest.
