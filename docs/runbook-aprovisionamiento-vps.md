---
modificado: "11/10/2026 18:15"
---

# Runbook de Aprovisionamiento VPS Oracle — Proyecto Jericó
**Fase 4 · Frente 3 (Infraestructura & Operaciones)**
**Kaisen AI — Fecha:** 29/09/2026 · **Revisado:** 11/10/2026
**Autor:** Santiago González (CTO / Sudo Supremo) & Frente Infraestructura
**Objetivo:** Guía operativa paso a paso, idempotente y determinista para el aprovisionamiento desde cero de la instancia VPS en Oracle Cloud Infrastructure (OCI), hardening del sistema, red privada Tailscale y puesta en marcha de Jericó con Docker Compose, Redis y PostgreSQL 16.

---

> [!IMPORTANT]
> **Modo de Operación: Solo Preparación.** Este documento es un runbook ejecutable para ser corrido durante la ventana operativa autorizada por el CTO. No ejecutar comandos remotos fuera de la ventana programada.

> [!WARNING]
> **Revisión 11/10/2026.** Oracle redujo el Always Free ARM a **2 OCPU / 12 GB** (antes 4/24). Decisiones del CTO: región **Bogotá (`sa-bogota-1`)**, cuenta **Always Free pura**, **una sola VM** con Postgres co-locado en `127.0.0.1`, sin Coolify en Fase 0 y sin contingencia x86.
> Los pasos de creación de cuenta, red, VM, Tailscale, Postgres, backups y cierre perimetral (antes §1–§2) viven ahora en **`docs/guia-oci-principiantes.md`** con los scripts de `scripts/oci/`. Este runbook conserva el pre-vuelo resumido y el despliegue de Jericó (§3 en adelante).

---

## 1. Pre-vuelo (Checklist Binaria)

| Ítem | Requisito / Especificación | Criterio de Aceptación (Binario) | Estado |
| :--- | :--- | :--- | :---: |
| **1.1. Cuenta OCI** | Tenancy Always Free con MFA, compartment `kaisen-jerico` y alerta de presupuesto de 1 USD. | Guía, Parte B completada. | [ ] |
| **1.2. Región** | `sa-bogota-1` (Colombia Central). Irreversible. | Home region confirmada en la consola. | [ ] |
| **1.3. Shape & Arquitectura** | `VM.Standard.A1.Flex` ARM64, **2 OCPU / 12 GB** (máximo Always Free vigente). Sin contingencia x86 (rompe la regla ARM64). Ante falta de capacidad: Plan B de la guía (Parte D). | VM `RUNNING` con etiqueta Always Free-eligible. | [ ] |
| **1.4. Almacenamiento** | Boot Volume de 100 GB, Ubuntu 24.04 LTS aarch64 (límite gratuito: 200 GB acumulados). | Volumen asignado sin costo. | [ ] |
| **1.5. Llaves SSH** | Llaves públicas `ed25519` del equipo: `santiago` (CTO), `nicolas`, `jpablo`, `esteban`, `santiagojr`. Las ausentes se añaden después. | Formato `ssh-ed25519 AAAA...`; ninguna llave privada compartida. | [ ] |
| **1.6. Firewall / Security List** | Ingress temporal TCP 22 solo desde la IP del operador (`/32`); UDP 41641 opcional. PROHIBIDO abrir TCP 8000, 6379, 5432. Dentro de la VM: ufw deny entrante (lo aplica `01_bootstrap.sh`). | Reglas validadas en consola antes de crear la VM. | [ ] |
| **1.7. Red Privada / DNS** | Tailnet Kaisen AI activa; nombre de máquina `jerico-oracle`. | Sesión de administrador de Tailscale abierta para aprobar el nodo. | [ ] |
| **1.8. Presupuesto** | 0.00 USD (Always Free puro) con alerta en 1 USD. | Budget Alert activa. | [ ] |
| **1.9. Backups** | Bucket `jerico-backups` (Object Storage, privado) y llave age generada en la laptop del CTO. | Guía, Parte H completada y restauración probada. | [ ] |
| **1.10. Ventana Operativa** | 60 minutos máximo; canal síncrono con el CTO. | Notificación de inicio enviada al equipo. | [ ] |

