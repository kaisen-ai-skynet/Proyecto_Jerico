---
tipo: spec
proyecto: Jericó — Kaisen AI
estado: borrador para aprobación del CTO
creado: "13/10/2026 10:15"
modificado: "13/10/2026 22:00"
---

# Spec 003 — Endurecer la operación de Jericó CRM en kaisen-server

- **Estado:** BORRADOR. Pendiente de la aprobación del CTO, que también ejecuta en el servidor todo lo que aquí se entrega.
- **Tipo de cambio:** operación e infraestructura. No cambia el código del CRM (`src/jerico/crm` y `specs/001` pertenecen a crm-director).
- **Fuente:** mensaje del orquestador del 13/10/2026, autorizado por el CTO: «endurecer la operación de Jericó en kaisen-server (~/jerico, compose -p jerico)», con los entregables a) a d).
- **Contexto verificado (13/10/2026):**
  - `kaisen-server` (`DESKTOP-8F1B898`, Tailscale `100.79.169.121`) es Ubuntu sobre WSL2. El usuario es `kaisenai`, que pertenece al grupo `docker`, y las tareas programadas usan cron (bóveda, `Infraestructura/Servidor_Produccion.md`).
  - El servicio `jerico-crm` (en `docker-compose.yml`) monta el volumen `jerico_crm_data` en `/app/crm-data`. Dentro están la base SQLite `crm.db` (en WAL, ver `src/jerico/crm/app.py`), el archivo `heartbeat` y los adjuntos.
  - El healthcheck del contenedor exige que `heartbeat` tenga menos de 120 s.
  - La app trae su propio respaldo nocturno (`src/jerico/crm/backup.py`), pero solo funciona si `JERICO_CRM_BACKUP_AGE_RECIPIENT` y `JERICO_CRM_BACKUP_REMOTE` están definidos (con rclone). No sabemos si están definidos en el servidor: el `.env` no se lee.
  - En el servidor ya corre el vigía de Hermes (`~/hermes/vigia.py`, cron `*/5`), que reinicia contenedores caídos y avisa por correo. No sabemos si vigila `jerico-crm`.
- **Fuera de alcance:** ejecutar cualquier cosa en el servidor o en OCI, crear secretos, modificar el código del CRM y llevar los backups fuera del servidor (eso queda como mejora, ver §5).

## 1. Objetivo

Que el CTO pueda aprobar y ejecutar, sin improvisar, cuatro cosas:
1. Un backup cifrado de `jerico_crm_data` que no dependa de que la app esté sana, con retención y una prueba de restauración.
2. Un aviso inmediato si el contenedor deja de estar sano.
3. Un runbook de la operación diaria.
4. Un plan para migrar a OCI más adelante, aprovechando lo que ya está creado allí.

## 2. Requisitos

### a) Backup cifrado del volumen (`scripts/servidor/backup_crm.sh`)

- **SRV-01:** el backup saca una copia **consistente** de `crm.db` mientras el contenedor sigue corriendo, usando la API de backup de SQLite. Nunca copia a mano los archivos `crm.db`, `-wal` o `-shm`. También comprueba la copia con `PRAGMA integrity_check`.
- **SRV-02:** además de `crm.db`, el archivo incluye el resto del volumen (adjuntos y evidencias). Deja fuera `heartbeat` y los archivos `crm.db-wal` y `crm.db-shm`.
- **SRV-03:** el archivo se cifra con `age` para uno o varios destinatarios **públicos**, leídos de un archivo de destinatarios. En el servidor nunca hay una llave privada.
  - Si el archivo de destinatarios falta, está vacío o contiene `AGE-SECRET-KEY`, el script se niega a correr.
- **SRV-04:**
  - Antes de dar el backup por bueno, el script verifica que el resultado empieza por la cabecera `age-encryption.org/v1`.
  - En el disco nunca queda una copia sin cifrar: el directorio de trabajo es temporal y se borra siempre, también si falla.
  - La copia temporal que se hace dentro del contenedor también se borra.
