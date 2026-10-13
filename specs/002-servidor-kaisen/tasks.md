---
tipo: tareas
proyecto: Jericó — Kaisen AI
estado: completas T01–T09 (revisión APROBADO en la ronda 2); falta la aprobación del CTO
creado: "13/10/2026 10:22"
modificado: "13/10/2026 10:36"
---

# Tareas 002

| # | Tarea | Requisitos | Verificación |
|---|---|---|---|
| T01 | `crm_volume.py` (pack/unpack/verify) con sus tests primero | SRV-01, 02, 04, 10 | pytest |
| T02 | `notify_cto.sh` (Telegram → SMTP, `.env` sin `source`, token por stdin) con tests | SRV-14, 15 | pytest |
| T03 | `backup_crm.sh` + `backup-crm.env.example` con tests | SRV-03..09 | pytest |
| T04 | `restore_crm.sh` verify/apply con tests | SRV-10, 11 | pytest |
| T05 | `healthwatch_crm.sh` con tests (transiciones, recordatorio, gracia de *starting*) | SRV-12, 13 | pytest |
| T06 | `crontab.example`, `docker-compose.servidor.yml` y lint ampliado | SRV-18 | `lint.sh`, `docker compose config` si hay Docker |
| T07 | Runbook `docs/despliegue-servidor-kaisen.md` | SRV-17 | revisión |
| T08 | Plan `docs/migracion-oci.md` | SRV-19 | revisión |
| T09 | Revisión requisito por requisito (reviewer) e informe | todos | veredicto |

## Estado

- T01–T08 hechas, con 37 tests en `tests/test_servidor_scripts.py`.
- **T09, ronda 1 (reviewer):** CAMBIOS NECESARIOS, con 8 defectos. Los 8 se corrigieron:
  1. `pack-raw` para la copia pre-restore.
  2. El `.tar` en claro va a directorios 700 con `umask 077`.
  3. Retención de `pre-restore-*` y de las copias de la laptop.
  4. Tests de los caminos de fallo de `apply`.
  5. Pausa del cron durante la restauración.
  6. `trap ERR` y comprobación de que Docker responde.
  7. Arreglos en el runbook (§1.6, §4.1, `install -d`).
  8. `env_get` con comentarios en línea.
- **T09, ronda 2 (reviewer):** APROBADO. Los 8 defectos están corregidos, sin regresiones y con 37 tests.
- **Pendiente:** que el CTO apruebe la spec (en BORRADOR, con SRV-06, 08 y 11 ajustados tras la revisión) y la ejecute en el servidor.
- **No verificado:** nada de esto se ha probado contra Docker real, porque esta laptop no tiene acceso al socket sin sudo. Se verifica en el servidor con el paso 0 y el §1 del runbook.

---
> 🕒 **Última modificación:** 13/10/2026 10:36 (Claude Code · Opus 5.5)
