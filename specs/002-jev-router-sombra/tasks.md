---
modificado: "13/10/2026 22:15"
---

# Tareas 002 — Captura en sombra del router (Jev P1)

- **Estado:** **BORRADOR — no se ejecuta ninguna tarea hasta que el CTO apruebe la spec y el plan.** Una tarea por sesión; TDD estricto (rojo → verde); detención obligatoria al terminar cada una.
- **Base:** `spec.md` (requisitos `VRJ-001` a `VRJ-050`) y `plan.md`.
- **Quién ejecuta:** las tareas «Delegable a Gemini: SÍ» las implementa el panel `jer-jev-gem` con un contrato y el director verifica el resultado; las «NO» las trabaja el director (camino crítico del turno, privacidad o coordinación).
- **Fuera de este repo:** el cliente de Jev, el consenso, las métricas y el informe son de `Flota_Jev` (`kai-jev`); aquí solo hay una tarea de entrega del contrato (T14).

## Bloques comunes

**PROH (prohibiciones, aplican a todas):** no tocar `src/jerico/{crm,gateway,tools,state,cron}/`, `tests/conftest.py`, `docker-compose*.yml`, `Dockerfile`, `.env` (solo `.env.example` donde la tarea lo indique), `DECISIONES_CTO.md`, `docs/constitution.md`, `scripts/oci/`. No hacer `git push`. No añadir dependencias a `pyproject.toml`. No importar la herramienta de la flota. No leer ni escribir secretos. No llamar a ninguna red.

**VERIF (comando exacto, desde la raíz del repo):**
```
VIRTUAL_ENV=/home/janty-mr/Kaisen_AI/01_Proyectos/Proyecto_Jerico/.venv ./scripts/verify.sh
```
(`verify.sh` usa `$VIRTUAL_ENV` cuando no hay `.venv` local; el entorno del árbol principal se usa solo para ejecutar, sin modificarlo.) Debe pasar ruff, mypy y pytest con cobertura total ≥ 89 %. Además `pre-commit run --all-files` en verde antes de cada commit.

**Commit:** local, identidad `Santiago Gonzalez <kaisen.ai.santiago.cto@gmail.com>`, mensaje en español con el identificador de la tarea, y solo con autorización del CTO (constitución, principio 10).

---

## A. Base

- [ ] **T01 — Configuración de la captura**
  - **Delegable a Gemini:** SÍ — cambio mecánico y aislado en `config.py` y `.env.example` (el director revisa el diff).
  - Requisitos: VRJ-002, VRJ-014, VRJ-040.
  - **Tests primero:** `tests/test_routing_shadow_config.py`: valores por defecto (`enabled=False`, directorio `logs/route_shadow`, retención 90); variable vacía = no definida; las tres listas de léxico se normalizan; `.env.example` contiene las variables nuevas.
  - **Entregable exacto:** campos `route_shadow_enabled`, `route_shadow_dir`, `route_shadow_retention_days`, `route_shadow_money`, `route_shadow_client`, `route_shadow_legal` en `config.py` (valores iniciales de la sección 4 del plan) y sus líneas en `.env.example`.
  - **Hecho cuando:** el archivo de pruebas pasa y `verify.sh` queda en verde.

- [ ] **T02 — `TokenRouter.signals()`**
  - **Delegable a Gemini:** NO — toca el router, camino crítico de todos los turnos; hay que demostrar que no cambia ninguna decisión.
  - Requisitos: VRJ-005, VRJ-011.
  - **Tests primero:** `tests/test_router_signals.py`: para un conjunto de prompts (saludos, vacío, código, alto riesgo, frases exceptuadas, plurales, tildes) `signals()` coincide con la clasificación de `classify()`; `route()` devuelve lo mismo que antes; `classify()` no cambia.
  - **Entregable exacto:** `RouteSignals` (dataclass inmutable: `is_l0`, `l2_match`, `l3_match`, `l2_exception`) y `TokenRouter.signals(prompt)`, sin tocar `classify()` ni `route()`.
  - **Hecho cuando:** pruebas del router existentes y nuevas pasan, y una prueba de equivalencia recorre ≥ 30 prompts.

