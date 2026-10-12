# Plan 001 — CRM de ventas, fase F2 (rechazos y seguimiento)

- **Estado:** borrador para el gate de plan. No sustituye a `plan.md` (F1), que sigue vigente; este documento lo extiende.
- **Base:** `spec.md` (49 requisitos [F2], VCRM-018..039, 067..069, 072, 076, 099..103, 119..124, 141..143, 148, 149, 153, 160, 161, 169..171; decisiones Q-1 a Q-5 en §8) y el código F1 de `src/jerico/crm/`.
- **Validación:** solo con tests (no hay Docker en el portátil). Reloj, SMTP, IMAP y Telegram simulados con dobles de `tests/crm_support.py`.
- **Reglas de F1 que siguen:** núcleo (`gateway/`, `tools/`, `state/`, `cron/`, `main.py`) intacto; funciones puras con parámetro `now`; sin LangChain/LlamaIndex; sin datos personales en logs ni bitácora; stdlib antes que dependencias nuevas (esta fase no añade ninguna).

---

## 1. Decisiones de diseño (con alternativas descartadas)

| ID | Decisión | Alternativa descartada y motivo |
| :--- | :--- | :--- |
| D-1 | **Un solo barrido** `crm-followup` en el `CronScheduler` existente, cron `* * * * *` (UTC), 1 reintento. Pasos en orden: (1) activación F2 única (VCRM-160); (2) consulta del buzón si toca (VCRM-169); (3) expirar propuestas (VCRM-034); (4) generar propuestas vencidas (VCRM-027); (5) entregar envíos programados (VCRM-038). Cada paso aislado con `try/except` y sin datos personales en el log. | Un job por paso: multiplica ejecuciones concurrentes y el planificador ya omite una ejecución si la anterior sigue viva. Cron de 5 min: rompe los reintentos a 1 min de VCRM-038. |
| D-2 | **Idempotencia por restricciones de la base**, no por memoria: `UNIQUE (lead_id, kind, step)` en propuestas de seguimiento (VCRM-028), `UNIQUE (rfc_message_id)` en correo entrante (VCRM-169), `UNIQUE (proposal_id)` en envíos. Cada paso del barrido hace `INSERT ... ON CONFLICT DO NOTHING` y actúa solo si insertó. | Banderas en memoria o fecha del último barrido: se pierden al reiniciar. |
| D-3 | **Primer intento de envío en línea** al pulsar ✅ (si está dentro de franja y cupo); reintentos y diferidos los entrega el barrido cada minuto. Tolerancia: ≤ 60 s sobre 1 y 5 minutos. | Reusar `OutboxWorker` (5 s): su tabla y escalado son de notificaciones internas; mezclar contactos al cliente con críticas internas rompe VCRM-128. Se reutiliza solo `outbox.next_attempt_at` (calendario 0/1/5). |
| D-4 | **Lectura de respuestas: IMAP de solo lectura con sondeo saliente** cada 5 min (`imaplib` de la biblioteca estándar en `asyncio.to_thread`, `BODY.PEEK`, `SELECT` en modo lectura, `UID` incremental con `UIDVALIDITY` en `crm_meta`, lotes de 50, tope de 256 KB por mensaje, tiempo límite de socket 30 s). Deduplicación por `Message-ID`. Sin puerto ni ruta públicos (P-10). | Webhook del proveedor/Cloud Pub/Sub: ruta pública, prohibido por P-10. API Gmail con OAuth: dependencia y consentimiento nuevos. POP3: sin UID estable. Reenvío a una ruta propia: ídem webhook. |
| D-5 | **Baja por cabecera** `List-Unsubscribe: <mailto:BUZON?subject=BAJA%20TOKEN>`; `TOKEN` = id de envío + HMAC truncado con la clave de huella. La baja se identifica por el token, sin palabra clave (VCRM-124). Token inválido → VCRM-122. | `plus-addressing`: no todos los proveedores lo enrutan. Enlace web: prohibido (P-10). |
| D-6 | **Reescribir reinicia el plazo del gate** a `ahora + 48 h`; ✅ sobre versión previa no envía (VCRM-099). | Mantener el plazo original: obliga a reescribir con prisa. |
| D-7 | **Tras expirar**: la propuesta queda `expired`, ✅/❌ responden «expiró» y no la reviven; la cadencia consume el paso y programa el siguiente a `ahora + intervalo` (VCRM-034). Una solicitud de autorización expirada no tiene cadencia: el comercial puede pedir otra. | Permitir ✅ tardío: contradice P-17 y el gate acotado. |
| D-8 | **Hash de contenido**: `sha256(asunto + "\n" + cuerpo)` de la versión aprobada se guarda en el envío; al entregar se recalcula desde la versión almacenada y, si difiere, el envío falla cerrado `content_mismatch` (VCRM-036). | Confiar en el id de versión: no detecta alteración de la fila. |
| D-9 | **Sin buzón de entrada o sin referencia de aviso configurados, F2 no genera ni envía** (VCRM-149, 170) y avisa al CTO una vez: no se puede honrar una baja si no se puede leer. | Enviar sin leer respuestas: incumple J-06. |
| D-10 | **Rebotes y respuestas automáticas** se tratan como respuestas no asociables o por clasificar (VCRM-122/103); no se filtran en F2 (riesgo conocido). | Detección heurística de rebotes: fuera del alcance de la spec. |
| D-11 | Motivos de rechazo (`precio`, `momento`, `proveedor`, `no_interesado`, `otro`) **conservan su código** en español: son claves de configuración de la matriz y viajan en callbacks `v1:` ya emitidos. | Renombrarlos: invalida callbacks y datos sin beneficio. |

