---
modificado: "13/10/2026 22:41"
---

# Plan 007 — Capa de decisión con Jev para todo Jericó

- **Estado:** **BORRADOR (versión 3, tras dos auditorías QA) — depende de la aprobación de la spec 007 (Gate 1)**. Con la spec aprobada pasa a Gate 2.
- **Spec que implementa:** `specs/007-jev-transversal/spec.md` (requisitos `VJT-001` a `VJT-091`, incluidos VJT-010a, VJT-026, VJT-036, VJT-037, VJT-046 y VJT-055). El módulo CRM-consejero (`crm-consejero/`, requisitos `VJC-`) conserva su propio plan y sus tareas.
- **Principio rector:** primero la parte **sin red** (política, estado, registro, modos `apagado` y `sombra`); la consulta en línea a Jev, la sugerencia y el enrutado llegan después, con evidencia y con la orden del CTO para cada paso.
- **Hechos verificados** (ramas leídas con `git show`, sin cambiarlas):
  - El asistente del CRM usa un único cliente y un único modelo (`gpt-6-luna`, Responses API de OpenAI) construido en `crm/app.py`; no hay enrutador. Su contexto máximo es de 6 000 caracteres (`assistant.py`) y los topes son 60 000 tokens/día y 20 llamadas por usuario (`config.py`).
  - El núcleo resuelve `nivel → (url, llave, modelo)` en `Settings.endpoint_for`, por lo que ya admite un proveedor distinto por nivel (`config.py`, `llm_client.py`).
  - La spec 005 define `decidir(pregunta, estado) → opción` con regla fija de respaldo y R11 (registrar `model`, costo y tokens; sin texto libre hacia Jev).
  - La spec 004 excluye a OpenAI de los encargados de datos de contratos y prohíbe decisiones de LLM sobre textos jurídicos.
  - La herramienta de la flota tiene un cliente de Jev de unas 240 líneas con biblioteca estándar, y existe además `scripts/jev_decidir.py`; Trading tiene un tercero.
  - El escritor de archivos diarios `shadowlog` se construye en la tarea T01 del módulo CRM-consejero y la spec 002 lo reutiliza.
- **Base de código:** igual que el módulo CRM-consejero: la implementación sale de una rama que contenga el despliegue real del CRM (`d0aeab3` o su integración), acordada con `crm-director`; la rama `jev/p1-router-spec` solo guarda documentos.

## 1. Decisiones de diseño y alternativas descartadas

