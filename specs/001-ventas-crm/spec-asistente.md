# Spec — Asistente comercial con LLM (extensión del CRM de ventas)

Encargo del CTO (13/10/2026). Línea `crm/asistente-comercial-llm`. Prefijo de requisitos: `VCRM-A`.
Modelo: OpenAI `gpt-6-luna`, `reasoning.effort="low"`, Responses API. La llave vive solo en el `.env` del servidor (`OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_REASONING_EFFORT`); en local todo se prueba con transporte simulado.

## 1. Alcance (decisión del director, con criterio propio)
Comando `/asistente` para **CTO y comercial** (no abogado), **solo consultivo**:
| Subcomando | Qué hace |
|---|---|
| `/asistente resumen L-n` | Resume el historial estructurado de un lead visible para el actor (≤120 palabras) y sugiere un próximo paso. |
| `/asistente borrador L-n [instrucción]` | Redacta un borrador de correo de seguimiento (asunto + cuerpo) **solo para el comercial**. No crea propuesta ni envía nada. |
| `/asistente pregunta <texto>` | Responde dudas sobre el pipeline con **cifras agregadas** de los leads que el actor puede ver. |

Fuera de alcance: enviar al cliente, crear/aprobar propuestas, cambiar estados o datos, ejecutar herramientas, fase 3.

## 2. Requisitos
**Gate (sin excepciones)**
- VCRM-A01 El asistente nunca envía nada a un cliente ni crea propuestas, colas de envío o cambios en el lead. Todo lo que salga al cliente sigue el gate ✅/❌ existente (el comercial puede pegar el borrador en «✏️ Reescribir» de una propuesta pendiente).
- VCRM-A02 Toda respuesta de borrador se rotula «Borrador (no enviado)».
- VCRM-A03 Sin escritura en tablas del CRM salvo bitácora, contadores de uso y avisos únicos.

**Permisos**
- VCRM-A04 Solo usuarios activos con rol CTO o comercial; el abogado recibe la negativa estándar.
- VCRM-A05 `resumen`/`borrador` solo sobre leads visibles para el actor (`is_visible`); `pregunta` agrega solo sobre leads visibles.
- VCRM-A06 Lead suprimido o con bloqueo comercial: el asistente se niega (no se gasta una llamada) en `borrador`; `resumen` permitido salvo suprimidos.

**Ley 1581 — minimización y seudonimización**
- VCRM-A10 A OpenAI nunca viajan en claro nombre, empresa, representante legal, teléfono, correo, tipo/número de documento ni valores de campos personales. Se sustituyen por marcadores (`[CLIENTE]`, `[EMPRESA]`, `[REPRESENTANTE]`, `[TEL]`, `[CORREO]`, `[DOC]`).
- VCRM-A11 Se envían solo datos estructurados mínimos: estado, motivo de rechazo (código), servicio, plazo, fechas relativas, nº de eventos. **Las notas libres no se envían por defecto** (`assistant_include_notes=false`); si se activan, se depuran por valores conocidos del lead y por patrones (correos, teléfonos, secuencias de ≥6 dígitos, URL).
- VCRM-A12 El texto libre del usuario (instrucción/pregunta) se depura con los mismos patrones antes de enviarse.
- VCRM-A13 Los marcadores se reponen **solo localmente** en la respuesta mostrada al comercial; el mapa no se guarda ni se registra.
- VCRM-A14 La petición va con `store=false`; no se envía identificador de lead, usuario ni chat (solo un identificador anónimo de uso).
- VCRM-A15 Riesgo residual documentado: texto libre del usuario con nombres de terceros no detectables por patrón. Mitigación: aviso al usuario en la ayuda del comando; notas apagadas por defecto.
- VCRM-A16 La transferencia a OpenAI (internacional) queda como pendiente de revisión legal (aviso de privacidad); no se activa en producción sin la confirmación del CTO/abogado.

**Costo**
- VCRM-A20 `reasoning.effort` por defecto `low`; `max_output_tokens` acotado (600 por defecto, configurable, tope duro 2000); entrada acotada (6000 caracteres).
- VCRM-A21 Cada llamada registra tokens de entrada/salida, costo estimado (si hay tarifas configuradas), caso de uso y usuario; sin texto del prompt ni de la respuesta. Bitácora (`llm_call`) y contadores diarios.
- VCRM-A22 Tope diario configurable en tokens (`assistant_daily_token_cap`, 60 000 por defecto) y opcional en USD (`assistant_daily_cost_cap_usd`, requiere tarifas); al alcanzarlo se cortan nuevas llamadas con aviso al usuario y **un** aviso al CTO por día.
- VCRM-A23 Tope por usuario/día (`assistant_user_daily_calls`, 20 por defecto).
- VCRM-A24 Las tarifas por millón de tokens (`assistant_price_in_per_mtok`, `assistant_price_out_per_mtok`) no se asumen: sin ellas el costo se reporta como «no calculado» y solo rige el tope en tokens. **Pendiente CTO**: confirmar tarifas de `gpt-6-luna`.

**Operación y degradación**
- VCRM-A30 Flag `JERICO_CRM_ASSISTANT_ENABLED` apagado por defecto: el comando responde «no está activado» sin tocar la red.
- VCRM-A31 Con el flag encendido y sin llave: el comando responde «no disponible» y al arrancar se avisa **una vez** al CTO.
- VCRM-A32 Tiempo máximo por llamada 20 s, sin reintentos. Cualquier fallo (red, 4xx/5xx, tiempo, respuesta vacía/incompleta/rechazada) → mensaje «no disponible, inténtalo más tarde», bitácora `error`, sin romper el bucle del bot.
- VCRM-A33 Corta-circuito: tras 3 fallos seguidos, 5 minutos sin llamar.
- VCRM-A34 La llave nunca se imprime ni se registra; se mantiene como `SecretStr`.
- VCRM-A35 El CRM arranca con las variables `OPENAI_*` presentes (extras ignorados) y con vacías.
- VCRM-A36 La llamada de red ocurre **fuera** de la transacción SQLite (después del *commit*).