---

## 2. Aprovisionamiento (resumen; detalle en la guía)

| Paso | Dónde | Comando / acción | Verificación |
| :--- | :--- | :--- | :--- |
| 2.1 Cuenta, red y VM | Consola OCI | Guía, Partes B–D (Plan B: `scripts/oci/00_retry_launch_a1.sh` en Cloud Shell) | VM `RUNNING`, IP pública anotada |
| 2.2 Bootstrap | VM, `ubuntu` + sudo | `sudo KEY_...=... ./01_bootstrap.sh` (copiado con `scp`) | Termina en `BOOTSTRAP COMPLETADO` |
| 2.3 Tailscale | VM | `sudo tailscale up --hostname=jerico-oracle` | `ssh santiago@jerico-oracle` desde la laptop |
| 2.4 Código | Laptop | `scripts/oci/sync_repo_to_vps.sh santiago@jerico-oracle` | `/opt/jerico/app/.deployed_rev` = commit esperado |
| 2.5 PostgreSQL 16 | VM, `santiago` | `/opt/jerico/app/scripts/oci/02_postgres.sh` | `5432 solo en 127.0.0.1` |
| 2.6 Backups | VM, sudo | `/etc/jerico/{backup.env,rclone.conf}` + `sudo scripts/oci/03_backups.sh` | Backup de prueba en el bucket |
| 2.7 Cierre perimetral | VM por Tailscale, sudo | `sudo scripts/oci/04_lockdown.sh` + borrar regla 22 en la Security List | `ssh -o ConnectTimeout=5 ubuntu@<IP_PUBLICA>` falla por timeout |
| 2.8 Verificación | VM, sudo | `sudo scripts/oci/verify_vps.sh` | `RESULTADO: OK` |

**Qué hace `01_bootstrap.sh`:** paquetes base y parches automáticos; sustituye `iptables-persistent` de la imagen Oracle por **ufw** (son incompatibles); instala Tailscale y Docker CE con `"ip": "127.0.0.1"` en `daemon.json` (todo puerto publicado sin IP explícita queda en loopback); crea los 5 usuarios con sus llaves; endurece SSH; crea `/opt/jerico/{app,data,backups,logs,secrets}` y el alias `jc` (Compose base + `docker-compose.prod.yml`). Coolify queda fuera de Fase 0.

---

## 3. Puesta en Marcha de Jericó (Docker Compose)

### Paso 3.1: Despliegue del Repositorio en `/opt/jerico/app`
Conectado como usuario `santiago` vía Tailscale:

```bash
# Desde la laptop del CTO, en el repo, con el commit/tag aprobado en HEAD:
scripts/oci/sync_repo_to_vps.sh santiago@jerico-oracle
```

**Verificación:** `cat /opt/jerico/app/.deployed_rev` coincide con `git rev-parse --short HEAD` de la laptop. (Se copia con `git archive`, sin `git push` y sin `.env`.)

### Paso 3.2: Configuración del Archivo `.env` en Producción
Cargar el archivo de variables de entorno mediante el método seguro (ver Sección 4) en `/opt/jerico/app/.env`.

```bash
# Restringir estrictamente los permisos del archivo de secretos
chmod 600 /opt/jerico/app/.env
chown santiago:docker /opt/jerico/app/.env
```

**Verificación:** `ls -la /opt/jerico/app/.env` muestra permisos `-rw-------` y propietario `santiago:docker`.

### Paso 3.3: Validación e Inicio de Servicios
Validar la configuración de Compose sin ejecutar nada:

```bash
cd /opt/jerico/app
jc config --quiet
```
*Criterio:* Si no hay errores de sintaxis, no produce salida y retorna código 0.

Levantar los servicios en modo desacoplado con reconstrucción:

```bash
jc up -d --build
jc ps
```

**Verificación:**
`jc ps` debe listar los tres contenedores en estado `Up` o `healthy`:
- `jerico-redis`: `Up (healthy)`
- `jerico-core`: `Up`
- `jerico-postgres`: `Up (healthy)`

### Paso 3.4: Verificación Rigurosa de Salud (Health Checks)