| Id | Decisión | Alternativas descartadas y motivo |
|---|---|---|
| **P-1** | **Un paquete común `jerico/decision/`**, independiente de `jerico.crm` y del núcleo, que ambos importan. Toda la lógica de seguridad (conjunto permitido, piso por clase, validación y rangos del estado) vive ahí. | Una copia por área: cada una reimplementaría los pisos y divergirían. Ponerlo dentro de `jerico.crm`: el núcleo y Hermes tendrían que importar el CRM. |
| **P-2** | **Política base declarativa y versionada** en un archivo JSON dentro del paquete (sin dependencias nuevas), con, por cada par (tipo, tarea): clase, esquema de estado con rangos, opciones con criterio, orden de exigencia, función de opciones permitidas, base y modo por defecto. | Código disperso: no se puede auditar ni versionar. YAML: exigiría una dependencia. |
| **P-3** | **Dos niveles de entrega.** Nivel 1 (sin red): modos `apagado` y `sombra`; el producto registra estado y opción base, y la herramienta de la flota consulta a Jev por separado y escribe las respuestas en un archivo aparte unido por el identificador de evento (VJT-046, VJT-054). Nivel 2 (en línea): cliente de Jev dentro del producto para `sugerencia` y `enrutado`, solo tras promoción. | Consulta en línea desde el primer día: pone una llave y un tercero en el camino de cada petición sin evidencia de que sirva. |
| **P-4** | **El conjunto permitido lo calcula el código** a partir de la política y de la clase de datos; Jev solo elige dentro (VJT-001, VJT-002). Con una sola opción no se consulta ni cuenta para promoción (VJT-008). | Pedirle a Jev que elija entre todos los modelos y filtrar después: gasta llamadas y puede proponer opciones prohibidas. |
| **P-5** | **Piso por clase en una función pura** `apply_floor(clase, orden, base, jev, permitidas)`, con pruebas de propiedades (nunca fuera de lo permitido; en clase B nunca menos exigente que la base según el orden del tipo; en clase A siempre la base; en el asesor nunca se aplica). | Reglas repartidas por tipo: fáciles de olvidar al añadir un tipo. |
| **P-6** | **Caché, cortacircuitos y un solo vuelo en memoria** del proceso (se reinician con él). | Caché en base de datos: añade migraciones y estado compartido para un dato recalculable. |
| **P-7** | **Cliente único de Jev** (Q1): propuesta (a), el producto posee `jev_client` y la herramienta de la flota lo importa; solo biblioteca estándar. | (c) Copiarlo: lo prohíbe VJT-050. (b) Paquete compartido nuevo: requiere un repositorio y una publicación que hoy no existen. |
| **P-8** | **Registro con el escritor compartido** (`shadowlog`) y esquema versionado, en archivos diarios como el registro de auditoría existente; las métricas las calcula la herramienta de la flota. | Tabla en la base de dominio: migraciones y datos de observación mezclados con datos de clientes; calcular métricas en producción: duplicaría la flota. |
| **P-9** | **Dos identificadores:** *clave de decisión* determinista (para la caché y para decidir si dos casos son equivalentes) e *identificador de evento* único por ocurrencia (instante en UTC más una secuencia por proceso), sin datos personales (VJT-041). | Un solo identificador determinista: decisiones de leads distintos con el mismo estado se deduplicarían y se perdería la trazabilidad por decisión. |
| **P-10** | **Estado con rangos** definidos en la política (VJT-020): el estado nunca lleva enteros exactos, solo cubos. El mínimo de leads para estados individuales (VJT-026) lo aplica la herramienta de la flota al leer. | Enteros exactos con tope: con pocos leads, combinaciones de días y conteos pueden identificar a un titular. |
| **P-11** | **Señal local de apagado general:** archivo marcador fuera de la carpeta de retención, comprobado en cada decisión (VJT-014); la variable de entorno queda como equivalente que exige reiniciar. La **degradación** automática (VJT-015) se guarda también en archivos marcadores por tipo para que sobreviva a los reinicios. | Solo variable de entorno: exigiría reiniciar el proceso. Degradación solo en memoria: al reiniciar volvería a un modo promovido sin orden del CTO. |
| **P-12** | **Consenso solo fuera de línea** (herramienta de la flota); en línea, una consulta por decisión (VJT-035). | Consenso de 3 en línea: triplica latencia y costo en el camino de la petición. |

**Efecto en la constitución:** el modo en línea (Nivel 2) introduce `jev-latest`, que choca con el principio 5; hoy **no consta** una enmienda ni una excepción escrita, solo la decisión del CTO del 12/10 para la herramienta de la flota. Debe resolverse por escrito (Q8 de la spec) **antes** de implementar el Nivel 2. El Nivel 1 no la necesita porque no llama a Jev. Principio 6 (secretos): la llave solo en el `.env` del servidor. Principio 3 (pruebas herméticas): el cliente se prueba con transporte inyectado.

## 2. Archivos y funciones

Todo el código nuevo vive en `src/jerico/decision/` salvo los puntos de enganche indicados.

