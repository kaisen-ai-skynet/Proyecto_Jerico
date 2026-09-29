# Dossier 01: Migración a AsyncOpenAI

## Estado Real
Actualmente, el endpoint principal `POST /api/v1/ask` en FastAPI utiliza la librería `openai` de forma síncrona. Bajo alta concurrencia, cada petición bloquea el event loop (hilo principal) de `asyncio` durante toda la latencia del modelo (usualmente segundos). Esto significa que 1 solo worker no podrá manejar solicitudes concurrentes, limitando el throughput drásticamente a pesar de estar usando FastAPI.

## Opciones
1.  **Migrar a AsyncOpenAI (Refactor Completo):** Cambiar `LLMClient` a asíncrono y todas las dependencias hasta `api.py` (`async def ask()`).
2.  **Mitigación sin Migrar (Workers/Threads):** Mantener el código síncrono, pero definir el endpoint en FastAPI como `def ask()` (no asíncrono) para que Starlette lo ejecute en un *threadpool* separado, mitigando parcialmente el bloqueo del event loop.
3.  **Mantener Status Quo:** Aceptable solo para entornos de prueba locales.

## Riesgos y Esfuerzo
*   **Esfuerzo (Migración Completa):** Medio. Requiere ajustar `jerico.llm_client.py` y propagar la asincronía a través del pipeline de respuesta en `api.py`, re-verificando los tests.
*   **Esfuerzo (Mitigación Threads):** Muy Bajo. Ya se hace en gran medida al no usar `async def`, pero satura hilos bajo carga intensa y pierde los beneficios nativos de FastAPI.
*   **Riesgos:** La migración asíncrona podría introducir bugs temporales en la gestión de excepciones de timeout del LLM, que requieren ajuste en `pytest`.

## Recomendación Clara
**Ejecutar la Migración a AsyncOpenAI.** Jericó es el sistema central; un cuello de botella artificial en I/O destruye el propósito de usar FastAPI. El esfuerzo técnico de migrar el cliente es moderado y garantiza escalabilidad horizontal.

## Plan por Fases
1.  Introducir `AsyncOpenAI` en paralelo a `LLMClient` (`AsyncLLMClient`).
2.  Modificar `/api/v1/ask` a `async def` inyectando el nuevo cliente.
3.  Actualizar la suite de pruebas (uso de `@pytest.mark.asyncio`).
4.  Deprecar y eliminar el cliente síncrono antiguo.

---

### Decisiones que necesito del CTO
- [ ] ¿Aprueba la transición a `AsyncOpenAI` en el `LLMClient` y el endpoint `/api/v1/ask` de manera inmediata para este sprint?
