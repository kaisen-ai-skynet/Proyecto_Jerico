# Decisiones de Arquitectura del CTO — Proyecto Jericó

Documento formal de registro de decisiones de arquitectura (ADR) tomadas por el CTO para el sistema Jericó. No modifica código existente de forma inmediata; define los lineamientos, motivos, consecuencias y el inventario de archivos a modificar para su posterior implementación técnica.

---

## D1: Base de Datos — PostgreSQL 16 en Producción y SQLite Local/Testing

### Decisión
Adoptar **PostgreSQL 16** como motor de persistencia principal para el entorno de producción. Mantener **SQLite (con modo WAL)** de forma exclusiva para suites de pruebas unitarias/integración automatizadas y entornos de desarrollo local desconectados.
La selección del backend se gobernará mediante la variable de entorno estándar `DATABASE_URL`.
No se debe reescribir la capa de acceso a datos existente (`StateEngine`); se mantendrán los contratos públicos actuales haciéndolos configurables mediante un adaptador o pool de conexiones dinámico según el esquema de la URL (`postgresql://` vs `sqlite:///`).

### Motivo
1. **Concurrencia y Robustez:** Aunque SQLite WAL maneja concurrencia moderada con escritor serializado, PostgreSQL 16 ofrece control de concurrencia multiversión (MVCC) nativo, bloqueos a nivel de fila y escalabilidad para múltiples procesos concurrentes (API, Gateway, Scheduler, workers).
2. **Consultas FTS y Tipado Estricto:** Postgres 16 provee capacidades superiores de indexación de texto completo (`tsvector`/`GIN`), soporte JSONB optimizado y tipos enriquecidos.
3. **Velocidad de Testing:** Preservar SQLite en memoria o archivos efímeros garantiza que las pruebas de regresión en CI/CD y local se ejecuten en subsegundos sin dependencias externas pesadas.

### Consecuencia
- Se requiere desacoplar el uso directo del módulo estándar `sqlite3` en `StateEngine`, abstrayendo la ejecución mediante un protocolo de conexión común o driver compatible (`psycopg` / `asyncpg`).
- Los DDLs de inicialización de esquema (`src/jerico/state/schema.py`) y las consultas FTS5 (`src/jerico/state/fts.py`) deben soportar variantes dialectales o una migración limpia hacia sintaxis ANSI SQL compatible con PostgreSQL.
- Se debe añadir la dependencia del driver PostgreSQL al empaquetador del proyecto.

### Archivos a Modificar
- `src/jerico/config.py`
- `src/jerico/state/db.py`
- `src/jerico/state/schema.py`
- `src/jerico/state/fts.py`
- `src/jerico/state/search.py`
- `src/jerico/state/lockowners.py`
- `pyproject.toml`
- `tests/conftest.py`

---

## D2: Infraestructura — Instancia Dedicada en Oracle Cloud y Seguridad de Red

### Decisión
Desplegar PostgreSQL en un **servidor independiente** aprovisionado en **Oracle Cloud Infrastructure (OCI Always Free, arquitectura ARM Ampere A1, 4 OCPU, 24 GB de memoria RAM)**.
El servicio de PostgreSQL escuchará única y exclusivamente en la interfaz de bucle local (`127.0.0.1` / `localhost`). Queda **estrictamente prohibido** exponer el puerto `5432` hacia redes públicas o direcciones IP externas. El acceso administrativo y la interconexión con otros servicios se realizará exclusivamente mediante red privada de malla **Tailscale** o túneles cifrados **SSH**.
Se implementará un respaldo automatizado nocturno vía `pg_dump`, el cual será inmediatamente comprimido, cifrado y transferido **fuera de esa máquina** hacia un almacenamiento externo seguro.

### Motivo
1. **Aislamiento de Recursos:** Separar la base de datos de los agentes y de las cargas de trabajo de inferencia/gateway evita contención de CPU y agotamiento de RAM. La capacidad Always Free de OCI (4 OCPU ARM y 24 GB RAM) ofrece recursos holgados sin coste recurrente.
2. **Defensa en Profundidad (Cero Exposición Pública):** Cerrar el puerto 5432 y restringir el tráfico a localhost elimina vectores de ataque por fuerza bruta o vulnerabilidades de red en PostgreSQL.
3. **Resiliencia Operativa ante Desastres:** Un volcado nocturno almacenado localmente es inútil si la máquina virtual o la región fallan. La exportación remota garantiza recuperación ante desastres (DRP).