## B. Estado compacto

- [ ] **T03 — Estado compacto y su validación**
  - **Delegable a Gemini:** SÍ — función pura con contrato exacto en la spec y el plan (el director revisa la lista cerrada de campos).
  - Requisitos: VRJ-009, VRJ-010, VRJ-011, VRJ-012, VRJ-013, VRJ-042.
  - **Tests primero:** `tests/test_routing_shadow_state.py`: `build_state` con topes; `validate_state` rechaza clave extra, clave faltante, tipo erróneo (un `bool` no vale como entero), entero fuera de rango y enumerado desconocido; **prueba de privacidad**: con prompts que contienen correos, teléfonos y nombres, ningún valor `str` del estado sale fuera de los enumerados de VRJ-011.
  - **Entregable exacto:** `src/jerico/routing_shadow/__init__.py` y `state.py` (`SCHEMA_VERSION`, `CAPS`, `build_state`, `validate_state`, `InvalidShadowState`).
  - **Hecho cuando:** las pruebas pasan y el estado contiene exactamente los campos de la sección 3.1 del plan.

- [ ] **T04 — Léxico ampliado y banderas estructurales**
  - **Delegable a Gemini:** SÍ — funciones puras con casos de prueba claros.
  - Requisitos: VRJ-011, VRJ-012, VRJ-014.
  - **Tests primero:** `tests/test_routing_shadow_lexicon.py`: coincidencia con tildes y plurales; `has_code_block`, `has_figures`, `is_question`; solo se analizan los primeros 10 000 caracteres (un prompt de 1 000 000 de caracteres termina en tiempo acotado); la huella es estable y cambia si cambia una lista.
  - **Entregable exacto:** `routing_shadow/lexicon.py` (`Lexicon`, `from_settings`, `fingerprint`, `lexicon_flags`, `has_code_block`, `has_figures`, `is_question`).
  - **Hecho cuando:** las pruebas pasan; `build_state` (T03) usa `lexicon_flags` sin cambiar su contrato.

## C. Almacenamiento

- [ ] **T05 — Reutilizar el escritor compartido (`shadowlog`)**
  - **Delegable a Gemini:** NO — es una dependencia entre specs: el escritor se construye una sola vez en la spec `006-jev-crm-consejero` (T01).
  - Requisitos: VRJ-003, VRJ-007, VRJ-008, VRJ-020, VRJ-024, VRJ-040.
  - **Entregable exacto:** ninguna pieza nueva de escritura; las pruebas de `tests/test_routing_shadow_jsonl.py` que ya cubre el escritor compartido se sustituyen por una prueba de integración: el registrador usa `DailyJsonlWriter`, una línea por registro, mediana de 100 escrituras reales en `tmp_path` < 5 ms y 20 hilos × 50 líneas sin líneas intercaladas.
  - **Hecho cuando:** `shadowlog` existe (T01 de la spec 006 hecha) y las pruebas de integración pasan. **Si la spec 006 no se implementa, esta tarea vuelve a construir el escritor** como estaba descrito en la versión anterior de este plan.

## D. Registrador

- [ ] **T06 — Registrador de observaciones**
  - **Delegable a Gemini:** NO — lógica de privacidad y de tolerancia a fallos: `finish` no puede lanzar ni alterar el turno.
  - Requisitos: VRJ-002, VRJ-003, VRJ-004, VRJ-005, VRJ-007, VRJ-009, VRJ-041.
  - **Tests primero:** `tests/test_routing_shadow_recorder.py`: apagado por defecto no escribe; nivel 0 no escribe; registro con los campos exactos de VRJ-003; estado inválido no escribe y cuenta; `OSError` y `ValueError` al escribir no se propagan y cuentan; los cuatro resultados (`ok`, `iteraciones_agotadas`, `error`, `cancelado`); el aviso de log no contiene el texto del prompt (se comprueba con un prompt marcador).
  - **Entregable exacto:** `routing_shadow/recorder.py` (`ShadowRecorder`, `TurnObservation`, contadores).
  - **Hecho cuando:** las pruebas pasan y el registro nunca contiene texto del prompt.

