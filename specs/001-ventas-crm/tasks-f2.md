# Tareas 001 — CRM de ventas, fase F2

- **Estado:** borrador para el gate de tareas (fase 5 SDD). La implementación la delega el humano por tarea al panel Gemini y el coordinador verifica; las tareas «NO delegable» las trabaja el coordinador.
- **Base:** `plan-f2.md` (diseño) y los 49 requisitos [F2] de `spec.md`. `tasks.md` (F1) no se modifica.
- **Cómo usar una tarea como contrato:** copiar sus campos + los bloques **PROH** y **VERIF** de abajo, sustituyendo `<TESTS>` por los archivos de la tarea.

## Bloques comunes

**PROH (prohibiciones, aplican a todas):** no tocar `src/jerico/{gateway,tools,state,cron}/`, `main.py`, `tests/conftest.py`, `docker-compose.yml`, `Dockerfile`, `.env*`, `DECISIONES_CTO.md`, `docs/architecture/`, `scripts/oci/`, `scripts/bootstrap_vps_oracle.sh`, `plan.md`, `tasks.md` ni archivos fuera de «Entregable exacto»; sin dependencias nuevas; sin LangChain/LlamaIndex; sin datos personales en logs ni bitácora; sin `git commit` ni `git push`; no inventar requisitos: ante duda de diseño, detenerse y reportar.

**VERIF (comando exacto, desde la raíz del repo):**
```
PYTHONPATH=src .venv/bin/python -m pytest <TESTS> -q \
 && .venv/bin/ruff check src/jerico/crm tests/crm_support.py tests/test_crm_*.py \
 && .venv/bin/mypy src/jerico/crm tests/crm_support.py tests/test_crm_*.py \
 && ./scripts/verify.sh
```

**Reglas de método:** TDD (los tests nuevos se ejecutan primero y deben fallar por la razón correcta; se reporta la salida roja), nombres `test_vcrmNNN_...`, sin red (dobles de `tests/crm_support.py`), una tarea por sesión, detenerse al terminar y reportar archivos tocados y salida de VERIF. Estilo y dobles: ver `tests/test_crm_outbox.py` y `tests/crm_support.py`.

---

## A. Migración a valores en inglés (Q-1, VCRM-171; plan-f2 §2)

- [x] **F2-T01 — Tests rojos de migración v1→v2**
  - **Delegable a Gemini:** NO — arquitectura/seguridad: define la migración de datos persistidos y su criterio de aborto.
  - Requisitos: VCRM-171.
  - **Entregable exacto:** `tests/test_crm_migration.py`; adición a `tests/crm_support.py` (`build_v1_database(path)`: DDL v1 literal + filas de ejemplo en todos los estados); inventario de valores de `crm_confirmations.status` anotado en un comentario del test.
  - **Insumos:** `plan-f2.md` §2; `src/jerico/crm/db.py`, `model.py`, `repo.py` (`resolve_confirmation`), `parsing.py` (callbacks), `backup.py`.
  - **Tests primero:** `test_vcrm171_migracion_conserva_datos`, `..._valor_desconocido_aborta`, `..._idempotente`, `..._copia_previa`, `..._transaccion_unica_rollback`, `..._callbacks_v1_emitidos_siguen_vigentes`, `..._respaldo_f1_restaurado`.
  - **Hecho cuando:** los tests existen y fallan por ausencia de `migrate.py` (no por error de sintaxis).
  - **Verificación:** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_crm_migration.py -q` (rojo esperado).

- [x] **F2-T02 — `migrate.py` independiente (aún sin conectar)**
  - **Delegable a Gemini:** NO — arquitectura/seguridad: transforma datos persistidos y alberga el rollback.
  - Requisitos: VCRM-171.
  - **Entregable exacto:** `src/jerico/crm/migrate.py` (`migrate_v1_to_v2(path) -> None`, mapa de valores de plan-f2 §2, copia `.pre-v2.bak` con `integrity_check`, transacción única, reconstrucción de `crm_outbox`, `crm_titular_requests` y `CHECK` v2).
  - **Insumos:** `plan-f2.md` §2 y §3; `db.py`; `tests/test_crm_migration.py`.
  - **Prohibiciones:** PROH; no cambiar `SCHEMA_VERSION` ni `CrmDatabase` aún.
  - **Tests primero:** los de F2-T01 (pasan a verde).
  - **Hecho cuando:** `tests/test_crm_migration.py` en verde salvo `callbacks_v1...` (se cierra en T03) y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_migration.py`.

