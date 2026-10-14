---
modificado: "13/10/2026 22:15"
---

# Tareas 006 — Consejero de seguimiento con Jev en el CRM

- **Estado:** **BORRADOR — no se ejecuta ninguna tarea hasta que el CTO apruebe la spec y el plan.** Una tarea por sesión; TDD estricto (rojo → verde); detención obligatoria al terminar cada una.
- **Base:** `spec.md` (requisitos `VJC-001` a `VJC-040`) y `plan.md`.
- **Base de código:** las tareas se ejecutan sobre una rama que contenga el despliegue real del CRM (`d0aeab3` o su integración en `main`), acordada con `crm-director` antes de empezar (ver plan, «Base de código»). La rama `jev/p1-router-spec` solo guarda documentos.
- **Quién ejecuta:** las tareas «Delegable a Gemini: SÍ» las implementa el panel `jer-jev-gem` con un contrato y el director verifica; las «NO» las trabaja el director.
- **Fuera de este repo:** el cliente de Jev, el consenso, las métricas y el informe son de `Flota_Jev` (`kai-jev`); aquí solo hay una tarea de entrega del contrato (T11).

## Bloques comunes

**PROH (aplican a todas):** no tocar `src/jerico/crm/{compliance,retention,leads,replies,followup,assistant*,pseudonym,llm}.py`, `src/jerico/{gateway,tools,state,cron}/`, `tests/conftest.py`, `docker-compose*.yml`, `Dockerfile`, `.env` (solo `.env.example`), `DECISIONES_CTO.md`, `docs/constitution.md`, `scripts/oci/`. No hacer `git push`. No añadir dependencias a `pyproject.toml`. No importar la herramienta de la flota. No leer ni escribir secretos. No llamar a ninguna red. No tocar el servidor.

**VERIF (desde la raíz del repo):**
```
VIRTUAL_ENV=/home/janty-mr/Kaisen_AI/01_Proyectos/Proyecto_Jerico/.venv ./scripts/verify.sh; echo "código=$?"
```
Se guarda el código de salida real (sin tuberías que lo oculten). Debe pasar ruff, mypy y pytest con cobertura total ≥ 89 %. Además `pre-commit run --all-files` en verde antes de cada commit.

**Commit:** local, identidad `Santiago Gonzalez <kaisen.ai.santiago.cto@gmail.com>`, mensaje en español con el identificador de la tarea, solo con autorización del CTO (constitución, principio 10).

---

## A. Base reutilizable

- [ ] **T01 — Escritor de archivos diarios (`shadowlog`)**
  - **Delegable a Gemini:** SÍ — pieza aislada con pruebas explícitas (el director revisa la atomicidad del reemplazo y la concurrencia).
  - Requisitos: VJC-020, VJC-021, VJC-022, VJC-023.
  - **Tests primero:** `tests/test_shadowlog_jsonl.py`: línea JSON por registro; archivo `AAAA-MM-DD.jsonl` según el reloj inyectado; `read_day` devuelve los registros y descarta líneas incompletas o ilegibles; `purge` borra solo archivos más viejos que la retención; `rewrite_without` quita registros por predicado, devuelve lo quitado y es atómico (un fallo a mitad no deja un archivo parcial; si no puede reescribir, elimina el archivo y lo informa); 20 hilos × 50 líneas sin líneas corruptas ni intercaladas; línea > 4 KB rechazada con error; falla de disco lanza `OSError`.
  - **Entregable exacto:** `src/jerico/shadowlog/__init__.py` y `jsonl.py` (`DailyJsonlWriter`).
  - **Hecho cuando:** las pruebas pasan sin red y sin esperas reales (reloj falso).

## B. Vector del lead

- [ ] **T02 — Elegibilidad y vector con validación**
  - **Delegable a Gemini:** NO — define qué datos de un titular se derivan y se guardan: privacidad (Ley 1581).
  - Requisitos: VJC-007, VJC-011, VJC-012, VJC-013, VJC-014, VJC-015, VJC-016.
  - **Tests primero:** `tests/test_crm_advisor_state.py`: elegibilidad (suprimido, `opted_out` y autorización revocada fuera; estados finales dentro); cada campo con casos de borde (sin eventos, valores nulos, cadencia vencida, fechas futuras); topes; la referencia (HMAC) es estable, de 16 caracteres, cambia con otra clave y no contiene el número del lead; `client_type` y `reject_reason` desconocidos se mapean a `ninguno` y `otro`; alertas sin lead no cuentan y solicitudes vencidas sí; `validate_vector` rechaza clave extra o faltante, tipo erróneo (un `bool` no vale como entero), entero fuera de tope y cadena fuera del enumerado; **prueba de privacidad**: con leads cuyos textos son marcadores únicos (nombre, empresa, correo, teléfono, documento, valor pactado, notas), ningún marcador aparece en el vector serializado.
  - **Entregable exacto:** `src/jerico/crm/advisor_state.py` (`SCHEMA_VERSION`, `CAPS`, `lead_ref`, `is_eligible`, `build_vector`, `validate_vector`, `InvalidVector`), con un contexto de entrada simple (sin acceso a base) para mantenerlo puro.
  - **Hecho cuando:** las pruebas pasan y el vector contiene exactamente los campos de VJC-011.

