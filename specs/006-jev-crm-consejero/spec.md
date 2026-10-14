---
modificado: "13/10/2026 22:16"
---

# Spec 006 — Consejero de seguimiento con Jev en el CRM (modo sombra)

- **Estado:** **BORRADOR (versión 2, tras la auditoría QA) — pendiente de aprobación del CTO (Gate 1).** No se implementa nada hasta que el CTO apruebe. **Dos preguntas bloquean el Gate 1: Q2 (cuántos leads se esperan) y Q5 (base legal del archivo seudonimizado).**
- **Tipo de cambio:** funcionalidad nueva, de **solo lectura**, sobre el CRM de ventas ya desplegado.
- **Fuente:** Plan maestro de Jericó (frente F3, 13/10/2026); informe `Proyecto_Jerico_Implementacion_Jev` (casos P1 y P2 y sección 14); decisiones del CTO del 12/10/2026 (modo sombra, solo categorías y contadores, la IA propone y el código decide, `jev-latest` sin tope diario); hechos verificados en la rama `crm/asistente-comercial-llm` (commit `d0aeab3`).
- **Convención de marcas:** `(decisión CTO 12/10)` — ya decidido por el CTO; `(propuesta)` — valor propuesto, el CTO decide; `(supuesto)` — no verificado.
- **Relación con otras specs:** la spec `002-jev-router-sombra` (router del núcleo) **queda en espera** hasta que el núcleo se despliegue. Esta spec construye una sola vez el escritor de archivos diarios, que la spec 002 podrá reutilizar cuando se retome.
- **Alcance de esta spec:** solo el lado del CRM (qué se observa y se guarda). El lado de Jev (consultas, consenso, métricas, informe) pertenece a la herramienta de la flota (`Flota_Jev`, a cargo de `kai-jev`) y aquí se describe únicamente como contrato (sección 6).

## 1. Contexto verificado

- **Producción:** `kaisen-server` ejecuta solo el servicio del CRM. El núcleo con el router no corre. Hay un solo usuario (el CTO) y **0 leads cargados** (Plan maestro, sección 1; verificado por el director, no por esta spec).
- **Asistente `/asistente`:** encendido según el Plan maestro. Envía a OpenAI texto **seudonimizado** (resumen, borrador, pregunta con cifras agregadas), con tope de 60 000 tokens al día y 20 llamadas por usuario al día. Es consultivo: nada va al cliente sin ✅/❌.
- **Cómo se decide hoy qué lead atender primero:** `/lista` ordena por última interacción (más reciente primero) y `/seguimiento` ordena por número de lead. No hay priorización por valor, antigüedad, etapa ni probabilidad de cierre.
- **Respuestas de titulares por correo (F2):** el buzón está apagado en producción (faltan credenciales y datos registrales) y la revisión legal de la transferencia a OpenAI está pendiente según los informes del CRM. Por eso no hay tráfico de correo que clasificar.
- **El CRM ya guarda historial estructurado** de cada lead (estados, cambios de campo, reasignaciones, cadencias, propuestas, envíos), con fechas. Eso permite calcular un vector numérico por lead **sin leer texto libre**.
- **La supresión no borra filas:** ordenar la supresión de un titular marca el lead como suprimido y anula sus datos personales; el lead sigue existiendo en la base. Además, el barrido diario legal corre a las 08:00 de Bogotá, y el CRM ejecuta ese barrido también al arrancar.
- **Medición de Jev en la flota (12/10/2026):** unos 596 tokens por llamada, latencia mediana de 280 ms y p95 de 346 ms, costo de USD 0,0023 por 90 llamadas. En esa prueba la confianza de Jev **no vino calibrada** para la pregunta de modelo (error de calibración 0,33).

## 2. Replanteo de P1 y P2: dónde puede aportar Jev en el CRM

