# Tareas 001 — CRM de ventas, fase F1

- **Estado:** borrador para el gate de tareas (fase 5 SDD); aprobado por delegación del CTO si el reviewer no encuentra bloqueantes.
- **Base:** `plan.md` (mismo directorio) y los 101 requisitos [F1] de `spec.md`.
- **Cambio del 05/10/2026 (decisiones K-1 a K-8, spec §8):** nuevas T17b y T02b (sin marcar); ajustadas T19, T20a, T20b, T22, T24 y T25; T01–T18 hechas no se desmarcan (K-1 solo cambia la redacción de VCRM-048/156: T07/T16/T17 ya cumplen con los 9 campos de 4.3).
- **Reglas comunes a todas las tareas:**
  - TDD estricto: escribir primero los tests indicados (deben fallar por la razón correcta), luego el código mínimo.
  - Cada test lleva en su nombre el requisito que cubre (`test_vcrmNNN_...`).
  - Sin red: Telegram, SMTP, `age`/`rclone` y reloj simulados con los dobles de `tests/crm_support.py`.
  - No tocar `gateway/`, `tools/`, `state/`, `config.py`, `main.py`, `tests/conftest.py`, `docker-compose.yml`, `Dockerfile` ni `.env*`. Sin commits ni *push*.
  - **Comprobación estándar** (forma parte de cada «Hecho cuando»), desde la raíz del repo:
    `PYTHONPATH=src .venv/bin/python -m pytest <tests de la tarea> -q` en verde, y
    `.venv/bin/ruff check src/jerico/crm tests/crm_support.py tests/test_crm_*.py` y `.venv/bin/mypy src/jerico/crm tests/crm_support.py tests/test_crm_*.py` sin errores.
  - Una tarea a la vez; al terminar, detenerse y reportar.

---

## Fundamentos

- [x] **T01 — Paquete, entrypoint y configuración con topes legales**
  - Requisitos: VCRM-162 (cálculo del valor vigente y lista de avisos).
  - Archivos: `src/jerico/crm/__init__.py`, `src/jerico/crm/config.py`, `pyproject.toml` (solo aditivo: extra `crm = ["httpx>=0.27,<1"]` y script `jerico-crm = "jerico.crm.app:main"`), `tests/crm_support.py` (esqueleto), `tests/test_crm_config.py`.
  - Tests primero: valores por defecto de §4.6; valor > tope (consultas 12 → 10, reclamos 20 → 15, escalado 3 → 2, supresión 18 → 12 meses, J-14 45 → 30, respaldos 60 → 30); adjuntos de ganado 5 → 10 años (mínimo); valor ≤ 0 → por defecto; aviso J-14 ≥ máximo → corregido; valor más estricto aceptado; cada corrección genera `ConfigWarning(param, rechazado, vigente)`; SMTP sin valor por defecto; `pyproject.toml` declara el script y el extra (lectura con `tomllib`); hermeticidad: todos los tests usan `CrmSettings(_env_file=None, ...)` y una *fixture* con `monkeypatch.delenv` para cada `JERICO_CRM_*` del entorno (un `.env` local con valores distintos no cambia el resultado).
  - Hecho cuando: `tests/test_crm_config.py` en verde + comprobación estándar; `git diff pyproject.toml` muestra solo líneas añadidas.

- [x] **T02 — Tiempo, festivos de Colombia y días hábiles**
  - Requisitos: VCRM-077; base de VCRM-150–152.
  - Archivos: `src/jerico/crm/timeutil.py`, `tests/test_crm_timeutil.py`.
  - Tests primero: Pascua 2024–2027; los 18 festivos de 2026 (plan §5.1) y traslados Emiliani de un año más; `is_business_day` (sábado, domingo, festivo); `add_business_days` cuenta desde el día hábil siguiente (recepción en viernes antes de un lunes festivo); `business_days_between`; `add_months` con fin de mes; `to_iso` rechaza fechas *naive* y guarda UTC; `format_local` presenta en Bogotá (UTC−5); respaldo de zona fija cuando `ZoneInfo` falla.
  - Hecho cuando: `tests/test_crm_timeutil.py` en verde + comprobación estándar.

