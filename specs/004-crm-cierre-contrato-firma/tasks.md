# Tareas — Spec 004 (borrador; TDD rojo→verde en cada una; implementación tras OK del CTO)

Leyenda de responsable: **D** director (seguridad, arquitectura, datos personales), **G** Gemini con contrato y verificación del director.

## Fase C1 — Paquete + abogado
| # | Tarea | Req. | Resp. |
|---|---|---|---|
| C1-01 | Migración v2→v3: tablas `crm_offers`, `crm_offer_lines`, `crm_packages`; copia previa; prueba con base real de F1/F2 | P05 | D |
| C1-02 | `offer.py`: validación de líneas, moneda, importes enteros | C02 | G |
| C1-03 | `package.py`: armado, versionado, hash, completitud (handoff + oferta) | C01,C02,C04 | D |
| C1-04 | Repositorio de paquetes y ofertas (`repo`) | C04 | G |
| C1-05 | Permisos: acciones `PACKAGE_*` en la matriz (abogado limitado) | R04,R06 | D |
| C1-06 | `closing_bot.py`: `/cierre L-n`, captura guiada de oferta, edición | C01,C03 | G |
| C1-07 | Confirmación ✅/❌ del paquete por el gate | C03 | D |
| C1-08 | `package_render.py` y entrega a abogado por Telegram y correo, nombre neutro | C20-C22 | G |
| C1-09 | `lawyer_bot.py`: `/casos`, `/paquete` | R01,R02 | G |
| C1-10 | Base legal y bloqueos: paquete solo con autorización vigente o `legal_basis` | P03 | D |
| C1-11 | Bitácora de paquete (acciones nuevas) y pruebas de no-fuga a logs | C05,P07 | D |
| C1-12 | Aceptación E2E C1 y documentación | todos | G |

## Fase C2 — Contrato + firma
| # | Tarea | Req. | Resp. |
|---|---|---|---|
| C2-01 | Migración: `crm_contracts`, `crm_signatures` | — | D |
| C2-02 | `contract.py`: estados, transiciones, vencimiento (job) | C10-C14 | D |
| C2-03 | Subida de contrato por el abogado (`/subircontrato`), hash, almacenamiento 600 | C10,R02 | G |
| C2-04 | `/devolver` con motivo; reapertura del paquete | C11 | G |
| C2-05 | `/formaespecial` y detención del flujo | F03,R03 | G |
| C2-06 | Gate de envío a firma: verificación de hash y de `may_contact_commercially` | C12,C13 | D |
| C2-07 | `SignaturePort` + doble de pruebas | F01 | D |
| C2-08 | Adaptador de la fase 1 (según D-F1; sin contratar nada) | F02 | D |
| C2-09 | Recepción de resultado de firma, evidencia y archivo | F10,C15 | D |
| C2-10 | Avisos a comercial/CTO/abogado y propuesta de «ganado» | C15 | G |
| C2-11 | Pruebas negativas (hash distinto, lead suprimido, abogado sin acceso) | todos | G |
| C2-12 | Aceptación E2E C2 con firma simulada | todos | G |

## Fase C3 — Buzones por niveles
| # | Tarea | Req. | Resp. |
|---|---|---|---|
| C3-01 | Migración: `crm_mailboxes`, `crm_mail_candidates` | — | D |
| C3-02 | Carga de buzones desde `.env` (nombre de variable, nunca valor) | M01,P07 | D |
| C3-03 | IMAP multi-buzón de solo lectura (reusa `inbox.py`) | M01 | D |
| C3-04 | SMTP saliente desde el buzón del comercial | M01 | G |
| C3-05 | Visibilidad: comercial su buzón, CTO todos, abogado ninguno; prueba negativa | M02 | D |
| C3-06 | Metadatos mínimos y retención de candidatos (job) | M03,M05 | D |
| C3-07 | Detección de remitentes desconocidos → candidato | M04 | G |
| C3-08 | Botones ✅ Registrar / ❌ Descartar; alta del lead por el flujo F1/F2 | M04,M06 | G |
| C3-09 | Primer correo con aviso de privacidad por el gate | M06 | D |
| C3-10 | Reasignación y buzón de origen | M07 | G |
| C3-11 | Avisos diarios de buzón | M09 | G |
| C3-12 | Comandos `/buzon`, `/buzones` (CTO) | M02 | G |
| C3-13 | Pruebas de seguridad (aislamiento, secretos fuera de logs) | M02,P07 | D |
| C3-14 | Aceptación E2E C3 con IMAP/SMTP falsos | todos | G |