- [ ] **F2-T03 — Renombrar valores y miembros de enums a inglés (mecánico, atómico)**
  - **Delegable a Gemini:** SÍ (con revisión del coordinador del diff de `db.py` y `repo.py`). Excepción de tamaño: cambio mecánico que no puede partirse sin dejar la suite en rojo (≈ 45 min).
  - Requisitos: VCRM-171 (conservación del significado visible).
  - **Entregable exacto:** `src/jerico/crm/{model,states,leads,compliance,retention,repo,render,outbox,bot,parsing,db}.py` (miembros, literales SQL y `CHECK` v2; `SCHEMA_VERSION = 2`; fila inicial `schema_version = '2'`; `RequestType.UNCLASSIFIED`) y todos los `tests/test_crm_*.py` + `tests/crm_support.py` con los literales actualizados.
  - **Insumos:** `plan-f2.md` §2 (mapa); `grep -rnE` de los nombres antiguos en `src/jerico/crm tests`.
  - **Prohibiciones:** PROH; no cambiar códigos de motivo (`precio`, `momento`, `proveedor`, `no_interesado`, `otro`), `AuditDetail`, `medium` ni textos visibles; no tocar `migrate.py`.
  - **Tests primero:** añadir a `tests/test_crm_render.py` `test_vcrm171_textos_visibles_no_cambian` (golden de las etiquetas de estado y autorización) y ejecutarlo antes del cambio (verde) y después (verde).
  - **Hecho cuando:** `grep -rnE "RECHAZADO|AUTORIZADA|VENCIDA|EN_NUTRICION|SIN_AUTORIZACION|ENTREGADA|FALLIDA|ABIERTA|ATENDIDA" src tests` sin resultados; suite completa verde (1207 tests + los nuevos) y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/` (suite completa de CRM: `tests/test_crm_*.py`).

- [ ] **F2-T04 — Conectar la migración al arranque**
  - **Delegable a Gemini:** NO — arquitectura/seguridad: abre la base de datos real y decide el comportamiento ante fallo.
  - Requisitos: VCRM-171.
  - **Entregable exacto:** `src/jerico/crm/db.py` (si `schema_version = 1` → `migrate_v1_to_v2`; si es otra, error actual), `tests/test_crm_db.py` (adición), `tests/test_crm_migration.py` (arranque de `app` con base v1).
  - **Insumos:** `db.py`, `migrate.py`, `app.py`.
  - **Tests primero:** `test_vcrm171_abrir_base_v1_migra_y_conserva_datos`, `test_vcrm171_falla_migracion_deja_v1_y_no_arranca`.
  - **Hecho cuando:** ambos en verde, `test_crm_migration.py` completo verde y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_db.py tests/test_crm_migration.py tests/test_crm_app.py`.

## B. Dominio puro

- [ ] **F2-T05 — Franja, festivos y cupo semanal (`sendwindow.py`)**
  - **Delegable a Gemini:** NO — arquitectura/seguridad: implementa la Ley 2300 (J-11) y sus topes legales.
  - Requisitos: VCRM-072, 076, 100, 101.
  - **Entregable exacto:** `src/jerico/crm/sendwindow.py`, `tests/test_crm_sendwindow.py`.
  - **Insumos:** `plan-f2.md` §5.1; `timeutil.py`, `config.py` (`Params`, VCRM-162).
  - **Tests primero:** `test_vcrm072_franja_lv_sab_festivos` (07:00 incluido, 19:00 excluido; sábado 08–15; domingo y festivo cerrados; festivo extraordinario), `test_vcrm100_difiere_al_inicio_de_franja`, `test_vcrm076_un_contacto_por_semana` (lunes 00:00 a domingo 23:59 Bogotá), `test_vcrm101_excedente_a_semana_siguiente`, `test_vcrm072_utc_a_bogota_cambio_de_dia`.
  - **Hecho cuando:** tests verdes y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_sendwindow.py`.

- [x] **F2-T06 — Cadencias puras (`cadence.py`)**
  - **Delegable a Gemini:** SÍ.
  - Requisitos: VCRM-018, 022, 023, 026, 032, 034 (cálculo).
  - **Entregable exacto:** `src/jerico/crm/cadence.py` (matriz por defecto de plan-f2 §5.2, `row_for(reason)`, `first_action(now, interval)`, `after_step(...)`, `frequency_days("weekly"|"monthly")`), `tests/test_crm_cadence.py` (parte pura).
  - **Insumos:** `plan-f2.md` §5.2; `spec.md` VCRM-018..026 y §4.6; `leads.py` (`REJECT_REASONS`).
  - **Tests primero:** `test_vcrm018_matriz_por_motivo`, `test_vcrm022_reanudar_desde_ahora`, `test_vcrm023_frecuencia_desde_ultimo_envio`, `test_vcrm023_sin_envio_desde_cambio`, `test_vcrm026_ultimo_paso_completa`, `test_vcrm032_cancelar_salta_paso`.
  - **Prohibiciones:** PROH; sin E/S, sin `datetime.now()` (parámetro `now`).
  - **Hecho cuando:** verde y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_cadence.py`.

