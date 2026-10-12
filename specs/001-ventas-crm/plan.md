# Plan 001 — CRM de ventas, fase F1 (CÓMO técnico)

- **Estado:** borrador para el gate del plan (fase 4 SDD). Gate aprobado por delegación del CTO si el reviewer no encuentra bloqueantes.
- **Cambio del 05/10/2026 (fase 6):** decisiones K-1 a K-8 del CTO por delegación (spec §8): §4 (`JERICO_CRM_EXTRA_HOLIDAYS`), §5.1 (festivos extraordinarios), §5.7 y §8.2 (botón «Retractar»), §8.3 (titular sin cierre transitivo, huella mínima de la evidencia, exportación por partes), §10.1 y §13. Nuevos VCRM-163 a VCRM-168.
- **Alcance:** solo los **101 requisitos [F1]** de `spec.md` (§3.8), con §4.1–4.6 y §1.7. F2–F4 quedan fuera; el diseño deja los puntos de extensión, sin implementarlos.
- **Fuentes:** `spec.md` (APROBADA), `opciones.md` (decisiones 1, 2.0, 3 y §8), `docs/constitution.md` (RATIFICADA), `AGENTS.md`, código del núcleo leído: `cron/scheduler.py`, `state/db.py`, `config.py`, `gateway/platforms/telegram.py`, `pyproject.toml`, `scripts/verify.sh`, `Dockerfile`, `docker-compose.yml`, `.env.example`.

---

## 1. Principios de implementación

1. **Convivencia con el núcleo:** todo vive en un paquete nuevo `src/jerico/crm/`. **No se modifica** `gateway/`, `tools/` (incluido `approval.py`), `state/` ni `config.py`. Del núcleo solo se **importa** `jerico.cron.scheduler.CronScheduler` (sin cambios). Los patrones de `state/db.py` (WAL, escritor serializado, `busy_timeout`) se copian, no se reutiliza su base ni `state/schema.py`.
2. **Funciones puras con el tiempo inyectado:** toda regla dependiente del tiempo recibe `now: datetime` (UTC, *aware*) o `today: date` (Bogotá). Ningún módulo de dominio llama a `datetime.now()`; solo `app.py` crea el reloj (`utcnow`).
3. **Puertos para todo lo externo:** Telegram (`TelegramPort`), correo (`EmailSender`), procesos externos de respaldo (`CommandRunner`) y almacén de archivos (`FileStore`) son `Protocol`; los tests usan dobles en memoria. Sin red en ningún test.
4. **SQL portable a PostgreSQL 16** (constitución, punto 4; §1.7): SQL ANSI centralizado en `repo.py`; sin FTS5, sin `INSERT OR IGNORE`, sin `PRAGMA user_version` en el esquema; `ON CONFLICT DO NOTHING` y `RETURNING` (SQLite ≥ 3.35; el entorno tiene 3.53.1); fechas en texto ISO-8601 UTC (`timestamptz` en PG); booleanos `SMALLINT` 0/1.
5. **Sin datos personales fuera de la base:** ni en la bitácora (VCRM-096), ni en logs de `loguru`, ni en mensajes de error del servicio. Los logs solo llevan códigos, identificadores cortos (`L-0042`) e identificadores internos.
6. **Secretos solo por entorno** (constitución, punto 6): token del bot, clave HMAC, credenciales SMTP. En el repositorio, solo nombres de variables (propuesta en §11).

---

## 2. Estructura de archivos

Paquete plano (un módulo por responsabilidad, sin subpaquetes, por simplicidad):

| Archivo | Responsabilidad | Pureza |
| :--- | :--- | :--- |
| `src/jerico/crm/__init__.py` | Marca de paquete; `CURRENT_PHASE = 1`. | — |
| `src/jerico/crm/config.py` | `CrmSettings` (pydantic-settings, prefijo `JERICO_CRM_`), `Params`, `effective_params()` con topes legales (VCRM-162). | `effective_params` pura |
| `src/jerico/crm/timeutil.py` | Zona `America/Bogota`, ISO UTC, Pascua, festivos de Colombia, días hábiles, suma de meses/años. | Pura |
| `src/jerico/crm/model.py` | Enums (`Role`, `LeadState`, `RejectReason`, `AuthStatus`, `NotificationKind`, `Channel`, `OutboxStatus`, `RequestType`, `RequestStatus`, `AlertKind`) y *dataclasses* (`User`, `Lead`, `Note`, `Attachment`, `OutboxItem`, `TitularRequest`, `Alert`). | Pura |
| `src/jerico/crm/states.py` | Tabla de transiciones §4.2 con fase; `check_transition()`. | Pura |
| `src/jerico/crm/permissions.py` | Matriz §4.4 (`Action` × `Role` → `Scope`), `is_visible()`, `authorize()`, `commercial_recipients()`. | Pura |
| `src/jerico/crm/parsing.py` | Parser de `/nuevo`, `/editar` y órdenes F1; `normalize_phone()`, `normalize_email()`, `parse_short_id()`; datos de *callback*. | Pura |
| `src/jerico/crm/fingerprint.py` | Huella HMAC-SHA-256 con rotación de clave. | Pura |
| `src/jerico/crm/handoff.py` | Campos del handoff, validación (VCRM-112) y completitud (VCRM-111). | Pura |
| `src/jerico/crm/render.py` | Textos del bot y de notificaciones; contenido limitado para el abogado (VCRM-156); paginación (VCRM-090); troceo a 4096 caracteres. | Pura |
| `src/jerico/crm/db.py` | `CrmDatabase`: conexión WAL, escritor serializado, `tx()`, DDL y versión de esquema. | E/S |
| `src/jerico/crm/repo.py` | Todas las consultas SQL (usuarios, leads, eventos, notas, adjuntos, autorizaciones, supresión, solicitudes, *outbox*, alertas, auditoría, eventos procesados, entradas pendientes, metadatos). | E/S |
| `src/jerico/crm/ports.py` | `Protocol`s y tipos de intercambio: `TelegramPort`, `Update`, `InlineButton`, `SendResult`, `EmailSender`, `CommandRunner`, `FileStore`. | — |
| `src/jerico/crm/telegram.py` | `HttpxTelegramClient` (Bot API, long polling). | E/S |
| `src/jerico/crm/mail.py` | `SmtpEmailSender` (smtplib en hilo), `UnconfiguredEmailSender`, `build_email_sender()`. | E/S |
| `src/jerico/crm/files.py` | `LocalFileStore`: escritura atómica, borrado idempotente, límite de 20 MB. | E/S |
| `src/jerico/crm/outbox.py` | Calendario 0/1/5 min (puro), `enqueue_critical()`, `OutboxWorker` y cadena de escalado (VCRM-050, 107, 128–130, 155). | Mixta |
| `src/jerico/crm/team.py` | Siembra del CTO, alta y baja de usuarios, reasignación (VCRM-125, 126, 144, 091–093). | Servicio |
| `src/jerico/crm/leads.py` | Registro, duplicados, notas, adjuntos, edición, transiciones, aceptación, retractación, ganado, perdido (Módulos A, B, D). | Servicio |
| `src/jerico/crm/compliance.py` | Autorización, baja, supresión (orden del CTO y por plazo), exportación, solicitudes de titulares. | Servicio |
| `src/jerico/crm/retention.py` | Barrido diario: J-14 (aviso 25 d, supresión 30 d), VCRM-145, 146, 147, escalado y vencimiento de solicitudes, poda de eventos procesados. | Servicio |
| `src/jerico/crm/backup.py` | Respaldo nocturno: instantánea SQLite, empaquetado, cifrado `age`, subida `rclone`, retención (VCRM-097, 098). | Servicio |
| `src/jerico/crm/bot.py` | `CrmBot`: deduplicación de `update_id`, control de identidad, enrutado de órdenes y botones, entradas pendientes, envío de respuestas, bucle de *long polling*. | Servicio |
| `src/jerico/crm/jobs.py` | Registro de los jobs en `CronScheduler`. | — |
| `src/jerico/crm/app.py` | Cableado (`CrmApp`), `main()` del entrypoint `jerico-crm`, latido para *healthcheck*, señales. | E/S |

**Tests** (planos en `tests/`, sin subcarpeta, para evitar el choque de módulos `conftest` en `mypy src/ tests/`): `tests/crm_support.py` (dobles y *harness*, sin fixtures de pytest: funciones `make_harness(tmp_path, now)`) y `tests/test_crm_<área>.py` (24 archivos, ver §10). Convención: **cada test lleva en su nombre el requisito que cubre** (`test_vcrm047_...`), para trazabilidad verificable con `grep`.

**`pyproject.toml` (solo aditivo):**

```toml
[project.optional-dependencies]
crm = ["httpx>=0.27,<1"]

[project.scripts]
jerico-crm = "jerico.crm.app:main"
```

Se añaden esas dos líneas (y la cabecera de la clave `crm` dentro de la tabla existente); nada más cambia.

---

## 3. Modelo de datos (base propia del CRM)

- **Archivo:** `${JERICO_CRM_DATA_DIR}/crm.db` (SQLite WAL), separado de `jerico_state.db`. Adjuntos en `${JERICO_CRM_DATA_DIR}/attachments/<lead_id>/<uuid>`.
- **Conexión** (`db.py`): una conexión escritora protegida por `threading.RLock`, `PRAGMA journal_mode=WAL` (verificado como en `state/db.py`), `PRAGMA foreign_keys=ON`, `PRAGMA busy_timeout=60000`, `isolation_level=None` y `BEGIN IMMEDIATE` explícito en `tx()`. Las lecturas usan la misma conexión (volumen bajo: un proceso, uno o dos comerciales); se descarta el *pool* de lectores de `state/db.py` por innecesario. **Regla obligatoria:** ningún bloque `with db.tx()` contiene un `await` (ni llama a una función asíncrona): el `RLock` es reentrante para el mismo hilo y no impide que dos corrutinas del mismo bucle intercalen sentencias dentro de una transacción abierta; toda E/S de red (Telegram, SMTP, `age`/`rclone`) ocurre antes o después de la transacción. La revisión de código lo comprueba en cada tarea.
- **Versión de esquema:** tabla `crm_meta(key, value)` con `schema_version = 1` (portable; no `PRAGMA user_version`). Los PRAGMAs son de conexión, no de esquema.
- **Mapeo a PostgreSQL 16:** `INTEGER PRIMARY KEY` → `BIGINT GENERATED ALWAYS AS IDENTITY`; `TEXT` de fecha → `timestamptz`; `SMALLINT` igual; marcadores `?` → `%s` (adaptación en un único punto de `repo.py` cuando se migre). Los índices parciales (`WHERE active = 1`) existen en ambos motores.

DDL conceptual (nombres en inglés; todas las fechas-hora en UTC, VCRM-077):