| Caso | Decisión | Línea base hoy | ¿Aplica ahora? |
|---|---|---|---|
| **C1 (esta spec)** | Qué lead necesita atención y cuál es el siguiente paso prudente | Orden por última interacción y por número de lead; la persona decide | **Sí.** Datos estructurados ya existentes, sin texto libre, sin tráfico externo, sin nuevo encargado de datos si no viaja identidad. |
| P2 — respuestas «por clasificar» | Baja, consulta o reclamo, sin solicitud | Persona, con botones; la baja por palabra clave es automática | **No.** Buzón apagado, texto de terceros y cuestión legal abierta. Sigue en espera. |
| Router L1/L2/L3 | Nivel del turno del agente | Reglas por palabras clave | **No.** El núcleo no está desplegado (spec 002, en espera). |
| Filtro previo del asistente | ¿Se necesita el modelo pagado o basta una respuesta local? | Cada `/asistente` llama al modelo | **No.** No existe un catálogo de respuestas locales que elegir; no hay volumen que lo justifique con 20 llamadas por usuario al día. |
| Motivo de rechazo | Una de 5 opciones | La persona pulsa un botón | **No.** Ya es una elección de un clic. |
| Clasificar correo entrante del comercial como lead o no | ¿Es un lead nuevo? | No existe (frente F2 del Plan maestro) | **Después.** Es donde habrá más volumen (el criterio documentado del CRM es de menos de 100 correos al día). Se incorporará como entrada a la spec nueva del CRM que escribe `crm-director`, no aquí. |
| Elegir el contenido de la cadencia | Matriz fija de 5 motivos × 3 pasos, con aprobación humana a las 48 h | Matriz fija | **No ahora.** Volumen mínimo y mejora no medible. |

**Conclusión del replanteo:** el único caso aplicable hoy es **C1**. El mayor volumen futuro (correo de entrada) depende de la spec que está redactando `crm-director`.

## 3. Hipótesis y riesgo central

- **H1:** a partir de un vector numérico del lead (etapa, antigüedad, días sin interacción, estado de cadencia, datos del handoff completos o faltantes, alertas y propuestas pendientes), Jev ordena la urgencia de los leads y sugiere un siguiente paso prudente de forma que **se acerca más a lo que luego ocurre** que el orden actual.
- **Riesgo central, declarado desde ya:** con uno o dos comerciales y pocos leads activos, una persona puede revisar todos los leads a ojo, y el volumen será insuficiente para concluir. Además la confianza de Jev puede no estar calibrada. Un resultado «no concluyente» o negativo es un resultado válido y barato: el costo de la prueba es de centavos.
- **Sin datos hoy:** hay 0 leads. El piloto no puede medir nada hasta que el comercial cargue leads reales.

## 4. Alcance

**Dentro:**
- Una instantánea diaria, de solo lectura, que guarda el vector de cada lead elegible en un archivo local.
- Activación por configuración, apagada por defecto.
- Retención limitada y borrado de las líneas de un lead cuando se suprime.
- Contrato de datos con la herramienta de la flota.

**Fuera (explícito):**
- Mostrar a cualquier usuario una prioridad o sugerencia de Jev, o cambiar el orden de `/lista` o `/seguimiento`.
- Cambiar estados, cadencias, propuestas, alertas o mensajes; enviar algo a un titular; decidir acciones irreversibles (cerrar, perder, dar de baja, pagar, enviar).
- Cualquier llamada a Jev desde el CRM y cualquier credencial de TypeSafe en el CRM.
- Enviar a Jev texto libre (nombres, empresa, notas, motivo escrito, valor pactado escrito, correos, teléfonos) o identificadores.
- Tocar el asistente `/asistente`, el buzón de F2, el despliegue o el servidor.
- P2 y el router del núcleo.

## 5. Actores

| Actor | Papel |
|---|---|
| CTO (Santiago Gonzalez) | Aprueba la spec y decide los umbrales y el cierre del piloto. |
| Comerciales (hoy Duván, previsto un segundo) | Usan el CRM como siempre; no ven nada nuevo. |
| CRM | Genera la instantánea diaria. |
| Herramienta de la flota (`Flota_Jev`, `kai-jev`) | Lee los archivos, consulta a Jev, mide y produce el informe. |

## 6. Requisitos (EARS)

Prefijo `VJC-`. Definiciones:
- **Día de captura:** el día calendario en hora de Bogotá. Todas las «días de antigüedad» son diferencias de días calendario de Bogotá; si el resultado es negativo se registra como 0.
- **Lead elegible:** lead sin marca de supresión, que no esté en estado «baja» (`opted_out`) y cuya autorización de tratamiento no esté revocada. Los leads en estado final (`won`, `lost`) **sí** son elegibles, porque su desenlace es lo que se quiere observar.
- **Referencia del lead:** código derivado del número interno del lead con una clave secreta del CRM (VJC-014); no es secuencial y no se puede invertir sin la clave.
- **Falla ordinaria:** cualquier excepción que no sea una cancelación del proceso.