| Archivo | Contenido | Pura / con efectos |
|---|---|---|
| `decision/__init__.py` | Reexporta `decidir`, `Decision`, `Mode`. | — |
| `decision/policy.json` | Política base v1: tipos, clase, esquema de estado, opciones con criterio, base, modo por defecto `apagado`. | Datos |
| `decision/policy.py` | `load_policy()`, `PolicyKind`, `Policy.version`, validación de la política al cargarla (clase válida, base ∈ opciones, estado con lista cerrada). | Pura |
| `decision/state.py` | `validate_state(kind, state)`; `InvalidState`; enumeraciones comunes (`DataClass`). Rechaza cualquier valor fuera de la lista cerrada del tipo. | Pura |
| `decision/floor.py` | `allowed_options(kind, ctx)` y `apply_floor(clase, orden, base, jev, allowed)`. | Pura |
| `decision/cache.py` | `DecisionCache(ttl, clock)`; `decision_key(kind, tarea, state, policy_version)`; `SingleFlight`; `new_event_id(clock, seq)`. | Pura con reloj inyectado |
| `decision/breaker.py` | `CircuitBreaker(threshold, cooldown, clock)`. | Pura con reloj inyectado |
| `decision/recorder.py` | `DecisionRecorder(writer)`; escribe una línea por decisión (VJT-040) y nunca lanza. | Con efectos |
| `decision/port.py` | `decidir(kind, tarea, state, *, ctx) -> Decision`; `Decision(option, source, reason, event_id, decision_key, suggested)`. Orquesta: modo, permitido, caché, cortacircuitos, cliente, piso, registro. Nunca lanza. | Orquestación |
| `decision/jev_client.py` | **Nivel 2.** `JevClient(transport, key, timeout)`; arma la consulta, reintenta 429 y 529, interpreta `choice` y `score`, devuelve la versión del modelo. Solo biblioteca estándar. | Con efectos (red) |
| `decision/config.py` | Lectura de `JERICO_DECISION_*` (ver sección 4). | Pura |
| `crm/` (enganche) | `assistant.py`: llamada a `decidir("modelo_asistente", …)` antes del modelo (inactiva por VJT-008). `advisor_*`: el módulo CRM-consejero registra `seguimiento_lead`. | Modificación mínima |
| `.env.example`, `docs/` | Variables nuevas; apartado de despliegue y de reversa. | — |

**No se añaden dependencias** (`pyproject.toml` no cambia).

## 3. Diseño detallado

### 3.1 `decidir`

```
decidir(kind, tarea, state, *, ctx) -> Decision:     # nunca lanza (VJT-030)
    evento = nuevo_event_id()                         # instante UTC + secuencia (VJT-041)
    try:
        spec = policy.par(kind, tarea)                # clase, orden, base, esquema (VJT-009)
        mode = "apagado" if kill_activo() else config.mode_for(kind)       # VJT-014
        data_class = mas_restrictiva(spec.clase_datos, ctx.clase_datos)    # VJT-022
        if not state_valido(spec, state): return registrar(evento, base, "base", "estado_invalido")   # VJT-025, en todos los modos
        allowed = allowed_options(spec, ctx, data_class)   # lo calcula el código (VJT-001)
        base = spec.base(ctx)
        if len(allowed) == 1: return registrar(evento, allowed[0], "base", "una_opcion")   # VJT-008
        if spec.clase == "A" or spec.asesor or mode in ("apagado", "sombra"):
            if mode == "sombra" and nivel2_disponible: consulta_en_linea_solo_para_registro()
            return registrar(evento, base, "base", mode)                  # VJT-003, 010a, 011
        clave = decision_key(kind, tarea, state, policy.version)
        if hit := cache.get(clave): return registrar(evento, hit, "cache", ...)
        if breaker.open(): return registrar(evento, base, "respaldo", "cortacircuitos")
        answer = single_flight(clave, lambda: jev.consultar(spec, state, timeout=3s))   # VJT-031, 036
        if answer es inválida / desconocida / fuera de allowed: base con motivo (VJT-002)
        if answer.empate: base (VJT-037, se resuelve aquí, donde se ven las probabilidades)
        aplicada = apply_floor(spec.clase, spec.orden, base, answer.option, allowed)
        if mode == "sugerencia": aplicada = base       # la opción de Jev solo se registra / muestra al CTO
        cache.put(clave, answer.option)              # se cachea la respuesta de Jev, no la opción aplicada; la clave no incluye el modo
        return registrar(evento, aplicada, "jev", sugerida=answer.option, ...)
    except Exception:
        return registrar_sin_lanzar(evento, base_o_defecto, "respaldo", "excepcion")
```

En el Nivel 1, `jev` no existe: con modo `sombra` se registra el estado y la base, y la herramienta de la flota lee ese registro, consulta a Jev (con consenso, rangos y el mínimo de leads) y escribe sus respuestas en un archivo aparte unido por el identificador de evento (VJT-046, VJT-054). El registro original no se modifica.