> [!WARNING]
> **Regla de Oro:** Un `200 OK` en `/health` o `/api/v1/ask` **NO** demuestra que Redis esté operativo. La arquitectura de Jericó incluye un mecanismo de fallback automático a memoria RAM cuando Redis no está disponible. Para dar por bueno el despliegue, es obligatorio validar Redis de forma directa y demostrable.

Ejecutar la secuencia de pruebas en orden:

```bash
# 1. Comprobación directa del motor Redis (demostrable)
jc exec redis redis-cli ping
# Salida esperada: PONG

# 2. Comprobación de persistencia y estadísticas de Redis
jc exec redis redis-cli info stats | grep -E 'total_commands_processed|instantaneous_ops_per_sec'

# 3. Comprobación de salud HTTP de la API
curl --fail --silent --show-error http://127.0.0.1:8000/health
# Salida esperada: {"status":"ok"}

# 4. Verificación de Binds de Red (Aislamiento 127.0.0.1)
ss -tulpn | grep -E '8000|6379'
```
*Criterio demostrable de Binds:*
- El puerto `8000` debe figurar escuchando exclusivamente en `127.0.0.1:8000`.
- El puerto `6379` debe figurar escuchando exclusivamente en `127.0.0.1:6379` (o no figurar en el host si solo se expone en la red interna Compose).
- **BAJO NINGUNA CIRCUNSTANCIA** deben figurar `0.0.0.0:8000`, `0.0.0.0:6379`, `[::]:8000` ni `[::]:6379`.

### Paso 3.5: Ejecución de la Prueba E2E (L0 y Memoria)
Ejecutar la prueba de extremo a extremo desde el host del VPS:

```bash
cd /opt/jerico/app
export JERICO_API_TOKEN=$(grep -E '^JERICO_API_TOKEN=' .env | cut -d '=' -f2-)
export JERICO_HOST="127.0.0.1"
export JERICO_PORT="8000"

bash scripts/test_e2e.sh
```

**Verificación:**
1. Salida de consola: `✅ Prueba E2E (L0) exitosa: {"reply":"...","level":"L0",...}`.
2. Confirmar que Redis almacenó la sesión generada por la prueba E2E:
   ```bash
   jc exec redis redis-cli keys "*test_e2e*"
   ```
   *Criterio:* Redis devuelve la clave de sesión creada, confirmando que la aplicación escribió en el backend de caché real y no en el fallback de RAM.

3. Inspeccionar logs para validar que no existan advertencias de fallback:
   ```bash
   jc logs --tail=100 jerico-core | grep -i "fallback" || true
   ```
   *Criterio:* Cero líneas que indiquen degradación a memoria en proceso.

---

## 4. Datos y Secretos

### 4.1. Inventario de Variables de Entorno (`.env`)
A continuación se lista el inventario exhaustivo de las **30 variables** reconocidas por el runtime de Jericó (basado en `.env.example`). **PROHIBIDO registrar valores reales en este documento o en el control de versiones:**

1. `JERICO_LLM_BASE_URL`
2. `JERICO_LLM_API_KEY`
3. `JERICO_LLM_BASE_URL_L1`
4. `JERICO_LLM_API_KEY_L1`
5. `JERICO_LLM_BASE_URL_L2`
6. `JERICO_LLM_API_KEY_L2`
7. `JERICO_LLM_BASE_URL_L3`
8. `JERICO_LLM_API_KEY_L3`
9. `JERICO_LLM_MODEL_L1`
10. `JERICO_LLM_MODEL_L2`
11. `JERICO_LLM_MODEL_L3`
12. `JERICO_LLM_MODEL_VOICE`
13. `JERICO_LLM_TIMEOUT_S`
14. `JERICO_LLM_MAX_RETRIES`
15. `JERICO_ROUTER_L2_KEYWORDS`
16. `JERICO_ROUTER_L3_KEYWORDS`
17. `JERICO_ROUTER_L2_EXCEPTIONS`
18. `JERICO_HOST`
19. `JERICO_PORT`
20. `JERICO_LOG_LEVEL`
21. `JERICO_API_TOKEN`
22. `JERICO_RATE_LIMIT_PER_MIN`
23. `JERICO_ALLOWED_TELEGRAM_IDS`
24. `JERICO_REDIS_URL`
25. `JERICO_POSTGRES_URL` (valor generado por `02_postgres.sh` en `/opt/jerico/secrets/postgres_url`)
26. `JERICO_MEMORY_TTL_HOURS`
27. `JERICO_MEMORY_MAX_SESSIONS`
28. `JERICO_VOICES_DIR`
29. `JERICO_STT_MODEL`
30. `JERICO_TTS_ENGINE`

