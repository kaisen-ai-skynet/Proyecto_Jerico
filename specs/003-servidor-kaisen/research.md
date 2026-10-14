---
tipo: investigacion
proyecto: Jericó — Kaisen AI
autor: plan-gemini (Gemini 3.8 Flash, vía herdr), revisado por infra-arquitecto
creado: "13/10/2026 10:20"
modificado: "13/10/2026 10:28"
---

> **Procedencia:** lo redactó plan-gemini por contrato. infra-arquitecto revisó que las respuestas fueran coherentes con lo que se sabe y las usó en el plan, pero **no volvió a abrir las URL**. Las marcas [VERIFICADO-DOC] son de Gemini.

# Research Técnico: Servidor Kaisen, SQLite WAL, Respaldo y Migración OCI

Este documento responde a las 7 preguntas técnicas de investigación para la estabilización y respaldo de Jericó CRM en WSL2 y su futura migración a Oracle Cloud Infrastructure (OCI) A1 Always Free.

---

## 1. Copia consistente de una base SQLite WAL viva desde fuera del contenedor

### Respuesta concreta y análisis de riesgos
Para una base de datos SQLite en modo WAL viva, la única opción segura cuando no se garantiza el binario CLI `sqlite3` dentro del contenedor es ejecutar un script inline de Python que invoque la API nativa de respaldo (`sqlite3.Connection.backup()`).

- **docker exec + API `sqlite3.backup` de Python [VERIFICADO-DOC]:**
  - *Mecanismo:* Abre la base en modo solo lectura (`mode=ro`) y utiliza la API nativa `sqlite3_backup_*` del motor C para copiar página por página a un archivo destino. Maneja de forma consistente las páginas en el archivo principal y en el log WAL sin detener lecturas ni escrituras.
  - *Riesgos:* Requiere que Python esté instalado en la imagen (cumplido en Jericó) y espacio suficiente para escribir el archivo destino (en un volumen o streaming). Si hay escrituras concurrentes masivas, la API reintenta automáticamente las páginas modificadas sin corromper el destino.
- **`VACUUM INTO` [VERIFICADO-DOC]:**
  - *Mecanismo:* Genera una copia desfragmentada directamente mediante SQL (`VACUUM INTO '/ruta/backup.db'`).
  - *Riesgos:* Requiere un bloqueo reservado inicial que compite con transacciones de escritura concurrentes. Es mucho más costoso en CPU e I/O que una copia de páginas porque reconstruye todos los árboles B. No funciona si la conexión es estrictamente de solo lectura (`mode=ro`).
- **Copiar archivos (`cp crm.db*` / `docker cp`) [VERIFICADO-DOC]:**
  - *Mecanismo:* Copia a nivel de sistema de archivos de `crm.db`, `crm.db-wal` y `crm.db-shm`.
  - *Riesgos:* **PELIGRO DE CORRUPCIÓN.** La copia no es atómica. Si ocurre una escritura o un checkpoint entre la copia de `crm.db` y `crm.db-wal`, la cabecera y el log quedarán desincronizados, produciendo una base corrupta o con pérdida de transacciones. La documentación oficial de SQLite prohíbe explícitamente este método en caliente.

### Comando y flags exactos
```bash
docker exec jerico-crm python3 -c "
import sqlite3
src = sqlite3.connect('file:/app/crm-data/crm.db?mode=ro', uri=True)
dst = sqlite3.connect('/app/crm-data/crm_snapshot.db')
src.backup(dst)
dst.close()
src.close()
"
```

### Fuentes oficiales
- SQLite Online Backup API: https://www.sqlite.org/backup.html [VERIFICADO-DOC]
- SQLite WAL Mode (Backups): https://www.sqlite.org/wal.html [VERIFICADO-DOC]
- Python sqlite3 Connection.backup(): https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup [VERIFICADO-DOC]

---

## 2. Herramienta `age`: cifrado con destinatarios, descifrado e inspección

### Respuesta concreta
`age` permite cifrado asimétrico moderno (X25519) sin complejidad de GPG. Admite archivos de destinatarios (`recipients`) que contienen una o varias claves públicas (`age1...`), descifrado mediante archivos de identidad (`AGE-SECRET-KEY-...`), e identificación de formato mediante un preámbulo textual estandarizado.