- **SRV-05:** los archivos se llaman `crm-AAAAMMDDTHHMMSSZ.tar.age` y tienen permisos 600, dentro de un directorio con permisos 700.
- **SRV-06:** retención. Se borran los backups de más de `RETENTION_DAYS` días (14 por defecto, como máximo 30, el tope legal J-08 de la spec 001). Siempre se conserva al menos el más reciente. Solo se tocan los archivos que siguen el patrón de nombres de SRV-05 y las copias `pre-restore-AAAAMMDDTHHMMSSZ.tar.age` de SRV-11.
- **SRV-07:** solo puede correr un backup a la vez (`flock`). Si el contenedor no está corriendo, el backup falla con un código distinto de 0 y un mensaje claro.
- **SRV-08:** si el backup falla (también ante errores inesperados, mediante `trap ERR`, o si Docker no responde), se manda un aviso por el mismo canal que la alerta de b). Que el aviso falle no tapa el error del backup.
- **SRV-09:** la configuración (sin secretos) va en un archivo `backup-crm.env`, a partir de `deploy/servidor/backup-crm.env.example`. Las rutas por defecto son las del usuario `kaisenai`.

### a') Prueba de restauración (`scripts/servidor/restore_crm.sh`)

- **SRV-10:** `restore_crm.sh verify <backup.tar.age> <identidad>` descifra el backup en un directorio temporal y comprueba tres cosas:
  - que el tar contiene `crm.db`;
  - que `integrity_check` sale `ok`;
  - que existen las tablas básicas del CRM, `crm_meta` y `crm_leads` (definidas en `src/jerico/crm/db.py`).

  Al final imprime un resumen con el número de tablas y de archivos, y borra todo. Corre en la laptop del CTO, que es donde está la llave privada.
- **SRV-11:** `restore_crm.sh apply <backup.tar.age|backup.tar> [identidad]` restaura dentro del volumen y solo actúa si se pasa `CONFIRM=1`. Hace lo siguiente:
  1. Detiene `jerico-crm`.
  2. Guarda el contenido actual del volumen **tal cual** (`pack-raw`, sin comprobar la base, para que funcione aunque esté corrupta) en un archivo cifrado `pre-restore-*.tar.age`, usando el mismo archivo de destinatarios. Si esa copia falla, aborta sin tocar el volumen y vuelve a arrancar el contenedor.
  3. Vacía el volumen y extrae el backup.
  4. Arranca el contenedor y espera a que esté `healthy`.

  Si falta `CONFIRM=1`, solo muestra lo que haría.

### b) Alerta de salud (`scripts/servidor/healthwatch_crm.sh`)

- **SRV-12:** se ejecuta desde cron cada 5 minutos. Consulta el estado con `docker inspect` y lo clasifica:
  - **OK:** `healthy`.
  - **ARRANCANDO:** `starting`. Solo se trata como fallo si dura más de `STARTING_GRACE_MIN` (10 min).
  - **FALLO:** `unhealthy`, contenedor detenido o contenedor inexistente.
- **SRV-13:** avisa al pasar de OK a FALLO. Mientras el fallo siga, repite el aviso cada `REMIND_MIN` (60 min por defecto). Cuando vuelve a OK, manda un aviso de «recuperado» que dice cuánto duró la caída. El estado se guarda en un archivo de estado propio.
- **SRV-14:** el canal principal es Telegram (`sendMessage` del Bot API). Usa el token del bot y el chat del CTO que ya están en el `.env` del despliegue: `JERICO_CRM_TELEGRAM_BOT_TOKEN` y `JERICO_CRM_SEED_CTO_TELEGRAM_ID`.
  - Si Telegram falla, prueba por correo SMTP con las variables `JERICO_CRM_SMTP_*` y `JERICO_CRM_SEED_CTO_EMAIL`, si están definidas.
  - Si fallan los dos canales, termina con un código distinto de 0 y deja una línea en el log.