```sql
CREATE TABLE crm_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);           -- schema_version, telegram_offset, last_backup_ok_at

CREATE TABLE crm_users (
  id INTEGER PRIMARY KEY,
  telegram_id BIGINT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('commercial','cto','lawyer')),
  email TEXT NOT NULL,
  active SMALLINT NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, deactivated_at TEXT
);
CREATE UNIQUE INDEX ux_users_active_tg ON crm_users (telegram_id) WHERE active = 1;   -- VCRM-126 (repetido)

CREATE TABLE crm_leads (
  id INTEGER PRIMARY KEY,                       -- identificador corto L-%04d
  assigned_user_id INTEGER REFERENCES crm_users(id),
  state TEXT NOT NULL,                          -- nuevo|contactado|aceptado|rechazado|ganado|perdido|baja (+ F2)
  name TEXT, phone_e164 TEXT, email TEXT, company TEXT,
  client_type TEXT, doc_type TEXT, doc_number TEXT, legal_rep TEXT,
  service TEXT, agreed_value TEXT, start_term TEXT,          -- campos del handoff (§4.3)
  reject_reason TEXT, reject_text TEXT, rejection_is_retraction SMALLINT NOT NULL DEFAULT 0,
  auth_status TEXT NOT NULL DEFAULT 'sin_autorizacion',     -- sin_autorizacion|autorizada|revocada
  ever_accepted SMALLINT NOT NULL DEFAULT 0,                -- visibilidad del abogado (A.1)
  registered_at TEXT NOT NULL, last_interaction_at TEXT NOT NULL,
  accepted_exit_at TEXT,                                    -- reinicio del reloj J-14
  won_at TEXT, final_state_at TEXT,                         -- VCRM-145 / VCRM-146
  legal_hold_basis TEXT, commercial_block SMALLINT NOT NULL DEFAULT 0,   -- VCRM-094
  suppressed_at TEXT, suppression_cause TEXT
);
CREATE INDEX ix_leads_phone ON crm_leads (phone_e164);
CREATE INDEX ix_leads_email ON crm_leads (email);
CREATE INDEX ix_leads_assigned ON crm_leads (assigned_user_id, last_interaction_at);

CREATE TABLE crm_lead_events (               -- historial (VCRM-015, 080, 093, 132); solo INSERT
  id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES crm_leads(id),
  kind TEXT NOT NULL CHECK (kind IN ('state','field','reassign','titular_request')),
  field TEXT, old_value TEXT, new_value TEXT, reason TEXT, reason_text TEXT,
  actor_user_id INTEGER NOT NULL, at TEXT NOT NULL
);
CREATE TABLE crm_notes (id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL, author_user_id INTEGER NOT NULL, body TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE crm_attachments (
  id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('photo','document','voice','authorization')),
  author_user_id INTEGER NOT NULL, at TEXT NOT NULL,
  storage_key TEXT NOT NULL, size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, deleted_at TEXT
);
CREATE TABLE crm_consents (                  -- solo INSERT (VCRM-065, 138); se conserva en la supresión
  id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL, status TEXT NOT NULL, medium TEXT NOT NULL,
  at TEXT NOT NULL, actor_user_id INTEGER NOT NULL, notice_version TEXT, purposes TEXT, attachment_id INTEGER
);
CREATE TABLE crm_suppression (fingerprint TEXT PRIMARY KEY, at TEXT NOT NULL, medium TEXT NOT NULL);   -- VCRM-095
CREATE TABLE crm_titular_requests (
  id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL, type TEXT NOT NULL CHECK (type IN ('consulta','reclamo')),
  medium TEXT NOT NULL, received_on TEXT NOT NULL, due_on TEXT NOT NULL,           -- fechas de Bogotá (YYYY-MM-DD)
  status TEXT NOT NULL DEFAULT 'abierta' CHECK (status IN ('abierta','vencida','atendida')),
  registered_by INTEGER NOT NULL, registered_at TEXT NOT NULL,
  last_escalation_on TEXT, attended_by INTEGER, attended_at TEXT
);
CREATE TABLE crm_outbox (                    -- notificaciones críticas (VCRM-049) y registro de fallos no críticos (VCRM-012)
  id INTEGER PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL, critical SMALLINT NOT NULL, channel TEXT NOT NULL CHECK (channel IN ('telegram','email')),
  recipient_user_id INTEGER NOT NULL, lead_id INTEGER, origin_outbox_id INTEGER,
  subject TEXT, body TEXT,                   -- NULL en fallos no críticos; se purga en la supresión
  status TEXT NOT NULL CHECK (status IN ('pendiente','entregada','fallida')),
  attempts SMALLINT NOT NULL DEFAULT 0, first_attempt_at TEXT, next_attempt_at TEXT,
  last_error TEXT, provider_message_id TEXT, created_at TEXT NOT NULL
);
CREATE INDEX ix_outbox_due ON crm_outbox (status, next_attempt_at);
CREATE TABLE crm_alerts (                    -- VCRM-087, 155, 152
  id INTEGER PRIMARY KEY, lead_id INTEGER, kind TEXT NOT NULL, outbox_id INTEGER, request_id INTEGER,
  created_at TEXT NOT NULL, resolved_by INTEGER, resolved_at TEXT
);
CREATE TABLE crm_audit (                     -- VCRM-002, 075, 086, 096: sin datos de titulares
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, actor TEXT NOT NULL,       -- 'user:<id>' | 'tg:<telegram_id>' | 'system'
  action TEXT NOT NULL, lead_id INTEGER, outcome TEXT NOT NULL, detail_code TEXT
);
CREATE TABLE crm_processed_updates (update_id BIGINT PRIMARY KEY, processed_at TEXT NOT NULL);   -- VCRM-079
CREATE TABLE crm_pending_inputs (user_id INTEGER PRIMARY KEY, kind TEXT NOT NULL, lead_id INTEGER, data TEXT, expires_at TEXT NOT NULL);
CREATE TABLE crm_confirmations (             -- ✅/❌ de aceptación y retractación, idempotentes
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('accept','retract','authorization_question')),
  lead_id INTEGER NOT NULL, user_id INTEGER NOT NULL, reason TEXT, reason_text TEXT,
  status TEXT NOT NULL DEFAULT 'pendiente', created_at TEXT NOT NULL, resolved_at TEXT
);
CREATE TABLE crm_retention_notices (lead_id INTEGER NOT NULL, clock_start TEXT NOT NULL, kind TEXT NOT NULL,
  sent_at TEXT NOT NULL, PRIMARY KEY (lead_id, clock_start, kind));   -- aviso J-14 una sola vez por reloj
```

Notas:

- **Duplicados:** no hay índice único de contacto (VCRM-135 admite repetir el contacto de un «perdido»); la regla se aplica en `leads.register()` dentro de la transacción del escritor serializado, lo que evita la carrera.
- **Auditoría (VCRM-096):** `repo.audit()` acepta solo `action` y `detail_code` de enumeraciones cerradas (`AuditAction`, `AuditDetail`); no existe parámetro de texto libre. Un test recorre la tabla tras un flujo completo y comprueba que no aparecen nombre, teléfono, correo, documento ni texto de notas.
- **Visibilidad del abogado:** `ever_accepted` se pone a 1 al confirmar la primera aceptación y nunca vuelve a 0.

---

## 4. Configuración propia (`config.py`)

`CrmSettings(BaseSettings)` con `SettingsConfigDict(env_prefix="JERICO_CRM_", env_file=".env", extra="ignore")`. No toca `jerico.config.Settings` (que ya ignora variables desconocidas con `extra="ignore"`). **Tests herméticos:** los tests instancian `CrmSettings(_env_file=None, ...)` y una *fixture* aplica `monkeypatch.delenv` a toda variable `JERICO_CRM_*` presente en el entorno, de modo que ni un `.env` local ni el entorno del desarrollador alteran el resultado.

| Variable | Tipo | Por defecto | Uso |
| :--- | :--- | :--- | :--- |
| `JERICO_CRM_TELEGRAM_BOT_TOKEN` | `SecretStr` | ninguno (obligatorio para arrancar) | Bot propio del CRM (token distinto del núcleo). |
| `JERICO_CRM_FINGERPRINT_KEY` / `_PREVIOUS_KEYS` | `SecretStr` | ninguno (obligatorio) / vacío | HMAC de huellas; claves previas separadas por comas solo para comprobar. |
| `JERICO_CRM_SEED_CTO_TELEGRAM_ID`, `_SEED_CTO_EMAIL` | `str` | vacío | Siembra del CTO inicial (VCRM-125, 126). |
| `JERICO_CRM_DATA_DIR` | `Path` | `data/crm` | Base y adjuntos. |
| `JERICO_CRM_SMTP_HOST`, `_PORT`, `_SECURITY` (`starttls`/`ssl`), `_USERNAME`, `_PASSWORD`, `_FROM` | `str`/`int`/`SecretStr` | **sin valor** (decisión P-27) | Correo interno (VCRM-105, 140). |
| `JERICO_CRM_BACKUP_AGE_RECIPIENT`, `_BACKUP_REMOTE` | `str` | sin valor | Respaldo (VCRM-097). |
| `JERICO_CRM_QUERY_DEADLINE_BUSINESS_DAYS` | `int` | 10 (máx. 10) | VCRM-150 |
| `JERICO_CRM_CLAIM_DEADLINE_BUSINESS_DAYS` | `int` | 15 (máx. 15) | VCRM-150, 153 |
| `JERICO_CRM_ESCALATION_BUSINESS_DAYS` | `int` | 2 (máx. 2) | VCRM-151 |
| `JERICO_CRM_WON_ATTACHMENTS_RETENTION_YEARS` | `int` | 10 (mín. 10) | VCRM-145 |
| `JERICO_CRM_FINAL_STATE_SUPPRESSION_MONTHS` | `int` | 12 (máx. 12) | VCRM-146 |
| `JERICO_CRM_UNAUTHORIZED_WARNING_DAYS` / `_MAX_DAYS` | `int` | 25 / 30 (máx. 30; aviso < máximo) | VCRM-158, 159 |
| `JERICO_CRM_BACKUP_RETENTION_DAYS` | `int` | 30 (máx. 30) | VCRM-097 |
| `JERICO_CRM_OUTBOX_INTERVAL_S` / `_POLL_TIMEOUT_S` | `float`/`int` | 5 / 25 | Operación. |
| `JERICO_CRM_EXTRA_HOLIDAYS` | `str` | vacío | Festivos extraordinarios (VCRM-167, 168; §5.1): elementos separados por comas; cada uno es una fecha ISO `AAAA-MM-DD` o la ruta de un archivo de fechas. |

Los campos de plazo se declaran como `int` **sin** restricciones de pydantic (una restricción haría fallar el arranque en vez de aplicar el tope, contra VCRM-162). El tope lo aplica la función pura:

```text
effective_params(settings) -> (Params, list[ConfigWarning])
  LIMITS = {param: (default, kind ∈ {MAX, MIN}, legal_bound)}
  para cada param numérico:
     v = valor configurado
     si v <= 0:                 rige default;     warning(param, v, default)
     si kind=MAX y v > bound:   rige bound;       warning(param, v, bound)
     si kind=MIN y v < bound:   rige bound;       warning(param, v, bound)
     si no:                     rige v            (un valor más estricto que el legal se acepta)
  aviso J-14: si warning_days >= max_days_vigente: rige min(25, max_days_vigente - 1); warning
  return Params(frozen), warnings
```