### 4.2. Procedimiento Seguro de Carga en el VPS
Para evitar dejar secretos en el historial de comandos de bash (`~/.bash_history`) o en el syslog:

```bash
# 1. Desactivar temporalmente el historial de la sesión interactiva
set +o history

# 2. Cargar el contenido vía 'cat' interactivo hacia el archivo restringido
cat << 'EOF' > /opt/jerico/app/.env
# Pegar aquí el bloque de configuración provisto por el gestor de secretos corporativo
EOF

# 3. Restablecer el historial y fijar permisos restrictivos
set -o history
chmod 600 /opt/jerico/app/.env
chown santiago:docker /opt/jerico/app/.env
```

Alternativamente, transferir el archivo directamente desde la máquina local cifrada a través del canal seguro de Tailscale:
```bash
# Ejecutado desde la máquina del CTO:
scp -i ~/.ssh/id_ed25519_kaisen /path/seguro/jerico.env santiago@jerico-oracle:/opt/jerico/app/.env
```

---

## 5. Rollback y Recuperación por Fase

| Fase del Fallo | Causa Probable / Escenario | Procedimiento de Rollback & Mitigación | Tiempo Máx. Recuperación |
| :--- | :--- | :--- | :---: |
| **Fase 1: Creación de Instancia OCI** | Error de cuota en OCI, indisponibilidad de shape A1.Flex ARM64 en el AD seleccionado. | Plan B de la guía (Parte D): 1. Reintentar rotando fault domains y horarios.<br>2. `scripts/oci/00_retry_launch_a1.sh` en Cloud Shell.<br>3. Crear 1 OCPU / 6 GB y ampliar a 2/12 después.<br>Sin contingencia x86 ni cambio de región. | Variable |
| **Fase 2: Red & Tailscale** | Pérdida de conectividad SSH tras cerrar el puerto 22 en OCI o falla del servicio `tailscaled`. | 1. Abrir **OCI Console** ➔ Compute ➔ Instance ➔ **Console Connection** (Cloud Shell o VNC Connection). Este canal Out-Of-Band (OOB) no depende de la red pública ni de Tailscale.<br>2. Iniciar sesión mediante consola serie con el usuario `ubuntu` o `santiago`.<br>3. Verificar estado del daemon: `systemctl restart tailscaled`.<br>4. Si es necesario, reabrir temporalmente la regla TCP 22 en OCI Security List. | 10 minutos |
| **Fase 3: SSH Hardening** | Bloqueo por sintaxis inválida en `/etc/ssh/sshd_config.d/01-kaisen-security.conf`. | 1. Conectar por OCI Serial Console Connection.<br>2. Renombrar o eliminar el archivo conflictivo:<br>`sudo rm /etc/ssh/sshd_config.d/01-kaisen-security.conf`<br>3. Reiniciar SSH: `sudo systemctl restart ssh`. | 5 minutos |
| **Fase 4: Docker Compose & Jericó** | Contenedor `jerico-core` entra en `CrashLoopBackOff`, error en build, incompatibilidad de variables `.env`. | 1. Detener el despliegue fallido: `jc down`.<br>2. Consultar logs de error: `jc logs jerico-core`.<br>3. Regresar a la última versión estable etiquetada (desde la laptop):<br>`git checkout <tag-anterior-aprobado>`<br>`scripts/oci/sync_repo_to_vps.sh`<br>y en la VM `jc up -d --build`.<br>4. Repetir verificaciones de salud. | 5 minutos |
| **Fase 5: Redis & Persistencia** | Corrupción del archivo AOF (`appendonly.aof`) o fallo al levantar el contenedor `jerico-redis`. | 1. Detener Compose: `jc stop redis`.<br>2. Intentar reparar AOF: `jc run --rm redis redis-check-aof --fix /data/appendonly.aof`.<br>3. Si el volumen es irrecuperable: eliminar el volumen temporal `docker volume rm jerico_redis_data` y recrearlo (las sesiones de memoria son volátiles de corto plazo).<br>4. Iniciar servicio: `jc up -d redis`. | 5 minutos |

