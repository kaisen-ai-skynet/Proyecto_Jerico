# Spec 001 — CRM operativo asistido por IA para ventas de Kaisen AI

- **Estado:** **APROBADA** (Gate 1) por delegación del CTO el 04/10/2026, tras aplicar los ajustes finales A y las respuestas legales B de la ronda final (sección 8). Historial: auditoría QA de la fase 3 (H-01 a H-17), ronda 1 del CTO, correcciones QA ronda 2 (N-02, N-03, N-06, N-07, N-09, N-10), ronda 2 del CTO (P-02, P-06 de F1, P-11, P-12 en su tamaño, P-13, P-14, P-25 a P-27; N-01, N-04, N-05, N-11) y ronda final (A y B), todas del 04/10/2026. Todas las propuestas están ratificadas, las interpretaciones I-01 a I-07 confirmadas o reemplazadas, las preguntas al abogado J-01 a J-14 aceptadas por delegación y no queda ninguna pregunta abierta. La constitución del proyecto quedó **RATIFICADA** el 04/10/2026 con la enmienda de su punto 4 (excepción a D1 para el CRM). Siguiente paso: pasada final del reviewer sobre A y B y, después, plan de F1. **Cambio del 11/10/2026 (planificación de F2, delta spec-anchored):** decisiones Q-1 a Q-5 por delegación (sección 8); añade VCRM-169 a VCRM-171 (F2). **Cambio del 05/10/2026 (fase 6, delta spec-anchored):** decisiones K-1 a K-8 del CTO por delegación (sección 8); añade VCRM-163 a VCRM-168 (F1).
- **Tipo de cambio:** funcionalidad nueva (línea de trabajo bifurcada dentro de Jericó).
- **Fuente:** idea original del CTO (Santiago Gonzalez) del 04/10/2026, transcrita en la petición de esta línea; sus respuestas a las rondas 1, 2 y final de clarificación, y las respuestas del abogado (Juan José) por delegación (secciones 8 y 9).
- **Análisis de opciones técnicas:** documento de análisis de opciones que acompaña a esta spec.
- **Convención de marcas:**
  - `(PR-NN ratificada)` — propuesta del planificador ratificada por el CTO; rige (sección 7).
  - `(decisión P-NN)` — requisito fijado por una respuesta del CTO o resuelto por delegación del CTO; trazabilidad en la sección 8.
  - `(decisión A.N)` — ajuste final ratificado por el CTO en la ronda final (sección 8).
  - `(J-NN)` — respuesta legal aceptada por delegación del abogado (sección 9).
  - `(decisión K-N)` — decisión del CTO por delegación del 05/10/2026, tomada durante la implementación de F1 (sección 8).
  - `(I-NN)` — interpretación derivada de una respuesta del CTO, confirmada por delegación (sección 8).
  - Ya no quedan marcas `[PENDIENTE]`, `[PROPUESTA]` ni `[VERIFICAR CON ABOGADO]` abiertas.

---

## 1. Ficha

### 1.1 Problema

El proceso comercial de Kaisen AI tiene tres cuellos de botella:

1. **Captura:** el comercial pierde tiempo llenando formularios; los datos de campo (notas, audios, fotos, documentos) quedan dispersos en su teléfono.
2. **Abandono de rechazos:** cuando un cliente dice «no», el lead se pierde; no existe registro del motivo ni seguimiento programado.
3. **Fricción en el cierre:** cuando un cliente acepta, el CTO y el abogado se enteran tarde; el contrato y la autorización de datos se preparan a mano.

### 1.2 Usuarios y roles

Las acciones permitidas a cada rol están en la matriz de permisos (sección 4.4).

| Rol | Quién | Qué hace en el sistema |
| :--- | :--- | :--- |
| Comercial | Duván, único comercial hoy; se esperan 2 comerciales en 12 meses (decisión P-03). | Registra leads, notas, adjuntos, ediciones y resultados de sus propios leads (decisión P-04; PR-04 ratificada), incluido «perdido» (decisiones P-25 y A.1); registra la autorización con documento o captura y confirma las respuestas del titular propuestas como autorización (decisión N-04); aprueba ✅/❌ los mensajes al cliente final de sus leads (decisión P-16). |
| CTO | Santiago Gonzalez | Ve todos los leads (decisión P-04); marca «ganado» y «perdido» (decisiones P-25 y A.1); recibe alertas de cierre y de retractación y los avisos de registro duplicado (decisión P-11); recibe todo lo dirigido al comercial del lead cuando el lead es suyo o no tiene comercial (decisión A.2); supervisa leads y cadencias; aprueba ✅/❌ los mensajes al cliente final de cualquier lead (decisión P-16); da de alta usuarios y da de baja comerciales y al abogado por el bot (decisión A.5); atiende solicitudes de titulares (consulta, reclamo y supresión) con sus plazos legales (PR-04 ratificada; J-05). |
| Abogado | Juan José (decisión P-01), encargado del tratamiento (J-09) | Recibe por Telegram la alerta inmediata y por correo los 7 campos del handoff de cada aceptación y retractación, para preparar contrato y autorización de tratamiento de datos (J-09); consulta solo los leads que alguna vez estuvieron en «aceptado»; marca «ganado» y registra la retractación de un «aceptado» con motivo y confirmación ✅/❌; no marca «perdido» (decisión A.1). |
| Cliente final (titular) | Persona natural o representante de una empresa contactado por el comercial (decisión P-19) | Recibe mensajes aprobados en el gate (decisión P-09); otorga la autorización respondiendo al correo, con confirmación del comercial, o mediante documento firmado o captura que adjunta el comercial (decisión N-04); pide la baja respondiendo al correo (decisión P-10); solicita consulta, reclamo o supresión. No interactúa con la interfaz interna. |

### 1.3 Objetivos medibles

| ID | Objetivo | Métrica |
| :--- | :--- | :--- |
| OBJ-1 | Ningún cierre se pierde | 100 % de los leads confirmados como «aceptado» generan las notificaciones de VCRM-047 que constan como entregadas (4.5), o una alerta de fallo persistente en la ficha del lead (VCRM-087). |
| OBJ-2 | Cero envíos accidentales | 0 mensajes al cliente final sin una aprobación ✅ registrada para ese contenido exacto (decisión P-09). |
| OBJ-3 | Ningún rechazo abandonado | 100 % de los leads rechazados tienen motivo de la matriz (desde F1) y, si tienen autorización vigente, una próxima acción programada (desde F2). |
| OBJ-4 | Captura sin formularios | Un lead se registra con un único mensaje en el formato de registro (4.3). |
| OBJ-5 | Cumplimiento | 0 mensajes comerciales a leads sin autorización vigente, en baja o fuera de la franja horaria permitida. |
| OBJ-6 | Material a la mano (F3) | El comercial obtiene el enlace de un material comercial sin salir del canal de interacción. |

### 1.4 Alcance por fases (ruta del CTO)

| Fase | Alcance | Resultado tangible |
| :--- | :--- | :--- |
| **F1 — Flujo crítico** | Interfaz del comercial en Telegram; lista de usuarios autorizados persistida, con alta y baja por el bot (decisión A.5); registro de leads en formato estructurado (con aviso de duplicados), edición con historial, notas y adjuntos de hasta 20 MB; carga manual, uno a uno, de los leads previos del comercial (decisión P-13); permisos por rol con visibilidad por comercial y del abogado; estados básicos, rechazo con motivo (incluida la retractación confirmada de un aceptado), vuelta de un rechazado a «contactado» o «aceptado», y estados finales «ganado» y «perdido»; notificación de aceptación y de retractación al CTO (Telegram) y al abogado (Telegram y correo), con 3 intentos y respaldo por correo; correo saliente interno (solo al CTO, comerciales y abogado); registro de autorización de datos por documento o captura, baja y supresión; registro de solicitudes de titulares con plazos legales y escalado; plazos de conservación y depuración automática; respaldo cifrado. | El comercial reporta en tiempo real y no se pierde ningún contrato. |
| **F2 — Rechazos y seguimiento** | Motor de cadencias; gate ✅/❌ antes de cada mensaje al cliente final; correo hacia el cliente final; solicitud de autorización por correo con confirmación del comercial sobre la respuesta del titular (decisión N-04); baja por respuesta al correo; revisión humana de respuestas con escalado; reglas de horario, frecuencia y baja (Ley 2300, J-11). | Seguimiento programado de los rechazos en el que cada mensaje al cliente final sale solo tras su aprobación ✅ (decisión P-09). |
| **F3 — Drive y materiales** | Catálogo de materiales en Google Drive; enlace del material incluido en las propuestas de seguimiento sometidas al gate; borrador de contrato desde la plantilla que entregue el abogado (decisión P-22). | El comercial no busca PDFs a mano en su celular. |
| **F4 — Multimodal y app** | Transcripción local de notas de voz; extracción y tipificación con IA sobre datos seudonimizados (J-10), incluido el registro por texto libre; borradores de mensajes con IA; evaluación de una app web propia. | Sistema maduro y escalable. |

### 1.5 Fuera de alcance

- Envío del contrato al cliente final y firma electrónica (paso futuro; ver el análisis de opciones, decisión 5; J-13).
- Inscripción de la base en el Registro Nacional de Bases de Datos (RNBD): tarea administrativa fuera del sistema (J-12).
- Redacción de la política de tratamiento y del aviso de privacidad: son del abogado; el sistema solo los referencia desde su configuración (J-02).
- Envío de datos personales sin seudonimizar a proveedores de LLM o de transcripción externos (J-10).
- Negociación automatizada, aprobación automática de descuentos, facturación y pagos.
- Campañas masivas (envío a listas); cada envío es individual y pasa por el gate.
- Integración con CRMs externos (HubSpot, Salesforce u otros) y puntuación predictiva de leads.
- WhatsApp hacia el cliente final antes de F4: en F2 el canal al cliente es solo el correo (decisión P-18).
- Construcción de la app web propia: en F4 solo se evalúa.
- Registro de leads por texto libre antes de F4: en F1–F3 solo se admite el formato estructurado (4.3).
- Migración masiva o importación de leads existentes: no la hay (decisión P-13). El comercial carga sus leads previos uno a uno por el bot con la orden de registro (4.3); quedan «sin autorización» hasta que él la registre (VCRM-066, VCRM-138).
- Detección automática de la autorización por palabra clave en la respuesta del titular: descartada; el sistema propone la respuesta y el comercial confirma (decisión N-04).
- Rutas o páginas públicas de cualquier tipo (doble opt-in por enlace, enlace de baja de un clic, formularios web): descartadas por el CTO; se mantiene la postura Zero-Trust (decisión P-10).
- Mensajes automáticos al cliente final: ningún mensaje al cliente sale sin el gate ✅/❌ (decisión P-09).

### 1.6 Relación con capacidades de Jericó (conceptual)

Detalle técnico y justificación en el análisis de opciones (decisiones 1, 2, 3, 4 y 7, y puntos de coordinación con el núcleo).

**Se reutiliza (como librería, sin modificar su comportamiento):**

- **Patrón de lista blanca de identidades de Telegram** del gateway omnicanal, aplicado a una lista propia del CRM con roles.
- **Transcripción de voz local** (extra opcional de voz), en F4.
- **Planificador periódico asíncrono** (ejecución por expresión cron con reintentos y timeout) para el barrido de cadencias, entregas pendientes y respaldos.
- **Patrones del motor de persistencia transaccional** (escritor serializado, modo WAL, esquema versionado), aplicados a una base propia del CRM; el motor de producción se rige por la sección 1.7 (decisión P-14).
- **Cliente LLM con router por niveles y modelos pineados** y **constructor de prompts con huella SHA-256**, en F4.

**No se reutiliza (y por qué):**

- **Turno del agente del gateway omnicanal:** las operaciones del CRM son una máquina de estados con botones; un turno de LLM por mensaje añade costo y no determinismo. El CRM tiene su propio bot.
- **Protocolo de aprobación de D5:** rige acciones de alto riesgo del núcleo (aprobador único, CTO, expiración de 10 minutos). El gate de mensajes al cliente final es una aprobación de negocio con otros aprobadores y plazos, persistida por el CRM; se alinea con la experiencia de D5 (botones, identidad verificada, expiración) sin depender de ella.
- **Registro de herramientas del núcleo:** no se usa en F1–F3; en F4 se evalúa exponer consultas de solo lectura del CRM al asistente principal de Jericó, coordinado con el núcleo.

### 1.7 Restricciones de despliegue (decisiones del CTO, ronda 2)

- El CRM corre en la misma instancia de Oracle Cloud que Jericó (decisión P-14).
- En producción, el CRM usa SQLite WAL como **excepción temporal y acotada a D1**, autorizada por el CTO, con SQL portable a PostgreSQL 16 (decisiones P-14 y A.4). La excepción rige solo para el CRM y hasta que el CTO disponga la migración; el resto del núcleo sigue bajo D1. Queda recogida en el punto 4 de la constitución ratificada; su reflejo en el registro de decisiones del CTO queda a cargo del CTO.
- El buzón remitente del correo interno y sus credenciales son parámetros de configuración que se fijan por variables de entorno, sin valor predeterminado en el sistema; se configuran después (decisión P-27).
- Tamaño máximo de un adjunto: 20 MB (decisión P-12).
- La lista de usuarios autorizados (rol, identificador de Telegram y correo) se persiste en la base del CRM; la configuración solo siembra el CTO inicial (decisión A.5).
- Los plazos legales y de conservación son parámetros configurables con valor por defecto (sección 4.6).

---

## 2. Historias de usuario

### Módulo A — Canal de entrada e interfaz del comercial

- **HU-A1.** Como comercial, quiero registrar un lead con un solo mensaje (nombre y teléfono o correo) para no perder tiempo en formularios. *Límites:* datos incompletos, formato inválido, contacto duplicado (propio o de otro comercial), contacto que pidió no ser contactado.
- **HU-A2.** Como comercial, quiero adjuntar notas de texto, fotos, documentos y notas de voz a mis leads para conservar el contexto de cada reunión. *Límites:* archivo demasiado grande, descarga fallida, lead inexistente o ajeno.
- **HU-A3.** Como comercial, quiero consultar la lista y la ficha de mis leads, como CTO las de todos y como abogado las de los leads que alguna vez estuvieron en «aceptado», para saber en qué estado está cada oportunidad. *Límites:* lista más larga que una página. *Error:* comercial que intenta ver un lead ajeno; abogado que intenta ver un lead que nunca estuvo en «aceptado».
- **HU-A4.** Como CTO, quiero que solo las personas autorizadas puedan usar el bot, y cada una solo para lo que su rol permite, para que los datos de clientes no queden expuestos. *Error:* usuario desconocido; acción no permitida al rol; acción sobre un lead ajeno.
- **HU-A5.** Como comercial o CTO, quiero corregir o completar los datos de un lead, incluidos los del handoff, y que quede el historial del cambio para mantener la ficha al día sin perder trazabilidad. *Límites:* valor inválido, contacto que coincide con otro lead, campo inexistente, representante legal de una persona natural.
- **HU-A6.** Como CTO, quiero dar de alta por el bot a un nuevo comercial o al abogado, y dar de baja a un comercial que deja la empresa reasignando sus leads, para que solo accedan las personas vigentes y ningún lead quede sin responsable. *Error:* alta sin rol, identificador de Telegram o correo válido; identificador ya registrado.

### Módulo B — Gestión del lead y memoria de contexto

- **HU-B1.** Como comercial, quiero cambiar el estado de mis leads (contactado, aceptado, rechazado, perdido, baja) con botones, incluida la vuelta de un rechazado a «contactado» o «aceptado», para reflejar el resultado de cada interacción. *Error:* transición no permitida; «aceptado» → «perdido» sin retractación previa.
- **HU-B2.** Como comercial, quiero registrar el motivo de un rechazo de una lista cerrada desde F1 para que no se pierda el motivo y, en F2, el sistema active el seguimiento adecuado. *Límites:* motivo «otro» sin texto; lead sin autorización.
- **HU-B3.** Como comercial o CTO, quiero pausar, reanudar o cambiar la frecuencia (semanal/mensual) del seguimiento de un lead para adaptarlo a la conversación.
- **HU-B4.** Como CTO, quiero una vista de los leads en seguimiento con su modalidad y próxima acción para supervisar el embudo.
- **HU-B5.** Como CTO o abogado, quiero marcar un lead como «ganado» (contrato firmado), y como comercial o CTO, como «perdido» (descartado del todo, sin seguimiento), para cerrar su ciclo comercial (decisiones P-25 y A.1). *Error:* transición desde un estado no admitido; rol no autorizado para marcar «ganado» o «perdido».

### Módulo C — Disparador de material y aprobación humana

- **HU-C1.** Como aprobador, quiero recibir el mensaje propuesto y el material antes de cada mensaje al cliente final para aprobar (✅) o cancelar/reescribir (❌) y evitar envíos accidentales. *Límites:* doble pulsación, ✅ sobre una versión ya reescrita, gate sin respuesta, canal del cliente caído.
- **HU-C2.** Como comercial, quiero que el sistema adjunte el material de Drive correspondiente al motivo del rechazo para no buscar PDFs en mi celular (F3). *Límites:* material borrado o sin acceso; Drive sin respuesta.

### Módulo D — Handoff de cierre y legal

- **HU-D1.** Como comercial, quiero marcar al cliente como «aceptado» y que el CTO y Juan José reciban la alerta al instante (y Juan José la ficha completa por correo) para que nadie pierda el cierre. *Límites:* canal caído, correo no entregado, ambos canales caídos, datos incompletos, doble marcación.
- **HU-D2.** Como abogado, quiero recibir los datos del cliente y un borrador del contrato rellenado desde la plantilla para preparar contrato y autorización sin transcribir datos (F3). *Límites:* campo faltante, marcador desconocido en la plantilla.
- **HU-D3.** Como CTO, quiero recibir el contexto completo del cierre para monitorearlo, autorizar descuentos o intervenir en la negociación.
- **HU-D4.** Como CTO o abogado, quiero enterarme cuando un cliente aceptado se retracta, con el motivo, y como comercial, CTO o abogado, poder registrar esa retractación, para detener la preparación del contrato (decisión A.1). *Límites:* retractación cancelada con ❌ en la confirmación. *Error:* retractación sin motivo.

### Módulo E — Copiloto comercial con IA

- **HU-E1.** Como comercial, quiero enviar un audio o un texto libre describiendo la reunión y que el sistema lo procese, extraiga los datos y me proponga la actualización del lead (F4). *Límites:* transcripción fallida o vacía; extracción ambigua.
- **HU-E2.** Como aprobador, quiero borradores de seguimiento redactados por IA según el perfil del cliente, siempre sujetos al gate (F4). *Error:* servicio de IA no disponible.

### Transversal — Cumplimiento y operación

- **HU-L1.** Como CTO, quiero registrar y probar la autorización de tratamiento de datos de cada lead —por respuesta del titular al correo confirmada por el comercial, o por documento firmado o captura adjuntados por el comercial— para cumplir la Ley 1581 de 2012. *Error:* autorización sin evidencia adjunta.
- **HU-L2.** Como cliente final, quiero darme de baja de los mensajes comerciales, también respondiendo al propio correo, y que se respete de inmediato.
- **HU-L3.** Como cliente final, quiero consultar mis datos o pedir su supresión y que se atienda dentro de los plazos legales (10 días hábiles para consultas y 15 para reclamos). *Límites:* solicitud sin atender a los 2 días hábiles; solicitud vencida. *Error:* copias ya enviadas al CTO o al abogado.
- **HU-L4.** Como CTO, quiero que la base del CRM, con sus evidencias de autorización, tenga respaldo cifrado fuera de la máquina para no perderla ante un fallo de la instancia.
- **HU-L5.** Como CTO, quiero que los adjuntos y los leads sin autorización se conserven solo durante los plazos acordados y se eliminen automáticamente al vencer, con aviso previo al comercial, para cumplir la Ley 1581 sin depender de una limpieza manual (J-01, J-14). *Límites:* autorización registrada entre el aviso y el vencimiento; lead «ganado» que pasa a «baja». *Error:* fallo de la eliminación programada.

---

## 3. Requisitos (EARS en español)

Cada requisito se mapea 1:1 a al menos un caso de prueba. Etiqueta de fase entre corchetes. Los identificadores existentes se conservan; los añadidos tras la auditoría QA van del VCRM-079 al VCRM-103 y los añadidos tras la ronda 1 del CTO, del VCRM-104 al VCRM-120, los añadidos tras la auditoría QA ronda 2, del VCRM-121 al VCRM-126, los añadidos tras la ronda 2 del CTO, del VCRM-127 al VCRM-143, y los añadidos tras la ronda final (ajustes A y respuestas legales B), del VCRM-144 al VCRM-162, y los añadidos por las decisiones K del 05/10/2026, del VCRM-163 al VCRM-168, ubicados en su módulo. Un requisito obsoleto se marca «RETIRADO» con su motivo en vez de borrarse (hasta ahora: VCRM-106 y VCRM-108).

### 3.1 Módulo A — Canal e interfaz del comercial

