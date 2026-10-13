---
modificado: "13/10/2026 10:27"
---

# Plan 002 — Captura en sombra del router (Jev P1)

- **Estado:** **BORRADOR — depende de la aprobación de la spec 002 (Gate 1)**. Cuando se apruebe la spec, este plan pasa a Gate 2 (aprobación del CTO).
- **Spec que implementa:** `specs/002-jev-router-sombra/spec.md` (requisitos `VRJ-001` a `VRJ-050`).
- **Principio rector:** el núcleo solo **observa y registra**; nunca consulta a Jev. Todo lo que habla con Jev vive en `Flota_Jev` (`kai-jev`).
- **Hechos verificados en el código (rama `jev/p1-router-spec`, base `aa12fb3`):**
  - El router se invoca una sola vez por turno, en `src/jerico/agent/conversation_loop.py:80`; `main.py` (`jerico ask`) lo invoca aparte y **no** pasa por el bucle.
  - El bucle tiene un `try/finally` que ya libera el lease (`conversation_loop.py`, bloque final de `run_turn`); varios `return` (L0, respuesta normal, iteraciones agotadas) y cancelación por `request_interrupt`.
  - `StateEngine.append_messages` devuelve los ids de las filas insertadas (`state/db.py:186`), pero `TurnFinalizer` y el bucle los descartan.
  - Configuración con `pydantic-settings`, prefijo `JERICO_` (`config.py`); `.env.example` usa marcadores `__REPLACE_ME__` y las variables vacías se tratan como no definidas (commit `fdf20a9`).
  - `docker-compose.yml:13` ya monta `./logs:/app/logs`; `logs/` está en `.gitignore`.
  - `tools/base.py` escribe `logs/audit.log` **incluyendo los argumentos de cada herramienta**; por eso el registro de la sombra **no** reutiliza ese archivo.
  - Las pruebas simulan el LLM con `FakeLLM` y usan `tmp_path` (`tests/test_turn_loop_orchestration.py`).

## 1. Decisiones de diseño y alternativas descartadas

| Id | Decisión | Alternativas descartadas y motivo |
|---|---|---|
| **P-1** | **Sombra desacoplada:** el núcleo escribe un archivo local; `Flota_Jev` lo lee, consulta a Jev y mide. | (A) Instalar `Flota_Jev` como dependencia del núcleo: la herramienta no tiene remoto ni se publica, así que rompe el CI de GitHub y el `Dockerfile` (viola VRJ-021). (B) Copiar el cliente de Jev al núcleo: duplica la herramienta (prohibido por el CTO). (C) Llamar a Jev desde el núcleo en segundo plano: mete red de terceros y la llave en el núcleo (viola VRJ-001 y VRJ-023). |
| **P-2** | **Archivos JSONL diarios** en un directorio (`logs/route_shadow/AAAA-MM-DD.jsonl`); retención = borrar archivos viejos. | Tabla en `StateEngine`: obliga a una migración del esquema del núcleo, sin purga automática hoy y roza la regla de integridad de datos de la constitución. Reescribir un solo archivo para purgar: exige bloqueo y puede perder líneas. Reutilizar `audit.log`: contiene argumentos de herramientas. |
| **P-3** | **Observador inyectable** en `AgentTurnLoop` (`shadow: ShadowRecorder \| None`), con `begin()` tras calcular la presión de tokens y `finish()` en el `finally`. | Envolver `run_turn` desde fuera: no ve el historial ni la presión de tokens. Parchear cada `return`: frágil ante nuevos caminos. |
| **P-4** | **Referencia al mensaje:** el bucle y el finalizador conservan el id de la fila del mensaje del usuario y lo exponen en `TurnResult.user_message_id` (campo nuevo con valor por defecto `None`, compatible hacia atrás). | Guardar `session_id`: es un identificador que puede venir de una persona (VRJ-013). Usar un ordinal dentro de la sesión: obliga a guardar igualmente el `session_id`. |
| **P-5** | **Señales del router sin duplicar reglas:** `TokenRouter.signals(prompt)` devuelve las banderas que ya calcula; `classify` se mantiene como está y una prueba comprueba que ambos coinciden. | Reimplementar las expresiones regulares en el módulo nuevo: se desincronizarían. Cambiar `classify` para que use `signals`: toca el camino crítico sin necesidad. |
| **P-6** | **Revisión ciega por subcomando de la CLI existente** (`jerico route-review`), no por la API. | Endpoint de la API: expone prompts por red (viola VRJ-033). |
| **P-7** | **Léxico ampliado por configuración**, con una lista inicial mínima de la que se deja constancia en el registro mediante huella SHA-256. | Listas en código: obliga a redeploy por cada ajuste. |

