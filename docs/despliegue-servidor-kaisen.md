---
tipo: runbook
proyecto: Jericó — Kaisen AI
estado: EJECUTADO en kaisen-server el 14/10/2026 (§1 sin el 1.6; §1.7 y §7 añadidos)
creado: "13/10/2026 10:25"
modificado: "14/10/2026 01:43"
---

# Runbook — Jericó CRM en kaisen-server

**Servidor:** `kaisen-server` (`DESKTOP-8F1B898`, Ubuntu sobre WSL2, Tailscale `100.79.169.121`), usuario `kaisenai`.
**Despliegue:** `~/jerico`, proyecto compose `jerico`, solo el servicio `jerico-crm`, con el volumen `jerico_crm_data`.
**Spec:** `specs/003-servidor-kaisen/`. **Quién ejecuta:** el CTO, con cada paso aprobado. Ningún agente ejecuta este runbook en el servidor.

> Desde la laptop se entra con `ssh kaisen-server` (alias de la guía de la bóveda *Guia_Despliegue_SSH_Servidor*). Si no tienes el alias, usa `ssh kaisenai@100.79.169.121`.
> En el servidor, todos los comandos `docker compose` usan este atajo (pégalo en cada sesión o añádelo a `~/.bashrc`):
> ```bash
> jcs() { (cd ~/jerico && docker compose -p jerico -f docker-compose.yml -f deploy/servidor/docker-compose.servidor.yml "$@"); }
> ```

## 0. Inspección (solo lectura, antes de todo)

> **Estado comprobado el 13/10/2026 a las 22:0x** (infra-arquitecto, solo lectura, contra el despliegue `d0aeab3`):
> - `~/jerico` **no** es un repo git: es una copia de archivos con `DEPLOYED_COMMIT` = `d0aeab3`.
> - `.env` está en 600 y existe una copia `.env.bak-20261013-2127`, también en 600.
> - `jerico-crm` está `running healthy` con la imagen `jerico-crm:0.2.0`. La anterior se guardó como `jerico-crm:prev-5f4cd5d`.
> - Los logs usan `json-file` **sin límite**.
> - `scripts/servidor/` **no está** en el servidor.
> - **`age` no está instalado.** `flock`, `curl` y Python con el filtro PEP 706 sí están.
> - El vigía de Hermes **no** menciona `jerico` (`grep -c jerico ~/hermes/vigia.py` = 0), así que no interfiere con una restauración.
> - Disco: 3 % usado.
>
> Repite la inspección justo antes de instalar, por si algo cambió.

```bash
ssh kaisen-server
cat ~/jerico/DEPLOYED_COMMIT                    # commit desplegado (hoy d0aeab3)
stat -c '%a %U' ~/jerico/.env                   # 600 kaisenai
docker inspect -f '{{.State.Status}} {{.State.Health.Status}} {{.Config.Image}}' jerico-crm   # running healthy jerico-crm:0.2.0
docker image ls jerico-crm                      # 0.2.0 y prev-<commit anterior>
ls ~/jerico/scripts/servidor 2>/dev/null || echo "faltan los scripts (paso 1.0)"
crontab -l                                      # lo que ya hay: vigía de Hermes, Seguros Bolívar, @reboot de oci-a1...
which age flock curl python3 || echo "falta algo"
python3 -c "import tarfile; tarfile.data_filter" && echo "python3 OK"   # filtro PEP 706
grep -c jerico ~/hermes/vigia.py                # 0 = el vigía de Hermes no toca jerico-crm
df -h ~ | tail -n 1
```

- [ ] `jerico-crm` está `running healthy` y `DEPLOYED_COMMIT` es el que esperas.
- [ ] Anotaste qué hay en `crontab -l`, porque lo vas a ampliar sin borrar nada.
- [ ] Si falta `age`, instálalo (necesita tu sudo): `sudo apt-get install -y age`.

## 1. Instalar el backup y la alerta (una vez)

0. **Copiar solo los scripts** desde la laptop, una vez aprobada la rama `infra/servidor-produccion`. Se copian **únicamente** `scripts/servidor` y `deploy/servidor`. No se sincroniza el repo completo: esta rama no contiene el código del CRM desplegado (`d0aeab3`), y sobrescribir `~/jerico` con ella dejaría el código fuente desfasado para el siguiente build.
   ```bash
   cd ~/Kaisen_AI/01_Proyectos/Proyecto_Jerico
   git archive infra/servidor-produccion scripts/servidor deploy/servidor | ssh kaisen-server 'tar -x -C ~/jerico'
   ssh kaisen-server 'ls ~/jerico/scripts/servidor ~/jerico/deploy/servidor'
   ```
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
   install -d -m 700 ~/jerico-backups-copia && scp "kaisen-server:$f" ~/jerico-backups-copia/
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
6. **Rotación de logs** (§5) — **pendiente**: el 14/10 no se aplicó porque obliga a recrear `jerico-crm` (lo hará crm-director en su próximo despliegue, usando `jcs`). Aplica el override. El contenedor se recrea con el límite de logs, lo que supone un corte de unos segundos:
   ```bash
   jcs up -d jerico-crm && jcs ps jerico-crm
   docker inspect -f '{{.HostConfig.LogConfig}}' jerico-crm      # {json-file map[max-file:3 max-size:10m]}
   ```

