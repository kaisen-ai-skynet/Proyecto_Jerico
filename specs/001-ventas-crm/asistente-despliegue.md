# Asistente comercial con LLM — privacidad, costos y despliegue

Rama `crm/asistente-comercial-llm`. Spec: `spec-asistente.md`; plan: `plan-asistente.md`.

## 1. Qué viaja a OpenAI y qué no (Ley 1581)
| Dato | ¿Sale? | Cómo |
|---|---|---|
| Nombre, empresa, representante legal | No | Marcadores `[CLIENTE]`, `[EMPRESA]`, `[REPRESENTANTE]`; también sus palabras sueltas (≥3 letras; ≥4 en empresa, sin sufijos como SAS; las de ≥5 letras también pegadas a otras letras) y normalización Unicode |
| Teléfono, correo, documento | No | `[TEL]`, `[CORREO]`, `[DOC]`; además patrones: correos, enlaces (con o sin https://), secuencias de ≥6 dígitos → `[CORREO_X]`, `[ENLACE]`, `[NUM]` |
| Valores antiguos/nuevos de campos editados | No | Solo se envía «se actualizó el dato X», nunca el valor |
| Notas libres del lead | No por defecto | `JERICO_CRM_ASSISTANT_INCLUDE_NOTES=false`; si se activan, se depuran |
| Estado, servicio, plazo, valor acordado, antigüedad en días, cadencia | Sí | Servicio/plazo/valor pasan por la depuración; las fechas van relativas («hace N días») |
| Cifras del pipeline (`pregunta`) | Sí | Solo conteos por estado de los leads visibles para el actor |
| Texto libre del comercial | Sí, depurado | Mismos patrones; tope de 500 caracteres |
| Id de lead, de usuario, de chat | No | La petición lleva `store=false` y sin identificadores |

La respuesta se «rehidrata» solo en local (el comercial ve el nombre real); el mapa no se guarda.

**Riesgo residual (A15):** nombres de terceros escritos en texto libre sin patrón detectable. Mitigación: aviso en la ayuda del comando y notas apagadas.
**Pendiente legal (A16, depende del CTO/abogado):** decidir si la transferencia a un proveedor en el exterior, con datos seudonimizados, exige actualizar el aviso de privacidad y `JERICO_CRM_DATA_PROCESSORS` (hoy «Telegram,Google»). No se activa en producción hasta confirmarlo.

## 2. Qué hace y qué no
`/asistente resumen L-n`, `/asistente borrador L-n [indicación]`, `/asistente pregunta <texto>`. Solo CTO y comercial. Solo consultivo: no envía nada al cliente, no crea propuestas ni cambia estados; todo lo que salga al cliente sigue pasando por ✅/❌. El borrador llega rotulado «Borrador (no enviado)».

## 3. Costos
`reasoning.effort=low`, `max_output_tokens` 600 (tope duro 2000), entrada ≤6000 caracteres, 20 consultas por usuario/día, tope diario de 60 000 tokens (todo configurable), y opcionalmente un tope diario en USD. Al alcanzar el tope: se corta el servicio, el usuario recibe el aviso y el CTO uno solo por día. Cada llamada deja en el log una línea `asistente: caso=… usuario=… entrada=… salida=… costo=…` (sin texto) y una entrada `llm_call` en la bitácora.
**Pendiente CTO:** tarifas de `gpt-6-luna` (no se asumieron). Sin ellas el costo sale «no calculado» y solo rige el tope en tokens. El tope puede sobrepasarse como máximo por la última llamada en curso.

## 4. Degradación
Flag apagado → «no está activado» sin red. Flag encendido sin llave → «no disponible» y un aviso al CTO al arrancar. Fallo de OpenAI (red, tiempo 20 s, HTTP, respuesta vacía o rechazada) → «no disponible», entrada `error` en bitácora, sin reintentos; tras 3 fallos seguidos, 5 minutos de pausa. El resto del CRM no se ve afectado. La llamada de red ocurre después del *commit* y bloquea el procesamiento de mensajes durante su duración (≤20 s): aceptable con 2 comerciales.

## 5. Lista de despliegue (la coordina el orquestador con el CTO; esta rama no toca el servidor)
1. Traer la rama al servidor y reconstruir solo `jerico-crm`.
2. El `.env` ya tiene `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_REASONING_EFFORT`; el CRM las tolera aunque el flag esté apagado (probado, A35). Con el flag apagado el comportamiento es idéntico al actual.
3. Para activar: `JERICO_CRM_ASSISTANT_ENABLED=true` y reiniciar. Opcional: ajustar topes y tarifas.
4. Primera prueba real con el CTO: `/asistente pregunta cómo va el pipeline` y `/asistente resumen L-n`; mirar en `docker logs` la línea de uso.
5. Reversión: `JERICO_CRM_ASSISTANT_ENABLED=false` y reiniciar.

## 6. Lo que NO se verificó
- La forma exacta de la respuesta de `gpt-6-luna` por la Responses API **no se probó en vivo** (sin llave en local, por instrucción): el cliente sigue la forma documentada de la API (`output[].content[].text`, `usage.input_tokens/output_tokens`, `status`) y está probado contra un transporte simulado. La primera llamada real debe confirmarlo.
- Que `max_output_tokens=600` alcance con el razonamiento incluido: si las respuestas salen cortadas, subirlo hasta 2000.