- [x] **T03 — Base de datos propia, esquema y bitácora sin datos personales**
  - Requisitos: VCRM-078 (persistencia), VCRM-075 (API de bitácora), VCRM-096.
  - Archivos: `src/jerico/crm/model.py`, `src/jerico/crm/db.py`, `src/jerico/crm/repo.py` (consultas de usuarios, leads, eventos, metadatos, auditoría y alertas de `crm_alerts`: `create_alert`, `open_alerts`, `resolve_alert`), `tests/test_crm_db.py`.
  - Tests primero: WAL activo y `schema_version = 1` en `crm_meta`; `tx()` hace *rollback* ante excepción; datos confirmados sobreviven a cerrar y reabrir la base; `repo.audit` solo acepta códigos de enumeración (un texto libre es error de tipo/valor) y la fila no tiene columnas de datos del titular; el DDL no usa `INSERT OR IGNORE`, `AUTOINCREMENT` ni `PRAGMA user_version` (inspección del texto del esquema); `create_alert` → aparece en `open_alerts` (por lead y para el CTO) y `resolve_alert` registra autor y fecha y la retira; resolver dos veces no duplica.
  - Hecho cuando: `tests/test_crm_db.py` en verde + comprobación estándar.

- [x] **T04 — Máquina de estados F1**
  - Requisitos: VCRM-013, 014, 117, 133.
  - Archivos: `src/jerico/crm/states.py`, `tests/test_crm_states.py`.
  - Tests primero: todas las transiciones F1 de §4.2 permitidas; las de F2 rechazadas en fase 1; transición no permitida devuelve los destinos válidos; `ganado`/`perdido` → solo `baja`; `baja` sin destinos; `aceptado → perdido` devuelve `requires_retraction`.
  - Hecho cuando: `tests/test_crm_states.py` en verde + comprobación estándar.

- [x] **T05 — Matriz de permisos y visibilidad**
  - Requisitos: VCRM-085, 086 (decisión), 109 (decisión), 134 (decisión), 136 (decisión).
  - Archivos: `src/jerico/crm/permissions.py`, `tests/test_crm_permissions.py`.
  - Tests primero: tabla parametrizada con cada fila F1 de §4.4 × 3 roles × lead propio/ajeno; comercial sobre lead ajeno → `foreign_lead`; abogado sobre lead nunca aceptado → `foreign_lead` y sobre uno que lo estuvo → visible; comercial + marcar ganado → `role`; `commercial_recipients` devuelve el CTO si el lead es suyo o su comercial está inactivo.
  - Hecho cuando: `tests/test_crm_permissions.py` en verde + comprobación estándar.

- [x] **T06 — Parser del formato estructurado, normalización y huella**
  - Requisitos: VCRM-004, 005, 081 (análisis), 082 (validación), 095 (huella).
  - Archivos: `src/jerico/crm/parsing.py`, `src/jerico/crm/fingerprint.py`, `tests/test_crm_parsing.py`.
  - Tests primero: ejemplos de §4.3 (completo, solo correo, nota con `;`); falta nombre o todo contacto → error con dato faltante y ejemplo; teléfono de 10 dígitos → `+57…`; `+`/`00` internacional; teléfono inválido y correo sin `@`/dominio → campo inválido; `/editar` con campo no editable → lista de editables; `parse_short_id`; datos de *callback* ≤ 64 bytes; HMAC estable, distinto con otra clave, comprobación con clave previa, y la huella no contiene el contacto.
  - Hecho cuando: `tests/test_crm_parsing.py` en verde + comprobación estándar.

- [x] **T07 — Handoff y textos (ficha, listas, notificaciones)**
  - Requisitos: VCRM-111, 112 (validación), 048 (contenido), 104, 156, 090 (paginación pura).
  - Archivos: `src/jerico/crm/handoff.py`, `src/jerico/crm/render.py`, `tests/test_crm_render.py`.
  - Tests primero: faltantes con persona natural, empresa y tipo sin registrar (anotación «obligatorio si es empresa»); valores vacíos, tipo y documento no admitidos → error con valores admitidos; documento «NIT 900123456-7» → tipo y número; contenido de la notificación al CTO (notas, autorización, handoff y faltantes) y del correo al abogado (7 campos, faltantes, solicitud explícita, sin notas); alerta de Telegram al abogado (VCRM-104); propiedad VCRM-156: con texto centinela en notas, adjuntos e historial, ningún texto `*_lawyer` lo contiene; página de 10 con «página X de Y»; `split_message` ≤ 4096.
  - Hecho cuando: `tests/test_crm_render.py` en verde + comprobación estándar.

