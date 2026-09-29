# Especificación Arquitectónica de Jericó v2 (SPEC_JERICO_V2)

**Documento Canónico de Arquitectura de Sistemas y Transferencia Tecnológica**
**Organización:** Kaisen AI
**Autor:** Santiago Gonzalez (CTO) & Equipo de Arquitectura
**Fecha:** 29 de septiembre de 2026
**Referencia upstream:** [`nousresearch/hermes-agent`](https://github.com/nousresearch/hermes-agent)
**Estado:** Aprobado para implementación por fases

---

## 1. Resumen ejecutivo

Jericó v2 constituye la evolución arquitectónica de Jericó desde un servicio reactivo stateless (FastAPI v0.2.0)
hacia un sistema operativo de inteligencia artificial autónomo (AI-OS) de grado productivo para Kaisen AI.
Tomando como referencia la ingeniería de sistemas de Hermes Agent (Nous Research), esta especificación
formaliza un núcleo de cintura estrecha (*narrow waist*) sustentado en dos invariantes absolutos: la inmutabilidad
estricta del prompt del sistema para preservar el *prompt caching* por sesión, y la delegación de capacidades a los
bordes mediante herramientas gobernadas por compuertas de servicio (`check_fn`) y el estándar de habilidades `SKILL.md`.
La arquitectura introduce un bucle de turnos agéntico modular (descompuesto bajo el patrón Fachada + Hermanos),
persistencia transaccional en SQLite WAL con diagnóstico forense de bloqueos por PID (`/proc/<pid>/fd`), compresión
de contexto en dos capas (poda determinista sin coste + resumen estructurado con modelo auxiliar) y un curador
autónomo accionado por inactividad. Todo el diseño preserva rigurosamente el stack económico y soberano de Kaisen AI:
modelos estrictamente pineados sin alias flotantes (`glm-5.3-flash` en L1, `deepseek-flash` en L2), despliegue
optimizado para Oracle Cloud Free Tier (Ampere A1 ARM64) y un arnés de calidad innegociable (cobertura ≥ 89%).

---

## 2. Objetivos y no-objetivos de Jericó v2

### Objetivos
1. **Bucle de Turnos Agéntico Determinado (`AgentTurnLoop`):** Sustituir el actual endpoint síncrono de un solo paso por un ciclo agéntico desacoplado capaz de iteración multi-vuelta autónoma, despacho coordinado de herramientas, validación de retornos y autorrecuperación determinista ante anomalías.
2. **Invariante de Prompt Caching Sagrado:** Garantizar la estabilidad binaria byte por byte del *system prompt* durante toda la sesión para reutilizar el prefijo de contexto (*KV-cache* del proveedor) y reducir costos y latencia hasta en un 90%, canalizando instrucciones dinámicas, marcas temporales y memorias en mensajes de rol `user` o `tool`.
3. **Persistencia Durable SQLite WAL con Diagnóstico Forense:** Sustituir la memoria volátil en RAM/Redis por `jerico_state.db` operando bajo `PRAGMA journal_mode=WAL` y `PRAGMA synchronous=NORMAL`, incorporando deduplicación de prompts por hash SHA-256, linaje de sesiones (`parent_session_id`), índice FTS5 trigram para búsqueda histórica e inspección de `/proc/<pid>/fd` para resolver contenciones de bloqueo por PID.
4. **Compresión de Contexto Jerárquica en Dos Capas:** Implementar una gestión inteligente de ventana de contexto: Capa 1 de poda determinista de bajo costo (truncado de payloads masivos de herramientas antiguas sin llamada al LLM) y Capa 2 de resumen estructurado mediante modelo auxiliar económico, asegurando retención incondicional de los últimos $N$ turnos y directivas de seguridad.
5. **Catálogo de Herramientas de Cintura Estrecha (*Narrow Waist*):** Estructurar el inventario de herramientas con compuertas de disponibilidad (`check_fn` con TTL-cache), segregación de posturas operativas (`coding`, `ops`, `personal`, `default`) y aislamiento de entornos de ejecución (subproceso local vs contenedor Docker efímero), blindando operaciones mutables bajo el Protocolo Santiago (`confirm=True` + bitácora de auditoría).
6. **Ecosistema de Habilidades (`SKILL.md`) y Curador Autónomo:** Establecer el estándar formal de autoría de habilidades operativas de Kaisen AI con auditoría estricta de portabilidad y un Curador en segundo plano accionado por periodos de inactividad de usuario para transicionar, archivar y consolidar habilidades obsoletas sin consumo de CPU en caliente.
7. **Omni-Gateway Unificado y Planificador de Tareas (Cron):** Proveer un punto de entrada desacoplado multi-superficie (Telegram con notas de voz transcribibles, Siri Shortcuts conciso, CLI interactivo y API REST) coordinado con un planificador de fondo (`jerico.cron`) para watchdogs de infraestructura (Docker, PostgreSQL) y sincronizaciones asíncronas.
8. **Preservación del Arnés de Calidad e Infraestructura:** Mantener el 100% de verificaciones verdes (`verify.sh`), tipado estricto mypy, cobertura de código $\ge 89\%$ y compatibilidad estricta con el entorno ARM64 Ampere de Oracle Free Tier.

### No-objetivos
1. **Frameworks de Terceros Monumentales:** Queda estrictamente prohibido introducir dependencias de cajas negras como LangChain, LangGraph, CrewAI, AutoGen o Celery. Toda la orquestación se construye sobre Python 3.12 nativo, FastAPI y asyncio.
2. **Uso de Modelos Flotantes en Producción:** Queda terminantemente vetado el uso de sufijos o alias flotantes (`-latest`, `-preview`) en la configuración de LLMs, evitando regresiones silenciosas en producción (lección aprendida TaxisMVP).
3. **Streaming de Audio en Tiempo Real (Live API):** Jericó v2 no implementará WebSockets bidireccionales ni APIs multimodales de baja latencia tipo Gemini Live API debido a sus costos y falta de soporte de clonación soberana. El flujo de voz se mantiene push-to-talk half-duplex (STT local `faster-whisper` + TTS `fish-s1-mini`).
4. **Monolito de Herramientas en el Núcleo (*Fat Core*):** No se integrarán APIs especializadas o conectores externos específicos en el esquema base del modelo; cualquier nueva integración debe incorporarse como comando CLI + skill, servidor MCP o compuerta `check_fn`.
5. **Requerimiento de GPU Dedicada en el Nodo Central:** El núcleo de Jericó no dependerá de hardware gráfico en el nodo principal (Oracle VM.Standard.A1.Flex); las cargas de inferencia de voz pesadas se delegan a workers externos o ejecución CPU cuantizada.

---

## 3. Arquitectura objetivo: módulos, responsabilidades, límites y diagrama ASCII

### Módulos y responsabilidades

1. **`jerico.agent` (Núcleo de Turnos Agénticos):**
   - `conversation_loop.py`: Fachada pública del bucle de turnos agéntico. Orquesta el flujo iterativo del agente manteniendo invariantes de alternancia de roles.
   - `turn_preflight.py`: Adquisición de leases de sesión, verificación de presupuesto de iteraciones y chequeo previo de presión de tokens.
   - `turn_request_assembly.py`: Ensamblado de payloads de solicitud garantizando system prompt byte-estable y mensajes efímeros (`user`/`tool`).
   - `turn_api_call.py`: Ejecución de llamadas HTTP interruptibles contra endpoints OpenAI-compatibles con streaming y reintentos jittered.
   - `turn_api_error.py`: Clasificación taxonómica de excepciones (429, 5xx, timeout, formato inválido) y activación de escalera de reintentos.
   - `turn_tool_round.py`: Despacho concurrente/secuencial de herramientas, validación de esquemas e intercepción de confirmaciones.
   - `turn_overflow.py`: Detección temprana de sobrepresión de ventana de contexto (>80% de utilización).
   - `turn_context_compaction.py`: Algoritmo de compactación de contexto en dos capas (poda zero-cost + resumen auxiliar).
   - `turn_recovery.py`: Escalera de autorrecuperación escalonada ante respuestas vacías, errores de formato o fallos del proveedor.
   - `turn_finalizer.py`: Contabilidad de tokens, cálculo de costes, emisión de respuesta final y persistencia de estado.

2. **`jerico.gateway` (Capa de Acceso Omnicanal):**
   - `runner.py`: Despachador asíncrono y gestor del ciclo de vida de peticiones provenientes de múltiples superficies.
   - `session_lease.py`: Coordinación de acceso exclusivo por sesión para evitar condiciones de carrera entre canales concurrentes.
   - `platforms/`: Adaptadores desacoplados de entrada/salida (`telegram.py`, `siri.py`, `cli.py`, `rest.py`).
   - `stream_consumer.py`: Manejador de eventos de streaming, pensamiento (*reasoning*) y retroalimentación de estado al usuario.

3. **`jerico.state` (Persistencia y Linaje Transaccional):**
   - `db.py`: Conexión SQLite WAL, pragmas de alto rendimiento (`synchronous=NORMAL`, `busy_timeout=60000`) y pool de lectura.
   - `schema.py`: Definición y migración de esquemas DDL (sesiones, mensajes, system prompts por hash, uso por modelo).
   - `lockowners.py`: Escáner forense de contención de bloqueos mediante inspección de `/proc/<pid>/fd`.
   - `fts.py` / `search.py`: Tabla virtual FTS5 trigram para búsqueda léxica sobre el historial completo sin RAG pesado.

4. **`jerico.tools` (Catálogo de Herramientas y Aislamiento):**
   - `registry.py`: Registro dinámico de herramientas con compuertas `check_fn` y almacenamiento en caché TTL.
   - `toolsets.py`: Conjuntos de herramientas agrupados por postura operativa (`coding`, `ops`, `personal`, `default`).
   - `approval.py`: Guardián de seguridad del Protocolo Santiago para intercepción y confirmación de operaciones no-readonly.
   - `environments/`: Abstracciones de ejecución de terminal y comandos (`local.py`, `docker.py`).

5. **`jerico.skills` (Habilidades Autónomas y Curación):**
   - `loader.py`: Descubrimiento y parseo de paquetes `SKILL.md` desde `skills/`.
   - `validator.py`: Linter hardline de estándares de autoría (longitud de descripción, invocación de tools nativas, aislamiento OS).
   - `curator.py`: Orquestador en segundo plano para mantenimiento de ciclo de vida accionado por inactividad (`active` $\to$ `stale` $\to$ `archived`).

6. **`jerico.llm` (Cliente de Inferencia y Contabilidad):**
   - `llm_client.py`: Cliente asíncrono multi-modelo con pooling de conexiones, soporte de prefijo de caché y fallback determinista.
   - `token_accounting.py`: Registro granular de tokens de entrada, salida, razonamiento y caché reportados por el proveedor.

7. **`jerico.cron` (Planificador de Fondo y Watchdogs):**
   - `scheduler.py`: Planificador ligero asíncrono de tareas recurrentes con control de huérfanos y límites de ejecución.
   - `jobs/`: Tareas de monitoreo y mantenimiento (watchdog de Docker, sincronización YouTrack/Notion, copias de seguridad de `state.db`).

### Diagrama ASCII de Arquitectura

```text
+---------------------------------------------------------------------------------------+
|                                CAPA DE ACCESO Y GATEWAY                               |
|   +------------------+  +------------------+  +------------------+  +-------------+   |
|   | Telegram Bot     |  | Siri Shortcuts   |  | CLI / REPL       |  | REST / Web  |   |
|   | (Voice STT / PT) |  | (Concise REST)   |  | (Interactive)    |  | (/api/v1)   |   |
|   +--------+---------+  +--------+---------+  +--------+---------+  +------+------+   |
|            |                     |                     |                   |          |
|            +---------------------+----------+----------+-------------------+          |
|                                             |                                         |
|                                    [ Gateway Runner ]                                 |
|                         (Session Lease Guard & Rate Limiter)                          |
+---------------------------------------------+-----------------------------------------+
                                              |
                                              v
+---------------------------------------------------------------------------------------+
|                          NÚCLEO DEL AGENTE (THE NARROW WAIST)                         |
|                                                                                       |
|   +-------------------------------------------------------------------------------+   |
|   | Agent Turn Loop (Facade + Siblings)                                           |   |
|   |                                                                               |   |
|   |  [turn_preflight]  ---> [turn_request_assembly] ---> [turn_api_call]              |   |
|   |          ^                        |                          |                    |   |
|   |          |                        v                          v                    |   |
|   |  [turn_context_compaction] <-- [turn_overflow]     [turn_tool_round]              |   |
|   |          |                        ^                          |                    |   |
|   |          v                        |                          v                    |   |
|   |  [turn_recovery]   -------------------------------> [turn_finalizer]              |   |
|   +--------------------------------------------------------------+----------------+   |
|                                                                  |                    |
|                +-------------------------------------------------+                    |
|                |                                                                      |
|                v                                                                      v
|   +--------------------------+                               +--------------------+   |
|   | LLM Client (AsyncOpenAI) |                               | Tool Registry      |   |
|   | - L1: GLM-5.3-Flash      |                               | - check_fn + TTL   |   |
|   | - L2: DeepSeek-Flash     |                               | - Posture Toolsets |   |
|   | - Prompt Caching (KV)    |                               | - Protocol Santiago|   |
|   +--------------------------+                               +---------+----------+   |
+------------------------------------------------------------------------|--------------+
                                                                         |
                +--------------------------------------------------------+
                |
                v
+---------------------------------------+     +-----------------------------------------+
| ENTORNOS DE EJECUCIÓN (SANDBOXING)    |     | PERSISTENCIA Y ESTADO (STATE ENGINE)    |
|                                       |     |                                         |
| +-----------------------------------+ |     | +-------------------------------------+ |
| | Local Environment (Subprocess PTY)| |     | | SQLite WAL (jerico_state.db)        | |
| +-----------------------------------+ |     | | - system_prompts (SHA-256 deduplic.)| |
| +-----------------------------------+ |     | | - sessions & lineage (parent_id)    | |
| | Docker Sandbox (Isolated Runner)  | |     | | - messages (append-only transcript) | |
| +-----------------------------------+ |     | | - session_model_usage (tokens/cost) | |
|                                       |     | +-------------------------------------+ |
| +-----------------------------------+ |     | +-------------------------------------+ |
| | Integration Adapters              | |     | | FTS5 Full-Text Search (Trigram)     | |
| | - YouTrack / Notion / Host Monitor| |     | +-------------------------------------+ |
| +-----------------------------------+ |     | +-------------------------------------+ |
|                                       |     | | Lockowner Scanner (/proc/<pid>/fd)  | |
+---------------------------------------+     | +-------------------------------------+ |
                                              +-----------------------------------------+
                                                                   ^
                                                                   |
+------------------------------------------------------------------+--------------------+
| ECOSISTEMA DE HABILIDADES Y CURADOR AUTÓNOMO                                          |
|                                                                                       |
|   +-------------------------+  +-------------------------+  +---------------------+   |
|   | Skills Loader & Linter  |  | Inactivity Curator      |  | Scheduler (Cron)    |   |
|   | - Standard SKILL.md     |  | - Idle Trigger (>2h)    |  | - Docker Watchdog   |   |
|   | - Hardline Constraints  |  | - Active->Stale->Archive|  | - State DB Backups  |   |
|   | - Native tool references|  | - Auxiliary model fork  |  | - YouTrack Sync     |   |
|   +-------------------------+  +-------------------------+  +---------------------+   |
+---------------------------------------------------------------------------------------+
```

---

## 4. Mejoras derivadas de Hermes

| # | Mejora | Patrón de referencia (repo Hermes) | Encaje en Jericó | Riesgo |
|---|:---|:---|:---|:---|
| 1 | Descomposición modular del Agent Turn Loop | `agent/conversation_loop.py`, `agent/turn_*.py` | Sustituir la función monolítica `ask()` de `api.py` por fases atómicas desacopladas (`turn_preflight`, `turn_request_assembly`, `turn_api_call`, `turn_tool_round`, `turn_finalizer`). | Complejidad añadida en el flujo de control y acoplamiento de contratos entre siblings si no se definen dataclasses inmutables de paso. |
| 2 | Invariante sagrado de Prompt Caching | `agent/system_prompt.py`, `agent/turn_request_assembly.py` | Congelar byte por byte el prompt del sistema durante toda la sesión en `jerico.llm`; inyectar contexto dinámico (fecha/hora, memorias, skills) exclusivamente en mensajes de rol `user` o `tool`. | Invalidación accidental del KV-cache si un componente intermedio muta cadenas o reordena los esquemas de herramientas enviados al proveedor. |
| 3 | Persistencia transaccional SQLite WAL y deduplicación de prompts | `hermes_state.py`, `hermes_state_wal.py`, `hermes_state_schema.py` | Reemplazar el almacenamiento en memoria y Redis volátil por `jerico_state.db` con pragmas WAL (`busy_timeout=60000`, `synchronous=NORMAL`) y tabla `system_prompts` indexada por SHA-256. | Contención de concurrencia y contienda de bloqueos entre peticiones entrantes de la API y workers en segundo plano. |
| 4 | Diagnóstico forense de bloqueos de base de datos | `hermes_state_lockowners.py` | Implementar en `jerico.state` un escáner forense que analice `/proc/<pid>/fd` ante excepciones `sqlite3.OperationalError` para registrar el PID, usuario y comando exacto que retiene el bloqueo. | Incompatibilidad si se ejecuta fuera de Linux POSIX (riesgo nulo en despliegue Oracle Linux A1). |
| 5 | Compresión de contexto jerárquica en dos capas | `agent/turn_context_compaction.py`, `agent/conversation_compression.py` | Sustituir el corte arbitrario a 20 mensajes de `memory.py` por Poda Capa 1 (reducción zero-cost de outputs de tools pasadas) y Resumen Capa 2 con modelo L1 (`glm-5.3-flash`), preservando los últimos 10 turnos. | Degradación semántica o pérdida de restricciones operativas en resúmenes generados por modelos ligeros. |
| 6 | Catálogo de herramientas con cintura estrecha (*Narrow Waist*) | `toolsets.py`, `tools/registry.py` | Mantener un esquema base minimalista; compuertas de servicio (`check_fn` con caché TTL) para herramientas no configuradas y selección de toolsets por postura (`coding`, `ops`, `personal`). | Incremento en latencia de arranque si `check_fn` realiza verificaciones de red bloqueantes sin TTL persistente. |
| 7 | Entornos de ejecución aislados (*Sandboxing*) | `tools/environments/local.py`, `tools/environments/docker.py` | Conectar los stubs de `jerico.tools.docker` mediante una interfaz de ejecución (`ExecutionEnvironment`) que despache herramientas críticas a contenedores efímeros aislados. | Sobrecarga de CPU/RAM en la máquina Oracle Free Tier al levantar contenedores Docker bajo demanda para comandos simples. |
| 8 | Ecosistema de habilidades `SKILL.md` con linter hardline | `skills/`, `AGENTS.md` | Estructurar las directivas operativas de Kaisen AI en paquetes autónomos `skills/<cat>/<nombre>/SKILL.md` con descripción concisa $\le 60$ caracteres y referencias exclusivas a herramientas nativas. | Desalineación de los modelos L1/L2 si las instrucciones en Markdown no respetan esquemas deterministas o son ambiguas. |
| 9 | Curador de habilidades accionado por inactividad | `agent/curator.py`, `agent/skill_utils.py` | Demonio ligero en `jerico.skills` que despierta tras inactividad prolongada (>2h inactivo, frecuencia semanal) para transicionar skills en desuso (`active` $\to$ `stale` $\to$ `archived`) sin gastar cómputo en caliente. | Archivar habilidades de contingencia infrecuentes pero críticas si no se protegen con el atributo inmutable `pinned: true`. |
| 10 | Protocolo de aprobación interactiva (Protocolo Santiago) | `agent/turn_tool_round.py`, `tools/approval.py` | Interceptar herramientas con `readonly=False` antes de su despacho, exigiendo confirmación explícita del usuario (`confirm=True`) vía interactividad en Telegram/Siri con registro estricto en `audit.log`. | Bloqueo o timeout del turno conversacional si el usuario no responde en tiempo límite ante la solicitud de confirmación. |
| 11 | Memoria episódica con búsqueda FTS5 trigram | `hermes_state_fts.py`, `hermes_state_search.py` | Indexar el historial de mensajes de `jerico_state.db` en una tabla virtual FTS5 con tokenizador `trigram`, dotando al agente de la herramienta `session_search` sin necesidad de una base vectorial pesada. | Crecimiento no acotado del archivo SQLite WAL si no se configuran tareas periódicas de mantenimiento (`PRAGMA optimize`, checkpoints WAL). |
| 12 | Planificador de fondo desacoplado (*Cron Engine*) | `cron/scheduler.py`, `cron/jobs.py` | Incorporar un scheduler asíncrono para tareas operativas periódicas (watchdog de Docker, verificación de certificados, backups) sin bloquear los hilos de atención del gateway. | Proliferación de procesos zombi o condiciones de carrera si el planificador no maneja timeouts rígidos y cancelación limpia de tareas. |

---

## 5. Contratos de interfaz a alto nivel (nombres y firmas; sin cuerpos de código)

### 5.1 Núcleo del Agente y Turnos

```python
class AgentTurnLoop:
    async def run_turn(
        self,
        session_id: str,
        user_prompt: str,
        *,
        task_id: str | None = None,
        posture: ToolsetPosture = ToolsetPosture.DEFAULT,
        surface: SurfaceType = SurfaceType.REST,
    ) -> TurnResult: ...

    def request_interrupt(self, session_id: str) -> bool: ...


class TurnPreflightGate:
    async def acquire_lease(self, session_id: str, timeout_s: float = 5.0) -> SessionLease: ...
    async def release_lease(self, lease: SessionLease) -> None: ...
    def evaluate_token_pressure(
        self, session_id: str, current_history_tokens: int, window_limit: int
    ) -> TokenPressureLevel: ...


class ContextCompactor:
    def should_compact(
        self, current_tokens: int, max_window: int, threshold: float = 0.80
    ) -> bool: ...

    def prune_tool_results_zero_cost(
        self, messages: list[MessagePayload], preserve_tail_turns: int = 5
    ) -> list[MessagePayload]: ...

    async def compact_history_structured(
        self,
        session_id: str,
        messages: list[MessagePayload],
        *,
        preserve_last_n: int = 10,
        auxiliary_model: str = "glm-5.3-flash",
    ) -> CompactionOutcome: ...
```

### 5.2 Motor de Persistencia y Diagnóstico Forense

```python
class StateEngine:
    def initialize_database(self, db_path: Path) -> None: ...

    def get_or_create_session(
        self,
        session_id: str,
        system_prompt: str,
        model: str,
        parent_session_id: str | None = None,
    ) -> SessionRecord: ...

    def append_message(
        self,
        session_id: str,
        role: MessageRole,
        content: str,
        *,
        tool_calls: list[ToolCallPayload] | None = None,
        tool_call_id: str | None = None,
        reasoning: str | None = None,
    ) -> int: ...

    def get_session_transcript(
        self, session_id: str, limit: int | None = None
    ) -> list[MessageRecord]: ...

    def record_usage(
        self,
        session_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cached_tokens: int = 0,
    ) -> None: ...

    def search_history_fts(self, query: str, limit: int = 10) -> list[SearchResult]: ...

    def scan_database_lockowners(self, db_path: Path) -> list[LockHolder]: ...
```

### 5.3 Catálogo de Herramientas y Entornos de Ejecución

```python
class ToolRegistry:
    def register(
        self,
        tool: BaseTool,
        *,
        check_fn: Callable[[], bool] | None = None,
        check_ttl_s: int = 300,
    ) -> None: ...

    def get(self, name: str) -> BaseTool | None: ...

    def resolve_for_session(
        self, posture: ToolsetPosture, surface: SurfaceType
    ) -> list[ToolSchema]: ...

    async def dispatch(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult: ...


class ExecutionEnvironment:
    async def execute_command(
        self,
        command: str,
        *,
        cwd: Path | None = None,
        timeout_s: float = 60.0,
        env: dict[str, str] | None = None,
    ) -> ProcessExecutionResult: ...

    async def cleanup(self) -> None: ...
```

### 5.4 Sistema de Habilidades y Curador

```python
class SkillEngine:
    def discover_skills(self, directory: Path) -> dict[str, SkillDefinition]: ...
    def validate_skill_manifest(self, manifest_path: Path) -> list[SkillLintIssue]: ...


class Curator:
    def maybe_run_maintenance(
        self, min_idle_hours: int = 2, interval_hours: int = 168
    ) -> CuratorRunSummary: ...

    def apply_lifecycle_transitions(
        self, stale_days: int = 14, archive_days: int = 30
    ) -> list[SkillTransition]: ...
```

### 5.5 Capa de Acceso Omni-Gateway y Planificador

```python
class OmniGateway:
    async def handle_inbound_turn(
        self,
        session_id: str,
        user_prompt: str,
        surface: SurfaceType,
        authorization: str,
    ) -> InboundTurnResponse: ...

    def subscribe_stream(self, session_id: str) -> AsyncIterator[StreamChunk]: ...


class CronScheduler:
    def register_job(
        self,
        job_id: str,
        cron_expression: str,
        callback: Callable[[], Coroutine[Any, Any, None]],
        *,
        max_retries: int = 2,
    ) -> None: ...

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
```

---

## 6. Plan por PRs (máximo 8)

### PR 1: Motor de Persistencia SQLite WAL y Diagnóstico Forense de Bloqueos
- **Alcance:** Creación del paquete `jerico.state`. Implementación de `state.db` con pragmas WAL (`synchronous=NORMAL`, `busy_timeout=60000`), tablas relacionales `system_prompts` (deduplicación SHA-256), `sessions`, `messages` y `session_model_usage`. Implementación de pool de lectura concurrente y escáner forense de descriptores `/proc/<pid>/fd` ante errores de contención `sqlite3.OperationalError`.
- **Rutas objetivo:** `src/jerico/state/__init__.py`, `src/jerico/state/db.py`, `src/jerico/state/schema.py`, `src/jerico/state/lockowners.py`, `src/jerico/state/messages.py`.
- **Tests requeridos:** `tests/test_state_wal_lifecycle.py`, `tests/test_state_lockowners.py`, `tests/test_state_dedup.py`.
- **Criterio de aceptación:** Ejecución impecable de `./scripts/verify.sh` (ruff, mypy, pytest), sin regresión en los 173 tests existentes, cobertura total del proyecto $\ge 89\%$.

### PR 2: Invariante de Prompt Caching e Inmutabilidad del System Prompt
- **Alcance:** Creación de `prompt_builder.py` y refactorización de `llm_client.py`. Garantizar que el *system prompt* sea estricto, byte-estable e inmutable por sesión (registrado por su hash SHA-256). Inyección de contexto dinámico (marcas temporales, perfiles de usuario, directivas de memoria) dentro de mensajes efímeros de rol `user` o `tool`. Soporte de metadatos de tokens de caché en respuestas de proveedor.
- **Rutas objetivo:** `src/jerico/agent/prompt_builder.py`, `src/jerico/agent/turn_request_assembly.py`, `src/jerico/llm_client.py`.
- **Tests requeridos:** `tests/test_prompt_caching_invariant.py`, `tests/test_turn_request_assembly.py`, `tests/test_llm_cache_accounting.py`.
- **Criterio de aceptación:** `./scripts/verify.sh` verde, verificación de estabilidad de hash SHA-256 en llamadas consecutivas, cobertura total $\ge 89\%$.

### PR 3: Bucle de Turnos Agéntico Modular (Patrón Facade + Siblings)
- **Alcance:** Implementación de `AgentTurnLoop` estructurado en hermanos modulares bajo `jerico/agent/`. Incluye adquisición de lease de sesión (`turn_preflight`), llamada interruptible a API LLM (`turn_api_call`), manejo de errores y reintentos con backoff exponencial (`turn_api_error`), procesamiento e intercepción de llamadas a herramientas (`turn_tool_round`), alternancia estricta de roles y finalización con persistencia en `state.db` (`turn_finalizer`).
- **Rutas objetivo:** `src/jerico/agent/__init__.py`, `src/jerico/agent/conversation_loop.py`, `src/jerico/agent/turn_preflight.py`, `src/jerico/agent/turn_api_call.py`, `src/jerico/agent/turn_tool_round.py`, `src/jerico/agent/turn_finalizer.py`.
- **Tests requeridos:** `tests/test_turn_loop_orchestration.py`, `tests/test_turn_phases_isolation.py`, `tests/test_role_alternation.py`.
- **Criterio de aceptación:** `./scripts/verify.sh` verde, prueba de ejecución agéntica multi-vuelta simulada con mocks deterministas, cobertura $\ge 89\%$.

### PR 4: Compresión de Contexto en Dos Capas (Poda Zero-Cost y Resumen Auxiliar)
- **Alcance:** Detección preventiva de umbral de contexto (>80% de ventana) en `turn_overflow.py`. Capa 1 de poda determinista de bajo costo: reemplazo de volcados masivos de resultados de herramientas antiguas por marcadores breves de resumen sin invocar LLMs. Capa 2: resumen estructurado del historial intermedio mediante modelo económico auxiliar (`glm-5.3-flash`), preservando los últimos 10 mensajes intactos y enlazando sesiones mediante `parent_session_id`.
- **Rutas objetivo:** `src/jerico/agent/turn_overflow.py`, `src/jerico/agent/turn_context_compaction.py`, `src/jerico/agent/compression.py`.
- **Tests requeridos:** `tests/test_context_overflow_detection.py`, `tests/test_zero_cost_pruning.py`, `tests/test_structured_compression.py`.
- **Criterio de aceptación:** `./scripts/verify.sh` verde, verificación de reducción de tokens preservando invariantes de alternancia, cobertura $\ge 89\%$.

### PR 5: Tool Registry de Cintura Estrecha, `check_fn` y Entornos de Ejecución
- **Alcance:** Reestructuración de `jerico.tools` bajo el principio de cintura estrecha (*narrow waist*). Adición de compuertas de servicio `check_fn` con caché TTL en el registro, configuración de conjuntos de herramientas según la postura operativa (`coding`, `ops`, `personal`, `default`), abstracción de entornos de ejecución `ExecutionEnvironment` (local PTY vs Docker sandboxed) y formalización del Protocolo Santiago para herramientas mutables (`readonly=False`).
- **Rutas objetivo:** `src/jerico/tools/registry.py`, `src/jerico/tools/toolsets.py`, `src/jerico/tools/approval.py`, `src/jerico/tools/environments/base.py`, `src/jerico/tools/environments/local.py`, `src/jerico/tools/environments/docker.py`.
- **Tests requeridos:** `tests/test_tools_registry_gating.py`, `tests/test_toolsets_resolution.py`, `tests/test_approval_protocol.py`, `tests/test_execution_environments.py`.
- **Criterio de aceptación:** `./scripts/verify.sh` verde, auditoría estricta de bloqueos `confirm=True`, cobertura $\ge 89\%$.

### PR 6: Sistema de Habilidades (`SKILL.md`), Linter de Autoría y Curador por Inactividad
- **Alcance:** Módulo `jerico.skills` para carga de paquetes de habilidades en `skills/<categoria>/<nombre>/SKILL.md`. Linter estricto de estándares de calidad (longitud de descripción $\le 60$ caracteres, mención exclusiva de herramientas nativas, compatibilidad de plataformas declarada). Implementación del Curador autónomo (`curator.py`) accionado por inactividad de usuario (>2h de inactividad, ciclo de 7 días) para transicionar habilidades (`active` $\to$ `stale` $\to$ `archived`).
- **Rutas objetivo:** `src/jerico/skills/__init__.py`, `src/jerico/skills/loader.py`, `src/jerico/skills/validator.py`, `src/jerico/skills/curator.py`.
- **Tests requeridos:** `tests/test_skill_parser.py`, `tests/test_skill_linter_rules.py`, `tests/test_curator_lifecycle.py`.
- **Criterio de aceptación:** `./scripts/verify.sh` verde, validación de inactividad y protección de habilidades `pinned: true`, cobertura $\ge 89\%$.

### PR 7: Memoria Episódica con Búsqueda FTS5 Trigram e Introspección
- **Alcance:** Creación de la tabla virtual `messages_fts` en `state.db` utilizando el tokenizador `trigram` de SQLite FTS5. Módulo de búsqueda léxica y ranking BM25 para consultas históricas sobre turnos previos de conversación. Integración de la herramienta de introspección del agente `session_search` permitiendo a Jericó recordar decisiones de arquitectura e incidencias previas sin frameworks vectoriales pesados.
- **Rutas objetivo:** `src/jerico/state/fts.py`, `src/jerico/state/search.py`, `src/jerico/tools/session_search.py`.
- **Tests requeridos:** `tests/test_fts5_indexing.py`, `tests/test_session_search_query.py`, `tests/test_session_search_tool.py`.
- **Criterio de aceptación:** `./scripts/verify.sh` verde, pruebas de búsqueda sobre transcripciones multilingües, cobertura $\ge 89\%$.

### PR 8: Omni-Gateway Unificado (Telegram, Siri, CLI, REST) y Scheduler de Fondo
- **Alcance:** Punto de entrada unificado `jerico.gateway` que enruta eventos desde Telegram (con soporte para notas de voz transcribibles con `faster-whisper`), Siri Shortcuts (respuestas concisas), CLI interactivo y API FastAPI `/api/v1/ask` delegando en el `AgentTurnLoop`. Implementación de `jerico.cron` para jobs periódicos desacoplados (watchdog de Docker, sincronizaciones de estado y rotación de backups SQLite WAL).
- **Rutas objetivo:** `src/jerico/gateway/runner.py`, `src/jerico/gateway/platforms/telegram.py`, `src/jerico/gateway/platforms/siri.py`, `src/jerico/cron/scheduler.py`, `src/jerico/cron/jobs.py`, `src/jerico/api.py`.
- **Tests requeridos:** `tests/test_gateway_omnichannel.py`, `tests/test_cron_scheduler.py`, `tests/test_api_v2_backward_compat.py`.
- **Criterio de aceptación:** `./scripts/verify.sh` verde con suite completa de 173+ tests pasando, cero degradación de compatibilidad con clientes existentes, cobertura global $\ge 89\%$.

---

## 7. Riesgos, mitigaciones y rollback

### Matriz de Riesgos Técnicos

1. **Riesgo:** Bloqueos concurrentes en SQLite WAL (`database is locked`) entre el Gateway multi-hilo y las tareas de fondo del Cron/Curador.
   **Mitigación:** Configuración mandatoria de pragmas `busy_timeout=60000`, `synchronous=NORMAL`, segregación de conexiones en un pool de solo lectura para búsquedas (`readpool`) y despliegue del módulo forense `hermes_state_lockowners` para identificar PIDs contrapuestos.

2. **Riesgo:** Invalidación involuntaria de Prompt Caching por variaciones sutiles en llamadas consecutivas (mutaciones de whitespace, fecha dinámica en system prompt o reordenamiento de tools).
   **Mitigación:** Deduplicación estricta de system prompts por hash SHA-256 antes del envío a la API; prohibición absoluta de variables de entorno o marcas de tiempo en el system prompt; ordenamiento canónico alfabético de los esquemas de herramientas enviados al proveedor; tests de regresión que verifiquen la igualdad de bytes del prefijo.

3. **Riesgo:** Alucinación o pérdida de directivas críticas durante la Capa 2 de compresión de contexto con modelos de bajo coste.
   **Mitigación:** Preservación incondicional de los últimos $N$ mensajes (`protect_last_n = 10`), preservación del árbol genealógico de sesiones (`parent_session_id`), y plantilla de resumen estructurado determinista con campos explícitos e inmutables (metas activas, acuerdos con el usuario, restricciones de seguridad).

4. **Riesgo:** Ejecución de acciones destructivas o no autorizadas sobre la infraestructura de producción mediante herramientas de shell o Docker.
   **Mitigación:** Blindaje inmutable a nivel de clase (`BaseTool.readonly = True` por defecto); el despachador intercepta llamadas mutables y exige aprobación interactiva con timeout mediante el Protocolo Santiago (`confirm=True`), registrando invariablemente cada intento en `logs/audit.log` antes de interactuar con el entorno de ejecución.

5. **Riesgo:** Latencia acumulada y consumo excesivo de tokens por bucles infinitos en el ciclo de turnos agéntico.
   **Mitigación:** Límite duro de iteraciones por turno (`max_iterations = 8`), presupuesto decreciente de tokens, control estricto de alternancia de roles (rechazo de turnos consecutivos sin avance) y desconexión automática (*circuit breaker*) con respuesta de degradación graciosa al usuario.

### Estrategia de Rollback

- **Conmutador de Motor en Caliente:** La configuración expone `JERICO_ENGINE_VERSION="v2"` por defecto, admitiendo conmutación instantánea a `"v1"` (FastAPI tradicional con memoria volátil) sin requerir re-despliegue del contenedor ni modificaciones de base de datos.
- **Persistencia No Destructiva y Aditiva:** `jerico_state.db` opera de forma completamente aislada a los backends de Redis existentes, permitiendo el desacople total de v2 sin migración inversa ni riesgo de corrupción de datos en ejecución.
- **Validación Continua en Cadena:** Cada uno de los 8 PRs se fusiona garantizando de forma incondicional que la suite completa previa de tests (173 tests iniciales) permanezca verde y la cobertura no descienda del 89%.

---

## 8. Preguntas abiertas para el CTO

1. **Topología de Persistencia Primaria (SQLite WAL vs PostgreSQL 16):** Hermes basa toda su arquitectura en un archivo SQLite WAL local con pool de lectura y diagnóstico de bloqueos por PID. Jericó v1 contemplaba Redis 7 (corto plazo) y PostgreSQL 16 (largo plazo). ¿Validamos adoptar SQLite WAL (`jerico_state.db`) como la fuente de verdad canónica transaccional de sesiones y mensajes (reduciendo a cero la dependencia de base de datos externa en el nodo Oracle Free Tier A1), reservando PostgreSQL únicamente para auditoría corporativa y analítica diferida?
2. **Modelo Asignado a Tareas Auxiliares (Compresión y Curación):** Para la Capa 2 de compresión de contexto y los resúmenes del Curador de habilidades, ¿asignamos `glm-5.3-flash` (L1, $0.075/$0.25 por 1M) para maximizar el ahorro económico del Free Tier, o reservamos `deepseek-flash` (L2) para asegurar máxima fidelidad y razonamiento en la síntesis de decisiones complejas?
3. **Mecanismo de Interacción para el Protocolo Santiago en Canales Desacoplados:** Cuando una herramienta requiera confirmación explícita (`confirm=True`), ¿cuál será el flujo de interacción prioritario para Santiago en movilidad? ¿Implementamos botones interactivos (Inline Keyboard en Telegram con timeout de expiración de 120s) o exigimos una confirmación textual explícita tipo `/aprobar <token>` para evitar activaciones táctiles accidentales?
4. **Política de Seguridad para el Entorno Docker en Oracle VPS:** Para el sandboxing de comandos de infraestructura, ¿se autoriza el montaje del socket `/var/run/docker.sock` del host en el contenedor de Jericó (con acceso a contenedores adyacentes en red privada), o se restringe el entorno de ejecución a un subproceso local con usuario sin privilegios (*least privilege non-root*) para prevenir escape de contenedor?
5. **Autonomía del Curador de Habilidades:** Hermes archiva automáticamente habilidades que no registran uso en 30 días moviéndolas a `skills/.archive/`. En Jericó v2, ¿autorizamos transiciones automáticas a `stale` y `archived` durante los ciclos de inactividad nocturna (siempre reversibles y con bypass para skills `pinned: true`), o el Curador debe limitarse a emitir un informe de recomendación semanal que requiera aprobación manual del CTO?