## 2. Cambio de valores de dominio a inglés (Q-1; VCRM-171)

**Evaluación: razonable, se hace al INICIO de F2** (tareas F2-T01 a F2-T04). Motivos: convención del repo (identificadores en inglés), F1 aún sin datos de producción conocidos (el volumen a migrar es mínimo), el riesgo es acotado por una transacción y una copia previa, y cada día de retraso encarece el cambio al crecer F2. Los textos que ve el usuario salen de `render.py` por *mapas* enum → etiqueta, así que no cambian.

**Mapa de valores (los nombres de miembro Python también pasan a inglés):**

| Enum | Antes → después |
| :--- | :--- |
| `LeadState` | nuevo→`new`, contactado→`contacted`, aceptado→`accepted`, rechazado→`rejected`, en_nutricion→`nurturing`, pausado→`paused`, reactivado→`reactivated`, ganado→`won`, perdido→`lost`, baja→`opted_out` |
| `AuthStatus` | sin_autorizacion→`unauthorized`, autorizada→`authorized`, revocada→`revoked` |
| `OutboxStatus` | pendiente→`pending`, entregada→`delivered`, fallida→`failed` |
| `RequestType` | consulta→`inquiry`, reclamo→`claim` (+ nuevo `unclassified`, VCRM-153) |
| `RequestStatus` | abierta→`open`, vencida→`overdue`, atendida→`attended` |
| Estado de `crm_confirmations` | pendiente→`pending`; los valores de resolución se inventarían al leer `repo.resolve_confirmation` (tarea T01) |

**Fuera del mapa (se justifica):** códigos de motivo (D-11), `AuditDetail` (`orden_cto`, `vencimiento_plazo`), `suppression_cause` y `medium` de consentimientos/supresión (son etiquetas de evidencia legal ya firmadas; reescribirlas altera evidencia sin beneficio).

**Superficie afectada (inventario):**
- Columnas con valores: `crm_leads.state`, `crm_leads.auth_status`, `crm_lead_events.old_value/new_value` (cuando `kind='state'`), `crm_consents.status`, `crm_outbox.status`, `crm_titular_requests.type/status`, `crm_confirmations.status`; `crm_pending_inputs.data` y `crm_alerts.kind` no guardan estos valores (verificar en T01).
- `CHECK` en `crm_outbox.status`, `crm_titular_requests.type/status`: SQLite no altera `CHECK`; se reconstruyen las tablas (`CREATE new` → `INSERT ... SELECT CASE` → `DROP old` → `ALTER ... RENAME`).
- Código: `model.py`, `states.py`, `leads.py`, `compliance.py`, `retention.py`, `repo.py` (SQL con literales), `render.py`, `outbox.py`, `bot.py`, `parsing.py` y ~25 archivos de tests (`tests/crm_support.py::make_lead` usa `"aceptado"` y `"sin_autorizacion"`).
- **Callbacks `v1:`:** llevan la operación (`contacto`, `aceptar`…) y el código de motivo, no valores de estado; formato y `CALLBACK_VERSION` no cambian. Un test (`test_vcrm171_callbacks_v1_emitidos_siguen_vigentes`) fija una muestra de callbacks de F1 y exige que sigan interpretándose. Si T01 encontrara un callback con valor de estado, se añade un alias de lectura en `parsing.py`.