- [x] **T08 — Adaptadores: Telegram (httpx) y correo (SMTP)**
  - Requisitos: VCRM-105, 140, 008 (límite de descarga), 012 (semántica de «entregado»).
  - Archivos: `src/jerico/crm/ports.py`, `src/jerico/crm/telegram.py`, `src/jerico/crm/mail.py`, `src/jerico/crm/files.py`, `tests/test_crm_adapters.py`, dobles en `tests/crm_support.py` (`FakeTelegram`, `FakeEmailSender`, `FakeClock`).
  - Tests primero (con `httpx.MockTransport` y `smtplib` falso): `getUpdates` normaliza mensaje, archivo y `callback_query`; `sendMessage` con teclado *inline* → entregado con `message_id`; `ok=false`/timeout → no entregado; descarga > 20 MB se corta sin dejar archivo; el token no aparece en errores; SMTP STARTTLS y SSL entregan con `Message-ID`; destinatario rechazado → no entregado; sin buzón o credenciales → `UnconfiguredEmailSender` con fallo permanente y sin conexión; `LocalFileStore` atómico y borrado idempotente.
  - Hecho cuando: `tests/test_crm_adapters.py` en verde + comprobación estándar.

## Equipo y bot

- [x] **T09 — Usuarios autorizados: siembra, alta, baja y reasignación**
  - Requisitos: VCRM-125, 126, 144, 091, 092, 093.
  - Archivos: `src/jerico/crm/team.py`, `repo.py` (consultas de usuarios), `tests/test_crm_team.py`.
  - Tests primero: siembra del CTO solo si no hay CTO activo y persiste tras reabrir; siembra inválida (sin correo, correo mal formado, id repetido) → no siembra y log con el nombre del dato, sin valores; alta por el CTO de comercial/abogado con acceso inmediato, confirmación y auditoría; alta inválida → dato faltante, inválido o repetido; alta por un no-CTO → denegada; baja de comercial → inactivo, auditoría y lista de sus leads (estado ≠ baja) con botones de reasignación; baja del abogado; el CTO no se da de baja; lead de comercial inactivo → «sin comercial asignado»; reasignación con evento (anterior, nuevo, autor, fecha).
  - Hecho cuando: `tests/test_crm_team.py` en verde + comprobación estándar.

- [x] **T10 — Núcleo del bot: identidad, deduplicación y denegaciones**
  - Requisitos: VCRM-001, 002, 079, 086 (respuesta y auditoría), 012 (respuestas no reintentadas).
  - Archivos: `src/jerico/crm/bot.py` (bucle, `process_update`, enrutado, entradas pendientes, confirmaciones), `repo.py` (eventos procesados, entradas pendientes, confirmaciones), `tests/test_crm_bot.py`.
  - Tests primero: identidad fuera de la lista → sin efecto, sin respuesta con datos y auditoría (identidad, fecha, tipo); usuario dado de baja deja de ser atendido; mismo `update_id` dos veces → un solo efecto; *offset* persistido; chat no privado ignorado; acción no permitida al rol → «no tiene permiso» + auditoría; respuesta interactiva fallida → fila `fallida` no crítica sin cuerpo y sin reintento; error de handler → *rollback* del efecto, respuesta genérica sin datos y, en transacción aparte, `update_id` marcado como procesado con auditoría `handler_error` (procesar de nuevo el mismo update no repite el handler).
  - Hecho cuando: `tests/test_crm_bot.py` en verde + comprobación estándar.

## Leads

- [x] **T11 — Registro de leads, duplicados, supresión y pregunta de autorización**
  - Requisitos: VCRM-003, 004 (respuesta), 006, 066, 088, 110, 135, 137.
  - Archivos: `src/jerico/crm/leads.py` (`register`), `bot.py` (orden `/nuevo` y botones), `tests/test_crm_register.py`.
  - Tests primero: `/nuevo` válido → lead «nuevo» asignado al comercial (o al CTO si lo registra él) con respuesta `L-NNNN` y datos; error de formato → dato faltante y ejemplo; duplicado visible → aviso con id, estado y comercial y botones «Abrir lead existente»/«Cancelar»; duplicado no visible → sin datos y aviso al CTO con id, comercial («del CTO»/«sin comercial asignado»), autor y fecha, con botón «Reasignar»; coincidencia solo con «perdido» → crea; huella suprimida → no crea (prevalece sobre las demás reglas); pregunta de autorización con botones; «No» o sin respuesta → «sin autorización».
  - Hecho cuando: `tests/test_crm_register.py` en verde + comprobación estándar.

