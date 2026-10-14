---
modificado: "13/10/2026 22:41"
---

# Plan del módulo CRM-consejero (spec 007) — instantánea diaria

- **Estado:** **BORRADOR — depende de la aprobación de la módulo CRM-consejero de la spec 007 (Gate 1)**. Con la spec aprobada pasa a Gate 2.
- **Spec que implementa:** `specs/007-jev-transversal/crm-consejero/spec.md` (requisitos `VJC-001` a `VJC-040`).
- **Principio rector:** el CRM solo **observa y guarda**, en modo lectura, una instantánea diaria sin texto libre. Todo lo que habla con Jev vive en `Flota_Jev` (`kai-jev`).
- **Hechos verificados en el código** (rama `crm/asistente-comercial-llm`, commit `d0aeab3`, leída con `git show`; el código no se modificó):
  - Los trabajos periódicos se registran en un único punto, `register_jobs` (`crm/jobs.py`), llamado desde `crm/app.py`; hoy hay `crm-daily` (13:00 UTC = 08:00 Bogotá), `crm-backup` y `crm-followup`.
  - `CrmDatabase` (`crm/db.py`) ofrece `read()` y `tx()`. `read()` **no abre una transacción**: toma el cerrojo de la conexión y entrega esa misma conexión en modo de confirmación automática; la consistencia viene de que `tx()` no puede ejecutarse mientras dura `read()`.
  - `repo.pending_proposals(conn, now)` devuelve solo las pendientes vencidas y no recibe `lead_id`; por eso la prueba de equivalencia usa SQL directo por lead.
  - `CrmSettings` (`crm/config.py`) usa el prefijo `JERICO_CRM_`, `env_ignore_empty=True` y ya tiene `data_dir` (en producción `/app/crm-data`, volumen persistente `jerico_crm_data`).
  - `timeutil.local_date(dt)` devuelve el día calendario en hora de Bogotá.
  - `repo.py` expone `all_leads`, `lead_events`, `lead_notes`, `get_cadence`, `pending_proposals`, `open_alerts`, `open_titular_requests`; `handoff.missing_handoff_fields(lead)` devuelve los campos faltantes.
  - `Lead` tiene `state`, `reject_reason`, `auth_status`, `ever_accepted`, `rejection_is_retraction`, `commercial_block`, `registered_at`, `last_interaction_at`, `suppressed_at` y demás campos de la spec; `EventKind` incluye `state`, `field`, `reassign` y `titular_request`.
  - La supresión ocurre en un único punto, `compliance.execute_suppression`, y marca `suppressed_at` (no borra la fila). El barrido diario (`crm-daily`) corre a las 13:00 UTC y también al arrancar el CRM.
  - `lead.client_type` toma los valores «persona natural» y «empresa» (con espacio); `reject_reason` es texto en la base y el código lo restringe a 5 valores (registros antiguos podrían traer otros).
  - `/lista` ordena por última interacción (`repo.all_leads`) y `/seguimiento` ordena por número de lead (`followup_view`).
- **Base de código:** esta rama de especificación (`jev/p1-router-spec`) sale de `main` (`aa12fb3`) y **no contiene** el asistente. La implementación debe salir de una rama que contenga el despliegue real (`d0aeab3` o su integración en `main`) para compartir `config.py` y `app.py` sin conflicto; se coordina con `crm-director` antes de empezar. Pendiente de confirmar: si esa base ya está integrada cuando se apruebe la spec.

## 1. Decisiones de diseño y alternativas descartadas

