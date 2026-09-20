# Muse instructions — Proyecto Jericó (AI-OS Kaisen AI, greenfield)

Stack v0: Python 3.12, FastAPI, Pydantic v2, Typer, Loguru, Pytest.
LLM: cliente OpenAI-compatible. Modelos: `glm-5.3-flash` (default: ruteo, comercial, actas) y `deepseek-flash` (código, thinking+FIM). `Gemini AI Studio` solo bootstrap, no prod. Pin de versión, prohibido `-latest`/`-preview`.
No usar en v0: LangChain, LangGraph, Celery, Next.js, Tauri, Gemini Live API. Solo interfaces listas para migrar.
Tools: cada tool hereda `BaseTool` Pydantic, read-only por defecto. Writes requieren `confirm=True` + audit log.
Voz: STT `faster-whisper` + TTS clonada `Fish S1-mini` (v0 CPU) → `Fish S2 / XTTS v2` (v1). Half-duplex, no streaming. `voices/` fuera del repo, con consentimiento.
Infra: Oracle Ampere ARM64 + Docker. No asumir `100.79.169.121` (quarantine).
Responder siempre con código + test pytest.