**Procedimiento de migración (`src/jerico/crm/migrate.py`, `schema_version` 1 → 2):**
1. Se ejecuta al abrir la base si `schema_version = 1`, antes de cualquier consulta de negocio, con el servicio detenido.
2. Copia previa con la API de respaldo de `sqlite3` a `<db>.pre-v2.bak` (tras `wal_checkpoint(TRUNCATE)`); `PRAGMA integrity_check` de la copia debe devolver `ok`; si falla, aborta sin tocar la base.
3. Una única transacción `BEGIN IMMEDIATE`: `UPDATE ... CASE` de las columnas, reconstrucción de las tres tablas con `CHECK` v2, `CREATE TABLE IF NOT EXISTS` de las tablas F2 (§3), `PRAGMA foreign_key_check` vacío y, por último, `schema_version = 2`. Cualquier excepción → *rollback* completo y la base queda en v1 intacta.
4. Idempotente: con `schema_version = 2` no hace nada. Una base nueva nace directamente en v2.
5. Sin migración descendente.

**Riesgos y rollback:**
- *R-M1* valor no mapeado (dato corrupto): la migración falla con `CASE ... ELSE RAISE`-equivalente (se cuenta `SELECT` de valores fuera del mapa antes del `UPDATE`; si > 0, aborta con la lista de valores, sin datos personales). Mitigación: test con valor desconocido.
- *R-M2* interrupción a mitad: SQLite es transaccional; queda v1.
- *R-M3* respaldo cifrado de F1 (VCRM-097) restaurado sobre código v2: la base restaurada es v1 y se migra al arrancar; test incluido.
- **Rollback operativo:** detener el servicio; restaurar `<db>.pre-v2.bak` sobre la base; volver a la imagen/commit anterior (`34ad63e`). Lo escrito después de migrar se pierde, por eso se migra con el servicio detenido y se arranca F2 solo tras verificar. Si el humano prefiere no migrar: dejar fuera T01–T04 solo es posible a costa de mantener valores en español (F2 funcionaría igual); se descarta por coherencia, no por técnica.

## 3. Modelo de datos F2 (todas con `CREATE TABLE IF NOT EXISTS`, parte de v2)

| Tabla | Columnas clave | Restricciones |
| :--- | :--- | :--- |
| `crm_cadences` | `lead_id` PK→leads, `reason`, `interval_days`, `total_steps`, `steps_done`, `sent_count`, `next_action_at` NULL, `last_sent_at`, `status` (`active`,`paused`,`completed`,`stopped`), `started_at`, `updated_at` | una cadencia por lead |
| `crm_proposals` | `id`, `lead_id`, `kind` (`followup`,`auth_request`), `step` NULL, `status` (`pending`,`approved`,`sent`,`failed`,`cancelled`,`expired`,`blocked`), `current_version`, `approver_user_id`, `expires_at`, `created_at`, `resolved_at`, `resolved_by` | índice único parcial `(lead_id, kind, step)` para `followup` (VCRM-028); único parcial de una `auth_request` abierta por lead |
| `crm_proposal_versions` | `proposal_id`, `version`, `subject`, `body`, `content_hash`, `author_user_id`, `created_at` | PK `(proposal_id, version)` |
| `crm_sends` | `id`, `proposal_id` UNIQUE, `version`, `approved_hash`, `approved_by`, `approved_at`, `scheduled_at`, `status` (`scheduled`,`sent`,`failed`,`cancelled`), `attempts`, `first_attempt_at`, `next_attempt_at`, `rfc_message_id`, `last_error`, `sent_at`, `lead_id`, `week_start` | índice `(lead_id, week_start, status)` para el cupo semanal |
| `crm_inbound` | `id`, `rfc_message_id` UNIQUE, `uid`, `received_at`, `sender_fp`, `lead_id` NULL, `association` (`thread`,`sender`,`token`,`none`), `class` (`stop_keyword`,`stop_header`,`auth_candidate`,`review`,`unassociated`), `new_text`, `decision` (`pending`,`confirmed`,`rejected`,`n/a`), `decided_by`, `decided_at` | contiene datos personales: entra en la supresión (VCRM-073) y en la depuración por plazo |
| `crm_titular_requests` (v2) | + `inbound_id` NULL; `type` admite `unclassified` | reconstruida en la migración |
| `crm_meta` | claves nuevas: `f2_activated_at`, `imap_uidvalidity`, `imap_last_uid`, `imap_last_poll_at`, `imap_failing` | — |

## 4. Archivos a tocar