- **VCRM-001 [F1]** EL SISTEMA procesa mensajes y pulsaciones de botones únicamente de identidades de Telegram incluidas en la lista de usuarios autorizados, cada una con un rol asignado (comercial, CTO o abogado).
- **VCRM-002 [F1]** SI una identidad no autorizada envía un mensaje o pulsa un botón, ENTONCES EL SISTEMA no ejecuta la acción, no revela datos de leads y registra el intento (identidad, fecha-hora, tipo de evento) en la bitácora de auditoría.
- **VCRM-125 [F1]** EL SISTEMA conserva en su base de datos la lista de usuarios autorizados, cada uno con rol, identificador de Telegram y dirección de correo, y la mantiene tras los reinicios; la configuración solo siembra el usuario CTO inicial (rol, identificador de Telegram y correo) cuando la lista no contiene ningún CTO, y las altas y bajas posteriores se hacen por el bot (VCRM-144, VCRM-091) (decisión A.5).
- **VCRM-144 [F1]** CUANDO el CTO da de alta por el bot a un usuario con rol «comercial» o «abogado», identificador de Telegram y dirección de correo válidos, EL SISTEMA lo añade a la lista de usuarios autorizados persistida, le da acceso de inmediato según su rol (4.4), confirma el alta al CTO y la registra en la bitácora de auditoría (decisión A.5).
- **VCRM-126 [F1]** SI el alta de un usuario —por el bot o por la siembra del CTO inicial desde la configuración— carece de rol, de identificador de Telegram o de dirección de correo, el correo no tiene la forma usuario@dominio o el identificador de Telegram ya pertenece a un usuario autorizado, ENTONCES EL SISTEMA no da de alta a ese usuario, no le da acceso e informa el dato faltante, inválido o repetido (al CTO en el bot; en el registro del servicio para la siembra) (decisión A.5; resuelve R-02 y R-06).
- **VCRM-085 [F1]** EL SISTEMA permite a cada rol únicamente las acciones marcadas para ese rol en la matriz de permisos (4.4) (PR-04 ratificada con ajuste).
- **VCRM-086 [F1]** SI un usuario autorizado solicita una acción que su rol no permite según la matriz (4.4), ENTONCES EL SISTEMA no la ejecuta, responde que no tiene permiso para esa acción y registra el intento en la bitácora de auditoría.
- **VCRM-109 [F1]** SI un comercial solicita consultar la ficha, editar, cambiar el estado o agregar notas o adjuntos a un lead que no le está asignado, ENTONCES EL SISTEMA no ejecuta la acción, responde que no tiene acceso a ese lead sin mostrar ninguno de sus datos y registra el intento en la bitácora de auditoría (decisión P-04; PR-04 ratificada con ajuste: «ve solo sus leads» incluye editar, notas y adjuntos).
- **VCRM-136 [F1]** SI el abogado solicita la ficha de un lead o una acción sobre un lead que nunca estuvo en «aceptado», ENTONCES EL SISTEMA no muestra ninguno de sus datos, responde que no tiene acceso a ese lead y registra el intento en la bitácora de auditoría (decisiones P-26 y A.1).
- **VCRM-079 [F1]** SI llega un evento entrante del canal (mensaje o pulsación de botón) cuyo identificador ya fue procesado, ENTONCES EL SISTEMA no lo procesa de nuevo ni repite su efecto.
- **VCRM-003 [F1]** CUANDO un comercial envía la orden de registro en el formato estructurado (4.3) con nombre y al menos un dato de contacto (teléfono o correo), EL SISTEMA crea el lead en estado «nuevo», lo asigna a quien lo registra (el comercial o, si lo registra el CTO, el CTO) y responde con el identificador corto del lead y los datos registrados (PR-01 ratificada). Los leads previos del comercial se cargan por esta misma vía, uno a uno (decisión P-13).
- **VCRM-004 [F1]** SI la orden de registro carece de nombre o de todo dato de contacto, ENTONCES EL SISTEMA no crea el lead y responde indicando el dato faltante y un ejemplo del formato (4.3).
- **VCRM-005 [F1]** SI el teléfono no es normalizable al formato internacional E.164 (indicativo por defecto +57, PR-02 ratificada) o el correo no tiene la forma usuario@dominio, ENTONCES EL SISTEMA no crea el lead y responde indicando el campo inválido.
- **VCRM-006 [F1]** SI el teléfono o el correo normalizados de una orden de registro coinciden (coincidencia de contacto, 4.5) con un lead existente que no está en «perdido» y es visible para el usuario (4.4), ENTONCES EL SISTEMA no crea un lead nuevo, avisa que el contacto ya está registrado, muestra el identificador, estado y comercial del existente y ofrece los botones «Abrir lead existente» y «Cancelar» (decisión P-11; I-01).
- **VCRM-110 [F1]** SI el teléfono o el correo normalizados de una orden de registro de un comercial coinciden (coincidencia de contacto, 4.5) con un lead que no está en «perdido» y no es visible para ese comercial (4.4) —asignado a otro comercial, al CTO o «sin comercial asignado»—, ENTONCES EL SISTEMA no crea el lead, no muestra ningún dato del lead existente, responde que el contacto ya está registrado en el sistema y que se avisó al CTO, y aplica VCRM-137 (decisiones P-04, P-11 y A.2; I-01; resuelve R-01).
- **VCRM-137 [F1]** CUANDO se rechaza una orden de registro según VCRM-110, EL SISTEMA envía al CTO por Telegram un aviso con el identificador del lead existente, su comercial asignado (o la indicación «del CTO» o «sin comercial asignado»), el comercial que intentó el registro y la fecha-hora, con la opción de reasignar el lead (VCRM-093) (decisiones P-11 y A.2; I-06).
- **VCRM-135 [F1]** CUANDO el teléfono o el correo normalizados de una orden de registro válida coinciden (coincidencia de contacto, 4.5) solo con leads en «perdido», EL SISTEMA crea el lead nuevo según VCRM-003 sin modificar los leads en «perdido» (decisión N-05: «si un perdido vuelve, se crea un lead nuevo»; I-01).
- **VCRM-088 [F1]** SI la huella (4.5) del teléfono o del correo de una orden de registro figura en la lista de supresión, ENTONCES EL SISTEMA no crea el lead y responde al comercial que ese contacto solicitó no ser contactado, sin mostrar otros datos (PR-10 ratificada). Esta regla prevalece sobre VCRM-006, VCRM-110 y VCRM-135.
- **VCRM-007 [F1]** CUANDO un comercial envía una foto, documento o nota de voz asociada a un lead existente visible para él (4.4), EL SISTEMA la guarda como adjunto del lead con tipo, autor y fecha-hora, y confirma la asociación.
- **VCRM-008 [F1]** SI el adjunto supera 20 MB (decisión P-12), la descarga falla o el lead indicado no existe, ENTONCES EL SISTEMA no guarda un adjunto parcial e informa la causa al comercial (para el tamaño, indicando el límite de 20 MB).
- **VCRM-009 [F1]** CUANDO un comercial agrega una nota de texto a un lead visible para él (4.4), EL SISTEMA la añade al historial del lead con autor y fecha-hora.
- **VCRM-080 [F1]** CUANDO un usuario con permiso de edición (4.4) envía la orden de edición (4.3) con un valor válido para un campo editable, EL SISTEMA guarda el nuevo valor y registra en el historial del lead el campo, el valor anterior, el valor nuevo, el autor y la fecha-hora (PR-01 ratificada).
- **VCRM-081 [F1]** SI la orden de edición indica un lead inexistente o un campo no editable, ENTONCES EL SISTEMA no modifica el lead y responde con la causa y la lista de campos editables.
- **VCRM-082 [F1]** SI el valor editado de teléfono o correo no cumple la validación de VCRM-005, ENTONCES EL SISTEMA no modifica el lead y responde indicando el campo inválido.
- **VCRM-083 [F1]** SI el valor editado de teléfono o correo coincide con el de otro lead que no está en «perdido» o su huella figura en la lista de supresión, ENTONCES EL SISTEMA no modifica el lead y responde con la causa (para el duplicado, con el identificador del otro lead solo si ese lead es visible para el usuario según 4.4) (decisión P-11; I-01, I-06).
- **VCRM-112 [F1]** SI la orden de edición de un campo del handoff (4.3) trae un valor vacío, un tipo de cliente distinto de «persona natural» o «empresa», o un tipo de documento distinto de «cédula de ciudadanía», «NIT», «cédula de extranjería» o «pasaporte», ENTONCES EL SISTEMA no modifica el lead y responde con el campo y los valores admitidos (PR-24 ratificada; decisión N-05).
- **VCRM-010 [F1]** CUANDO un usuario autorizado solicita la lista de leads, EL SISTEMA devuelve los leads visibles para su rol según la matriz (4.4) —al comercial, solo los asignados a él; al CTO, todos (decisión P-04); al abogado, solo los que alguna vez estuvieron en «aceptado» (decisiones P-26 y A.1)— con identificador, nombre, estado y fecha de última interacción, ordenados por última interacción descendente.
- **VCRM-090 [F1]** SI la lista solicitada supera el tamaño de página de 10 leads (PR-08 ratificada), ENTONCES EL SISTEMA la entrega por páginas con los botones «Anterior» y «Siguiente» y el número de página sobre el total.
- **VCRM-011 [F1]** CUANDO un usuario autorizado consulta un lead visible para su rol (4.4), EL SISTEMA muestra su ficha: datos de contacto, estado, comercial, campos del handoff (4.3), notas, adjuntos, motivo de rechazo (si aplica), estado de autorización de datos, próxima acción programada (si aplica) y alertas activas (si aplica).
- **VCRM-012 [F1]** SI una respuesta interactiva del bot (4.5) o una notificación interna no crítica (4.5) no consta como entregada (4.5), ENTONCES EL SISTEMA no la reintenta, la registra como «fallida» y no altera por ello el estado del lead; solo las notificaciones críticas (4.5) siguen el calendario de intentos de VCRM-127 (decisiones P-02 y A.3; I-03 reemplazada).
- **VCRM-091 [F1]** CUANDO el CTO da de baja por el bot a un comercial o al abogado, EL SISTEMA retira su identidad de la lista de usuarios autorizados persistida de inmediato, registra la baja en la bitácora de auditoría y, si es un comercial, presenta al CTO la lista de sus leads (en cualquier estado salvo «baja») con la opción de reasignarlos a otro comercial o a sí mismo; el rol CTO no se da de baja por el bot (PR-09 ratificada; decisión A.5).
- **VCRM-092 [F1]** MIENTRAS un lead pertenezca a un comercial dado de baja y no haya sido reasignado, EL SISTEMA lo muestra al CTO marcado «sin comercial asignado» en la lista de leads.
- **VCRM-093 [F1]** CUANDO el CTO reasigna un lead, EL SISTEMA cambia el comercial del lead y registra en el historial el comercial anterior, el nuevo, el autor y la fecha-hora.

### 3.2 Módulo B — Gestión del lead, estados y cadencias

- **VCRM-013 [F1]** EL SISTEMA solo aplica las transiciones de estado definidas en la sección 4.2 habilitadas para la fase vigente.
- **VCRM-014 [F1]** SI se solicita una transición no permitida desde el estado actual, ENTONCES EL SISTEMA no la aplica y responde con las transiciones válidas desde ese estado.
- **VCRM-015 [F1]** CUANDO se aplica una transición de estado, EL SISTEMA registra en el historial del lead el estado de origen, el de destino, el autor, la fecha-hora y el motivo (si aplica); ese historial no se edita ni se borra salvo por supresión legal (VCRM-073).
- **VCRM-089 [F1]** CUANDO un usuario con permiso (4.4) pulsa «Registrar contacto» en la ficha de un lead en «nuevo» o en «rechazado», EL SISTEMA lo pasa a «contactado» (PR-07 ratificada; decisión N-01 para el origen «rechazado»).
- **VCRM-132 [F1]** CUANDO un lead en «rechazado» (incluido uno retractado) pasa a «contactado» o a «aceptado», EL SISTEMA conserva en su historial el rechazo o la retractación previos con su motivo, autor y fecha-hora, y no borra sus notas, adjuntos ni su registro de autorización de datos (decisión N-01).
- **VCRM-016 [F1]** CUANDO un usuario con permiso (4.4) marca un lead como «rechazado» desde un estado de origen admitido (4.2), EL SISTEMA exige elegir un motivo de la matriz de motivos mediante botones antes de aplicar la transición (PR-13 ratificada; decisión P-08: el rechazo con motivo se registra desde F1).
- **VCRM-017 [F1]** SI el motivo elegido es «otro» y el texto descriptivo está vacío, ENTONCES EL SISTEMA no aplica la transición y solicita el texto (PR-13 ratificada).
- **VCRM-118 [F1]** CUANDO se registra un rechazo con motivo y las cadencias no están habilitadas en la fase vigente, EL SISTEMA deja el lead en «rechazado» con su motivo y sin próxima acción programada (decisión P-08).
- **VCRM-131 [F1]** CUANDO un usuario con permiso (4.4) —el comercial del lead, el CTO o el abogado (decisión A.1)— solicita la retractación de un lead en «aceptado» y elige el motivo según VCRM-016 y VCRM-017, EL SISTEMA muestra el identificador del lead, el nombre o razón social y el motivo, y pide confirmación con ✅ y ❌; con ✅ aplica VCRM-113 y con ❌ no aplica la transición, mantiene el lead en «aceptado» y no envía notificaciones de retractación (decisión N-11).
- **VCRM-163 [F1]** MIENTRAS un lead está en «aceptado», EL SISTEMA muestra en su ficha, solo a los usuarios con permiso de retractación (4.4) —el comercial del lead, el CTO o el abogado—, un botón «Retractar» que inicia la misma solicitud de retractación que la orden escrita (elección del motivo según VCRM-016 y VCRM-017 y confirmación según VCRM-131); en cualquier otro estado, o para un usuario sin ese permiso, la ficha no muestra el botón y una pulsación sobre un botón anterior se rechaza con el motivo, sin aplicar la transición (decisión K-2).
- **VCRM-113 [F1]** CUANDO se confirma con ✅ la retractación de un lead en «aceptado» (VCRM-131), EL SISTEMA aplica la transición a «rechazado», registra el motivo como retractación y envía, por los mismos canales que la notificación de aceptación —al CTO por Telegram y al abogado por Telegram y por correo—, una notificación de retractación con el identificador del lead, el nombre o razón social, el motivo, el autor y la fecha-hora, con el plazo de VCRM-047 y las garantías de entrega y respaldo de las notificaciones críticas (VCRM-049, VCRM-050, VCRM-107 y VCRM-127 a VCRM-130); la notificación al abogado se limita según VCRM-156 (decisiones P-08, P-02, N-05, A.1 y A.3).
- **VCRM-114 [F1]** SI se solicita la retractación de un lead en «aceptado» sin motivo o con el motivo «otro» sin texto, ENTONCES EL SISTEMA no aplica la transición, mantiene el lead en «aceptado», no envía notificaciones de retractación y solicita el motivo (decisión P-08).
- **VCRM-115 [F1]** CUANDO el CTO o el abogado marca como «ganado» (contrato firmado) un lead en «aceptado», EL SISTEMA aplica la transición y la registra según VCRM-015 (decisiones P-07 y P-25).
- **VCRM-134 [F1]** SI un comercial solicita marcar un lead como «ganado», ENTONCES EL SISTEMA no aplica la transición, responde que esa acción corresponde al CTO o al abogado y registra el intento en la bitácora de auditoría (decisión P-25).
- **VCRM-116 [F1]** CUANDO el comercial del lead (4.5) o el CTO marca como «perdido» un lead en un estado de origen admitido (4.2), EL SISTEMA aplica la transición, detiene la cadencia si la hay, cancela las propuestas pendientes de aprobación de ese lead y no programa ninguna acción de seguimiento; el abogado no marca «perdido» (VCRM-086) (decisiones P-07, P-25 y A.1; PR-23 ratificada; resuelve P-32).
- **VCRM-133 [F1]** SI se solicita marcar como «perdido» un lead en «aceptado», ENTONCES EL SISTEMA no aplica la transición y responde que primero debe registrarse la retractación (VCRM-131) (PR-23 ratificada).
- **VCRM-117 [F1]** MIENTRAS un lead está en «ganado» o «perdido», EL SISTEMA no genera propuestas ni envíos de seguimiento para ese lead y solo admite la transición a «baja»; si un lead en «perdido» vuelve, se registra como lead nuevo (VCRM-135) (decisiones P-07 y N-05).
- **VCRM-018 [F2]** CUANDO se registra un rechazo con motivo y el lead tiene autorización vigente para contacto comercial, EL SISTEMA asigna la cadencia asociada al motivo en la matriz configurable (4.6; decisión P-17), calcula la fecha-hora de la próxima acción y pasa el lead a «en nutrición».
- **VCRM-019 [F2]** SI se registra un rechazo y el lead no tiene autorización vigente para contacto comercial, ENTONCES EL SISTEMA deja el lead en «rechazado» sin cadencia y avisa al comercial que falta la autorización.
- **VCRM-121 [F2]** CUANDO se registra la autorización vigente (4.5) de un lead en «rechazado», EL SISTEMA asigna la cadencia asociada a su motivo de rechazo registrado en la matriz configurable (4.6; decisión P-17), calcula la fecha-hora de la próxima acción y pasa el lead a «en nutrición», como en VCRM-018; los leads que ya estaban en «rechazado» con autorización vigente al habilitarse las cadencias se rigen por VCRM-160 (decisión P-29).
- **VCRM-160 [F2]** CUANDO se habilitan las cadencias en el sistema (activación de F2), EL SISTEMA asigna a cada lead en «rechazado» con autorización vigente la cadencia de su motivo de rechazo, calcula su próxima acción a partir de la fecha-hora de activación —no de la fecha del rechazo— y lo pasa a «en nutrición»; los leads en «rechazado» sin autorización vigente quedan como están (decisión P-29).
- **VCRM-020 [F2]** CUANDO un usuario con permiso sobre la cadencia (4.4) pausa la cadencia de un lead en «en nutrición», EL SISTEMA pasa el lead a «pausado» y cancela las propuestas pendientes de aprobación de ese lead.
- **VCRM-021 [F2]** MIENTRAS un lead está en «pausado», EL SISTEMA no genera propuestas ni envíos para ese lead.
- **VCRM-022 [F2]** CUANDO un usuario con permiso sobre la cadencia (4.4) reanuda la cadencia de un lead en «pausado», EL SISTEMA lo pasa a «en nutrición» y calcula la próxima acción a partir de la fecha-hora de reanudación, sin generar las acciones omitidas durante la pausa (PR-14 ratificada).
- **VCRM-023 [F2]** CUANDO un usuario con permiso sobre la cadencia (4.4) cambia la frecuencia de la cadencia (semanal o mensual), EL SISTEMA recalcula la próxima acción a partir del último envío al cliente o, si no lo hubo, a partir de la fecha-hora del cambio (PR-15 ratificada).
- **VCRM-024 [F2]** CUANDO un comercial marca como «reactivado» un lead en «en nutrición», «pausado» o «rechazado», EL SISTEMA detiene la cadencia si la hay, cancela las propuestas pendientes y deja el lead disponible para las transiciones desde «reactivado» (4.2) (PR-16 ratificada).
- **VCRM-025 [F2]** CUANDO un usuario con permiso de consulta (4.4) solicita la vista de seguimiento, EL SISTEMA devuelve los leads visibles para él en «en nutrición» o «pausado» con motivo, frecuencia, fecha-hora de la próxima acción y número de envíos realizados.
- **VCRM-026 [F2]** CUANDO una cadencia completa su último paso (4.6; decisión P-17), EL SISTEMA deja de generar propuestas para ese lead, lo informa al comercial del lead (4.5) con los botones «Marcar perdido» y «Reactivar», y mantiene el lead en «en nutrición» sin próxima acción hasta que un usuario con permiso (4.4) decida; el sistema no lo pasa a «perdido» por sí solo (decisión P-17).

### 3.3 Módulo C — Gate de aprobación y materiales