**Efecto en la constitución:** ninguna enmienda es necesaria. Principio 5 (sin alias flotantes) no aplica: el núcleo no configura ni llama a Jev. Principio 6 se cumple: el núcleo no conoce la llave. Principio 3 se cumple: todo es hermético.

## 2. Archivos y funciones

Todo el código nuevo vive en un paquete nuevo y pequeño: `src/jerico/routing_shadow/`.

| Archivo | Contenido | Pura / con efectos |
|---|---|---|
| `routing_shadow/__init__.py` | Reexporta `ShadowRecorder`, `InvalidShadowState`. | — |
| `routing_shadow/state.py` | `SCHEMA_VERSION = 1`; topes por campo (`CAPS`); enumeraciones permitidas; `build_state(...)`; `validate_state(state)`; `InvalidShadowState`. | Pura |
| `routing_shadow/lexicon.py` | `Lexicon` (dataclass inmutable: dinero, cliente_lead, contrato_legal); `Lexicon.from_settings`; `Lexicon.fingerprint()`; `lexicon_flags(text, lexicon)`; `has_code_block(text)`; `has_figures(text)`; `is_question(text)`. | Pura |
| `routing_shadow/jsonl.py` | `DailyJsonlWriter(directory, prefix, retention_days, clock)` con `append(record)` y `purge()`. | Con efectos (disco), reloj inyectado |
| `routing_shadow/recorder.py` | `ShadowRecorder(enabled, writer, lexicon, clock, monotonic)`; `begin(...) -> TurnObservation \| None`; `TurnObservation.finish(outcome, usage, iterations, user_message_id)`; contadores `written`, `failed_writes`, `invalid_states`. | Con efectos |
| `routing_shadow/review.py` | `load_review_items(directory, ids, n, seed)`; `ReviewItem`; `record_judgment(writer, item_ref, level, reviewer_role, now)`; `run_review(...)` (interacción con la persona). | Mixta |
| `router.py` (modificación mínima) | Método nuevo `TokenRouter.signals(prompt) -> RouteSignals`. `RouteSignals` es un dataclass con `is_l0`, `l2_match`, `l3_match`, `l2_exception`. | Pura |
| `agent/types.py` (modificación mínima) | `TurnResult.user_message_id: int \| None = None`. | — |
| `agent/turn_finalizer.py` (modificación mínima) | Recoger los ids que ya devuelve `append_messages` y rellenar `TurnResult.user_message_id`. | — |
| `agent/conversation_loop.py` (modificación mínima) | Parámetro `shadow` en el constructor; `begin()` tras la presión de tokens; capturar el id del mensaje de usuario de las rondas de herramientas; `finish()` en el `finally`. | — |
| `api.py` (modificación mínima) | Construir el `ShadowRecorder` desde `Settings` y pasarlo a `AgentTurnLoop`. | — |
| `config.py` (modificación mínima) | Campos `route_shadow_*` (ver sección 4). | — |
| `main.py` (modificación mínima) | Subcomando `route-review`. | — |
| `.env.example`, `docs/` | Variables nuevas y una nota en el documento de despliegue. | — |

**No se añade ninguna dependencia** (`pyproject.toml` no cambia). `typer`, `pydantic-settings` y la biblioteca estándar ya cubren todo.

## 3. Diseño detallado

### 3.1 Estado compacto (`state.py`)

Campos y tipo (el orden y los nombres son el contrato con `Flota_Jev`):

| Campo | Tipo | Tope / valores |
|---|---|---|
| `schema_version` | entero | 1 |
| `rule_level` | entero | 1, 2 o 3 |
| `l2_match`, `l3_match`, `l2_exception` | booleano | — |
| `char_count` | entero | tope 10 000 |
| `word_count` | entero | tope 2 000 |
| `history_messages` | entero | tope 200 (todos los roles, antes del turno) |
| `history_tokens` | entero | tope 200 000 |
| `pressure` | enumerado | `low`, `elevated`, `overflow` (valor de `evaluate_token_pressure`, antes de compactar) |
| `surface` | enumerado | `rest`, `cli`, `telegram`, `siri` |
| `posture` | enumerado | `coding`, `ops`, `personal`, `default` |
| `mentions_money`, `mentions_client`, `mentions_legal` | booleano | del léxico ampliado |
| `has_code_block`, `has_figures`, `is_question` | booleano | — |