Al arrancar, cada `ConfigWarning` se registra en el log (parámetro, valor rechazado y valor que rige: no son datos personales) y se envía al CTO por Telegram como notificación no crítica (VCRM-162).

---

## 5. Dominio puro

### 5.1 Tiempo y calendario (`timeutil.py`) — VCRM-077, 150–152, 167, 168

- `BOGOTA = ZoneInfo("America/Bogota")`, con respaldo `timezone(timedelta(hours=-5), "America/Bogota")` si falta la base tz del sistema (Colombia no usa horario de verano desde 1993). Se descarta la dependencia `tzdata` por innecesaria.
- `to_iso(dt)` exige `tzinfo` y serializa en UTC (`...Z`); `from_iso()` devuelve UTC *aware*; `local_date(dt)` → fecha en Bogotá; `format_local(dt)` → `DD/MM/YYYY HH:mm` en Bogotá para todo texto mostrado.
- **Festivos (implementación pura propia; Ley 51 de 1983 «Ley Emiliani»):**

```text
easter(y): algoritmo anónimo gregoriano (Meeus/Jones/Butcher)
next_monday(d): d si d es lunes; si no, el lunes siguiente
colombian_holidays(y) (lru_cache):
  fijos: 1-ene, 1-may, 20-jul, 7-ago, 8-dic, 25-dic
  trasladables a lunes: 6-ene, 19-mar, 29-jun, 15-ago, 12-oct, 1-nov, 11-nov
  Pascua: E-3 (Jueves Santo), E-2 (Viernes Santo),
          next_monday(E+39) Ascensión, next_monday(E+60) Corpus Christi, next_monday(E+68) Sagrado Corazón
is_business_day(d): d.weekday() < 5 y d no está en colombian_holidays(d.year)
add_business_days(d, n): avanza día a día desde d+1 contando solo días hábiles hasta n   (cuenta desde el día hábil siguiente)
business_days_between(a, b): días hábiles en (a, b]
add_months(dt, n) / add_years(dt, n): aritmética de calendario en hora de Bogotá, con recorte a fin de mes (31-ene + 1 mes = 28/29-feb)
```

  Vector de prueba: los 18 festivos de 2026 (Pascua 5-abr): 1-ene, 12-ene, 23-mar, 2-abr, 3-abr, 1-may, 18-may, 8-jun, 15-jun, 29-jun, 20-jul, 7-ago, 17-ago, 12-oct, 2-nov, 16-nov, 8-dic, 25-dic. Se descarta el paquete `holidays` (dependencia nueva para ~30 líneas verificables) y la tabla anual en configuración (mantenimiento manual).

- **Festivos extraordinarios (decisión K-6; VCRM-167, 168).** Se suman a los calculados; el cálculo automático no cambia.

```text
# config.py (pura salvo la lectura de archivo inyectada)
parse_extra_holidays(raw: str, read_text: Callable[[Path], str]) -> (frozenset[date], list[HolidayWarning])
  para cada token de raw.split(',') con strip() no vacío:
    si token empieza por dígito:                               # fecha
       date.fromisoformat exige ^\d{4}-\d{2}-\d{2}$ y fecha real; si no → warning(token, 'fecha no válida; formato AAAA-MM-DD')
    si no:                                                      # ruta de archivo (absoluta o relativa al directorio de trabajo)
       texto = read_text(Path(token)); OSError/UnicodeDecodeError → warning(token, 'archivo no legible: <motivo>'), sigue
       por línea: quitar comentario tras '#', strip; vacía → ignorar; si no, misma validación de fecha
         (warning con '<ruta>:<n.º de línea>: <valor>')
  return frozenset(fechas válidas), warnings                    # duplicados se funden; nunca lanza
HolidayWarning(entry: str, reason: str)                          # aparte de ConfigWarning (cuyo `rejected` es numérico)
Params.extra_holidays: frozenset[date]                            # lo rellena effective_params a partir de la tupla anterior

# timeutil.py: parámetro opcional, por defecto vacío (compatibilidad con T02 y sus tests)
is_business_day(d, extra=frozenset()): d.weekday() < 5 y d ∉ colombian_holidays(d.year) y d ∉ extra
add_business_days(d, n, extra=frozenset()) / business_days_between(a, b, extra=frozenset()): delegan en is_business_day(…, extra)
```

  Formato del archivo: UTF-8, una fecha ISO por línea; líneas vacías y comentarios con `#` admitidos. **Validación con error claro:** cada entrada rechazada produce un `HolidayWarning` con la entrada (o `ruta:línea`) y el motivo; se registra en el log y se envía al CTO por Telegram al arrancar, junto con los `ConfigWarning` de VCRM-162 (cableado en T24). No se aborta el arranque (mismo criterio que D-08): ignorar un festivo mal escrito solo adelanta vencimientos, nunca los retrasa. Los llamadores (T21, T22) pasan `params.extra_holidays`. Descartado: dos variables separadas (fechas y archivo), porque la decisión pide una sola lista configurable y un token por elemento basta; y abortar el arranque, porque dejaría sin CRM por un error tipográfico.

### 5.2 Máquina de estados (`states.py`) — VCRM-013, 014, 117, 133

```text
TRANSITIONS: dict[(origen, destino), fase]
  (nuevo, contactado):1  (rechazado, contactado):1
  (nuevo|contactado|rechazado, aceptado):1
  (nuevo|contactado, rechazado):1   (aceptado, rechazado):1      # retractación
  (aceptado, ganado):1
  (nuevo|contactado|rechazado, perdido):1
  (s, baja):1 para todo s != baja
  filas de F2 (en_nutricion, pausado, reactivado) con fase 2: presentes, filtradas
check_transition(src, dst, phase=CURRENT_PHASE) -> TransitionCheck(ok, error_code, valid_targets)
  si (src,dst) habilitada para phase: ok
  si src=aceptado y dst=perdido: error 'requires_retraction'      # VCRM-133
  si no: error 'not_allowed', valid_targets = destinos habilitados desde src     # VCRM-014
```

`ganado` y `perdido` solo tienen `baja` como destino (VCRM-117); `baja` no tiene destinos.

### 5.3 Permisos (`permissions.py`) — VCRM-085, 086, 109, 134, 136

```text
Scope = NONE | OWN | VISIBLE | ALL
MATRIX[Action][Role] transcribe §4.4 (solo filas F1), p. ej.:
  REGISTER: commercial=ALL(sí), cto=ALL, lawyer=NONE
  NOTE_ATTACH, EDIT, CONTACT_REJECT, ACCEPT, MARK_LOST, REGISTER_OPT_OUT,
  REGISTER_REQUEST, REGISTER_AUTH: commercial=OWN, cto=ALL, lawyer=NONE
  VIEW, RETRACT: commercial=OWN, cto=ALL, lawyer=VISIBLE
  MARK_WON: commercial=NONE, cto=ALL, lawyer=VISIBLE
  ATTEND_REQUEST, EXPORT, SUPPRESS, MANAGE_USERS, REASSIGN, RESOLVE_ALERT: solo cto=ALL
is_visible(user, lead): cto → True; commercial → lead.assigned_user_id == user.id; lawyer → lead.ever_accepted
authorize(user, action, lead|None) -> Decision(allowed, denial ∈ {None,'role','foreign_lead'})
  scope = MATRIX[action][user.role]
  NONE → 'role'          (respuesta VCRM-086; para MARK_WON de un comercial, texto de VCRM-134)
  OWN  → lead.assigned_user_id == user.id, si no 'foreign_lead'   (VCRM-109)
  VISIBLE → is_visible(user, lead), si no 'foreign_lead'          (VCRM-136)
commercial_recipients(lead, users) -> [user]: comercial asignado si está activo y es comercial; si no, el CTO (A.2)
```

Toda denegación se audita (`access_denied` / `permission_denied` / `foreign_lead`) sin datos del lead.

### 5.4 Parser del formato estructurado (`parsing.py`) — §4.3, VCRM-003–005, 081, 082

```text
parse_register(text) -> RegisterCommand | ParseError
  cuerpo = texto tras '/nuevo'; campos = cuerpo.split(';', maxsplit=4); strip de cada uno
  nombre = campos[0]; vacío → ParseError(missing='nombre', example=EJEMPLO_NUEVO)     # VCRM-004
  tel, correo = campos[1], campos[2] (si existen); ambos vacíos → ParseError(missing='contacto')
  tel no vacío → normalize_phone; None → ParseError(invalid='telefono')               # VCRM-005
  correo no vacío → normalize_email; None → ParseError(invalid='correo')
  empresa = campos[3]; nota = campos[4] (conserva ';' internos)
normalize_phone(raw, default_cc='57'):
  s = quitar espacios, guiones, puntos y paréntesis; '00' inicial → '+'
  '+' + 8..15 dígitos sin 0 inicial → '+dígitos'
  10 dígitos sin '+' → '+57' + dígitos    (PR-02; móviles 3xx y fijos 60x)
  otro → None
normalize_email(raw): minúsculas; exige ^[^@\s;]+@[^@\s;]+\.[^@\s;]+$ ; si no → None
parse_edit(text) -> EditCommand(short_id, field, value) | ParseError
  '/editar L-0042; campo; valor' con split(';', maxsplit=2); alias sin tilde (teléfono→telefono)
  campo fuera de EDITABLE → ParseError(code='field_not_editable', editable=EDITABLE)    # VCRM-081
parse_short_id('L-0042'|'l-42') -> int | None
callback data: 'v1:<acción>:<arg>[:<arg>]' ≤ 64 bytes (límite de Telegram); parse_callback() valida.
```

Se descarta `phonenumbers` (metadatos de varios MB para una regla de 10 dígitos colombianos más E.164 explícito).

Órdenes F1 (texto de ayuda en `render.py`): `/nuevo`, `/editar`, `/nota L-n; texto`, `/lista [página]`, `/ver L-n`, `/autorizacion L-n` (seguida de un archivo), `/baja L-n; medio`, `/solicitud L-n; consulta|reclamo; AAAA-MM-DD; medio`, `/solicitudes`, `/atendida S-n`, `/exportar L-n`, `/suprimir L-n[; conservar: campos; fundamento: texto]`, `/alta comercial|abogado; telegram_id; correo`, `/baja_usuario telegram_id`, `/reasignar L-n; telegram_id|cto`, `/usuarios`, `/ayuda`. Adjuntos: foto, documento o nota de voz con el identificador `L-n` en el pie (*caption*). Las acciones de estado se ofrecen como botones en la ficha según la matriz.

### 5.5 Handoff (`handoff.py`) — VCRM-111, 112

- `HANDOFF_FIELDS` = tipo, nombre o razón social, documento, representante, teléfono, correo, servicio, valor, plazo (§4.3).
- `validate_handoff_value(field, value)`: vacío → error; `tipo` ∈ {persona natural, empresa} (comparación sin mayúsculas ni tildes); `documento` = tipo admitido (cédula de ciudadanía, NIT, cédula de extranjería, pasaporte; coincidencia por prefijo más largo) + número no vacío → `(doc_type, doc_number)`.
- `missing_handoff_fields(lead)`: obligatorios sin valor; «nombre o razón social» mira `name` si persona natural y `company` si empresa; representante solo si empresa; tipo sin registrar → faltan «tipo» y «representante (obligatorio si es empresa)».