- [ ] **F2-T07 — Texto nuevo, palabra «BAJA» y token de baja (`inbound.py`)**
  - **Delegable a Gemini:** NO — arquitectura/seguridad: decide bajas legales (J-06) y firma el token.
  - Requisitos: VCRM-102, 120, 124 (parte pura), definiciones 4.5.
  - **Entregable exacto:** `src/jerico/crm/inbound.py` (`extract_new_text`, `has_stop_keyword`, `make_unsub_token`, `verify_unsub_token`), `tests/test_crm_inbound.py` (parte pura).
  - **Insumos:** `plan-f2.md` §5.7, D-5; spec 4.5 «Palabra clave presente» y «Texto nuevo»; `fingerprint.py`.
  - **Tests primero:** `test_vcrm102_palabra_completa_sin_tildes` («baja», «Baja.», «BAJA»; no «trabajamos», «bajamos»), `test_vcrm102_cita_no_cuenta`, `test_vcrm102_falso_positivo_temporada_baja_aceptado`, `test_vcrm124_token_valido_e_invalido`, `test_vcrm124_token_manipulado`, extracción con citas `>`, «El … escribió:» y «On … wrote:».
  - **Hecho cuando:** verde y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_inbound.py`.

- [ ] **F2-T08 — Textos de seguimiento y pie legal (`followup_text.py`)**
  - **Delegable a Gemini:** SÍ.
  - Requisitos: VCRM-027 (texto), 069, 148, 161.
  - **Entregable exacto:** `src/jerico/crm/followup_text.py` (carga TOML con `tomllib`, `lookup(reason, step) -> str | None`, `footer(sender_name)`, `auth_request_body(notice_ref, version, processors)`), `tests/test_crm_followup.py` (parte de textos).
  - **Insumos:** `plan-f2.md` §5.3, §5.5, §5.6, §6; spec VCRM-069, 148.
  - **Tests primero:** `test_vcrm161_sin_texto_devuelve_none`, `test_vcrm069_pie_con_baja_sin_enlaces` (ninguna cadena `http`), `test_vcrm148_incluye_aviso_y_encargados`, TOML inválido → `None` y sin traza con contenido.
  - **Prohibiciones:** PROH; no redactar textos comerciales reales (los aporta el CTO); fixtures con textos de prueba.
  - **Hecho cuando:** verde y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_followup.py`.

## C. Configuración, datos y guarda

- [ ] **F2-T09 — Configuración F2 con secretos**
  - **Delegable a Gemini:** NO — arquitectura/seguridad: toca credenciales IMAP.
  - Requisitos: VCRM-148, 149, 169, 170 (parámetros).
  - **Entregable exacto:** `src/jerico/crm/config.py` (campos de plan-f2 §6; `imap_password` `SecretStr`; `f2_enabled(settings)`), `tests/test_crm_config.py` (adición).
  - **Insumos:** `plan-f2.md` §6; `config.py`; `app.py`.
  - **Tests primero:** `test_vcrm170_repr_no_expone_password`, `test_vcrm149_sin_aviso_deshabilita`, `test_vcrm169_periodo_minimo_1`, valores por defecto.
  - **Hecho cuando:** verde y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_config.py`.

- [ ] **F2-T10 — Tablas F2 y consultas (`db.py`, `repo.py`)**
  - **Delegable a Gemini:** SÍ (el esquema está fijado en plan-f2 §3; revisión del coordinador de las restricciones únicas).
  - Requisitos: VCRM-028, 160, 169 (persistencia).
  - **Entregable exacto:** `src/jerico/crm/db.py` (DDL de `crm_cadences`, `crm_proposals`, `crm_proposal_versions`, `crm_sends`, `crm_inbound`, índices únicos; `inbound_id` en `crm_titular_requests`), `src/jerico/crm/repo.py` (funciones de inserción/consulta/actualización), `src/jerico/crm/model.py` (enums y dataclasses `Cadence`, `Proposal`, `ProposalVersion`, `Send`, `Inbound`), `tests/test_crm_db.py` (adición).
  - **Insumos:** `plan-f2.md` §3; `db.py`, `repo.py`, `model.py`; `migrate.py` (debe crear las mismas tablas: añadir al DDL compartido, no duplicar).
  - **Tests primero:** `test_vcrm028_unica_propuesta_por_lead_y_paso`, `test_vcrm169_unico_message_id`, `test_vcrm028_una_solicitud_de_autorizacion_abierta`, ida y vuelta de cada tabla, `foreign_key_check`.
  - **Hecho cuando:** verde, migración (`test_crm_migration.py`) sigue verde y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_db.py tests/test_crm_migration.py`.