### Consecuencia
- Requiere configuración de políticas de firewall estricto (`ufw` / `iptables` y Security Lists de OCI).
- Configuración de un nodo Tailscale en la máquina de base de datos con reglas de control de acceso (ACLs) específicas para que solo el host de Jericó tenga visibilidad del servicio.
- Creación y mantenimiento de un script de respaldo nocturno cronometrado con rotación de claves y destino remoto (GCS / S3 / máquina secundaria).

### Archivos a Modificar
- `docs/runbook-aprovisionamiento-vps.md`
- `docs/despliegue-vps.md`
- `docs/decisiones/03-despliegue-vps.md`
- `docker-compose.yml`
- `scripts/backup_postgres.sh` (nuevo script de automatización y exportación remota)
- `src/jerico/cron/jobs.py`

### Addendum D2 — 11/10/2026 (revisión por cambio de límites de Oracle)
- **Hecho nuevo:** Oracle redujo el Always Free Ampere A1 de 4 OCPU / 24 GB a **2 OCPU / 12 GB** (comunicado del 21/07/2026; verificado el 30/09/2026, ver Obsidian `Infraestructura/Decision_Arquitectura_Jerico_Oracle_2026-09-30.md`). La premisa "4/24" de esta decisión cayó.
- **Decisión del CTO:** región **Bogotá (`sa-bogota-1`)** y cuenta **Always Free pura** (sin pago por uso).
- **Ajuste de topología:** en lugar de un servidor de base de datos independiente, Fase 0 usa **una sola VM A1 de 2 OCPU / 12 GB** con PostgreSQL 16 en contenedor, publicado **solo en `127.0.0.1:5432`** y accesible para Jericó por la red interna `jerico_net`. Dos VMs de 1/6 consumirían todo el cupo A1 y dejarían cajas pequeñas; se reevalúa con carga real.
- **Se mantienen sin cambios:** 5432 nunca expuesto, acceso solo por Tailscale/SSH, backup nocturno `pg_dump` cifrado y enviado fuera de la VM.
- **Implementación:** `docker-compose.prod.yml`, `scripts/oci/` (bootstrap con ufw, Postgres, backups con age + rclone a OCI Object Storage, cierre perimetral, verificación) y `deploy/oci/` (timer systemd y plantillas). El script previsto como `scripts/backup_postgres.sh` vive en `scripts/oci/backup_postgres.sh`. Guía: `docs/guia-oci-principiantes.md`.
- **Descartado en Fase 0:** contingencia x86 `E2.1.Micro` (rompe la regla ARM64) y Coolify (el puerto 8000 choca con la API; Compose basta).
- **Pendiente de D1 (sin cambio aquí):** el código aún no usa PostgreSQL (`StateEngine` sigue en SQLite); la base queda lista para cuando se implemente D1.

---

## D3: Sandboxing de Herramientas — Subprocess Aislado y Prohibición de docker.sock

### Decisión
Ejecutar las herramientas (*tools*) que involucren ejecución de comandos mediante **procesos subordinados (`subprocess`) aislados**, gobernados por:
1. `timeout` estricto por defecto.
2. Directorio temporal efímero exclusivo por invocación (`tempfile.TemporaryDirectory`).
3. Entorno de variables de entorno saneado (`env` limpio de credenciales, secretos, API keys o tokens del sistema).
4. Límites duros de consumo de memoria y CPU (mediante `resource.setrlimit` en sistemas POSIX / cgroups).

Queda **TERMINANTEMENTE PROHIBIDO** montar o exponer el socket de Docker del host (`/var/run/docker.sock`) dentro de contenedores o entornos de herramientas. Como arquitectura de contenedores a futuro, se migrará hacia **Podman rootless** (en espacio de usuario sin privilegios de root).

### Motivo
1. **Prevención de Escalamiento de Privilegios:** Montar `/var/run/docker.sock` otorga efectivamente privilegios de `root` en el host anfitrión, lo que representa una vulnerabilidad crítica ante inyecciones de comandos generadas por el modelo de lenguaje.
2. **Aislamiento de Secretos:** Si una herramienta ejecuta código arbitrario o scripts de terceros, no debe tener acceso a las variables de entorno de Jericó (`JERICO_LLM_API_KEY`, `DATABASE_URL`, etc.).
3. **Control de Estabilidad:** El agotamiento de memoria por procesos descontrolados o bucles infinitos debe ser mitigado mediante timeouts forzados y límites de memoria del kernel.

