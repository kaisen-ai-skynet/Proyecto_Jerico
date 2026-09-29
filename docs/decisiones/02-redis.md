# Dossier 02: Implementación de Redis

## Estado Real
Jericó gestiona la memoria a corto plazo de sesiones (`MemoryManager`) y el control de tasa (`RateLimiter`) a través de estructuras nativas de Python (diccionarios en memoria RAM) dentro del mismo proceso. Esto no escala si se escalan los workers de Uvicorn/Gunicorn a más de una instancia, pues cada worker tendría su propia memoria y rate limiter independiente.

## Opciones y Casos de Uso (Para qué Redis)
1.  **Rate Limiting Global:** Evita abusos de la API independientemente de qué worker atienda la petición.
2.  **Memoria de Corto Plazo / Caché Compartido:** Mantiene las sesiones (`session_id`) sincronizadas entre nodos/workers.
3.  **Colas (Futuro):** Para tareas en background (ej. STT, transcripción asíncrona pesada) mediante Celery/ARQ.

*Alternativas a Redis Local/Self-hosted:*
*   Seguir en RAM local (MVP de un solo worker).
*   PostgreSQL / SQLite para memoria, pero sufren en performance de read/write para Rate Limiting.
*   Managed Redis (ej. Upstash o ElastiCache) que tiene costo por mes y mayor latencia externa.

## Riesgos y Costos
*   **Costos:** Redis local (contenedor) no tiene costo adicional más allá del RAM consumido en el VPS (estimado <100MB).
*   **Esfuerzo:** Medio-Bajo. Supone inyectar `redis-py` (o `redis.asyncio`) en `RateLimiter` y `MemoryManager`. Requiere actualizar el `docker-compose.yml` base para levantar el servicio.
*   **Riesgos:** Agrega una dependencia crítica al _startup_. Si Redis falla, las peticiones pueden bloquearse si no se establecen timeouts adecuados.

## Recomendación Clara
**Adoptar Redis (Contenedor Local) desde ahora.** El costo de RAM es marginal y previene comportamientos erráticos de sesión al escalar los workers en el futuro cercano.

## Pasos de Implementación
1.  Añadir dependencia `redis` a `pyproject.toml`.
2.  Desarrollar adaptadores para `RateLimiter` y `MemoryManager` (`RedisMemoryManager`).
3.  Modificar configuración para habilitar Redis si la URL `JERICO_REDIS_URL` está presente, cayendo graciosamente a memoria RAM local si falla.

---

### Decisiones que necesito del CTO
- [ ] ¿Aprueba la adopción de Redis para persistencia de contexto volátil y Rate Limiting?
- [ ] ¿Aprobamos que el despliegue inicial sea un contenedor Redis local (en `docker-compose.yml`) en lugar de un servicio cloud administrado (para evitar costos iniciales)?