Nuevos (`src/jerico/crm/`): `migrate.py`, `sendwindow.py` (puro), `cadence.py` (puro), `inbound.py` (puro), `followup_text.py` (carga TOML + plantillas), `followup.py` (generación, gate, entrega), `inbox.py` (adaptador IMAP), `authreq.py` (solicitud y confirmación de autorización), `sweep.py`.
Modificados: `__init__.py` (`CURRENT_PHASE = 2`), `model.py`, `states.py`, `db.py`, `repo.py`, `config.py`, `ports.py` (`InboxPort`, cabeceras opcionales en `EmailSender.send`), `mail.py`, `compliance.py` (`may_contact_commercially`), `leads.py` (gancho de rechazo y de reactivación), `bot.py`, `render.py`, `jobs.py`, `app.py`, `permissions.py` (solo si falta una acción de cadencia).
Tests nuevos: `tests/test_crm_migration.py`, `test_crm_sendwindow.py`, `test_crm_cadence.py`, `test_crm_followup.py`, `test_crm_gate.py`, `test_crm_inbox.py`, `test_crm_inbound.py`, `test_crm_authreq.py`, `test_crm_sweep.py`, `test_crm_f2_bot.py`, `test_crm_f2_acceptance.py`; `tests/crm_support.py` crece (`FakeInbox`, `FakeClock` ya existen).

## 5. Diseño por requisito (algoritmos)

### 5.1 Franja y cupo (`sendwindow.py`, VCRM-072, 076, 100, 101)
```
allowed(at, extra):                # at aware; se convierte a Bogotá
  d = local_date(at); t = hora local
  if d in festivos(d.year) | extra or d.weekday()==6: return False
  return (d.weekday()<=4 and 07:00<=t<19:00) or (d.weekday()==5 and 08:00<=t<15:00)
next_slot(at, extra): primer instante >= at con allowed() (inicio de franja del siguiente día válido)
week_start(at): lunes 00:00 Bogotá de la semana de at
schedule(now, sends_in_week_fn, limit, extra):
  c = next_slot(now)
  while sends_in_week_fn(week_start(c)) >= limit: c = next_slot(week_start(c)+7 días)
  return c
```
La franja y el límite salen de `Params` con topes legales (VCRM-162: no ampliar franja, límite ≤ 1). El cupo cuenta envíos `scheduled` y `sent` del lead en esa semana (también `auth_request`).

### 5.2 Cadencias (`cadence.py`, VCRM-018..026, 121, 160)
Matriz por defecto (3 pasos, intervalo en días; textos del CTO en TOML):

| Motivo | Pasos | Intervalo | Tipo de contenido |
| :--- | :---: | :---: | :--- |
| `precio` | 3 | 30 | propuesta de valor (alcance y opciones) |
| `momento` | 3 | 30 (60 si el CTO lo configura: 30/60/90 acumulados) | recordatorio |
| `proveedor` | 3 | 30 | contenido educativo |
| `no_interesado` | 3 | 30 | contenido educativo |
| `otro` | 3 | 30 | genérico |

```
start(lead, now): if not auth_vigente: notificar falta (019); return
   reason→row; insert crm_cadences(active, next_action_at = now + interval)    # 018 / 121 / 160 (desde now)
   lead -> nurturing
on_step_consumed(cad, now, outcome):      # sent | cancelled | expired
   steps_done += 1; if outcome==sent: sent_count += 1; last_sent_at = ...
   if steps_done >= total: status=completed; next_action_at=NULL; avisar con botones «Marcar perdido»/«Reactivar» (026)
   else next_action_at = (sent_at|now) + interval
pause: lead nurturing->paused; cad.status=paused; cancelar propuestas pendientes (020, 021)
resume: next_action_at = now + interval (022)   # sin acciones omitidas
set_frequency(weekly=7|monthly=30): next = (last_sent_at or now) + nuevo_interval (023)
reactivate: cad.status=stopped; cancelar pendientes (024)
```
Activación (VCRM-160): en el primer barrido con `f2_activated_at` ausente, para cada lead `rejected` con autorización vigente se llama `start` con `now` = activación, y se guarda `f2_activated_at` en la misma transacción.

