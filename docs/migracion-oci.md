---
tipo: plan-de-migracion
proyecto: Jericó — Kaisen AI
estado: futuro (sin fecha; depende de la capacidad A1)
creado: "13/10/2026 10:26"
modificado: "13/10/2026 22:00"
---

# Plan de migración de Jericó CRM: kaisen-server → OCI (A1 Always Free)

**Hoy:** el CRM corre en `kaisen-server` (`docs/despliegue-servidor-kaisen.md`). La VM de OCI no se pudo crear: no había capacidad A1 en Bogotá ni por consola (2/12 y 1/6) ni con el reintento en Cloud Shell (cortado en el intento 153/200, el 13/10/2026). Este plan reutiliza lo que ya existe en OCI y se ejecuta cuando la VM esté `RUNNING`.
**Quién ejecuta:** el CTO, o el orquestador con su OK para la consola. Ningún agente ejecuta este plan.

## 1. Lo que ya existe en OCI (creado el 13/10/2026; se conserva)

| Recurso | Estado | Costo | Qué revisar antes de migrar |
|---|---|---|---|
| Presupuesto `kaisen-alerta-1usd` (raíz, 1 USD/mes, alerta al 1 %) | creado | 🆓 | Que el correo de alerta siga llegando a `kaisen.ai.santiago.cto@gmail.com` |
| Compartment `kaisen-jerico` | creado | 🆓 | — |
| VCN `jerico-vcn` (`10.0.0.0/16`, pública `10.0.0.0/24`, privada `10.0.1.0/24`) | creada | ✅ AF | — |
| Security List: TCP 22 solo desde la `/32` del CTO; ICMP del wizard; nada en 5432/6379/8000 | ajustada | 🆓 | **La IP pública del CTO cambia**: actualiza la regla 22 antes de crear la VM (`curl -4 ifconfig.me`) |
| UDP 41641 (Tailscale directo) | no creada (opcional) | 🆓 | Sin ella, Tailscale funciona por DERP |
| VM `jerico-core-oracle-01` | **sin crear** | ✅ AF si es A1 ≤ 2/12 | Valores en `docs/oci-valores-dia1.md` §3 |
| Bucket `jerico-backups` | sin crear | ✅ AF (20 GB) | `docs/oci-valores-dia1.md` §4 |

> **Fin de la prueba (~20/10/2026):** después de esa fecha solo sobrevive lo Always Free. Todo lo de la tabla lo es. Revisa que la consola muestre la cuenta como *Always Free* y que el costo sea 0. **No pulses "Upgrade".**

## 2. Requisitos previos

- [ ] **Capacidad A1.** Relanza `scripts/oci/00_retry_launch_a1.sh` en Cloud Shell con los mismos `export` de `docs/dia-1-oci.md` (bloque 3). Las madrugadas y los fines de semana suelen tener más capacidad. Se acepta 1 OCPU / 6 GB (`OCPUS=1 MEMORY_GB=6`): al CRM le basta, porque en el servidor está limitado a 0,5 CPU y 512 MB.
- [ ] **Día 1 completo hasta el bloque 4** (`docs/dia-1-oci.md`): `01_bootstrap.sh`, Tailscale (`jerico-oracle`) y `ssh santiago@jerico-oracle` por Tailscale.
- [ ] **Riesgo de que Oracle reclame la VM por inactividad:** Oracle puede reclamar las instancias Always Free que pasan 7 días con muy poco uso de CPU, red y memoria. Un CRM con poco tráfico podría entrar en ese criterio. **[VERIFICAR]** los umbrales actuales en la página oficial *Always Free Resources* antes de migrar, y decide si basta con lo que hace el CRM.
- [ ] **Ventana de corte avisada** al equipo de ventas (unos 30 min sin bot).

## 3. Preparación en la VM (sin corte; el servidor sigue atendiendo)