### 1.7 Copia fuera del servidor (OCI Object Storage, decidido con Jev)

- **Bucket:** `jerico-backups` en el compartment `kaisen-jerico`. Es privado (`NoPublicAccess`), Standard y sin versionado; entra en el Always Free de 20 GB. Lo creó la CLI `oci` del servidor (`~/.oci`, en 700/600).
- **Script:** `scripts/servidor/offsite_oci.sh`. Cuando acaba `backup_crm.sh`, sube los `crm-*.tar.age` que todavía no estén en el bucket, bajo el prefijo `crm/`. Solo sube archivos con cabecera age y borra del bucket los que tengan más de 30 días.
- **Cron:** la línea de las 03:45 encadena `backup_crm.sh && offsite_oci.sh`.
- **Comprobación:** `~/.local/bin/oci os object list --bucket-name jerico-backups --query "data[].name"`

## 7. DocuSeal (firma electrónica, spec 004)

- **Instalación:** `~/docuseal/docker-compose.yml`, copia de `deploy/docuseal/docker-compose.yml`. Imagen `docuseal/docuseal:3.3.2`, volumen `docuseal_data` (SQLite en `/data`), proyecto compose `docuseal`, **aparte de jerico**.
- **Red:** el puerto se publica **solo en `127.0.0.1:3010`**. Además está en `jerico_net`, así que el CRM lo ve en `http://docuseal:3000`.
- **Acceso del CTO:**
  ```bash
  ssh -L 3010:127.0.0.1:3010 kaisen-server
  ```
  Luego abre `http://127.0.0.1:3010`. El usuario y la contraseña están en `~/docuseal/admin-credentials.txt` (600): pásalos a tu gestor de contraseñas y borra el archivo con `shred -u`.
- **Variables en `~/jerico/.env`:** `JERICO_CRM_DOCUSEAL_URL=http://docuseal:3000` y `JERICO_CRM_DOCUSEAL_TOKEN`, que es el token de API del usuario admin. El CRM solo las lee al **recrear** `jerico-crm`; eso lo hace crm-director cuando despliegue la spec 004.
- **Limitación:** los firmantes externos no pueden abrir enlaces de `127.0.0.1`. Publicar la firma hacia fuera, con un túnel y dominio y con la aprobación del CTO, es una decisión pendiente de F2.
- **Operación:**
  ```bash
  docker compose -p docuseal -f ~/docuseal/docker-compose.yml ps     # estado
  docker compose -p docuseal -f ~/docuseal/docker-compose.yml logs --tail 25
  ```
  Para actualizar, cambia la etiqueta fija de la imagen y ejecuta `up -d`. Antes de hacerlo, copia el volumen.

## 2. Actualizar la versión

> En `docker-compose.yml` la etiqueta de la imagen es fija (`jerico-crm:0.2.0`), así que cada build la **sobrescribe**. Antes de construir, se guarda la imagen actual con la convención que ya se usa en el servidor: `jerico-crm:prev-<commit desplegado>` (hoy existe `prev-5f4cd5d`).

1. **Copiar el código** del commit aprobado (desde la laptop). No toca `.env` y actualiza `DEPLOYED_COMMIT`:
   ```bash
   cd ~/Kaisen_AI/01_Proyectos/Proyecto_Jerico
   REV=$(git rev-parse --short <commit aprobado>)   # p. ej. el HEAD de la rama del CRM que aprobó el CTO
   git archive "$REV" | ssh kaisen-server 'tar -x -C ~/jerico'
   ssh kaisen-server "cp ~/jerico/DEPLOYED_COMMIT ~/jerico/DEPLOYED_COMMIT.anterior && echo $REV > ~/jerico/DEPLOYED_COMMIT && cat ~/jerico/DEPLOYED_COMMIT"
   ```
   Los archivos que se borraron en el repo **no** se borran en el servidor; si hace falta, se limpian a mano. Hazlo siempre con el commit **del CRM** (la rama que contiene `src/jerico/crm` al día), nunca con una rama de infraestructura sola.