- [x] **T12 — Notas, adjuntos y edición con historial**
  - Requisitos: VCRM-007, 008, 009, 080, 081, 082, 083, 109, 112.
  - Archivos: `leads.py` (`add_note`, `add_attachment`, `edit`), `bot.py` (`/nota`, `/editar`, archivos con pie `L-n`), `tests/test_crm_lead_data.py`.
  - Tests primero: nota con autor y fecha; foto, documento y voz guardados con tipo, autor y fecha y confirmación; > 20 MB, descarga fallida o lead inexistente → sin adjunto ni archivo parcial y causa (con el límite de 20 MB); edición válida → evento con campo, anterior, nuevo, autor y fecha; lead inexistente o campo no editable → lista de editables; teléfono/correo inválidos; duplicado (id solo si visible) y huella suprimida; valores de handoff inválidos; comercial sobre lead ajeno (ficha, edición, estado, nota, adjunto) → «no tiene acceso» sin datos + auditoría.
  - Hecho cuando: `tests/test_crm_lead_data.py` en verde + comprobación estándar.

- [x] **T13 — Lista paginada y ficha por rol**
  - Requisitos: VCRM-010, 011, 090, 092 (presentación), 136.
  - Archivos: `leads.py` o `bot.py` (`/lista`, `/ver`, navegación), `tests/test_crm_views.py`.
  - Tests primero: comercial ve solo los suyos, CTO todos, abogado solo los que alguna vez estuvieron en «aceptado»; orden por última interacción descendente con id, nombre, estado y fecha; 25 leads → 3 páginas con «Anterior»/«Siguiente»; ficha completa (contacto, estado, comercial, handoff, notas, adjuntos, motivo, autorización, alertas); «sin comercial asignado» en la lista del CTO; abogado sobre lead nunca aceptado → «no tiene acceso» + auditoría.
  - Hecho cuando: `tests/test_crm_views.py` en verde + comprobación estándar.

- [x] **T14 — Transiciones: contacto, rechazo con motivo, ganado y perdido**
  - Requisitos: VCRM-015, 016, 017, 089, 115, 116, 117, 118, 132, 133, 134, 014 (respuesta).
  - Archivos: `leads.py` (`transition`), `bot.py` (botones de la ficha y motivos), `tests/test_crm_transitions.py`.
  - Tests primero: «Registrar contacto» desde nuevo y rechazado; rechazo exige motivo por botones; «otro» sin texto → pide el texto y no transiciona; rechazo sin próxima acción; vuelta de rechazado (incluido retractado) a contactado o aceptado conserva historial, notas, adjuntos y autorización; ganado por CTO y abogado; comercial → «corresponde al CTO o al abogado» + auditoría; perdido por comercial del lead o CTO, abogado denegado; aceptado → perdido → «primero la retractación»; ganado/perdido solo a baja; no permitida → transiciones válidas; historial con origen, destino, autor, fecha y motivo, sin operación de edición ni borrado.
  - Hecho cuando: `tests/test_crm_transitions.py` en verde + comprobación estándar.

## Notificaciones críticas

- [x] **T15 — *Outbox*: persistencia, calendario 0/1/5 min y trabajador**
  - Requisitos: VCRM-049, 127, 047 (primer intento inmediato e independencia), 012 (no críticas sin reintento).
  - Archivos: `src/jerico/crm/outbox.py`, `repo.py` (*outbox*; las alertas ya existen desde T03), `tests/test_crm_outbox.py`.
  - Tests primero: `next_attempt_at` (0, 60, 300 s; `None` tras el tercero); la fila existe antes del primer intento; `kick()` provoca el intento sin esperar el intervalo; fallos sucesivos → intentos a +0, +1, +5 min (reloj simulado) y luego «fallida» sin más; un destinatario que falla no retrasa a los demás; fallo permanente → «fallida» sin reintentos; clave de idempotencia evita duplicar filas; tras reabrir la base, una pendiente con 1 intento hecho recibe solo los 2 restantes según `first_attempt_at`.
  - Hecho cuando: `tests/test_crm_outbox.py` en verde + comprobación estándar.

- [x] **T16 — Aceptación con confirmación y handoff**
  - Requisitos: VCRM-046, 047, 048, 051, 052, 104, 111, 156.
  - Archivos: `leads.py` (`request_accept`, `confirm_accept`), `bot.py`, `tests/test_crm_acceptance.py`.
  - Tests primero: resumen + ✅/❌; ❌ no transiciona; ✅ transiciona, marca `ever_accepted` y encola 3 críticas (CTO/Telegram, abogado/Telegram, abogado/correo) con primer intento en el mismo instante simulado; contenido según VCRM-048/104 y sin datos fuera del handoff para el abogado; faltantes indicados en las tres y petición al comercial del lead (o al CTO si el lead es suyo); doble ✅ o confirmar un lead ya aceptado → «ya estaba aceptado» sin repetir notificaciones.
  - Hecho cuando: `tests/test_crm_acceptance.py` en verde + comprobación estándar.