### 5.3 Generación y gate (`followup.py`, VCRM-027..039, 067, 099)
```
generate_due(now):
  if not f2_enabled(): return                       # D-9
  for cad en active con next_action_at <= now y lead.state==nurturing:
     if not may_contact_commercially(lead): continue            # 067 (Q-4)
     if lead.email is None: avisar dato faltante; continue      # 039
     text = followup_text.lookup(reason, step)
     if text is None: avisar CTO una vez; continue              # 161, cadencia no avanza
     INSERT proposal(kind=followup, step=steps_done+1, expires=now+48h) ON CONFLICT DO NOTHING   # 028
     if insertado: version 1 (texto + pie con remitente y BAJA, 069); cad.next_action_at=NULL
                   enviar al aprobador (comercial del lead o CTO) con ✅ ❌
approve(user, pid, ver, now):
  if user no aprobador: audit(permission_denied); return                        # 035
  p = get(pid)
  if p.status != pending: "ya procesada" (030) / "expiró" (D-7)
  if p.expires_at <= now: expire(p); return
  if ver != p.current_version: "reemplazada; vigente = n" (099)
  if not guard(lead, p, now): p.status=blocked; "cancelado por estado"; avisar (037)
  slot = sendwindow.schedule(...)
  insert crm_sends(approved_hash = version.content_hash, scheduled_at=slot); p.status=approved
  if slot > now: informar fecha-hora prevista (100/101) else deliver(send_id) en línea
reject(❌) -> botones «Cancelar envío»/«Reescribir»  (031)
cancel: p.status=cancelled; on_step_consumed(cancelled) (032)
rewrite: pending_input 'rewrite' -> texto -> nueva versión, expires=now+48h, invalida la previa (033, D-6)
expire_due(now): pending con expires_at<=now -> expired; avisar; si followup: on_step_consumed(expired) (034)
```
`guard(lead, p)`: seguimiento = estado `nurturing` ∧ autorización vigente ∧ no suprimido ∧ no `commercial_block` ∧ no `opted_out`; solicitud de autorización = solo no suprimido ni `opted_out` (VCRM-037, 067, 071).

### 5.4 Entrega (`followup.deliver_due`, VCRM-036, 038, 072, 076)
```
for s in sends scheduled con next_attempt_at <= now:
   if not allowed(now): s.next_attempt_at = next_slot(now); continue          # sin intentos fuera de franja
   if cupo_semanal excedido por otro envío: reprogramar (101)
   if not guard(...): s.cancelled; p.status=blocked; avisar                    # antes de CADA intento
   if sha256(version) != s.approved_hash: s.failed('content_mismatch'); avisar # 036
   r = email.send(to, asunto, cuerpo, headers={List-Unsubscribe, Auto-Submitted: no})
   ok -> s.sent, rfc_message_id, p.sent; on_step_consumed(sent) (029)
   fail -> attempts += 1; nxt = outbox.next_attempt_at(first_attempt_at, attempts)
           if nxt None o not allowed(nxt): s.failed; avisar; cadencia sin avanzar hasta reintentar/cancelar (038)
```
Botones de la propuesta fallida: «Reintentar» (nuevo calendario) y «Cancelar» (consume el paso).

### 5.5 Correo al cliente (`mail.py`, `ports.py`; VCRM-069, 123)
`EmailSender.send(to, subject, body, headers: Mapping[str, str] | None = None)`: parámetro opcional, los llamadores de F1 no cambian. `SmtpEmailSender` rechaza CR/LF en `to`, `subject` y valores de cabecera. Pie fijo: identificación del remitente + «responda BAJA para no recibir más mensajes»; ningún enlace.

### 5.6 Solicitud de autorización (`authreq.py`, VCRM-068, 148, 149, 141..143)
- Comando `/autorizacion L-NNNN` (permiso 4.4): falta política/aviso/encargados → responde que falta la configuración y no crea propuesta (149). Con configuración: propuesta `auth_request` con aviso, versión, encargados (`Telegram, Google` por defecto) e instrucciones de responder o `BAJA` (148, 068); mismo gate y límites que un seguimiento.
- Respuesta candidata (119): `crm_inbound.class='auth_candidate'`; al comercial del lead se le presenta el texto nuevo, fecha-hora y forma de asociación con ✅/❌ (`v1:aok:<inbound_id>`, `v1:ano:<inbound_id>`).
- ✅ (141): `compliance` registra autorización medio «respuesta al correo confirmada por el comercial» con versión del aviso y finalidades de la solicitud enviada, referencia al mensaje; si el lead está `rejected` arranca cadencia (121). ❌ (142): historial, sin autorización. Doble pulsación (143): `decision != pending` → «ya procesada».

### 5.7 Respuestas entrantes (`inbox.py`, `inbound.py`; VCRM-102, 103, 119..124, 153, 169, 170)
```
poll(now): si imap_last_poll_at + período > now: return
   try: msgs = inbox.fetch_new(uidvalidity, last_uid)    # solo lectura
   except: si no imap_failing: avisar CTO (una vez); imap_failing=1; return                  # 170
   imap_failing=0; for m in msgs: INSERT crm_inbound ON CONFLICT(rfc_message_id) DO NOTHING; si insertó: classify(m)
   avanzar last_uid solo tras persistir el lote
classify(m):
   token_baja = subject coincide «BAJA <token>» con HMAC válido
   lead = asociar(m)  # In-Reply-To/References ∈ crm_sends.rfc_message_id; si no, huella del remitente con exactamente un lead
   si token_baja válido: lead del envío -> aplicar baja (medio «cabecera de baja del correo»)            # 124
   elif lead is None: titular_request(unclassified) -> CTO                                              # 122, 153
   else:
      t = extract_new_text(m.body)        # descarta citas «>», «El ... escribió:», «On ... wrote:», firmas de reenvío
      si has_stop_keyword(t): baja (medio «respuesta al correo»); no proponer autorización             # 102, 120
      elif lead sin autorización vigente ∧ existe auth_request enviada a ese lead: candidata (119)
      else: titular_request(unclassified) -> comercial del lead                                         # 103, 153
```
`has_stop_keyword`: palabra completa «baja», sin mayúsculas ni tildes (`unicodedata` NFKD), delimitada por inicio/fin/espacios/puntuación (definición 4.5). La baja usa el flujo F1 `compliance` (VCRM-070) sin acuse al titular (Q-5). El texto de la respuesta se muestra como texto plano, sin `parse_mode`, truncado a 1.500 caracteres, sin caracteres de control.