- **VCRM-027 [F2]** CUANDO llega la fecha-hora de la próxima acción de un lead en «en nutrición», EL SISTEMA genera una propuesta (texto fijo del motivo configurado por el CTO, decisión P-21, y material asociado al motivo) y la presenta por chat individual con el bot al comercial del lead (4.5) con los botones ✅ y ❌; el CTO también puede aprobarla desde la ficha del lead (decisión P-16).
- **VCRM-161 [F2]** SI al generar una propuesta no hay texto fijo configurado para el motivo de rechazo del lead, ENTONCES EL SISTEMA no genera la propuesta, no avanza la cadencia de ese lead y avisa al CTO por Telegram con el motivo sin texto (decisión P-21).
- **VCRM-028 [F2]** EL SISTEMA genera como máximo una propuesta por lead y por paso de cadencia, aunque la evaluación periódica se ejecute varias veces o el servicio se reinicie.
- **VCRM-029 [F2]** CUANDO el aprobador pulsa ✅ sobre la versión vigente de una propuesta pendiente, EL SISTEMA envía el mensaje al cliente final por correo desde el buzón del sistema (decisión P-18), registra el envío (contenido, material, aprobador, fecha-hora) y programa la siguiente acción de la cadencia.
- **VCRM-030 [F2]** SI se pulsa ✅ o ❌ sobre una propuesta ya resuelta (incluida la doble pulsación o la pulsación desde dos dispositivos), ENTONCES EL SISTEMA no repite la acción y responde que la propuesta ya fue procesada.
- **VCRM-031 [F2]** CUANDO el aprobador pulsa ❌, EL SISTEMA ofrece las opciones «Cancelar envío» y «Reescribir».
- **VCRM-032 [F2]** CUANDO el aprobador elige «Cancelar envío», EL SISTEMA no envía el mensaje, registra la cancelación con autor y fecha-hora, y programa la siguiente acción de la cadencia, saltando al paso siguiente (decisión P-17).
- **VCRM-033 [F2]** CUANDO el aprobador elige «Reescribir» y envía un texto nuevo, EL SISTEMA crea una nueva versión de la propuesta con ese texto, invalida la versión anterior y presenta la nueva con ✅ y ❌, sin enviarla hasta una nueva pulsación de ✅.
- **VCRM-099 [F2]** SI se pulsa ✅ sobre una versión de propuesta invalidada por una reescritura, ENTONCES EL SISTEMA no envía el mensaje y responde que esa versión fue reemplazada, indicando la versión vigente.
- **VCRM-034 [F2]** SI una propuesta no recibe respuesta dentro del plazo del gate (4.6: 48 horas por defecto; decisión P-17), ENTONCES EL SISTEMA la marca «expirada», no la envía, avisa al aprobador y, si es un seguimiento de cadencia, programa la siguiente acción como en VCRM-032.
- **VCRM-035 [F2]** SI una identidad sin rol de aprobador pulsa ✅ o ❌, ENTONCES EL SISTEMA no cambia la propuesta y registra el intento en la bitácora de auditoría.
- **VCRM-036 [F2]** EL SISTEMA no envía ningún mensaje al cliente final —seguimientos, solicitudes de autorización, acuses o cualquier otro— sin una aprobación ✅ registrada cuyo contenido coincida exactamente con el enviado (decisión P-09).
- **VCRM-037 [F2]** SI en el momento del envío de un seguimiento aprobado el lead no está en «en nutrición», no tiene autorización vigente o la huella de su contacto figura en la lista de supresión, ENTONCES EL SISTEMA no envía el mensaje, lo marca «cancelado por estado» y avisa al aprobador; para una solicitud de autorización aprobada (VCRM-068) solo aplica la condición de la lista de supresión.
- **VCRM-038 [F2]** SI el envío al cliente final no consta como entregado (4.5) por canal caído o rechazo del proveedor, ENTONCES EL SISTEMA lo intenta hasta 3 veces en total —a los 0, 1 y 5 minutos del primer intento—, sin hacer ningún intento fuera de la franja permitida (VCRM-072) y comprobando VCRM-037 antes de cada uno; si el tercer intento falla o el siguiente caería fuera de la franja, marca el envío «fallido», avisa al aprobador y no avanza la cadencia de ese lead hasta que un usuario con permiso sobre la cadencia (4.4) decida reintentar o cancelar (decisión P-33; PR-17 ratificada).
- **VCRM-039 [F2]** SI el lead carece del dato de contacto que exige el canal configurado, ENTONCES EL SISTEMA no genera la propuesta y avisa al comercial el dato faltante.
- **VCRM-040 [F3]** EL SISTEMA mantiene un catálogo de materiales comerciales indexado desde las carpetas de Google Drive configuradas, con nombre, tipo, categoría (carpeta), enlace y fecha de última sincronización.
- **VCRM-041 [F3]** CUANDO se ejecuta la sincronización del catálogo, EL SISTEMA agrega los materiales nuevos, actualiza los modificados y marca como «no disponible» los eliminados o sin acceso.
- **VCRM-042 [F3]** CUANDO se genera una propuesta de seguimiento, EL SISTEMA incluye el enlace del material de la categoría asociada al motivo de rechazo según la matriz configurable.
- **VCRM-043 [F3]** SI el material asociado no existe o no es accesible al generar la propuesta o al enviarla, ENTONCES EL SISTEMA no envía el enlace, avisa al aprobador y le permite elegir otro material o enviar sin material.
- **VCRM-044 [F3]** CUANDO un comercial solicita material por categoría o por texto, EL SISTEMA devuelve los materiales disponibles que coinciden, hasta el máximo de resultados (PR-21 ratificada: 10), con nombre y enlace.
- **VCRM-045 [F3]** SI Google Drive no responde durante la sincronización, ENTONCES EL SISTEMA conserva el último catálogo sincronizado, registra el fallo e indica la fecha de esa última sincronización en las consultas de material.

### 3.4 Módulo D — Handoff de cierre, retractación y notificaciones internas

- **VCRM-046 [F1]** CUANDO un usuario con permiso (4.4) marca un lead como «aceptado», EL SISTEMA muestra el resumen del lead y pide confirmación con ✅ y ❌; con ✅ aplica la transición y con ❌ no la aplica (PR-05 ratificada).
- **VCRM-047 [F1]** CUANDO se confirma la aceptación de un lead, EL SISTEMA genera tres notificaciones independientes —al CTO por Telegram; al abogado por Telegram, como alerta inmediata; y al abogado por correo, con la ficha completa— y realiza el primer intento de entrega de cada una antes de que transcurra 1 minuto desde la confirmación, de modo que el fallo de una no impide ni retrasa las demás (decisiones P-01 y P-02; I-04).
- **VCRM-048 [F1]** EL SISTEMA incluye en la notificación de aceptación al CTO: identificador del lead, comercial, fecha-hora de aceptación, notas registradas, estado de la autorización de datos y los campos del handoff (4.3) con sus valores y la lista de los faltantes; y en el correo al abogado: identificador del lead, comercial, fecha-hora de aceptación, estado de la autorización de datos, los campos acordados del handoff (4.3: los de la decisión P-05 más el tipo de cliente de PR-24) con sus valores y la lista de los faltantes, y la solicitud explícita de preparar contrato y autorización de tratamiento de datos, sin notas ni otros datos del titular (VCRM-156) (decisiones P-01 y P-05; PR-24; J-09; decisión K-1).
- **VCRM-104 [F1]** EL SISTEMA incluye en la alerta de aceptación por Telegram al abogado el identificador del lead, el nombre o razón social, el comercial, la fecha-hora de aceptación y la indicación de que la ficha completa se envió por correo (decisión P-01).
- **VCRM-156 [F1]** EL SISTEMA no incluye en ninguna notificación al abogado (aceptación, retractación, actualización del handoff, supresión, respaldos y avisos de fallo) datos del titular distintos de los campos acordados del handoff (4.3: los de la decisión P-05 más el tipo de cliente de PR-24) —ni notas, ni adjuntos, ni historial, ni transcripciones— (J-09; decisión K-1).
- **VCRM-105 [F1]** EL SISTEMA envía las notificaciones internas por correo (al CTO, a los comerciales y al abogado) desde el buzón remitente que fija la configuración del sistema, sin valor predeterminado para el buzón ni para sus credenciales, a la dirección de correo registrada para cada usuario autorizado; en F1 no envía correos al cliente final (decisiones P-01 y P-27).
- **VCRM-140 [F1]** SI el buzón remitente o sus credenciales no están configurados, ENTONCES EL SISTEMA marca «fallida» sin más intentos cada notificación por correo y aplica, según corresponda, VCRM-050 o VCRM-129 (decisión P-27).
- **VCRM-049 [F1]** EL SISTEMA persiste cada notificación crítica (4.5), por Telegram o por correo, antes de intentar su entrega, la mantiene pendiente hasta que conste como entregada (4.5) o quede «fallida» según VCRM-127 y, tras un reinicio del servicio, reanuda la entrega de las pendientes con los intentos que les queden (decisión A.3).
- **VCRM-127 [F1]** SI el intento de entrega de una notificación crítica (4.5), por Telegram o por correo, no consta como entregado (4.5), ENTONCES EL SISTEMA la intenta hasta 3 veces en total —a los 0, 1 y 5 minutos del primer intento— y, si el tercer intento tampoco consta como entregado, la marca «fallida» y no la intenta más; las respuestas interactivas del bot y las notificaciones no críticas no se reintentan (VCRM-012) (decisiones P-02 y A.3; I-02 e I-03 reemplazadas).
- **VCRM-106 [F1]** RETIRADO (inalcanzable: todo usuario autorizado tiene dirección de correo, porque VCRM-126 impide el alta sin ella; decisión A.5, hallazgo R-06).
- **VCRM-050 [F1]** SI una notificación de aceptación, de retractación o de actualización del handoff (VCRM-084) queda «fallida» (VCRM-127) —por Telegram a cualquier destinatario o por correo al abogado—, ENTONCES EL SISTEMA envía por correo al CTO y al comercial del lead (4.5; si es el CTO, un solo correo) un correo de respaldo con el identificador del lead, el destinatario y el canal que fallaron (decisiones P-01 y P-02; decisión N-05: el respaldo también se activa si falla el correo al abogado).
- **VCRM-128 [F1]** EL SISTEMA no envía el correo de respaldo de VCRM-050 mientras la notificación conserve intentos pendientes según VCRM-127; el respaldo sale solo tras fallar el tercer intento y nunca en paralelo a los intentos (decisiones P-02 y A.3).
- **VCRM-107 [F1]** SI la notificación de aceptación, de retractación o de actualización del handoff al CTO por Telegram queda «fallida», ENTONCES EL SISTEMA incluye en el correo de respaldo al CTO el contenido completo de esa notificación (decisión P-01).
- **VCRM-108 [F1]** RETIRADO (el reintento indefinido del aviso de fallo queda sustituido por el calendario de 3 intentos de VCRM-127 y por VCRM-129 y VCRM-130; decisiones P-02 y A.3).
- **VCRM-129 [F1]** SI el correo de respaldo de VCRM-050 queda «fallido» (VCRM-127), ENTONCES EL SISTEMA envía al CTO y al comercial del lead (4.5; si es el CTO, un solo aviso por canal), por Telegram y por correo, un aviso de fallo del respaldo con el identificador del lead, la notificación original que falló y el destinatario del respaldo que falló (decisión N-11).
- **VCRM-130 [F1]** SI el aviso de fallo del respaldo (VCRM-129) queda «fallido» (VCRM-127) por Telegram y por correo, ENTONCES EL SISTEMA no realiza más envíos ni reintentos por esa notificación y mantiene la alerta de VCRM-087 (decisión P-02; I-05).
- **VCRM-087 [F1]** MIENTRAS una notificación de aceptación, de retractación o de actualización del handoff de un lead esté «fallida», EL SISTEMA muestra una alerta en la ficha del lead y lo señala en la lista de leads del CTO, hasta que el CTO la marque «atendida por otro medio» (I-05).
- **VCRM-051 [F1]** SI se confirma la aceptación de un lead que ya está en «aceptado», ENTONCES EL SISTEMA no repite las notificaciones e informa que el lead ya estaba aceptado.
- **VCRM-111 [F1]** CUANDO se evalúa la completitud del handoff de un lead (al confirmar la aceptación y tras cada edición de un lead en «aceptado»), EL SISTEMA considera faltante todo campo obligatorio del handoff (4.3) sin valor y el representante legal solo si el tipo de cliente es «empresa»; si el tipo de cliente no está registrado, lista como faltantes el tipo de cliente y el representante legal con la anotación «obligatorio si es empresa» (PR-24 ratificada; decisión P-05).
- **VCRM-052 [F1]** SI al confirmar la aceptación faltan campos del handoff según VCRM-111, ENTONCES EL SISTEMA envía igualmente las notificaciones de VCRM-047 indicando en cada una los campos faltantes y solicita al comercial del lead (4.5) completarlos (PR-06 ratificada; decisión A.2).
- **VCRM-084 [F1]** CUANDO se completa por edición (VCRM-080) un campo del handoff que figuraba como faltante en un lead «aceptado», EL SISTEMA envía al CTO (por Telegram) y al abogado (por Telegram y por correo) una notificación de actualización con el campo completado y los campos que siguen faltando, con las garantías de entrega y respaldo de las notificaciones críticas (VCRM-049, VCRM-050, VCRM-107 y VCRM-127 a VCRM-130) (PR-06 ratificada; decisiones P-02 y A.3).
- **VCRM-053 [F3]** CUANDO se confirma la aceptación y existe una plantilla de contrato configurada (entregada y mantenida por el abogado; decisión P-22), EL SISTEMA genera un borrador de contrato preliminar con los datos del lead y lo entrega al abogado y al CTO.
- **VCRM-054 [F3]** SI la plantilla requiere un campo que no tiene valor en la ficha del lead, ENTONCES EL SISTEMA no genera el borrador, informa al abogado y al comercial la lista de campos faltantes y permite regenerarlo cuando se completen.
- **VCRM-055 [F3]** SI la plantilla contiene un marcador que no corresponde a ningún campo conocido, ENTONCES EL SISTEMA no genera el borrador y reporta el marcador desconocido al abogado y al CTO.
- **VCRM-056 [F3]** EL SISTEMA registra cada borrador generado con la versión de la plantilla, la fecha-hora y los valores usados, y nunca lo envía al cliente final.

### 3.5 Módulo E — Copiloto comercial con IA

- **VCRM-057 [F4]** CUANDO un comercial envía una nota de voz asociada a un lead o sin lead, EL SISTEMA la transcribe y muestra la transcripción al comercial dentro del plazo máximo de procesamiento (4.6: 10 minutos por defecto); la transcripción se hace en la propia instancia, sin enviar el audio a servicios externos (decisión P-23; J-10).
- **VCRM-058 [F4]** SI la transcripción falla o resulta vacía, ENTONCES EL SISTEMA conserva el audio como adjunto (si hay lead), informa el error al comercial y no modifica el lead.
- **VCRM-059 [F4]** CUANDO hay una transcripción o un texto libre del comercial disponible, EL SISTEMA extrae nombre, contacto, empresa, resultado (aceptado, rechazado o seguimiento), motivo de rechazo y objeciones, y presenta la actualización propuesta con ✅ y ❌; solo la aplica tras ✅ (decisión P-24).
- **VCRM-060 [F4]** SI la extracción no cumple el esquema de datos esperado o no determina el resultado, ENTONCES EL SISTEMA no propone cambio de estado y pide al comercial la aclaración del dato.
- **VCRM-061 [F4]** CUANDO corresponde generar una propuesta de seguimiento y el borrador con IA está habilitado, EL SISTEMA redacta el texto a partir del perfil del lead, el motivo de rechazo y las objeciones registradas, y lo somete al gate (VCRM-027 a VCRM-036).
- **VCRM-062 [F4]** SI el servicio de IA falla o excede su timeout, ENTONCES EL SISTEMA usa el texto fijo del motivo e indica en la propuesta que no es un borrador de IA (PR-22 ratificada).
- **VCRM-063 [F4]** EL SISTEMA registra para cada salida de IA el identificador exacto del modelo y la huella del prompt de sistema utilizado.
- **VCRM-064 [F4]** EL SISTEMA no incluye en las solicitudes enviadas a servicios de IA externos ningún dato personal del titular sin seudonimizar: omite teléfono, correo y número de documento, sustituye nombre, razón social y representante legal por marcadores antes del envío y los restituye solo dentro del sistema (decisión P-23; J-10).
- **VCRM-157 [F4]** SI la seudonimización de una solicitud a un servicio de IA externo falla o deja un dato personal del titular sin sustituir, ENTONCES EL SISTEMA no envía la solicitud, no modifica el lead y aplica VCRM-062 (texto fijo) o, en la extracción, informa al comercial que debe registrar los datos con el formato estructurado (4.3) (J-10).

### 3.6 Cumplimiento (transversal)