- [ ] **F2-T11 — Guarda de contacto exige autorización (Q-4)**
  - **Delegable a Gemini:** NO — arquitectura/seguridad: consentimiento (Ley 1581).
  - Requisitos: VCRM-067, 071.
  - **Entregable exacto:** `src/jerico/crm/compliance.py` (`may_contact_commercially` exige `auth_status == authorized`; `may_request_authorization`), `tests/test_crm_consent.py` y `tests/test_crm_suppression.py` (ajustes), `tests/test_crm_followup.py` (adición).
  - **Insumos:** `plan-f2.md` §5.8; `compliance.py` líneas 228–236; `tests/test_crm_consent.py` (casos 459–499).
  - **Tests primero:** `test_vcrm067_guarda_exige_autorizacion`, `test_vcrm067_revocada_niega`, `test_vcrm067_solicitud_no_exige_autorizacion`, `test_vcrm071_suprimido_sigue_negando`.
  - **Hecho cuando:** verde y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_consent.py tests/test_crm_suppression.py tests/test_crm_followup.py`.

## D. Servicios

- [ ] **F2-T12 — Servicio de cadencias (alta, pausa, reanudación, frecuencia, reactivación)**
  - **Delegable a Gemini:** SÍ.
  - Requisitos: VCRM-018, 019, 020, 021, 022, 023, 024, 026, 121.
  - **Entregable exacto:** `src/jerico/crm/followup.py` (parte de cadencias: `start_cadence`, `pause`, `resume`, `set_frequency`, `reactivate`, `on_step_consumed`), gancho en `leads.py` (rechazo → cadencia o aviso; autorización de un `rejected` → cadencia), `states.py` (`CURRENT_PHASE` no cambia aún: usar `phase=2` en pruebas), `tests/test_crm_cadence.py` (parte de servicio).
  - **Insumos:** `plan-f2.md` §5.2; `leads.py` (transiciones y `REJECT_REASONS`), `states.py`, `repo.py` (T10), `cadence.py`, `compliance.py`.
  - **Tests primero:** `test_vcrm018_rechazo_con_autorizacion_crea_cadencia`, `test_vcrm019_rechazo_sin_autorizacion_avisa`, `test_vcrm020_pausar_cancela_pendientes`, `test_vcrm021_pausado_no_genera`, `test_vcrm022_reanudar_sin_omitidas`, `test_vcrm023_frecuencia_semanal_mensual`, `test_vcrm024_reactivado_detiene`, `test_vcrm026_ultimo_paso_avisa_sin_perder`, `test_vcrm121_autorizar_rechazado_crea_cadencia`.
  - **Hecho cuando:** verde y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_cadence.py tests/test_crm_transitions.py`.

- [ ] **F2-T13 — Generación de propuestas (sin envío)**
  - **Delegable a Gemini:** SÍ (con revisión del coordinador).
  - Requisitos: VCRM-027, 028, 039, 067, 161.
  - **Entregable exacto:** `src/jerico/crm/followup.py` (`generate_due(conn, now, ...) -> list[Outgoing]`), `tests/test_crm_followup.py`.
  - **Insumos:** `plan-f2.md` §5.3 (primer bloque); `followup_text.py`, `cadence.py`, `repo.py`, `compliance.may_contact_commercially`.
  - **Tests primero:** `test_vcrm027_genera_propuesta_al_vencer` (aprobador = comercial del lead o CTO si no tiene), `test_vcrm028_barrido_repetido_no_duplica`, `test_vcrm028_reinicio_no_duplica`, `test_vcrm161_sin_texto_no_avanza_y_avisa_una_vez`, `test_vcrm039_sin_correo_avisa`, `test_vcrm067_sin_autorizacion_no_genera`.
  - **Prohibiciones:** PROH; esta tarea no envía correo.
  - **Hecho cuando:** verde y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_followup.py`.

- [ ] **F2-T14 — Gate ✅/❌: aprobar, rechazar, cancelar, reescribir, expirar**
  - **Delegable a Gemini:** NO — arquitectura/seguridad: gate P-09 (OBJ-2).
  - Requisitos: VCRM-029 (hasta programar), 030, 031, 032, 033, 034, 035, 036, 099.
  - **Entregable exacto:** `src/jerico/crm/followup.py` (`approve`, `reject`, `cancel`, `start_rewrite`, `submit_rewrite`, `expire_due`), `tests/test_crm_gate.py`.
  - **Insumos:** `plan-f2.md` §5.3, D-6, D-7, D-8; `permissions.py`, `repo.py` (`crm_pending_inputs`, audit), `bot.py` (patrón `register_confirmation`).
  - **Tests primero:** `test_vcrm030_doble_pulsacion`, `test_vcrm031_rechazo_ofrece_opciones`, `test_vcrm032_cancelar_salta_paso`, `test_vcrm033_reescribir_nueva_version_reinicia_plazo`, `test_vcrm099_aprobar_version_obsoleta`, `test_vcrm034_expira_a_las_48h`, `test_vcrm034_aprobar_tras_expirar`, `test_vcrm035_no_aprobador_audita`, `test_vcrm036_acuse_requiere_aprobacion`, `test_vcrm036_hash_aprobado_se_guarda`.
  - **Hecho cuando:** verde y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_gate.py`.

