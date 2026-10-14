---
modificado: "13/10/2026 22:41"
---

# Tareas 007 — Capa de decisión con Jev para todo Jericó

- **Estado:** **BORRADOR (versión 3) — no se ejecuta ninguna tarea hasta que el CTO apruebe la spec y el plan.** Una tarea por sesión; TDD estricto (rojo → verde); detención obligatoria al terminar cada una.
- **Base:** `spec.md` (requisitos `VJT-001` a `VJT-091`) y `plan.md`. El módulo CRM-consejero tiene sus propias tareas en `crm-consejero/tasks.md` (T01 a T11 de ese módulo, requisitos `VJC-`).
- **Base de código:** las tareas se ejecutan sobre una rama que contenga el despliegue real del CRM (`d0aeab3` o su integración), acordada con `crm-director` (tarea T17). La rama `jev/p1-router-spec` solo guarda documentos.
- **Quién ejecuta:** las «Delegable a Gemini: SÍ» las implementa `jer-jev-gem` con un contrato y el director verifica; las «NO» las trabaja el director. Las tareas marcadas **BLOQUEADA** no se empiezan hasta cumplir la condición escrita.
- **Pasos con gasto o despliegue:** ninguno de estos requiere pagos. Activar cualquier modo en el servidor, colocar la llave de Jev y desplegar piden el OK explícito del CTO para ese paso.

## Bloques comunes

**PROH (aplican a todas):** no tocar `src/jerico/crm/{compliance,retention,leads,replies,followup,pseudonym,llm}.py` (salvo lo que diga T10), `src/jerico/{gateway,tools,state,cron}/`, `tests/conftest.py`, `docker-compose*.yml`, `Dockerfile`, `.env` (solo `.env.example`), `DECISIONES_CTO.md`, `docs/constitution.md`, `scripts/oci/`. No hacer `git push`. No añadir dependencias a `pyproject.toml`. No importar la herramienta de la flota. No leer ni escribir secretos. No llamar a ninguna red. No tocar el servidor.

**VERIF (desde la raíz del repo):**
```
VIRTUAL_ENV=/home/janty-mr/Kaisen_AI/01_Proyectos/Proyecto_Jerico/.venv ./scripts/verify.sh; echo "código=$?"
```
Se guarda el código de salida real (sin tuberías que lo oculten). Debe pasar ruff, mypy y pytest con cobertura total ≥ 89 %. Además `pre-commit run --all-files` en verde antes de cada commit.

**Commit:** local, identidad `Santiago Gonzalez <kaisen.ai.santiago.cto@gmail.com>`, mensaje en español con el identificador de la tarea, solo con autorización del CTO (constitución, principio 10).

---

## A. Capa común sin red (F0)

- [x] **T01 — Cargador y validador de la política**
  - **Delegable a Gemini:** SÍ — código de carga y validación con contrato exacto (el director revisa las reglas de validación).
  - Requisitos: VJT-006, VJT-010.
  - **Tests primero:** `tests/test_decision_policy.py`: carga una política mínima; rechaza clase inválida, base fuera de las opciones, tipo sin esquema de estado de lista cerrada, clase B sin orden de exigencia y modo por defecto distinto de `apagado`; la versión de la política es estable.
  - **Entregable exacto:** `src/jerico/decision/__init__.py` y `policy.py` (`load_policy`, `Policy`, `PolicyKind`).
  - **Hecho cuando:** las pruebas pasan sin red.

- [x] **T02 — Contenido de la política v1**
  - **Delegable a Gemini:** NO — define qué puede decidir Jev en cada tipo (clases, bases, opciones permitidas por clase de datos): seguridad y privacidad.
  - Requisitos: VJT-003, VJT-004, VJT-005, VJT-007, VJT-009, VJT-010a, VJT-024, VJT-060 a VJT-063.
  - **Tests primero:** parte de `tests/test_decision_areas.py`: ningún tipo de precios ofrece calcularlos; ningún tipo de marketing ofrece publicar o gastar; contratos, firma y bajas no figuran como tipos consultables; `con_datos_personales` solo admite los modelos aptos; `seguimiento_lead` es asesor y su salida nunca se aplica; la tabla tarea → clase coincide con la de la spec; `ruta_consulta_financiera` solo puede subir hacia «humano».
  - **Entregable exacto:** `src/jerico/decision/policy.json` con los tipos de la sección 4 de la spec.
  - **Hecho cuando:** carga con T01 y las pruebas pasan; el revisor confirma que no hay opción prohibida.