### 6.1 Captura de la instantánea

- **VJC-001** EL SISTEMA no incluye en el paquete de la instantánea ninguna importación de clientes de red (HTTP, sockets, URL) ni de la herramienta de la flota, y ningún proceso del CRM consulta a Jev o a TypeSafe (verificable con un análisis estático de los módulos).
- **VJC-002** MIENTRAS la instantánea esté desactivada (valor por defecto), EL SISTEMA no escribe ningún archivo de instantánea y el CRM se comporta exactamente igual que sin esta funcionalidad.
- **VJC-003** CUANDO la instantánea está activada y llega su corrida diaria, EL SISTEMA escribe una línea por cada lead elegible con su vector (6.2), el día de captura y la versión del esquema.
- **VJC-004** SI la corrida se ejecuta más de una vez en el mismo día de captura (reinicio del contenedor o reintento), ENTONCES EL SISTEMA no duplica las líneas de los leads ya registrados ese día, y SI el archivo del día tiene una línea incompleta o ilegible, ENTONCES la descarta al leerlo y escribe los leads que falten.
- **VJC-005** EL SISTEMA no escribe en la base del CRM durante la captura y realiza todas sus lecturas dentro de una única sección de lectura de la conexión del CRM, que excluye las escrituras de otros trabajos mientras dura, de modo que ve un estado consistente.
- **VJC-006** SI la captura falla por una falla ordinaria, ENTONCES EL SISTEMA continúa con los demás trabajos del CRM, anota en el registro de la aplicación un aviso sin datos de leads (sin referencias, ni números internos, ni valores del vector) que incluye el contador de fallos desde el arranque, y reintenta en la siguiente corrida; el contador vive en memoria y se reinicia con el proceso.
- **VJC-007** SI el vector de un lead no cumple la validación de 6.2, ENTONCES EL SISTEMA omite a ese lead, cuenta la omisión, la informa en el resumen sin datos de leads que escribe al final de cada corrida en el registro de la aplicación y continúa con los demás.
- **VJC-008** EL SISTEMA obtiene los datos de todos los leads, incluida la lista de leads, con un número de sentencias de lectura que no depende del número de leads (como máximo 12 sentencias por corrida, verificable contando sentencias en una prueba con 1 000 leads y con 10 leads, que deben dar el mismo número).
- **VJC-009** EL SISTEMA programa la corrida diaria de la instantánea 30 minutos después del barrido legal diario del CRM, y no la ejecuta al arrancar el proceso.
- **VJC-010** SI no hay ningún lead elegible, ENTONCES EL SISTEMA no escribe líneas ese día y aun así aplica la retención y los retiros (6.3).

### 6.2 Vector del lead (sin texto libre)

- **VJC-011** EL SISTEMA construye el vector de cada lead únicamente con valores enumerados, booleanos y enteros acotados, calculados localmente a partir de datos estructurados del CRM.
- **VJC-012** EL SISTEMA incluye en el vector exactamente los siguientes campos (lista cerrada), además de la versión del esquema, el día de captura y la referencia del lead (VJC-014), y ningún otro:
  - **Etapa** (`new`, `contacted`, `accepted`, `rejected`, `nurturing`, `paused`, `reactivated`, `won`, `lost`).
  - **Antigüedad** del lead; **días desde la última interacción**; **días en la etapa actual** = días desde el último evento de cambio de etapa del lead, o desde el registro si no tiene ninguno.
  - **Banderas**: aceptado alguna vez; el rechazo fue una retractación; bloqueo comercial; tiene teléfono; tiene correo; tiene valor pactado (no vacío); tiene servicio definido (no vacío); tiene comercial asignado.
  - **Tipo de cliente**: `persona_natural` si vale «persona natural», `empresa` si vale «empresa», `ninguno` en cualquier otro caso (incluido vacío).
  - **Motivo de rechazo**: `precio`, `momento`, `proveedor`, `no_interesado` u `otro` (cualquier valor fuera de esa lista cuenta como `otro`) o `ninguno` si está vacío.
  - **Autorización**: `unauthorized` o `authorized` (la revocada no es elegible).
  - **Campos faltantes del handoff**: número que devuelve la regla vigente de completitud del handoff (0 a 9).
  - **Actividad**: número de eventos del lead de tipo cambio de etapa, cambio de campo o reasignación ocurridos en los 30 días calendario de Bogotá anteriores al día de captura (el día de captura incluido); número de notas (solo el conteo).
  - **Cadencia**: estado (`active`, `paused`, `completed`, `stopped`, o `ninguna` si el lead no tiene cadencia), pasos hechos, pasos totales, envíos hechos, si tiene fecha de próxima acción, y días calendario de Bogotá hasta esa acción (negativo si está vencida; 0 si no tiene fecha).
  - **Pendientes**: número de propuestas del lead en estado pendiente (de cualquier tipo, incluidas las de solicitud de autorización), de alertas sin resolver del lead (las alertas sin lead no cuentan) y de solicitudes de titular no atendidas del lead (abiertas o vencidas).
  - **Día de la semana** del día de captura (0 a 6).