Pseudocódigo:

```
build_state(prompt, signals, rule_level, history_messages, history_tokens,
            pressure, surface, posture, lexicon) -> dict
    text = prompt[:10_000]                       # VRJ-012: costo acotado
    flags = lexicon_flags(text, lexicon)
    state = {campos con enteros recortados al tope, enumerados como str.value}
    validate_state(state)          # lanza InvalidShadowState
    return state

validate_state(state)
    exigir exactamente el conjunto de claves esperado
    bool -> isinstance bool; int -> int (no bool) y 0 <= v <= tope;
    enumerado -> v in permitidos
    cualquier otra cosa -> InvalidShadowState
```

### 3.2 Registro (`recorder.py`)

```
ShadowRecorder.begin(prompt, signals, rule_level, model, ...) -> TurnObservation | None
    si no enabled -> None                          # VRJ-002
    si rule_level == 0 -> None                     # VRJ-004
    try: state = build_state(...)
    except InvalidShadowState: invalid_states += 1; log aviso sin texto; return None   # VRJ-009
    return TurnObservation(state, model, t0 = monotonic(), lexicon.fingerprint())

TurnObservation.finish(outcome, usage, iterations, user_message_id)
    record = { schema_version, ts = clock().isoformat(), state, rule_level, model,
               prompt_tokens, completion_tokens, tool_rounds, duration_ms,
               outcome, user_message_id, lexicon_fingerprint }
    try: writer.append(record)                     # una línea, un solo write
    except OSError/ValueError: failed_writes += 1; log aviso sin texto   # VRJ-007
```

`outcome` (valores de la spec): `ok`; `iteraciones_agotadas` (rama que devuelve `exhausted_iterations_answer`); `error` (cualquier `Exception`, incluido el `LLMError` por historial que sigue superando la ventana tras compactar); `cancelado` (`CancelledError`, que no es `Exception`: el bucle ya la deja pasar y `finish` solo registra y no la atrapa). Si el mensaje del usuario no llegó a guardarse (error o cancelación antes de la primera persistencia), `user_message_id` queda en `null` (VRJ-006) y el turno es «no revisable» (VRJ-032).

`DailyJsonlWriter.append`: abre `AAAA-MM-DD.jsonl` en modo anexar, escribe la línea completa en **una sola llamada** (≤ 4 KB; se rechaza una línea mayor, VRJ-008) y cierra. La escritura es síncrona y breve; no se usa `asyncio.to_thread` dentro del `finally` para no ceder el control mientras puede estar llegando una cancelación. Se asume (supuesto) que el volumen de `logs/` es un sistema de archivos local POSIX, donde un `write` en modo anexar de una línea corta no se intercala con otro (VRJ-024; se comprueba con hilos concurrentes en la prueba). `purge()` borra los archivos con fecha anterior a `hoy − retention_days`; se llama al crear el recorder y una vez por día de reloj mientras la captura esté activa (VRJ-040). La herramienta de la flota lee archivos por día e ignora una última línea incompleta (contrato, spec sección 6).

### 3.3 Enganche en el bucle (`conversation_loop.py`)

```
run_turn(...):
    obs = None; outcome = "error"; iterations = 0; user_message_id = None
    try:
        lease...; decision = router.route(prompt)
        ... historial, presión de tokens (pressure) ...
        obs = shadow.begin(...) if shadow else None        # tras la presión; nunca lanza
        ... (flujo actual) ...
        # cada return: outcome = "ok" | "iteraciones_agotadas"; iterations = n;
        #              user_message_id = result.user_message_id (o el de la ronda de herramientas)
    except asyncio.CancelledError:
        outcome = "cancelado"; raise
    except Exception:
        outcome = "error"; raise              # incluye LLMError por ventana tras compactar
    finally:
        if obs: obs.finish(outcome, usage, iterations, user_message_id)   # nunca lanza
        ... (liberación de lease actual) ...
```

`finish` jamás lanza (VRJ-007). La decisión de `route()` no se toca.

### 3.4 Revisión ciega (`review.py` y subcomando)