- **SRV-15:** los secretos se leen del `.env` sin ejecutarlo: se interpreta `CLAVE=valor` y nunca se hace `source`. El token nunca aparece en la línea de comandos (`ps`) ni en los logs, porque se pasa a `curl` por stdin con `-K -`. El aviso no incluye logs del contenedor (pueden contener datos personales); solo indica el comando que hay que correr para verlos.
- **SRV-16:** `sendMessage` no afecta el *polling* del bot. El conflicto 409 de Telegram solo ocurre con `getUpdates` o con webhooks, como recoge `research.md`.

### c) Runbook (`docs/despliegue-servidor-kaisen.md`)

- **SRV-17:** el runbook incluye siete procedimientos, con comandos copiables y la comprobación de cada paso:
  0. Inspección de solo lectura del estado actual.
  1. Instalar backup y alerta (cron).
  2. Actualizar la versión, etiquetando antes la imagen actual como rollback.
  3. Rotar el token del bot.
  4. Rollback de imagen y rollback de datos.
  5. Logs, con su rotación.
  6. Qué hacer cuando llega una alerta.
- **SRV-18:** se añade un override `deploy/servidor/docker-compose.servidor.yml` que limita los logs de `jerico-crm` (json-file, 10 MB × 3). Así el disco no crece sin límite, y no hace falta tocar `docker-compose.yml`.

### d) Plan de migración a OCI (`docs/migracion-oci.md`)

- **SRV-19:** el plan parte de lo que ya existe en OCI: el presupuesto `kaisen-alerta-1usd`, el compartment `kaisen-jerico`, `jerico-vcn` y su Security List. Incluye:
  - los requisitos previos (capacidad A1 y fin de la prueba hacia el ~20/10/2026);
  - la reconstrucción de la imagen en **arm64**;
  - un corte ordenado. El bot no puede hacer *polling* en dos sitios a la vez, así que hay que detener el CRM en el servidor, sacar un backup final, restaurarlo en la VM y verificar;
  - un rollback al servidor;
  - las tareas de limpieza.

## 3. Criterios de aceptación

- Hay tests automáticos (pytest, con `docker`, `age` y `curl` falsos en el `PATH`) que cubren SRV-01 a SRV-15. Ningún test toca Docker real, la red ni secretos reales.
- `scripts/oci/lint.sh` (o el equivalente que incluya `scripts/servidor/`) da 0 hallazgos de ShellCheck.
- `./scripts/verify.sh` y `pre-commit` en verde.
- La revisión (rol reviewer) audita cada requisito y da un veredicto: APROBADO o CAMBIOS NECESARIOS.

## 4. Riesgos y supuestos

- **[VERIFICADO 13/10/2026 22:00, solo lectura]** `~/jerico` contiene `docker-compose.yml` y `.env` (600). No es un repo git: es una copia de archivos con `DEPLOYED_COMMIT` = `d0aeab3`. `age` no está instalado y el vigía de Hermes no vigila `jerico-crm`. Detalle en el runbook, paso 0.
- **Renumeración:** esta spec nació como `002-servidor-kaisen`. Se renumeró a `003` el 13/10/2026 porque `jev/p1-router-spec` creó antes `specs/002-jev-router-sombra` (10:27 frente a 10:28).
- **[SUPUESTO]** cron corre en el WSL2 del servidor, porque el vigía de Hermes ya lo usa.
- **Riesgo:** el backup se queda en el mismo disco que el servidor. Protege frente a errores de datos, pero no frente a la pérdida de la máquina. La mitigación está en §5.
- **Riesgo:** si el problema es el propio token de Telegram (por ejemplo, revocado), la alerta solo llega si el correo está configurado.

## 5. Mejoras posteriores (no incluidas)

- Copiar los backups fuera del servidor, por ejemplo con `scp` periódico a la laptop, con el bucket `jerico-backups` de OCI o con el backup interno de la app (rclone).
- Integrar la alerta en el vigía de Hermes, que es ajeno a este repo.

---
> 🕒 **Última modificación:** 13/10/2026 22:00 (Claude Code · Opus 5.5)