- **VJC-013** EL SISTEMA aplica a cada entero un tope fijo (propuesta: 365 días, 50 eventos, 50 notas, 50 envíos, 50 pendientes, ±365 días hasta la próxima acción), de modo que un valor mayor se registra como el tope.
- **VJC-014** EL SISTEMA identifica a cada lead en los archivos únicamente con su referencia (VJC-016 define la clave) y no guarda el número interno; SI no hay clave configurada, ENTONCES EL SISTEMA no activa la instantánea y avisa al CTO por Telegram una vez por arranque, con el mismo mecanismo que usa para los demás avisos de configuración. Cambiar la clave equivale a reiniciar el piloto: las líneas con referencias de la clave anterior no pueden reconciliarse y se retiran (VJC-022).
- **VJC-015** EL SISTEMA no guarda en el vector ni nombre, empresa, representante, correo, teléfono, documento, notas, motivo escrito, texto del valor pactado o del servicio, ni el texto de ningún mensaje: esos campos solo se miran para saber si están vacíos.
- **VJC-016** EL SISTEMA calcula la referencia con un código de autenticación de mensaje (HMAC-SHA-256) del número interno con una clave secreta propia de esta funcionalidad, guardada solo en la configuración del servidor, y la acorta a 16 caracteres hexadecimales.

### 6.3 Archivos, retención, supresión y retiros

- **VJC-020** EL SISTEMA escribe las instantáneas en líneas independientes, con versión de esquema, en un archivo por día de captura (nombre con la fecha) dentro del directorio de datos persistente del CRM, de modo que la herramienta de la flota pueda leerlas sin código del CRM e ignorar una última línea incompleta.
- **VJC-021** EL SISTEMA elimina los archivos de instantáneas con fecha anterior al número de días de retención configurado (propuesta: 90), y los de retiros con fecha anterior a 30 días, al comienzo de cada corrida; si se reduce la retención, se aplica en la siguiente corrida.
- **VJC-022** CUANDO comienza una corrida, ANTES de escribir, EL SISTEMA elimina de todos los archivos de instantáneas las líneas cuya referencia no corresponda a un lead elegible, es decir, la de un lead suprimido, en estado «baja», con autorización revocada o inexistente en la base (este último caso solo por robustez, porque la supresión actual no borra filas), y las de una clave anterior (VJC-014).
- **VJC-023** SI EL SISTEMA no puede reescribir un archivo para quitar líneas (VJC-022), ENTONCES elimina ese archivo completo, avisa sin datos de leads y no escribe las líneas nuevas del día hasta resolverlo.
- **VJC-024** CUANDO elimina líneas por VJC-022, EL SISTEMA anota cada referencia retirada y el día del retiro (y nada más) en un archivo de retiros por día, con nombre que lleva la fecha, en el mismo directorio y con una retención de 30 días (propuesta), para que la herramienta de la flota retire sus copias.

### 6.4 Aislamiento y dependencias

- **VJC-030** EL SISTEMA no incluye la herramienta de la flota entre las dependencias del proyecto ni la importa en ningún módulo (verificable con un análisis estático).
- **VJC-031** EL SISTEMA no contiene en el código del CRM la llave de acceso a TypeSafe, ni la dirección de su servicio, ni el identificador del modelo de Jev (verificable con una búsqueda de cadenas en las pruebas).
- **VJC-032** EL SISTEMA no añade dependencias nuevas al proyecto y usa solo la biblioteca estándar para escribir, rotar y reescribir los archivos.