| Id | Decisión | Alternativas descartadas y motivo |
|---|---|---|
| **P-1** | **Archivos JSONL diarios** en el directorio de datos del CRM. | Tabla nueva en la base del CRM: obliga a una migración del esquema (`migrate.py` ya cargó la migración v1→v2) y roza la integridad de datos; borrarla por supresión sería más pesado. Mantener todo en memoria: no sirve para comparar días. |
| **P-2** | **Trabajo propio** `crm-jev-snapshot` (cron `30 13 * * *` = 08:30 Bogotá, 30 minutos después del barrido legal), registrado solo si la funcionalidad está activa; **no** se ejecuta al arrancar (VJC-009). | Colgarlo de `crm-daily`: un fallo o una demora afectaría al barrido legal diario (VJC-006). Ejecutarlo al arrancar: duplicaría corridas en cada reinicio. |
| **P-3** | **Reconciliación de supresión al comienzo de cada corrida**: se calculan las referencias (HMAC) de los leads con `suppressed_at`, en estado `opted_out` o ausentes, y se quitan de todos los archivos antes de escribir; si un archivo no puede reescribirse se elimina entero; las referencias retiradas se anotan en un archivo de retiros. | Engancharse a `compliance.execute_suppression`: es código legal crítico; no se toca para algo opcional. Detectar la supresión por «fila ausente»: los leads nunca se borran. |
| **P-4** | **Idempotencia por archivo del día:** antes de escribir se leen las referencias ya presentes en el archivo de hoy y se omiten. | Un archivo marcador aparte: puede desincronizarse del contenido. |
| **P-5** | **Consultas en bloque** (una consulta por tipo de dato, con `GROUP BY` por lead y sin listas `IN` de ids, para no chocar con el límite de variables de SQLite), todas dentro de **una sola sección `read()`**, con un máximo de 12 sentencias por corrida —incluida la lista de leads— independientemente del número de leads (VJC-005, VJC-008). | Llamar a `lead_events`, `get_cadence`, etc. por cada lead (N+1). Medir el tiempo en pruebas: depende del equipo y no es determinista, por eso se cuentan sentencias. |
| **P-6** | **Escritor de archivos compartido** `shadowlog` (`DailyJsonlWriter` con `append`, `purge` y `rewrite_without`), construido **una sola vez** aquí y reutilizado por la spec 002 (router) cuando se despierte. | Duplicar el escritor en cada spec (el CTO pidió no duplicar). |
| **P-7** | **Referencia del lead = HMAC-SHA-256 del número interno** con una clave propia (`JERICO_CRM_JEV_SNAPSHOT_KEY`, secreto solo en el `.env` del servidor), acortada a 16 caracteres. Sin clave no se activa. | Guardar el número interno secuencial: es reidentificable desde el CRM (auditoría QA). Un hash sin clave: invertible por fuerza bruta sobre números pequeños. |
| **P-8** | **Sin dependencias nuevas** (`pyproject.toml` no cambia). | — |

**Efecto en la constitución:** ninguna enmienda. Principio 5 no aplica (el CRM no configura ni llama a Jev). Principio 6: el CRM no conoce la llave. Principio 3: pruebas herméticas. Principio 4: el CRM mantiene su base; los archivos no son una base de datos.

## 2. Archivos y funciones

| Archivo | Contenido | Pura / con efectos |
|---|---|---|
| `src/jerico/shadowlog/__init__.py` | Reexporta `DailyJsonlWriter`. | — |
| `src/jerico/shadowlog/jsonl.py` | `DailyJsonlWriter(directory, prefix, retention_days, clock)` con `append(record)` (una línea, ≤ 4 KB), `read_day(day)` (ignora líneas incompletas o ilegibles), `append` (si el archivo no termina en salto de línea, lo añade antes de escribir, para no pegar un registro a una línea parcial), `purge()` (borra por fecha) y `rewrite_without(predicate)` (reescribe con archivo temporal y reemplazo atómico; si no puede, elimina el archivo y lo informa). | Con efectos (disco); reloj inyectado; solo biblioteca estándar |
| `src/jerico/crm/advisor_state.py` | `SCHEMA_VERSION = 1`; `CAPS`; enumeraciones permitidas; `lead_ref(key, lead_id)`; `is_eligible(lead)`; `build_vector(lead, ctx, today, key)`; `validate_vector(vector)`; `InvalidVector`. | Pura |
| `src/jerico/crm/advisor_queries.py` | `load_context(conn, lead_ids, now)`: consultas de solo lectura agrupadas por lead (eventos de cambio de etapa, de campo y de reasignación de los últimos 30 días y fecha del último cambio de etapa, notas contadas, cadencia, propuestas pendientes, alertas sin resolver del lead, solicitudes de titular no atendidas), todas dentro de una sola sección `read()`; las propuestas pendientes cuentan todas las de estado pendiente (de seguimiento y de solicitud de autorización) con `GROUP BY` por lead. | Con efectos (lectura) |
| `src/jerico/crm/advisor_snapshot.py` | `run_snapshot(db, writer, retiros, key, now) -> SnapshotReport`: aplica retención, reconcilia supresiones y retiros, lee leads, filtra elegibles, construye y valida, y escribe omitiendo los ya presentes. Contadores de omitidos y de fallos (en memoria). | Con efectos |
| `src/jerico/crm/config.py` (modificación mínima) | `jev_snapshot_enabled: bool = False`, `jev_snapshot_key: str = ""`, `jev_snapshot_dir: Path \| None = None` (por defecto `data_dir/jev_snapshot`), `jev_snapshot_retention_days: int = 90`; la activación efectiva exige clave no vacía (VJC-014), como el patrón de `f2_missing`. | — |
| `src/jerico/crm/jobs.py` (modificación mínima) | Constantes `SNAPSHOT_JOB`, `SNAPSHOT_CRON`; parámetro opcional `snapshot` en `register_jobs`. | — |
| `src/jerico/crm/app.py` (modificación mínima) | Construir el escritor y registrar `run_jev_snapshot_job` solo si está activa; el trabajo envuelve `run_snapshot` y captura excepciones. | — |
| `.env.example`, `docs/` | Variables nuevas; apartado de despliegue. | — |