### 5.6 Huella (`fingerprint.py`) — VCRM-095, 088

`fingerprint(key, normalized) = hex(HMAC-SHA-256(key, normalized_utf8))`; `matches(fp_set, normalized, keys)` prueba la clave actual y las previas. Se calcula sobre el teléfono E.164 y el correo en minúsculas, por separado. Se descarta un hash sin clave (los móviles colombianos son enumerables, opciones §3).

### 5.7 Textos (`render.py`) — VCRM-011, 048, 090, 104, 156

- `render_lead_card(lead, notes, attachments, auth, alerts, viewer)`: contacto, estado, comercial («sin comercial asignado» si el asignado está inactivo), handoff, notas, adjuntos, motivo de rechazo, estado de autorización, próxima acción («no aplica en F1») y alertas activas.
- `render_lead_card` devuelve además `buttons`: «Retractar» (`build_callback('retractar', str(lead_id))`) solo si el lead está en `aceptado` y `can(viewer, RETRACT, lead)` (VCRM-163; decisión K-2).
- `render_list_page(leads, page, size=10)` → texto + botones «Anterior»/«Siguiente» + «página X de Y» (VCRM-090).
- Notificaciones: `acceptance_for_cto`, `acceptance_alert_for_lawyer` (VCRM-104), `acceptance_email_for_lawyer` (VCRM-048), `retraction_*`, `handoff_update_*`, `suppression_copies_*`, `backup_email`, `backup_failure_notice`.
- **Contenido del abogado (VCRM-156):** toda función `*_lawyer` recibe un `LawyerView` construido por `lawyer_view(lead)`, que solo expone identificador, comercial, fechas, estado de autorización y los campos del handoff; así es imposible pasarle notas, adjuntos o historial. Test de propiedad: con notas y adjuntos de texto centinela, ningún texto para el abogado los contiene.
- `split_message(text, limit=4096)`: corta por saltos de línea (o duro si una línea excede); los botones van en el último trozo.

---

## 6. Puertos y adaptadores

### 6.1 Telegram (`ports.TelegramPort`, `telegram.HttpxTelegramClient`)

```python
class TelegramPort(Protocol):
    async def get_updates(self, offset: int | None, timeout_s: int) -> list[Update]: ...
    async def send_message(
        self, chat_id: int, text: str, buttons: list[list[InlineButton]] | None = None
    ) -> SendResult: ...
    async def answer_callback(self, callback_id: str, text: str | None = None) -> None: ...
    async def download_file(self, file_id: str, dest: Path, max_bytes: int) -> DownloadResult: ...
    async def send_document(self, chat_id: int, path: Path, caption: str) -> SendResult: ...
```

- Cliente delgado con `httpx.AsyncClient` (ya transitivo por `openai`; declarado en el extra `crm`). Métodos de la Bot API: `getUpdates` (con `offset`, `timeout`, `allowed_updates=["message","callback_query"]`), `sendMessage` (`reply_markup.inline_keyboard`), `answerCallbackQuery`, `getFile` + descarga en *streaming* con corte al superar `max_bytes`, `sendDocument` (multipart).
- `SendResult(delivered: bool, message_id: str | None, error: str | None, permanent: bool)`: **entregado** solo si `ok=true` y hay `message_id` (§4.5); *timeout* o error → no entregado.
- `Update` normaliza mensaje y `callback_query`: `update_id`, `user_id`, `chat_id`, `chat_type`, `text`, `caption`, `file` (id, tamaño declarado, tipo foto/documento/voz), `callback_id`, `callback_data`.
- El token se usa solo en la URL interna; nunca se registra (los errores se registran con el método y el código HTTP).
- Tests con `httpx.MockTransport` (sin red). Se descartan `python-telegram-bot` y `aiogram` (peso y cintura estrecha; opciones, decisión 1).

### 6.2 Correo (`ports.EmailSender`, `mail.py`) — VCRM-105, 140

```python
class EmailSender(Protocol):
    async def send(self, to: str, subject: str, body: str) -> SendResult: ...
```

- `SmtpEmailSender`: `smtplib.SMTP_SSL` o `SMTP` + `starttls()` con `ssl.create_default_context()`, autenticación, `EmailMessage` con `Message-ID` de `email.utils.make_msgid()`; se ejecuta con `asyncio.to_thread` y *timeout* de 30 s. Entregado = `send_message` sin excepción y sin destinatarios rechazados; `message_id` = el `Message-ID` generado.
- `UnconfiguredEmailSender`: devuelve `SendResult(delivered=False, permanent=True, error='mailbox_not_configured')` sin conectar (VCRM-140).
- `build_email_sender(settings)`: si falta host, puerto, remitente o credenciales → `UnconfiguredEmailSender`.
- **Solo destinatarios internos:** el *outbox* resuelve la dirección desde `crm_users` (correo registrado, VCRM-105); no existe ninguna ruta que reciba una dirección de un lead. Test: tras un flujo completo, todas las direcciones usadas pertenecen a usuarios autorizados.
- Se descartan `aiosmtplib` (dependencia nueva para < 100 correos al día) y una API HTTP de proveedor (acopla a un proveedor; el CTO configura el buzón después, P-27).

### 6.3 Archivos y procesos

- `LocalFileStore.save_atomic(lead_id, tmp_path) -> storage_key` (renombra dentro del mismo volumen), `delete(storage_key)` (archivo ausente = éxito, para reintentos idempotentes), `open(storage_key)`.
- `CommandRunner.run(argv, timeout_s) -> CommandResult(returncode, stderr_tail)` sobre `asyncio.create_subprocess_exec` (sin *shell*, `# noqa: S603` justificado); solo lo usa `backup.py`.

---

## 7. Bot (`bot.py`) — VCRM-001, 002, 012, 079, 086

```text
run_polling(stop):
  offset = repo.get_meta('telegram_offset')
  mientras no stop:
    updates = await telegram.get_updates(offset, timeout=25)   # error de red: espera 5 s y sigue
    para u en updates: await process_update(u); offset = u.update_id + 1
    escribir latido

process_update(u):
  si u trae archivo: prefetch = await descargar_a_temporal(u) si el remitente es usuario activo
                     (tamaño declarado > 20 MB → no descarga; resultado 'too_large')
  with db.tx() as tx:
     si not repo.mark_update_processed(tx, u.update_id, now): borrar temporal; return     # VCRM-079
     repo.set_meta(tx, 'telegram_offset', u.update_id + 1)
     user = repo.active_user_by_telegram(tx, u.user_id)
     si user es None: repo.audit(tx, actor=f'tg:{u.user_id}', action=ACCESS_DENIED, ...); out = []   # VCRM-001/002: silencio
     si u.chat_type != 'private': out = []  (auditado; el bot solo opera en chats individuales)
     si no: out = route(tx, user, u, prefetch, now)     # handlers de team/leads/compliance; devuelven Outgoing
  # tras el commit (efecto y marca de procesado en la misma transacción):
  para o en out: r = await telegram.send_message(...); si no r.delivered: repo.record_failed_noncritical(...)   # VCRM-012
  si u.callback_id: await telegram.answer_callback(u.callback_id)
  si algún handler encoló críticas: outbox.kick()
```

- Las respuestas interactivas y las notificaciones no críticas se envían una sola vez; si fallan se registra una fila `crm_outbox` con `critical=0`, `status='fallida'`, `body=NULL` (sin datos personales) y no se toca el lead (VCRM-012).
- **Entradas pendientes** (`crm_pending_inputs`, caducan a los 30 min; una orden nueva las sustituye): texto de «otro» en rechazo y retractación, evidencia de autorización tras «Sí» o `/autorizacion`.
- **Confirmaciones** (`crm_confirmations`): ✅/❌ de aceptación, de retractación y pregunta de autorización; la resolución es `UPDATE ... SET status=? WHERE id=? AND status='pendiente'`; 0 filas → «ya procesada».
- Errores inesperados en un handler: *rollback*, respuesta genérica sin datos, log con el tipo de excepción; tras el *rollback*, en una **transacción aparte** se marca el `update_id` como procesado y se escribe la auditoría `handler_error` (tipo de excepción, sin datos). No se confía en la reentrega de Telegram: `run_polling` avanza el *offset* en memoria y no existe contador de fallos, así que el update no se reintenta; el usuario recibe la respuesta genérica y puede repetir la orden. Si esa segunda transacción también falla, se registra en el log y el bucle continúa.

---

## 8. Casos de uso (servicios)

Todos reciben `tx` y `now` y devuelven `list[Outgoing]` (respuestas y no críticas) más, si aplica, filas encoladas en el *outbox*; las reglas se apoyan en §5.

### 8.1 Equipo (`team.py`) — VCRM-125, 126, 144, 091, 092, 093

- `seed_cto(tx, settings, now)`: si no hay CTO activo → valida (VCRM-126: id numérico, correo válido, id no repetido) → inserta; si falla, log con el **nombre** del dato faltante o inválido, sin valores.
- `add_user` (`/alta`): solo CTO; rol ∈ {comercial, abogado}; valida; inserta; acceso inmediato (la siguiente actualización ya lo encuentra activo); confirma; audita `user_added`.
- `deactivate_user` (`/baja_usuario`): solo CTO; rol CTO → rechazo; `active=0`; audita; si es comercial, responde con la lista paginada de sus leads (estado ≠ baja), cada uno con botón «Reasignar», que abre el teclado de destinos (comerciales activos y CTO).
- `reassign` (`/reasignar` o botón): solo CTO; destino activo; evento `reassign` con anterior, nuevo, autor y fecha (VCRM-093).
- «Sin comercial asignado» (VCRM-092) se deriva al leer: asignado inactivo. `commercial_recipients()` envía al CTO lo dirigido a ese comercial (A.2).

### 8.2 Leads (`leads.py`)