- [ ] **F2-T15 — Programación y entrega con guardas y reintentos**
  - **Delegable a Gemini:** NO — arquitectura/seguridad: último control antes de contactar al titular (Ley 2300, supresión).
  - Requisitos: VCRM-029, 036, 037, 038, 072, 076, 100, 101.
  - **Entregable exacto:** `src/jerico/crm/followup.py` (`guard`, `schedule_send`, `deliver_due`), `tests/test_crm_gate.py` (adición).
  - **Insumos:** `plan-f2.md` §5.3 (`guard`), §5.4; `sendwindow.py`, `outbox.next_attempt_at`, `compliance.py`, `ports.EmailSender`.
  - **Tests primero:** `test_vcrm029_aprobar_envia_y_programa_siguiente`, `test_vcrm037_estado_cambia_cancela_por_estado`, `test_vcrm037_solicitud_solo_suprimido`, `test_vcrm036_hash_distinto_falla_cerrado`, `test_vcrm038_tres_intentos_0_1_5`, `test_vcrm038_sin_intentos_fuera_de_franja`, `test_vcrm038_fallido_no_avanza_y_reintentar_cancelar`, `test_vcrm100_aprobar_fuera_de_franja_difiere_e_informa`, `test_vcrm101_excedente_semanal_difiere`, `test_vcrm037_guarda_se_reevalua_en_cada_intento`.
  - **Hecho cuando:** verde y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_gate.py tests/test_crm_sendwindow.py`.

- [ ] **F2-T16 — Cabeceras de baja en el adaptador SMTP**
  - **Delegable a Gemini:** NO — arquitectura/seguridad: el archivo maneja credenciales SMTP.
  - Requisitos: VCRM-123, 069.
  - **Entregable exacto:** `src/jerico/crm/ports.py` (`EmailSender.send(..., headers=None)`), `src/jerico/crm/mail.py` (cabeceras opcionales; rechazo de CR/LF), `tests/crm_support.py` (`FakeEmailSender` captura cabeceras), `tests/test_crm_adapters.py` (adición).
  - **Insumos:** `plan-f2.md` §5.5; `mail.py`, `ports.py`.
  - **Tests primero:** `test_vcrm123_cabecera_list_unsubscribe_mailto`, `test_vcrm123_rechaza_crlf_en_cabeceras`, `test_vcrm069_llamadas_f1_sin_cabeceras_siguen_igual`.
  - **Hecho cuando:** verde, `tests/test_crm_outbox.py` sigue verde y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_adapters.py tests/test_crm_outbox.py`.

- [ ] **F2-T17 — Adaptador IMAP de solo lectura (`inbox.py`)**
  - **Delegable a Gemini:** NO — arquitectura/seguridad: credenciales, ingreso de contenido no confiable.
  - Requisitos: VCRM-169, 170.
  - **Entregable exacto:** `src/jerico/crm/ports.py` (`InboxPort`, `InboundMessage`), `src/jerico/crm/inbox.py` (`ImapInbox`, `UnconfiguredInbox`, `build_inbox`), `tests/crm_support.py` (`FakeInbox`), `tests/test_crm_inbox.py`.
  - **Insumos:** `plan-f2.md` D-4, §5.7; `mail.py` (patrón `Unconfigured*`/`build_*`).
  - **Tests primero:** con un servidor IMAP simulado (doble de `imaplib.IMAP4_SSL`): `test_vcrm169_lectura_solo_lectura_peek`, `test_vcrm169_uidvalidity_distinto_reinicia`, `test_vcrm169_tope_256kb_y_lote_50`, `test_vcrm169_mensaje_sin_message_id_usa_hash`, `test_vcrm169_sin_ruta_publica` (el módulo no abre sockets de escucha), `test_vcrm170_fallo_de_conexion_sin_secreto_en_error`, `test_vcrm169_html_se_reduce_a_texto`.
  - **Hecho cuando:** verde y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_inbox.py`.

- [ ] **F2-T18 — Procesamiento de respuestas entrantes**
  - **Delegable a Gemini:** NO — arquitectura/seguridad: aplica bajas y deriva autorizaciones.
  - Requisitos: VCRM-102, 103, 119, 120, 122, 124, 153, 169, 170.
  - **Entregable exacto:** `src/jerico/crm/inbound.py` (`associate`, `classify`, `poll_and_process`), `src/jerico/crm/compliance.py` (reuso de la baja de F1 con medios «respuesta al correo», «cabecera de baja del correo» y «respuesta al correo confirmada por un usuario»), `tests/test_crm_inbound.py` (parte de servicio).
  - **Insumos:** `plan-f2.md` §5.7; `inbound.py` (T07), `inbox.py` (T17), `compliance.py` (baja, VCRM-070; solicitudes de titulares), `repo.py`.
  - **Tests primero:** `test_vcrm102_baja_por_respuesta_inmediata`, `test_vcrm120_baja_en_respuesta_a_solicitud_no_propone_autorizacion`, `test_vcrm103_respuesta_a_revision_del_comercial`, `test_vcrm122_no_asociable_al_cto`, `test_vcrm122_varios_leads_por_huella_no_asociable`, `test_vcrm124_cabecera_aplica_baja_sin_palabra_clave`, `test_vcrm124_token_invalido_es_no_asociable`, `test_vcrm153_botones_y_fecha_limite_15_dias_habiles`, `test_vcrm169_mensaje_una_sola_vez`, `test_vcrm170_fallo_avisa_una_vez_y_recupera_sin_perder`, `test_vcrm102_sin_acuse_al_titular`.
  - **Hecho cuando:** verde y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_inbound.py tests/test_crm_suppression.py`.