### Consecuencia
- El módulo de ejecución en entornos locales debe filtrar exhaustivamente el diccionario `os.environ` antes de pasarlo al subproceso.
- Se debe refactorizar o eliminar cualquier lógica en `src/jerico/tools/docker.py` que intente interactuar con el socket del daemon de Docker de forma privilegiada.
- Se planificará la adopción de Podman rootless para escenarios que requieran empaquetado OCI hermético.

### Archivos a Modificar
- `src/jerico/config.py`
- `src/jerico/tools/environments/base.py`
- `src/jerico/tools/environments/local.py`
- `src/jerico/tools/environments/docker.py`
- `src/jerico/tools/docker.py`
- `src/jerico/tools/registry.py`

---

## D4: Curador de Habilidades — Solo Sugerencias e Integración YouTrack

### Decisión
El mecanismo de curaduría de habilidades (*skills*) operará exclusivamente en **modo sugerencia**, quedando fijada la bandera `curator.auto_archive=false` de manera predeterminada.
Las habilidades que permanezcan inactivas (sin invocación) por más de **7 días** no serán archivadas automáticamente; en su lugar, el sistema generará una sugerencia formal de descarte/optimización y abrirá de manera autónoma un **ticket de revisión en YouTrack**.
Ninguna habilidad será archivada o modificada sin la confirmación y aprobación explícita del CTO.

### Motivo
1. **Gobernanza y Control Humano:** El descarte automático de habilidades por simple paso del tiempo puede degradar capacidades críticas de ejecución de baja frecuencia (ej. tareas de cierre de mes, auditorías o tareas de rescate).
2. **Trazabilidad:** Registrar las sugerencias en YouTrack proporciona un flujo de trabajo auditable con contexto histórico, evitando pérdida accidental de habilidades.

### Consecuencia
- `Curator` en `src/jerico/skills/curator.py` ya no debe aplicar transiciones destructivas directas en el estado en disco sin bandera de confirmación humana.
- Se debe integrar un conector directo hacia el servicio de YouTrack (`src/jerico/tools/youtrack.py`) que tome las transiciones sugeridas y cree las incidencias correspondientes en el tablero del proyecto.
- Se actualizan las firmas y pruebas de ciclo de vida del curador.

### Archivos a Modificar
- `src/jerico/config.py`
- `src/jerico/skills/curator.py`
- `src/jerico/tools/youtrack.py`
- `src/jerico/cron/jobs.py`
- `tests/test_curator_lifecycle.py`

---

## D5: Gateway Omnicanal — Protocolo de Aprobación por Telegram y Respaldo CLI

### Decisión
Establecer **Telegram** como el canal principal e interactivo para la autorización y aprobación de **acciones de alto riesgo** (tales como mutaciones masivas, reinicio de servicios, operaciones de infraestructura o ejecución de herramientas de impacto).
El protocolo implementará:
1. Mensajes interactivos con botones inline `[Aprobar]` y `[Rechazar]`.
2. Restricción criptográfica y contextual: solo el `chat_id` verificado del CTO podrá responder a la solicitud.
3. Expiración y descarte automático: si no se recibe confirmación dentro de los **10 minutos**, la acción se marca automáticamente como **RECHAZADA por expiración temporal**.
4. Canal de respaldo: la interfaz de línea de comandos (**CLI**) se conservará como mecanismo de aprobación secundario/fallback en caso de indisponibilidad de la API de Telegram o ejecuciones locales interactivas.

### Motivo
1. **Seguridad Operativa en Movilidad:** Permite al CTO auditar y autorizar operaciones críticas desde su dispositivo móvil sin necesidad de abrir una sesión SSH o terminal.
2. **Defensa contra Acción no Supervisada:** El rechazo automático a los 10 minutos previene la acumulación de operaciones pendientes que podrían ejecutarse fuera de contexto temporal.
3. **Resiliencia:** Si la red de Telegram presenta degradación o incidentes, la CLI local permite desbloquear manualmente la ejecución.

### Consecuencia
- La interfaz de aprobación (`src/jerico/tools/approval.py`) debe volverse asíncrona y soportar temporizadores de caducidad con estado persistente.
- El adaptador de Telegram (`src/jerico/gateway/platforms/telegram.py`) debe procesar eventos `CallbackQuery` y validar estrictamente el identificador del usuario antes de desbloquear la ejecución de la herramienta.
- La CLI (`src/jerico/gateway/platforms/cli.py`) debe implementar la misma interfaz de consulta de confirmación para fungir como canal de rescate.

