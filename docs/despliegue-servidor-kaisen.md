---
tipo: runbook
proyecto: Jericó — Kaisen AI
estado: listo para aprobación del CTO (nada ejecutado en el servidor)
creado: "13/10/2026 10:25"
modificado: "13/10/2026 10:25"
---

# Runbook — Jericó CRM en kaisen-server

**Servidor:** `kaisen-server` (`DESKTOP-8F1B898`, Ubuntu sobre WSL2, Tailscale `100.79.169.121`), usuario `kaisenai`.
**Despliegue:** `~/jerico`, proyecto compose `jerico`, solo el servicio `jerico-crm`, con el volumen `jerico_crm_data`.
**Spec:** `specs/002-servidor-kaisen/`. **Quién ejecuta:** el CTO, con cada paso aprobado. Ningún agente ejecuta este runbook en el servidor.

> Desde la laptop se entra con `ssh kaisen-server` (alias de la guía de la bóveda *Guia_Despliegue_SSH_Servidor*). Si no tienes el alias, usa `ssh kaisenai@100.79.169.121`.
> En el servidor, todos los comandos `docker compose` usan este atajo (pégalo en cada sesión o añádelo a `~/.bashrc`):
> ```bash
> jcs() { (cd ~/jerico && docker compose -p jerico -f docker-compose.yml -f deploy/servidor/docker-compose.servidor.yml "$@"); }
> ```

## 0. Inspección (solo lectura, antes de todo)

Confirma los supuestos de la spec (§4) sin cambiar nada:

```bash
ssh kaisen-server
ls -la ~/jerico | head -n 20                    # docker-compose.yml, .env (600), ¿scripts/? ¿.deployed_rev?
cat ~/jerico/.deployed_rev 2>/dev/null          # revisión desplegada, si se usó sync_repo_to_vps.sh
stat -c '%a %U' ~/jerico/.env                   # debe ser 600 kaisenai
docker ps --filter name=jerico --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
docker inspect -f '{{.State.Status}} {{.State.Health.Status}}' jerico-crm   # running healthy
docker volume inspect jerico_crm_data -f '{{.Mountpoint}}'
docker image ls jerico-crm
crontab -l                                      # lo que ya hay: vigía de Hermes, Seguros Bolívar...
which age flock curl python3 || echo "falta algo"
python3 -c "import tarfile; tarfile.data_filter" && echo "python3 OK"   # filtro PEP 706
df -h ~ | tail -n 1
```

- [ ] `~/jerico` existe con `docker-compose.yml` y `.env` en 600. Si `scripts/servidor/` **no** está, primero haz el paso 2.1 (copiar el repo) **sin** reconstruir.
- [ ] `jerico-crm` está `running healthy`.
- [ ] Anotaste qué hay en `crontab -l`, porque lo vas a ampliar sin borrar nada.
- [ ] Si falta `age`: `sudo apt-get install -y age`.

> ⚠️ El vigía de Hermes (`~/hermes/vigia.py`) **reinicia contenedores caídos**. Si vigila `jerico-crm`, puede arrancarlo en mitad de una restauración (§4.2). Antes de restaurar, comprueba si lo incluye con `grep -n jerico ~/hermes/vigia.py`.

## 1. Instalar el backup y la alerta (una vez)

1. **Llave pública age:** usa la misma de la laptop (`~/.config/kaisen/jerico-backup.agekey`). En la laptop, `age-keygen -y ~/.config/kaisen/jerico-backup.agekey` imprime la línea `age1...`, que es **pública**. En el servidor:
   ```bash
   mkdir -p ~/.config/jerico ~/jerico-backups ~/.local/state/jerico && chmod 700 ~/.config/jerico ~/jerico-backups
   nano ~/.config/jerico/backup-recipients.txt     # pega SOLO la línea age1...
   cp ~/jerico/deploy/servidor/backup-crm.env.example ~/.config/jerico/backup-crm.env && chmod 600 ~/.config/jerico/backup-crm.env
   ```
   Nunca copies al servidor la llave privada (`AGE-SECRET-KEY-...`). El script se niega a correr si la encuentra.
2. **Primer backup a mano:**
   ```bash
   ~/jerico/scripts/servidor/backup_crm.sh
   ls -l ~/jerico-backups/crm/                     # crm-AAAAMMDDTHHMMSSZ.tar.age, -rw-------
   ```
3. **Prueba de restauración** (en la laptop, que es donde está la llave privada; hazla también una vez al mes):
   ```bash
   cd ~/Kaisen_AI/01_Proyectos/Proyecto_Jerico
   f=$(ssh kaisen-server 'ls -1 ~/jerico-backups/crm/crm-*.tar.age | tail -n 1')
   mkdir -p ~/jerico-backups-copia && scp "kaisen-server:$f" ~/jerico-backups-copia/
   scripts/servidor/restore_crm.sh verify ~/jerico-backups-copia/"$(basename "$f")" ~/.config/kaisen/jerico-backup.agekey
   ```
   Debe terminar con `RESTAURACIÓN VERIFICADA` y mostrar `integrity_check: ok`, `schema_version`, el número de leads y el de archivos. De paso, la copia queda **fuera del servidor**.