## E. Integración en el bucle

- [ ] **T07 — Identificador del mensaje del usuario en `TurnResult`**
  - **Delegable a Gemini:** NO — toca el finalizador y el tipo del resultado del turno.
  - Requisitos: VRJ-006.
  - **Tests primero:** en `tests/test_routing_shadow_loop.py` (parte 1): `TurnResult.user_message_id` es el id de la fila del mensaje del usuario cuando el finalizador lo guarda, es `None` por defecto y no cambia el resto del resultado; los tests existentes del finalizador siguen pasando.
  - **Entregable exacto:** campo `user_message_id: int | None = None` en `agent/types.py`; `TurnFinalizer` recoge el id que ya devuelve `append_messages`.
  - **Hecho cuando:** las pruebas existentes y nuevas pasan; ningún llamador existente cambia.

- [ ] **T08 — Enganche del observador en el bucle y en la API**
  - **Delegable a Gemini:** NO — camino crítico: `try/finally` del turno, cancelación y reintentos.
  - Requisitos: VRJ-003, VRJ-005, VRJ-006, VRJ-007, VRJ-002.
  - **Tests primero:** `tests/test_routing_shadow_loop.py` (parte 2), con `FakeLLM`: el turno con captura activada y con captura apagada devuelve el mismo `TurnResult`; un `finish` que lanza (inyectado) no cambia el resultado ni la excepción; registro con `ok`, `iteraciones_agotadas`, `error` y `cancelado` (la cancelación se sigue propagando); `user_message_id` correcto con y sin rondas de herramientas y nulo si el mensaje no se guardó; los reintentos internos del proveedor no generan un segundo registro; un turno de nivel 0 no registra.
  - **Entregable exacto:** parámetro opcional `shadow` en `AgentTurnLoop`; `begin()` tras la evaluación de presión; `finish()` en el `finally`; construcción del `ShadowRecorder` desde `Settings` en `api.py`.
  - **Hecho cuando:** las pruebas del bucle existentes y nuevas pasan, y con la variable apagada el comportamiento es idéntico al de antes de la rama.

## F. Revisión ciega

- [ ] **T09 — Biblioteca de revisión ciega**
  - **Delegable a Gemini:** SÍ — lógica aislada y probada (el director revisa que nada del nivel de reglas ni de Jev llegue a la salida).
  - Requisitos: VRJ-030, VRJ-031, VRJ-032, VRJ-035, VRJ-041.
  - **Tests primero:** `tests/test_routing_shadow_review.py` (parte 1): la salida de un elemento contiene solo el texto; muestra por lista de referencias y por semilla (misma semilla = misma muestra); referencias nulas excluidas y contadas; texto inexistente = «no revisable»; el juicio se guarda con referencia, valor, rol y fecha-hora y **sin el texto**.
  - **Entregable exacto:** `routing_shadow/review.py` (`load_review_items`, `ReviewItem`, `record_judgment`).
  - **Hecho cuando:** las pruebas pasan sin red.

- [ ] **T10 — Subcomando `route-review`**
  - **Delegable a Gemini:** SÍ — conexión sencilla a la CLI existente (el director revisa `--rol` y que no exista ruta en la API).
  - Requisitos: VRJ-033, VRJ-034, VRJ-035.
  - **Tests primero:** `tests/test_routing_shadow_review.py` (parte 2): el comando exige `--rol` con valor de persona; `--ids-file` y `--random/--seed`; ninguna ruta de la API devuelve prompts ni juicios.
  - **Entregable exacto:** subcomando en `main.py` que usa `review.py`.
  - **Hecho cuando:** las pruebas pasan y `verify.sh` queda en verde.

