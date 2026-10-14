# Spec Hija A5 — Interfaz Gráfica PWA de Jericó (F4)

- **Estado:** IMPLEMENTACIÓN TDD (14/10/2026). Rama `impl/005-asistente-hermes`.
- **Insumos:** `specs/005-asistente-hermes/spec.md` (§3 Fase A5, §4 R10), `specs/001-ventas-crm/spec-asistente.md`, `DECISIONES_CTO.md` (D5 Gateway Omnicanal).
- **Reglas del Proyecto:** Mismo API FastAPI (`src/jerico/api.py`), mismo gateway omnicanal (`OmniGateway`), mismos roles y control de acceso del CRM, trazabilidad y auditoría idéntica a Telegram, sin nuevos servicios de pago en la nube.

---

## 1. Problema y Objetivos

Jericó opera actualmente con interfaz primaria en Telegram (`@Jericoo_bot`). Para habilitar una experiencia comercial completa desde navegadores de escritorio y dispositivos móviles sin depender de aplicaciones de terceros, se especifica e implementa la **PWA (Progressive Web App)** de Jericó.

La PWA no introduce un backend separado ni reescribe la lógica de negocio; es un cliente web ligero servido directamente por FastAPI que consume el mismo núcleo del CRM y el asistente con cuatro pantallas mínimas:
1. **Chat:** Consulta al asistente con presupuesto diario, redactor de datos personales y memoria persistente.
2. **Leads:** Lista de prospectos visibles con aislamiento estricto por rol (comercial solo sus asignados; CTO todos).
3. **Aprobaciones:** Cola HITL (Human-in-the-Loop) para propuestas de seguimiento pendientes (mismo gate ✅/❌).
4. **Consumo:** Visualización de tokens consumidos hoy, cupo restante y llamadas del usuario.

---

## 2. Requisitos EARS

- **A5-R1** La PWA SHALL proveer un manifiesto Web App Manifest estándar en `/manifest.json` con `display: standalone` y un Service Worker en `/sw.js` para caché del shell.
- **A5-R2** La API web SHALL requerir autenticación mediante header `X-User-ID` y `Authorization: Bearer <token>`, validando que el usuario exista y se encuentre activo (`active=1`).
- **A5-R3** WHEN un usuario no autenticado o inactivo acceda a la API web, el sistema SHALL responder HTTP 401 o 403 respectivamente.
- **A5-R4** El endpoint `/api/v1/web/chat` SHALL ejecutar consultas a través del asistente comercial con seudonimización (`Redactor`), deducción de presupuesto diario (`AssistantBudget`) y persistencia aislada en `AssistantMemory`.
- **A5-R5** El endpoint `/api/v1/web/leads` SHALL retornar exclusivamente los leads que el rol del usuario tiene permitido ver (`leads.visible_leads`), garantizando aislamiento entre comerciales.
- **A5-R6** El endpoint `/api/v1/web/approvals` SHALL listar las propuestas de seguimiento pendientes que el usuario puede aprobar o rechazar (`gate.may_decide`).
- **A5-R7** WHEN un usuario apruebe o rechace una propuesta en `/api/v1/web/approvals/{id}/approve` o `/reject`, el sistema SHALL actualizar su estado en `crm_proposals` y registrar un evento auditable (`repo.audit`).
- **A5-R8** El endpoint `/api/v1/web/consumption` SHALL devolver el consumo de tokens y llamadas acumuladas en el día según el presupuesto del CRM.

---

## 3. Endpoints de la API Web PWA

| Método | Ruta | Descripción | Roles Permitidos |
|---|---|---|---|
| `GET` | `/manifest.json` | Manifiesto PWA para instalación en móviles/escritorio | Público |
| `GET` | `/sw.js` | Service Worker para ciclo de vida y caché offline | Público |
| `GET` | `/` | Shell visual HTML PWA responsivo con navegación | Público (autentica en cliente) |
| `POST` | `/api/v1/web/chat` | Chat comercial con el asistente IA | Comercial, CTO |
| `GET` | `/api/v1/web/leads` | Leads asignados / visibles | Comercial, CTO |
| `GET` | `/api/v1/web/approvals` | Cola de propuestas pendientes (Gate HITL) | Comercial, CTO |
| `POST` | `/api/v1/web/approvals/{id}/approve` | Aprobación de propuesta comercial | Comercial asignado, CTO |
| `POST` | `/api/v1/web/approvals/{id}/reject` | Rechazo de propuesta comercial | Comercial asignado, CTO |
| `GET` | `/api/v1/web/consumption` | Consumo de tokens y presupuesto del día | Comercial, CTO |