### 5.8 Guarda de contacto (VCRM-067, Q-4)
`compliance.may_contact_commercially` pasa a exigir además `lead.auth_status == authorized` (con evidencia, sin revocatoria). La solicitud de autorización usa una variante `may_request_authorization` (sin exigir autorización). Los tests de F1 que esperan `True` sin autorización se ajustan en F2-T11 (cambio de comportamiento aprobado por la spec).

### 5.9 Vista y comandos (VCRM-025, 020..024)
`/seguimiento` (tabla de leads visibles `nurturing`/`paused` con motivo, frecuencia, próxima acción, envíos); botones en la ficha: Pausar, Reanudar, Frecuencia semanal/mensual, Reactivar, Marcar perdido. Permisos según 4.4; abogado sin acceso.

## 6. Configuración nueva (`CrmSettings`, prefijo `JERICO_CRM_`)
`imap_host`, `imap_port` (993), `imap_username`, `imap_password` (SecretStr, sin valor por defecto, `repr` enmascarado), `imap_mailbox` (`INBOX`), `inbox_poll_minutes` (5, mínimo 1), `privacy_notice_ref`, `privacy_notice_version`, `data_processors` (`Telegram,Google`), `cadence_file` (ruta TOML con textos por motivo y paso; por defecto `<data_dir>/cadences.toml`; sin archivo → VCRM-161). Faltantes: `app.py` no falla (F1 sigue operando) pero F2 queda deshabilitada y avisa al CTO (D-9).

## 7. Estrategia de pruebas

TDD estricto; cada test lleva `test_vcrmNNN_` en el nombre. Dobles: `FakeInbox` (lista de mensajes con UID, fallos programables), `FakeEmailSender` con cabeceras capturadas, reloj simulado.