```text
register(tx, user, cmd, now):                          # VCRM-003, 006, 088, 110, 135, 137, 066
  authorize(REGISTER)
  fps = huellas de tel y correo
  si alguna en crm_suppression: return respuesta 'contacto pidió no ser contactado'      # VCRM-088 (prevalece)
  coincidencias = leads no suprimidos con mismo tel o correo y estado != perdido
  si coincidencias:
     visibles = [l for l in coincidencias if is_visible(user, l)]
     si visibles: aviso con id, estado y comercial + botones «Abrir lead existente» / «Cancelar»   # VCRM-006
     si no: respuesta sin datos + no crítica al CTO con id, comercial («del CTO»/«sin comercial asignado»),
            quien intentó y fecha, con botón «Reasignar»                                  # VCRM-110, 137
     return
  insertar lead 'nuevo' asignado a user (comercial o CTO); evento state; nota inicial si hay; audit lead_created
  responder L-NNNN + datos + pregunta de autorización con botones Sí/No (confirmación 'authorization_question')   # VCRM-066
  # «No» o sin respuesta: auth_status sigue 'sin_autorizacion'. «Sí»: entrada pendiente de evidencia.
add_note: authorize(NOTE_ATTACH); insertar con autor y fecha; last_interaction; audit          # VCRM-009, 109
add_attachment(prefetch): sin lead indicado o lead inexistente → error; demasiado grande o descarga fallida
  → error con causa (límite 20 MB); si no → authorize, save_atomic, fila con tipo/autor/fecha; si falla el
  insert, se borra el archivo (sin adjunto parcial)                                         # VCRM-007, 008
edit: lead inexistente → error + campos editables; authorize(EDIT); validar (VCRM-005 para tel/correo,
  validate_handoff_value para handoff); duplicado no perdido o huella suprimida → error (id solo si visible);
  guardar; evento field (anterior, nuevo, autor, fecha); audit; si estado='aceptado' y el campo figuraba
  faltante → encolar críticas de actualización del handoff (VCRM-084)                     # VCRM-080–083, 112
transition(tx, user, lead, dst, reason?, now):
  authorize(acción de dst); check_transition; aplicar; evento state (origen, destino, autor, fecha, motivo)  # VCRM-015
  rechazo: exige motivo de la matriz por botones; 'otro' exige texto (entrada pendiente); sin próxima acción (F1)  # 016, 017, 118
  contactado desde nuevo/rechazado: botón «Registrar contacto» (089); desde rechazado conserva historial, notas,
  adjuntos y autorización (132: no se borra nada; el evento previo sigue)
  ganado: CTO o abogado, desde aceptado; won_at=now                                          # 115, 134
  perdido: comercial del lead o CTO; desde nuevo/contactado/rechazado; final_state_at=now; cancela confirmaciones
  pendientes del lead; aceptado→perdido → 'primero registre la retractación'                  # 116, 133, 117
request_accept → confirmación ✅/❌ con resumen                                               # 046
confirm_accept(✅): si estado ya 'aceptado' → 'ya estaba aceptado', sin notificaciones        # 051
  transición; ever_accepted=1; faltantes = missing_handoff_fields                             # 111
  encolar 3 críticas: CTO/telegram, abogado/telegram, abogado/email (idempotency 'accept:<lead>:<evento>:<canal>:<user>')  # 047, 048, 104, 156
  si faltantes: no crítica al comercial del lead pidiendo completarlos                        # 052
request_retract: authorize(RETRACT) → motivo por botones ('otro' con texto) → confirmación con id, nombre y motivo  # 131, 114
confirm_retract(✅): aceptado→rechazado, rejection_is_retraction=1, accepted_exit_at=now; encolar críticas de
  retractación por los mismos canales (abogado limitado por LawyerView)                      # 113
confirm_retract(❌): sin transición ni notificaciones                                         # 131
callback 'retractar:<lead>' (botón de la ficha) → request_retract(lead) (misma autorización y
  guardas: si ya no está en 'aceptado' o sin permiso → rechazo con motivo, sin transición)    # 163
```

### 8.3 Cumplimiento (`compliance.py`)

- **Autorización** (VCRM-065, 138, 139): `/autorizacion L-n` o «Sí» tras el registro abre una entrada pendiente; solo una foto o documento la cumple → adjunto `authorization` + fila `crm_consents(status='autorizada', medium='documento_o_captura', actor, at, attachment_id)` + `auth_status='autorizada'`. Texto, nota de voz, o cualquier otro medio → no registra, mantiene el estado e informa los medios válidos. `notice_version` y `purposes` quedan nulos en el medio (b) (riesgo conocido de la spec, J-04).
- **Baja** (VCRM-070, 071, 095): `/baja L-n; medio`: authorize(REGISTER_OPT_OUT); transición a `baja` (desde cualquier estado ≠ baja); huellas de tel y correo en `crm_suppression` (solo huella, fecha y medio); `final_state_at=now`; cancela confirmaciones y entradas pendientes del lead; consentimiento `revocada` con el medio de la baja; evento y auditoría. En F1 no existe ningún envío al cliente; `may_contact_commercially(lead)` (falso con huella suprimida, baja o `commercial_block`) es la guarda única que usará F2, y se prueba ya en F1 (VCRM-071).
- **Supresión** (VCRM-073, 094, 154, 155; también la usan 146 y 159):

```text
plan_suppression(lead, keep_fields, keep_attachments_of_won) -> SuppressionPlan     # pura
  files = adjuntos no borrados excepto 'authorization' y, si keep_attachments_of_won, excepto los de ganado
  evidence_files = adjuntos 'authorization' no borrados solo si cause = 'orden_cto'      # VCRM-164, 165 (K-4)
  (por plazo — VCRM-146/159 — la evidencia se conserva íntegra: VCRM-164)
titular_leads(lead) -> [lead]     # VCRM-073; spec 4.5 «leads del mismo titular» (decisión K-3)
  [lead] + leads con suppressed_at IS NULL, id ≠ lead.id y
     ((lead.phone_e164 IS NOT NULL y phone_e164 = lead.phone_e164) o (lead.email IS NOT NULL y email = lead.email))
  una sola consulta, sin iteración: SIN cierre transitivo (A~B por teléfono, B~C por correo → sobre A: A y B; C no)
  incluye «perdido», «baja» y retractados (a diferencia de repo.contact_matches, que excluye «perdido» para el registro)
execute_suppression(lead_ids, cause, now, keep_fields=∅, basis=None, add_fingerprint):
  1. borrar archivos de los planes de todos los leads (fuera de la transacción); si alguno falla → SuppressionFailed (nada se marca)
  2. una sola tx para todos los leads; por cada lead: huella a crm_suppression si add_fingerprint;
         anular en crm_leads los campos personales salvo keep_fields; borrar notas; marcar adjuntos borrados;
         borrar eventos 'field'; anular reason_text; purgar subject/body del outbox del lead;
         borrar confirmaciones y entradas pendientes; conservar crm_consents (estado, medio, fecha, versión,
         finalidades, actor, attachment_id: sin datos del titular);
         adjuntos 'authorization': si cause='orden_cto' → archivo borrado en el paso 1 y fila con deleted_at=now,
         conservando kind, at, size_bytes y sha256 = huella mínima (VCRM-165); si no → intactos (VCRM-164);
         suppressed_at, suppression_cause; si keep_fields: legal_hold_basis=basis, commercial_block=1
         keep_fields solo se aplica a los leads en 'aceptado' o 'ganado'; el resto se suprime completo
         audit 'suppression' (causa) por lead; encolar UNA crítica supresion_copias por destinatario y canal
         con todos los identificadores: CTO/telegram (todos los lead_ids) y, si alguno tiene ever_accepted,
         abogado/telegram y abogado/email (solo los lead_ids con ever_accepted), sin datos personales  # 154
```

  `/suprimir L-n` (solo CTO, VCRM-073) reúne con `titular_leads` los leads no suprimidos que coinciden exactamente con el teléfono E.164 o el correo normalizado del lead indicado (incluidos retractados, perdidos y en baja; sin encadenar, decisión K-3) y llama a `execute_suppression(ids, cause='orden_cto', ..., add_fingerprint=True)`; la confirmación al CTO enumera todos los identificadores suprimidos. Con `; conservar: campos; fundamento: texto` solo se admite si al menos un lead del grupo está en `aceptado` o `ganado` (un retractado está en `rechazado` y queda excluido) → `keep_fields` y `basis` solo para esos leads (VCRM-094). El barrido por plazo (§8.4) llama con un único id. Si la notificación de supresión queda fallida → alerta `suppression_notice_failed` en la lista del CTO, una por lead afectado, con destinatario y canal (VCRM-155). Un lead suprimido deja de listarse; su ficha responde «lead suprimido».
- **Exportación** (VCRM-074, 075, 166): solo CTO; `zipfile` con `ficha.txt` (ficha, handoff, historial completo, autorizaciones; de una evidencia reducida solo su huella mínima: tipo, fecha, tamaño y SHA-256, VCRM-165) y los adjuntos vigentes; `send_document` al chat privado del CTO; temporales borrados al terminar (también en fallo); auditoría `export` con el número de partes. **Partes numeradas (decisión K-5):**

```text
TELEGRAM_UPLOAD_LIMIT = 50 * 1024 * 1024; PART_MARGIN = 1 MiB          # límite de subida de la Bot API
plan_export_parts(doc_size, attachments[(id, size)], limit) -> [[item]]   # pura, determinista
  cap = limit - PART_MARGIN (cabeceras ZIP y del multipart)
  parte 1 = [ficha.txt]; para cada adjunto en orden de id (first-fit secuencial):
     si tamaño_actual + size > cap → abrir parte nueva; añadir a la parte actual
  (cota: tamaño sin comprimir ≥ tamaño en ZIP_DEFLATED salvo ~bytes de cabecera, cubiertos por el margen;
   un adjunto nunca supera cap: la Bot API no permite a un bot descargar archivos > 20 MB)
export_lead(lead, limit=TELEGRAM_UPLOAD_LIMIT):
  partes = plan_export_parts(...); n = len(partes)
  n = 1 → 'export_L-0042.zip' (comportamiento original)
  n > 1 → por k: 'export_L-0042_parte_k_de_n.zip', leyenda «Parte k de n», cada ZIP abrible por sí solo,
          ficha.txt solo en la parte 1 con el índice de qué adjunto va en qué parte
  envío en orden; un fallo de una parte no detiene las siguientes; al final, si hubo fallos →
     respuesta al CTO con las partes no entregadas (p. ej. «No se entregaron: 2 y 3 de 4»)
```

  Descartado: cortar el ZIP en trozos binarios (`.zip.001`), porque obliga al CTO a unirlos con otra herramienta; y comprimir para medir antes de repartir, porque el reparto por tamaño sin comprimir con margen es determinista y comprobable en tests con `limit` pequeño.
- **Solicitudes de titulares** (VCRM-150): `/solicitud L-n; tipo; fecha de recepción; medio` (comercial sobre los propios, CTO sobre todos); fecha futura → error; `due_on = add_business_days(received_on, plazo_vigente)` (10 consultas, 15 reclamos); evento `titular_request`; no crítica al CTO; `/solicitudes` las lista al CTO; `/atendida S-n` (solo CTO) registra autor y fecha y cierra la alerta de vencida.

### 8.4 Barrido diario (`retention.py`) — VCRM-145–147, 151, 152, 158, 159

