# Plan — Spec 004 (cierre → abogado → contrato → firma; correo por niveles; rol abogado)

Borrador. Implementación bloqueada hasta el OK del CTO. Todo aditivo sobre el paquete `src/jerico/crm/`.

## 1. Entrega por fases (cada una desplegable y reversible por separado)
| Fase | Contenido | Req. | Depende de |
|---|---|---|---|
| **C1** Paquete + abogado | Oferta, paquete versionado, confirmación ✅/❌, entrega a abogado (Telegram/correo), `/casos`, `/paquete`, bitácora | C01-C05, C20-C23, R01, R04-R06, P01-P03, P05 | decisiones D-C1, D-C2, D-P1 |
| **C2** Contrato + firma | Subida del contrato, devolución, aprobación y envío a firma, `SignaturePort`, evidencia, vencimiento | C10-C15, F01-F03, F10, R02-R03 | C1 + decisión D-F1 |
| **C3** Buzones por niveles | Buzones por comercial, visibilidad, candidatos de lead, avisos | M01-M09, P04, P07 | decisión D-M1 y credenciales reales |

C3 es independiente de C1/C2 y puede ir en paralelo con otra rama.

## 2. Modelo de datos (migración v2→v3, con la misma disciplina que v1→v2: copia `crm.db.pre-v3.bak`, transaccional, `migrate_if_needed`)
- `crm_offers(id, lead_id, version, currency, payment_terms, valid_until, special_conditions, created_by, created_at)` y `crm_offer_lines(offer_id, position, description, quantity, unit_price)`. Importes como entero en la unidad menor y moneda ISO.
- `crm_packages(id, lead_id, version, offer_id, content_hash, status[draft|confirmed|sent|superseded|cancelled], legal_basis[code], confirmed_by, sent_at)`; índice único: un paquete vivo por lead.
- `crm_contracts(id, package_id, status[…§5.1], file_path, sha256, uploaded_by, approved_by, special_form, expires_at, signed_at)`.
- `crm_signatures(id, contract_id, provider, external_id, status, evidence_path, evidence_sha256, created_at, updated_at)`: sin PII en claro más allá de lo que ya vive en el lead.
- `crm_mailboxes(id, user_id, address, secret_env_name, active, last_ok_at)`; `crm_mail_candidates(id, mailbox_id, sender_fp, subject_trunc, received_at, message_id, status, expires_at)` (el remitente se guarda con la huella HMAC existente y, solo si el comercial registra el lead, en claro en el lead).
- `AuditAction` nuevas (la columna no tiene `CHECK`): `package_*`, `contract_*`, `signature_*`, `mailbox_*`.

## 3. Módulos
| Módulo | Responsabilidad |
|---|---|
| `offer.py`, `package.py` | Validación de oferta y armado del paquete (puro), versionado, hash |
| `package_render.py` | Texto/PDF del paquete sin datos de más (PDF solo si no exige dependencia nueva de pago; si no, texto + Markdown) |
| `closing_bot.py` | Comandos y botones del comercial (`/cierre L-n`, edición de oferta) por los puntos de extensión del bot |
| `lawyer_bot.py` | `/casos`, `/paquete`, `/subircontrato`, `/devolver`, `/formaespecial` |
| `contract.py` | Máquina de estados del contrato, comprobación de hash, vencimientos (job del barrido de F2) |
| `signature.py` | `SignaturePort`, adaptador de la fase 1 elegida, evidencia |
| `mailboxes.py`, `mail_levels.py` | Configuración de buzones, visibilidad por rol, candidatos |
| `permissions.py` | Acciones nuevas en la matriz (filas para abogado/comercial/CTO) |

## 4. Reglas de diseño
- Todo lo que sale al cliente (envío a firma, primer correo al candidato) pasa por `gate.py`; el paquete y el contrato al abogado también por ✅ del comercial/CTO (datos personales hacia un tercero).
- Ni IA ni plantilla escriben el texto jurídico (C13). El asistente LLM no recibe paquetes ni contratos (P01).
- Sin dependencia de pago: la fase 1 de firma usa lo que la comparativa marque como gratis; el puerto permite cambiar sin tocar el CRM.
- Secretos de buzones y de firma solo en `.env`; `CrmSettings` carga los nombres, nunca los valores en la base.
- Los trabajos de red van tras el *commit* (patrón `bot.defer` del asistente).

## 5. Pruebas
TDD por tarea; dobles para IMAP/SMTP/firma/Telegram; pruebas negativas obligatorias (aislamiento de buzones, abogado sin acceso fuera de sus casos, no envío sin ✅, hash distinto → rechazo, lead suprimido → rechazo). Aceptación E2E por fase con proveedor de firma simulado. Cobertura del código nuevo ≥99 %.

## 6. Riesgos
1. **Forma de firma**: un contrato que exija forma especial no puede cerrarse en línea → C03 detiene el flujo.
2. **Base legal y encargados** sin definir por el abogado: bloquea activar C1 con datos reales.
3. **Buzones**: credenciales y verificación de Google no confirmadas (D-M1).
4. **Migración v3 en producción** con servicio detenido y copia previa.
5. **Telegram** como canal de documentos con datos personales (C23).
6. Tamaño: C3 es la fase más larga por IMAP multi-buzón.

## 7. Estimación orientativa (sin verificar)
C1 ≈ 12 tareas, C2 ≈ 12, C3 ≈ 14 (ver `tasks.md`).