- **VCRM-065 [F1]** EL SISTEMA registra por lead el estado de la autorización de tratamiento de datos (sin autorización, autorizada, revocada), con medio de obtención, fecha-hora, versión del aviso de privacidad y finalidades informadas, y referencia a la evidencia.
- **VCRM-066 [F1]** CUANDO se registra un lead (incluidos los leads previos que el comercial carga uno a uno, decisión P-13), EL SISTEMA pregunta al comercial con botones si cuenta con un documento firmado o una captura que pruebe la autorización del titular; si responde que sí, le pide adjuntarlo y aplica VCRM-138; si la respuesta es negativa o no se responde, marca el lead «sin autorización» (PR-03 ratificada; decisión N-04).
- **VCRM-138 [F1]** CUANDO un usuario con permiso (4.4) adjunta a un lead un documento firmado o una captura como evidencia de la autorización del titular —al registrarlo o después—, EL SISTEMA guarda el adjunto con el tipo «autorización» y registra la autorización como «autorizada» con medio «documento o captura adjuntada por el comercial», autor, fecha-hora y referencia al adjunto (decisión N-04; I-07; J-04).
- **VCRM-139 [F1]** SI se solicita registrar la autorización de un lead sin adjuntar un documento firmado o una captura, o por un medio distinto de los admitidos (respuesta del titular al correo confirmada por el comercial, documento firmado o captura), ENTONCES EL SISTEMA no la registra, mantiene el estado de autorización del lead e informa los medios válidos (decisión N-04).
- **VCRM-067 [F2]** SI un lead no tiene autorización vigente para contacto comercial, ENTONCES EL SISTEMA no genera propuestas ni envíos comerciales para ese lead.
- **VCRM-068 [F2]** CUANDO un usuario con permiso (4.4) solicita obtener la autorización de un lead, EL SISTEMA prepara la solicitud dirigida al titular por correo con la referencia a la política de tratamiento y al aviso de privacidad y la mención de los encargados (VCRM-148), y la instrucción de responder a ese correo para otorgar la autorización o con la palabra «BAJA» para no recibir más mensajes, la presenta al aprobador (VCRM-027: comercial del lead o CTO; decisión P-16) con ✅ y ❌ y solo la envía tras ✅ (decisiones P-09, P-10 y N-04; J-02, J-03).
- **VCRM-148 [F2]** EL SISTEMA obtiene de su configuración la referencia a la política de tratamiento y al aviso de privacidad (URL o texto, con su versión), redactados y mantenidos por el abogado, y la lista de encargados del tratamiento, que por defecto incluye Telegram y Google; incluye esa referencia y la mención de esos encargados en cada solicitud de autorización y registra la versión del aviso en cada autorización obtenida por correo (J-02, J-10).
- **VCRM-149 [F2]** SI no está configurada la referencia a la política de tratamiento o al aviso de privacidad, ENTONCES EL SISTEMA no prepara la solicitud de autorización y responde al usuario que la solicitó que falta esa referencia en la configuración (J-02).
- **VCRM-119 [F2]** CUANDO llega por el canal de envío al cliente una respuesta del titular asociada (4.5) a un lead sin autorización vigente al que se envió una solicitud de autorización (VCRM-068), cuyo texto nuevo (4.5) no contiene la palabra clave «BAJA» (4.5), EL SISTEMA no registra la autorización: presenta al comercial del lead (4.5) el texto nuevo de la respuesta, la fecha-hora de recepción y la forma de asociación, con la pregunta de si esa respuesta autoriza el tratamiento de datos y los botones ✅ y ❌; mientras no haya confirmación, el lead sigue «sin autorización» (decisión N-04; PR-25 reemplazada; J-03).
- **VCRM-141 [F2]** CUANDO el comercial del lead pulsa ✅ sobre una respuesta propuesta como autorización (VCRM-119), EL SISTEMA registra la autorización del lead con medio «respuesta al correo confirmada por el comercial», el comercial que confirmó, la fecha-hora de la respuesta y la de la confirmación, la forma de asociación (referencia de hilo o huella del remitente), la versión del aviso y las finalidades de la solicitud enviada, y la referencia al mensaje recibido como evidencia (decisión N-04; J-03).
- **VCRM-142 [F2]** CUANDO el comercial del lead pulsa ❌ sobre una respuesta propuesta como autorización (VCRM-119), EL SISTEMA no registra la autorización, mantiene el lead «sin autorización» y registra en el historial del lead la respuesta, la decisión, el autor y la fecha-hora (decisión N-04).
- **VCRM-143 [F2]** SI se pulsa ✅ o ❌ sobre una respuesta propuesta como autorización que ya fue resuelta (incluida la doble pulsación o la pulsación desde dos dispositivos), ENTONCES EL SISTEMA no repite la acción y responde que la propuesta ya fue procesada (decisión N-04).
- **VCRM-120 [F2]** SI el texto nuevo (4.5) de una respuesta del titular asociada a un lead al que se envió una solicitud de autorización contiene la palabra clave «BAJA», ENTONCES EL SISTEMA aplica la baja según VCRM-102, no presenta la respuesta al comercial como posible autorización y no registra la autorización (decisión N-04).
- **VCRM-069 [F2]** EL SISTEMA incluye en cada mensaje comercial y en cada solicitud de autorización al cliente final la identificación del remitente y la instrucción para solicitar la baja respondiendo con la palabra «BAJA» (PR-20 ratificada); no incluye enlaces a páginas públicas de baja ni de autorización (decisión P-10).
- **VCRM-123 [F2]** EL SISTEMA incluye en cada mensaje comercial y en cada solicitud de autorización enviados por correo al cliente final la cabecera estándar de baja por correo, que permite al titular solicitar la baja desde su cliente de correo mediante un mensaje dirigido al buzón del sistema, sin enlaces a páginas públicas (PR-26 ratificada; decisión P-10).
- **VCRM-070 [F1]** CUANDO se registra la solicitud de baja del titular (comunicada al comercial y registrada por un usuario con permiso, 4.4; además por respuesta al correo en F2, VCRM-102, VCRM-124 y VCRM-153), EL SISTEMA aplica la baja en ese mismo momento (J-05): pasa el lead a «baja», añade la huella de su contacto a la lista de supresión, cancela propuestas y envíos pendientes y registra la solicitud con fecha-hora y medio.
- **VCRM-102 [F2]** CUANDO llega por el canal de envío al cliente una respuesta del titular asociada a un lead (4.5) cuyo texto nuevo (4.5) contiene la palabra clave «BAJA» (4.5), EL SISTEMA aplica la baja de ese lead según VCRM-070 con medio «respuesta al correo», de inmediato y sin confirmación humana (PR-20 ratificada; decisiones P-10 y P-31; J-06).
- **VCRM-124 [F2]** CUANDO llega al buzón del sistema una solicitud de baja generada por la cabecera de baja de un mensaje enviado (VCRM-123), EL SISTEMA aplica la baja del lead al que se envió ese mensaje según VCRM-070 con medio «cabecera de baja del correo», sin exigir la palabra clave «BAJA» ni confirmación humana; si no identifica ese mensaje, aplica VCRM-122 (PR-26 ratificada; decisión P-31; J-06).
- **VCRM-103 [F2]** SI llega por el canal de envío al cliente una respuesta del titular asociada a un lead (4.5) cuyo texto nuevo (4.5) no contiene la palabra clave «BAJA» y a la que no se aplica VCRM-119, ENTONCES EL SISTEMA la registra en el historial del lead y la reenvía al comercial del lead (4.5) para revisión humana según VCRM-153, sin cambiar su estado (PR-20 ratificada).
- **VCRM-122 [F2]** SI llega por el canal de envío al cliente una respuesta no asociable a un lead (4.5), ENTONCES EL SISTEMA no cambia el estado de ningún lead, no registra autorización ni baja, conserva la respuesta y la presenta al CTO para revisión humana según VCRM-153 (PR-27 ratificada).
- **VCRM-153 [F2]** CUANDO se presenta una respuesta del titular para revisión humana (VCRM-103 o VCRM-122), EL SISTEMA la registra como solicitud del titular «por clasificar», con fecha límite de 15 días hábiles desde su recepción (VCRM-150), y ofrece los botones «Aplicar baja», «Registrar consulta o reclamo» y «Sin solicitud»; con «Aplicar baja» aplica VCRM-070 con medio «respuesta al correo confirmada por un usuario»; con «Registrar consulta o reclamo» la reclasifica según VCRM-150; con «Sin solicitud» la cierra; cada decisión se registra con autor y fecha-hora (decisión P-31; J-05, J-06).
- **VCRM-169 [F2]** EL SISTEMA obtiene las respuestas del titular y las solicitudes de baja de la cabecera (VCRM-123) consultando periódicamente el buzón del sistema mediante conexiones iniciadas por el propio sistema, sin exponer ninguna ruta pública de ingreso (decisiones P-10 y Q-2), y procesa cada mensaje recibido una sola vez aunque la consulta se repita o el servicio se reinicie.
- **VCRM-170 [F2]** SI la consulta del buzón (VCRM-169) falla por conexión o credenciales, ENTONCES EL SISTEMA avisa al CTO una vez por episodio de fallo, reintenta en la siguiente consulta periódica y, al recuperarse, procesa todos los mensajes recibidos durante el fallo, sin perder ninguno (decisión Q-2).
- **VCRM-171 [F2]** CUANDO se activa F2 sobre datos de F1, EL SISTEMA conserva sin pérdida ni cambio de significado los estados de leads, autorizaciones, notificaciones, solicitudes de titulares e historial, y mantiene operativos los botones emitidos antes de la activación (decisión Q-1).
- **VCRM-071 [F1]** MIENTRAS la huella (4.5) de un contacto figura en la lista de supresión, EL SISTEMA no genera propuestas ni envíos comerciales dirigidos a ese contacto, cualquiera que sea el lead al que esté asociado.
- **VCRM-095 [F1]** EL SISTEMA guarda en la lista de supresión únicamente la huella (4.5) del contacto normalizado, la fecha-hora y el medio de la solicitud; nunca el contacto en claro.
- **VCRM-072 [F2]** EL SISTEMA envía mensajes comerciales y solicitudes de autorización al cliente final, sea persona natural o empresa, solo dentro de la franja permitida en hora de Colombia: lunes a viernes de 07:00 a 19:00 y sábados de 08:00 a 15:00, excluidos domingos y festivos de Colombia (franja configurable, 4.6) (J-11).
- **VCRM-100 [F2]** SI una propuesta se aprueba fuera de la franja permitida (VCRM-072), ENTONCES EL SISTEMA difiere el envío al inicio de la siguiente franja permitida y lo informa al aprobador con la fecha-hora prevista (PR-18 ratificada).
- **VCRM-076 [F2]** EL SISTEMA no envía a un mismo lead, sea persona natural o empresa, más contactos —mensajes comerciales y solicitudes de autorización— por semana calendario (4.5) que el límite configurado, 1 por defecto (4.6) (decisión P-19; J-11).
- **VCRM-101 [F2]** SI una propuesta aprobada excede el límite semanal de VCRM-076, ENTONCES EL SISTEMA difiere el envío a la primera franja permitida de la semana calendario siguiente y lo informa al aprobador (PR-19 ratificada).
- **VCRM-073 [F1]** CUANDO el CTO ordena la supresión de los datos de un titular, EL SISTEMA elimina de la base de datos y del almacén de adjuntos los datos personales de todos los leads del mismo titular (4.5), incluidos los retractados (ficha, campos del handoff, notas, adjuntos, transcripciones, historial de cambios de datos y textos de propuestas), conserva únicamente la huella del contacto en la lista de supresión y la huella mínima (4.5) de las evidencias de autorización y revocatoria (VCRM-165), confirma la supresión al CTO con los identificadores de todos los leads suprimidos y aplica VCRM-154 (PR-04 ratificada; J-07; decisiones K-3 y K-4).
- **VCRM-094 [F1]** SI el CTO ordena la supresión de un titular cuyo lead está en «aceptado» o «ganado» y el CTO indica que existe un deber legal o contractual de conservar datos, ENTONCES EL SISTEMA conserva solo los datos señalados para ese deber, los bloquea para todo uso comercial, suprime el resto, registra el fundamento indicado, reduce las evidencias de autorización y revocatoria a su huella mínima según VCRM-165 y aplica VCRM-154; un lead retractado (en «rechazado» tras haber estado en «aceptado») no se acoge a esta excepción (J-07).
- **VCRM-164 [F1]** EL SISTEMA conserva las evidencias de autorización y de revocatoria de cada lead (registro y adjunto) mientras exista la obligación de probar el consentimiento (Decreto 1377, art. 7); ni la supresión por plazo (VCRM-146, VCRM-159) ni la conservación de adjuntos de VCRM-145 las eliminan; solo la supresión ordenada por el CTO las reduce según VCRM-165 (decisión K-4).
- **VCRM-165 [F1]** CUANDO se ejecuta una supresión ordenada por el CTO a solicitud del titular (VCRM-073 o VCRM-094), EL SISTEMA elimina el archivo de cada evidencia de autorización y de revocatoria de los leads suprimidos y conserva solo su huella mínima (4.5), sin nombre, contacto, número de documento ni otro dato personal en claro; la exportación posterior de esos leads (VCRM-074) solo muestra la huella mínima (decisión K-4).
- **VCRM-154 [F1]** CUANDO se ejecuta una supresión ordenada por el CTO (VCRM-073 o VCRM-094) o por vencimiento de un plazo (VCRM-146 o VCRM-159), EL SISTEMA envía como notificación crítica (4.5) una notificación de supresión de las copias ya enviadas —al CTO por Telegram y, si el lead estuvo alguna vez en «aceptado», también al abogado por Telegram y por correo— con el identificador del lead, la fecha-hora de la supresión y la indicación de suprimir las copias recibidas, sin ningún dato personal del titular (J-07).
- **VCRM-155 [F1]** SI una notificación de supresión (VCRM-154) queda «fallida» (VCRM-127), ENTONCES EL SISTEMA muestra una alerta en la lista de leads del CTO con el identificador del lead, el destinatario y el canal que fallaron, hasta que el CTO la marque «atendida por otro medio» (J-07).
- **VCRM-074 [F1]** CUANDO el CTO solicita la consulta de datos de un titular, EL SISTEMA genera una exportación con todos los datos asociados al lead (ficha, campos del handoff, historial, adjuntos y evidencias de autorización) como un archivo comprimido con un documento legible y los adjuntos, y la entrega al CTO por su chat privado con el bot; si supera el límite de envío de Telegram, la entrega en partes numeradas según VCRM-166 (PR-04 y PR-11 ratificadas; decisión K-5).
- **VCRM-166 [F1]** SI el archivo de una exportación (VCRM-074) supera el límite de tamaño de envío de documentos de Telegram, ENTONCES EL SISTEMA divide la exportación en partes numeradas «parte k de n», cada una dentro del límite y abrible por sí sola, con el documento legible en la parte 1 y cada adjunto completo en una sola parte, y las entrega en orden por el chat privado del CTO; si el envío de alguna parte falla, informa al CTO qué partes no se entregaron (decisión K-5).
- **VCRM-150 [F1]** CUANDO un usuario con permiso (4.4) registra en el bot una solicitud de un titular sobre un lead —consulta, o reclamo, incluidos los de supresión y revocatoria— con su fecha de recepción, EL SISTEMA la registra con tipo, medio, fecha de recepción y fecha límite —10 días hábiles para consultas y 15 días hábiles para reclamos y para las solicitudes «por clasificar» (VCRM-153), contados en días hábiles (4.5) desde el día hábil siguiente a la recepción— y la muestra al CTO; los plazos son configurables (4.6), y un valor configurado mayor que el tope legal se rechaza y rige el tope (J-05).
- **VCRM-151 [F1]** SI una solicitud de un titular sigue sin marcarse «atendida» 2 días hábiles después de su recepción, ENTONCES EL SISTEMA la escala al CTO por Telegram con el identificador de la solicitud y del lead, el tipo, la fecha de recepción y los días hábiles que faltan hasta su fecha límite, y repite el aviso cada día hábil hasta que el CTO la marque «atendida», lo que registra con autor y fecha-hora (J-05).
- **VCRM-152 [F1]** SI una solicitud de un titular llega a su fecha límite sin marcarse «atendida», ENTONCES EL SISTEMA la marca «vencida», la señala con una alerta en la lista de leads del CTO y mantiene el aviso diario de VCRM-151 hasta que el CTO la marque «atendida» (J-05).
- **VCRM-145 [F1]** EL SISTEMA conserva los adjuntos de un lead que pasó a «ganado» durante el plazo de conservación de adjuntos de clientes configurado (4.6: 10 años por defecto), contado desde la fecha-hora de ese paso, aunque el lead pase después a «baja»; al vencer el plazo, los elimina del almacén de adjuntos y registra la eliminación en la bitácora de auditoría (J-01).
- **VCRM-146 [F1]** CUANDO transcurre el plazo de supresión por estado final configurado (4.6: 12 meses por defecto) desde la última transición de un lead a «perdido» o a «baja», EL SISTEMA suprime los datos personales de ese lead según VCRM-073 —salvo los adjuntos que conserva VCRM-145—, aplica VCRM-154 y registra la supresión en la bitácora de auditoría con la causa «vencimiento del plazo»; la huella del contacto solo queda en la lista de supresión si el lead estaba en «baja» (J-01).
- **VCRM-158 [F1]** CUANDO un lead que no está en «aceptado» ni en «ganado» cumple el plazo de aviso configurado (4.6: 25 días por defecto) con la autorización de datos en «sin autorización», contado desde su registro o, si salió de «aceptado» después, desde esa salida, EL SISTEMA avisa por Telegram al comercial del lead (4.5) con el identificador del lead, el nombre y la fecha en que se suprimirá si no se registra la autorización (J-14).
- **VCRM-159 [F1]** CUANDO un lead que no está en «aceptado» ni en «ganado» cumple el plazo máximo configurado (4.6: 30 días por defecto, contados como en VCRM-158) y sigue «sin autorización», EL SISTEMA suprime sus datos personales según VCRM-073 sin añadir su huella a la lista de supresión, aplica VCRM-154, avisa por Telegram al comercial del lead (4.5) y al CTO con el identificador del lead y la causa, y registra la supresión en la bitácora de auditoría; si la autorización se registró antes de cumplirse el plazo, no suprime (J-14).
- **VCRM-147 [F1]** SI la eliminación o la supresión por vencimiento de un plazo (VCRM-145, VCRM-146 o VCRM-159) falla, ENTONCES EL SISTEMA no da por suprimido el lead, avisa al CTO por Telegram con el identificador del lead y la causa, y la reintenta en cada evaluación diaria siguiente hasta completarla (J-01, J-14).
- **VCRM-075 [F1]** EL SISTEMA registra en la bitácora de auditoría toda creación, modificación, exportación y supresión de datos de leads, con actor, acción, identificador del lead y fecha-hora.
- **VCRM-096 [F1]** EL SISTEMA no registra en la bitácora de auditoría nombres, datos de contacto, números de documento ni contenido de notas o adjuntos de titulares.

### 3.7 Transversales de operación

- **VCRM-077 [F1]** EL SISTEMA almacena las fechas-hora en UTC y las presenta y calcula (cadencias, franjas, festivos —calculados y extraordinarios, VCRM-167—, semana calendario) en la zona horaria America/Bogota.
- **VCRM-167 [F1]** EL SISTEMA trata como festivo, además de los festivos de Colombia calculados por ley, cada fecha de la lista configurable de festivos extraordinarios (4.6), en todo cálculo de días hábiles (4.5) y de franjas (decisión K-6).
- **VCRM-168 [F1]** SI una entrada de la lista de festivos extraordinarios no es una fecha válida con el formato año-mes-día o la fuente indicada para la lista no se puede leer, ENTONCES EL SISTEMA no aplica esa entrada o esa fuente, aplica las fechas válidas restantes y los festivos calculados, y avisa al CTO por Telegram con la entrada o la fuente rechazada y el motivo (decisión K-6).
- **VCRM-078 [F1]** EL SISTEMA conserva tras un reinicio del servicio todos los leads, estados, historiales, cadencias, propuestas y notificaciones pendientes confirmados antes del reinicio.
- **VCRM-162 [F1]** SI un parámetro con límite legal (4.6) se configura con un valor fuera de ese límite, o un plazo o límite se configura con un valor no positivo, ENTONCES EL SISTEMA no aplica ese valor, rige el límite legal (o el valor por defecto, si el valor no es positivo) y avisa al CTO por Telegram con el parámetro, el valor rechazado y el valor que rige (J-01, J-05, J-08, J-11, J-14).
- **VCRM-097 [F1]** EL SISTEMA genera cada noche un respaldo cifrado de la base del CRM (incluidas evidencias de autorización y adjuntos), lo transfiere fuera de la máquina que aloja el servicio (D2) y conserva cada respaldo durante el plazo de retención configurado (4.6: 30 días por defecto); al vencer ese plazo, elimina el respaldo, de modo que los datos suprimidos después de generarlo dejan de existir en los respaldos como máximo al terminar ese plazo (PR-12 ratificada; J-08).
- **VCRM-098 [F1]** SI la generación, el cifrado, la transferencia o la eliminación por vencimiento de un respaldo falla, ENTONCES EL SISTEMA avisa al CTO por Telegram y por correo con la causa y la fecha del último respaldo correcto (J-08; decisión N-11).

### 3.8 Conteo por fase

| Fase | Requisitos | Cantidad |
| :--- | :--- | :---: |
| F1 | 001–017, 046–052, 065, 066, 070, 071, 073–075, 077–098, 104, 105, 107, 109–118, 125–140, 144–147, 150–152, 154–156, 158, 159, 162–168 | 101 |
| F2 | 018–039, 067–069, 072, 076, 099–103, 119–124, 141–143, 148, 149, 153, 160, 161, 169–171 | 49 |
| F3 | 040–045, 053–056 | 10 |
| F4 | 057–064, 157 | 9 |
| **Total vigentes** | | **169** |
| Retirados | 106 y 108 (F1) | 2 |

Variación por las decisiones Q del 11/10/2026 (166 → 169 vigentes): +3 nuevos, todos en F2 (VCRM-169 y VCRM-170 lectura del buzón sin ruta pública, Q-2; VCRM-171 continuidad de datos y botones al activar F2, Q-1); 0 retirados; ningún cambio de fase. F2: 46 + 3 = 49.

Variación por las decisiones K del 05/10/2026 (160 → 166 vigentes): +6 nuevos, todos en F1 (VCRM-163 botón «Retractar» en la ficha, K-2; VCRM-164 y VCRM-165 conservación y huella mínima de la evidencia de autorización, K-4; VCRM-166 exportación en partes numeradas, K-5; VCRM-167 y VCRM-168 festivos extraordinarios configurables, K-6); 0 retirados; ningún cambio de fase. F1: 95 + 6 = 101.

Variación de la ronda final (A y B) (142 → 160 vigentes): +19 nuevos (VCRM-144 a VCRM-162: 13 en F1 —144 a 147, 150 a 152, 154 a 156, 158, 159 y 162—, 5 en F2 —148, 149, 153, 160 y 161— y 1 en F4 —157—); 1 retirado (VCRM-106, F1; hallazgo R-06); ningún cambio de fase. F1: 83 + 13 − 1 = 95; F2: 41 + 5 = 46; F4: 8 + 1 = 9. Los 19 identificadores VCRM-144 a VCRM-162 se cuentan íntegros en la ronda final, incluidos los fijados por delegación (VCRM-160 por P-29 y VCRM-161 por P-21) y el de los topes legales (VCRM-162).

Variación de la ronda 2 del CTO (126 → 142 vigentes): +17 nuevos (VCRM-127 a VCRM-143: 14 en F1 y 3 en F2); 1 retirado (VCRM-108, F1); ningún cambio de fase. F1: 70 + 14 − 1 = 83; F2: 38 + 3 = 41.

Variación respecto a la versión anterior (120), por la auditoría QA ronda 2: +6 nuevos (VCRM-121 a VCRM-126: 2 en F1 y 4 en F2); 0 retirados; ningún cambio de fase.

Variación de la ronda 1 del CTO (103 → 120): +17 nuevos (VCRM-104 a VCRM-120: 15 en F1 y 2 en F2); VCRM-016 y VCRM-017 pasan de F2 a F1 (decisión P-08); 0 retirados.

---

## 4. Modelo conceptual: estados, formatos, permisos y definiciones

### 4.1 Estados

| Estado | Significado | Fase |
| :--- | :--- | :---: |
| nuevo | Registrado por el comercial; sin contacto registrado. | F1 |
| contactado | El comercial registró al menos una interacción con el cliente (VCRM-089). | F1 |
| aceptado | El cliente aceptó la propuesta; dispara el handoff al CTO y al abogado. | F1 |
| rechazado | El cliente rechazó o se retractó tras aceptar; motivo registrado; sin cadencia activa (en F1, siempre; en F2, por falta de autorización o antes de asignarla) (decisión P-08). Puede volver a «contactado» o directamente a «aceptado», conservando su historial (decisión N-01). | F1 |
| en nutrición | Cadencia de seguimiento activa; genera propuestas sujetas al gate. | F2 |
| pausado | Cadencia detenida temporalmente por decisión de un usuario con permiso. | F2 |
| reactivado | El cliente volvió a mostrar interés; la cadencia (si la había) se detiene y el lead vuelve al flujo activo. | F2 |
| ganado | Final: contrato firmado; lo marcan el CTO o el abogado; solo admite «baja» (decisiones P-07, P-25 y N-05). | F1 |
| perdido | Final: lead descartado del todo, sin seguimiento; lo marcan el comercial del lead o el CTO, nunca el abogado; solo admite «baja»; si el contacto vuelve, se registra un lead nuevo (decisiones P-07, P-25, N-05 y A.1). | F1 |
| baja | El titular pidió no ser contactado; terminal para todo contacto comercial. | F1 |

El estado «cerrado» de la versión anterior queda sustituido por «ganado» y «perdido» (decisión P-07).

### 4.2 Transiciones permitidas