### 6.5 Calidad

- **VJC-040** EL SISTEMA mantiene la verificación completa del proyecto en verde y la cobertura total por encima del 89 % con el código añadido por esta spec.

## 7. Contrato con la herramienta de la flota (para `kai-jev`)

No es una tarea para el CRM ni se verifica con pruebas del CRM:

1. **Lectura** de los archivos de instantáneas (VJC-020), ignorando una última línea incompleta y deduplicando por (referencia, día).
2. **Aplicar los retiros** del archivo de retiros (VJC-024) a todas sus copias y **la misma retención** que el CRM. Los archivos copiados quedan fuera del control del CRM.
3. **Qué se envía a Jev:** solo los campos del vector de VJC-012. **Nunca** la referencia del lead ni el día de captura (con la antigüedad permitirían reconstruir la fecha de registro).
4. **Esquema de vector** propio del CRM; el esquema vigente de la flota es de tareas de desarrollo.
5. **Preguntas a Jev** (propuesta):
   - `urgencia` — tipo `score` ordenado: «baja» (no requiere acción en los próximos 7 días), «moderada» (requiere acción entre 3 y 7 días), «alta» (requiere acción en 48 horas), «critica» (requiere acción hoy: tiene una acción de cadencia vencida, una alerta sin resolver o un plazo por vencer).
   - `siguiente_paso` — tipo `choice`: «esperar» (no hay nada que hacer todavía), «contactar_hoy» (hablar con el cliente), «enviar_propuesta» (el lead está listo para recibir una propuesta), «completar_datos» (faltan campos del handoff), «escalar_cto» (necesita decisión del CTO). Solo se ofrecen pasos reversibles: **no** hay opciones de cerrar, dar por perdido, dar de baja ni enviar.
6. **Consenso** de tres respuestas por lead y día; los casos sin consenso se cuentan aparte.
7. **Etiquetas de resultado** calculadas comparando instantáneas de días distintos: hay interacción nueva entre el día D y el día D+k cuando los días desde la última interacción en D+k son menores que los de D más k; los leads con 365 días o más se excluyen de la etiqueta.
8. **Informe** con comparación contra la línea base, calibración (Brier y error de calibración), latencia, costo y número de leads distintos.
9. **Traslado de los archivos** del servidor a la herramienta: pregunta Q1.
10. **Modelo `jev-latest`** y sin tope diario (decisión CTO 12/10). Registrar la versión que devuelva Jev, porque cambia con el tiempo. La excepción a «modelos pineados» (constitución, principio 5) debe constar por escrito del CTO, con fecha, en el registro de la herramienta de la flota **antes de activar cualquier consulta a Jev**. El CRM no contiene ese identificador (VJC-031), así que esta spec no enmienda la constitución.

## 8. Criterios de decisión al cierre del piloto

Son **criterios de negocio** para que el CTO decida, no requisitos verificables con pruebas del CRM. Todos los umbrales son una **propuesta**.

- **Etiquetas (propuesta):** `avance_14d` = en los 14 días siguientes hubo interacción nueva (punto 7 de la sección 7) o el lead avanzó en el orden `new` < `contacted` < `accepted` < `won` (pasar a `rejected`, `lost`, `nurturing`, `paused` o `reactivated` no cuenta como avance); `desenlace_30d` = a los 30 días el lead está en `won`, `lost` o sigue abierto.
- **Línea base:** el orden actual por última interacción. Referencia de comparación: entre el 20 % de leads que cada orden pone primero, la proporción que tiene `avance_14d`.
- **Muestra mínima:** al menos 30 leads distintos y 100 pares (lead, día) con la ventana de 14 días completa, durante al menos 8 semanas, con un máximo de 12. Si pasado ese máximo no se alcanza, se declara «no concluyente» y se cierra.
- **Éxito indicativo (continuar a una spec posterior que muestre la sugerencia al comercial):** Jev supera a la línea base en 15 puntos porcentuales o más en la métrica anterior, y su probabilidad de avance tiene un Brier menor que el de predecir siempre la tasa base.
- **Cierre negativo o no concluyente:** el informe lo declara; no se invierte más en C1.
- **Regla permanente:** Jev solo sugiere; la persona decide. Ninguna spec futura puede dejar que Jev ejecute una acción irreversible.