### 3.2 Piso por clase (`floor.py`)

```
apply_floor(clase, orden, base, jev, allowed):
    if jev not in allowed: return base
    if clase == "A": return base
    if clase == "B": return jev if orden.index(jev) >= orden.index(base) else base   # solo subir
    if clase == "C": return jev            # ya restringido a 'allowed' y a data_class permitida
```

El orden de exigencia lo declara la política por tipo (sección 4 de la spec). Para `ruta_consulta_financiera` el orden es conceptual < herramienta < humano, de modo que desde la base «herramienta» Jev solo puede subir a «humano».

### 3.3 Conjunto permitido

`allowed_options(kind, ctx)` combina: opciones de la política para ese tipo; filtro por `data_class` (VJT-024: `con_datos_personales` solo admite los modelos que la política marque como aptos para datos personales); filtro por rol; filtro por efecto externo (VJT-007). Con la política v1, para `modelo_asistente` el resultado es `{gpt-6-luna}` en toda tarea actual del asistente.

### 3.4 Clase de datos

La calcula quien llama, y entra por `ctx`. Regla (VJT-022, VJT-023): `seudonimizado_verificado` solo si el contexto se construyó en origen con campos estructurados de lista cerrada más los marcadores del seudonimizador, y el constructor del contexto lo declara con una marca explícita de que no incluyó ningún campo de texto libre; `sin_datos_personales` si la tarea no usa datos de titulares; en cualquier otro caso `con_datos_personales`. Hoy el constructor de contexto del asistente incluye texto libre (hasta 6 000 caracteres y, si se activan, notas), por lo que todas las tareas del asistente son `con_datos_personales`.

## 4. Configuración

| Variable | Valor por defecto | Para qué |
|---|---|---|
| `JERICO_DECISION_MODES` | vacío (= todos `apagado`) | Modo por tipo, p. ej. `seguimiento_lead=sombra`. |
| `JERICO_DECISION_KILL` | `false` | Apagado general por configuración (exige reiniciar). El archivo marcador `decision.KILL` en el directorio de datos del producto, **fuera** del directorio de retención del registro, lo hace sin reiniciar (VJT-014). |
| `JERICO_DECISION_DIR` | `logs/decision` | Directorio del registro. |
| `JERICO_DECISION_RETENTION_DAYS` | `90` | Retención (VJT-043). |
| `JERICO_DECISION_TIMEOUT_S` | `3` | Tiempo máximo (VJT-031), **Nivel 2**. |
| `JERICO_DECISION_BREAKER` | `3,300` | Fallos seguidos y segundos de pausa (VJT-032, VJT-015), **Nivel 2**. |
| `JERICO_DECISION_MIN_LEADS` | `20` | Mínimo de leads activos para que la flota use estados de lead (VJT-026); lo lee la herramienta de la flota. |
| `JERICO_DECISION_CACHE_TTL_S` | `86400` | Vigencia de la caché (VJT-034). |
| `JERICO_DECISION_ONLINE` | `false` | Habilita el Nivel 2 (consulta en línea) además de la llave (VJT-054). |
| `TYPESAFE_API_KEY` | vacía | Llave de Jev, solo en el `.env` del servidor; **Nivel 2**. La coloca el CTO. |

## 5. Orden de entrega (fases)

| Fase | Contenido | Condición para empezar |
|---|---|---|
| **F0 — Capa común sin red** | Política, estado, piso, caché, registro, `decidir` en modos `apagado` y `sombra`; pruebas de propiedades y de aislamiento. | Aprobación de esta spec (Gate 1) y del plan. |
| **F1 — CRM** | Tipo `seguimiento_lead` (módulo CRM-consejero) en `sombra`; `modelo_asistente` registrado e inactivo (VJT-008). | F0 hecha; Q2 y Q5 del módulo resueltas; `crm-director` acuerda la base. |
| **F2 — Cliente en línea** | `jev_client`, cortacircuitos, tiempo máximo, modo `sugerencia` solo para el CTO. | Orden del CTO; excepción de `jev-latest` por escrito; Q1 y Q5 resueltas; llave colocada por el CTO. |
| **F3 — Enrutado de una tarea de clase C** | Un segundo proveedor de LLM, tarifas verificadas y una tarea ligera real; promoción por evidencia. | Spec 005 (A1/A6) con LLM multi-proveedor; Q2 y Q3; orden del CTO. |
| **F4 — Otras áreas** | `nivel_turno` (spec 002), `modelo`, `habilidad`, `escalar_humano`, `siguiente_paso_voz` (spec 005), `riesgo_pieza` (spec 008), `ruta_consulta_financiera` (spec 006). | Cada spec aprobada e implementada por su responsable. |

