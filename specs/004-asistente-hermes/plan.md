# Plan 004 — Asistente de Jericó por fases (F4)

Las fases A1–A6 y sus criterios de salida están en `spec.md` §3; este plan fija el orden y las dependencias.

1. **A1 Núcleo y memoria** — depende de F2 (CRM desplegado) y de decidir PostgreSQL en desarrollo. Bloquea todo lo demás.
2. **A2 Habilidades y curador** — depende de A1. Usa el catálogo de F6 (spec 003) para la habilidad «preparar propuesta».
3. **A5 Interfaz web** — depende de A1; puede ir antes de A3 si se suman comerciales.
4. **A3 Leads, webs y apps** — depende de A1 y A2; sandbox según D3.
5. **A4 Voz** — A4.1 (notas de voz) tras A1; A4.2 solo tras la prueba ciega y el OK del CTO.
6. **A6 Jev y mejora continua** — depende de F3 y de la bitácora de `Flota_Jev`.

Dónde escribir: `src/jerico/agent/` (bucle), `src/jerico/memory.py` → repositorio PostgreSQL, `src/jerico/voice/`, `src/jerico/web/` (nuevo, PWA). Nada de esto se implementa en esta rama: son specs.

> 🕒 **Última modificación:** 13/10/2026 22:40 (Claude Code · Sonnet 5.5 · kai-jev)