- [ ] **T03 — Consultas de solo lectura en bloque**
  - **Delegable a Gemini:** SÍ — consultas acotadas con una prueba de equivalencia (el director revisa que todas sean `SELECT`).
  - Requisitos: VJC-005, VJC-008, VJC-012.
  - **Tests primero:** `tests/test_crm_advisor_queries.py`: en una base con casos variados (leads con y sin eventos, con y sin cadencia, propuestas, alertas y solicitudes), el contexto en bloque coincide con lo que dan `lead_events`, `lead_notes`, `get_cadence`, `pending_proposals`, `open_alerts` y `open_titular_requests` lead por lead; con 1 000 leads se ejecutan como máximo 12 sentencias (conteo con la traza de SQLite), todas de lectura y dentro de una sola transacción.
  - **Entregable exacto:** `src/jerico/crm/advisor_queries.py` (`load_context`).
  - **Hecho cuando:** las pruebas pasan y el análisis estático confirma que no hay `INSERT`, `UPDATE`, `DELETE` ni `PRAGMA` de escritura.

## C. Captura

- [ ] **T04 — Corrida de la instantánea**
  - **Delegable a Gemini:** NO — integra elegibilidad, idempotencia y supresión (privacidad y borrado).
  - Requisitos: VJC-003, VJC-004, VJC-005, VJC-006, VJC-007, VJC-010, VJC-021, VJC-022, VJC-023, VJC-024.
  - **Tests primero:** `tests/test_crm_advisor_snapshot.py`: una línea por lead elegible; dos corridas el mismo día no duplican (también tras un reinicio y con una línea parcial); el cambio de día se decide en hora de Bogotá (23:30 y 00:30 locales); **la base queda idéntica** (volcado antes y después); un lead inválido se omite y se cuenta; tras marcar `suppressed_at`, pasar a `opted_out` o quitar la fila, la corrida borra sus líneas de todos los archivos **antes** de escribir y anota el retiro en el archivo de retiros; un archivo que no se puede reescribir se elimina y ese día no se escribe; cero leads elegibles no escribe pero aplica retención y retiros; un fallo de lectura no escribe nada.
  - **Entregable exacto:** `src/jerico/crm/advisor_snapshot.py` (`run_snapshot`, `SnapshotReport`) y el archivo de retiros.
  - **Hecho cuando:** las pruebas pasan y la huella de la base no cambia.

## D. Cableado y configuración

- [ ] **T05 — Configuración**
  - **Delegable a Gemini:** SÍ — cambio mecánico en `config.py` y `.env.example`.
  - Requisitos: VJC-002, VJC-014, VJC-021.
  - **Tests primero:** `tests/test_crm_advisor_config.py`: valores por defecto (apagado, clave vacía, retención 90, directorio vacío = `data_dir/jev_snapshot`); sin clave la funcionalidad no se activa; variable vacía = no definida; `.env.example` contiene las variables nuevas.
  - **Entregable exacto:** campos `jev_snapshot_enabled`, `jev_snapshot_key`, `jev_snapshot_dir`, `jev_snapshot_retention_days` en `CrmSettings` y sus líneas en `.env.example` (sin valores reales).
  - **Hecho cuando:** las pruebas pasan y el CRM arranca igual con la variable apagada.