- `jerico route-review --ids-file RUTA` (lista de `user_message_id` que entrega `Flota_Jev` para la muestra de desacuerdos) o `--random N --seed S` (muestra aleatoria de los registros).
- La muestra se arma con `--ids-file` o `--random N --seed S` (VRJ-035); con la misma semilla se obtiene la misma muestra (`random.Random(seed)` sobre la lista ordenada de referencias). Registros con referencia nula se excluyen y se cuentan.
- Por cada elemento: leer el texto en `StateEngine` por id; si no existe → «no revisable» (VRJ-032); mostrar solo el texto y pedir `operativo`, `codigo` o `alto_riesgo`; guardar el juicio en `logs/route_shadow/judgments/AAAA-MM-DD.jsonl` con `user_message_id`, juicio, rol del revisor y fecha-hora, **sin copiar el texto** (VRJ-031).
- No muestra el nivel de las reglas ni la opinión de Jev (VRJ-030). El comando exige `--rol` con el rol de una persona (VRJ-034) y solo funciona con acceso local al almacén (VRJ-033).

## 4. Configuración

Variables nuevas (todas con prefijo `JERICO_`; vacías = no definidas):

| Variable | Valor por defecto | Para qué |
|---|---|---|
| `ROUTE_SHADOW_ENABLED` | `false` | Activa la captura (VRJ-002). |
| `ROUTE_SHADOW_DIR` | `logs/route_shadow` | Directorio de registros. |
| `ROUTE_SHADOW_RETENTION_DAYS` | `90` | Retención (VRJ-040; propuesta). |
| `ROUTE_SHADOW_MONEY` | lista inicial mínima | Léxico «dinero». |
| `ROUTE_SHADOW_CLIENT` | lista inicial mínima | Léxico «cliente o lead». |
| `ROUTE_SHADOW_LEGAL` | lista inicial mínima | Léxico «contrato o legal». |

Listas iniciales mínimas (propuesta, el CTO las aprueba en Q4): dinero → `precio, costo, factura, pago, presupuesto, cobro, nomina`; cliente → `cliente, lead, prospecto, propuesta, cotizacion`; legal → `contrato, clausula, demanda, juridico, ley, habeas`. Se normalizan como las listas del router (`textutil.normalize`, plural opcional).

## 5. Estrategia de pruebas

Todas herméticas (constitución, principio 3). Sin red, sin Jev, sin `Flota_Jev`. Reloj y temporizador inyectados.

| Archivo de pruebas | Qué cubre | Requisitos |
|---|---|---|
| `tests/test_routing_shadow_state.py` | Construcción, topes, enumerados, rechazo de claves extra/faltantes, de tipos y de cadenas libres; **prueba de contrato de privacidad**: ningún valor de tipo `str` fuera de los enumerados (con prompts que contienen correos, teléfonos y nombres). | VRJ-010 a 013, 009, 042 |
| `tests/test_routing_shadow_lexicon.py` | Banderas, plural, tildes, huella estable y sensible al cambio de listas. | VRJ-011, 014 |
| `tests/test_routing_shadow_jsonl.py` | Una línea por registro, archivo del día, `purge` por fecha con reloj falso (en el arranque y al cambiar de día), escritura concurrente desde 20 hilos × 50 líneas sin líneas corruptas ni intercaladas, línea mayor de 4 KB rechazada, falla de disco, **mediana de 100 escrituras reales en `tmp_path` < 5 ms**, lectura que ignora una última línea incompleta. | VRJ-003, 007, 008, 020, 024, 040 |
| `tests/test_routing_shadow_recorder.py` | Apagado por defecto no escribe; nivel 0 no escribe; contadores; fallo de escritura no rompe el turno; `finish` no lanza; campos del registro. | VRJ-002, 003, 004, 007, 009 |
| `tests/test_router_signals.py` | `signals()` coincide con `classify()` en un conjunto de prompts (incluye excepciones y L0); `route()` no cambia. | VRJ-005 |
| `tests/test_routing_shadow_loop.py` | Con `FakeLLM`: el turno con captura activada y desactivada devuelve el **mismo** `TurnResult` (nivel, modelo, respuesta); con un registrador cuyo `finish` falla (excepción inyectada) el turno devuelve lo mismo y la excepción original no cambia; registro con los cuatro resultados (`ok`, `iteraciones_agotadas`, `error`, `cancelado`); la cancelación sigue propagándose; `user_message_id` correcto con y sin rondas de herramientas y nulo cuando el mensaje no se guardó; los reintentos internos del proveedor no generan un segundo registro. | VRJ-003, 005, 006, 007 |
| `tests/test_routing_shadow_isolation.py` | Ningún módulo del paquete importa `flota_jev`, `requests`, `httpx`, `socket` ni `urllib` (análisis del árbol de sintaxis); ni `pyproject.toml` ni `src/` contienen `flota_jev`, `TYPESAFE`, `api.typesafe.ai` ni `jev-latest`; con `socket` sustituido por una función que lanza, el turno con captura funciona. | VRJ-001, 021, 023 |
| `tests/test_routing_shadow_review.py` | Salida de la revisión sin nivel de reglas ni Jev; juicio guardado sin texto; «no revisable» (texto inexistente o referencia nula); misma semilla = misma muestra; `--rol` obligatorio y de persona; la API no expone la ruta. | VRJ-030 a 035 |
| `tests/test_routing_shadow_config.py` | Valores por defecto, variables vacías, `.env.example` contiene las variables nuevas. | VRJ-002, 040 |