```text
daily_sweep(now):                       # idempotente; se ejecuta al arrancar y por cron
  today = local_date(now)
  # J-14
  para lead no suprimido, estado ∉ {aceptado, ganado}, auth_status = 'sin_autorizacion':
     start = max(registered_at, accepted_exit_at)
     si now >= start + max_days: execute_suppression(cause='j14', add_fingerprint=False)
                                 + no crítica al comercial del lead y al CTO (id y causa)           # 159
     elif now >= start + warning_days y no hay crm_retention_notices(lead,start,'warn'):
                                 no crítica al comercial del lead (id, nombre, fecha de supresión)  # 158
  # VCRM-146
  para lead no suprimido en perdido/baja con now >= add_months(final_state_at, months):
     execute_suppression(cause='final_state', add_fingerprint=(estado == baja),
                         keep_attachments_of_won=(won_at y now < add_years(won_at, years)))        # 145 prevalece
  # VCRM-145
  para adjunto no borrado (≠ 'authorization') de lead con won_at y now >= add_years(won_at, years):
     borrar archivo; marcar deleted_at; audit 'attachment_expired'
  # VCRM-147: cualquier fallo de los pasos anteriores → no se marca nada de ese lead; no crítica al CTO
  #           (id y causa); el siguiente barrido diario lo reintenta (los criterios siguen cumpliéndose)
  # Solicitudes (151, 152)
  para solicitud abierta o vencida:
     si status='abierta' y today >= due_on: status='vencida'; alerta 'request_overdue'                # 152
     si is_business_day(today) y today >= add_business_days(received_on, escalation_days)
        y last_escalation_on != today: no crítica al CTO (id, lead, tipo, recepción,
        business_days_between(today, due_on) restantes); last_escalation_on = today                   # 151
  # Mantenimiento: borrar crm_processed_updates con más de 7 días
```

Decisión: el adjunto tipo `authorization` (evidencia de autorización) no se borra por VCRM-145 ni por la supresión, porque VCRM-073 ordena conservar las evidencias; se registra como riesgo para revisión (§13).

### 8.5 *Outbox* de notificaciones críticas (`outbox.py`) — VCRM-047, 049, 050, 087, 107, 127–130, 140, 155

```text
OFFSETS = (0 s, 60 s, 300 s)
next_attempt_at(first_attempt_at, attempts_done) -> datetime | None     # pura
  attempts_done >= 3 → None; si no → first_attempt_at + OFFSETS[attempts_done]
enqueue_critical(tx, kind, channel, recipient, lead_id, subject, body, origin=None, key) -> id
  INSERT ... ON CONFLICT (idempotency_key) DO NOTHING; status='pendiente', next_attempt_at=now     # 049: persistida antes del intento
OutboxWorker.run(stop): bucle: esperar kick() o intervalo (5 s) → deliver_due(clock())
deliver_due(now):
  due = pendientes con next_attempt_at <= now (orden id)
  resultados = await gather(*[send(item) for item in due], return_exceptions=True)   # independencia: 047
  por cada item, en su propia tx:
     éxito → 'entregada', provider_message_id
     fallo permanente (correo no configurado) → 'fallida' sin más intentos            # 140
     fallo → attempts += 1; first_attempt_at ||= now; nxt = next_attempt_at(first, attempts)
             nxt None → 'fallida' → escalate(tx, item, now) ; si no next_attempt_at = nxt   # 127
escalate(tx, item, now):
  kind ∈ {aceptacion, retractacion, handoff}:
     alerta 'notification_failed' (lead, outbox) en ficha y lista del CTO                    # 087
     para u en {CTO} ∪ commercial_recipients(lead) (sin repetir): encolar 'respaldo_correo'/email
       con id del lead, destinatario y canal fallidos; si el fallido era CTO/telegram, + contenido completo  # 050, 107
       (solo aquí, tras el tercer fallo: nunca en paralelo)                                   # 128
  kind = respaldo_correo: para u en {CTO} ∪ commercial_recipients(lead): encolar 'fallo_respaldo' por telegram
       y por email (id, notificación original, destinatario del respaldo)                     # 129
  kind = fallo_respaldo: nada más                                                             # 130
  kind = supresion_copias: alerta 'suppression_notice_failed'                                # 155
```

- **Plazo de VCRM-047:** tras el *commit* de la confirmación, el servicio llama a `kick()`; el trabajador intenta en el mismo ciclo, sin esperar al intervalo; el test comprueba que las tres filas tienen `first_attempt_at == instante de confirmación` con reloj simulado y que el fallo de una no altera las otras. Tolerancia de los reintentos: intervalo del trabajador (5 s por defecto).
- **Reinicio (VCRM-049, 078):** las filas `pendiente` sobreviven; al arrancar, `deliver_due` las retoma con los intentos que les quedan (el calendario se calcula desde `first_attempt_at`, de modo que un intento atrasado no reinicia la cuenta).
- **Doble entrega aceptada** (§4.5): si el proceso cae entre el envío y la actualización, la fila sigue pendiente y se reintenta.
- Alertas: `/ver` muestra las activas; botón «Atendida por otro medio» (solo CTO, VCRM-087/155) las resuelve con autor y fecha.

### 8.6 Respaldo cifrado (`backup.py`) — VCRM-097, 098

```text
run_backup(now):
  name = 'crm-' + now(UTC, %Y%m%dT%H%M%SZ) + '.tar.gz.age'
  1. instantánea consistente: conexión PROPIA de solo lectura (sqlite3.connect('file:crm.db?mode=ro', uri=True))
     abierta y cerrada dentro del hilo que ejecuta el respaldo → src.backup(temporal) (sin bloquear al escritor;
     no se usa la conexión escritora, que fallaría por check_same_thread al usarse desde otro hilo)
  2. tarfile gz: instantánea + attachments/ (incluye evidencias)
  3. cifrado: runner ['age', '--encrypt', '--recipient', RECIPIENT, '--output', out, tar]
  4. subida:  runner ['rclone', 'copyto', out, f'{REMOTE}/{name}']
  5. retención: runner ['rclone', 'lsf', REMOTE] → expired_backups(nombres, now, días) (pura, por la fecha del nombre)
              → runner ['rclone', 'deletefile', f'{REMOTE}/{n}'] por cada vencido
  6. borrar temporales locales siempre (finally); éxito → crm_meta.last_backup_ok_at = now
  fallo en cualquier paso (incluida configuración ausente o binario inexistente) → no crítica al CTO
  con el paso fallido, la causa (código, sin datos) y la fecha del último respaldo correcto       # 098
```

- **Cifrado asimétrico con `age`** (recomendado en opciones, decisión 3): en el servidor solo está la clave **pública** (`JERICO_CRM_BACKUP_AGE_RECIPIENT`); la privada la guarda el CTO fuera de la instancia, de modo que un compromiso del servidor no descifra respaldos antiguos. Se descarta `cryptography` (dependencia nueva, no instalada en el entorno, y obligaría a diseñar un formato propio) y `gpg` (configuración de *keyring* más pesada).
- **Transferencia con `rclone`** a OCI Object Storage (Always Free) u otro destino: permite subir, listar y borrar con un mismo binario y sin dependencias Python. Se descarta `boto3`/SDK de OCI (pesados) y la URL preautenticada de OCI (no permite listar ni borrar, lo que impediría cumplir la retención desde el sistema).
- **Parte operativa (propuesta, fuera del código):** crear el *bucket* y su remoto `rclone` por variables `RCLONE_CONFIG_<REMOTO>_*` en `.env`; generar el par `age-keygen` fuera de la instancia; regla de ciclo de vida del *bucket* a 31 días como defensa en profundidad; simulacro de restauración trimestral: `rclone copyto` → `age --decrypt -i clave` → `tar xzf`.

---

## 9. Jobs y proceso `jerico-crm` (`jobs.py`, `app.py`)

- `CronScheduler` del núcleo, sin cambios, con `execution_timeout_s=1800` (el respaldo puede tardar) y `poll_interval_s=20`. Jobs (expresiones en UTC; Bogotá = UTC−5):

| Job | Cron (UTC) | Hora Bogotá | Función | Reintentos |
| :--- | :--- | :--- | :--- | :--- |
| `crm-daily` | `0 13 * * *` | 08:00 | `retention.daily_sweep` (J-14, 145–147, 151–152, poda) | 1 |
| `crm-backup` | `0 8 * * *` | 03:00 | `backup.run_backup` | 1 |

  Hora de `crm-daily` elegida para que los avisos al comercial y al CTO lleguen en horario laboral. Ambos son idempotentes; `daily_sweep` se ejecuta además una vez al arrancar para recuperar una ejecución perdida por caída.
- El *outbox* **no** es un job de cron: la granularidad de 1 minuto del planificador no cumple el primer intento inmediato ni el reintento al minuto con margen; corre como `OutboxWorker` (tarea asyncio, 5 s, despertable con `kick()`). Alternativa descartada: job `* * * * *` (reintentos con hasta 60 s de deriva).
- `main()` (entrypoint `jerico-crm`): `CrmSettings()` → `effective_params()` → exige token y clave HMAC (si faltan: log del nombre de la variable y salida con código 2) → `CrmDatabase` → `seed_cto` → construye adaptadores → notifica los `ConfigWarning` al CTO (VCRM-162) → `daily_sweep` de recuperación → `scheduler.start()` → `asyncio.gather(bot.run_polling, outbox.run, heartbeat)`; `SIGTERM`/`SIGINT` → parada ordenada (`scheduler.stop()`, cierre de la base). Latido: `${DATA_DIR}/heartbeat` (mtime) cada ciclo de *polling*, para el *healthcheck* del contenedor.

---

## 10. Estrategia de pruebas

- **Herméticas:** sin red ni procesos externos. Dobles en `tests/crm_support.py`: `FakeTelegram` (registra envíos, guion de fallos por destinatario/intento, `Update`s sintéticos), `FakeEmailSender`, `FakeRunner` (registra `argv`, guion de códigos de salida), `FakeClock` (UTC, avanzable), `make_harness(tmp_path, now, **params)` (base temporal, usuarios CTO/comercial/abogado sembrados, `CrmApp` cableada con dobles). `HttpxTelegramClient` se prueba con `httpx.MockTransport`; `SmtpEmailSender` con un `smtplib.SMTP` falso vía `monkeypatch`.
- **Asíncronas** con `pytest.mark.asyncio` (pytest-asyncio 1.4 instalado), como `tests/test_cron_scheduler.py`.
- **Cobertura:** objetivo ≥ 89 % global y ≥ 89 % de `src/jerico/crm` (`pytest --cov=src/jerico --cov-report=term`, aunque `verify.sh` no lo mida). Las ramas de E/S (SMTP, httpx, subprocess) se cubren con dobles.
- **Calidad:** `ruff check` y `mypy` sobre los archivos nuevos en cada tarea; `./scripts/verify.sh` al final.
- **Trazabilidad:** cada requisito F1 tiene al menos un test cuyo nombre contiene `vcrmNNN`; la tarea final lo verifica con `grep`.

### 10.1 Matriz requisito F1 → test(s)