- [x] **T17 — Retractación confirmada y actualización del handoff**
  - Requisitos: VCRM-084, 113, 114, 131, 156 (retractación y actualización).
  - Archivos: `leads.py` (`request_retract`, `confirm_retract`; aviso en `edit`), `bot.py`, `tests/test_crm_retraction.py`.
  - Tests primero: comercial del lead, CTO y abogado pueden pedirla; motivo por botones; sin motivo u «otro» sin texto → sigue «aceptado» sin notificaciones; confirmación con id, nombre y motivo; ❌ → sigue «aceptado» sin notificaciones; ✅ → «rechazado» como retractación, `accepted_exit_at`, 3 críticas por los mismos canales con id, nombre, motivo, autor y fecha; completar por edición un campo faltante de un «aceptado» → críticas de actualización al CTO (Telegram) y al abogado (Telegram y correo) con el campo y los que siguen faltando; editar un campo no faltante no notifica.
  - Hecho cuando: `tests/test_crm_retraction.py` en verde + comprobación estándar.

- [x] **T18 — Cadena de escalado: respaldo, aviso de fallo y alertas**
  - Requisitos: VCRM-050, 087, 107, 128, 129, 130, 140 (integración).
  - Archivos: `outbox.py` (`escalate`), `bot.py` (botón «Atendida por otro medio»), `tests/test_crm_escalation.py`.
  - Tests primero: ningún correo de respaldo mientras queden intentos; tras el tercer fallo de Telegram (CTO o abogado) o del correo al abogado → respaldo por correo al CTO y al comercial del lead (uno solo si es el CTO) con id, destinatario y canal; si falló el Telegram del CTO, el respaldo incluye el contenido completo; respaldo fallido → aviso por Telegram y correo al CTO y al comercial; aviso fallido por ambos canales → nada más; alerta en ficha y lista del CTO hasta «Atendida por otro medio» (solo CTO, con autor y fecha); buzón sin configurar → correo «fallido» sin intentos y se activa la cadena.
  - Hecho cuando: `tests/test_crm_escalation.py` en verde + comprobación estándar.

- [x] **T17b — Botón «Retractar» en la ficha (decisión K-2)**
  - Requisitos: VCRM-163.
  - Archivos: `src/jerico/crm/render.py` (`render_lead_card` con `buttons`), `src/jerico/crm/leads.py` (envío de la ficha con teclado), `src/jerico/crm/bot.py` (*callback* `retractar`), `tests/test_crm_retraction.py`, `tests/test_crm_views.py`.
  - Tests primero: ficha de un «aceptado» vista por el comercial del lead, el CTO y el abogado → botón «Retractar»; en otro estado o para un comercial ajeno → sin botón; la pulsación abre la elección de motivo y la confirmación ✅/❌ igual que `/retractar L-n`; pulsar un botón obsoleto (lead ya no «aceptado») o sin permiso → rechazo con motivo, sin transición ni notificaciones; `callback_data` ≤ 64 bytes.
  - Hecho cuando: `tests/test_crm_retraction.py` y `tests/test_crm_views.py` en verde + comprobación estándar.

## Cumplimiento

- [x] **T19 — Autorización con evidencia, baja y lista de supresión**
  - Requisitos: VCRM-065, 070, 071, 095, 138, 139, 164 (la baja no elimina la evidencia).
  - Archivos: `src/jerico/crm/compliance.py` (autorización, baja, `may_contact_commercially`), `bot.py` (`/autorizacion`, `/baja`), `tests/test_crm_consent.py`.
  - Tests primero: documento o foto tras «Sí» o `/autorizacion` → adjunto `authorization` y consentimiento «autorizada» con medio, autor, fecha y referencia; texto o voz en su lugar → no registra y lista los medios válidos; `/baja` → estado «baja», huellas de teléfono y correo (sin contacto en claro: inspección de la tabla), confirmaciones canceladas, registro con fecha y medio, consentimiento «revocada» y la evidencia de autorización previa (registro y archivo) intacta (VCRM-164); `may_contact_commercially` falso con huella suprimida aunque el contacto esté en otro lead; ningún correo del sistema va a una dirección que no sea de un usuario autorizado.
  - Hecho cuando: `tests/test_crm_consent.py` en verde + comprobación estándar.