| Desde | Hacia | Disparador | Fase |
| :--- | :--- | :--- | :---: |
| nuevo | contactado | Usuario con permiso pulsa «Registrar contacto» (VCRM-089) (PR-07 ratificada) | F1 |
| rechazado | contactado | Usuario con permiso pulsa «Registrar contacto»; se conserva el historial (VCRM-089, VCRM-132) (decisión N-01) | F1 |
| nuevo, contactado, rechazado | aceptado | Marca de aceptación y confirmación ✅ (VCRM-046); desde «rechazado», se conserva el historial (VCRM-132) (decisión N-01) | F1 |
| nuevo, contactado | rechazado | Rechazo con motivo (VCRM-016) (decisión P-08) | F1 |
| aceptado | rechazado | Retractación con motivo y confirmación ✅/❌, registrada por el comercial del lead, el CTO o el abogado, con notificación al CTO y al abogado (VCRM-131, VCRM-113) (decisiones P-08, N-11 y A.1) | F1 |
| aceptado | ganado | Contrato firmado; lo marcan el CTO o el abogado (VCRM-115) (decisiones P-25 y A.1) | F1 |
| nuevo, contactado, rechazado | perdido | Descarte del lead; lo marcan el comercial del lead o el CTO (VCRM-116) (PR-23 ratificada; decisiones P-25 y A.1) | F1 |
| en nutrición, pausado, reactivado | perdido | Descarte del lead; lo marcan el comercial del lead o el CTO (VCRM-116) (PR-23 ratificada; decisiones P-25 y A.1) | F2 |
| rechazado | en nutrición | Sistema, al existir autorización vigente y cadencia asignada: al registrarse el rechazo (VCRM-018), al registrarse después la autorización (VCRM-121) o, para los rechazados de F1 con autorización vigente, al activarse F2, con la próxima acción contada desde la activación (VCRM-160) (decisión P-29) | F2 |
| en nutrición | pausado | Usuario con permiso pausa (VCRM-020) | F2 |
| pausado | en nutrición | Usuario con permiso reanuda (VCRM-022) | F2 |
| en nutrición, pausado, rechazado | reactivado | Comercial registra interés renovado (VCRM-024) (PR-16 ratificada) | F2 |
| reactivado | contactado, aceptado, rechazado | Comercial registra el nuevo resultado | F2 |
| cualquier estado salvo baja | baja | Solicitud del titular (VCRM-070; en F2 también VCRM-102 y VCRM-124) | F1 |

Notas:

- «Reanudar» (pausado → en nutrición) es una acción sobre la cadencia; «reactivado» es un estado del lead. No se confunden.
- «Ganado» y «perdido» son finales del ciclo comercial: no admiten más transición que «baja», que es un derecho del titular y procede desde cualquier estado (VCRM-117). Si el contacto de un lead «perdido» vuelve, se registra un lead nuevo (VCRM-135) (decisión N-05).
- Un lead «aceptado» no pasa directamente a «perdido»: primero se registra la retractación a «rechazado» (el abogado puede registrarla; el «perdido» posterior lo marcan el comercial del lead o el CTO, decisión A.1), para que el CTO y el abogado reciban la notificación de retractación (VCRM-133) (PR-23 ratificada).
- Desde «baja» no hay transiciones; un nuevo registro con el mismo contacto queda bloqueado (VCRM-088) y todo contacto comercial también (VCRM-071).
- ~~En F1, un lead «rechazado» (incluido uno retractado) solo puede pasar a «perdido» o «baja»; la vuelta al flujo activo («reactivado») llega en F2.~~ RETIRADA (decisión N-01): en F1, un lead «rechazado» (incluido uno retractado) puede volver a «contactado» o directamente a «aceptado», conservando su historial (VCRM-132); además puede pasar a «perdido» o «baja». En F2 se suma «reactivado».

### 4.3 Formato de registro y de edición (F1–F3) (PR-01 ratificada)

En F1–F3 no hay interpretación de lenguaje natural; el registro y la edición usan un formato estructurado. El texto libre llega en F4 (VCRM-059).

**Orden de registro:** comando «/nuevo» seguido de campos separados por punto y coma, en este orden:

| Posición | Campo | Obligatorio | Regla |
| :---: | :--- | :--- | :--- |
| 1 | Nombre | Sí | No vacío. |
| 2 | Teléfono | Sí, si el campo 3 está vacío | Normalizable a E.164 (VCRM-005). |
| 3 | Correo | Sí, si el campo 2 está vacío | Forma usuario@dominio (VCRM-005). |
| 4 | Empresa | No | Texto libre. |
| 5 | Nota inicial | No | Todo el texto restante, incluidos puntos y coma; se guarda como primera nota (VCRM-009). |

- Se ignoran los espacios al inicio y al final de cada campo; los campos vacíos se dejan entre separadores y los opcionales finales pueden omitirse.
- Ejemplo: «/nuevo Ana Pérez; 300 123 4567; ana@empresa.co; Empresa SAS; Interesada en el plan anual».
- Ejemplo solo con correo: «/nuevo Ana Pérez; ; ana@empresa.co».

**Campos del handoff (decisión P-05).** Son los datos mínimos que necesita el abogado; se completan con la orden de edición y su completitud se evalúa según VCRM-111.

| Campo del handoff | Nombre en «/editar» | Obligatorio para un handoff completo | Regla |
| :--- | :--- | :--- | :--- |
| Tipo de cliente (PR-24 ratificada) | tipo | Sí | «persona natural» o «empresa». |
| Nombre o razón social | nombre (persona natural) o empresa (empresa) | Sí | Para persona natural, el campo Nombre; para empresa, el campo Empresa como razón social. No vacío. |
| Documento de identificación (decisión N-05) | documento | Sí | Tipo «cédula de ciudadanía», «NIT», «cédula de extranjería» o «pasaporte» seguido del número; número no vacío. |
| Representante legal | representante | Solo si el tipo de cliente es «empresa» | No vacío. |
| Teléfono de contacto | telefono | Sí | VCRM-005. |
| Correo de contacto | correo | Sí | VCRM-005. |
| Servicio contratado | servicio | Sí | No vacío. |
| Valor acordado | valor | Sí | No vacío (texto con el valor y su moneda). |
| Plazo o fecha de inicio | plazo | Sí | No vacío. |

- En el registro basta un dato de contacto (VCRM-003); para el handoff completo se requieren teléfono y correo (decisión P-05).
- Ejemplo de edición: «/editar L-0042; documento; NIT 900123456-7».

**Orden de edición:** comando «/editar» seguido de identificador corto del lead; campo; nuevo valor. Campos editables: nombre, teléfono, correo, empresa y los campos del handoff de la tabla anterior. Ejemplo: «/editar L-0042; correo; ana.perez@empresa.co».

### 4.4 Matriz de permisos (PR-04 ratificada con ajuste)

«Propios» = leads asignados a ese comercial. La matriz está ratificada por el CTO (ronda 2, P-06) con ajustes: «ve solo sus leads» del comercial incluye editar, agregar notas y agregar adjuntos de esos leads; el abogado ve solo los leads que alguna vez estuvieron en «aceptado», marca «ganado» y registra la retractación, pero no marca «perdido» (decisión A.1, que sustituye a P-26). Lo dirigido al comercial del lead va al CTO cuando el lead es suyo o no tiene comercial (decisión A.2; 4.5). Las celdas marcadas con I-NN son interpretaciones confirmadas por delegación del CTO (sección 8).

| Acción | Comercial | CTO | Abogado |
| :--- | :---: | :---: | :---: |
| Registrar lead | Sí (queda asignado a él) | Sí | No |
| Agregar notas y adjuntos | Propios | Todos | No |
| Editar datos del lead, incluidos los del handoff (VCRM-080) | Propios | Todos | No |
| Ver lista y fichas | Solo propios (decisión P-04) | Todos (decisión P-04) | Solo los que alguna vez estuvieron en «aceptado» (decisión A.1) |
| Registrar contacto (también desde «rechazado», decisión N-01), rechazo y reactivación | Propios | Todos | No |
| Registrar la retractación de un «aceptado» con confirmación ✅/❌ (VCRM-131) | Propios | Todos | Visibles para él (decisión A.1) |
| Marcar «aceptado» y confirmar | Propios | Todos | No |
| Marcar «ganado» | No (decisión P-25) | Todos (decisión P-25) | Visibles para él (decisiones P-25 y A.1) |
| Marcar «perdido» | Propios (decisión P-25) | Todos (decisión P-25) | No (decisión A.1; resuelve P-32) |
| Registrar una baja comunicada por el titular | Propios | Todos | No |
| Registrar una consulta o un reclamo del titular (VCRM-150) y clasificar una respuesta «por clasificar» (F2, VCRM-153) | Propios | Todos | No |
| Marcar «atendida» una solicitud de un titular (VCRM-151, VCRM-152) | No | Sí | No |
| Pausar, reanudar y cambiar frecuencia de cadencia; decidir sobre envíos fallidos | Propios | Todos | No |
| Aprobar ✅/❌ mensajes al cliente final (F2, por chat individual con el bot) | Propios (decisión P-16) | Todos (decisión P-16) | No |
| Solicitar la autorización de datos al titular | Propios | Todos | No |
| Registrar la autorización con documento firmado o captura (VCRM-138) | Propios (decisión N-04) | Todos (I-07) | No |
| Confirmar ✅/❌ una respuesta del titular propuesta como autorización (F2, VCRM-119) | Propios (decisión N-04) | Leads asignados a él o sin comercial (decisión A.2; I-07) | No |
| Exportar y suprimir datos de un titular | No | Sí | No |
| Dar de alta y de baja usuarios por el bot y reasignar leads (VCRM-144, VCRM-091) | No | Sí (decisión A.5) | No |
| Recibir el aviso de registro duplicado de otro comercial (VCRM-137) | No | Sí, por Telegram (decisión P-11; I-06) | No |
| Marcar una notificación fallida como «atendida por otro medio» | No | Sí | No |
| Consultar materiales (F3) | Sí | Sí | No |
| Recibir notificaciones de aceptación, retractación y actualización del handoff | No | Sí, por Telegram (decisión P-01) | Sí, por Telegram y correo (decisión P-01) |
| Recibir el correo de respaldo (VCRM-050) | Propios, por correo (decisiones P-01 y P-02) | Sí, por correo (decisiones P-01 y P-02) | No |
| Recibir el aviso de fallo del respaldo (VCRM-129) | Propios, por Telegram y correo (decisión N-11) | Sí, por Telegram y correo (decisión N-11) | No |
| Recibir la notificación de supresión de copias (VCRM-154) | No | Sí, por Telegram (J-07) | Sí, por Telegram y correo, si el lead estuvo alguna vez en «aceptado» (J-07) |
| Recibir los avisos de supresión por falta de autorización (VCRM-158, VCRM-159) | Propios, por Telegram (J-14) | Sí, por Telegram (J-14; decisión A.2) | No |
| Recibir borradores de contrato (F3) | No | Sí | Sí |

### 4.5 Definiciones

- **Entregado:** un mensaje saliente consta como entregado cuando la API del canal confirma su aceptación (para Telegram, respuesta de éxito con identificador del mensaje; para correo, aceptación por el servidor o la API del proveedor de correo con identificador del mensaje). No implica lectura ni llegada al buzón o al dispositivo. Si la confirmación no llega (p. ej., timeout), el intento cuenta como fallido y se reintenta según VCRM-127; en ese caso el destinatario podría recibirlo dos veces, riesgo aceptado frente a perder un aviso de cierre.
- **Fallido:** estado de un mensaje saliente interno que no consta como entregado tras el calendario de reintentos de VCRM-127 (o sin más intentos, en el caso de VCRM-140) (decisiones P-02 y A.3). Las respuestas interactivas del bot y las notificaciones internas no críticas que no constan como entregadas quedan «fallidas» sin reintento (VCRM-012).
- **Correo de respaldo:** correo al CTO y al comercial del lead que avisa de una notificación de aceptación, retractación o actualización del handoff que quedó «fallida» (VCRM-050); nunca se envía en paralelo a los reintentos (VCRM-128).
- **Notificación interna:** mensaje del sistema dirigido al CTO, a un comercial o al abogado, por Telegram o por correo; nunca al cliente final.
- **Notificación crítica (decisión A.3):** notificación interna de aceptación, de retractación o de actualización del handoff, a cualquier destinatario y por cualquier canal (incluido el correo al abogado); el correo de respaldo (VCRM-050); el aviso de fallo del respaldo (VCRM-129), y la notificación de supresión de copias (VCRM-154). Solo estas siguen el calendario de intentos de VCRM-127 y se persisten antes de enviarse (VCRM-049).
- **Notificación interna no crítica:** toda notificación interna que no es crítica (p. ej., avisos de duplicado, de cadencia, de autorización faltante, de solicitudes de titulares, de respaldos y de supresión por plazo).
- **Respuesta interactiva del bot:** mensaje con el que el bot contesta a una orden o pulsación de un usuario autorizado (confirmaciones, fichas, listas, peticiones de dato y mensajes de error); no se reintenta (VCRM-012; decisión A.3).
- **Día hábil:** de lunes a viernes, excluidos los festivos de Colombia —los calculados por ley y los extraordinarios de la lista configurable (4.6; VCRM-167)—, en hora de Bogotá (VCRM-077).
- **Evento entrante procesado:** mensaje o pulsación cuyo identificador único asignado por el canal quedó registrado como procesado (VCRM-079).
- **Huella de contacto:** valor derivado del teléfono o correo normalizado que permite comprobar si un contacto coincide, pero no recuperar el contacto sin una clave secreta del sistema.
- **Coincidencia de contacto (duplicado) (decisión K-3):** un lead coincide con un contacto cuando su teléfono normalizado es exactamente igual al teléfono normalizado del contacto o su correo normalizado es exactamente igual al correo normalizado del contacto. Las coincidencias no se encadenan: un lead que solo comparte un dato con otro lead coincidente, y no con el contacto, no coincide.
- **Leads del mismo titular (decisión K-3):** el lead indicado y los leads que tienen una coincidencia de contacto con el teléfono o el correo normalizados de ese lead, sin encadenar. Ejemplo: si A y B comparten teléfono y B y C comparten correo, la supresión ordenada sobre A alcanza a A y B, no a C.
- **Huella mínima de una evidencia (decisión K-4):** lo que queda de una evidencia de autorización o de revocatoria tras una supresión a solicitud del titular: un valor derivado del contenido del archivo que permite comprobar que un documento presentado coincide con el original, junto con el estado, el medio, la fecha-hora, la versión del aviso de privacidad, las finalidades informadas y el usuario interno que la registró; sin el archivo ni datos personales del titular en claro.
- **Semana calendario:** desde el lunes 00:00 hasta el domingo 23:59 en hora de Bogotá (PR-19 ratificada; J-11).
- **Franja permitida:** la definida en VCRM-072.
- **Autorización vigente:** estado «autorizada» con evidencia registrada (VCRM-065) y sin revocatoria posterior.
- **Medios válidos de autorización (decisión N-04):** (a) respuesta del titular al correo de solicitud, propuesta por el sistema y confirmada con ✅ por el comercial (VCRM-119, VCRM-141; F2); (b) documento firmado o captura que adjunta el comercial (VCRM-138; desde F1). No hay detección automática de una palabra de aceptación ni otros medios válidos (VCRM-139).
- **Comercial del lead:** el comercial asignado al lead en ese momento (VCRM-003, VCRM-093). Cuando el lead está asignado al CTO o «sin comercial asignado» (VCRM-092), todo lo dirigido al comercial del lead lo recibe el CTO, una sola vez por canal (decisión A.2; resuelve P-30 y R-01).
- **Respuesta del titular:** mensaje recibido por el canal de envío al cliente final (F2).
- **Texto nuevo de una respuesta:** el texto redactado por el remitente en esa respuesta, excluido el contenido citado o reproducido de mensajes anteriores (incluida la solicitud o el mensaje al que responde).
- **Palabra clave presente:** «BAJA» está presente en una respuesta cuando aparece en su texto nuevo como palabra completa —delimitada por el inicio o el final del texto, espacios o signos de puntuación—, sin distinguir mayúsculas de minúsculas ni letras con o sin tilde. Ejemplos: «baja» y «Baja.» cuentan; «trabajamos» y «bajamos» no; una palabra clave que solo aparece en el contenido citado no cuenta. «ACEPTO» dejó de ser palabra clave (decisión N-04; PR-25 reemplazada). **Riesgo conocido:** expresiones como «temporada baja» o «prioridad baja» cuentan como «BAJA» y aplicarían una baja no pedida; el CTO acepta ese riesgo frente a retrasar una baja que debe honrarse de inmediato (decisión P-31; J-06).
- **Lead asociado a una respuesta:** el lead al que se envió el mensaje que la respuesta referencia en su hilo; si la respuesta no trae esa referencia o la referencia no corresponde a ningún mensaje enviado, el único lead cuya huella de contacto coincide con la huella de la dirección del remitente. Una respuesta es «no asociable» si de este modo no se identifica exactamente un lead (ninguno o varios por la huella) (PR-27 ratificada).
- **Cabecera de baja por correo:** cabecera estándar del mensaje de correo que permite al cliente de correo del titular ofrecer una opción de «cancelar suscripción» que envía un mensaje al buzón del sistema, sin abrir páginas web (PR-26 ratificada; J-06).

### 4.6 Parámetros configurables

Valores por defecto fijados por el CTO, por el abogado (por delegación) o por el planificador con delegación del CTO (sección 8). Un parámetro con límite legal no admite valores fuera de ese límite (VCRM-162).

| Parámetro | Por defecto | Límite | Requisitos | Origen |
| :--- | :--- | :--- | :--- | :--- |
| Franja permitida para contactar al cliente final | Lunes a viernes 07:00–19:00 y sábados 08:00–15:00; sin domingos ni festivos | No puede ampliarse | VCRM-072, 100 | J-11 |
| Contactos por lead y por semana calendario | 1 | Máximo 1 | VCRM-076, 101 | J-11; decisión P-19 |
| Plazo del gate antes de expirar una propuesta | 48 horas | — | VCRM-034 | Decisión P-17 |
| Cadencia por motivo de rechazo | Para cada motivo: un paso cada 30 días, 3 pasos | — | VCRM-018, 026, 121, 160 | Decisión P-17 |
| Textos fijos por motivo de rechazo | Sin valor (los redacta y aprueba el CTO) | — | VCRM-027, 161 | Decisión P-21 |
| Plazo máximo de transcripción | 10 minutos | — | VCRM-057 | Decisión P-23 |
| Plazo de respuesta a consultas / a reclamos y solicitudes «por clasificar» | 10 / 15 días hábiles | Máximo 10 / 15 | VCRM-150, 153 | J-05 (Ley 1581, arts. 14 y 15) |
| Escalado al CTO de una solicitud sin atender | 2 días hábiles | Máximo 2 | VCRM-151 | J-05 |
| Conservación de adjuntos de leads en «ganado» | 10 años | Mínimo 10 años | VCRM-145 | J-01 |
| Supresión tras «perdido» o «baja» | 12 meses | Máximo 12 meses | VCRM-146 | J-01 |
| Aviso / plazo máximo de un lead «sin autorización» | 25 / 30 días | Máximo 30 días; el aviso, antes del plazo máximo | VCRM-158, 159 | J-14 |
| Retención de respaldos | 30 días | Máximo 30 días | VCRM-097 | PR-12; J-08 |
| Referencia a la política de tratamiento y al aviso de privacidad (URL o texto, con versión) | Sin valor | — | VCRM-148, 149 | J-02 |
| Encargados mencionados en la solicitud de autorización | Telegram y Google | — | VCRM-148 | J-10 |
| Buzón remitente y credenciales | Sin valor | — | VCRM-105, 140 | Decisión P-27 |
| Buzón de consulta de respuestas y su credencial | Sin valor | — | VCRM-169, 170 | Decisión Q-2 |
| Período de consulta del buzón | 5 minutos | Mínimo 1 minuto | VCRM-169 | Decisión Q-2 |
| Cadencia del motivo «momento no oportuno» | Un paso cada 30 días, 3 pasos (el CTO puede fijar 60 días) | — | VCRM-018, 023 | Decisión Q-3 |
| Tipo de contenido por motivo | Precio: propuesta de valor; momento: recordatorio; proveedor y no interesado: contenido educativo; otro: genérico | — | VCRM-027, 161 | Decisión Q-3 |
| Festivos extraordinarios (fechas decretadas adicionales a los festivos calculados por ley), en la configuración del sistema y/o en un archivo de fechas | Sin valor (solo festivos calculados) | Fechas con formato año-mes-día | VCRM-167, 168 | Decisión K-6 |

---

## 5. Requisitos de cumplimiento (Colombia)

Interpretación del planificador revisada por el abogado (Juan José) mediante las respuestas J-01 a J-14, aceptadas por delegación el 04/10/2026 (sección 9). No sustituye la asesoría jurídica: los textos legales (política, aviso, contratos) los redacta y mantiene el abogado.