- [x] **T03 — Validación del estado**
  - **Delegable a Gemini:** NO — privacidad (Ley 1581): decide qué puede salir hacia un tercero.
  - Requisitos: VJT-020, VJT-021, VJT-025.
  - **Tests primero:** `tests/test_decision_state.py`: la validación se aplica antes de registrar en todos los modos; rechaza enteros exactos fuera de cubo, clave extra o faltante, tipo erróneo (un `bool` no vale como entero), entero fuera de tope y cadena fuera del enumerado; **prueba de privacidad** con marcadores únicos (correo, teléfono, nombre, id) que nunca pasan.
  - **Entregable exacto:** `src/jerico/decision/state.py` (`validate_state`, `InvalidState`, `DataClass`).
  - **Hecho cuando:** las pruebas pasan.

- [x] **T04 — Conjunto permitido y piso por clase**
  - **Delegable a Gemini:** NO — es el núcleo de seguridad de la capa.
  - Requisitos: VJT-001, VJT-002, VJT-003, VJT-004, VJT-005, VJT-007, VJT-008, VJT-010a, VJT-022, VJT-023, VJT-024, VJT-037.
  - **Tests primero:** `tests/test_decision_floor.py` con **pruebas de propiedades** sobre todas las combinaciones de clase, base, respuesta y permitidas: nunca fuera de lo permitido; clase A siempre la base; clase B nunca menos exigente que la base según el orden del tipo (y `ruta_consulta_financiera` nunca a «conceptual»);  formato inválido, opción desconocida y fuera de permitidas con motivos distintos; un contexto sin la marca de «sin texto libre» se trata como `con_datos_personales`; entre la clase de la política y la del llamador gana la más restrictiva; con una sola opción no se consulta; `con_datos_personales` nunca admite DeepSeek.
  - **Entregable exacto:** `src/jerico/decision/floor.py` (`allowed_options`, `apply_floor`).
  - **Hecho cuando:** las propiedades pasan y el revisor confirma la tabla de exigencia por tipo.

- [x] **T05 — Claves, identificador de evento, caché y un solo vuelo**
  - **Delegable a Gemini:** SÍ — pieza pura con reloj inyectado.
  - Requisitos: VJT-034, VJT-036, VJT-041.
  - **Tests primero:** `tests/test_decision_cache.py`: identificadores de evento sin colisión entre dos procesos simulados ni tras un reinicio con el mismo instante; misma clave de decisión → fuente `cache`; vigencia; otra versión de política no reutiliza; dos casos con el mismo estado comparten clave pero tienen identificadores de evento distintos; 20 decisiones simultáneas con la misma clave hacen una sola consulta.
  - **Entregable exacto:** `src/jerico/decision/cache.py` (`DecisionCache`, `decision_key`, `SingleFlight`, `new_event_id`).
  - **Hecho cuando:** las pruebas pasan sin esperas reales.

- [x] **T06 — Cortacircuitos**
  - **Delegable a Gemini:** SÍ — pieza pura con reloj inyectado.
  - Requisitos: VJT-032.
  - **Tests primero:** `tests/test_decision_breaker.py`: se abre tras N fallos seguidos, se mantiene abierto durante la pausa, se cierra después, un éxito reinicia la cuenta.
  - **Entregable exacto:** `src/jerico/decision/breaker.py`.
  - **Hecho cuando:** las pruebas pasan.

