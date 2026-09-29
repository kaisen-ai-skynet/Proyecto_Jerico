# Dossier 03: Despliegue en VPS Oracle

## Estado Real
El proyecto cuenta con un script de preparación de infraestructura en `scripts/bootstrap_vps_oracle.sh`, pero aún no se ha formalizado la arquitectura de despliegue sobre el VPS para el ambiente operativo de la API. 

## Arquitectura Objetivo
El modelo recomendado se basa en un esquema de **Contenedorización (Docker Compose)**.
*   **Servicios:** La API de Jericó (`app`) y, si se aprueba, un contenedor `redis` auxiliar.
*   **Red / Exposición:** La aplicación **NO** debe exponerse a internet público directamente (no bind a `0.0.0.0`). Según el reporte P-01 (Auditoría de Claude), el puerto de la aplicación debe estar expuesto exclusivamente en `127.0.0.1` o estar restringido dentro de la VPN de **Tailscale**.
*   **Acceso:** Todo acceso externo debe ser intermediado a través de Tailscale, Cloudflare Tunnels o un Reverse Proxy autenticado interno.

## Checklist de Seguridad y Rollback
1.  **Red Privada:** Bind de Uvicorn/Docker a `127.0.0.1:8000`.
2.  **Secretos:** El `.env` debe generarse desde un sistema de secretos seguro; no copiarlo manualmente ni commitearlo en texto plano. Validar `JERICO_API_TOKEN` obligatorio.
3.  **Monitoreo:** Captura de logs JSONL de peticiones y auditoría.
4.  **Rollback:** Mantener imágenes versionadas (`:v0.2.0`, `:v0.2.1`). Un rollback de emergencia se ejecuta con `git checkout tags/vX` y un `docker compose up -d` de la versión previa.

## Riesgos y Esfuerzo
*   **Esfuerzo:** Bajo-Medio. Requiere refinar `docker-compose.yml`, configurar variables en el host remoto y lanzar el script de bootstrap.
*   **Riesgos:** La exposición accidental del puerto 8000 a internet (por sobre-escritura de iptables de Docker). Se mitiga amarrando explícitamente el puerto a `127.0.0.1` en `docker-compose.yml` (ej. `127.0.0.1:8000:8000`).

## Recomendación Clara
Desplegar utilizando `docker compose` con restricción estricta al `127.0.0.1`. El tráfico hacia el frontend (o los clientes CLI remotos) deberá circular usando la red encriptada de Tailscale para mantener latencia baja y seguridad total perimetral (Zero Trust).

---

### Decisiones que necesito del CTO
- [ ] ¿Aprueba el modelo Docker Compose como estándar para el VPS Oracle (incluyendo los binds limitados a `127.0.0.1`/Tailscale IP)?
- [ ] ¿Autoriza la ejecución del script `bootstrap_vps_oracle.sh` en la infraestructura de producción durante la próxima ventana operativa?

### Estado 29/09/2026: APROBADO por el CTO. Etapa actual: guía ejecutable lista en docs/despliegue-vps.md; pendiente ventana operativa.