### Archivos a Modificar
- `src/jerico/config.py`
- `src/jerico/tools/approval.py`
- `src/jerico/gateway/runner.py`
- `src/jerico/gateway/platforms/telegram.py`
- `src/jerico/gateway/platforms/cli.py`
- `tests/test_approval_protocol.py`

---

## Lista Consolidada de Archivos a Modificar por Decisión

### Por Decisión D1 (Base de Datos PostgreSQL 16 y SQLite Configurable):
- `src/jerico/config.py`: Definición y validación de `database_url` (Postgres / SQLite).
- `src/jerico/state/db.py`: Adaptación de `StateEngine` para soportar pool de conexiones PostgreSQL y SQLite WAL.
- `src/jerico/state/schema.py`: Definición de esquemas compatibles con DDL de Postgres y SQLite.
- `src/jerico/state/fts.py`: Búsqueda de texto completo compatible con PostgreSQL (`tsvector`/`pg_trgm`) y SQLite FTS5.
- `src/jerico/state/search.py`: Adaptación de sintaxis de consultas de búsqueda.
- `src/jerico/state/lockowners.py`: Adaptación de inspección de bloqueos concurrentes.
- `pyproject.toml`: Inclusión de driver PostgreSQL (`psycopg[binary]` o `asyncpg`).
- `tests/conftest.py`: Configuración de fixtures SQLite para tests rápidos.

### Por Decisión D2 (Infraestructura OCI ARM, Red Privada y Backups):
- `docs/runbook-aprovisionamiento-vps.md`: Procedimiento de aprovisionamiento en Oracle Cloud ARM.
- `docs/despliegue-vps.md`: Guía de despliegue con enlace local 127.0.0.1 y Tailscale.
- `docs/decisiones/03-despliegue-vps.md`: Registro de arquitectura de infraestructura segregada.
- `docker-compose.yml`: Restricción de puertos de base de datos a localhost.
- `scripts/backup_postgres.sh`: Script de volcado nocturno `pg_dump` con cifrado y envío externo.
- `src/jerico/cron/jobs.py`: Registro del job cron de verificación de respaldos.

### Por Decisión D3 (Sandboxing Subprocess, Aislamiento y Sin docker.sock):
- `src/jerico/config.py`: Parámetros de timeout, límites de memoria y directorio temporal del sandbox.
- `src/jerico/tools/environments/base.py`: Contrato base de sandbox con límites de recursos.
- `src/jerico/tools/environments/local.py`: Implementación de subproceso con timeout, `TemporaryDirectory`, sanitización de `env` y `setrlimit`.
- `src/jerico/tools/environments/docker.py`: Eliminación de referencias y montajes a `/var/run/docker.sock`.
- `src/jerico/tools/docker.py`: Restricción o eliminación de operaciones dependientes del socket del host; preparación de Podman rootless.
- `src/jerico/tools/registry.py`: Forzado de ejecución bajo entorno de sandbox para tools de sistema.

### Por Decisión D4 (Curador en Modo Sugerencia e Integración YouTrack):
- `src/jerico/config.py`: Configuración de `curator_auto_archive = False` y umbral de 7 días.
- `src/jerico/skills/curator.py`: Modificación del algoritmo para emitir sugerencias sin auto-archivo.
- `src/jerico/tools/youtrack.py`: Integración de creación de incidencias/tickets para revisión de skills.
- `src/jerico/cron/jobs.py`: Tarea programada de curaduría en modo auditoría.
- `tests/test_curator_lifecycle.py`: Casos de prueba para verificar que no se auto-archive sin confirmación.

### Por Decisión D5 (Aprobación Telegram para Alto Riesgo y Respaldo CLI):
- `src/jerico/config.py`: Variables para chat_id del CTO, timeout de 600 segundos y lista de herramientas de alto riesgo.
- `src/jerico/tools/approval.py`: Protocolo asíncrono con temporizador de expiración de 10 minutos y rechazo automático.
- `src/jerico/gateway/runner.py`: Orquestación del flujo de bloqueo y espera de aprobación en el turno del gateway.
- `src/jerico/gateway/platforms/telegram.py`: Interfaz de botones inline (Aprobar/Rechazar) y validación de `chat_id`.
- `src/jerico/gateway/platforms/cli.py`: Interfaz interactiva de consola para aprobación local de respaldo.
- `tests/test_approval_protocol.py`: Pruebas de integración del flujo de aprobación, rechazo y timeout de 10 min.

---
> 🕒 **Última modificación:** 11/10/2026 18:20 (Claude Code · Opus 5.5)