- [x] **T07 — Registro de decisiones**
  - **Delegable a Gemini:** NO — define qué queda guardado de cada decisión (privacidad).
  - Requisitos: VJT-040, VJT-041, VJT-043, VJT-045, VJT-046.
  - **Tests primero:** `tests/test_decision_recorder.py`: campos obligatorios en todos los modos y campos solo con consulta (VJT-040); el registro es solo de anexión y lleva el identificador de evento; repetir un evento con el mismo identificador no duplica el registro; ningún texto del estado fuera de la lista cerrada; costo «no calculado» sin tarifas; retención por fecha; no lanza ante falla de disco. Depende de `shadowlog` (T01 del módulo CRM-consejero).
  - **Entregable exacto:** `src/jerico/decision/recorder.py`.
  - **Hecho cuando:** las pruebas pasan.

- [x] **T08 — Puerto `decidir` y configuración**
  - **Delegable a Gemini:** NO — orquesta modos, respaldo y fallos: nunca debe lanzar.
  - Requisitos: VJT-010, VJT-011, VJT-012, VJT-013, VJT-014, VJT-015, VJT-026, VJT-030, VJT-033, VJT-037, VJT-044, VJT-052, VJT-054.
  - **Tests primero:** `tests/test_decision_port.py`: `apagado` y `sombra` aplican la base; `sugerencia` aplica la base y expone la opción de Jev; `enrutado` aplica el piso; interruptor general; **empate → base**; la sugerencia de Jev queda en `suggested` y no se pierde por la caché; cambiar de modo no reutiliza resultados viejos; apagado general por archivo marcador sin reiniciar (la variable exige reiniciar); degradación a `sombra` desde `sugerencia` y `enrutado` tras fallos, que persiste tras un reinicio; con `cohorte_suficiente` falsa no consulta en línea; `sugerencia` expone la opción solo con rol CTO verificado; la consulta simulada de 2 s no retrasa a otro mensaje más de 100 ms; nunca lanza ante fallos del registro, la caché o el cliente (inyectados); sin llave → base y aviso único; alerta por volumen anómalo solo con 14 días de historia y mediana ≥ 10, sin cortar el servicio.
  - **Entregable exacto:** `src/jerico/decision/port.py`, `decision/config.py` y variables en `.env.example`.
  - **Hecho cuando:** las pruebas pasan y, con modos `apagado` y `sombra`, no hay ninguna llamada de red.

- [x] **T09 — Pruebas de aislamiento del Nivel 1**
  - **Delegable a Gemini:** SÍ — prueba estática sin tocar código de producción.
  - Requisitos: VJT-050, VJT-054, VJT-091.
  - **Tests primero:** `tests/test_decision_isolation.py`: ningún módulo del paquete (salvo el cliente del Nivel 2, que aún no existe) importa red; `pyproject.toml` no cambia; la dirección del servicio de TypeSafe no aparece fuera de `jev_client`.
  - **Hecho cuando:** las pruebas pasan.

## B. CRM (F1)

- [x] **T10 — Enganche en el CRM**
  - **Delegable a Gemini:** NO — toca el asistente en producción.
  - Requisitos: VJT-008, VJT-063.
  - **BLOQUEADA hasta:** T08 hecha y base de código acordada (T17).
  - **Tests primero:** `tests/test_decision_crm_hook.py`: `/asistente` llama a `decidir("modelo_asistente", …)` y obtiene siempre `gpt-6-luna` sin consultar a Jev (un solo permitido); con la captura apagada el asistente se comporta exactamente igual que sin la capa; el tipo `seguimiento_lead` queda registrado como asesor, apagado por defecto y activable en `sombra` por configuración cuando el módulo CRM-consejero está activo.
  - **Entregable exacto:** llamada a `decidir` en el asistente y registro del tipo `seguimiento_lead`; sin cambiar mensajes, topes ni presupuesto del asistente.
  - **Hecho cuando:** las pruebas del asistente existentes y nuevas pasan.