- [ ] **F2-T19 — Solicitud de autorización (`authreq.py`)**
  - **Delegable a Gemini:** NO — arquitectura/seguridad: consentimiento y texto legal.
  - Requisitos: VCRM-068, 148, 149.
  - **Entregable exacto:** `src/jerico/crm/authreq.py` (`request_authorization`), `tests/test_crm_authreq.py`.
  - **Insumos:** `plan-f2.md` §5.6; `followup_text.py`, `followup.py` (gate), `config.py`, `permissions.py`.
  - **Tests primero:** `test_vcrm068_solicitud_pasa_por_gate_y_solo_sale_tras_ok`, `test_vcrm148_incluye_aviso_version_y_encargados`, `test_vcrm149_sin_aviso_no_prepara_y_responde`, `test_vcrm068_lead_suprimido_no_prepara`, `test_vcrm068_cuenta_en_cupo_semanal`.
  - **Hecho cuando:** verde y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_authreq.py`.

- [ ] **F2-T20 — Confirmación ✅/❌ de la respuesta como autorización**
  - **Delegable a Gemini:** NO — arquitectura/seguridad: registra autorización (decisión N-04).
  - Requisitos: VCRM-119, 141, 142, 143, 121.
  - **Entregable exacto:** `src/jerico/crm/authreq.py` (`propose_authorization`, `confirm`, `decline`), `src/jerico/crm/compliance.py` (registro con medio «respuesta al correo confirmada por el comercial», versión del aviso, finalidades y referencia al mensaje), `tests/test_crm_authreq.py` (adición).
  - **Insumos:** `plan-f2.md` §5.6; `compliance.py` (VCRM-138/139, `insert_consent`), `inbound.py`.
  - **Tests primero:** `test_vcrm119_propone_sin_registrar`, `test_vcrm141_confirma_registra_con_evidencia`, `test_vcrm141_rechazada_solo_por_comercial_del_lead`, `test_vcrm142_rechaza_no_registra_y_deja_historial`, `test_vcrm143_doble_pulsacion`, `test_vcrm121_confirmar_en_rejected_inicia_cadencia`.
  - **Hecho cuando:** verde y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_authreq.py tests/test_crm_consent.py`.

## E. Bot, vista y barrido

- [ ] **F2-T21 — Callbacks del gate y de autorización en el bot**
  - **Delegable a Gemini:** NO — arquitectura/seguridad: cablea el gate a la interfaz.
  - Requisitos: VCRM-027, 029, 030, 031, 032, 033, 099, 141, 142, 143.
  - **Entregable exacto:** `src/jerico/crm/bot.py` (callbacks `v1:pok|pno|pcancel|prewrite|pretry|pabort|aok|ano:<id>[:<ver>]`, registro de `pending` `rewrite`; ≤ 64 bytes), `src/jerico/crm/render.py` (textos), `tests/test_crm_f2_bot.py`.
  - **Insumos:** `plan-f2.md` §5.3, §5.6; `bot.py` (`register_callback`, `register_pending`), `parsing.build_callback`.
  - **Tests primero:** `test_vcrm029_boton_ok_envia`, `test_vcrm030_boton_doble`, `test_vcrm033_texto_de_reescritura_crea_version`, `test_vcrm099_boton_version_vieja`, `test_vcrm141_boton_ok_autorizacion`, callbacks ≤ 64 bytes, chat no individual rechazado.
  - **Hecho cuando:** verde y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_f2_bot.py tests/test_crm_bot.py`.

- [ ] **F2-T22 — Vista `/seguimiento`**
  - **Delegable a Gemini:** SÍ.
  - Requisitos: VCRM-025.
  - **Entregable exacto:** `src/jerico/crm/bot.py` (comando), `src/jerico/crm/render.py`, `tests/test_crm_f2_bot.py` (adición).
  - **Insumos:** `plan-f2.md` §5.9; `spec.md` VCRM-025 y 4.4; `bot.py` (`/lista`), `permissions.py`, `repo.py`.
  - **Tests primero:** `test_vcrm025_vista_seguimiento_visibilidad` (comercial solo los suyos; CTO todos; abogado negado), `test_vcrm025_incluye_motivo_frecuencia_proxima_y_envios`, vacío.
  - **Prohibiciones:** PROH; no mostrar leads suprimidos con campos vacíos (ver F2-T27).
  - **Hecho cuando:** verde y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_f2_bot.py`.