```bash
# laptop
scripts/oci/sync_repo_to_vps.sh santiago@jerico-oracle                  # repo → /opt/jerico/app
# .env: lo copia el CTO de servidor a VM sin pasar por la laptop ni por un chat
scp -3 kaisen-server:jerico/.env santiago@jerico-oracle:/opt/jerico/app/.env
ssh santiago@jerico-oracle 'chmod 600 /opt/jerico/app/.env'
```
```bash
# VM (santiago)
cd /opt/jerico/app
docker compose -p jerico build jerico-crm           # build NATIVO arm64 (python:3.12-slim es multi-arch)
docker compose -p jerico -f docker-compose.yml -f deploy/servidor/docker-compose.servidor.yml create jerico-crm
#   crea el contenedor y el volumen jerico_crm_data SIN arrancar el bot (no puede hacer polling en dos sitios)
docker image inspect jerico-crm:0.2.0 -f '{{.Architecture}}'   # arm64
```
- La imagen **no** se copia desde el servidor (x86_64): en ARM daría `exec format error`. Ver `specs/003-servidor-kaisen/research.md` §7.
- La base SQLite **sí** es portable entre arquitecturas: el backup del servidor se restaura tal cual.
- Configura en la VM `~/.config/jerico/backup-crm.env` y `backup-recipients.txt`, como en el runbook §1, con estas rutas: `ENV_FILE=/opt/jerico/app/.env` y `BACKUP_DIR=/opt/jerico/backups/crm`.

## 4. Corte

| # | Dónde | Paso | Comprobación |
|---|---|---|---|
| 1 | servidor | Comenta en `crontab -e` las dos líneas de Jericó (así el vigía no avisa de la parada) | `crontab -l \| grep jerico` muestra `#` |
| 2 | servidor | `jcs stop jerico-crm` | `docker inspect -f '{{.State.Status}}' jerico-crm` → `exited` |
| 3 | servidor | `ALLOW_STOPPED=1 ~/jerico/scripts/servidor/backup_crm.sh`: backup final sin escrituras en curso | aparece un `crm-*.tar.age` nuevo |
| 4 | laptop | Con `umask 077`: `scp` del backup a `~/jerico-backups-copia` (700), `restore_crm.sh verify ...` (anota los leads y archivos) y `age -d ... -o restaurar.tar` | `RESTAURACIÓN VERIFICADA` |
| 5 | laptop | `ssh santiago@jerico-oracle 'install -d -m 700 ~/jerico-restaurar'`, `scp -p restaurar.tar santiago@jerico-oracle:jerico-restaurar/` y `shred -u restaurar.tar` | — |
| 6 | VM | `SKIP_PRE_RESTORE=1 CONFIRM=1 /opt/jerico/app/scripts/servidor/restore_crm.sh apply ~/jerico-restaurar/restaurar.tar` y después `shred -u ~/jerico-restaurar/restaurar.tar` | termina con `healthy` |
| 7 | VM | `docker logs --tail 25 jerico-crm`; escribe al bot | responde; los leads coinciden con el paso 4 |
| 8 | VM | Instala el cron de backup y del vigía (`deploy/servidor/crontab.example` con las rutas de `/opt/jerico/app`) y prueba `notify_cto.sh` | llega el aviso |

> En el paso 6, `SKIP_PRE_RESTORE=1` solo es correcto porque el volumen de la VM está recién creado y vacío.

## 5. Rollback (si el paso 6 o el 7 fallan)

1. VM: `docker compose -p jerico stop jerico-crm`, para que el bot no haga *polling* en dos sitios.
2. Servidor: `jcs start jerico-crm` y descomenta las líneas del cron.
3. El servidor vuelve al estado exacto del paso 2, porque su volumen no se tocó. Si la VM llegó a atender, lo que se escribió allí se recupera con un backup de la VM restaurado en el servidor (runbook §4.2).

## 6. Después del corte

- **Durante 14 días** no se borra nada en el servidor: ni el volumen `jerico_crm_data`, ni la imagen, ni los backups. Es el rollback. Pasado ese plazo, con el OK del CTO: `jcs down` (sin `-v`), luego `docker volume rm jerico_crm_data` y borrar los backups que ya estén copiados fuera.
- **Backups fuera de la VM:** crea el bucket `jerico-backups` (Parte H de la guía). Hay dos caminos:
  - activar el backup interno de la app (`JERICO_CRM_BACKUP_AGE_RECIPIENT` y `JERICO_CRM_BACKUP_REMOTE` con rclone);
  - copiar con rclone los `crm-*.tar.age` de `backup_crm.sh`.

  La decisión es del CTO. Ninguno de los dos guarda secretos en el repo.
- **Cierre perimetral:** `04_lockdown.sh` desde la sesión Tailscale, **borrar la regla TCP 22** de la Security List y correr `verify_vps.sh` → `RESULTADO: OK`.
- **Costo:** que el presupuesto siga en 0 y que la VM muestre *Always Free-eligible*. Revísalo la semana siguiente al ~20/10/2026.
- Actualiza `docs/despliegue-servidor-kaisen.md` (servidor → VM) y la nota de Jericó en la bóveda.

---
> 🕒 **Última modificación:** 13/10/2026 22:00 (Claude Code · Opus 5.5)