- [x] **T20a — Supresión por orden del CTO de todos los leads del titular, excepción legal y notificación de copias**
  - Requisitos: VCRM-073, 094, 154, 155, 165.
  - Archivos: `compliance.py` (`plan_suppression`, `titular_leads` sin cierre transitivo, `execute_suppression` con `cause='orden_cto'`), `bot.py` (`/suprimir`), `tests/test_crm_suppression.py`.
  - Tests primero: `test_vcrm073_*` con dos leads del mismo contacto (mismo teléfono E.164 o correo normalizado; uno «perdido» y otro activo o retractado) → `/suprimir` sobre uno suprime ambos y la confirmación al CTO lista los dos identificadores; sin cierre transitivo (decisión K-3): teléfono compartido entre A y B y correo entre B y C → `/suprimir` sobre A suprime A y B y deja C intacto; un lead de otro contacto no se toca; la supresión borra ficha, handoff, notas, adjuntos (archivos incluidos), eventos de datos, textos de motivo y cuerpos del *outbox* y conserva la huella del contacto; `test_vcrm165_*`: el archivo de la evidencia de autorización se borra y quedan solo el consentimiento (estado, medio, fecha, versión, finalidades, actor) y la fila del adjunto con tamaño y SHA-256, sin ningún dato del titular en claro (búsqueda de centinelas en toda la base); solo el CTO; con «conservar/fundamento» en aceptado o ganado → conserva solo esos campos en esos leads, `commercial_block` y fundamento, y el resto del grupo se suprime completo; si ningún lead del grupo está en aceptado o ganado (p. ej. retractado) se rechaza la excepción; una notificación crítica de supresión por destinatario y canal con todos los identificadores: al CTO por Telegram y, si alguno estuvo aceptado, al abogado por Telegram y correo con los identificadores de esos leads, sin datos personales; si queda fallida → alerta en la lista del CTO con lead, destinatario y canal hasta «atendida»; fallo al borrar un archivo de cualquier lead del grupo → nada se marca.
  - Hecho cuando: `tests/test_crm_suppression.py` en verde + comprobación estándar.

- [x] **T20b — Exportación de datos del titular y bitácora**
  - Requisitos: VCRM-074, 075, 166.
  - Archivos: `compliance.py` (`export_lead`, `plan_export_parts` pura), `bot.py` (`/exportar`), `tests/test_crm_export.py`.
  - Tests primero: solo el CTO; ZIP con documento legible (ficha, handoff, historial, autorizaciones) y adjuntos vigentes entregado por el chat privado del CTO; archivo temporal borrado también en fallo; `plan_export_parts` con `limit` pequeño → ficha en la parte 1, cada adjunto completo en una sola parte, ninguna parte supera `limit − margen`; exportación que no cabe → partes «parte k de n» enviadas en orden, cada ZIP abrible por sí solo, temporales borrados; fallo al enviar una parte → siguen las demás y aviso al CTO con las no entregadas; una evidencia reducida (VCRM-165) aparece solo como huella mínima; bitácora de creación, modificación, exportación y supresión con actor, acción, lead y fecha (sin datos del titular).
  - Hecho cuando: `tests/test_crm_export.py` en verde + comprobación estándar.

- [x] **T02b — Festivos extraordinarios configurables (decisión K-6)**
  - Requisitos: VCRM-167, 168 (el aviso al CTO al arrancar se cablea en T24).
  - Archivos: `src/jerico/crm/config.py` (`JERICO_CRM_EXTRA_HOLIDAYS`, `parse_extra_holidays`, `HolidayWarning`, `Params.extra_holidays`), `src/jerico/crm/timeutil.py` (parámetro `extra` en `is_business_day`, `add_business_days`, `business_days_between`), `tests/test_crm_config.py`, `tests/test_crm_timeutil.py`.
  - Tests primero: sin variable → conjunto vacío y tests de T02 sin cambios; «2026-12-24, 2026-12-31» → dos fechas; ruta a archivo (`tmp_path`) con una fecha por línea, líneas vacías y comentarios `#` → fechas del archivo; mezcla de fechas y ruta; `2026-02-30`, `24/12/2026` y archivo inexistente → `HolidayWarning` con la entrada (o `ruta:línea`) y el motivo, sin excepción, y las válidas se aplican; un viernes extraordinario no es hábil; `add_business_days` y `business_days_between` lo saltan; los 18 festivos calculados de 2026 siguen iguales.
  - Hecho cuando: `tests/test_crm_config.py` y `tests/test_crm_timeutil.py` en verde + comprobación estándar.

