# Informe crm-director — Asistente comercial con LLM (13/10/2026)

Rama `crm/asistente-comercial-llm` (sale de `crm/pulido-post-despliegue`). Commits locales, sin push. Nada de esto toca el servidor ni los secretos.

## Respuesta urgente (req. 5)
El CRM **sí arranca** con `OPENAI_API_KEY`, `OPENAI_MODEL` y `OPENAI_REASONING_EFFORT` presentes: `CrmSettings` usa `extra="ignore"` y esas variables no llevan el prefijo `JERICO_CRM_`. Probado con valores falsos, también vacíos y con un esfuerzo desconocido (cae a `low`). El contenedor actual no necesita cambios para convivir con ellas.

## Entregado
| Pieza | Archivo |
|---|---|
| SDD: spec (36 requisitos `VCRM-A*`), plan, tareas | `specs/001-ventas-crm/{spec,plan,tasks}-asistente.md` |
| Config + flag apagado por defecto | `src/jerico/crm/config.py` |
| Seudonimización (Ley 1581) | `src/jerico/crm/pseudonym.py` |
| Cliente Responses API (httpx, `store=false`, 20 s, sin reintentos) | `src/jerico/crm/llm.py` |
| Topes diario/usuario, costo, corta-circuito, aviso único al CTO | `src/jerico/crm/assistant_budget.py` (Gemini, revisado) |
| Casos de uso y comando `/asistente` | `src/jerico/crm/assistant.py` |
| Trabajos diferidos tras el *commit* | `bot.py` (`defer`), cableado en `app.py` |
| Privacidad, costos y lista de despliegue | `specs/001-ventas-crm/asistente-despliegue.md` |

Casos de uso (solo consultivos, para CTO y comercial): `resumen L-n`, `borrador L-n [indicación]` y `pregunta <texto>` con cifras agregadas. **Nada va al cliente**: el borrador llega rotulado «Borrador (no enviado)»; lo que salga al cliente sigue por ✅/❌.

## Verificación
`verify.sh` y pre-commit en verde, 1678 tests; módulos nuevos al 100 % de cobertura. Pruebas adversarias de fuga: Gemini escribió ~37 casos y halló 7 fugas reales (palabras pegadas, Unicode NFD, URL sin esquema) además de la que detectó mi propio test (palabra suelta de la empresa); todas corregidas.

## Incidente de proceso
Un commit intermedio se hizo con la puerta de verificación fallida porque la tubería con `tail` ocultó el código de salida; lo detecté al instante, corregí y enmendé antes de seguir. Corregido el método (código de salida a archivo).

## Pendiente / no verificado
1. **No se probó contra la API real**: la forma de respuesta de `gpt-6-luna` sigue la API documentada y se probó con transporte simulado. La primera llamada real debe confirmarla; si salen respuestas cortadas, subir `max_output_tokens`.
2. **Tarifas de `gpt-6-luna`**: pendiente del CTO; sin ellas el costo sale «no calculado» y rige solo el tope en tokens (60 000/día).
3. **Revisión legal**: transferencia internacional a OpenAI con datos seudonimizados; decidir si exige actualizar el aviso de privacidad y `JERICO_CRM_DATA_PROCESSORS`. No activar en producción sin esa confirmación.
4. Riesgo residual: nombres de terceros en texto libre sin patrón. Notas del lead apagadas por defecto.
5. La llamada de red bloquea unos segundos (≤20 s) el procesamiento de mensajes: aceptable con 2 comerciales.
6. Despliegue: lo coordina el orquestador con el CTO. Con el flag apagado el comportamiento es idéntico al actual; activar con `JERICO_CRM_ASSISTANT_ENABLED=true`.

> 🕒 **Última modificación:** 13/10/2026 (Claude Code · crm-director, Sonnet 5.5)