- [ ] **F2-T23 — Botones de cadencia en la ficha (pausar, reanudar, frecuencia, reactivar, perdido)**
  - **Delegable a Gemini:** SÍ.
  - Requisitos: VCRM-020, 022, 023, 024, 026.
  - **Entregable exacto:** `src/jerico/crm/bot.py`, `src/jerico/crm/render.py`, `tests/test_crm_f2_bot.py` (adición).
  - **Insumos:** `plan-f2.md` §5.9; `followup.py` (T12), `leads.py` (`STATE_OPS`), `permissions.py`.
  - **Tests primero:** `test_vcrm020_boton_pausar`, `test_vcrm022_boton_reanudar`, `test_vcrm023_boton_frecuencia`, `test_vcrm024_boton_reactivar`, `test_vcrm026_botones_marcar_perdido_y_reactivar`, permisos denegados auditados.
  - **Hecho cuando:** verde y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_f2_bot.py tests/test_crm_views.py`.

- [ ] **F2-T24 — Comando `/autorizacion`**
  - **Delegable a Gemini:** NO — arquitectura/seguridad: dispara contacto legal al titular.
  - Requisitos: VCRM-068, 149.
  - **Entregable exacto:** `src/jerico/crm/bot.py` (comando `/autorizacion L-NNNN`), `tests/test_crm_f2_bot.py` (adición).
  - **Insumos:** `authreq.py` (T19), `bot.py`, `permissions.py`.
  - **Tests primero:** `test_vcrm068_comando_crea_propuesta`, `test_vcrm149_comando_sin_configuracion_informa`, `test_vcrm068_comercial_ajeno_denegado`.
  - **Hecho cuando:** verde y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_f2_bot.py`.

- [ ] **F2-T25 — Barrido único y registro del job (`sweep.py`, `jobs.py`)**
  - **Delegable a Gemini:** NO — arquitectura/seguridad: orquesta envíos, lectura de buzón y activación.
  - Requisitos: VCRM-028, 034, 038, 160, 169, 170.
  - **Entregable exacto:** `src/jerico/crm/sweep.py` (`followup_sweep(...)`: activación F2 una vez, `poll`, `expire_due`, `generate_due`, `deliver_due`, cada paso aislado), `src/jerico/crm/jobs.py` (`FOLLOWUP_JOB = "crm-followup"`, `FOLLOWUP_CRON = "* * * * *"`, `register_jobs(..., followup=...)` con parámetro opcional para no romper F1), `tests/test_crm_sweep.py`, `tests/test_crm_app.py` (adición).
  - **Insumos:** `plan-f2.md` D-1, D-2, D-9, §5.2 (activación); `jobs.py`, `retention.daily_sweep` (patrón), `src/jerico/cron/scheduler.py` (solo lectura).
  - **Tests primero:** `test_vcrm160_activacion_desde_ahora_una_sola_vez`, `test_vcrm028_barrido_repetido_idempotente`, `test_vcrm169_periodo_de_consulta_respetado`, `test_vcrm170_fallo_de_un_paso_no_detiene_los_otros`, `test_vcrm038_reintento_al_minuto`, job registrado en UTC con 1 reintento, F2 deshabilitada si falta configuración (D-9) con aviso único al CTO.
  - **Hecho cuando:** verde y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_sweep.py tests/test_crm_app.py`.

- [ ] **F2-T26 — Activar la fase 2 en el arranque**
  - **Delegable a Gemini:** NO — arquitectura/seguridad: activa el comportamiento F2 y construye adaptadores con secretos.
  - Requisitos: VCRM-160, 171 (activación).
  - **Entregable exacto:** `src/jerico/crm/__init__.py` (`CURRENT_PHASE = 2`), `src/jerico/crm/app.py` (construye `build_inbox`, registra el barrido, ejecuta el barrido una vez al arrancar), `tests/test_crm_states.py` y `tests/test_crm_app.py` (ajustes de fase).
  - **Insumos:** `plan-f2.md` D-9; `app.py`, `states.py`, `mail.py` (`build_email_sender`).
  - **Tests primero:** `test_vcrm160_arranque_registra_job_y_activa`, `test_vcrm171_arranque_con_base_v1_migra_y_opera`, transiciones de fila F2 habilitadas con `CURRENT_PHASE = 2`, arranque sin configuración IMAP no falla y deja F2 deshabilitada.
  - **Hecho cuando:** verde y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_app.py tests/test_crm_states.py tests/test_crm_transitions.py`.