- [x] **T21 — Solicitudes de titulares: plazos hábiles, escalado y vencimiento**
  - Requisitos: VCRM-150, 151, 152.
  - Archivos: `compliance.py` (registro y atención; plazos con `params.extra_holidays`, T02b), `retention.py` (parte de solicitudes de `daily_sweep`), `bot.py` (`/solicitud`, `/solicitudes`, `/atendida`), `tests/test_crm_requests.py`.
  - Tests primero: registro por comercial (propios) y CTO con tipo, medio, recepción y fecha límite en días hábiles desde el día hábil siguiente (10 y 15; con festivo de por medio); fecha futura → error; se muestra al CTO; tope legal aplicado si la configuración lo excede; a los 2 días hábiles sin atender → aviso al CTO con id, lead, tipo, recepción y días restantes; repetición una vez por día hábil (no en sábado, domingo ni festivo; no dos veces el mismo día); al llegar a la fecha límite → «vencida» con alerta y aviso diario; `/atendida` solo CTO, con autor y fecha, detiene avisos.
  - Hecho cuando: `tests/test_crm_requests.py` en verde + comprobación estándar.

- [x] **T22 — Conservación y supresión por plazo (J-01, J-14)**
  - Requisitos: VCRM-145, 146, 147, 158, 159, 164 (y 154 en la supresión por plazo).
  - Archivos: `src/jerico/crm/retention.py` (`daily_sweep`), `tests/test_crm_retention.py`.
  - Tests primero: lead «sin autorización» a los 25 días → un solo aviso al comercial del lead (o al CTO) con id, nombre y fecha de supresión; a los 30 → supresión sin huella, notificación de copias, aviso al comercial y al CTO, auditoría «vencimiento del plazo»; autorización registrada antes → no suprime; reloj detenido en «aceptado»/«ganado» y reiniciado al salir de «aceptado»; perdido/baja a los 12 meses → supresión (huella solo si «baja») con la evidencia de autorización intacta (VCRM-164); ganado → baja conserva adjuntos hasta 10 años desde el paso a ganado; a los 10 años se eliminan con auditoría; fallo de borrado → no se da por suprimido, aviso al CTO y reintento en el barrido siguiente; ejecutar el barrido dos veces el mismo día no duplica efectos.
  - Hecho cuando: `tests/test_crm_retention.py` en verde + comprobación estándar.

## Operación

- [x] **T23 — Respaldo nocturno cifrado fuera de la máquina**
  - Requisitos: VCRM-097, 098.
  - Archivos: `src/jerico/crm/backup.py`, `tests/test_crm_backup.py` (con `FakeRunner`).
  - Tests primero: instantánea consistente con adjuntos y evidencias en el `tar.gz`; `argv` exactos de `age --encrypt --recipient` y `rclone copyto`; nombre con fecha UTC; `expired_backups` elimina los de más de 30 días (tope legal aplicado) con `rclone deletefile`; temporales borrados también en fallo; éxito actualiza `last_backup_ok_at`; fallo en generación, cifrado, subida o borrado (o configuración ausente) → aviso al CTO con causa y fecha del último respaldo correcto.
  - Hecho cuando: `tests/test_crm_backup.py` en verde + comprobación estándar.

- [x] **T24 — Cableado, jobs en `CronScheduler`, arranque y reinicio**
  - Requisitos: VCRM-162 y 168 (aviso al CTO), VCRM-078 y 049 (de extremo a extremo).
  - Archivos: `src/jerico/crm/jobs.py`, `src/jerico/crm/app.py`, `tests/test_crm_app.py`.
  - Tests primero: `register_jobs` registra `crm-daily` (`0 13 * * *`) y `crm-backup` (`0 8 * * *`) y `CronScheduler.tick` con reloj simulado los dispara; al arrancar con parámetros fuera de tope → aviso al CTO por Telegram con parámetro, valor rechazado y vigente; festivo extraordinario inválido → aviso al CTO con la entrada y el motivo, y el arranque continúa; sin token o sin clave HMAC → salida con código 2 y log sin secretos; `daily_sweep` de recuperación al arrancar; latido escrito; de extremo a extremo con dobles: registrar, aceptar con Telegram del abogado caído, «reiniciar» (cerrar y recrear `CrmApp` sobre la misma base) y comprobar que leads, historial y notificación pendiente persisten y que la pendiente completa sus intentos restantes.
  - Hecho cuando: `tests/test_crm_app.py` en verde + comprobación estándar.

## Cierre

- [x] **T25 — Verificación integral y trazabilidad**
  - Requisitos: los 101 de F1 (comprobación de conjunto).
  - Archivos: ninguno nuevo (solo correcciones mínimas si algo falla, sin tocar el núcleo).
  - Pasos: (1) `./scripts/verify.sh` en verde (ruff + mypy + pytest de toda la suite); (2) `PYTHONPATH=src .venv/bin/python -m pytest --cov=src/jerico --cov-report=term` con total ≥ 89 %; (3) `PYTHONPATH=src .venv/bin/python -m pytest tests/test_crm_*.py --cov=src/jerico/crm --cov-report=term` con total ≥ 89 %; (4) trazabilidad: `grep -ohE "vcrm[0-9]{3}" tests/test_crm_*.py | sort -u` contiene los 101 identificadores F1 de la tabla siguiente; (5) `git status` muestra cambios solo en `src/jerico/crm/`, `tests/crm_support.py`, `tests/test_crm_*.py`, `pyproject.toml` (aditivo) y `specs/001-ventas-crm/`.
  - Hecho cuando: los cinco pasos se cumplen y su salida (resumida) se adjunta al reporte para la auditoría del reviewer.