4. **Prueba de la alerta** (manda un mensaje real al CTO):
   ```bash
   ~/jerico/scripts/servidor/notify_cto.sh "Prueba de aviso de Jericó CRM desde kaisen-server"
   ```
   Te tiene que llegar por Telegram. Si el bot no responde, el script prueba el correo SMTP del `.env`, si está configurado.
5. **Cron:** añade las líneas de `deploy/servidor/crontab.example` **sin borrar** las que ya hay (las instrucciones están en la cabecera del archivo). Comprueba con `crontab -l | tail -n 6`.
   - Backup diario a las 03:45; log en `~/jerico-backups/backup-crm.log`.
   - Vigía cada 5 min; log en `~/.local/state/jerico/healthwatch.log`.
   - cron en WSL2: si el servidor se reinicia, cron tiene que arrancar solo. El vigía de Hermes ya usa cron, así que hoy funciona. Si algún día deja de correr: `sudo service cron status`, y lee `research.md` §5 (`systemd=true` o `[boot] command` en `/etc/wsl.conf`).
6. **Rotación de logs** (§5): la primera vez que uses `jcs up -d`, el contenedor se recrea con el límite de logs. Es un corte de unos segundos.

## 2. Actualizar la versión

> En `docker-compose.yml` la etiqueta de la imagen es fija (`jerico-crm:0.2.0`), así que cada build la **sobrescribe**. Por eso, antes de construir, se guarda la imagen actual como `jerico-crm:rollback`.

1. **Copiar el repo** (desde la laptop, rama y commit aprobados): copia `HEAD` con `git archive`. No toca `.env` y escribe `.deployed_rev`:
   ```bash
   cd ~/Kaisen_AI/01_Proyectos/Proyecto_Jerico && git status --short && git log --oneline -1
   REMOTE_DIR=/home/kaisenai/jerico scripts/oci/sync_repo_to_vps.sh kaisen-server
   ```
   Los archivos que se borraron en el repo **no** se borran en el servidor. Si hace falta, se limpian a mano.
2. **En el servidor:**
   ```bash
   ~/jerico/scripts/servidor/backup_crm.sh                       # backup justo antes del cambio
   docker tag jerico-crm:0.2.0 jerico-crm:rollback               # imagen actual → rollback
   jcs build jerico-crm
   jcs up -d jerico-crm
   ```
3. **Comprobar** (1–2 min):
   ```bash
   jcs ps jerico-crm                                             # (healthy)
   docker logs --tail 25 jerico-crm                              # sin Traceback ni ERROR
   ```
   Después escríbele algo al bot.
4. Si la nueva versión trae una **migración de esquema** (por ejemplo, v1 → v2 en `src/jerico/crm/migrate.py`), sigue las notas de crm-director para esa versión. **No hay migración hacia atrás**: si después hay que volver atrás, hace falta también el rollback de datos (§4.2), con el backup del paso 2.

## 3. Rotar el token del bot

Hazlo si el token se filtró, si alguien del equipo deja de tener acceso o como higiene periódica.

1. En Telegram, en **@BotFather**: `/mybots` → el bot → *API Token* → **Revoke current token**. El token viejo deja de funcionar al instante y el bot queda sin servicio hasta el paso 3.
2. En el servidor, edita **a mano** la línea `JERICO_CRM_TELEGRAM_BOT_TOKEN=` de `~/jerico/.env`:
   ```bash
   nano ~/jerico/.env && chmod 600 ~/jerico/.env
   ```
   El token no se pega en chats, tickets ni en el repo; se guarda solo en el gestor de contraseñas.
3. Recrea el contenedor. `env_file` solo se vuelve a leer al recrear, no basta con `restart`:
   ```bash
   jcs up -d --force-recreate jerico-crm
   jcs ps jerico-crm && docker logs --tail 25 jerico-crm
   ```
4. Comprueba que el bot responde y que la alerta usa el token nuevo. `notify_cto.sh` lo lee del mismo `.env`:
   ```bash
   ~/jerico/scripts/servidor/notify_cto.sh "Prueba tras rotar el token"
   ```
5. Si el bot corría también en otro sitio (por ejemplo, una prueba en la laptop), ese sitio queda sin servicio. Es lo esperado.

## 4. Rollback

### 4.1 Volver a la imagen anterior (sin tocar los datos)