- [ ] **T06 — Registro del trabajo y manejo de fallos**
  - **Delegable a Gemini:** NO — toca el arranque y el programador de trabajos del CRM en producción.
  - Requisitos: VJC-002, VJC-006, VJC-009, VJC-014.
  - **Tests primero:** `tests/test_crm_advisor_wiring.py`: con la variable apagada o sin clave no se registra el trabajo (y sin clave se avisa una vez); con ella activa se registra con el cron `30 13 * * *`, 30 minutos después de `crm-daily`; no se ejecuta al arrancar; una excepción dentro del trabajo no se propaga, cuenta el fallo, el aviso no incluye datos de leads y no impide los demás trabajos.
  - **Entregable exacto:** `SNAPSHOT_JOB` y `SNAPSHOT_CRON` en `jobs.py`; parámetro `snapshot` opcional en `register_jobs`; construcción del escritor y envoltorio con `asyncio.to_thread` en `app.py`.
  - **Hecho cuando:** las pruebas del CRM existentes y nuevas pasan, y con la variable apagada el comportamiento es idéntico al anterior.

## E. Cierre

- [ ] **T07 — Pruebas de aislamiento**
  - **Delegable a Gemini:** SÍ — prueba estática sin tocar código de producción.
  - Requisitos: VJC-001, VJC-030, VJC-031, VJC-032.
  - **Tests primero:** `tests/test_crm_advisor_isolation.py`: ningún módulo nuevo importa `flota_jev`, `requests`, `httpx`, `socket` ni `urllib`; ni `pyproject.toml` ni `src/` contienen `flota_jev`, `TYPESAFE`, `api.typesafe.ai` ni `jev-latest`; `pyproject.toml` no cambia respecto de la base.
  - **Hecho cuando:** las pruebas pasan.

- [ ] **T08 — Documentación de despliegue**
  - **Delegable a Gemini:** SÍ — documentación.
  - Requisitos: VJC-002, VJC-014, VJC-021, VJC-022.
  - **Entregable exacto:** apartado en la documentación de despliegue del CRM con las variables nuevas, dónde y quién coloca la clave, el volumen, la retención, el archivo de retiros, cómo activar y apagar, y la nota sobre respaldos. Con marca de tiempo.
  - **Hecho cuando:** el apartado existe y coincide con `config.py`.

- [ ] **T09 — Verificación final y revisión**
  - **Delegable a Gemini:** NO — la hace el revisor (`reviewer`) con veredicto binario.
  - Requisitos: todos (VJC-001 a VJC-040).
  - **Entregable exacto:** informe del revisor con recorrido requisito por requisito contra las pruebas.
  - **Hecho cuando:** `verify.sh` en verde con cobertura ≥ 89 %, `pre-commit run --all-files` en verde y veredicto `APROBADO`.

- [ ] **T10 — Coordinación de base de código**
  - **Delegable a Gemini:** NO — coordinación entre directores.
  - Requisitos: (proceso).
  - **Entregable exacto:** acuerdo escrito con `crm-director` sobre la rama base y el orden de integración, antes de T01.
  - **Hecho cuando:** consta en la bitácora del Plan maestro.

- [ ] **T11 — Entrega del contrato a `kai-jev`**
  - **Delegable a Gemini:** NO — coordinación entre directores.
  - Requisitos: (contrato de la sección 7 de la spec; no verificable con pruebas del CRM).
  - **Entregable exacto:** mensaje a `kai-jev` con la sección 7 de la spec (vector, preguntas, aplicar retiros y retención, no enviar referencia ni día) y el punto Q1 (traslado de archivos), sin duplicar ni modificar `Flota_Jev`.
  - **Hecho cuando:** `kai-jev` confirma qué parametriza (esquema, preguntas, lector, etiquetas).

---

## Orden y dependencias

`T10` y `T11` pueden hacerse en cuanto se apruebe la spec. Luego: `T01` y `T05` independientes → `T02` → `T03` → `T04` (usa `T01`, `T02`, `T03`) → `T06` (usa `T04`, `T05`) → `T07` → `T08` → `T09`.

## Cobertura de requisitos

| Requisito | Tareas |
|---|---|
| VJC-001, 030, 031, 032 | T07 |
| VJC-002 | T05, T06 |
| VJC-003, 004 | T04 |
| VJC-005 | T03, T04 |
| VJC-006 | T04, T06 |
| VJC-007 | T02, T04 |
| VJC-008 | T03 |
| VJC-009 | T06 |
| VJC-010 | T04 |
| VJC-011, 012, 013, 015, 016 | T02 (VJC-012 también T03) |
| VJC-014 | T02, T05, T06 |
| VJC-020 a 023 | T01 |
| VJC-021 a 024 | T04 |
| VJC-040 | T09 (y `verify.sh` en cada tarea) |

> 🕒 **Última modificación:** 13/10/2026 22:15 (Agente Claude Code · Sonnet 5.5)