### Comandos y flags exactos
- **Cifrar usando archivo de destinatarios (-R / --recipients-file) [VERIFICADO-DOC]:**
  ```bash
  age --encrypt -R /ruta/destinatarios.txt -o backup.tar.gz.age backup.tar.gz
  ```
  *Flags:* `-e` / `--encrypt` activa cifrado; `-R` especifica el archivo de claves públicas; `-o` define el archivo de salida.
- **Descifrar usando identidad (-i / --identity) [VERIFICADO-DOC]:**
  ```bash
  age --decrypt -i /ruta/identidad.agekey -o backup.tar.gz backup.tar.gz.age
  ```
  *Flags:* `-d` / `--decrypt` activa descifrado; `-i` especifica el archivo con la clave secreta; `-o` el destino descifrado.
- **Detección de archivo age válido sin poseer la clave [VERIFICADO-DOC]:**
  La especificación oficial de `age` estipula que la primera línea de la cabecera ASCII de cualquier archivo age debe ser exactamente:
  `age-encryption.org/v1` (terminada en salto de línea `\n`, 22 bytes en total).
  *Comando de verificación:*
  ```bash
  test "$(head -n 1 backup.tar.gz.age)" = "age-encryption.org/v1" && echo "Válido" || echo "Inválido"
  ```

### Fuentes oficiales
- Especificación oficial de formato age (v1): https://age-encryption.org/v1 [VERIFICADO-DOC]
- Repositorio y manual de age: https://github.com/FiloSottile/age [VERIFICADO-DOC]

---

## 3. Telegram Bot API: sendMessage vía curl y concurrencia con getUpdates

### Respuesta concreta y análisis de concurrencia
- **¿Interfiere `sendMessage` con un bot haciendo long polling `getUpdates` con el mismo token? [VERIFICADO-DOC]:**
  **NO, no interfiere en absoluto.** El error `HTTP 409 Conflict` ocurre exclusivamente cuando existen dos clientes consumiendo actualizaciones al mismo tiempo (dos llamadas concurrentes a `getUpdates` o una llamada a `getUpdates` mientras existe un webhook activo).
  `sendMessage` es una llamada de salida sin estado (*stateless outbound request*) y opera de forma completamente desacoplada del pipeline de recepción de eventos.
- **Límites y parámetros [VERIFICADO-DOC]:**
  - `chat_id` (obligatorio): identificador numérico del chat o canal (`-100...` o ID del usuario).
  - `text` (obligatorio): contenido del mensaje (de 1 a 4096 caracteres UTF-8).
  - `disable_notification` (opcional): booleano (`true`/`false`). Si es `true`, envía el mensaje de forma silenciosa (sin sonido ni vibración).
  - *Límites de tasa (Rate Limits):* máximo 1 mensaje por segundo por chat individual; máximo 30 mensajes por segundo a nivel global del bot; ráfagas cortas permitidas.

### Comando y flags exactos
```bash
curl -s -S -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d chat_id="${TELEGRAM_CHAT_ID}" \
  -d text="Aviso: Respaldo nocturno completado exitosamente" \
  -d disable_notification=true
```

### Fuentes oficiales
- Telegram Bot API - sendMessage: https://core.telegram.org/bots/api#sendmessage [VERIFICADO-DOC]
- Telegram Bot API - getUpdates y conflictos: https://core.telegram.org/bots/api#getupdates [VERIFICADO-DOC]
- Telegram Bot FAQ - Broadcasting limits: https://core.telegram.org/bots/faq#broadcasting-to-users [VERIFICADO-DOC]

---

## 4. Envío de correo con curl por SMTP (puertos 465 y 587)

### Respuesta concreta y gestión segura de credenciales
`curl` soporta el protocolo SMTP/SMTPS nativamente. Para no exponer credenciales en la tabla de procesos (`ps aux` / `/proc`), se debe evitar el flag `-u usuario:pass` en línea de comandos y utilizar `--netrc-file` apuntando a un archivo con permisos `600`.