| Requisito | Tarea(s) | Test(s): archivo → foco (`test_vcrmNNN_*`) |
| :--- | :--- | :--- |
| VCRM-001 | T10 | `test_crm_bot.py` → solo identidades de la lista con rol procesan mensajes y botones |
| VCRM-002 | T10 | `test_crm_bot.py` → identidad no autorizada: sin efecto ni datos; auditoría con identidad, fecha y tipo |
| VCRM-003 | T11 | `test_crm_register.py` → /nuevo válido crea «nuevo», asigna al autor y responde L-NNNN |
| VCRM-004 | T06, T11 | `test_crm_parsing.py`, `test_crm_register.py` → falta nombre o contacto: dato faltante y ejemplo |
| VCRM-005 | T06 | `test_crm_parsing.py` → teléfono no E.164 (+57 por defecto) o correo inválido |
| VCRM-006 | T11 | `test_crm_register.py` → duplicado visible: aviso y botones |
| VCRM-007 | T12 | `test_crm_lead_data.py` → adjunto con tipo, autor y fecha |
| VCRM-008 | T08, T12 | `test_crm_adapters.py`, `test_crm_lead_data.py` → > 20 MB, descarga fallida o lead inexistente: sin adjunto parcial |
| VCRM-009 | T12 | `test_crm_lead_data.py` → nota con autor y fecha |
| VCRM-010 | T13 | `test_crm_views.py` → lista por rol ordenada por última interacción |
| VCRM-011 | T13 | `test_crm_views.py` → ficha completa |
| VCRM-012 | T08, T10, T15 | `test_crm_adapters.py`, `test_crm_bot.py`, `test_crm_outbox.py` → respuesta o no crítica fallida: «fallida» sin reintento ni cambio de estado |
| VCRM-013 | T04 | `test_crm_states.py` → solo transiciones de la fase vigente |
| VCRM-014 | T04, T14 | `test_crm_states.py`, `test_crm_transitions.py` → transición no permitida: transiciones válidas |
| VCRM-015 | T14 | `test_crm_transitions.py` → historial de transición con origen, destino, autor, fecha y motivo |
| VCRM-016 | T14 | `test_crm_transitions.py` → rechazo exige motivo por botones |
| VCRM-017 | T14 | `test_crm_transitions.py` → «otro» sin texto no transiciona |
| VCRM-046 | T16 | `test_crm_acceptance.py` → confirmación ✅/❌ de la aceptación |
| VCRM-047 | T15, T16 | `test_crm_outbox.py`, `test_crm_acceptance.py` → tres notificaciones independientes con primer intento inmediato |
| VCRM-048 | T07, T16 | `test_crm_render.py`, `test_crm_acceptance.py` → contenido para el CTO y correo al abogado |
| VCRM-049 | T15, T24 | `test_crm_outbox.py`, `test_crm_app.py` → persistida antes del intento y reanudada tras reinicio |
| VCRM-050 | T18 | `test_crm_escalation.py` → correo de respaldo al CTO y al comercial tras «fallida» |
| VCRM-051 | T16 | `test_crm_acceptance.py` → aceptación repetida sin notificaciones |
| VCRM-052 | T16 | `test_crm_acceptance.py` → faltantes indicados y petición al comercial del lead |
| VCRM-065 | T19 | `test_crm_consent.py` → estado de autorización con medio, fecha, versión, finalidades y evidencia |
| VCRM-066 | T11 | `test_crm_register.py` → pregunta con botones; «No» o sin respuesta: «sin autorización» |
| VCRM-070 | T19 | `test_crm_consent.py` → baja inmediata: estado, huella, cancelaciones y registro |
| VCRM-071 | T19 | `test_crm_consent.py` → sin contacto comercial con huella suprimida |
| VCRM-073 | T20a | `test_crm_suppression.py` → supresión por orden del CTO de los leads del mismo titular (dos leads del mismo contacto, uno «perdido» y otro activo o retractado: ambos suprimidos; sin cierre transitivo: A~B por teléfono y B~C por correo → sobre A se suprimen A y B, C intacto) |
| VCRM-074 | T20b | `test_crm_export.py` → exportación ZIP al chat privado del CTO (una parte si cabe en el límite) |
| VCRM-075 | T03, T20b | `test_crm_db.py`, `test_crm_export.py` → bitácora de creación, modificación, exportación y supresión |
| VCRM-077 | T02 | `test_crm_timeutil.py` → UTC almacenado; cálculo y presentación en Bogotá |
| VCRM-078 | T03, T24 | `test_crm_db.py`, `test_crm_app.py` → persistencia tras reinicio |
| VCRM-079 | T10 | `test_crm_bot.py` → update_id repetido sin efecto |
| VCRM-080 | T12 | `test_crm_lead_data.py` → edición con historial |
| VCRM-081 | T06, T12 | `test_crm_parsing.py`, `test_crm_lead_data.py` → lead inexistente o campo no editable: lista de editables |
| VCRM-082 | T06, T12 | `test_crm_parsing.py`, `test_crm_lead_data.py` → teléfono o correo editado inválido |
| VCRM-083 | T12 | `test_crm_lead_data.py` → edición duplicada o con huella suprimida |
| VCRM-084 | T17 | `test_crm_retraction.py` → notificación de actualización del handoff |
| VCRM-085 | T05 | `test_crm_permissions.py` → matriz de permisos §4.4 |
| VCRM-086 | T05, T10 | `test_crm_permissions.py`, `test_crm_bot.py` → acción no permitida: respuesta y auditoría |
| VCRM-087 | T18 | `test_crm_escalation.py` → alerta persistente hasta «atendida por otro medio» |
| VCRM-088 | T11 | `test_crm_register.py` → huella suprimida bloquea el registro y prevalece |
| VCRM-089 | T14 | `test_crm_transitions.py` → «Registrar contacto» desde nuevo y rechazado |
| VCRM-090 | T07, T13 | `test_crm_render.py`, `test_crm_views.py` → páginas de 10 con «Anterior»/«Siguiente» y X de Y |
| VCRM-091 | T09 | `test_crm_team.py` → baja de comercial o abogado con reasignación; CTO no |
| VCRM-092 | T09, T13 | `test_crm_team.py`, `test_crm_views.py` → «sin comercial asignado» |
| VCRM-093 | T09 | `test_crm_team.py` → reasignación con historial |
| VCRM-094 | T20a | `test_crm_suppression.py` → excepción por deber legal o contractual |
| VCRM-095 | T06, T19 | `test_crm_parsing.py`, `test_crm_consent.py` → lista de supresión solo con huella HMAC |
| VCRM-096 | T03 | `test_crm_db.py` → bitácora sin datos personales |
| VCRM-097 | T23 | `test_crm_backup.py` → respaldo nocturno cifrado, transferido y con retención |
| VCRM-098 | T23 | `test_crm_backup.py` → aviso de fallo del respaldo con causa y último correcto |
| VCRM-104 | T07, T16 | `test_crm_render.py`, `test_crm_acceptance.py` → alerta de Telegram al abogado |
| VCRM-105 | T08 | `test_crm_adapters.py` → correo interno desde el buzón configurado a usuarios autorizados |
| VCRM-107 | T18 | `test_crm_escalation.py` → respaldo al CTO con el contenido completo |
| VCRM-109 | T05, T12 | `test_crm_permissions.py`, `test_crm_lead_data.py` → comercial sobre lead ajeno: sin acceso ni datos; auditoría |
| VCRM-110 | T11 | `test_crm_register.py` → duplicado no visible: sin datos y aviso al CTO |
| VCRM-111 | T07, T16 | `test_crm_render.py`, `test_crm_acceptance.py` → completitud del handoff |
| VCRM-112 | T07, T12 | `test_crm_render.py`, `test_crm_lead_data.py` → valores de handoff no admitidos |
| VCRM-113 | T17 | `test_crm_retraction.py` → retractación confirmada: «rechazado» y notificaciones críticas |
| VCRM-114 | T17 | `test_crm_retraction.py` → retractación sin motivo: sigue «aceptado» |
| VCRM-115 | T14 | `test_crm_transitions.py` → ganado por CTO o abogado |
| VCRM-116 | T14 | `test_crm_transitions.py` → perdido por comercial del lead o CTO; abogado no |
| VCRM-117 | T04, T14 | `test_crm_states.py`, `test_crm_transitions.py` → ganado y perdido solo admiten baja |
| VCRM-118 | T14 | `test_crm_transitions.py` → rechazo en F1 sin próxima acción |
| VCRM-125 | T09 | `test_crm_team.py` → lista persistida y siembra del CTO |
| VCRM-126 | T09 | `test_crm_team.py` → alta o siembra inválida rechazada |
| VCRM-127 | T15 | `test_crm_outbox.py` → 3 intentos a 0, 1 y 5 minutos y «fallida» |
| VCRM-128 | T18 | `test_crm_escalation.py` → respaldo nunca en paralelo a los intentos |
| VCRM-129 | T18 | `test_crm_escalation.py` → aviso de fallo del respaldo por Telegram y correo |
| VCRM-130 | T18 | `test_crm_escalation.py` → sin más envíos tras fallar el aviso |
| VCRM-131 | T17 | `test_crm_retraction.py` → retractación con confirmación ✅/❌ |
| VCRM-132 | T14 | `test_crm_transitions.py` → vuelta desde rechazado conserva historial y datos |
| VCRM-133 | T04, T14 | `test_crm_states.py`, `test_crm_transitions.py` → aceptado → perdido exige retractación |
| VCRM-134 | T05, T14 | `test_crm_permissions.py`, `test_crm_transitions.py` → comercial no marca ganado |
| VCRM-135 | T11 | `test_crm_register.py` → coincidencia solo con «perdido» crea lead |
| VCRM-136 | T05, T13 | `test_crm_permissions.py`, `test_crm_views.py` → abogado sobre lead nunca aceptado: sin acceso |
| VCRM-137 | T11 | `test_crm_register.py` → aviso al CTO con opción de reasignar |
| VCRM-138 | T19 | `test_crm_consent.py` → autorización con documento o captura |
| VCRM-139 | T19 | `test_crm_consent.py` → autorización sin evidencia o por otro medio rechazada |
| VCRM-140 | T08, T18 | `test_crm_adapters.py`, `test_crm_escalation.py` → buzón sin configurar: «fallida» sin intentos |
| VCRM-144 | T09 | `test_crm_team.py` → alta por el bot con acceso inmediato |
| VCRM-145 | T22 | `test_crm_retention.py` → adjuntos de ganado 10 años, aun en baja |
| VCRM-146 | T22 | `test_crm_retention.py` → supresión a los 12 meses de perdido o baja |
| VCRM-147 | T22 | `test_crm_retention.py` → fallo de supresión: aviso y reintento diario |
| VCRM-150 | T21 | `test_crm_requests.py` → registro con fecha límite en días hábiles y tope |
| VCRM-151 | T21 | `test_crm_requests.py` → escalado a los 2 días hábiles y aviso diario |
| VCRM-152 | T21 | `test_crm_requests.py` → «vencida» con alerta |
| VCRM-154 | T20a, T22 | `test_crm_suppression.py`, `test_crm_retention.py` → notificación crítica de supresión de copias |
| VCRM-155 | T20a | `test_crm_suppression.py` → alerta por notificación de supresión fallida |
| VCRM-156 | T07, T16, T17 | `test_crm_render.py`, `test_crm_acceptance.py`, `test_crm_retraction.py` → al abogado solo campos del handoff |
| VCRM-158 | T22 | `test_crm_retention.py` → aviso a los 25 días sin autorización |
| VCRM-159 | T22 | `test_crm_retention.py` → supresión a los 30 días sin autorización |
| VCRM-162 | T01, T24 | `test_crm_config.py`, `test_crm_app.py` → topes legales aplicados y aviso al CTO |
| VCRM-163 | T17b | `test_crm_retraction.py` → botón «Retractar» en la ficha solo en «aceptado» y con permiso; la pulsación abre la misma solicitud (motivo y ✅/❌); botón obsoleto o sin permiso → rechazo sin transición |
| VCRM-164 | T19, T22 | `test_crm_consent.py`, `test_crm_retention.py` → evidencia de autorización (registro y archivo) intacta tras la supresión por plazo |
| VCRM-165 | T20a | `test_crm_suppression.py` → tras `/suprimir`, archivo de evidencia borrado; quedan estado, medio, fecha, versión, finalidades, actor, tamaño y SHA-256; ningún dato del titular en claro (centinelas) |
| VCRM-166 | T20b | `test_crm_export.py` → con `limit` pequeño: partes «k de n» abribles por sí solas, ficha en la parte 1, cada adjunto en una sola parte, envío en orden; fallo de una parte → aviso con las no entregadas |
| VCRM-167 | T02b | `test_crm_timeutil.py` → fecha extraordinaria configurada no es hábil; `add_business_days` y `business_days_between` la saltan |
| VCRM-168 | T02b, T24 | `test_crm_config.py`, `test_crm_app.py` → entrada mal escrita, fecha imposible o archivo ilegible: se ignora, rigen las válidas y se avisa al CTO con entrada y motivo |