```bash
docker image ls jerico-crm                                       # debe existir jerico-crm:rollback
docker tag jerico-crm:rollback jerico-crm:0.2.0
jcs up -d --no-build --force-recreate jerico-crm
jcs ps jerico-crm && docker logs --tail 25 jerico-crm
```
Sirve si la versión nueva **no** cambió el esquema. Si lo cambió, la imagen vieja puede fallar con la base nueva: aplica también el §4.2 con el backup de antes de actualizar.

### 4.2 Volver a un backup (datos)

1. Elige el backup, que debe ser anterior al problema: `ls -1 ~/jerico-backups/crm/`.
2. **Descifra en la laptop** (la llave privada no viaja al servidor) y sube el `.tar`:
   ```bash
   # laptop
   scp kaisen-server:jerico-backups/crm/crm-AAAAMMDDTHHMMSSZ.tar.age ~/jerico-backups-copia/
   age -d -i ~/.config/kaisen/jerico-backup.agekey -o ~/jerico-backups-copia/restaurar.tar ~/jerico-backups-copia/crm-AAAAMMDDTHHMMSSZ.tar.age
   scripts/servidor/restore_crm.sh verify ~/jerico-backups-copia/crm-AAAAMMDDTHHMMSSZ.tar.age ~/.config/kaisen/jerico-backup.agekey
   scp ~/jerico-backups-copia/restaurar.tar kaisen-server:/tmp/restaurar.tar
   ```
3. **En el servidor**, primero mira el plan (no cambia nada) y luego ejecútalo:
   ```bash
   ~/jerico/scripts/servidor/restore_crm.sh apply /tmp/restaurar.tar
   CONFIRM=1 ~/jerico/scripts/servidor/restore_crm.sh apply /tmp/restaurar.tar
   shred -u /tmp/restaurar.tar                                   # el .tar está en claro: bórralo ya
   ```
   El script verifica el archivo y luego:
   1. detiene `jerico-crm`;
   2. guarda lo que había en `~/jerico-backups/crm/pre-restore-*.tar.age` (cifrado);
   3. reemplaza el volumen;
   4. arranca el contenedor y espera a que esté `healthy`.

   Si te equivocaste de backup, la copia `pre-restore-*` se restaura igual.
4. **Borra la copia en claro de la laptop:** `shred -u ~/jerico-backups-copia/restaurar.tar`.

> Lo que pasó entre el backup y la restauración (leads, notas, mensajes) **se pierde**. Avisa al equipo de ventas antes de restaurar.

## 5. Logs

```bash
docker logs --tail 50 jerico-crm                     # últimas líneas
docker logs --since 30m jerico-crm | tail -n 50      # última media hora
docker logs -f jerico-crm                            # en vivo (Ctrl+C para salir)
tail -n 20 ~/jerico-backups/backup-crm.log           # backups
tail -n 20 ~/.local/state/jerico/healthwatch.log     # avisos del vigía
cat ~/.local/state/jerico/healthwatch.state          # estado del vigía (status/since/alerted)
```
- **Rotación:** con `deploy/servidor/docker-compose.servidor.yml` (el atajo `jcs` lo incluye), Docker guarda como máximo 3 archivos de 10 MB. Compruébalo con `docker inspect -f '{{.HostConfig.LogConfig}}' jerico-crm`, que debe mostrar `max-size:10m`.
- Los logs pueden tener datos personales de los leads: no los pegues en chats ni en tickets sin recortarlos.

## 6. Llegó una alerta

| Aviso | Qué hacer |
|---|---|
| 🔴 `estado: running unhealthy` | `docker logs --tail 50 jerico-crm`. El healthcheck mira que `heartbeat` tenga menos de 120 s: si falla, el bucle del bot está colgado o caído. Si el log no muestra la causa: `jcs restart jerico-crm`. |
| 🔴 `estado: exited ...` / `restarting` | `docker logs --tail 50 jerico-crm`. Si sale con código 2, falta configuración (token o clave en `.env`). Corrige y `jcs up -d jerico-crm`. |
| 🔴 `el contenedor no existe` | Alguien lo borró o se hizo un `down`. Hay que levantarlo con `jcs up -d jerico-crm`; el volumen sigue intacto. |
| 🔴 `lleva N min arrancando` | Igual que *unhealthy*. Revisa también el disco (`df -h ~`) y la memoria (`docker stats --no-stream jerico-crm`; el tope es 512 MB). |
| 🔴 `falló el backup` | `tail -n 20 ~/jerico-backups/backup-crm.log`. Si el contenedor estaba caído, se arregla primero eso y luego `backup_crm.sh` a mano. |
| 🟢 `recuperado tras N min` | Nada urgente. Anota la causa si la sabes. |

Si no llega ningún aviso pero sospechas un problema: `cat ~/.local/state/jerico/healthwatch.state` y `crontab -l`.

---
> 🕒 **Última modificación:** 13/10/2026 10:25 (Claude Code · Opus 5.5)