## G. Cierre

- [ ] **T11 — Pruebas de aislamiento**
  - **Delegable a Gemini:** SÍ — prueba estática, sin tocar código de producción.
  - Requisitos: VRJ-001, VRJ-021, VRJ-023.
  - **Tests primero:** `tests/test_routing_shadow_isolation.py`: ningún módulo del paquete importa `flota_jev`, `requests`, `httpx`, `socket` ni `urllib` (árbol de sintaxis); ni `pyproject.toml` ni `src/` contienen `flota_jev`, `TYPESAFE`, `api.typesafe.ai` ni `jev-latest`; con `socket` sustituido por una función que lanza, un turno con captura activada funciona.
  - **Hecho cuando:** las pruebas pasan.

- [ ] **T12 — Documentación de despliegue**
  - **Delegable a Gemini:** SÍ — documentación.
  - Requisitos: VRJ-002, VRJ-040.
  - **Entregable exacto:** apartado en `docs/despliegue-vps.md` con las variables nuevas, el volumen `logs`, la retención y el procedimiento para activar y apagar la captura. Con marca de tiempo.
  - **Hecho cuando:** el apartado existe y coincide con `config.py`.

- [ ] **T13 — Verificación final y revisión**
  - **Delegable a Gemini:** NO — la hace el revisor (`reviewer`) con veredicto binario.
  - Requisitos: todos (VRJ-001 a VRJ-050).
  - **Entregable exacto:** informe del revisor con recorrido requisito por requisito contra las pruebas.
  - **Hecho cuando:** `./scripts/verify.sh` en verde con cobertura ≥ 89 %, `pre-commit run --all-files` en verde y veredicto `APROBADO`.

- [ ] **T14 — Entrega del contrato a `kai-jev`**
  - **Delegable a Gemini:** NO — coordinación entre directores.
  - Requisitos: VRJ-022.
  - **Entregable exacto:** mensaje a `kai-jev` con la sección 6 de la spec y la sección 3.1 del plan (esquema del estado y preguntas), sin duplicar ni modificar `Flota_Jev`.
  - **Hecho cuando:** `kai-jev` confirma qué parte parametriza (esquema, preguntas, importador, archivo de referencias).

---

## Orden y dependencias

`T01` y `T02` son independientes → `T03` (usa `T02`) → `T04` → `T05` → `T06` (usa `T03`, `T04`, `T05`) → `T07` → `T08` (usa `T06`, `T07`) → `T09` → `T10` → `T11` → `T12` → `T13`. `T14` puede hacerse en cuanto se apruebe la spec.

## Cobertura de requisitos

| Requisito | Tareas |
|---|---|
| VRJ-001, 021, 023 | T11 |
| VRJ-002 | T01, T06, T08 |
| VRJ-003 | T05, T06, T08 |
| VRJ-004 | T06 |
| VRJ-005 | T02, T06, T08 |
| VRJ-006 | T07, T08 |
| VRJ-007 | T05, T06, T08 |
| VRJ-008 | T05 |
| VRJ-009 | T03, T06 |
| VRJ-010 a 013, 042 | T03 |
| VRJ-014 | T01, T04 |
| VRJ-020, 024 | T05 |
| VRJ-022 | T14 |
| VRJ-030, 031, 032, 035 | T09 |
| VRJ-033, 034 | T10 |
| VRJ-040 | T01, T05, T12 |
| VRJ-041 | T06, T09 |
| VRJ-050 | T13 (y `verify.sh` en cada tarea) |

> 🕒 **Última modificación:** 13/10/2026 22:15 (Agente Claude Code · Sonnet 5.5)