---

## Tabla de cobertura: requisito F1 → tarea

| Requisito | Tarea(s) | Requisito | Tarea(s) | Requisito | Tarea(s) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| VCRM-001 | T10 | VCRM-002 | T10 | VCRM-003 | T11 |
| VCRM-004 | T06, T11 | VCRM-005 | T06 | VCRM-006 | T11 |
| VCRM-007 | T12 | VCRM-008 | T08, T12 | VCRM-009 | T12 |
| VCRM-010 | T13 | VCRM-011 | T13 | VCRM-012 | T08, T10, T15 |
| VCRM-013 | T04 | VCRM-014 | T04, T14 | VCRM-015 | T14 |
| VCRM-016 | T14 | VCRM-017 | T14 | VCRM-046 | T16 |
| VCRM-047 | T15, T16 | VCRM-048 | T07, T16 | VCRM-049 | T15, T24 |
| VCRM-050 | T18 | VCRM-051 | T16 | VCRM-052 | T16 |
| VCRM-065 | T19 | VCRM-066 | T11 | VCRM-070 | T19 |
| VCRM-071 | T19 | VCRM-073 | T20a | VCRM-074 | T20b |
| VCRM-075 | T03, T20b | VCRM-077 | T02 | VCRM-078 | T03, T24 |
| VCRM-079 | T10 | VCRM-080 | T12 | VCRM-081 | T06, T12 |
| VCRM-082 | T06, T12 | VCRM-083 | T12 | VCRM-084 | T17 |
| VCRM-085 | T05 | VCRM-086 | T05, T10 | VCRM-087 | T18 |
| VCRM-088 | T11 | VCRM-089 | T14 | VCRM-090 | T07, T13 |
| VCRM-091 | T09 | VCRM-092 | T09, T13 | VCRM-093 | T09 |
| VCRM-094 | T20a | VCRM-095 | T06, T19 | VCRM-096 | T03 |
| VCRM-097 | T23 | VCRM-098 | T23 | VCRM-104 | T07, T16 |
| VCRM-105 | T08 | VCRM-107 | T18 | VCRM-109 | T05, T12 |
| VCRM-110 | T11 | VCRM-111 | T07, T16 | VCRM-112 | T07, T12 |
| VCRM-113 | T17 | VCRM-114 | T17 | VCRM-115 | T14 |
| VCRM-116 | T14 | VCRM-117 | T04, T14 | VCRM-118 | T14 |
| VCRM-125 | T09 | VCRM-126 | T09 | VCRM-127 | T15 |
| VCRM-128 | T18 | VCRM-129 | T18 | VCRM-130 | T18 |
| VCRM-131 | T17 | VCRM-132 | T14 | VCRM-133 | T04, T14 |
| VCRM-134 | T05, T14 | VCRM-135 | T11 | VCRM-136 | T05, T13 |
| VCRM-137 | T11 | VCRM-138 | T19 | VCRM-139 | T19 |
| VCRM-140 | T08, T18 | VCRM-144 | T09 | VCRM-145 | T22 |
| VCRM-146 | T22 | VCRM-147 | T22 | VCRM-150 | T21 |
| VCRM-151 | T21 | VCRM-152 | T21 | VCRM-154 | T20a, T22 |
| VCRM-155 | T20a | VCRM-156 | T07, T16, T17 | VCRM-158 | T22 |
| VCRM-159 | T22 | VCRM-162 | T01, T24 | VCRM-163 | T17b |
| VCRM-164 | T19, T22 | VCRM-165 | T20a | VCRM-166 | T20b |
| VCRM-167 | T02b | VCRM-168 | T02b, T24 | — | — |

Total: **101 de 101** requisitos F1 con tarea y test asignados; sin huecos (VCRM-106 y VCRM-108 están retirados y no se implementan). Cada tarea T01–T24 (con T20 dividida en T20a y T20b, más T02b y T17b del cambio del 05/10/2026: 27 tareas de implementación) cubre al menos un requisito; T25 verifica el conjunto.

---

> Última modificación: 05/10/2026 08:54 (Planificador SDD)
