# Runbook de Aprovisionamiento VPS Oracle — Proyecto Jericó
**Fase 4 · Frente 3 (Infraestructura & Operaciones)**  
**Kaisen AI — Fecha:** 29/09/2026  
**Autor:** Santiago González (CTO / Sudo Supremo) & Frente Infraestructura  
**Objetivo:** Guía operativa paso a paso, idempotente y determinista para el aprovisionamiento desde cero de la instancia VPS en Oracle Cloud Infrastructure (OCI), hardening del sistema, red privada Tailscale y puesta en marcha de Jericó con Docker Compose y Redis.

---

> [!IMPORTANT]
> **Modo de Operación: Solo Preparación.** Este documento es un runbook ejecutable para ser corrido durante la ventana operativa autorizada por el CTO. No ejecutar comandos remotos fuera de la ventana programada.

---

## 1. Pre-vuelo (Checklist Binaria)

Antes de iniciar la ventana de aprovisionamiento, el operador debe validar el cumplimiento del 100% de los siguientes ítems:

| Ítem | Requisito / Especificación | Criterio de Aceptación (Binario) | Estado |
| :--- | :--- | :--- | :---: |
| **1.1. Cuenta OCI** | Tenancy activa en Oracle Cloud Infrastructure con permisos de administrador en Compute y VCN. | Acceso confirmado a la consola OCI sin alertas de facturación ni suspensión. | [ ] |
| **1.2. Región** | Región asignada (ej. `sa-saopaulo-1`, `us-ashburn-1` o tenancy corporativa Kaisen AI). | Región seleccionada en consola con disponibilidad de recursos Free Tier / Pay-as-you-go. | [ ] |
| **1.3. Shape & Arquitectura** | Primario: `VM.Standard.A1.Flex` (Ampere ARM64 - 4 OCPU, 24 GB RAM).<br>Contingencia: `VM.Standard.E2.1.Micro` (AMD64 - 1 OCPU, 1 GB RAM). | Capacidad de cómputo verificada en el Availability Domain (AD) destino. | [ ] |
| **1.4. Almacenamiento** | Boot Volume de 50 GB a 100 GB (rendimiento balanceado, Ubuntu 24.04 LTS). | Volumen asignado dentro del margen gratuito OCI (hasta 200 GB acumulados). | [ ] |
| **1.5. Llaves SSH** | 5 llaves públicas `ed25519` del equipo técnico recolectadas:<br>- `santiago` (CTO)<br>- `nicolas` (Lead Sysadmin)<br>- `jpablo` (Backend)<br>- `esteban` (Infra)<br>- `santiagojr` (Ops/BD) | Claves públicas validadas en formato `ssh-ed25519 AAAAC3... email@kaisen.ai` sin claves privadas expuestas. | [ ] |
| **1.6. Firewall / NSG** | OCI VCN Default Security List preparada:<br>- Ingress temporal: TCP 22 desde IP pública del operador (o `0.0.0.0/0` solo durante bootstrap inicial).<br>- UDP 41641 (Tailscale WireGuard direct peer, opcional).<br>- PROHIBIDO abrir a `0.0.0.0/0`: TCP 8000, TCP 6379, TCP 5432. | Reglas de ingress validadas en consola OCI antes de encender la máquina. | [ ] |
| **1.7. Red Privada / DNS** | Tailnet corporativa Kaisen AI activa en Tailscale (`kaisen.ai`).<br>Nombre de máquina planeado: `jerico-oracle`. | MagicDNS habilitado y sesión de administrador en Tailscale abierta para aprobar el nodo. | [ ] |
| **1.8. Presupuesto** | 0.00 USD (Always Free Tier) o presupuesto asignado con alerta en $1 USD. | Alarma de presupuesto (Budget Alert) activa en OCI Cost Management. | [ ] |
| **1.9. Ventana Operativa** | Ventana acordada: 60 minutos de duración máxima.<br>Canal de comunicación síncrono activo con el CTO y desarrolladores. | Notificación de inicio enviada al equipo Kaisen AI. | [ ] |

---

## 2. Pasos Numerados de Aprovisionamiento

Todos los comandos son idempotentes y reproducibles.