| Requisito | Test(s) (archivo) |
| :--- | :--- |
| 018, 019 | `test_vcrm018_rechazo_con_autorizacion_crea_cadencia`, `test_vcrm019_rechazo_sin_autorizacion_avisa` (`test_crm_cadence`) |
| 020, 021 | `test_vcrm020_pausar_cancela_pendientes`, `test_vcrm021_pausado_no_genera` (`test_crm_cadence`) |
| 022, 023, 024 | `test_vcrm022_reanudar_sin_omitidas`, `test_vcrm023_frecuencia_desde_ultimo_envio`, `test_vcrm024_reactivado_detiene` (`test_crm_cadence`) |
| 025 | `test_vcrm025_vista_seguimiento_visibilidad` (`test_crm_f2_bot`) |
| 026 | `test_vcrm026_ultimo_paso_avisa_sin_perder` (`test_crm_cadence`) |
| 027, 161, 039 | `test_vcrm027_genera_propuesta_al_vencer`, `test_vcrm161_sin_texto_no_avanza`, `test_vcrm039_sin_correo_avisa` (`test_crm_followup`) |
| 028 | `test_vcrm028_barrido_repetido_no_duplica`, `test_vcrm028_reinicio_no_duplica` (`test_crm_followup`, `test_crm_sweep`) |
| 029, 030, 031 | `test_vcrm029_aprobar_envia_y_programa_siguiente`, `test_vcrm030_doble_pulsacion`, `test_vcrm031_rechazo_ofrece_opciones` (`test_crm_gate`) |
| 032, 033, 099 | `test_vcrm032_cancelar_salta_paso`, `test_vcrm033_reescribir_nueva_version`, `test_vcrm099_aprobar_version_obsoleta` (`test_crm_gate`) |
| 034, 035 | `test_vcrm034_expira_a_las_48h`, `test_vcrm034_aprobar_tras_expirar`, `test_vcrm035_no_aprobador_audita` (`test_crm_gate`) |
| 036 | `test_vcrm036_hash_distinto_falla_cerrado`, `test_vcrm036_acuse_requiere_aprobacion` (`test_crm_gate`) |
| 037 | `test_vcrm037_estado_cambia_cancela`, `test_vcrm037_solicitud_solo_suprimido` (`test_crm_gate`) |
| 038 | `test_vcrm038_tres_intentos_0_1_5`, `test_vcrm038_sin_intentos_fuera_de_franja`, `test_vcrm038_fallido_no_avanza` (`test_crm_gate`) |
| 067, Q-4 | `test_vcrm067_sin_autorizacion_no_genera`, `test_vcrm067_guarda_exige_autorizacion` (`test_crm_followup`, `test_crm_consent`) |
| 068, 148, 149 | `test_vcrm068_solicitud_pasa_por_gate`, `test_vcrm148_incluye_aviso_y_encargados`, `test_vcrm149_sin_aviso_no_prepara` (`test_crm_authreq`) |
| 069, 123 | `test_vcrm069_pie_con_baja_sin_enlaces`, `test_vcrm123_cabecera_list_unsubscribe` (`test_crm_authreq`, `test_crm_adapters`) |
| 072, 100 | `test_vcrm072_franja_lv_sab_festivos`, `test_vcrm100_difiere_al_inicio_de_franja` (`test_crm_sendwindow`) |
| 076, 101 | `test_vcrm076_un_contacto_por_semana`, `test_vcrm101_excedente_a_semana_siguiente` (`test_crm_sendwindow`) |
| 102, 120 | `test_vcrm102_baja_por_respuesta_inmediata`, `test_vcrm120_baja_en_respuesta_a_solicitud` (`test_crm_inbound`) |
| 103, 153 | `test_vcrm103_respuesta_a_revision`, `test_vcrm153_botones_y_fecha_limite` (`test_crm_inbound`) |
| 119, 141, 142, 143 | `test_vcrm119_propone_autorizacion`, `test_vcrm141_confirma_registra`, `test_vcrm142_rechaza_no_registra`, `test_vcrm143_doble_pulsacion` (`test_crm_authreq`) |
| 121, 160 | `test_vcrm121_autorizar_rechazado_crea_cadencia`, `test_vcrm160_activacion_desde_ahora` (`test_crm_cadence`, `test_crm_sweep`) |
| 122 | `test_vcrm122_no_asociable_al_cto` (`test_crm_inbound`) |
| 124 | `test_vcrm124_cabecera_aplica_baja`, `test_vcrm124_token_invalido` (`test_crm_inbound`) |
| 169, 170 | `test_vcrm169_mensaje_una_sola_vez`, `test_vcrm169_sin_ruta_publica`, `test_vcrm170_fallo_avisa_una_vez_y_recupera` (`test_crm_inbox`, `test_crm_sweep`) |
| 171 | `test_vcrm171_migracion_conserva_datos`, `..._valor_desconocido_aborta`, `..._idempotente`, `..._copia_previa`, `..._callbacks_v1_emitidos_siguen_vigentes`, `..._respaldo_f1_restaurado` (`test_crm_migration`) |

Además: `test_crm_f2_acceptance.py` recorre rechazo → cadencia → propuesta → ✅ → envío → respuesta → baja con dobles, y cada fase termina con `./scripts/verify.sh`. Cobertura ≥ 89 % global y del paquete `crm` (hoy 97 %).

## 8. Cambios propuestos fuera del alcance (NO se aplican; los decide el coordinador/CTO)

- **`docker-compose.yml`:** ninguno estructural. El servicio `jerico-crm` ya tiene `env_file`; no se abre ningún puerto (P-10). Salida requerida: 993/TCP (IMAP) al proveedor, además del SMTP ya permitido. Si se restringe la red de salida, añadir esa regla. Volumen de `data/crm` debe ser persistente y admitir la copia `*.pre-v2.bak` y `cadences.toml`.
- **`Dockerfile`:** ninguno (sin dependencias nuevas; `imaplib`, `tomllib` y `email` son de la biblioteca estándar de Python 3.12).
- **`.env.example`** (variables nuevas, sin valores reales): `JERICO_CRM_IMAP_HOST`, `JERICO_CRM_IMAP_PORT=993`, `JERICO_CRM_IMAP_USERNAME`, `JERICO_CRM_IMAP_PASSWORD`, `JERICO_CRM_IMAP_MAILBOX=INBOX`, `JERICO_CRM_INBOX_POLL_MINUTES=5`, `JERICO_CRM_PRIVACY_NOTICE_REF`, `JERICO_CRM_PRIVACY_NOTICE_VERSION`, `JERICO_CRM_DATA_PROCESSORS=Telegram,Google`, `JERICO_CRM_CADENCE_FILE`.
- **Despliegue:** crear un buzón dedicado con acceso IMAP y contraseña de aplicación; redactar `cadences.toml` (textos del CTO, P-21) y aviso de privacidad (abogado, J-02) antes de activar; migrar con el servicio detenido (§2).