- [x] **T11 — Módulo CRM-consejero**
  - **Delegable a Gemini:** según cada tarea (ver `crm-consejero/tasks.md`).
  - Requisitos: `VJC-001` a `VJC-040`.
  - **BLOQUEADA hasta:** Q2 y Q5 del módulo resueltas por el CTO (bloquean su Gate 1) y T08 hecha.
  - **Entregable exacto:** las tareas T01 a T09 de `crm-consejero/tasks.md` (su T10 y su T11 son las coordinaciones T17 y T16 de esta lista).
  - **Hecho cuando:** el módulo cumple su «Hecho cuando» y su revisión.

## C. Cliente en línea (F2)

- [x] **T12 — Cliente de Jev (Nivel 2)**
  - **Delegable a Gemini:** NO — red, secretos y tercero.
  - Requisitos: VJT-031, VJT-032, VJT-035, VJT-050, VJT-051, VJT-053.
  - **BLOQUEADA hasta:** orden del CTO para el Nivel 2; Q8 resuelta por escrito (enmienda o versión fija; constitución, principio 5); Q1 (cliente único) y Q5 (legal) resueltas.
  - **Tests primero:** `tests/test_decision_jev_client.py` con transporte falso: interpreta `choice` y `score`, reintenta 429 y 529, respeta el tiempo máximo, devuelve la versión del modelo, la llave nunca aparece en errores ni registros, una sola consulta por decisión; la consulta no retrasa a otros mensajes más de 100 ms.
  - **Entregable exacto:** `src/jerico/decision/jev_client.py`, solo biblioteca estándar.
  - **Hecho cuando:** las pruebas pasan sin red.

- [x] **T13 — Modo sugerencia solo para el CTO**
  - **Delegable a Gemini:** NO.
  - Requisitos: VJT-012, VJT-013, VJT-015.
  - **BLOQUEADA hasta:** T12 hecha y orden del CTO para ese tipo.
  - **Tests primero:** la opción de Jev se muestra únicamente a un usuario con rol CTO verificado por el mecanismo de identidad del CRM y en el registro, nunca a otros usuarios ni a clientes, y la aplicada sigue siendo la base.
  - **Hecho cuando:** las pruebas pasan.

## D. Evaluación y enrutado (F3)

- [ ] **T14 — Informe de promoción por tipo**
  - **Delegable a Gemini:** NO — lo produce `kai-jev` con la herramienta de la flota; el director revisa.
  - Requisitos: criterios de promoción de la sección 7 de la spec (el informe lo escribe la herramienta de la flota).
  - **BLOQUEADA hasta:** 200 decisiones registradas del tipo.
  - **Entregable exacto:** informe con acuerdo con la base, calibración, latencia, costo de Jev, tasa de sobrescritura humana y, si hay tarifas verificadas, ahorro neto.
  - **Hecho cuando:** el CTO decide la promoción del tipo.

- [ ] **T15 — Enrutado de una tarea de clase C**
  - **Delegable a Gemini:** NO.
  - Requisitos: VJT-005, VJT-013, VJT-015, VJT-022, VJT-023.
  - **BLOQUEADA hasta:** spec 005 con LLM de más de un proveedor y una tarea ligera real; tarifas verificadas (Q2); definición de «seudonimizado verificado» (Q3); T14 aprobada; orden del CTO.
  - **Hecho cuando:** el tipo opera en `enrutado` con degradación automática probada.

## E. Coordinación y cierre

- [ ] **T16 — Alineación con `kai-jev` (spec 005 y `Flota_Jev`)**
  - **Delegable a Gemini:** NO — coordinación entre directores.
  - Requisitos: (proceso; VJT-026, VJT-046, VJT-050).
  - **Entregable exacto:** mensaje a `kai-jev` (enviado el 13/10/2026 en borrador) y acuerdo final sobre: `decidir(kind, tarea, state)` como función de su §3.1 y la tabla de correspondencia de la sección 9; esquema del registro; archivo de respuestas unido por identificador de evento; rangos y mínimo de leads al leer; cliente único (Q1).
  - **Hecho cuando:** `kai-jev` confirma qué ajusta en la 005 y en la flota, y consta en la bitácora del Plan maestro.

