---
tipo: tareas
proyecto: Jericó — Kaisen AI
estado: en curso
creado: "13/10/2026 10:22"
modificado: "13/10/2026 10:22"
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

---
> 🕒 **Última modificación:** 13/10/2026 10:22 (Claude Code · Opus 5.5)