### Paso 2.1: Creación de la Instancia en OCI Console
1. Entrar a **OCI Console** ➔ **Compute** ➔ **Instances** ➔ **Create Instance**.
2. Parámetros de creación:
   - **Name:** `jerico-core-oracle-01`
   - **Placement:** Availability Domain por defecto.
   - **Image:** Canonical Ubuntu 24.04 LTS (aarch64 / ARM64).
   - **Shape:** Ampere `VM.Standard.A1.Flex` con **4 OCPUs** y **24 GB de Memoria**.
   - **Networking:** Asignar a la VCN principal, subred pública, con **Assign a public IPv4 address** activado temporalmente.
   - **SSH Keys:** Seleccionar "Paste public keys" y pegar la llave pública del CTO (`KEY_SANTIAGO`).
   - **Boot Volume:** 50 GB (extensión por defecto).
3. Hacer clic en **Create**.
4. **Verificación:** La instancia pasa al estado `RUNNING` y se anota la `<IP_PUBLICA_ORACLE>`.

### Paso 2.2: Conexión Inicial y Preparación de Insumos
Desde la estación de trabajo autorizada del operador:

```bash
# Probar conexión SSH inicial con la clave de provisión
ssh -o StrictHostKeyChecking=accept-new -i ~/.ssh/id_ed25519_kaisen ubuntu@<IP_PUBLICA_ORACLE>
```

**Verificación:** Acceso exitoso al shell `ubuntu@jerico-core-oracle-01:~$`.

### Paso 2.3: Inyección de Llaves y Ejecución de Bootstrap
Subir o definir en el entorno remoto las claves públicas del equipo y ejecutar el script `scripts/bootstrap_vps_oracle.sh`:

```bash
# En el VPS como root o mediante sudo:
sudo -i

# Exportar las claves públicas del equipo antes de invocar el bootstrap
export KEY_SANTIAGO="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... santiago@kaisen.ai"
export KEY_NICOLAS="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... nicolas@kaisen.ai"
export KEY_JPABLO="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... jpablo@kaisen.ai"
export KEY_ESTEBAN="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... esteban@kaisen.ai"
export KEY_SANTIAGOJR="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... santiagojr@kaisen.ai"

# Descargar o clonar el script de bootstrap desde el repositorio
mkdir -p /opt/jerico/scripts
curl -fsSL https://raw.githubusercontent.com/kaisen-ai-skynet/Proyecto_Jerico/main/scripts/bootstrap_vps_oracle.sh -o /opt/jerico/scripts/bootstrap_vps_oracle.sh
chmod +x /opt/jerico/scripts/bootstrap_vps_oracle.sh

# Ejecutar el bootstrap idempotente
/opt/jerico/scripts/bootstrap_vps_oracle.sh
```

**¿Qué ejecuta este paso de forma determinista?**
1. Actualización de paquetes base del OS (`apt-get update && apt-get upgrade`).
2. Desbloqueo y persistencia de iptables de Oracle para interfaz `tailscale0`.
3. Instalación de Tailscale daemon.
4. Instalación de Docker CE y plugin Compose (`docker-compose-plugin`).
5. Creación de usuarios locales (`santiago`, `nicolas`, `jpablo`, `esteban`, `santiagojr`) con pertenencia al grupo `docker`, llaves en `~/.ssh/authorized_keys` y sudoers según matriz.
6. Hardening de SSH en `/etc/ssh/sshd_config.d/01-kaisen-security.conf` (`PermitRootLogin no`, `PasswordAuthentication no`, `AllowUsers`).
7. Despliegue de Coolify en `/data/coolify`.
8. Creación del directorio de trabajo `/opt/jerico/{data,backups,logs}` con permisos `santiago:docker` (775).

**Verificación:**
```bash
# 1. Comprobar Docker y Compose
docker --version && docker compose version

# 2. Comprobar usuarios y grupos
id santiago && id jpablo && id esteban

# 3. Comprobar sintaxis SSH
sshd -t
```
*Criterio:* Los comandos retornan código de salida 0 sin advertencias de sintaxis.

### Paso 2.4: Activación y Enlace a Tailscale Mesh
En el shell del VPS:

```bash
sudo tailscale up --hostname=jerico-oracle --ssh --accept-routes
```

1. El comando imprime una URL de autenticación (`https://login.tailscale.com/a/...`).
2. El operador abre la URL en su navegador y autoriza la máquina dentro del Tailnet `kaisen.ai`.
3. Validar estado y dirección IP interna asignada:

```bash
tailscale status
tailscale ip -4
```

**Verificación:** `tailscale ip -4` retorna una IP en el rango CGNAT `100.x.y.z`, y el nodo figura activo como `jerico-oracle` en la consola de Tailscale.

### Paso 2.5: Verificación de Acceso SSH por Tailscale y Cierre Perimetral OCI
1. Desde la máquina local del operador (conectada a Tailscale):
```bash
ssh santiago@jerico-oracle
```
2. Confirmar que el login funciona sin contraseña mediante la llave `ed25519`.
3. **Cierre de Brecha Perimetral en OCI Console:**
   - Ir a **Networking** ➔ **Virtual Cloud Networks** ➔ Seleccionar VCN ➔ **Security Lists** ➔ **Default Security List**.
   - **ELIMINAR** la regla de Ingress: `TCP Port 22` desde `0.0.0.0/0`.
   - Mantener únicamente: Egress total (`0.0.0.0/0`) y opcional Ingress UDP 41641.
4. **Verificación de Cierre:**
   Intentar conectar por la IP pública directa:
   ```bash
   ssh -o ConnectTimeout=5 ubuntu@<IP_PUBLICA_ORACLE>
   ```
   *Criterio:* La conexión debe fallar por timeout (`Operation timed out`), mientras que `ssh santiago@jerico-oracle` responde inmediatamente vía Tailscale.

---

## 3. Puesta en Marcha de Jericó (Docker Compose)

### Paso 3.1: Despliegue del Repositorio en `/opt/jerico/app`
Conectado como usuario `santiago` vía Tailscale:

```bash
cd /opt/jerico
if [ ! -d "/opt/jerico/app" ]; then
    git clone https://github.com/kaisen-ai-skynet/Proyecto_Jerico.git /opt/jerico/app
fi

cd /opt/jerico/app
git fetch --tags
git checkout tags/v0.2.0 || git checkout main
```

**Verificación:** `git status` y `git rev-parse --short HEAD` confirman la revisión aprobada.

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
docker compose config --quiet
```
*Criterio:* Si no hay errores de sintaxis, no produce salida y retorna código 0.

Levantar los servicios en modo desacoplado con reconstrucción:

```bash
docker compose up -d --build
docker compose ps
```

**Verificación:**
`docker compose ps` debe listar los dos contenedores en estado `Up` o `healthy`:
- `jerico-redis`: `Up (healthy)`
- `jerico-core`: `Up`

### Paso 3.4: Verificación Rigurosa de Salud (Health Checks)

> [!WARNING]
> **Regla de Oro:** Un `200 OK` en `/health` o `/api/v1/ask` **NO** demuestra que Redis esté operativo. La arquitectura de Jericó incluye un mecanismo de fallback automático a memoria RAM cuando Redis no está disponible. Para dar por bueno el despliegue, es obligatorio validar Redis de forma directa y demostrable.

Ejecutar la secuencia de pruebas en orden:

```bash
# 1. Comprobación directa del motor Redis (demostrable)
docker compose exec redis redis-cli ping
# Salida esperada: PONG