## 3. Diseño detallado

### 3.1 Elegibilidad y vector (`advisor_state.py`)

```
is_eligible(lead):
    return lead.suppressed_at is None
       and lead.state != "opted_out"
       and lead.auth_status != "revoked"

lead_ref(key, lead_id):  hmac_sha256(key, f"lead:{lead_id}")[:16]

build_vector(lead, ctx, today, key):           # today = día calendario en Bogotá
    v = {
      schema_version: 1, day: today.isoformat(), lead_ref: lead_ref(key, lead.id),
      stage: lead.state,
      age_days:               cap(max(0, (today - local_date(lead.registered_at)).days), 365),
      days_since_interaction: cap(max(0, (today - local_date(lead.last_interaction_at)).days), 365),
      days_in_stage:          cap(max(0, (today - (ctx.last_state_event_day[lead.id] or local_date(lead.registered_at))).days), 365),
      ever_accepted, is_retraction, commercial_block, has_phone, has_email,
      has_agreed_value, has_service, has_assignee,                 # bool (texto solo si está vacío)
      client_type: {"persona natural": "persona_natural", "empresa": "empresa"}.get(lead.client_type, "ninguno"),
      reject_reason: ninguno si vacío; si no, el valor si está en los 5 conocidos, y "otro" en otro caso,
      auth: {"unauthorized","authorized"},
      handoff_missing: len(missing_handoff_fields(lead)),          # regla vigente, 0..9
      events_30d: cap(ctx.events_30d[lead.id], 50), notes: cap(ctx.notes[lead.id], 50),
      cadence: {status|"ninguna", steps_done, steps_total, sent (cap 50), has_next: bool,
                days_to_next: cap(dias hasta next_action_at, ±365) o 0 si no tiene},
      proposals_pending, alerts_open, titular_open: cap(.., 50),   # definiciones de VJC-012
      weekday: today.weekday()
    }
    validate_vector(v); return v
```

`validate_vector` exige exactamente las claves de la lista cerrada, `bool` solo donde corresponde, enteros dentro de tope y cadenas solo si pertenecen al enumerado (la referencia y el día son los únicos valores especiales). Los textos del lead solo se miran para saber si están vacíos; nunca se copian.

### 3.2 Corrida (`advisor_snapshot.py`)

```
run_snapshot(db, writer, retiros, key, now):
    today = local_date(now)
    writer.purge(); retiros.purge(retention_days=30)                 # VJC-021
    with db.read() as conn:                                          # una sola sección de lectura (VJC-005)
        leads = all_leads(conn, exclude_suppressed=False)
        eligible = [l for l in leads if is_eligible(l)]
        ctx = load_context(conn, [l.id for l in eligible], now)      # <= 12 sentencias (VJC-008)
    vivos = {lead_ref(key, l.id) for l in eligible}                  # referencias que SÍ pueden estar
    retirar = lambda rec: rec["lead_ref"] not in vivos               # suprimidos, opted_out o ausentes
    quitadas = writer.rewrite_without(retirar)                       # VJC-022 / VJC-023
    retiros.append_all({"lead_ref": r, "day": today} for r in quitadas)   # VJC-024 (retiros-AAAA-MM-DD, 30 días)
    if writer.last_rewrite_failed: report.blocked = True; return     # no escribe hoy (VJC-023)
    hechos = {rec["lead_ref"] for rec in writer.read_day(today)}     # VJC-004
    for lead in eligible:
        ref = lead_ref(key, lead.id)
        if ref in hechos: continue
        try: writer.append(build_vector(lead, ctx, today, key))
        except InvalidVector: report.omitted += 1                    # VJC-007
```

Notas: no se escribe en la base (VJC-005); si la lectura falla, no se escribe nada ese día (VJC-006); con cero leads elegibles no se escriben líneas pero sí se aplican retención y retiros (VJC-010). Un lead que se suprime después de la captura del día se retira en la corrida del día siguiente (en menos de 24 horas).