- **SMTPS implícito (puerto 465):** TLS directo desde el handshake TCP inicial (`smtps://`).
- **STARTTLS explícito (puerto 587):** conexión SMTP inicial en texto plano que se eleva obligatoriamente a TLS mediante el comando STARTTLS (`smtp://` + `--ssl-reqd`).

### Comandos y flags exactos
Archivo de credenciales `/etc/jerico/smtp.netrc` (modo `chmod 600`):
```text
machine smtp.ejemplo.com login usuario@dominio.com password MI_PASSWORD_SECRETO
```

- **Envío vía SMTPS (puerto 465) [VERIFICADO-DOC]:**
  ```bash
  curl --url "smtps://smtp.ejemplo.com:465" \
    --ssl-reqd \
    --netrc-file /etc/jerico/smtp.netrc \
    --mail-from "notificaciones@dominio.com" \
    --mail-rcpt "cto@dominio.com" \
    --upload-file /tmp/mensaje.eml
  ```
- **Envío vía STARTTLS (puerto 587) [VERIFICADO-DOC]:**
  ```bash
  curl --url "smtp://smtp.ejemplo.com:587" \
    --ssl-reqd \
    --netrc-file /etc/jerico/smtp.netrc \
    --mail-from "notificaciones@dominio.com" \
    --mail-rcpt "cto@dominio.com" \
    --upload-file /tmp/mensaje.eml
  ```
*Flags:* `--mail-from` define el envelope sender; `--mail-rcpt` define el envelope recipient; `--ssl-reqd` exige conexión TLS estricta; `--upload-file` pasa el archivo con cabeceras RFC 5322 (`From:`, `To:`, `Subject:`) y cuerpo.

### Fuentes oficiales
- curl Manpage - SMTP options: https://curl.se/docs/manpage.html [VERIFICADO-DOC]
- Everything curl - Sending email via SMTP: https://everything.curl.dev/usingcurl/smtp [VERIFICADO-DOC]

---

## 5. Demonio cron en Ubuntu bajo WSL2 y aseguramiento de arranque

### Respuesta concreta
En WSL2 tradicional, `cron` **no arranca automáticamente** porque el sistema de inicio de Microsoft (`/init`) no lanza servicios de fondo por defecto.

### Mecanismos de arranque en `/etc/wsl.conf`
1. **Opción recomendada: Activar systemd nativo [VERIFICADO-DOC]:**
   En distribuciones modernas de WSL2 (Windows 10/11 con WSL >= 0.67.6), se habilita systemd en `/etc/wsl.conf`:
   ```ini
   [boot]
   systemd=true
   ```
   Al reiniciar la instancia (`wsl --shutdown` desde Windows), systemd corre como PID 1 y gestiona `cron.service` automáticamente (`sudo systemctl enable cron`).
2. **Opción alternativa sin systemd: Directiva boot command [VERIFICADO-DOC]:**
   ```ini
   [boot]
   command="service cron start"
   ```
   WSL ejecuta este comando con privilegios de `root` cada vez que la distribución se inicializa.

### Riesgos operativos en WSL2 [VERIFICADO-DOC]
- **Apagado por inactividad:** WSL2 se detiene automáticamente tras unos minutos si no hay ventanas de terminal interactivas abiertas o procesos de Windows vinculados. Si la máquina host está desatendida, los trabajos de cron no se disparan a menos que se mantenga una tarea en segundo plano en Windows.
- **Suspensión / Sleep del host:** Cuando la laptop entra en suspensión, la VM se pausa. Los cron jobs programados para ese intervalo se omiten hasta el despertar, y el reloj de la VM puede desfasarse temporalmente.

### Fuentes oficiales
- Microsoft Learn - Configuración avanzada de WSL (wsl.conf): https://learn.microsoft.com/en-us/windows/wsl/wsl-config [VERIFICADO-DOC]
- Microsoft Learn - Systemd support in WSL: https://learn.microsoft.com/en-us/windows/wsl/systemd [VERIFICADO-DOC]

---

## 6. Estados y healthcheck en `docker inspect`

### Respuesta concreta y valores posibles
- **Valores posibles de `.State.Status` [VERIFICADO-DOC]:**
  `"created"`, `"restarting"`, `"running"`, `"removing"`, `"paused"`, `"exited"`, `"dead"`.