Total: 101 requisitos F1; cada uno con al menos un test nombrado `test_vcrmNNN_*`.

---

## 11. Cambios propuestos fuera del alcance de implementación

**No se tocarán** en esta línea `docker-compose.yml`, `Dockerfile` ni `.env`/`.env.example` (límite del humano). Bloques exactos propuestos para que el CTO los aplique cuando decida desplegar:

**`docker-compose.yml`** — servicio nuevo bajo `services:` y volumen nuevo bajo `volumes:` (aditivo; `jerico-core` y `redis` no cambian):

```yaml
  jerico-crm:
    build:
      context: .
      args:
        EXTRAS: crm
        CRM_TOOLS: "1"
    image: jerico-crm:0.2.0
    container_name: jerico-crm
    command: ["jerico-crm"]
    env_file: .env
    environment:
      JERICO_CRM_DATA_DIR: /app/crm-data
    volumes:
      - jerico_crm_data:/app/crm-data
    restart: unless-stopped
    mem_limit: 512m
    cpus: 0.5
    healthcheck:
      test: ["CMD", "python", "-c", "import os,sys,time; sys.exit(0 if time.time()-os.path.getmtime('/app/crm-data/heartbeat') < 120 else 1)"]
      interval: 60s
      timeout: 5s
      retries: 3
    networks:
      - jerico_net
```

```yaml
  jerico_crm_data:
    name: jerico_crm_data
```

Sin `ports`: el bot solo hace conexiones salientes (long polling), coherente con la postura Zero-Trust (P-10).

**`Dockerfile`** — argumentos con valor por defecto que dejan intacta la imagen de `jerico-core`:

```dockerfile
# Etapa base, tras la instalación de dependencias base:
ARG EXTRAS=""
RUN if [ -n "$EXTRAS" ]; then python -c 'import os, subprocess, tomllib; opt = tomllib.load(open("pyproject.toml", "rb"))["project"]["optional-dependencies"]; deps = [d for e in os.environ["EXTRAS"].split(",") for d in opt[e]]; subprocess.check_call(["pip", "install", "--no-cache-dir", *deps])'; fi

# Etapa runtime, junto a la copia de /usr/local/bin/jerico:
COPY --from=base /usr/local/bin/jerico-crm /usr/local/bin/jerico-crm
ARG CRM_TOOLS=0
RUN if [ "$CRM_TOOLS" = "1" ]; then apt-get update && apt-get install -y --no-install-recommends age rclone && rm -rf /var/lib/apt/lists/*; fi
# En el RUN existente de useradd, añadir:
#   && mkdir -p /app/crm-data && chown jerico:jerico /app/crm-data
```

El `HEALTHCHECK` HTTP de la imagen lo sustituye el `healthcheck` del servicio en compose.

**`.env.example`** — solo nombres, sin valores reales:

```dotenv
JERICO_CRM_TELEGRAM_BOT_TOKEN=__REPLACE_ME__
JERICO_CRM_FINGERPRINT_KEY=__REPLACE_ME__
JERICO_CRM_FINGERPRINT_PREVIOUS_KEYS=
JERICO_CRM_SEED_CTO_TELEGRAM_ID=__REPLACE_ME__
JERICO_CRM_SEED_CTO_EMAIL=__REPLACE_ME__
JERICO_CRM_DATA_DIR=/app/crm-data
JERICO_CRM_SMTP_HOST=
JERICO_CRM_SMTP_PORT=
JERICO_CRM_SMTP_SECURITY=
JERICO_CRM_SMTP_USERNAME=
JERICO_CRM_SMTP_PASSWORD=
JERICO_CRM_SMTP_FROM=
JERICO_CRM_BACKUP_AGE_RECIPIENT=
JERICO_CRM_BACKUP_REMOTE=
JERICO_CRM_QUERY_DEADLINE_BUSINESS_DAYS=10
JERICO_CRM_CLAIM_DEADLINE_BUSINESS_DAYS=15
JERICO_CRM_ESCALATION_BUSINESS_DAYS=2
JERICO_CRM_WON_ATTACHMENTS_RETENTION_YEARS=10
JERICO_CRM_FINAL_STATE_SUPPRESSION_MONTHS=12
JERICO_CRM_UNAUTHORIZED_WARNING_DAYS=25
JERICO_CRM_UNAUTHORIZED_MAX_DAYS=30
JERICO_CRM_BACKUP_RETENTION_DAYS=30
# Remoto rclone del respaldo (p. ej. OCI Object Storage), configurado por entorno:
# RCLONE_CONFIG_CRMBACKUP_TYPE=...
```

**`scripts/verify.sh`:** sin cambios (añadir el umbral de cobertura es decisión del núcleo; opciones §8). La cobertura se mide aparte en la tarea final.

---

## 12. Plan de convivencia

- No se modifican `src/jerico/gateway/`, `src/jerico/tools/` (incluido `approval.py`), `src/jerico/state/`, `src/jerico/config.py`, `src/jerico/main.py`, `tests/conftest.py` ni archivos del núcleo. `CronScheduler` se importa tal cual.
- `pyproject.toml`: solo el extra `crm` y el script `jerico-crm` (§2).
- Archivos nuevos únicamente bajo `src/jerico/crm/`, `tests/crm_support.py` y `tests/test_crm_*.py`. Sin commits ni *push* (los decide el CTO). Si otra línea cambia `CronScheduler.register_job` o `tick`, el único punto de contacto es `jobs.py`.
- Ningún test del CRM escribe fuera de `tmp_path`; el *fixture* autouse existente (`audit_log_aislado`) no interfiere.

---

## 13. Decisiones y riesgos

| # | Decisión | Alternativa descartada | Por qué |
| :--- | :--- | :--- | :--- |
| D-01 | Paquete plano `jerico.crm` con base SQLite propia | Tablas `crm_` en la base del núcleo | Excepción a D1 acotada al CRM; no toca `state/schema.py`. |
| D-02 | Un escritor con `RLock` y lecturas en la misma conexión | *Pool* de lectores de `state/db.py` | Un proceso y volumen bajo; menos código. |
| D-03 | *Outbox* en tarea asyncio de 5 s con `kick()` | Job de cron cada minuto | VCRM-047 (< 1 min) y reintento al minuto con precisión. |
| D-04 | Efecto + marca de `update_id` + *offset* en la misma transacción | Solo *offset* de `getUpdates` | VCRM-079 ante reinicios entre efecto y confirmación. |
| D-05 | Festivos con función pura propia | Paquete `holidays`; tabla en configuración | Sin dependencia; verificable con vectores de 2026. |
| D-06 | `smtplib` en hilo | `aiosmtplib`; API HTTP de proveedor | Sin dependencia nueva; volumen < 100 correos al día. |
| D-07 | `age` (clave pública en el servidor) + `rclone` | `cryptography` + formato propio; `gpg`; SDK de OCI; URL preautenticada | Sin dependencias Python; la clave privada nunca está en la instancia; listar y borrar para la retención. |
| D-08 | Topes legales aplicados por función pura, no por validadores de pydantic | `Field(le=...)` | VCRM-162 exige aplicar el tope y avisar, no abortar. |
| D-09 | Baja registra un consentimiento `revocada` | No tocar el consentimiento | VCRM-065 contempla «revocada»; la baja es la revocatoria del contacto comercial (L-5). |
| D-10 | Bot solo en chats privados | Grupos | Evita exponer fichas en grupos y el *privacy mode* (P-16). |
| D-11 | «Leads del mismo titular» por coincidencia exacta con el lead indicado, en una consulta (K-3) | Cierre transitivo iterativo | Decisión del CTO: no se encadenan titulares. |
| D-12 | Huella mínima = filas de `crm_consents` y del adjunto (con `sha256` y tamaño) con el archivo borrado; sin esquema nuevo (K-4) | Tabla nueva de huellas; conservar el archivo cifrado | Las columnas ya existen; nada en claro queda tras la supresión. |
| D-13 | Exportación en ZIP independientes por partes, reparto *first-fit* por tamaño sin comprimir con margen (K-5) | Trozos binarios `.zip.001`; comprimir para medir | Cada parte se abre sola; reparto determinista y comprobable. |
| D-14 | Festivos extraordinarios en `JERICO_CRM_EXTRA_HOLIDAYS` (fechas y/o rutas), con aviso y sin abortar (K-6) | Dos variables; abortar el arranque; paquete `holidays` | Una sola lista configurable; mismo criterio que D-08. |
| D-15 | Botón «Retractar» en la ficha en F1 (tarea T17b) (K-2) | Dejarlo para F2 | Costo bajo: un botón y un *callback* que reutilizan `request_retract`, ya probado en T17. |

**Riesgos:** (1) la evidencia de autorización (`authorization`) no se borra ni por VCRM-145 ni por supresión por plazo (VCRM-164); tras la supresión ordenada por el CTO queda solo su huella mínima (VCRM-165); si el abogado entiende que a los 10 años también debe eliminarse, es un cambio de una línea en `plan_suppression`/barrido; (2) exportaciones > 50 MB se entregan en partes numeradas (VCRM-166); el reparto usa el tamaño sin comprimir con 1 MiB de margen; (3) los festivos extraordinarios dependen de que el CTO los cargue a tiempo en la lista configurable (VCRM-167); una entrada mal escrita se ignora con aviso (VCRM-168); (4) `age` y `rclone` dependen de la propuesta del `Dockerfile`; sin ellos el respaldo falla y se avisa (VCRM-098); (5) la cobertura global depende de que la suite del núcleo no baje en paralelo (otras líneas trabajan en `main`).

---

> Última modificación: 05/10/2026 08:54 (Planificador SDD)