### 3.3 Cableado (`app.py`)

```
if settings.jev_snapshot_enabled and settings.jev_snapshot_key:
    writer = DailyJsonlWriter(dir, "crm_snapshot", retention_days, clock)
    retiros = DailyJsonlWriter(dir, "crm_retiros", 30, clock)
    register snapshot job (SNAPSHOT_CRON) -> async wrapper:
        try: report = await asyncio.to_thread(run_snapshot, db, writer, retiros, key, clock())
        except Exception: failures += 1; log aviso sin datos de leads (+ contador)
```

La corrida usa `asyncio.to_thread` para no bloquear el procesamiento de mensajes de Telegram. El envoltorio atrapa `Exception` (no la cancelación), incrementa un contador en memoria y escribe el aviso sin datos de leads (VJC-006); al final de cada corrida escribe un resumen sin datos de leads con escritas, omitidas y retiradas (VJC-007). Sin clave, el aviso al CTO usa el mecanismo de avisos de configuración que ya ejecuta el arranque del CRM (VJC-014). No se llama al iniciar el proceso (VJC-009).

## 4. Configuración

| Variable | Valor por defecto | Para qué |
|---|---|---|
| `JERICO_CRM_JEV_SNAPSHOT_ENABLED` | `false` | Activa la instantánea (VJC-002). |
| `JERICO_CRM_JEV_SNAPSHOT_KEY` | vacío | Clave secreta de la referencia (VJC-014, VJC-016). Solo en el `.env` del servidor, la coloca el CTO. Sin clave no se activa. |
| `JERICO_CRM_JEV_SNAPSHOT_DIR` | vacío (= `data_dir/jev_snapshot`) | Directorio de archivos. |
| `JERICO_CRM_JEV_SNAPSHOT_RETENTION_DAYS` | `90` | Retención (VJC-021; propuesta). |

## 5. Estrategia de pruebas

Herméticas (constitución, principio 3): bases SQLite temporales con los constructores de prueba del CRM, relojes inyectados, sin red, sin Jev, sin `Flota_Jev`.

| Archivo de pruebas | Qué cubre | Requisitos |
|---|---|---|
| `tests/test_shadowlog_jsonl.py` | Línea por registro; archivo del día; `read_day` descarta líneas incompletas o ilegibles; `purge` por fecha con reloj falso (y con retención reducida); `rewrite_without` atómico y, si falla, elimina el archivo y lo informa; 20 hilos × 50 líneas sin líneas corruptas; línea > 4 KB rechazada; falla de disco. | VJC-020 a 023 |
| `tests/test_crm_advisor_state.py` | Elegibilidad (suprimido, `opted_out`, autorización revocada fuera; estados finales dentro); cada campo con casos de borde (sin eventos de etapa → desde el registro; cadencia ausente, sin fecha y vencida; fechas futuras → 0; `client_type` y `reject_reason` desconocidos; alertas sin lead no cuentan; solicitudes vencidas cuentan); topes; la referencia es estable, de 16 caracteres, distinta con otra clave y no contiene el número; `validate_vector` rechaza clave extra o faltante, tipo erróneo, entero fuera de tope y cadena fuera del enumerado; **prueba de privacidad**: con leads cuyos textos son marcadores únicos, ningún marcador aparece en el vector serializado. | VJC-011 a 016, 007 |
| `tests/test_crm_advisor_queries.py` | Las consultas en bloque coinciden con lo que dan `lead_events`, `lead_notes`, `get_cadence`, `pending_proposals`, `open_alerts` y `open_titular_requests` lead por lead; con 1 000 leads se ejecutan como máximo 12 sentencias (conteo con la traza de SQLite); todas son lecturas. | VJC-005, 008, 012 |
| `tests/test_crm_advisor_snapshot.py` | Apagado por defecto no escribe; una línea por lead elegible; dos corridas el mismo día no duplican (también tras un reinicio y con una línea parcial); el día se decide en hora de Bogotá (23:30 y 00:30 locales); **la base queda idéntica** antes y después; un lead inválido se omite y cuenta; supresión: tras marcar `suppressed_at`, pasar a `opted_out` o quitar la fila, la corrida borra sus líneas **antes** de escribir y anota el retiro; un archivo que no se puede reescribir se elimina y no se escribe ese día; cero leads elegibles no escribe pero aplica retención; un fallo de lectura no escribe. | VJC-002 a 007, 010, 021 a 024 |
| `tests/test_crm_advisor_wiring.py` | Con la variable apagada o sin clave no se registra el trabajo y se avisa una vez; con ella activa se registra con el cron `30 13 * * *`, 30 minutos después de `crm-daily`; no se ejecuta al arrancar; una excepción dentro del trabajo no se propaga, cuenta el fallo, no incluye datos de leads en el aviso y no impide los demás trabajos. | VJC-002, 006, 009, 014 |
| `tests/test_crm_advisor_isolation.py` | Ningún módulo nuevo importa `flota_jev`, `requests`, `httpx`, `socket` ni `urllib` (árbol de sintaxis); `pyproject.toml` y `src/` no contienen `flota_jev`, `TYPESAFE`, `api.typesafe.ai` ni `jev-latest`; `pyproject.toml` no cambia respecto de la base. | VJC-001, 030, 031, 032 |
| `tests/test_crm_advisor_config.py` | Valores por defecto, variable vacía = no definida, `.env.example` contiene las variables nuevas sin valores reales. | VJC-002, 014, 021 |