## 9. Preguntas abiertas para el CTO

**Bloquean el Gate 1:**
- **Q2 — Cuántos leads distintos esperas en las próximas 12 semanas.** Si son menos de 30 (el mínimo de la sección 8), el piloto se declara no viable desde el inicio y no vale la pena implementar nada.
- **Q5 — Base legal de los archivos seudonimizados.** Tanto el archivo de instantáneas como el de retiros contienen una referencia que el CRM puede reidentificar con su clave (el de retiros, además, revela que ese titular fue dado de baja o suprimido, durante 30 días). El de instantáneas contiene datos estructurados de un titular identificados por esa referencia; es **seudonimización, no anonimización** (con pocos leads, la combinación de etapa, antigüedad y fechas puede ser casi única para quien conoce la cartera). El aviso de privacidad cubre el tratamiento comercial; no consta que cubra un piloto de evaluación con un tercero. El flujo a Jev no lleva referencia ni fecha, pero el CTO y el abogado deben confirmar la base legal y la finalidad antes de implementar.

**No bloquean:**
- **Q1 — Traslado de archivos.** Opciones: (a) copia manual periódica autorizada por el CTO; (b) ejecutar la herramienta en el servidor (implicaría poner la llave de TypeSafe allí); (c) un comando del CRM que exporte los archivos. Esta spec propone (a) para el piloto.
- **Q3 — Etiqueta humana.** ¿Duván (o el CTO) aceptaría marcar cada semana «los 3 leads que atendería primero»? Daría etiquetas más rápidas que esperar desenlaces. Sería una funcionalidad aparte del bot.
- **Q4 — Retención** de 90 días (propuesta).
- **Q6 — Umbrales** de la sección 8.
- **Q7 — Clave de la referencia.** El CTO coloca la clave en la configuración del servidor (nunca en el repositorio). Si se cambia, las referencias de los días anteriores dejan de coincidir.

## 10. Riesgos

| Riesgo | Mitigación |
|---|---|
| Volumen insuficiente para concluir (riesgo central) | Se declara en la sección 3; máximo de 12 semanas y cierre «no concluyente». |
| La captura afecta al CRM | Apagada por defecto, solo lectura, aislada de los demás trabajos, tolerante a fallos (VJC-002, VJC-005, VJC-006). |
| Fuga de datos personales al archivo o a Jev | Lista cerrada de campos, referencia con clave en vez del número interno, prueba de privacidad; la referencia y el día nunca van a Jev (VJC-012, VJC-014 a VJC-016 y sección 7). |
| Datos derivados de un lead suprimido quedan en los archivos o en copias | Reconciliación al comienzo de cada corrida y archivo de retiros que la flota debe aplicar (VJC-022 a VJC-024). Los respaldos del CRM conservan datos hasta 30 días por política vigente. |
| Apagar la funcionalidad deja líneas sin reconciliar | Apagarla exige borrar la carpeta de instantáneas ese mismo día (procedimiento de despliegue); apagada, el CRM no retira ni purga nada. |
| Ventana de hasta 24 horas entre una supresión y el retiro de sus líneas (también si el barrido legal se reintenta después de la corrida) | Aceptada y declarada: el retiro ocurre al comienzo de la siguiente corrida diaria. |
| Que alguien trate la sugerencia de Jev como una decisión | Fuera de alcance mostrarla; solo opciones prudentes; regla permanente (sección 8). |
| Confianza de Jev sin calibrar | Se mide y se exige mejora del Brier antes de cualquier uso. |

## 11. Trazabilidad con el informe

| Requisito | Origen |
|---|---|
| VJC-001, VJC-005, VJC-030, VJC-031 | La IA propone, el código decide; siempre con respaldo (lecciones de Trading 1 y 6). |
| VJC-011 a VJC-016 | State compacto sin texto libre y privacidad (lecciones 5 y 8; decisión CTO 12/10). |
| VJC-020 a VJC-024 | Registro de cada decisión para auditar y Ley 1581 (lecciones 7 y 8). |
| Sección 8 | Modo sombra, medir contra la línea base y calibrar (lecciones 2 y 3). |

> 🕒 **Última modificación:** 13/10/2026 22:16 (Agente Claude Code · Sonnet 5.5)