---

## 6. Definición de "Ventana Exitosa" y Reporte al CTO

### 6.1. Criterios de Cierre de la Ventana (Todos deben cumplirse)
Para declarar la ventana formalmente **CERRADA Y EXITOSA**, se requiere verificar afirmativamente cada una de las siguientes condiciones:

1. [ ] **Aislamiento Perimetral:** El puerto 22 y los puertos de aplicación (8000, 6379, 5432) están 100% cerrados a `0.0.0.0/0` en la Security List de OCI.
2. [ ] **Acceso Tailscale Zero-Trust:** El nodo `jerico-oracle` responde en el Tailnet corporativo y los 5 ingenieros autorizados pueden autenticar por SSH mediante sus llaves públicas individuales.
3. [ ] **Contenedores Activos:** `jc ps` reporta `jerico-core` y `jerico-redis` en estado `Up` y `healthy`.
4. [ ] **Binds Seguros en Loopback:** `ss -tulpn` confirma que los servicios escuchan exclusivamente en `127.0.0.1:8000` y `127.0.0.1:6379`.
5. [ ] **Salud de Aplicación:** `http://127.0.0.1:8000/health` responde con HTTP 200 y JSON `status: ok`.
6. [ ] **Operatividad de Redis Demostrada:** `redis-cli ping` responde `PONG` en el contenedor de Redis y almacena claves en las pruebas.
7. [ ] **Prueba E2E Exitosa:** `scripts/test_e2e.sh` ejecuta sin errores sobre la ruta L0 autenticada con token Bearer.
8. [ ] **Protección de Secretos:** Archivo `.env` con permisos `600` (`-rw-------`), sin presencia en repositorios git ni en el historial de comandos.

---

### 6.2. Plantilla de Reporte al CTO (Entregable de Cierre de Ventana)

```markdown
# 📋 Reporte de Cierre de Ventana Operativa — Aprovisionamiento VPS Oracle
**Fecha:** [AAAA-MM-DD HH:MM UTC-5]
**Responsable de Operación:** [Nombre del Operador]
**Aprobador:** Santiago González (CTO Kaisen AI)
**Resultado:** [EXITOSA / ROLLBACK EJECUTADO]

## 1. Identificación del Nodo
- **Hostname en Tailscale:** jerico-oracle
- **IP Privada Tailscale:** [100.x.y.z]
- **Región / AD OCI:** sa-bogota-1 / AD-1
- **Shape Aprovisionado:** VM.Standard.A1.Flex (ARM64, 2 OCPU, 12 GB RAM)
- **Versión de OS:** Ubuntu 24.04 LTS (Linux kernel aarch64)

## 2. Evidencias de Verificación
- **OCI Security List:** Puerto 22 cerrado a internet público [VERIFICADO]
- **SSH Individual:** 5 cuentas creadas con llaves ed25519 [VERIFICADO]
- **Docker Compose:** Tag desplegado: [tag / commit hash]
- **Redis Health:** jc exec redis redis-cli ping -> PONG [VERIFICADO]
- **API Health:** curl http://127.0.0.1:8000/health -> {"status":"ok"} [VERIFICADO]
- **Prueba E2E L0:** scripts/test_e2e.sh completado con código 0 [VERIFICADO]
- **Binds de Red:** 127.0.0.1:8000 y 127.0.0.1:6379 estrictos [VERIFICADO]

## 3. Incidentes y Desviaciones
- [Ninguno / Detallar cualquier ajuste realizado durante el bootstrap]

## 4. Dictamen Final
La infraestructura del VPS Oracle se encuentra aprovisionada, endurecida y lista para recibir tráfico operativo de Jericó AI-OS bajo arquitectura Zero-Trust.
```

---
> 🕒 **Última modificación:** 11/10/2026 18:15 (Claude Code · Opus 5.5)