Cobertura: los módulos nuevos al 100 % y el total ≥ 89 %.

## 6. Matriz requisito → prueba

| Requisito | Archivo de pruebas |
|---|---|
| VJC-001, 030, 031, 032 | isolation |
| VJC-002 | snapshot, wiring, config |
| VJC-003, 004 | snapshot |
| VJC-005 | snapshot (base idéntica), queries (lecturas y transacción única) |
| VJC-006 | wiring, snapshot |
| VJC-007 | advisor_state, snapshot |
| VJC-008 | queries |
| VJC-009 | wiring |
| VJC-010 | snapshot |
| VJC-011, 012, 013, 015, 016 | advisor_state, queries |
| VJC-014 | advisor_state, wiring, config |
| VJC-020, 021 | shadowlog, config, snapshot |
| VJC-022, 023, 024 | shadowlog, snapshot |
| VJC-040 | `verify.sh` en cada tarea |

## 7. Coordinación con `Flota_Jev` (sin duplicar)

`kai-jev` recibe el contrato de la spec, sección 7: lector de los archivos, esquema de vector del CRM, las dos preguntas (`urgencia` como `score`, `siguiente_paso` como `choice`), consenso de tres, etiquetas calculadas entre instantáneas y el informe. Aquí no se escribe nada de eso. Obligaciones que Jericó le pide a la flota: aplicar los retiros y la retención sobre sus copias, y no enviar a Jev ni la referencia ni el día. El traslado de los archivos del servidor es la pregunta Q1 de la spec.

## 8. Despliegue y reversa

- **Entrega apagada:** con `JERICO_CRM_JEV_SNAPSHOT_ENABLED=false` el CRM se comporta como hoy.
- **Activación:** solo con la orden del CTO, añadiendo la variable al `.env` del servidor (lo hace el orquestador con el CTO; esta spec no toca el servidor).
- **Reversa:** apagar la variable **y borrar la carpeta de instantáneas ese mismo día** (apagada, el CRM no retira ni purga nada). No hay migración de datos.
- **Respaldos:** el volumen del CRM entra en los respaldos cifrados (retención de 30 días); las instantáneas viajarían ahí. Es un dato seudonimizado, no anónimo; se anota para la revisión legal (Q5 de la spec, que bloquea el Gate 1).
- **Clave:** la clave de la referencia la coloca el CTO en el `.env` del servidor (`chmod 600`); nunca en el repositorio.

## 9. Riesgos del plan

| Riesgo | Mitigación |
|---|---|
| Choque de `config.py`/`app.py` con la rama del asistente | Implementar sobre la base que ya contiene `d0aeab3`; coordinar con `crm-director`. |
| Consultas lentas con muchos leads | Consultas en bloque y prueba que cuenta sentencias (≤ 12, igual con 10 y con 1 000 leads). |
| Reescritura de archivos por supresión | Archivo temporal con reemplazo atómico y prueba de fallo intermedio. |
| Un cambio de clave retira todo el historial (queda declarado en VJC-014) | No cambiar la clave durante el piloto; si cambia, se reinicia el piloto. |
| La captura bloquea el bot | `asyncio.to_thread` y trabajo separado de `crm-daily`. |
| Volumen real nulo | Declarado: cierre «no concluyente» a las 12 semanas. |

> 🕒 **Última modificación:** 13/10/2026 22:41 (Agente Claude Code · Sonnet 5.5)