# 2. Comprobación de persistencia y estadísticas de Redis
docker compose exec redis redis-cli info stats | grep -E 'total_commands_processed|instantaneous_ops_per_sec'

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
   docker compose exec redis redis-cli keys "*test_e2e*"
   ```
   *Criterio:* Redis devuelve la clave de sesión creada, confirmando que la aplicación escribió en el backend de caché real y no en el fallback de RAM.

3. Inspeccionar logs para validar que no existan advertencias de fallback:
   ```bash
   docker compose logs --tail=100 jerico-core | grep -i "fallback" || true
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
25. `JERICO_POSTGRES_URL`
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
| **Fase 1: Creación de Instancia OCI** | Error de cuota en OCI, indisponibilidad de shape A1.Flex ARM64 en el AD seleccionado. | 1. Cambiar de Availability Domain dentro de la misma región.<br>2. Si persiste, conmutar al shape de contingencia `VM.Standard.E2.1.Micro` (AMD64).<br>3. En caso extremo, destruir la instancia creada y reintentar. | 5 minutos |
| **Fase 2: Red & Tailscale** | Pérdida de conectividad SSH tras cerrar el puerto 22 en OCI o falla del servicio `tailscaled`. | 1. Abrir **OCI Console** ➔ Compute ➔ Instance ➔ **Console Connection** (Cloud Shell o VNC Connection). Este canal Out-Of-Band (OOB) no depende de la red pública ni de Tailscale.<br>2. Iniciar sesión mediante consola serie con el usuario `ubuntu` o `santiago`.<br>3. Verificar estado del daemon: `systemctl restart tailscaled`.<br>4. Si es necesario, reabrir temporalmente la regla TCP 22 en OCI Security List. | 10 minutos |
| **Fase 3: SSH Hardening** | Bloqueo por sintaxis inválida en `/etc/ssh/sshd_config.d/01-kaisen-security.conf`. | 1. Conectar por OCI Serial Console Connection.<br>2. Renombrar o eliminar el archivo conflictivo:<br>`sudo rm /etc/ssh/sshd_config.d/01-kaisen-security.conf`<br>3. Reiniciar SSH: `sudo systemctl restart ssh`. | 5 minutos |
| **Fase 4: Docker Compose & Jericó** | Contenedor `jerico-core` entra en `CrashLoopBackOff`, error en build, incompatibilidad de variables `.env`. | 1. Detener el despliegue fallido: `docker compose down`.<br>2. Consultar logs de error: `docker compose logs jerico-core`.<br>3. Regresar a la última versión estable etiquetada:<br>`git checkout <tag-anterior-aprobado>`<br>`docker compose up -d --build`.<br>4. Repetir verificaciones de salud. | 5 minutos |
| **Fase 5: Redis & Persistencia** | Corrupción del archivo AOF (`appendonly.aof`) o fallo al levantar el contenedor `jerico-redis`. | 1. Detener Compose: `docker compose stop redis`.<br>2. Intentar reparar AOF: `docker compose run --rm redis redis-check-aof --fix /data/appendonly.aof`.<br>3. Si el volumen es irrecuperable: eliminar el volumen temporal `docker volume rm jerico_redis_data` y recrearlo (las sesiones de memoria son volátiles de corto plazo).<br>4. Iniciar servicio: `docker compose up -d redis`. | 5 minutos |

---

## 6. Definición de "Ventana Exitosa" y Reporte al CTO

### 6.1. Criterios de Cierre de la Ventana (Todos deben cumplirse)
Para declarar la ventana formalmente **CERRADA Y EXITOSA**, se requiere verificar afirmativamente cada una de las siguientes condiciones:

1. [ ] **Aislamiento Perimetral:** El puerto 22 y los puertos de aplicación (8000, 6379, 5432) están 100% cerrados a `0.0.0.0/0` en la Security List de OCI.
2. [ ] **Acceso Tailscale Zero-Trust:** El nodo `jerico-oracle` responde en el Tailnet corporativo y los 5 ingenieros autorizados pueden autenticar por SSH mediante sus llaves públicas individuales.
3. [ ] **Contenedores Activos:** `docker compose ps` reporta `jerico-core` y `jerico-redis` en estado `Up` y `healthy`.
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
- **Región / AD OCI:** [ej. sa-saopaulo-1 / AD-1]
- **Shape Aprovisionado:** VM.Standard.A1.Flex (ARM64, 4 OCPU, 24 GB RAM)
- **Versión de OS:** Ubuntu 24.04 LTS (Linux kernel aarch64)

## 2. Evidencias de Verificación
- **OCI Security List:** Puerto 22 cerrado a internet público [VERIFICADO]
- **SSH Individual:** 5 cuentas creadas con llaves ed25519 [VERIFICADO]
- **Docker Compose:** Tag desplegado: [tag / commit hash]
- **Redis Health:** docker compose exec redis redis-cli ping -> PONG [VERIFICADO]
- **API Health:** curl http://127.0.0.1:8000/health -> {"status":"ok"} [VERIFICADO]
- **Prueba E2E L0:** scripts/test_e2e.sh completado con código 0 [VERIFICADO]
- **Binds de Red:** 127.0.0.1:8000 y 127.0.0.1:6379 estrictos [VERIFICADO]

## 3. Incidentes y Desviaciones
- [Ninguno / Detallar cualquier ajuste realizado durante el bootstrap]

## 4. Dictamen Final
La infraestructura del VPS Oracle se encuentra aprovisionada, endurecida y lista para recibir tráfico operativo de Jericó AI-OS bajo arquitectura Zero-Trust.
```