| # | Obligación | Fuente normativa | Efecto en el sistema |
| :--- | :--- | :--- | :--- |
| L-1 | Autorización **previa, expresa e informada** del titular para tratar sus datos personales. | Ley 1581 de 2012, art. 9; Decreto 1377 de 2013, arts. 5 y 7 (compilado en el Decreto 1074 de 2015). | Estado de autorización por lead (VCRM-065/066); sin autorización no hay contacto comercial (VCRM-067); un lead «sin autorización» se suprime a los 30 días (VCRM-158, VCRM-159; J-14). |
| L-2 | **Finalidad** informada; el tratamiento se limita a ella. | Ley 1581, arts. 4 (b) y 12. | Cada autorización guarda las finalidades informadas y la versión del aviso (VCRM-065, VCRM-148) (J-02). |
| L-3 | **Prueba** de la autorización, conservable y consultable. Medios válidos: escrito, oral o conductas inequívocas. | Decreto 1377 de 2013, arts. 7 y 8. | Evidencia referenciada por lead: medio, fecha-hora, versión y soporte (VCRM-065, VCRM-068, VCRM-119, VCRM-138, VCRM-141); respaldo cifrado fuera de la máquina (VCRM-097). Por decisión del CTO, los únicos medios válidos son (a) la respuesta del titular al correo, propuesta por el sistema y confirmada por el comercial, sin páginas públicas (decisiones P-10 y N-04), y (b) el documento firmado o la captura que adjunta el comercial (decisión N-04); el abogado acepta ambas como prueba (J-03, J-04). |
| L-4 | **Aviso de privacidad** cuando no se entrega la política al momento de la recolección. | Decreto 1377 de 2013, arts. 14 y 15. | La solicitud de autorización incluye el aviso (VCRM-068); el aviso es versionado y lo redacta el abogado; el sistema solo referencia su URL o texto desde la configuración (VCRM-148, VCRM-149; J-02). |
| L-5 | **Revocatoria y supresión** a solicitud del titular, salvo deber legal o contractual de conservar. | Ley 1581, art. 8 (e); Decreto 1377, art. 9. | Baja (VCRM-070/071/102/124), supresión (VCRM-073), excepción por deber legal o contractual (VCRM-094), lista de supresión solo con huella (VCRM-095) y bitácora sin datos personales (VCRM-096). La supresión cubre base de datos, adjuntos y leads retractados, y notifica la supresión de las copias enviadas al CTO y al abogado (VCRM-073, VCRM-154, VCRM-155; J-07). Los respaldos previos a una supresión conservan los datos como máximo 30 días (VCRM-097; J-08). La baja se aplica en el momento en que se registra o se recibe, sin confirmación humana (VCRM-070, VCRM-102, VCRM-124; decisión P-31; J-05, J-06). Conservación por estado final: adjuntos de «ganado» 10 años; datos de «perdido» o «baja» suprimidos a los 12 meses (VCRM-145 a VCRM-147; J-01). |
| L-6 | **Consultas** (máx. 10 días hábiles) y **reclamos** (máx. 15 días hábiles). | Ley 1581, arts. 14 y 15. | Exportación de datos del titular (VCRM-074); registro de cada solicitud con su fecha límite, escalado al CTO si no se atiende en 2 días hábiles y alerta de vencimiento (VCRM-150 a VCRM-153; J-05). La respuesta al titular la da una persona; si se envía por el sistema, pasa por el gate (decisión P-09) y el escalado cubre el riesgo de que el aprobador no actúe (decisión P-28). |
| L-7 | **Política de tratamiento** de la información adoptada por el responsable. | Decreto 1377, art. 13. | La redacta, publica y mantiene el abogado fuera del sistema; el sistema solo referencia su URL o texto desde la configuración (VCRM-148, VCRM-149; decisión P-20; J-02). |
| L-8 | **Transmisión o transferencia internacional** de datos (proveedores de mensajería, correo, nube, IA y transcripción fuera de Colombia). | Ley 1581, art. 26; Decreto 1377, arts. 24 y 25. | Minimización hacia IA externa (VCRM-064); contratos de transmisión con encargados; ver el análisis de opciones. Desde F1 la ficha completa del cliente (incluido el número de documento de identificación) viaja por correo al abogado y por Telegram al CTO (VCRM-048): el proveedor de correo y Telegram actúan como encargados, y si el abogado no es parte de la planta de Kaisen, la entrega de la ficha podría ser una transmisión a un encargado. Respuesta: el abogado actúa como encargado y recibe solo los 7 campos del handoff (VCRM-048, VCRM-156; J-09); Telegram y Google se aceptan como encargados y se mencionan en la autorización (VCRM-148; J-10); ningún dato personal sin seudonimizar va a servicios de IA externos (VCRM-064, VCRM-157; F4; J-10). |
| L-9 | **Ley 2300 de 2023 («dejen de fregar»):** contacto para ofertas comerciales solo por los canales autorizados por el consumidor, en franja de lunes a viernes 07:00–19:00 y sábados 08:00–15:00, sin domingos ni festivos, con límites de frecuencia por semana. | Ley 2300 de 2023, arts. 2 y 3. | Franja horaria (VCRM-072/100) y tope semanal (VCRM-076/101). Aplica también a clientes empresa (B2B); máximo 1 contacto por semana calendario y por lead (decisión P-19; J-11). |
| L-10 | **Registro Nacional de Bases de Datos (RNBD)** ante la SIC, según umbral de activos del responsable. | Decreto 090 de 2018 (modifica el Decreto 1074 de 2015). | Ninguno en el sistema; la gestiona el responsable fuera del sistema (J-12). |
| L-11 | **Registro de Números Excluidos** de la CRC para mensajes comerciales por SMS o llamadas. | Regulación CRC sobre RNE. | Solo aplica si se usan SMS o llamadas (fuera de alcance hoy); el canal al cliente en F2 es solo el correo (decisión P-18); WhatsApp queda fuera hasta F4 y requerirá revisión (J-12). |
| L-12 | **Datos en audio:** las notas de voz del comercial pueden contener datos personales de terceros; si se graba la voz del cliente, podría tratarse como dato biométrico o sensible. | Ley 1581, arts. 5 y 6. | El sistema transcribe audios del comercial, no del cliente; grabar al cliente queda fuera de alcance; el tratamiento de audios se revisa al llegar F4 (J-12). |

---

## 6. Preguntas

Ninguna se ha inventado. Tras la ronda final del 04/10/2026 no queda ninguna pregunta abierta: las del CTO se resolvieron con los ajustes A o por delegación del CTO en la recomendación del planificador, y las del abogado con las respuestas J-01 a J-14 aceptadas por delegación (secciones 8 y 9). Prioridad histórica: **A** bloqueaba F1; **B**, F2; **C**, F3/F4.

### 6.1 Pendientes

Ninguna.

### 6.2 Resueltas (ronda 1, 04/10/2026)

Respuestas del CTO transcritas tal como las dio; la trazabilidad a requisitos y propuestas está en la sección 8.

| ID | Pregunta (resumen) | Respuesta del CTO |
| :--- | :--- | :--- |
| P-01 | Abogado, canal del aviso y canal alternativo. | «El abogado es Juan José. Al aceptarse un lead se le avisa por Telegram y por correo: el correo lleva la ficha completa y Telegram sirve como alerta inmediata. Si Telegram falla, el respaldo para avisar al CTO y al comercial es el correo.» |
| P-03 | Número de comerciales hoy y en 12 meses. | «Hoy hay 1 comercial (Duván) y se esperan 2 en 12 meses.» |
| P-04 | Visibilidad de leads entre comerciales. | «Cada comercial ve solo sus leads; el CTO ve todos.» |
| P-05 | Campos mínimos del handoff. | «Campos mínimos para el abogado: nombre o razón social, cédula o NIT, representante legal (si es empresa), teléfono y correo de contacto, servicio contratado, valor acordado, plazo o fecha de inicio.» |
| P-06 (parcial) | Ratificación de PR-05 y PR-06. | «RATIFICADAS. Hay confirmación ✅/❌ antes de marcar “Aceptado”, y se notifica aunque falten campos, indicando cuáles faltan.» El resto de propuestas sigue pendiente (6.1). |
| P-07 | Significado de «cerrado». | «Hay dos estados finales distintos: “Ganado” (contrato firmado) y “Perdido” (descartado del todo, sin seguimiento).» Quién los marca no fue respondido (P-25). |
| P-08 | Rechazo en F1 y retractación. | «Un lead “Aceptado” puede retractarse. Pasa a “Rechazado” con motivo y se notifica al CTO y a Juan José. Desde F1 se registra el rechazo con su motivo, aunque la cadencia llegue en F2.» |
| P-09 | Mensajes automáticos al cliente final. | «Ningún mensaje al cliente final sale de forma automática; todo pasa por el gate ✅/❌.» |
| P-10 | Ruta pública mínima. | «NO se autoriza ninguna ruta pública. La autorización de datos y la baja se hacen respondiendo el correo, y queda [VERIFICAR CON ABOGADO] si esa prueba es suficiente. Se mantiene la postura Zero-Trust.» |

### 6.2 bis Resueltas (ronda 2, 04/10/2026)

Respuestas del CTO transcritas tal como las dio (en P-27 se omite el nombre del archivo de configuración); la trazabilidad está en la sección 8. Las respuestas a los hallazgos N-01, N-04, N-05 y N-11 de la auditoría QA ronda 2 se registran solo en la sección 8.

| ID | Pregunta (resumen) | Respuesta del CTO |
| :--- | :--- | :--- |
| P-02 | Plazo «inmediato» y reintentos. | «La aceptación se notifica en menos de 1 minuto. Si Telegram falla, se hacen 3 reintentos (a los 0, 1 y 5 minutos). El correo de respaldo al CTO y al comercial sale SOLO si Telegram sigue fallando tras los reintentos; no va en paralelo. El abogado recibe siempre Telegram y correo (P-01). Esto sustituye el “reintento indefinido” de N-05.» |
| P-06 (propuestas de F1) | Ratificación del resto de propuestas. | «PR-01, PR-02, PR-03, PR-07, PR-08, PR-09, PR-10, PR-11, PR-12 (sujeta al abogado), PR-13 y PR-24: RATIFICADAS. PR-04: RATIFICADA con un ajuste: el abogado ve aceptados, ganados y PERDIDOS (P-26). “Ve solo sus leads” incluye editar, notas y adjuntos.» PR-23 se ratificó con P-25. Siguen abiertas las de F2 a F4 (6.1). |
| P-11 | Duplicados. | «Duplicados (mismo teléfono o correo): se avisa y NO se crea otro lead. Si es del mismo comercial, se le ofrece abrirlo. Si es de otro comercial, no se le muestran los datos y se notifica al CTO para que lo asigne.» |
| P-12 (tamaño) | Tamaño máximo de adjunto. | «Adjuntos de hasta 20 MB.» La conservación sigue abierta para el abogado (6.1). |
| P-13 | Leads existentes. | «No hay migración masiva. Duván cargará sus leads previos uno a uno por el bot, y quedan “sin autorización” hasta que él la registre.» |
| P-14 | Instancia y motor de producción. | «El CRM corre en la misma instancia OCI que Jericó. SQLite en producción queda AUTORIZADO como excepción temporal a D1, con SQL portable a PostgreSQL 16.» |
| P-25 | Quién marca ganado y perdido; PR-23. | «“Ganado” lo marcan el CTO o el abogado. “Perdido” lo marcan el comercial, el CTO o el abogado.» «PR-23 RATIFICADA: no se pasa de “aceptado” a “perdido” directamente; primero se registra la retractación.» |
| P-26 | Visibilidad del abogado. | «El abogado ve solo los leads aceptados, ganados y perdidos.» |
| P-27 | Buzón remitente del correo interno. | «El buzón remitente y las credenciales se configuran después: déjalo como parámetro de configuración […], sin valor fijo.» |

### 6.2 ter Resueltas (ronda final, 04/10/2026)

El CTO aceptó todas las recomendaciones pendientes y delegó las decisiones restantes en el criterio del planificador; el abogado aceptó por delegación J-01 a J-14. Detalle y trazabilidad en las secciones 8 y 9.

| ID | Prio. | Tema | Resolución |
| :--- | :---: | :--- | :--- |
| P-32 | A | «Perdido» marcado por el abogado | Decisión A.1 del CTO: el abogado marca «ganado» y registra la retractación; «perdido» lo marcan solo el comercial del lead o el CTO; el abogado ve los leads que alguna vez estuvieron en «aceptado». |
| P-30 | A | Comercial del lead asignado al CTO o sin comercial | Decisión A.2 del CTO: todo lo dirigido al comercial del lead va al CTO. |
| P-12 | A | Conservación de adjuntos | J-01: adjuntos de «ganado» 10 años; datos de «perdido» o «baja» suprimidos a los 12 meses del estado final (VCRM-145 a VCRM-147). |
| P-06 | B | Ratificación del resto de propuestas | El CTO acepta todas las recomendaciones pendientes: PR-14 a PR-22, PR-26 y PR-27 quedan ratificadas (sección 7). |
| P-31 | B | Baja por respuesta al correo | Por delegación: la baja por palabra clave o por cabecera se aplica de inmediato y sin confirmación humana (J-06); el riesgo de falsos positivos se acepta. |
| P-33 | B | Reintentos de envíos al cliente final | Por delegación: 3 intentos en total (0, 1 y 5 minutos), solo dentro de la franja permitida (VCRM-038). |
| P-15 | B | Volumen y presupuesto | Por delegación: volumen bajo (menos de 100 correos al día) y gasto objetivo de USD 0 al mes con cuotas gratuitas; se revisa si se supera. No genera requisitos. |
| P-16 | B | Aprobador del gate | Por delegación: aprueba el comercial del lead por chat individual con el bot; el CTO puede aprobar cualquier lead y recibe las de sus leads y los sin comercial (A.2). |
| P-17 | B | Cadencias y plazo del gate | Por delegación: por defecto, un paso cada 30 días y 3 pasos por motivo, configurable (4.6); al terminar, el lead no pasa solo a «perdido» (VCRM-026); gate de 48 horas; «Cancelar envío» y la expiración saltan al paso siguiente. |
| P-18 | B | Canal al cliente | Por delegación: en F2, solo correo desde el buzón del sistema; WhatsApp, fuera hasta F4. |
| P-19 | B | Tipo de cliente y frecuencia | Clientes empresa y personas naturales; máximo 1 contacto por lead y semana calendario (J-11). |
| P-20 | B | Política y aviso | J-02: los redacta y mantiene el abogado; el sistema referencia su URL o texto desde la configuración (VCRM-148, VCRM-149). |
| P-21 | B | Textos de F2 | Por delegación: los textos fijos por motivo los redacta y aprueba el CTO; sin texto configurado no se genera la propuesta (VCRM-161). |
| P-28 | B | Acuse de baja y plazos | J-05: la baja se procesa al registrarse; consultas y reclamos con plazo, escalado a los 2 días hábiles y alerta de vencimiento (VCRM-150 a VCRM-153). |
| P-29 | B | Rechazos acumulados en F1 al activar F2 | Por delegación: los que tienen autorización vigente entran en cadencia al activarse F2, con la próxima acción contada desde la activación; los demás quedan en «rechazado» (VCRM-160). |
| P-22 | C | Plantilla de contrato y Google | Por delegación: la plantilla la entrega y mantiene el abogado (VCRM-053); el formato y la cuenta de Google se fijan en el plan de F3. |
| P-23 | C | Voz, IA y proveedores | Por delegación: transcripción en la propia instancia con plazo de 10 minutos; a la IA externa solo van datos seudonimizados (VCRM-057, VCRM-064, VCRM-157; J-10). |
| P-24 | C | IA y cambios | Por delegación: la IA propone y el comercial confirma con ✅ (VCRM-059). |

### 6.3 Propuesta de siguiente ronda

Ninguna: no quedan preguntas abiertas. Siguiente paso: pasada final del reviewer sobre los ajustes A y B y, después, plan de F1.

---

## 7. Propuestas a ratificar

Decisiones del planificador no pedidas de forma explícita por el CTO. Tras la ronda final (04/10/2026), en la que el CTO aceptó todas las recomendaciones pendientes, todas están ratificadas y rigen, salvo PR-25, «REEMPLAZADA», que no rige y se conserva tachada junto con el reemplazo decidido por el CTO. La columna «Alternativa» queda como registro de la opción descartada.

| ID | Fase | Estado | Propuesta | Requisitos | Alternativa si se descarta |
| :--- | :---: | :--- | :--- | :--- | :--- |
| PR-01 | F1 | **RATIFICADA** (04/10/2026, ronda 2) | Registro y edición con formato estructurado (4.3); texto libre solo en F4. | VCRM-003, 004, 080; 4.3 | Botones paso a paso (un mensaje por campo). |
| PR-02 | F1 | **RATIFICADA** (04/10/2026, ronda 2) | Indicativo +57 por defecto para teléfonos sin indicativo. | VCRM-005 | Exigir siempre el indicativo. |
| PR-03 | F1 | **RATIFICADA** (04/10/2026, ronda 2) | Preguntar con botones por la autorización al registrar; sin respuesta = «sin autorización». | VCRM-066 | Registrar la autorización solo cuando el comercial la informe. |
| PR-04 | F1 | **RATIFICADA con ajuste** (04/10/2026, ronda 2) | Matriz de permisos (4.4), incluido que solo el CTO exporte y suprima datos de titulares. Ajuste del CTO: el abogado ve los leads «aceptado», «ganado» y «perdido» (decisión P-26; sustituido en la ronda final por la decisión A.1: ve los leads que alguna vez estuvieron en «aceptado»), y «ve solo sus leads» del comercial incluye editar, notas y adjuntos. | VCRM-073, 074, 085, 086; 1.2; 4.4 | Matriz que defina el CTO. |
| PR-05 | F1 | **RATIFICADA** (04/10/2026) | Confirmación ✅/❌ antes de aplicar «aceptado». | VCRM-046 | — |
| PR-06 | F1 | **RATIFICADA** (04/10/2026) | Notificar el cierre aunque falten campos del handoff, indicando cuáles faltan, y avisar al completarlos. | VCRM-052, 084 | — |
| PR-07 | F1 | **RATIFICADA** (04/10/2026, ronda 2) | «nuevo» → «contactado» con el botón «Registrar contacto». | VCRM-089; 4.2 | Paso automático al registrar la primera nota. |
| PR-08 | F1 | **RATIFICADA** (04/10/2026, ronda 2) | Paginación de listados de 10 leads por página. | VCRM-090 | Otro tamaño de página. |
| PR-09 | F1 | **RATIFICADA** (04/10/2026, ronda 2) | Baja de un comercial por el CTO con reasignación de sus leads. | VCRM-091, 092, 093 | Reasignación automática al CTO. |
| PR-10 | F1 | **RATIFICADA** (04/10/2026, ronda 2) | No registrar como lead nuevo un contacto en la lista de supresión. | VCRM-088 | Registrar el lead directamente en «baja». |
| PR-11 | F1 | **RATIFICADA** (04/10/2026, ronda 2) | Exportación como archivo comprimido (documento legible + adjuntos) entregado al CTO por su chat privado. | VCRM-074 | Otro formato o canal que indique el CTO. |
| PR-12 | F1 | **RATIFICADA** (04/10/2026, ronda 2; plazo confirmado por el abogado en la ronda final, J-08) | Retención de respaldos de 30 días. | VCRM-097 | Otro plazo que fije el abogado. |
| PR-13 | F1 (antes F2; decisión P-08) | **RATIFICADA** (04/10/2026, ronda 2) | Matriz de motivos de rechazo: precio/presupuesto; momento no oportuno; ya tiene proveedor; no interesado; otro (con texto obligatorio). Se usa también para la retractación. | VCRM-016, 017, 113, 114 | Lista de motivos que defina el CTO. |
| PR-14 | F2 | **RATIFICADA** (04/10/2026, ronda final; decisión P-06) | Al reanudar, la próxima acción se calcula desde la reanudación, sin acciones omitidas. | VCRM-022 | Retomar la fecha original. |
| PR-15 | F2 | **RATIFICADA** (04/10/2026, ronda final; decisión P-06) | Al cambiar la frecuencia, recalcular desde el último envío (o desde el cambio). | VCRM-023 | Recalcular siempre desde el cambio. |
| PR-16 | F2 | **RATIFICADA** (04/10/2026, ronda final; decisión P-06) | «reactivado» alcanzable también desde «rechazado». | VCRM-024; 4.2 | Solo desde «en nutrición» y «pausado». |
| PR-17 | F2 | **RATIFICADA** (04/10/2026, ronda final; decisión P-06) | Un envío fallido detiene la cadencia del lead hasta decisión humana. | VCRM-038 | Saltar al siguiente paso automáticamente. |
| PR-18 | F2 | **RATIFICADA** (04/10/2026, ronda final; decisión P-06) | Aprobación fuera de franja: diferir al inicio de la siguiente franja. | VCRM-100 | Rechazar la aprobación y pedir aprobar dentro de la franja. |
| PR-19 | F2 | **RATIFICADA** (04/10/2026, ronda final; decisión P-06) | Semana calendario de lunes 00:00 a domingo 23:59 (Bogotá); el exceso se difiere a la semana siguiente. | VCRM-076, 101; 4.5 | Ventana móvil de 7 días; cancelar el exceso. |
| PR-20 | F2 | **RATIFICADA** (04/10/2026, ronda final; decisiones P-06 y P-31) | Baja por respuesta con la palabra «BAJA» (evaluada como palabra completa en el texto nuevo, 4.5); las demás respuestas asociadas a un lead van al historial y al comercial. | VCRM-069, 102, 103 | Baja solo por orden del comercial en el bot (el enlace de baja quedó descartado por la decisión P-10). |
| PR-21 | F3 | **RATIFICADA** (04/10/2026, ronda final; decisión P-06) | Máximo 10 resultados por búsqueda de material. | VCRM-044 | Paginación como en VCRM-090. |
| PR-22 | F4 | **RATIFICADA** (04/10/2026, ronda final; decisión P-06) | Si la IA falla, usar el texto fijo del motivo. | VCRM-062 | No generar la propuesta y avisar al aprobador. |
| PR-23 | F1–F2 | **RATIFICADA** (04/10/2026, ronda 2, con P-25) | «perdido» alcanzable desde nuevo, contactado y rechazado (F1) y desde en nutrición, pausado y reactivado (F2); no directamente desde «aceptado», que primero se retracta a «rechazado» para que se notifique al CTO y al abogado. | VCRM-116; 4.2 | Permitir «aceptado» → «perdido» con la misma notificación que la retractación. |
| PR-24 | F1 | **RATIFICADA** (04/10/2026, ronda 2) | Campo «tipo de cliente» (persona natural o empresa) para decidir si el representante legal es obligatorio. | VCRM-111, 112; 4.3 | Deducir «empresa» cuando el documento es NIT o el campo Empresa tiene valor. |
| PR-25 | F2 | **REEMPLAZADA** (04/10/2026, ronda 2; decisión N-04) | ~~Autorización por respuesta al correo con la palabra «ACEPTO» (evaluada como palabra completa en el texto nuevo, 4.5); si la respuesta contiene también «BAJA», prevalece la baja.~~ Reemplazo decidido por el CTO (flujo con humano en el bucle): el sistema detecta la respuesta del titular asociada al lead y la propone al comercial, que confirma con ✅/❌; no hay detección automática de «ACEPTO»; si la respuesta contiene «BAJA», prevalece la baja (VCRM-120). | VCRM-068, 103, 119, 120, 141, 142, 143 | Toda respuesta a la solicitud va al comercial, que registra la autorización a mano adjuntando el correo. |
| PR-26 | F2 | **RATIFICADA** (04/10/2026, ronda final; decisiones P-06 y P-31) | Cabecera estándar de baja por correo (sin enlace web) en cada mensaje comercial y solicitud de autorización; la solicitud que genera aplica la baja sin exigir la palabra «BAJA». Recogida de la recomendación del análisis de opciones (decisión 6.2). | VCRM-123, 124; 4.5 | Sin cabecera: baja solo por respuesta con «BAJA» (VCRM-102) o comunicada al comercial (VCRM-070). |
| PR-27 | F2 | **RATIFICADA** (04/10/2026, ronda final; decisión P-06) | Una respuesta no asociable a exactamente un lead (sin referencia de hilo válida y con huella del remitente que no coincide con ningún lead o coincide con varios) no cambia ningún lead y se presenta al CTO para revisión humana. | VCRM-122; 4.5 | Si la huella coincide con varios leads, presentarla a los comerciales de esos leads; si no coincide con ninguno, solo registrarla en la bitácora. |

