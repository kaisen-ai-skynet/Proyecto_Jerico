# INFORME HERDR - Estado y Mejoras del Proyecto Jericó

**Fecha:** 29 de septiembre de 2026
**Autor:** Antigravity (Modo Autónomo)
**Revisor:** Santiago Gonzalez (CTO)

## 1. Estado Actual (Análisis Profundo)

Se realizó una auditoría completa de la base de código en `~/Kaisen_AI/01_Proyectos/Proyecto_Jerico`.

*   **Tests:** La suite de tests cuenta con 31 pruebas (`test_api.py`, `test_memory.py`, `test_router.py`, `test_tools_readonly.py`). Se ejecutó `pytest` y **todas (31/31) pasan correctamente**.
*   **Documentación:** `docs/spec/` contiene la especificación canónica actualizada (v2). No hay duplicados residuales en el directorio `Boceto_jerico/` exterior. El archivo `README.md` está alineado.
*   **Entorno (`.env`):** Existe un `pyproject.toml` válido y un `.env.example` exhaustivo que prevé un gateway compartido (OpenRouter) y variables precisas para ruteo (L1-L3), límites de tasa y autenticación.
*   **Calidad de Código (Deuda Técnica encontrada):**
    *   Existen advertencias menores de tipado de `mypy` en `memory.py`, `llm_client.py` y `stt.py` que sugerían inestabilidad con los genéricos y los diccionarios de variables de entorno.
    *   **Deuda de Concurrencia:** El endpoint de FastAPI `POST /api/v1/ask` es síncrono y la llamada al LLM a través de `OpenAI` también lo es, lo que bloquea el event loop de `asyncio` bajo concurrencia real.
    *   **Deuda de Escalabilidad:** `RateLimiter` y `MemoryManager` viven enteramente en memoria (`dict`), lo cual rompe la escalabilidad si se levantan múltiples workers con Gunicorn/Uvicorn.
    *   **Scripts de Soporte:** Faltaban pruebas _End-to-End_ reales con HTTP requests y un script unificado de validación.

## 2. Hallazgos y Mejoras Implementadas (Fase 2)

Se han clasificado las mejoras por impacto y esfuerzo, y se han **implementado localmente** las de riesgo bajo (seguras y reversibles).

*   **[Implementado] Resolución de Types (mypy):** Se corrigieron las advertencias estáticas sobre `_execute` en las herramientas (Notion, YouTrack, Docker), así como en la obtención de propiedades de memoria, para lograr un pase limpio en `mypy`.
*   **[Implementado] Scripts de Verificación Unificada:** Se creó `scripts/verify.sh` que centraliza la ejecución de `ruff`, `mypy` y `pytest`. 
*   **[Implementado] Prueba E2E:** Se creó `scripts/test_e2e.sh`, que envía una solicitud HTTP POST real a `/api/v1/ask` (Nivel 0) usando un token autorizado para asegurar que FastAPI y el enrutador central funcionan integralmente.
*   **[Completado] Control de Versiones:** Todos estos cambios han sido integrados con la identidad `Santiago Gonzalez <kaisen.ai.santiago.cto@gmail.com>` de forma local. No se ha realizado `push`.

## 3. Hecho vs Pendiente

### Hecho
*   [x] Validación cruzada de duplicados en bocetos vs repositorio de código base.
*   [x] Pase limpio y verde de la suite de 31 pruebas.
*   [x] Implementación de scripts E2E y de validación (`scripts/test_e2e.sh`, `scripts/verify.sh`).
*   [x] Resolución y superación completa de las barreras del linter y tipeado estático.
*   [x] Configuración de `.env.example` revisada (preparada con el gateway compartido y variables de entorno completas).

### Pendiente
*   [ ] Migrar el cliente LLM (de OpenAI síncrono al `AsyncOpenAI`) y hacer los endpoints `async def`.
*   [ ] Extraer `MemoryManager` y `RateLimiter` hacia Redis o Postgres si se requiere multi-worker (está previsto en `.env`, pero la lógica no está en `memory.py` aún).
*   [ ] Despliegue de Fase 0 (VPS Oracle) a través de la ejecución en firme de `scripts/bootstrap_vps_oracle.sh`.

## 4. Decisiones Requeridas del CTO

1.  **Bloqueo de Event Loop (Prioridad Alta):** ¿Procedo con un refactor del cliente LLM para usar `AsyncOpenAI`? Afectará a `jerico.llm_client.py` y `jerico.api.py`. Dado que esto altera el flujo asíncrono, prefiero validación antes de proceder.
2.  **Estado/Almacenamiento (Prioridad Media):** ¿Cambiamos `MemoryManager` a la implementación de Redis en esta etapa de MVP, o nos mantenemos en RAM por ahora con 1 worker?
3.  **Despliegue VPS (Prioridad Alta):** ¿Tiene autorización el agente de ejecutar `scripts/bootstrap_vps_oracle.sh` en el entorno remoto, o será ejecutado manualmente? 