## 9. Riesgos
(1) Falsos positivos de «BAJA» (aceptado, P-31). (2) Dependencia del proveedor IMAP; mitigada por VCRM-170 y D-9. (3) Rebotes llegan al CTO como no asociables (D-10). (4) La migración Q-1 toca datos; mitigada por copia, transacción única y tests. (5) Tolerancia de ±60 s en reintentos (D-3). (6) Rechazos por retractación (`rejection_is_retraction`) entran también en cadencia (VCRM-018 no los excluye); si el CTO no lo quiere, es un cambio de spec.

## 10. Implementación: desviaciones respecto al diseño y pendientes de despliegue (11/10/2026)

Lo construido difiere del diseño original en lo siguiente; cada punto tiene su test.

**Módulos.** En vez de concentrar todo en `followup.py`: `followup.py` (cadencias y generación de propuestas), `gate.py` (decisiones del aprobador), `delivery.py` (franja, cupo, reintentos y entrega), `replies.py` (respuestas del titular y sondeo), `authreq.py` (solicitud y confirmación de la autorización), `f2_bot.py` (botones y comando), `followup_view.py` (vista y botones de la ficha) y `sweep.py` (el barrido). Los botones se registran por los puntos de extensión de `CrmBot`; su núcleo no cambió.

**Esquema (v2, aún sin desplegar).** `crm_inbound.classification` (no `class`, palabra reservada). `crm_titular_requests.lead_id` admite nulo (respuesta sin lead asociable, VCRM-122) y gana `inbound_id`. `crm_consents.evidence_inbound_id` guarda la referencia al correo que sirvió de evidencia (VCRM-141). El índice único de propuestas de seguimiento ignora las **canceladas y bloqueadas**: pausar cancela la propuesta sin avanzar el paso y, con el índice original, reanudar dejaba la cadencia atascada para siempre.

**Seguridad.** La huella del contenido aprobado antepone la longitud del asunto (con `asunto + "\n" + cuerpo` dos pares distintos colisionaban). Un token de baja inválido no recurre al hilo ni al remitente. `extract_new_text` descarta además las líneas que el cliente reproduce tal cual de nuestro mensaje y el pie «Responda BAJA…»; el aviso de privacidad tiene una única instrucción de baja y ninguna otra frase con esa palabra. Las acciones automáticas se atribuyen a `SYSTEM_USER_ID` (0), no a un usuario.

**Producto.** El comando de F2 es `/pedirautorizacion L-n` (el `/autorizacion` de F1 sigue registrando la evidencia). «Reescribir» no se ofrece para una solicitud de autorización (texto legal). Una respuesta sin lead solo ofrece «Sin solicitud». Aviso de privacidad y textos de cadencias viajan como **recursos del paquete** (`resources/`), sustituibles por archivo (`JERICO_CRM_PRIVACY_NOTICE_FILE`, `JERICO_CRM_CADENCE_FILE`); un archivo configurado que no se puede leer deja F2 deshabilitada, no recurre al del paquete. `start_cadence` desde los ganchos no recibe las claves de huella: la guarda definitiva con huellas se aplica al generar y en cada intento de envío. Los usuarios no guardan nombre, así que los textos no usan `{comercial}`.

**Comportamiento de F1 que cambia.** `CURRENT_PHASE = 2` habilita las filas de F2 de la máquina de estados. El arranque, sin configuración de F2, avisa **una vez** al CTO de que F2 está deshabilitada y por qué (antes no enviaba nada). `/lista` oculta los leads suprimidos.

**Pendiente antes de activar F2 en producción (nada de esto se puede hacer sin credenciales reales).**
1. Variables en `.env`: `JERICO_CRM_IMAP_HOST/USERNAME/PASSWORD` (buzón dedicado con contraseña de aplicación), el SMTP de salida y `JERICO_CRM_SENDER_NAME` si no es «Kaisen AI». Salida a 993/TCP si hay filtro.
2. Datos registrales del responsable en el aviso de privacidad (razón social, NIT, domicilio), hoy marcados `[PENDIENTE]` en `resources/aviso-privacidad.md`.
3. Prueba con Telegram y correo reales en la instancia, y verificar la entrega de las bajas desde un cliente de correo real (cabecera `List-Unsubscribe`).
4. Migrar con el servicio detenido; queda una copia `crm.db.pre-v2.bak` junto a la base.

> Última modificación: 11/10/2026 17:53 (Planificador SDD)
