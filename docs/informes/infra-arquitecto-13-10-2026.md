---
tipo: informe
proyecto: Jericó — Kaisen AI
autor: infra-arquitecto (Claude Code · Opus 5.5)
creado: "13/10/2026 10:35"
modificado: "13/10/2026 10:36"
---

# Informe infra-arquitecto: 13/10/2026

**Encargo:** el orquestador, con autorización del CTO, pidió endurecer la operación de Jericó CRM en `kaisen-server`.
**Rama:** `infra/servidor-produccion`, trabajada en un worktree aparte (`~/Kaisen_AI/01_Proyectos/worktrees/Proyecto_Jerico/infra-servidor-produccion`) para no tocar la rama de crm-director. Los commits son locales, con la identidad de empresa y **sin push**.

## Entregado (spec 002: `specs/002-servidor-kaisen/`)

| Entregable | Archivos | Estado |
|---|---|---|
| a) Backup cifrado de `jerico_crm_data` con retención y prueba de restauración | `scripts/servidor/{crm_volume.py,backup_crm.sh,restore_crm.sh,lib.sh}`, `deploy/servidor/backup-crm.env.example` | hecho, con tests |
| b) Alerta si falla el healthcheck: Telegram, y correo SMTP si Telegram falla | `scripts/servidor/{healthwatch_crm.sh,notify_cto.sh}`, `deploy/servidor/crontab.example` | hecho, con tests |
| c) Runbook: actualizar versión, rotar el token, rollback y logs | `docs/despliegue-servidor-kaisen.md`, `deploy/servidor/docker-compose.servidor.yml` (rotación de logs) | hecho |
| d) Plan de migración a OCI con lo que ya está creado | `docs/migracion-oci.md` | hecho |

- **SDD:** spec, plan y tareas están en `specs/002-servidor-kaisen/`. plan-gemini hizo la investigación (`research.md`) por contrato con herdr; la revisé por muestreo y no volví a abrir sus URL. La implementación siguió TDD: los tests se escribieron primero y fallaron en rojo antes de implementar.
- **Revisión (reviewer):** la ronda 1 dio CAMBIOS NECESARIOS, con 8 defectos (4 de severidad media y 4 de severidad baja), y los corregí todos. **La ronda 2 dio APROBADO:** los 8 defectos están corregidos y no hay regresiones. El reviewer avisa de que la spec sigue en BORRADOR y que los cambios en SRV-06, SRV-08 y SRV-11 los tiene que aprobar el CTO.
- **Verificado en la laptop:**
  - `./scripts/verify.sh`: 1581 tests pasan, 37 de ellos nuevos.
  - `pre-commit`: en verde.
  - `scripts/oci/lint.sh`: ShellCheck 0.11.0 sin hallazgos en 15 scripts.
  - El recorrido backup → verify funcionó con el `age` real.
  - `docker compose config` mezcla bien el override de logs.

## Sin verificar (dicho con claridad)

- **No se probó nada contra Docker real.** Esta sesión no tiene permiso sobre el socket de Docker sin sudo, y no lo usé. En los tests, `docker` es un sustituto falso; el código Python sí corre de verdad contra una base SQLite en WAL.
  - El paso 0 y el §1 del runbook son la primera prueba real, en el servidor y en manos del CTO.
  - Queda por confirmar que `python -c` funcione dentro de la imagen, que el usuario `jerico` pueda escribir en el volumen y que la restauración llegue a `healthy`.
- **No se ejecutó nada en `kaisen-server` ni en OCI.** No leí `docker logs jerico-crm`, porque no hizo falta.
- **Supuestos que el paso 0 tiene que confirmar:**
  - que `~/jerico` tiene `docker-compose.yml` y `.env`;
  - que `scripts/servidor/` todavía **no** está en el servidor (habrá que copiarlo con `sync_repo_to_vps.sh`, como indica el runbook en §2.1);
  - que cron arranca en WSL2;
  - si el vigía de Hermes reinicia `jerico-crm` (puede interferir con una restauración).

## Para el CTO (decisiones)

1. **Aprobar la rama** y decidir cuándo integrarla en `main`.
2. **Ejecutar en el servidor el runbook**: paso 0 (solo lectura) y luego §1. Eso incluye pegar la llave age **pública**, hacer el primer backup, la prueba de restauración en la laptop, la prueba del aviso y el cron.
3. **Backups fuera del servidor:** hoy quedan en el mismo disco. La copia a la laptop (runbook §1.3) mitiga el riesgo a mano. La solución automática (bucket OCI o el backup interno de la app con rclone) queda pendiente de tu decisión.

---
> 🕒 **Última modificación:** 13/10/2026 10:36 (Claude Code · Opus 5.5)