## 6. Estrategia de pruebas

Herméticas: sin red, sin Jev (transporte inyectado), relojes inyectados, bases temporales.

| Archivo de pruebas | Qué cubre | Requisitos |
|---|---|---|
| `tests/test_decision_policy.py` | La política v1 carga **con todos sus tipos y tareas**; rechaza clase inválida, base fuera de las opciones, par sin esquema de lista cerrada, orden de exigencia ausente en la clase B y modo por defecto distinto de `apagado`; la tabla tarea → clase coincide con la de la spec; la versión es estable. | VJT-006, 009, 010 |
| `tests/test_decision_state.py` | Estado válido con rangos; la validación se aplica en todos los modos antes de registrar (un estado inválido no se registra); rechaza enteros exactos fuera de cubo, clave extra o faltante, tipos erróneos y cadenas fuera de enumerado; **prueba de privacidad**: marcadores (correo, teléfono, nombre, id) nunca pasan. | VJT-020, 021, 025 |
| `tests/test_decision_floor.py` | **Propiedades** sobre todas las combinaciones de clase, orden, base, respuesta y permitidas: nunca fuera de lo permitido; clase A siempre la base; clase B nunca menos exigente que la base (en `ruta_consulta_financiera` nunca a «conceptual»); asesor nunca aplicado; con una sola opción no se consulta ni cuenta para promoción; `con_datos_personales` nunca admite DeepSeek; un contexto sin la marca de «sin texto libre» se trata como `con_datos_personales`; entre la clase de datos de la política y la del llamador gana la más restrictiva; formato inválido, opción desconocida y fuera de permitidas dan motivos distintos. | VJT-001 a 010a, 024, 037 |
| `tests/test_decision_port.py` | **Empate → base** (se resuelve aquí); la sugerencia de Jev queda en el campo `suggested` y no se pierde por la caché; cambiar de modo no reutiliza resultados viejos; Modos: `apagado` y `sombra` aplican la base; `sugerencia` aplica la base y expone la opción solo con rol CTO verificado; `enrutado` aplica el piso; apagado general por archivo marcador sin reiniciar (la variable exige reiniciar); degradación a `sombra` desde `sugerencia` y `enrutado` que **persiste tras un reinicio**; `cohorte_suficiente` falsa → no consulta en línea; nunca lanza ante fallos del registro, la caché o el cliente; sin llave → base y aviso único; alerta por volumen anómalo solo con 14 días de historia y mediana ≥ 10; la consulta de 2 s simulada no retrasa a otro mensaje más de 100 ms. | VJT-010 a 015, 030, 033, 044, 052 |
| `tests/test_decision_cache.py` | Identificadores de evento sin colisión entre dos procesos simulados y tras un reinicio con el mismo instante; Misma clave → `cache`; vigencia; otra versión de política no reutiliza; dos casos distintos con el mismo estado tienen la misma clave pero eventos distintos; **un solo vuelo**: 20 decisiones simultáneas con la misma clave hacen una consulta. | VJT-034, 036, 041 |
| `tests/test_decision_breaker.py` | Se abre tras N fallos, se cierra tras la pausa, con reloj falso. | VJT-032 |
| `tests/test_decision_recorder.py` | Campos obligatorios en todos los modos y campos solo con consulta; sin texto libre; costo «no calculado» sin tarifas de modelos; el registro es solo de anexión y lleva el identificador de evento; repetir un evento con el mismo identificador no duplica el registro; retención; no lanza ante falla de disco. | VJT-040, 043, 045, 046 |
| `tests/test_decision_jev_client.py` | **Nivel 2**, con transporte falso: interpreta `choice` y `score`, reintenta 429 y 529, tiempo máximo, versión del modelo, una sola consulta por decisión, la llave nunca aparece en errores ni registros. | VJT-031, 035, 051, 053 |
| `tests/test_decision_isolation.py` | Nivel 1: ningún módulo importa red; ninguna llamada de red con `apagado` y `sombra`; la lista de dependencias es idéntica a la de la rama base; la dirección del servicio de TypeSafe solo aparece en `jev_client`. | VJT-050, 054, 091 |
| `tests/test_decision_areas.py` | Reglas por área: precios nunca ofrecen calcular; marketing nunca ofrece publicar o gastar; contratos, firma y bajas son clase A; `seguimiento_lead` es asesor en `sombra`; un proveedor nuevo con datos personales exige el registro previo de encargados (comprobación documental). | VJT-055, 060 a 063 |