2. **En el servidor:**
   ```bash
   ~/jerico/scripts/servidor/backup_crm.sh                       # backup justo antes del cambio
   PREV=$(cat ~/jerico/DEPLOYED_COMMIT.anterior)                 # lo guardó el paso 1
   docker tag jerico-crm:0.2.0 "jerico-crm:prev-$PREV"           # imagen actual → prev-<commit>
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

### 3.b Rotar la llave del asistente (`OPENAI_API_KEY`)

Desde `d0aeab3`, el asistente `/asistente` usa `OPENAI_API_KEY`, `OPENAI_MODEL` y `OPENAI_REASONING_EFFORT` del mismo `.env` (`specs/001-ventas-crm/asistente-despliegue.md`).
1. Crea la llave nueva en el panel del proveedor y **revoca la vieja**.
2. Edita la línea `OPENAI_API_KEY=` de `~/jerico/.env` a mano y vuelve a dejarlo en `chmod 600`.
3. Ejecuta `jcs up -d --force-recreate jerico-crm` y prueba `/asistente pregunta cómo va el pipeline`. En `docker logs`, la línea de uso aparece sin errores.
4. Las copias `~/jerico/.env.bak-*` guardan la llave vieja: bórralas con `shred -u` cuando ya no hagan falta.

## 4. Rollback

### 4.1 Volver a la imagen anterior (sin tocar los datos)

```bash
docker image ls jerico-crm                                       # elige la prev-<commit> buena (hoy: prev-5f4cd5d)
docker tag jerico-crm:prev-<commit> jerico-crm:0.2.0
jcs up -d --no-build --force-recreate jerico-crm
jcs ps jerico-crm && docker logs --tail 25 jerico-crm
```
Esto supone que `docker-compose.yml` sigue usando la etiqueta `jerico-crm:0.2.0`. Si la versión nueva la cambió (por ejemplo, a `0.3.0`), el rollback es volver a copiar el código del commit anterior (§2.1) y después correr `docker tag jerico-crm:prev-<commit> jerico-crm:0.2.0` y `jcs up -d --no-build --force-recreate jerico-crm`. Si vuelves a otro commit, actualiza también `DEPLOYED_COMMIT`.
Sirve si la versión nueva **no** cambió el esquema. Si lo cambió, la imagen vieja puede fallar con la base nueva: aplica también el §4.2 con el backup de antes de actualizar.

### 4.2 Volver a un backup (datos)

1. Elige el backup, que debe ser anterior al problema: `ls -1 ~/jerico-backups/crm/`.
2. **Pausa el cron de Jericó** en el servidor (`crontab -e`, comenta las dos líneas con `#`). Así el vigía no avisa de la parada y el backup nocturno no choca con la restauración. Si el vigía de Hermes también vigila `jerico-crm` (paso 0), páusalo igual.
3. **Descifra en la laptop** (la llave privada no viaja al servidor) y sube el `.tar` a un directorio privado, porque el `.tar` está **en claro**:
   ```bash
   # laptop
   umask 077 && install -d -m 700 ~/jerico-backups-copia
   scp kaisen-server:jerico-backups/crm/crm-AAAAMMDDTHHMMSSZ.tar.age ~/jerico-backups-copia/
   scripts/servidor/restore_crm.sh verify ~/jerico-backups-copia/crm-AAAAMMDDTHHMMSSZ.tar.age ~/.config/kaisen/jerico-backup.agekey
   age -d -i ~/.config/kaisen/jerico-backup.agekey -o ~/jerico-backups-copia/restaurar.tar ~/jerico-backups-copia/crm-AAAAMMDDTHHMMSSZ.tar.age
   ssh kaisen-server 'install -d -m 700 ~/jerico-restaurar'
   scp -p ~/jerico-backups-copia/restaurar.tar kaisen-server:jerico-restaurar/restaurar.tar
   ```
4. **En el servidor**, primero mira el plan (no cambia nada) y luego ejecútalo:
   ```bash
   ~/jerico/scripts/servidor/restore_crm.sh apply ~/jerico-restaurar/restaurar.tar
   CONFIRM=1 ~/jerico/scripts/servidor/restore_crm.sh apply ~/jerico-restaurar/restaurar.tar
   shred -u ~/jerico-restaurar/restaurar.tar                     # el .tar está en claro: bórralo ya
   ```
   El script verifica el archivo y luego:
   1. detiene `jerico-crm`;
   2. guarda lo que había en `~/jerico-backups/crm/pre-restore-*.tar.age` (cifrado);
   3. reemplaza el volumen;
   4. arranca el contenedor y espera a que esté `healthy`.

   La copia previa se guarda **tal cual**, aunque la base esté corrupta. Si te equivocaste de backup, se restaura igual que cualquier otro. Las copias `pre-restore-*` caen en la misma retención que los backups (`RETENTION_DAYS`, máximo 30 días).
5. **Borra la copia en claro de la laptop** (`shred -u ~/jerico-backups-copia/restaurar.tar`) y **reactiva el cron** (`crontab -e`, quita los `#`).

> **Retención en la laptop (tope de 30 días, J-08):** los `.tar.age` que se copian a `~/jerico-backups-copia/` también son datos personales. Bórralos a los 30 días: `find ~/jerico-backups-copia -name '*.tar.age' -mtime +30 -delete`.

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
> 🕒 **Última modificación:** 14/10/2026 01:43 (Claude Code · Opus 5.5)
