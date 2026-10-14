# Plan — Asistente comercial con LLM

## 1. Piezas (todas aditivas en `src/jerico/crm/`)
| Módulo | Responsabilidad |
|---|---|
| `config.py` | Campos nuevos (flag, llave `OPENAI_API_KEY`, modelo, esfuerzo, topes, tarifas, notas) con `validation_alias` para las `OPENAI_*` sin prefijo. |
| `pseudonym.py` | `Redactor`: marcadores, depuración por valores conocidos + patrones, reposición local. Función pura. |
| `llm.py` | `LlmPort` (Protocol), `LlmResult`, `LlmError`, `OpenAIResponsesClient` (httpx asíncrono, `store=false`, 20 s, sin reintentos). |
| `assistant_budget.py` | Contadores diarios (`crm_meta` por fecha de Bogotá), tope global/por usuario, costo, corta-circuito, avisos únicos al CTO. |
| `assistant.py` | Casos de uso: construye contexto mínimo seudonimizado, prompts, handler `/asistente`, trabajo diferido post-*commit*. |
| `bot.py` | Único cambio: cola de trabajos diferidos (`defer`) ejecutados tras el *commit* (misma idea que `_export_jobs`). |
| `app.py` | Cableado: cliente real si flag+llave; aviso único al CTO si falta la llave. |
| `model.py` | `AuditAction.LLM_CALL`. |

## 2. Flujo
1. `process_update` → handler `/asistente` dentro de la transacción: valida rol/visibilidad/flag/tope, arma el contexto seudonimizado y registra un trabajo diferido; responde nada aún (o «Consultando…»).
2. Tras el *commit*: el trabajo llama `llm.complete(...)` (red, sin transacción), reabre una transacción corta para registrar uso y bitácora, repone marcadores y entrega la respuesta.
3. Errores → mensaje de degradación; el bucle del bot no se detiene.

## 3. Decisiones
- Se descarta `ProposalKind` nuevo: exigiría migrar el `CHECK` de `crm_proposals` en producción y el encargo no pide envío automático. El borrador es texto para el comercial.
- Se usa `httpx` (ya en el extra `crm`) en lugar del SDK `openai`, que no está en la imagen del CRM.
- Contadores en `crm_meta` y bitácora existente: sin migración de esquema.
- Fecha del tope: día calendario de Bogotá.

## 4. Riesgos
Notas libres con terceros (mitigado: apagadas); sobrepaso de tope por la última llamada (≤ `max_output_tokens`+entrada, documentado); tarifas sin confirmar.