- [ ] **T17 — Alineación con `crm-director`**
  - **Delegable a Gemini:** NO.
  - Requisitos: (proceso).
  - **Entregable exacto:** acuerdo de la rama base del CRM y confirmación de que contratos, firma, bajas y autorizaciones de la spec 004 son clase A (no consultan a Jev).
  - **Hecho cuando:** consta en la bitácora.

- [ ] **T18 — Documentación de despliegue**
  - **Delegable a Gemini:** SÍ — documentación.
  - Requisitos: VJT-014, VJT-042, VJT-052.
  - **Entregable exacto:** apartado en la documentación de despliegue con las variables `JERICO_DECISION_*`, el archivo marcador de apagado, la regla de claves de idempotencia y `DRY_RUN` para cualquier acción disparada por una decisión, cómo activar un tipo en `sombra`, el interruptor general y la reversa; con marca de tiempo.
  - **Hecho cuando:** coincide con `decision/config.py`.

- [ ] **T19 — Verificación final y revisión**
  - **Delegable a Gemini:** NO — la hace el revisor (`reviewer`) con veredicto binario.
  - Requisitos: todos los de las fases que se hayan implementado.
  - **Hecho cuando:** `verify.sh` en verde con cobertura ≥ 89 %, `pre-commit run --all-files` en verde y veredicto `APROBADO`.

- [ ] **T20 — Proceso previo con el abogado (proveedores nuevos)**
  - **Delegable a Gemini:** NO — decisión legal.
  - Requisitos: VJT-055 y Q5.
  - **Entregable exacto:** confirmación escrita del abogado sobre (a) si el estado categórico con rangos que recibe Jev es dato personal, (b) si TypeSafe o DeepSeek deben figurar como encargados y en el aviso, antes de activar cualquier consulta a Jev con estados de leads.
  - **Hecho cuando:** consta la respuesta del abogado y el CTO la acepta.

---

## Orden y dependencias

`T16`, `T17` y `T20` pueden hacerse en cuanto se apruebe la spec. F0: `T01` → `T02`; `T03`, `T05` y `T06` independientes; `T04` (usa `T02` y `T03`); `T07` (usa `shadowlog`); `T08` (usa `T03`, `T04`, `T05`, `T06`, `T07`); `T09`. F1: `T10` (usa `T08` y `T17`); `T11`. F2: `T12` → `T13`. F3: `T14` → `T15`. Cierre: `T18` y `T19`.

## Cobertura de requisitos

| Requisito | Tareas |
|---|---|
| VJT-001, 002 | T04 |
| VJT-003, 004, 005 | T02, T04 |
| VJT-006 | T01, T02 |
| VJT-007, 008 | T02, T04 |
| VJT-009, 010a | T02, T04 |
| VJT-010 | T01, T08 |
| VJT-011 a 015 | T08 (VJT-012 y 013 también T13; VJT-013 y 015 también T15) |
| VJT-020, 021, 025 | T03 |
| VJT-022, 023 | T04 y T15 |
| VJT-024 | T02, T04 |
| VJT-030 | T08 |
| VJT-031, 033 | T12 |
| VJT-032 | T06 |
| VJT-026 | T08 y T16 |
| VJT-034, 036, 041 | T05 |
| VJT-035 | T12 |
| VJT-037 | T08 |
| VJT-040, 043, 045, 046 | T07 |
| VJT-042 | cada spec que dispare acciones (su propia tarea) |
| VJT-044, 052, 054 | T08 |
| VJT-050 | T09, T12, T16 |
| VJT-055 | T20 |
| VJT-051, 053 | T12 |
| VJT-060 a 063 | T02, T10 |
| VJT-090 | T19 (y `verify.sh` en cada tarea) |
| VJT-091 | T09 |

> 🕒 **Última modificación:** 13/10/2026 22:41 (Agente Claude Code · Sonnet 5.5)