- **Valores posibles de `.State.Health.Status` [VERIFICADO-DOC]:**
  - `"starting"`: el contenedor está dentro del periodo de arranque (`start-period`) o no ha completado el primer chequeo.
  - `"healthy"`: el último healthcheck retornó código de salida 0.
  - `"unhealthy"`: fallos consecutivos alcanzaron el umbral de reintentos (`retries`).
  - *Sin healthcheck:* si el contenedor no tiene directiva `HEALTHCHECK`, la propiedad `.State.Health` es `null` (en templates devuelve cadena vacía o `<no value>`).
- **Comportamiento si el contenedor NO existe [VERIFICADO-DOC]:**
  - Código de salida (*exit code*): `1`.
  - Salida estándar (*stdout*): vacía.
  - Salida de error (*stderr*): `Error response from daemon: No such container: <nombre>` (o `Error: No such container: ...`).

### Comandos y flags exactos
```bash
# Obtener estado general del contenedor
docker inspect --format '{{.State.Status}}' jerico-crm 2>/dev/null || echo "not_found"

# Obtener estado de salud de forma segura (tolerante a null)
docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' jerico-crm 2>/dev/null || echo "not_found"
```

### Fuentes oficiales
- Docker CLI Reference - docker inspect: https://docs.docker.com/reference/cli/docker/inspect/ [VERIFICADO-DOC]
- Docker Engine API v1.47 - ContainerInspect: https://docs.docker.com/engine/api/v1.47/#tag/Container/operation/ContainerInspect [VERIFICADO-DOC]
- Dockerfile Reference - HEALTHCHECK: https://docs.docker.com/reference/dockerfile/#healthcheck [VERIFICADO-DOC]

---

## 7. Migración a OCI A1 Always Free (x86_64 a aarch64)

### Portabilidad de SQLite entre arquitecturas [VERIFICADO-DOC]
- **¿La base SQLite es portable entre arquitecturas?** **SÍ, 100% portable y compatible binariamente.**
- La especificación de formato de SQLite garantiza que los archivos de base de datos son independientes de la arquitectura del procesador, el tamaño de palabra (32 o 64 bits) y el orden de bytes (*endianness*). Un archivo `crm.db` generado en x86_64 puede copiarse directamente a una máquina ARM64 (aarch64) y abrirse sin ninguna conversión ni volcado SQL intermedio.
- *Requisito crítico:* La base debe estar cerrada o respaldada limpiamente (mediante snapshot con `sqlite3.backup` o vaciado WAL previo `PRAGMA wal_checkpoint(TRUNCATE)`). **No** se deben transferir los archivos efímeros `-shm`.

### Reconstrucción de la imagen Docker [VERIFICADO-DOC]
- **¿Hay que reconstruir la imagen para arm64 / buildx?** **SÍ, obligatoriamente.**
- Los contenedores comparten el kernel Linux del host. Un binario compilado para x86_64 genera un error de sistema `exec format error` (errno 8) al intentar ejecutarse en el kernel ARM64 de OCI A1 (`VM.Standard.A1.Flex`).
- La emulación mediante QEMU (`binfmt_misc`) es lenta e inestable para entornos de producción.
- *Estrategia recomendada:* Reconstruir la imagen de forma nativa en la VM OCI ARM64 (`docker compose build`) o compilar una imagen multi-arquitectura con `docker buildx build --platform linux/amd64,linux/arm64` antes de la subida.

### Fuentes oficiales
- SQLite File Format Neutrality: https://www.sqlite.org/onefile.html [VERIFICADO-DOC]
- SQLite Architecture & Byte Order: https://www.sqlite.org/formatchng.html [VERIFICADO-DOC]
- Docker Multi-platform builds (Buildx): https://docs.docker.com/build/building/multi-platform/ [VERIFICADO-DOC]
- Oracle Cloud Infrastructure - Ampere A1 Compute: https://www.oracle.com/cloud/compute/arm/ [VERIFICADO-DOC]

---
> 🕒 **Última modificación:** 13/10/2026 10:28 (Claude Code · Opus 5.5)
