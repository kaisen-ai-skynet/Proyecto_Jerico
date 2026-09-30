# AGENTS.md — Proyecto Jericó AI-OS
AI-OS agéntico autónomo, soberano y económico para Kaisen AI (Oracle Cloud Free Tier A1).

## Stack y estructura
- Python 3.12, FastAPI, SQLite WAL, FTS5 trigram, Redis 7 (docker-compose).
- `jerico/` (núcleo agéntico, turn loop, persistencia, tools, gateway), `docs/` (especificación y arquitectura).
- `tests/` (suite unitaria e integración), `scripts/` (verificación y bootstrap VPS).

## Comandos
- Verificar suite completa: `./scripts/verify.sh`
- Ejecutar tests unitarios: `pytest tests/ -v`
- Formato e higiene: `pre-commit run --all-files`

## Convenciones
- Identidad Git: `Santiago Gonzalez <kaisen.ai.santiago.cto@gmail.com>`.
- Idioma: Español en documentación, commits y minutas; código e identificadores en inglés.
- Cobertura mínima obligatoria: $\ge 89\%$ (actualmente $92.95\%$, 268 tests).

## Reglas de dominio
- Modelos pineados sin alias flotantes; cero frameworks monolíticos externos (LangChain/LlamaIndex prohibidos).
- PromptBuilder inmutable por hash SHA-256; leases transaccionales SQLite cross-engine.
- Cintura estrecha (*narrow waist*): herramientas registradas con TTL cache y control de postura.

## Límites
- ✅ Siempre: ejecutar `./scripts/verify.sh` antes de commitear y mantener cobertura $\ge 89\%$.
- ⚠️ Preguntar antes: habilitar socket Docker para sandbox, activar mutación automática del curator.
- 🚫 Nunca: hacer `git push`, tocar archivos sin trackear ajenos, almacenar variables de `.env` en código.

## Verificación
- Ejecución limpia: `./scripts/verify.sh`
