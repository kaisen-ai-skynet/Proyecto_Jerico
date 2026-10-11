# Despliegue de Jericó en VPS Oracle

Runbook para desplegar la API con Docker Compose, AsyncOpenAI y Redis en la red privada del VPS. Se asume que la revisión desplegada incluye el servicio Compose `redis` y configura `JERICO_REDIS_URL=redis://redis:6379/0`; Redis no debe publicar un puerto en el host.

## Requisitos previos

- VPS preparado con Docker Engine y el plugin Docker Compose. `scripts/oci/01_bootstrap.sh` es una preparación de infraestructura de una sola vez, no forma parte de cada despliegue.
- Acceso al VPS por SSH/Tailscale y una revisión o tag aprobado del repositorio.
- Secretos configurados en `.env` mediante el mecanismo seguro del equipo. No subir `.env` al repositorio ni incluir valores secretos en comandos guardados en el historial.
- `JERICO_API_TOKEN` fuerte y credenciales/endpoint del proveedor LLM válidos para las solicitudes que usan AsyncOpenAI. Las solicitudes locales L0 no requieren una llamada al proveedor.

## Despliegue o actualización

Desde el directorio de la revisión aprobada en el VPS:

```bash
git fetch --tags
git checkout <tag-aprobado>
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

Mantén la publicación de la API restringida a `127.0.0.1:8000:8000`, como en `docker-compose.yml`. Para acceso desde Tailscale, enlaza el puerto a la IP Tailscale concreta del host y limita el tráfico con las reglas de firewall; no uses `8000:8000` ni `0.0.0.0`. Redis solo debe ser accesible por la red interna de Compose.

## Verificación posterior

Ejecuta los controles en este orden:

```bash
curl --fail --silent --show-error http://127.0.0.1:8000/health
docker compose exec redis redis-cli ping
```

La API debe responder `status: ok` y Redis debe responder `PONG`. Después, desde el host del VPS, ejecuta `scripts/test_e2e.sh` con `JERICO_API_TOKEN` disponible en el entorno de la terminal mediante el gestor de secretos del equipo. La prueba envía una solicitud L0 autenticada al endpoint real y ejercita el recorrido de sesión/memoria. Un `200` por sí solo no demuestra que la aplicación esté usando Redis en vez del fallback en RAM; confirma además el `PONG` y que la suite de la revisión cubre la integración y el comportamiento ante fallback. Si falla cualquiera de estas comprobaciones, revisa `docker compose ps` y `docker compose logs --tail=100 jerico-core redis` antes de dar el despliegue por válido.

Antes de desplegar una revisión, ejecuta `bash scripts/verify.sh` en el entorno de desarrollo con `.venv` instalada. Ese control reúne Ruff, mypy y pytest; la suite debe pasar incluyendo las pruebas de la ruta asíncrona y del adaptador Redis de esa revisión.

La comprobación L0 no hace una llamada al proveedor LLM. Para probar AsyncOpenAI de extremo a extremo, realiza además una petición que enrute a L1/L2 solo en una ventana controlada, con credenciales de proveedor válidas, y confirma la respuesta y los logs. Esa prueba puede generar consumo/coste del proveedor; las pruebas automatizadas de la suite no deben depender de credenciales reales.

## Rollback

Vuelve a la última revisión aprobada y reconstruye los servicios:

```bash
git checkout <tag-anterior-aprobado>
docker compose up -d --build
docker compose ps
```

Repite las verificaciones de salud, Redis y E2E. Las sesiones de memoria son datos de corto plazo: considera que pueden perderse al reiniciar o cambiar la configuración de Redis, salvo que el servicio se haya configurado explícitamente con persistencia.

---
> 🕒 **Última modificación:** 11/10/2026 18:25 (Claude Code · Opus 5.5)