---

## 8. Registro de decisiones del CTO

**Ronda 1 — 04/10/2026.** Respuestas a P-01 y P-03 a P-10 (P-02 no fue respondida). La spec sigue sin aprobar y la constitución del proyecto sigue sin ratificar.

| Decisión | Respuesta (resumen) | Requisitos modificados | Requisitos nuevos | Retirados | Propuestas y otros efectos |
| :--- | :--- | :--- | :--- | :--- | :--- |
| P-01 | Abogado: Juan José. Aviso de aceptación por Telegram (alerta inmediata) y por correo (ficha completa). Respaldo si Telegram falla: correo al CTO y al comercial. | VCRM-047, 048, 049, 050, 084, 087; 1.2, 1.4, 4.4, 4.5 | VCRM-104, 105, 106, 107, 108 | Ninguno | El correo saliente interno entra en F1 (en el análisis de opciones, el puerto de correo pasa a F1 para notificaciones internas; el correo al cliente sigue en F2). Nueva P-27 (buzón remitente). L-8 ampliada con `[VERIFICAR CON ABOGADO]` por la ficha con datos personales que viaja por correo. |
| P-03 | 1 comercial hoy (Duván); 2 esperados en 12 meses. | 1.2 | — | Ninguno | — |
| P-04 | Cada comercial ve solo sus leads; el CTO ve todos. | VCRM-006, 007, 009, 010, 025, 083; 4.4 | VCRM-109, 110 | Ninguno | PR-04 queda fijada en las filas de visibilidad del comercial y del CTO; el resto sigue sin ratificar. Lo que ve el abogado no fue respondido: nueva P-26. P-11 ampliada (duplicado de otro comercial). |
| P-05 | Campos mínimos del handoff: nombre o razón social; cédula o NIT; representante legal (solo empresa); teléfono y correo; servicio; valor; plazo o fecha de inicio. | VCRM-011, 048, 052, 073, 074, 084; 4.3 | VCRM-111, 112 | Ninguno | Nueva PR-24 (tipo de cliente para la validación condicional del representante legal). |
| P-06 (parcial) | PR-05 y PR-06 ratificadas. | VCRM-046, 052, 084 | — | Ninguno | PR-05 y PR-06 pasan a RATIFICADAS. P-06 sigue abierta para el resto de propuestas. |
| P-07 | Dos estados finales: «ganado» (contrato firmado) y «perdido» (descartado del todo, sin seguimiento). | VCRM-094; 4.1, 4.2, 4.4; HU-B1 | VCRM-115, 116, 117; HU-B5 | Ninguno (el estado «cerrado» se sustituye; no era un requisito) | Quién marca ganado/perdido no fue respondido: nueva P-25. Nueva PR-23 (estados de origen de «perdido»). P-17 ampliada (¿fin de cadencia → perdido?). |
| P-08 | «aceptado» puede retractarse a «rechazado» con motivo y notificación al CTO y a Juan José; el rechazo con motivo se registra desde F1; la cadencia sigue en F2. | VCRM-016 y 017 (F2 → F1), 050, 087; 4.1, 4.2 | VCRM-113, 114, 118; HU-D4 | Ninguno | PR-13 (matriz de motivos) pasa a F1 y bloquea F1. |
| P-09 | Ningún mensaje al cliente final sale de forma automática; todo pasa por el gate ✅/❌. | VCRM-036, 037, 068; 1.5; OBJ-2 | — | Ninguno | P-16 ampliada (aprobador también de solicitudes de autorización). Nueva P-28 (abogado): obligación legal de acuse en plazo y riesgo de que un gate sin respuesta incumpla plazos (L-5, L-6). |
| P-10 | Sin ruta pública; autorización y baja solo respondiendo el correo, con `[VERIFICAR CON ABOGADO]` sobre la suficiencia probatoria; postura Zero-Trust. | VCRM-068, 069, 102, 103; 1.5; L-3 | VCRM-119, 120 | Ninguno (la parte de enlace de baja de VCRM-069 se elimina dentro del requisito) | Nueva PR-25 (palabra «ACEPTO»). PR-20: alternativa actualizada. En el análisis de opciones (decisión 6 y 6.3) queda fijada la opción «respuesta al correo»; las demás, descartadas por decisión del CTO. |

**Correcciones QA ronda 2 — 04/10/2026.** Correcciones de redacción que no requieren decisión del CTO, pedidas por el humano. No introducen decisiones nuevas: lo que exigía elegir quedó como `[PENDIENTE]` o `[PROPUESTA]` nueva. N-01, N-04, N-05 y N-11 no se tocaron: quedan para la ronda 2 del CTO.

| Hallazgo | Corrección | Requisitos modificados | Requisitos nuevos | Preguntas y propuestas nuevas |
| :--- | :--- | :--- | :--- | :--- |
| N-02 | El paso a «en nutrición» también ocurre cuando la autorización vigente llega después del rechazo. | 4.2 | VCRM-121 | P-29 (rechazos acumulados en F1 al activar F2) |
| N-03 | Palabras clave evaluadas solo en el texto nuevo, como palabra completa, sin distinguir mayúsculas ni tildes; asociación de la respuesta por referencia de hilo o, en su defecto, por huella del remitente; respuesta no asociable a revisión humana; cabecera de baja por correo cubierta como propuesta. PR-25 sigue sin ratificar. | VCRM-102, 103, 119, 120; 4.2; 4.5; PR-20, PR-25 | VCRM-122, 123, 124 | PR-26 (cabecera de baja), PR-27 (respuesta no asociable) |
| N-06 | Marcas faltantes. | VCRM-083 (P-11), 111 y 112 (PR-24); P-11 | — | — |
| N-07 | La notificación de actualización del handoff tiene las mismas garantías de entrega, aviso de fallo y alerta que la de aceptación; definición de «comercial del lead». | VCRM-050, 084, 087, 107; 4.5 | — | P-30 (lead del CTO o sin comercial) |
| N-09 | Rol, identificador de Telegram y correo de cada usuario autorizado como configuración del sistema, sin interfaz de alta. | — | VCRM-125, 126 | — |
| N-10 | Ruta de archivo sustituida por «la constitución del proyecto». | Sección 8 | — | — |

**Registro de decisiones del CTO — ronda 2 — 04/10/2026.** Respuestas a P-02, P-06 (propuestas de F1), P-11, P-12 (tamaño), P-13, P-14, P-25, P-26 y P-27, y a los hallazgos N-01, N-04 (con N-03), N-05 y N-11 de la auditoría QA ronda 2. El gate sigue abierto: la spec no está aprobada y la constitución del proyecto no está ratificada.

| Decisión | Respuesta (resumen) | Requisitos modificados | Requisitos nuevos | Retirados | Propuestas y otros efectos |
| :--- | :--- | :--- | :--- | :--- | :--- |
| P-02 | Notificación de aceptación en menos de 1 minuto; si Telegram falla, 3 reintentos (0, 1 y 5 minutos); correo de respaldo al CTO y al comercial solo tras agotarlos, no en paralelo; el abogado recibe siempre Telegram y correo; sustituye el reintento indefinido. | VCRM-012, 047, 049, 050, 084, 087, 113; 4.4, 4.5 | VCRM-127, 128, 130 | VCRM-108 | El reintento de envíos al cliente final (VCRM-038) pasa a la nueva P-33. Interpretaciones I-02 a I-05. Análisis de opciones, decisión 2.0. |
| P-25 y PR-23 | «Ganado»: CTO o abogado. «Perdido»: comercial, CTO o abogado. PR-23 ratificada: «aceptado» no pasa a «perdido» sin retractación previa. | VCRM-115, 116; HU-B1, HU-B5; 1.2; 4.1, 4.2, 4.4 | VCRM-133, 134 | Ninguno | Nueva P-32: con P-26 y PR-23, el abogado no tiene ningún lead que pueda marcar «perdido». |
| P-26 | El abogado ve solo los leads en «aceptado», «ganado» y «perdido». | VCRM-010; HU-A3; 1.2; 4.4 | VCRM-136 | Ninguno | Ajuste de PR-04. |
| N-01 | Un lead rechazado o retractado puede volver en F1 a «contactado» o directamente a «aceptado», conservando su historial. | VCRM-089 (origen «rechazado»; además, «usuario con permiso» en lugar de «comercial», alineado con la matriz ratificada); HU-B1; 4.1, 4.2 | VCRM-132 | Nota de 4.2 «En F1, un lead rechazado solo puede pasar a perdido o baja» (tachada) | — |
| P-11 | Duplicado por mismo teléfono o correo: se avisa y no se crea; si es del mismo comercial, se le ofrece abrirlo; si es de otro, no se muestran datos y se notifica al CTO para que lo asigne. | VCRM-006, 083, 088, 110; HU-A1 | VCRM-137 | Ninguno | Interpretaciones I-01 e I-06. |
| P-13 | Sin migración masiva; carga manual uno a uno por el bot; esos leads quedan «sin autorización» hasta que el comercial la registre. | VCRM-003, 066; 1.4, 1.5 | — | Ninguno | — |
| P-14 | Misma instancia de OCI que Jericó; SQLite en producción autorizado como excepción temporal a D1, con SQL portable a PostgreSQL 16. | 1.6 | Sección 1.7 (sin VCRM nuevo) | Ninguno | Análisis de opciones: decisión 3, sección 8 y MVP. **Riesgo:** el punto 4 de la constitución (sin ratificar) dice que rige D1 sin excepciones; al ratificarla habrá que reflejar esta excepción. |
| P-27 | Buzón remitente y credenciales como parámetros de configuración por variables de entorno, sin valor fijo; se configuran después. | VCRM-105; 1.7 | VCRM-140 | Ninguno | Análisis de opciones: decisión 2.0 y sección 8. |
| P-12 (tamaño) | Adjuntos de hasta 20 MB. | VCRM-008; 1.4, 1.7 | — | Ninguno | La conservación sigue abierta para el abogado (P-12, J-01). |
| P-06 (propuestas de F1) | Ratificadas PR-01, PR-02, PR-03, PR-07 a PR-11, PR-12 (sujeta al abogado), PR-13 y PR-24; PR-04 ratificada con ajuste (abogado ve aceptados, ganados y perdidos; «ve solo sus leads» incluye editar, notas y adjuntos). | VCRM-003, 005, 016, 017, 066, 073, 074, 080, 085, 088, 089, 090, 091, 097, 109, 111, 112; 1.2; 4.3, 4.4; sección 7 | — | Ninguno | No queda ninguna propuesta de F1 sin ratificar. P-06 sigue abierta solo para PR-14 a PR-22, PR-26 y PR-27 (prioridad B). |
| N-05 | Documentos válidos: cédula de ciudadanía, NIT, cédula de extranjería y pasaporte. El respaldo también se activa si falla el correo al abogado. «Ganado» y «perdido» son finales y solo pasan a «baja»; si un perdido vuelve, se crea un lead nuevo. La retractación se notifica por los mismos canales que la aceptación. | VCRM-050, 112, 113, 117; 4.1, 4.2, 4.3 | VCRM-135 | Ninguno | Interpretación I-01. |
| N-11 | La retractación pide confirmación ✅/❌; el aviso de que falló el respaldo va por Telegram y por correo; se eliminan los textos «nutrición automatizada» y «envíos automáticos» que contradicen P-09. | VCRM-113; HU-D4; 1.4; 4.2, 4.4 | VCRM-129, 131 | Ninguno | Textos eliminados en 1.4 (resultado de F2 y enlaces de F3) y en el análisis de opciones (decisiones 2.1 y 6). |
| N-04 y PR-25 (resuelve N-03) | Medios válidos de autorización: (a) respuesta del cliente al correo, que el sistema detecta y propone al comercial, quien confirma con ✅/❌ (flujo con humano en el bucle; sin detección automática de «ACEPTO»); (b) documento firmado o captura que adjunta el comercial. | VCRM-066, 068, 103, 119 y 120 (reescritos, se conserva el ID); HU-L1; 1.2, 1.4, 1.5; 4.4, 4.5; L-3 | VCRM-138, 139, 141, 142, 143 | Ninguno | PR-25 REEMPLAZADA. La baja por palabra clave y por cabecera (VCRM-102, 103, 123, 124; PR-26, PR-27) se mantiene sin cambios porque el CTO no se pronunció: nueva P-31, con el riesgo de falsos positivos («temporada baja») y `[VERIFICAR CON ABOGADO]`. Interpretación I-07. |

**Interpretaciones derivadas de la ronda 2.** No son respuesta literal del CTO. En la ronda final quedan confirmadas por delegación del CTO I-01, I-04, I-05, I-06 e I-07 (esta última, con la decisión A.2); I-02 e I-03 quedan REEMPLAZADAS por la decisión A.3.

| ID | Interpretación | Por qué | Requisitos |
| :--- | :--- | :--- | :--- |
| I-01 | La regla de duplicados no considera los leads en «perdido»: si el contacto solo coincide con leads en «perdido», se crea un lead nuevo. Los contactos en «baja» o suprimidos siguen regidos por la lista de supresión, que prevalece. | Reconcilia «duplicado: no se crea» (P-11) con «si un perdido vuelve, se crea un lead nuevo» (N-05). Riesgo: dos leads con la misma huella hacen «no asociable» una respuesta sin referencia de hilo (PR-27). | VCRM-006, 083, 088, 110, 135 |
| I-02 | **REEMPLAZADA (decisión A.3):** ~~«3 reintentos (a los 0, 1 y 5 minutos)» son tres reintentos tras el primer intento fallido —de inmediato, al minuto y a los 5 minutos de ese fallo—: cuatro intentos en total.~~ Rige: 3 intentos en total, a los 0, 1 y 5 minutos. | Lectura literal de «si falla, se hacen 3 reintentos». Alternativa: tres intentos en total, en los minutos 0, 1 y 5. | VCRM-127 |
| I-03 | **REEMPLAZADA (decisión A.3):** ~~El calendario de reintentos se aplica a todo mensaje saliente interno, por Telegram y por correo: correo al abogado, correo de respaldo, aviso de fallo del respaldo y respuestas del bot al comercial.~~ Rige: solo las notificaciones críticas (4.5) se reintentan; las respuestas interactivas del bot y las notificaciones no críticas, no. | P-02 preguntaba de forma general «cuántos reintentos antes de marcar un aviso como fallido»; sin calendario para el correo no se sabría cuándo falla el correo al abogado, que activa el respaldo (N-05). | VCRM-012, 049, 127 |
| I-04 | «Se notifica en menos de 1 minuto» significa que el primer intento de entrega de cada notificación ocurre antes de 1 minuto desde la confirmación. | La entrega efectiva depende del canal y, con los reintentos, puede extenderse hasta unos 5 minutos. | VCRM-047 |
| I-05 | Tras fallar el aviso de fallo del respaldo por ambos canales no hay más envíos ni reintentos; queda la alerta persistente, que se levanta solo cuando el CTO la marca «atendida por otro medio» (ya no por entrega tardía). | Sustituye el reintento indefinido sin inventar reintentos nuevos. | VCRM-087, 130 |
| I-06 | El aviso al CTO por duplicado de otro comercial va por Telegram e incluye la opción de reasignar; la edición que produce un duplicado no notifica al CTO. | El CTO habló del alta («no se crea otro lead»); su canal habitual es Telegram. | VCRM-083, 137 |
| I-07 | El CTO también puede registrar la autorización con documento o captura (coherente con su permiso de adjuntos sobre todos los leads); la confirmación ✅/❌ de una respuesta corresponde al comercial del lead, y al CTO solo en leads suyos o sin comercial (P-30). | N-04 nombra al comercial; la matriz ratificada da al CTO los mismos permisos que al comercial sobre todos los leads. | VCRM-138, 119; 4.4 |

**Riesgos abiertos tras la ronda 2:** (1) la constitución (sin ratificar) no recoge la excepción a D1 (P-14); (2) baja por palabra clave sin confirmación humana con falsos positivos («temporada baja», «prioridad baja») (P-31); (3) el permiso del abogado para marcar «perdido» no tiene hoy efecto práctico (P-32); (4) el medio (b) puede no aportar la versión del aviso ni las finalidades que exige VCRM-065 (J-04); (5) las interpretaciones I-01 a I-07 pueden cambiar requisitos de F1 si el CTO no las confirma.

**Ronda final — decisiones del CTO (A) y respuestas legales (B) — 04/10/2026.** El CTO acepta todas las recomendaciones pendientes y delega las decisiones restantes en el criterio del planificador; el abogado (Juan José) acepta J-01 a J-14 y delega en las recomendaciones (sección 9). Con ello la spec queda **APROBADA** (Gate 1) y la constitución del proyecto, **RATIFICADA** con la enmienda de su punto 4.