Cobertura: los módulos nuevos al 100 % y el total ≥ 89 %.

## 7. Matriz requisito → prueba

| Requisito | Archivo de pruebas |
|---|---|
| VJT-001 a 010a | floor, port, policy |
| VJT-010, 011, 012, 013, 014, 015 | port |
| VJT-020, 021, 025 | state |
| VJT-022, 023, 024 | floor, state |
| VJT-026 | port (bandera y no consulta) y contrato con la herramienta de la flota |
| VJT-030, 033 | port |
| VJT-031, 035 | jev_client |
| VJT-032 | breaker |
| VJT-034, 036 | cache |
| VJT-037 | port |
| VJT-040, 043, 045, 046 | recorder |
| VJT-041 | cache, recorder |
| VJT-042 | tarea documental T18 y pruebas de cada herramienta que dispare acciones (en su spec) |
| VJT-044 | port |
| VJT-050, 054, 091 | isolation |
| VJT-051, 052, 053 | jev_client, port |
| VJT-055 | tarea T20 (proceso con el abogado; verificación documental) |
| VJT-060 a 063 | areas |
| VJT-090 | `verify.sh` en cada tarea |

## 8. Coordinación y dependencias (sin duplicar)

- **`kai-jev` (spec 005 y `Flota_Jev`):** acordar (1) que `decidir(kind, state)` de esta spec es la función de su §3.1; (2) los nombres de los tipos y sus estados; (3) la decisión Q1 del cliente único; (4) el esquema del registro, que la herramienta de la flota leerá para sus informes. La spec 005 ya contiene su §3.1; si algo diverge, se corrige en la 005, no aquí.
- **`crm-director`:** base de código común y confirmación de que los temas de la spec 004 son clase A.
- **Director:** tarifas verificadas (Q2); actualizar §4 del Plan maestro solo al promover un tipo a `enrutado`.
- **`kz-marca` (spec 008) y `kai-jev` (spec 006):** reciben las reglas VJT-060 y VJT-061 como requisitos de su lado.

## 9. Despliegue y reversa

- **F0 y F1** llegan con todos los tipos en `apagado` o `sombra` y sin llamadas de red: no cambian el comportamiento del CRM.
- **Activar:** solo con la orden del CTO, en el `.env` del servidor (lo hace el orquestador con el CTO). Esta spec no toca el servidor.
- **Reversa:** `JERICO_DECISION_KILL=true` o vaciar `JERICO_DECISION_MODES`; borrar el directorio del registro. No hay migraciones.

## 10. Riesgos del plan

| Riesgo | Mitigación |
|---|---|
| Una política mal configurada abre una opción prohibida | Propiedades en `test_decision_floor`, validación de la política al cargarla y versión en cada registro. |
| La capa se vuelve obligatoria para el camino crítico | `decidir` nunca lanza y siempre devuelve la base; interruptor general. |
| Diverge de la spec 005 | Alineación explícita con `kai-jev` y la 005 como fuente de los puntos de decisión de Hermes. |
| Se construye más de lo que el volumen justifica | Las fases F2 y F3 esperan evidencia; F0 y F1 son pequeñas y sin red. |
| El registro acumula datos que no debería | Estado de lista cerrada, prueba de privacidad y retención de 90 días. |

> 🕒 **Última modificación:** 13/10/2026 22:41 (Agente Claude Code · Sonnet 5.5)