## F. Observaciones de la auditoría F1 y cierre

- [ ] **F2-T27 — Lead suprimido fuera de `/lista` (observación d)**
  - **Delegable a Gemini:** SÍ.
  - Requisitos: VCRM-073 (coherencia visible), 025.
  - **Entregable exacto:** `src/jerico/crm/leads.py` (o `repo.py`, donde se arma `/lista`), `tests/test_crm_views.py`.
  - **Insumos:** `leads.py` (listado), `compliance.py` (`suppressed_at`); `tests/test_crm_views.py`.
  - **Tests primero:** `test_vcrm073_lead_suprimido_no_aparece_en_lista`.
  - **Hecho cuando:** verde y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_views.py tests/test_crm_suppression.py`.

- [ ] **F2-T28 — Prefijo `vcrm151` en tests de escalado (observación c)**
  - **Delegable a Gemini:** SÍ.
  - Requisitos: VCRM-151 (trazabilidad).
  - **Entregable exacto:** `tests/test_crm_escalation.py` (solo renombrar funciones de test a `test_vcrm151_...`).
  - **Insumos:** `tests/test_crm_escalation.py`.
  - **Tests primero:** `pytest --collect-only -q tests/test_crm_escalation.py | grep -c vcrm151` debe ser igual al total de tests del archivo.
  - **Hecho cuando:** conteo igual y VERIF; el diff solo contiene renombres.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_escalation.py`.

- [ ] **F2-T29 — Prueba de aceptación F2 de punta a punta**
  - **Delegable a Gemini:** SÍ (solo tests; el coordinador revisa que no contradigan el gate).
  - Requisitos: VCRM-018, 027, 029, 038, 102, 119, 141, 160 (flujo integrado).
  - **Entregable exacto:** `tests/test_crm_f2_acceptance.py`.
  - **Insumos:** `plan-f2.md` §7; `tests/test_crm_acceptance.py` (estilo F1), `tests/crm_support.py`.
  - **Tests primero:** `test_vcrm018_flujo_rechazo_a_primer_envio`, `test_vcrm141_flujo_solicitud_respuesta_confirmacion_cadencia`, `test_vcrm102_flujo_baja_cancela_pendientes`, `test_vcrm036_nada_sale_sin_aprobacion` (ningún `send` sin ✅ en todo el recorrido).
  - **Hecho cuando:** verde sin tocar `src/` y VERIF.
  - **Verificación:** VERIF con `<TESTS>` = `tests/test_crm_f2_acceptance.py`.

- [ ] **F2-T30 — Verificación integral F2**
  - **Delegable a Gemini:** NO — arquitectura/seguridad: cierre y evidencia para el gate de validación (la ejecuta el coordinador).
  - Requisitos: los 49 [F2] (trazabilidad) y OBJ-2, OBJ-3, OBJ-5.
  - **Entregable exacto:** ninguno nuevo; reporte con salida de comandos.
  - **Insumos:** `plan-f2.md` §7 (matriz).
  - **Hecho cuando:** (1) `./scripts/verify.sh` verde; (2) cobertura ≥ 89 % global y `pytest --cov=src/jerico/crm --cov-fail-under=89` verde para el paquete `crm`; (3) para cada VCRM de F2 existe al menos un test con `vcrmNNN` en su nombre (`grep -rhoE "def test_vcrm[0-9]{3}" tests | sort -u` cubre los 49 identificadores); (4) `git status` solo muestra archivos del contrato y ningún cambio en `docker-compose.yml`, `Dockerfile`, `.env*`, `docs/architecture/`, `scripts/oci/`; (5) los «Cambios propuestos fuera del alcance» de `plan-f2.md` §8 se entregan al humano.
  - **Verificación:** `./scripts/verify.sh` y `PYTHONPATH=src .venv/bin/python -m pytest tests -q --cov=src/jerico/crm --cov-report=term-missing --cov-fail-under=89`.

> Última modificación: 11/10/2026 17:53 (Planificador SDD)