| Decisión | Contenido | Requisitos modificados | Requisitos nuevos | Retirados |
| :--- | :--- | :--- | :--- | :--- |
| A.1 (P-32, añadido de J-09) | El abogado marca «ganado» y puede registrar la retractación (aceptado → rechazado con motivo y ✅/❌); «perdido» solo lo marcan el comercial del lead o el CTO; el abogado ve solo los leads que alguna vez estuvieron en «aceptado» (sustituye a P-26). | VCRM-010, 115, 116, 131, 136; HU-B5; 1.2; 4.1, 4.2, 4.4 | — | — |
| A.2 (P-30, R-01) | Si el lead es del CTO o no tiene comercial, todo lo dirigido al «comercial del lead» va al CTO. VCRM-110 no muestra datos de un lead no visible para quien registra. | VCRM-052, 110, 137; 1.2; 4.4, 4.5 | — | — |
| A.3 (I-02, I-03) | 3 intentos en total (0, 1 y 5 minutos); tras fallar el tercero sale el correo de respaldo; los reintentos aplican solo a las notificaciones críticas (aceptación, retractación, handoff y fallos); las respuestas interactivas del bot no se reintentan. | VCRM-012, 049, 084, 113, 127, 128; 4.5 | — | VCRM-108 (ya retirado) |
| A.4 (R-03) | Enmienda del punto 4 de la constitución: excepción temporal a D1 (SQLite) acotada al CRM. Constitución RATIFICADA. | 1.7 | — | — |
| A.5 (R-02, R-06) | La lista de comerciales y usuarios autorizados se persiste en la base de datos, no en la configuración; alta y baja por el bot; el correo es obligatorio en el alta. | VCRM-091, 125, 126; 1.4, 1.7; 4.4 | VCRM-144 | VCRM-106 (inalcanzable, R-06) |
| R-05, R-07 | Correcciones de redacción. R-07: el análisis de opciones ya no indica nada bloqueante para F1. R-05: resuelto por la decisión A.1. | Análisis de opciones (MVP) | — | — |
| B (J-01 a J-14) | Respuestas del abogado aceptadas por delegación, con plazos configurables (4.6); detalle en la sección 9. | VCRM-048, 057, 064, 068, 070, 072, 073, 076, 094, 097, 098, 102, 124; 5 | VCRM-145 a 155, 158, 159 y 162 (J-01, J-02, J-05 a J-08, J-11, J-14); VCRM-156 (J-09); VCRM-157 (J-10); además, por delegación, VCRM-160 (P-29) y VCRM-161 (P-21) | — |

**Resueltas por delegación del CTO (ronda final).** Opción elegida por el planificador y por qué, en una línea.

| ID | Opción | Por qué |
| :--- | :--- | :--- |
| P-06 (resto) | PR-14 a PR-22, PR-26 y PR-27 ratificadas. | El CTO aceptó todas las recomendaciones pendientes. |
| P-15 | Volumen bajo (menos de 100 correos al día); gasto objetivo USD 0 al mes. | Un comercial hoy y dos en 12 meses; las cuotas gratuitas bastan; se revisa si se supera. |
| P-16 | Aprueba el comercial del lead por chat individual; el CTO, cualquier lead. | El comercial conoce el contexto; el chat individual evita el modo privacidad de los grupos de Telegram. |
| P-17 | Un paso cada 30 días, 3 pasos por motivo; gate de 48 horas; cancelar o expirar salta al paso siguiente; sin paso automático a «perdido». | Respeta el tope de 1 contacto por semana con margen y deja el descarte a una persona. |
| P-18 | Solo correo en F2, desde el buzón del sistema. | Sin webhook público ni costo por mensaje (postura Zero-Trust, P-10). |
| P-21 | Textos fijos por motivo redactados y aprobados por el CTO. | Nada sale al cliente sin un texto revisado por el responsable (P-09). |
| P-22 | Plantilla entregada y mantenida por el abogado; formato y cuenta de Google en el plan de F3. | Prioridad C; no bloquea F1 ni F2. |
| P-23 | Transcripción en la propia instancia (10 minutos); a la IA externa solo datos seudonimizados. | Cumple J-10 sin transferir audios ni datos personales. |
| P-24 | La IA propone y el comercial confirma con ✅. | Humano en el bucle, coherente con P-09 y N-04. |
| P-28 | Baja procesada al registrarse; plazos de consultas y reclamos con escalado y alerta. | Cumple J-05 sin depender del gate. |
| P-29 | Rechazados de F1 con autorización vigente entran en cadencia al activar F2, con la próxima acción desde la activación. | Evita una ráfaga de envíos atrasados el día de la activación. |
| P-31 | Baja por palabra clave o cabecera inmediata, sin confirmación humana. | J-06: la baja se honra de inmediato; el falso positivo es el riesgo menor. |
| P-33 | 3 intentos (0, 1 y 5 minutos), solo dentro de la franja permitida. | Mismo calendario que A.3 sin contactar fuera de la franja legal. |
| J-14 (alcance) | El plazo de 30 días no corre mientras el lead está en «aceptado» o «ganado» y se reinicia al salir de «aceptado». | La autorización se prepara con el contrato (J-09) y suprimir un cliente en cierre rompería el handoff. |
| Topes legales | Un valor configurado fuera del límite legal no se aplica; rige el límite (VCRM-162). | Los plazos son configurables (B) sin poder incumplir la ley. |
| Notificación crítica (4.5) | Incluye, además de las de A.3, la notificación de supresión de copias (VCRM-154), con persistencia previa y calendario de 3 intentos (VCRM-049, VCRM-127). | J-07 exige que la orden de suprimir las copias llegue al CTO y al abogado; perderla dejaría copias sin suprimir. |
| «Ganado» que pasa a «baja» | Conserva sus adjuntos durante el plazo de VCRM-145 (10 años desde el paso a «ganado»); VCRM-145 prevalece sobre VCRM-146 y J-07 en cuanto a los adjuntos, y el resto de sus datos personales se suprime según VCRM-146. | J-01: el deber de conservación de los soportes del contrato prevalece sobre la supresión por estado final. |

**Riesgos tras la ronda final:** (1) falsos positivos de la baja por palabra clave aceptados (P-31); (2) los respaldos conservan datos suprimidos hasta 30 días (J-08); (3) los valores por defecto de cadencia y volumen (P-15, P-17) son del planificador y pueden requerir ajuste tras la operación real.

**Decisiones del CTO por delegación — 05/10/2026.** Tomadas durante la implementación de F1 (fase 6) sobre los asuntos señalados por el planificador; se aplican como cambio *spec-anchored*. El registro en el documento de decisiones del núcleo lo gestiona el humano con el CTO.

| Decisión | Respuesta (resumen) | Requisitos modificados | Requisitos nuevos | Retirados | Otros efectos |
| :--- | :--- | :--- | :--- | :--- | :--- |
| K-1 | Los 9 campos del handoff de 4.3 son correctos: los de la decisión P-05 más el tipo de cliente de PR-24. | VCRM-048, 156 | — | Ninguno | Se sustituye «los 7 campos» por «los campos acordados (P-05 más el tipo de cliente de PR-24)». |
| K-2 | La retractación por orden escrita vale para F1; además, si el costo es bajo, botón en la ficha. | — | VCRM-163 | Ninguno | El planificador valora el costo como bajo (reutiliza la solicitud de retractación ya implementada); el botón entra en F1. |
| K-3 | Sin cierre transitivo: un duplicado es una coincidencia exacta de teléfono normalizado o de correo con un lead existente; no se encadenan titulares. | VCRM-006, 073, 110, 135; 4.5 | — | Ninguno | Nuevas definiciones «coincidencia de contacto» y «leads del mismo titular» (4.5). |
| K-4 | La evidencia de autorización se conserva mientras exista obligación de probar el consentimiento (Decreto 1377, art. 7); si el titular pide supresión, solo se guarda la huella mínima de la evidencia, sin datos personales en claro. | VCRM-073, 094; 4.5 | VCRM-164, 165 | Ninguno | Nueva definición «huella mínima de una evidencia» (4.5). |
| K-5 | Una exportación que supera el límite de Telegram se divide en partes numeradas. | VCRM-074 | VCRM-166 | Ninguno | — |
| K-6 | Festivos extraordinarios desde una lista configurable (configuración del sistema o archivo), además del cálculo automático. | VCRM-077; 4.5, 4.6 | VCRM-167, 168 | Ninguno | Nuevo parámetro en 4.6. |
| K-7 | Si faltan las herramientas de cifrado o de copia del respaldo, se mantiene el fallo con aviso al CTO. | — | — | Ninguno | Sin cambio: rige VCRM-098. |
| K-8 | El documento de decisiones del núcleo no se modifica desde esta línea; lo reporta el humano al CTO. | — | — | Ninguno | Sin efecto en requisitos. |
| N-11 (corrección 05/10/2026) | La decisión N-11 («el aviso de que falló el respaldo va por Telegram y por correo») respondía al hallazgo sobre VCRM-098 (respaldo nocturno cifrado), no solo a VCRM-129. | — | — | VCRM-098 | VCRM-098 avisa al CTO por Telegram y por correo; VCRM-129 sin cambios. |

**Riesgos tras las decisiones K:** (1) sin cierre transitivo, una supresión puede dejar leads del mismo titular que solo comparten un dato con otro lead coincidente; el CTO puede ordenar otra supresión sobre ellos; (2) la huella mínima no permite reconstruir la evidencia: si un tercero la exige, solo se puede comprobar un documento que se presente; (3) un festivo extraordinario mal escrito se ignora con aviso al CTO y, mientras no se corrija, ese día cuenta como hábil (los plazos vencen antes, no después).


**Decisiones por delegación del CTO para F2 — 11/10/2026.** El humano reiteró la delegación total del 04/10/2026 para las preguntas abiertas de F2. Una verificación con búsqueda confirmó que P-15 a P-21 y PR-14 a PR-20 ya figuraban resueltas en las secciones 6 y 7; se registran aquí como **aceptado por delegación** junto con las decisiones nuevas Q-1 a Q-5.

| Decisión | Opción aceptada por delegación | Porqué (una línea) |
| :--- | :--- | :--- |
| P-15 a P-21 | Aceptadas tal como constan en 6.2 (volumen bajo y gasto USD 0; aprueba el comercial del lead o el CTO; cadencia 30 días x 3 pasos con gate de 48 h; solo correo; empresa y persona natural con 1 contacto/semana; política y aviso del abogado; textos del CTO). | Ya fijadas por el CTO o por delegación; no hay información nueva que las cambie. |
| PR-14 a PR-20 | Aceptadas tal como constan en 7 (reanudar desde la reanudación; frecuencia desde el último envío; «reactivado» detiene la cadencia; 3 intentos 0/1/5 min; diferir al inicio de la siguiente franja; semana lunes–domingo con diferimiento; «BAJA» por respuesta). | Son las alternativas conservadoras frente a Ley 2300 y no generan ráfagas de envíos. |
| Q-1 | Los valores internos de estados, autorizaciones, notificaciones y solicitudes pasan de español a inglés mediante migración de la base antes de F2; lo que ve el usuario no cambia (VCRM-171). | Coherencia de identificadores (código en inglés) a bajo costo mientras no hay datos de producción. |
| Q-2 | La lectura de respuestas es un sondeo saliente del buzón del sistema por IMAP cada 5 minutos, sin ruta pública (VCRM-169, 170). | Cumple P-10 (sin webhook ni puerto), sin costo y con latencia suficiente para honrar una baja el mismo día. |
| Q-3 | Matriz de motivos: precio → propuesta de valor; momento no oportuno → recordatorio cada 30 días (60 configurable); ya tiene proveedor y no interesado → contenido educativo; otro → genérico; 3 pasos cada uno. | Respeta P-17 y el tope semanal, y adapta el tono al motivo sin automatizar redacción (textos del CTO, P-21). |
| Q-4 | `MIENTRAS` no hay autorización vigente, la guarda de contacto comercial niega propuestas y envíos (cierra la observación de VCRM-067), salvo la solicitud de autorización (VCRM-068). | Una sola guarda para todos los envíos; evita contactar sin consentimiento. |
| Q-5 | Tras una baja por respuesta o cabecera no se envía acuse al titular. | VCRM-036 exige gate para cualquier mensaje y la baja debe ser inmediata (P-31). |

**Riesgos tras las decisiones Q:** (1) la migración Q-1 modifica datos existentes; se mitiga con copia previa y transacción única; (2) el sondeo IMAP depende de la disponibilidad del proveedor de correo y de una credencial adicional; (3) los rebotes y respuestas automáticas llegan al CTO como respuestas no asociables (VCRM-122).

**Autorizaciones del CTO — 11/10/2026 (aviso de privacidad y textos de cadencias).**

| ID | Decisión | Estado y fuente |
| :-- | :-- | :-- |
| A-1 | Aviso de privacidad v1.0 (`src/jerico/crm/resources/aviso-privacidad.md`): responsable Kaisen AI, finalidades del CRM, derechos del titular y canal de contacto (responder al mismo correo). Satisface la guarda de activación de F2 por existencia de texto y versión (J-02). | **Autorizado por Juan José según el CTO el 11/10/2026.** Redactado por el agente. Pendiente de datos registrales (razón social, NIT y domicilio), que no constan en ninguna fuente del repo ni de las bóvedas y no se inventan. |
| A-2 | Textos de seguimiento v1 (`src/jerico/crm/resources/cadences.toml`): 5 motivos × 3 pasos, voz cercana, profesional y sin presión, sin descuentos, precios ni enlaces (P-21). | **v1 autorizada por el CTO el 11/10/2026, editable.** Cada texto sigue pasando por el gate ✅/❌ antes de enviarse (P-09). |

---

## 9. Preguntas para el abogado (Juan José)

Consolida lo que estuvo marcado `[VERIFICAR CON ABOGADO]` en esta spec y en su análisis de opciones, y las preguntas dirigidas al abogado. El abogado (Juan José) aceptó J-01 a J-14 el 04/10/2026 y delegó en las recomendaciones; las respuestas se registran «aceptado por delegación» y los plazos son configurables (4.6). «Bloqueaba» indica la fase que no podía cerrarse sin la respuesta.

| ID | Tema | Pregunta | Origen | Bloqueaba | Respuesta |
| :--- | :--- | :--- | :--- | :---: | :--- |
| J-01 | Conservación de adjuntos | ¿Cuánto tiempo se conservan los audios, fotos y documentos adjuntos a un lead, y qué pasa con ellos al vencer ese plazo? | P-12; L-5 | F1 | **Aceptado por delegación.** Adjuntos de leads en «ganado»: 10 años; datos de «perdido» o «baja»: suprimidos a los 12 meses del estado final; plazos configurables (VCRM-145 a VCRM-147). |
| J-02 | Política y aviso de privacidad | ¿Kaisen tiene publicada una política de tratamiento y un aviso de privacidad? ¿Dónde, qué versión y con qué finalidades, responsable y canales de atención? | P-20; L-2, L-4, L-7; VCRM-065, 068 | F2 | **Aceptado por delegación.** La política y el aviso los redacta y mantiene el abogado; el sistema solo referencia su URL o texto desde la configuración (VCRM-148, VCRM-149). |
| J-03 | Prueba por respuesta al correo (medio a) | ¿Es prueba suficiente de autorización previa, expresa e informada la respuesta del titular al correo de solicitud (con el aviso de privacidad), confirmada por el comercial y conservada con sus cabeceras, fecha-hora y referencia? ¿Debe la respuesta contener una fórmula concreta? | L-1, L-3; VCRM-068, 119, 141; decisiones P-10 y N-04 | F2 | **Aceptado por delegación.** La respuesta al correo, confirmada por el comercial y conservada como evidencia, es prueba válida; no exige fórmula concreta (VCRM-119, VCRM-141). |
| J-04 | Prueba por documento firmado o captura (medio b) | ¿Es suficiente un documento firmado o una captura (p. ej. de un chat) adjuntados por el comercial? ¿Qué debe contener como mínimo (texto de la autorización, finalidades, versión del aviso, identificación y firma del titular) y cómo se custodia? | L-1, L-3; VCRM-065, 066, 138; decisión N-04 | F1 | **Aceptado por delegación.** El documento firmado o la captura adjuntados por el comercial son prueba válida (VCRM-138). |
| J-05 | Acuse de baja y plazos legales | ¿La baja o revocatoria exige un acuse al titular en un plazo legal? Si sí, ¿cómo se cumple el plazo si todo mensaje al cliente pasa por el gate y una propuesta sin respuesta expira, y puede enviarse el acuse a un contacto ya en la lista de supresión? ¿Cómo se cumplen los plazos de consultas (10 días hábiles) y reclamos (15 días hábiles)? | P-28; L-5, L-6; VCRM-034, 036, 037, 102 | F2 | **Aceptado por delegación.** La baja se procesa al registrarse; sin confirmación humana en 2 días hábiles se escala al CTO; nunca más de 10 días hábiles para consultas ni 15 para reclamos (Ley 1581, arts. 14 y 15) (VCRM-070, VCRM-150 a VCRM-153). |
| J-06 | Baja por respuesta al correo | ¿Hay obligación de honrar de inmediato toda solicitud de baja recibida por correo (palabra «BAJA» o cabecera de baja)? ¿Puede exigirse una confirmación humana previa, dado el riesgo de falsos positivos («temporada baja»)? ¿Es válida la cabecera estándar de baja por correo como medio de baja? | P-31; L-5; VCRM-102, 123, 124; PR-26 | F2 | **Aceptado por delegación.** La baja por correo (palabra «BAJA» o cabecera de baja) se honra de inmediato, sin confirmación humana; la cabecera es medio válido (VCRM-102, VCRM-123, VCRM-124). |
| J-07 | Alcance de la supresión | Al suprimir los datos de un titular: ¿deben suprimirse también las copias ya enviadas por correo y Telegram (ficha al abogado y al CTO)? ¿Es lícito conservar la huella del contacto y las evidencias de autorización y revocatoria? ¿La excepción por deber legal o contractual, hoy limitada a leads «aceptado» o «ganado», debe incluir o excluir a los retractados (rechazados tras aceptar)? | N-08; L-5; VCRM-073, 094, 095 | F1 | **Aceptado por delegación.** La supresión cubre base de datos, adjuntos y leads retractados; por las copias enviadas se notifica al CTO y al abogado; se conservan la huella y las evidencias (VCRM-073, VCRM-094, VCRM-154, VCRM-155). |
| J-08 | Retención de respaldos | ¿Son adecuados 30 días de retención de los respaldos cifrados (PR-12, ratificada con esta reserva)? ¿Es aceptable que un respaldo conserve datos ya suprimidos hasta su rotación? | PR-12; L-5; VCRM-097 | F1 | **Aceptado por delegación.** Respaldos de 30 días; los datos suprimidos persisten en ellos como máximo hasta ese plazo (VCRM-097, VCRM-098). |
| J-09 | Abogado como encargado | Si el abogado no es parte de la planta de Kaisen, ¿la entrega de la ficha completa (con número de documento) por correo y Telegram es una transmisión a un encargado que requiere contrato? ¿El contenido de la notificación de aceptación (campos del handoff y tipos de documento admitidos: cédula de ciudadanía, NIT, cédula de extranjería, pasaporte) basta para preparar contrato y autorización y respeta la minimización de datos? | L-8; VCRM-048; decisiones P-01, P-05 y N-05 | F1 | **Aceptado por delegación.** El abogado es encargado; el handoff y toda notificación al abogado se limitan a los 7 campos (VCRM-048, VCRM-156). |
| J-10 | Transmisión internacional | Telegram, el proveedor de correo, Google y, si se usan, los servicios de IA (GLM y DeepSeek, con infraestructura en China) y de transcripción procesan datos fuera de Colombia: ¿qué contratos de transmisión, inventario de encargados en el aviso y minimización se exigen? ¿Se admite enviar extractos de conversaciones a esos proveedores de IA o se exige un país con nivel adecuado de protección? | L-8; P-23; VCRM-064; análisis de opciones, decisiones 2, 4, 6 y 7 | F1 (Telegram y correo); F4 (IA) | **Aceptado por delegación.** Telegram y Google se aceptan como encargados y se mencionan en la autorización (VCRM-148); ningún dato personal sin seudonimizar va a servicios de IA externos (F4; VCRM-064, VCRM-157). |
| J-11 | Ley 2300 de 2023 | ¿Aplica a clientes empresa (B2B)? ¿Cuál es el límite de mensajes por semana y cómo se cuenta la semana? ¿Es correcta la franja (lunes a viernes 07:00–19:00, sábados 08:00–15:00, sin domingos ni festivos) y basta el correo como canal autorizado? | P-19; L-9; VCRM-072, 076, 100, 101 | F2 | **Aceptado por delegación.** La Ley 2300 aplica también a B2B: lunes a viernes 07:00–19:00, sábados 08:00–15:00, ni domingos ni festivos; máximo 1 contacto por semana calendario y por lead (VCRM-072, VCRM-076, VCRM-100, VCRM-101). |
| J-12 | Registros y otras obligaciones | ¿Kaisen debe inscribir la base en el RNBD? ¿Aplica el Registro de Números Excluidos de la CRC a correo o WhatsApp? ¿Las notas de voz del comercial con datos de terceros requieren tratamiento especial? | L-10, L-11, L-12 | F2 | **Aceptado por delegación.** El RNBD se gestiona fuera del sistema; el tratamiento de audios se revisa en F4. |
| J-13 | Firma electrónica (futuro) | Para el paso futuro de envío y firma del contrato, ¿qué tipo de firma (electrónica o digital certificada) y proveedor recomienda (Ley 527 de 1999, Decreto 2364 de 2012)? | Análisis de opciones, decisión 5 (fuera de alcance) | — | **Aceptado por delegación.** La firma electrónica queda fuera de alcance. |
| J-14 | Leads sin autorización | ¿Cuánto tiempo puede conservarse un lead registrado «sin autorización» y qué ocurre al vencer ese plazo? | L-1, L-5; VCRM-066; decisión P-13 | F1 | **Aceptado por delegación.** Un lead «sin autorización» se conserva como máximo 30 días; a los 25 se avisa al comercial; sin autorización se suprime automáticamente (VCRM-158, VCRM-159; alcance en la sección 8). |

---

> Última modificación: 11/10/2026 17:53 (Planificador SDD)