Cobertura: el código nuevo debe quedar cubierto de forma que el total se mantenga ≥ 89 % (hoy 92,95 %).

## 6. Matriz requisito → prueba

| Requisito | Archivo de pruebas |
|---|---|
| VRJ-001 | isolation |
| VRJ-002 | recorder, config |
| VRJ-003 | recorder, jsonl, loop |
| VRJ-004 | recorder |
| VRJ-005 | router_signals, loop |
| VRJ-006 | loop |
| VRJ-007 | recorder, jsonl, loop |
| VRJ-008 | jsonl |
| VRJ-009 | recorder, state |
| VRJ-010, 011, 012, 013 | state |
| VRJ-014 | lexicon |
| VRJ-020 | jsonl (esquema versionado, líneas independientes, rotación diaria) |
| VRJ-024 | jsonl (escritura concurrente) |
| VRJ-021 | isolation |
| VRJ-022 | revisión documental (spec, sección 6) y isolation |
| VRJ-023 | isolation |
| VRJ-030, 031, 032, 033, 034, 035 | review |
| VRJ-040 | jsonl, config |
| VRJ-041 | state, recorder |
| VRJ-042 | state |
| VRJ-050 | `./scripts/verify.sh` (ruff, mypy, pytest con cobertura ≥ 89 %) en cada tarea |

## 7. Coordinación con `Flota_Jev` (sin duplicar)

`Flota_Jev` es de `kai-jev`. Desde Jericó solo se le entrega **el contrato** (spec, sección 6) una vez aprobada la spec:
1. Un esquema de estado «router» con los campos de la sección 3.1.
2. Las dos preguntas (`nivel`, `riesgo`) y el consenso de tres.
3. Un importador de `logs/route_shadow/*.jsonl` que descarte `user_message_id` antes de consultar.
4. Un informe con acuerdo, falsos negativos/positivos de alto riesgo según los juicios, Brier, p95 y costo, más un archivo de ids para la revisión ciega.

Verificado: el esquema y las preguntas actuales de la herramienta son de tareas de desarrollo (`estado.py`, `QUESTIONS` en `jev.py`); hay que parametrizarlos, y eso lo decide y lo hace `kai-jev`.

## 8. Despliegue y reversa

- **Hoy:** el núcleo no está desplegado (solo `jerico-crm` en `kaisen-server`); el cambio llega apagado y no tiene efecto.
- **Cuando se despliegue el núcleo:** activar con `JERICO_ROUTE_SHADOW_ENABLED=true` y confirmar que `./logs` está montado (ya lo está en `docker-compose.yml`).
- **Reversa:** apagar el interruptor; no hay migración de datos que deshacer. Los archivos se pueden borrar.
- **Fuera de cobertura:** `jerico ask` (CLI) no pasa por el bucle y no se observa; solo se observan turnos del bucle (API y gateway).

## 9. Riesgos del plan

| Riesgo | Mitigación |
|---|---|
| Tocar el bucle del agente (camino crítico) | Cambio mínimo, observador opcional; pruebas que comparan el `TurnResult` con y sin captura. |
| Cancelación del turno deja el registro sin cerrar | `finish` en `finally`; `cancelado` se registra y la cancelación sigue propagándose (prueba). |
| Turnos sin mensaje guardado no se pueden revisar | Referencia nula declarada «no revisable»; se cuentan aparte (VRJ-032). Si son una fracción grande, se reporta como limitación. |
| El volumen real no alcanza la muestra mínima | Declarado en la spec (máx. 8 semanas y mínimo de 20 positivos). |
| Las listas iniciales de léxico son pobres | Se versionan por huella; el CTO las ajusta (Q4). |
| `jerico ask` queda sin observar | Documentado como fuera de alcance. |

> 🕒 **Última modificación:** 13/10/2026 10:27 (Agente Claude Code · Sonnet 5.5)
