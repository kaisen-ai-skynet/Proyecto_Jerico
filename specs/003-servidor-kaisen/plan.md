---
tipo: plan
proyecto: Jericó — Kaisen AI
estado: borrador para aprobación del CTO
creado: "13/10/2026 10:22"
modificado: "13/10/2026 22:00"
---

# Plan 003 — Endurecer la operación en kaisen-server

Este plan implementa `spec.md` (SRV-01 a SRV-19). La investigación de apoyo está en `research.md`, que entrega plan-gemini.

## Diseño

```
scripts/servidor/
  crm_volume.py        # Python estándar (sin dependencias): pack | unpack | verify
  notify_cto.sh        # aviso al CTO: Telegram → correo SMTP (SRV-14, 15)
  backup_crm.sh        # SRV-01..09
  restore_crm.sh       # verify | apply (SRV-10, 11)
  healthwatch_crm.sh   # SRV-12, 13
deploy/servidor/
  backup-crm.env.example
  crontab.example
  docker-compose.servidor.yml   # rotación de logs (SRV-18)
tests/test_servidor_scripts.py  # pytest con docker/age/curl falsos
```

- **Una sola pieza de Python para tocar el volumen (`crm_volume.py`).** El script se pasa como `python -c "$(cat crm_volume.py)"` a un intérprete:
  - Con el contenedor vivo: `docker exec jerico-crm python -c … pack /app/crm-data`.
  - Con el contenedor parado: `docker run --rm -i -v jerico_crm_data:/data <imagen> python -c … unpack /data` (el tar entra por stdin).

  No hace falta copiar nada a la imagen ni que tenga `sqlite3` o `tar`; la imagen trae `python:3.12-slim`. El modo `pack` funciona así:
  1. Hace la instantánea con `sqlite3.Connection.backup` (SRV-01) en un directorio temporal del contenedor y la comprueba con `integrity_check`.
  2. Escribe el tar en stdout, en modo stream `w|`, sin dejar ningún archivo en el host.
  3. Al terminar borra el temporal en un `finally` (SRV-04).

  `unpack` usa `tarfile` con `filter="data"`, que impide rutas absolutas y `..`. `verify` corre en la laptop.
- **El cifrado ocurre en el host** con `age -R <destinatarios>`: el tar llega por una tubería y lo cifrado se escribe en `*.partial`. Después se comprueba la cabecera y se renombra de forma atómica (SRV-04 y SRV-05).
- **Los secretos solo los lee `notify_cto.sh`:** interpreta `CLAVE=valor` del `.env` del despliegue y pasa el token a curl por `-K -` (stdin), así que no queda en `argv` (SRV-15).
- **Los tiempos se pueden inyectar:** `NOW_EPOCH` sirve para los tests de `healthwatch_crm.sh`.
- **Cron y no systemd,** porque así funciona el servidor (WSL2, con el vigía en cron). Las líneas están en `deploy/servidor/crontab.example`.
- **El lint** amplía `scripts/oci/lint.sh` para incluir `scripts/servidor/*.sh`.

## Pruebas (TDD)

- **Herramientas falsas en un `bin/` temporal que va primero en el `PATH`:**
  - `docker`: `inspect`, `exec -i … python -`, `run --rm -i -v …`, `stop` y `start`. Corre `crm_volume.py` con el Python local sobre un directorio que hace de volumen.
  - `age`: cabecera `age-encryption.org/v1` + contenido, y el proceso inverso.
  - `curl`: registra los argumentos y el stdin, y se le puede ordenar que falle.
- **Base real:** SQLite en WAL creada en el test, con `crm_meta` y `crm_leads`.
- Si el `age` real está instalado, un test extra hace el recorrido completo con él.

## Riesgos

- El *patrón* de nombres y la retención se calculan con la fecha del nombre, no con la `mtime`, igual que en `backup.py`.
- `filter="data"` (PEP 706) existe en Python 3.12+ y en los parches 3.10.12+/3.11.4+. La imagen (3.12) y la laptop lo cumplen; en el servidor se comprueba en el paso 0. Si falta, `crm_volume.py` se detiene con un mensaje claro.

---
> 🕒 **Última modificación:** 13/10/2026 22:00 (Claude Code · Opus 5.5)
