---
modificado: "13/10/2026 22:41"
---

# Spec 007 — Capa de decisión con Jev para todo Jericó

- **Estado:** **BORRADOR (versión 3, tras dos auditorías QA) — pendiente de aprobación del CTO (Gate 1).** No se implementa nada, no se despliega nada y no se gasta nada hasta que el CTO apruebe cada paso.
- **Tipo de cambio:** funcionalidad nueva y transversal. Parte del CRM ya desplegado y se extiende al núcleo, al asistente Hermes (spec 005), a marketing (F5) y a finanzas (F6).
- **Fuente:** Plan maestro de Jericó (§2.8, §4, §6, §7; 13/10/2026), directiva del CTO del 13/10 («usar Jev para decidir y ahorrar tokens»), spec 005 (§3.1 y §3.2), spec 002 (router en sombra), módulo CRM-consejero (antes spec 006), informe `Proyecto_Jerico_Implementacion_Jev` (secciones 8 a 15) y medición de la flota con Jev (12/10/2026).
- **Convención de marcas:** `(decisión CTO)` — ya decidido por el CTO; `(Plan maestro §N)` — regla del plan; `(propuesta)` — valor propuesto, el CTO decide; `(supuesto)` — no verificado; `(sin verificar aquí)` — dato de otra fuente que esta spec no pudo comprobar.
- **Qué es esta spec:** el **contrato común** de la función de decisión que la spec 005 llama `decidir(pregunta, estado) → opción`: tipos de decisión, clases de riesgo, modos, límites de privacidad, registro y medición. Cada área conserva su spec; esta define lo que tienen en común y deja explícito lo que cada una debe aportar (sección 9).

## 1. Contexto verificado

- **Producción hoy:** `kaisen-server` ejecuta solo el CRM. El asistente del CRM usa **un único modelo fijo** (`gpt-6-luna`, vía OpenAI) y no existe enrutador de modelos en el CRM; sus tarifas están sin configurar y el costo sale «no calculado» (verificado en el código de la rama desplegada).
- **Núcleo (no desplegado):** el router de niveles usa palabras clave; el modelo de su nivel de alto riesgo está vacío por defecto y en ese caso se usa el del nivel de código; el núcleo resuelve la dirección, la llave y el modelo por nivel, de modo que ya admite un proveedor distinto por nivel (verificado en la configuración y el cliente del núcleo).
- **Regla de enrutamiento del Plan maestro (§4), decidida con Jev el 13/10:** tareas ligeras del CRM → `deepseek-chat` (solo con datos seudonimizados); textos que lee el cliente → `gpt-6-luna`; contratos, precios finales y decisiones críticas → `gpt-6-luna`; Gemini 3.8 Flash, Argon y Opus como opciones que Jev evalúa por costo y calidad. **Esa tabla es la línea base** que Jev debe superar.
- **Spec 005 (§3.1):** define cuatro puntos de decisión del asistente —`modelo`, `habilidad`, `escalar_humano`, `siguiente_paso_voz`—, cada uno detrás de una función `decidir` con regla fija de respaldo, y deja el seguimiento de leads a esta spec. Su requisito R11 exige respaldo, registro del `model` devuelto, costo y tokens, y prohíbe enviar a Jev texto libre o datos personales.
- **Presupuesto (Plan maestro §4 y §6):** 10 a 25 USD al mes en total; la parte de LLM se estima en unos 3 USD (escenario A) a 7 USD (escenario B), **sin verificar**. El tope de 60 000 tokens al día del asistente es nuestro y se ajusta por configuración.
- **Jev medido en la flota (nota `Flota_Implementacion_Jev`, 12/10/2026; sin verificar aquí):** unos 596 tokens por llamada, latencia mediana de 280 ms y p95 de 346 ms, costo de USD 0,0023 por 90 llamadas (unos USD 0,0000256 por llamada). Consenso de 3 respuestas iguales en 29 de 30 tareas. La confianza **no vino calibrada** para la pregunta de modelo (error de calibración 0,33) y vino mejor para la de revisión de seguridad (0,08). Jev devuelve la versión del modelo que respondió (por ejemplo `jev-1.13.0`).
- **Hay tres clientes de Jev distintos hoy,** con la misma lógica de HTTP y de lectura de la respuesta: el de Trading, el de la herramienta de la flota y el script de decisión de la flota (verificados por existencia de los archivos).

## 2. Principios (heredados de las decisiones del CTO)

1. La IA propone, el código decide. Jev **elige entre opciones** que el código ya calculó como permitidas; nunca ejecuta una acción ni ve datos de clientes.
2. Toda decisión tiene una **regla fija de respaldo**: si Jev falla, tarda o responde algo inválido, se aplica la regla.
3. **Primero sombra:** Jev opina, manda la regla; solo toma el control de un tipo de decisión con evidencia medida y con la orden del CTO para ese tipo.
4. La confianza de Jev **no está calibrada**: se mide antes de usarla como umbral.
5. Solo categorías y contadores hacia Jev: sin texto libre ni identificadores.
6. Nada de pagos ni despliegues sin el OK explícito del CTO para ese paso.

## 3. Clases de decisión

| Clase | Qué cubre | Qué puede hacer Jev |
|---|---|---|
| **A — Legal, irreversible o de dinero** | Bajas y supresiones (Ley 1581), contratos, firma, cálculo de precios, publicar o gastar, enviar a un cliente, acciones sobre producción | **Nada.** La regla fija decide. Jev no se consulta o, si se consulta fuera de línea, no se aplica. |
| **B — Crítica con regla base** | Texto que puede leer el cliente, nivel de riesgo del turno, si pedir aprobación humana, ruta de una consulta financiera | **Solo subir:** pedir más revisión, un modelo superior o una aprobación humana, según el orden de exigencia que declara la política para ese tipo. Nunca bajar lo que fija la regla. |
| **C — Ligera, interna y con datos controlados** | Clasificar, extraer campos, resumir, elegir habilidad, elegir entre modelos baratos | Puede elegir entre las opciones permitidas, incluso un modelo más barato, solo en modo enrutado y solo con datos de clase `sin_datos_personales` o `seudonimizado_verificado`. |
| **D — Desarrollo de Jericó** | Asignar tareas a Gemini, Sonnet u Opus; si un cambio necesita revisión de seguridad | Lo cubre la herramienta de la flota; esta spec no la duplica. |
| **Asesor** (propiedad de un tipo, no una clase) | Seguimiento de leads | Su salida **nunca se aplica automáticamente**: solo se registra y, en una spec futura aprobada por el CTO, se podrá mostrar como sugerencia. |

**La clase pertenece al par (tipo, tarea)** y se fija en la política base, no en la respuesta de Jev (VJT-006, VJT-009).

## 4. Catálogo inicial de tipos y tareas

| Tipo | Área | Clase | Pregunta | Opciones permitidas (las calcula el código) | Base (regla fija) | Dependencia |
|---|---|---|---|---|---|---|
| `modelo_asistente` | CRM (desplegado) | Por tarea (tabla siguiente) | ¿Con qué modelo se atiende esta tarea del asistente? | Los modelos que la política permita para la tarea y la clase de datos | La tabla del Plan maestro §4 | LLM de más de un proveedor (sección 9) |
| `seguimiento_lead` | CRM | Asesor (nunca se aplica) | Urgencia (`score`) y siguiente paso (`choice`) del lead | Pasos reversibles | Orden actual por última interacción | Módulo CRM-consejero |
| `nivel_turno` | Núcleo | B | ¿L1, L2 o L3? | L1, L2, L3 | Palabras clave del router | Spec 002; núcleo desplegado |
| `modelo` | Hermes (005) | Por tarea (la misma tabla de modelos) | Modelo por tarea | Según política | Tabla de la 005 §3.2 | Spec 005 |
| `habilidad` | Hermes (005) | C | Qué habilidad activar | Habilidades permitidas al rol | Regla de intención de la 005 | Spec 005 |
| `escalar_humano` | Hermes (005) y otros | B | ¿Pedir aprobación? | Pedir o no pedir | **Siempre pedir** si hay efecto externo o es irreversible | Spec 005 |
| `siguiente_paso_voz` | Hermes, voz (005) | B | ¿Continuar o pasar a humano? | Continuar o pasar | Pasar a humano ante duda | Spec 005 |
| `riesgo_pieza` | Marketing F5 | B | Nivel de riesgo de una pieza antes de la aprobación | bajo, moderado, alto | **Siempre aprobación humana** | F5 (spec 008, sin escribir) |
| `ruta_consulta_financiera` | Finanzas F6 | B | ¿Herramienta de precios, respuesta conceptual o humano? | herramienta, conceptual, humano | **Toda cifra o precio → herramienta** | Spec 006 (catálogo) |

**Orden de exigencia** (de menor a mayor; lo declara la política para cada tipo y tarea de clase B, y la política se rechaza si falta): modelos de texto para el cliente (`modelo_asistente` y `modelo`, tarea «borrador»): `deepseek-chat` < `gemini-3.8-flash` < `gpt-6-luna` < `claude-opus-5.5` (propuesta, a confirmar con la evaluación y las tarifas de Q2); `nivel_turno`: L1 < L2 < L3; `escalar_humano`: no pedir < pedir; `siguiente_paso_voz`: continuar < pasar a humano; `riesgo_pieza`: bajo < moderado < alto; `ruta_consulta_financiera`: conceptual < herramienta < humano (Jev solo puede pasar de «herramienta» a «humano», nunca a «conceptual»).

**Tabla tarea → clase de `modelo_asistente`** (hoy y prevista):

| Tarea | Estado | Clase | Datos |
|---|---|---|---|
| Resumen de un lead | Existe | C | `con_datos_personales` (contexto con campos de texto libre) |
| Pregunta con cifras agregadas | Existe | C | `con_datos_personales` |
| Borrador (texto que puede leer el cliente) | Existe | B | `con_datos_personales` |
| Clasificar, extraer, resumir notas | Prevista (005 §3.2) | C | `con_datos_personales` mientras las notas sean texto libre y no se resuelva Q3 (VJT-023) |
| Generar páginas web o aplicaciones | Prevista (005, A3) | C | `sin_datos_personales` (en entorno aislado) |
| Contratos y precios finales | Prevista | A (contratos: abogado; precios: herramienta de F6) | — |

**Hallazgo sobre `modelo_asistente`:** con esa tabla, todas las tareas actuales del asistente tienen un único modelo permitido (`gpt-6-luna`); por eso VJT-008 manda no consultar a Jev y este tipo queda registrado pero inactivo hasta que existan tareas ligeras con datos de origen estructurado y un segundo proveedor de LLM. **El primer caso con decisión real en el CRM desplegado es `seguimiento_lead`.**

**Fuera de la capa (clase A):** bajas por la palabra «BAJA», supresión, asociación de respuestas a leads, autorización ✅/❌, handoff completo, generación o firma de contratos, aprobación de envío y publicación o gasto en campañas. P2 (triaje de respuestas «por clasificar») sigue en espera.

## 5. Requisitos (EARS)

Prefijo `VJT-`. Definiciones:
- **Tipo de decisión:** una fila de la sección 4 (o una añadida después con la misma estructura).
- **Política base:** archivo versionado que declara, para cada par (tipo, tarea): clase, esquema del estado con sus rangos, opciones con su criterio, orden de exigencia, función que calcula las opciones permitidas, opción base y modo por defecto.
- **Modo:** `apagado`, `sombra`, `sugerencia` o `enrutado`.
- **Nivel 1:** funcionamiento sin llamadas de red a Jev desde el producto. **Nivel 2:** el producto consulta a Jev en línea.
- **Decisión:** el resultado de pedir una opción para un tipo con un estado: opción aplicada, fuente (`base`, `jev`, `cache` o `respaldo`) y motivo.
- **Clave de decisión:** valor determinista derivado de (tipo, tarea, estado, versión de política); sirve para la caché. **Identificador de evento:** valor único por ocurrencia, sin datos personales (instante y secuencia); sirve para el registro y para unir respuestas.

### 5.1 Límites de lo que Jev puede decidir

- **VJT-001** EL SISTEMA aplica en cada decisión únicamente una opción que pertenezca al conjunto permitido calculado por el código antes de consultar a Jev.
- **VJT-002** SI la respuesta de Jev tiene un formato inválido, o una opción desconocida, o una opción fuera del conjunto permitido, ENTONCES EL SISTEMA aplica la opción base y registra el motivo correspondiente (`formato_invalido`, `opcion_desconocida` o `fuera_de_permitidas`).
- **VJT-003** EL SISTEMA no aplica nunca una respuesta de Jev en tipos y tareas de la clase A y aplica siempre su regla fija.
- **VJT-004** EL SISTEMA, en la clase B, aplica la opción de Jev solo si es igual o más exigente que la base según el orden de exigencia del tipo; en caso contrario aplica la base.
- **VJT-005** EL SISTEMA, en la clase C, aplica una opción distinta de la base solo en modo `enrutado` y solo cuando la clase de datos de la tarea es `sin_datos_personales` o `seudonimizado_verificado`.
- **VJT-006** EL SISTEMA toma la clase, el orden de exigencia y el conjunto permitido de la política base versionada y no de la respuesta de Jev.
- **VJT-007** EL SISTEMA no ofrece a Jev ninguna opción que ejecute una acción externa, calcule un precio, publique, gaste o cambie el estado de un titular.
- **VJT-008** SI el conjunto permitido de una decisión tiene una sola opción, ENTONCES EL SISTEMA devuelve esa opción sin consultar a Jev y la registra con fuente `base` y motivo `una_opcion`; esas decisiones no cuentan para los criterios de promoción de la sección 7.
- **VJT-009** EL SISTEMA define la clase y la clase de datos esperada de cada par (tipo, tarea) en la política base, incluida la tabla tarea → clase de la sección 4.
- **VJT-010a** EL SISTEMA trata como asesor el tipo `seguimiento_lead`: registra su salida y no la aplica a ningún flujo ni la muestra a ningún usuario.

### 5.2 Modos

- **VJT-010** EL SISTEMA mantiene el modo de cada tipo de decisión por configuración, con valor por defecto `apagado` para todos.
- **VJT-011** MIENTRAS un tipo esté en modo `apagado` o `sombra`, EL SISTEMA aplica siempre la opción base.
- **VJT-012** MIENTRAS un tipo esté en modo `sugerencia`, EL SISTEMA aplica la opción base y muestra la opción de Jev únicamente a un usuario con rol de CTO verificado por el mecanismo de identidad que ya usa el CRM, y en el registro; nunca a clientes ni a otros usuarios.
- **VJT-013** EL SISTEMA solo pasa un tipo a `sugerencia` o `enrutado` cuando el CTO lo ordena para ese tipo, después de cumplir los criterios de promoción de la sección 7.
- **VJT-014** CUANDO existe el archivo marcador de apagado general (ubicado fuera del directorio de retención del registro y comprobado en cada decisión), EL SISTEMA aplica la opción base en todos los tipos sin reiniciar el proceso; la variable de configuración equivalente exige reiniciar.
- **VJT-015** SI un tipo en modo `sugerencia` o `enrutado` acumula 3 respuestas inválidas o fallos seguidos (propuesta), ENTONCES EL SISTEMA vuelve ese tipo a `sombra` y avisa al CTO por el mismo canal que usa el CRM para los avisos de configuración, o en el registro de la aplicación si ese canal no está disponible; la degradación se guarda en un archivo marcador por tipo y sobrevive a los reinicios hasta que el CTO ordene lo contrario.

### 5.3 Estado y privacidad

- **VJT-020** EL SISTEMA construye el estado de cada tipo únicamente con valores enumerados, booleanos y enteros **agrupados en rangos** definidos en la política base (por ejemplo, días: 0, 1–2, 3–7, 8–14, 15–30, 31–90, más de 90), y lo valida antes de entregarlo; no entrega enteros exactos que, combinados con pocos casos, puedan identificar a un titular.
- **VJT-021** EL SISTEMA no incluye en el estado texto libre, nombres, teléfonos, correos, documentos, notas, rutas, secretos, identificadores de lead, de sesión o de usuario, ni fechas absolutas. «Texto libre» es cualquier campo cuyo valor no pertenezca a una lista cerrada o a un rango definido en la política.
- **VJT-022** EL SISTEMA calcula la clase de datos de cada tarea con valores `sin_datos_personales`, `seudonimizado_verificado` y `con_datos_personales`, y SI la clase que declara la política para la tarea y la que calcula quien llama difieren, ENTONCES aplica la más restrictiva, y SI la clase no se puede establecer por el origen de los datos (VJT-023), ENTONCES asigna `con_datos_personales`.
- **VJT-023** EL SISTEMA considera «seudonimizado verificado» únicamente un contexto construido en origen solo con campos estructurados de lista cerrada (etapa, estado, conteos, rangos, motivos de la lista fija) más los marcadores del seudonimizador, con una marca explícita de que no incluyó ningún campo de texto libre (notas, motivo escrito, valor escrito, empresa o cargos de terceros), y sin esa marca el contexto se trata como `con_datos_personales`; la pasada por el seudonimizador **no basta**, porque este declara que no detecta nombres de terceros en texto libre.
- **VJT-024** EL SISTEMA no permite que una tarea con clase de datos `con_datos_personales` se enrute a un modelo fuera de los permitidos para esa clase en la política base (en particular, nunca a `deepseek-chat`).
- **VJT-025** EL SISTEMA valida el estado de cada decisión antes de registrarlo y de entregarlo, en todos los modos; SI no cumple la validación, ENTONCES no lo registra ni lo entrega, aplica la opción base, cuenta el descarte y anota el motivo sin datos.
- **VJT-026** EL SISTEMA registra, para los tipos que describen a un lead individual, la bandera `cohorte_suficiente` (verdadera cuando los leads activos alcanzan el mínimo configurado, propuesta 20) y no consulta a Jev en línea cuando es falsa; la herramienta de la flota respeta esa bandera al leer los registros. El mínimo reduce, no elimina, el riesgo de identificación: la combinación de rangos de un lead puede seguir siendo única, por lo que Q5 exige además la confirmación del abogado.

### 5.4 Resiliencia y rendimiento

- **VJT-030** EL SISTEMA devuelve siempre una decisión, sin lanzar excepciones al módulo que decide, aun cuando Jev, la red, la clave, la caché o el registro fallen.
- **VJT-031** EL SISTEMA espera la respuesta de Jev como máximo 3 segundos, reintenta una vez ante respuestas 429 o 529 (propuesta) y, si no hay respuesta válida, aplica la base con fuente `respaldo`.
- **VJT-032** CUANDO se acumulan 3 fallos seguidos de Jev (propuesta), EL SISTEMA deja de consultar durante 5 minutos (propuesta) y aplica la base; el contador y la pausa viven en memoria y se reinician con el proceso.
- **VJT-033** MIENTRAS el producto consulta a Jev, EL SISTEMA no retrasa el procesamiento de otros mensajes más de 100 ms (verificable con una consulta simulada de 2 segundos).
- **VJT-034** CUANDO se repite la misma clave de decisión dentro de la vigencia de la caché (propuesta: 24 horas), EL SISTEMA devuelve la decisión anterior con fuente `cache` y no consulta de nuevo; la caché vive en memoria y se reinicia con el proceso.
- **VJT-035** EL SISTEMA, en el Nivel 2, realiza una sola consulta por decisión; el consenso de varias respuestas lo calcula solo la herramienta de la flota fuera de línea, y SI las respuestas no coinciden, ENTONCES esa decisión se cuenta como `sin_consenso` y no entra en las métricas de acierto.
- **VJT-036** CUANDO dos decisiones con la misma clave llegan a la vez, EL SISTEMA realiza una sola consulta a Jev y entrega el mismo resultado a ambas.
- **VJT-037** SI Jev devuelve opciones con la misma probabilidad, ENTONCES EL SISTEMA aplica la opción base.

### 5.5 Registro, idempotencia y control

- **VJT-040** EL SISTEMA registra cada decisión con campos **obligatorios en todos los modos**: identificador de evento, clave de decisión, tipo, tarea, modo, estado, opción base, opción aplicada, opción sugerida por Jev cuando la hay, fuente, motivo, versión de la política, bandera `cohorte_suficiente` cuando corresponda e instante; y con campos **solo cuando hubo consulta en línea** (Nivel 2): respuesta de Jev (opción, confianza y probabilidades), versión del modelo de Jev que respondió, latencia y tokens de entrada; sin texto libre.
- **VJT-041** EL SISTEMA construye la clave de decisión de forma determinista a partir de (tipo, tarea, estado, versión de política) para la caché, y genera un identificador de evento único por ocurrencia (instante, secuencia y sufijo aleatorio, de modo que no colisione entre procesos ni tras reinicios), de modo que decisiones de casos distintos con el mismo estado se registran por separado y repetir un evento con el mismo identificador no duplica el registro.
- **VJT-042** EL SISTEMA exige que toda acción que se dispare como consecuencia de una decisión use una clave de idempotencia determinista y respete el modo de comunicaciones externas simuladas (`JERICO_EXTERNAL_COMMS_DRY_RUN`) del Plan maestro.
- **VJT-043** EL SISTEMA conserva el registro de decisiones como máximo 90 días (propuesta) en archivos diarios de registro, como el registro de auditoría existente, y no en la base de datos de dominio, porque es información de observación que se puede borrar sin afectar datos de clientes.
- **VJT-044** EL SISTEMA no impone un tope diario de consultas a Jev (decisión CTO 12/10) y avisa al CTO, sin cortar el servicio, cuando las consultas de un día superen cinco veces la mediana de los 14 días anteriores, siempre que haya al menos 14 días de historia y la mediana sea de al menos 10 consultas al día (propuesta); en el Nivel 1 no hay consultas del producto y este requisito queda inactivo.
- **VJT-045** SI no hay tarifas configuradas para un modelo de lenguaje, ENTONCES EL SISTEMA registra su costo como «no calculado» y no publica cifras de ahorro para ese modelo; el costo de las consultas a Jev sale de la medición de la flota y se registra como estimado.
- **VJT-046** EL SISTEMA escribe los registros solo por anexión y con identificador de evento, de modo que la herramienta de la flota pueda escribir las respuestas de Jev en un archivo aparte unidas por ese identificador, sin modificar el registro original.

### 5.6 Cliente de Jev y secretos

- **VJT-050** EL SISTEMA contiene una sola implementación del cliente de Jev en producción y no duplica la de la herramienta de la flota ni la de Trading (pregunta Q1).
- **VJT-051** EL SISTEMA lee la llave de TypeSafe únicamente de la configuración del servidor y no la registra ni la incluye en mensajes de error.
- **VJT-052** SI la llave no está configurada, ENTONCES EL SISTEMA no consulta a Jev, aplica la base en todos los tipos y avisa al CTO una vez por arranque por el canal de avisos de configuración del CRM o, si no está disponible, en el registro de la aplicación.
- **VJT-053** EL SISTEMA solicita a Jev el modelo configurado (por defecto `jev-latest`, sujeto a la pregunta Q8) y registra en cada decisión la versión que devuelve.
- **VJT-054** EL SISTEMA no realiza llamada de red a Jev desde el proceso del producto en modo `apagado`, ni en modo `sombra` mientras el Nivel 2 no esté habilitado por configuración (clave presente y habilitación explícita, por defecto desactivada); con el Nivel 2 habilitado, en `sombra` el producto puede consultar en línea solo para registrar la respuesta, sin esperarla ni usarla para decidir. En el Nivel 1 la herramienta de la flota consulta a Jev por separado (VJT-046).
- **VJT-055** SI un proveedor nuevo (TypeSafe, DeepSeek u otro) va a recibir datos personales, ENTONCES antes de activarlo se añade a los encargados del tratamiento y al aviso de privacidad (proceso previo a la activación; verificado por el abogado).

### 5.7 Reglas por área

- **VJT-060** EL SISTEMA responde toda consulta de precios, cotizaciones o cifras comerciales con la herramienta determinista de finanzas (`consultar_catalogo`) y no ofrece a Jev ni al modelo de lenguaje la opción de calcularlas.
- **VJT-061** EL SISTEMA no permite que una decisión de Jev publique, gaste o envíe algo de marketing; en esos casos solo puede subir la exigencia de aprobación humana.
- **VJT-062** EL SISTEMA no consulta a Jev sobre contratos, firma, bajas, supresiones o autorización de datos (clase A).
- **VJT-063** EL SISTEMA registra el módulo CRM-consejero como el tipo de decisión `seguimiento_lead` (asesor), con el vector y las preguntas de ese módulo, y lo deja apagado por defecto y activable en modo `sombra` por configuración.

### 5.8 Calidad

- **VJT-090** EL SISTEMA mantiene la verificación completa del proyecto en verde y la cobertura total por encima del 89 % con el código añadido por esta spec.
- **VJT-091** EL SISTEMA no añade dependencias nuevas al proyecto (verificable comparando la lista de dependencias con la de la rama base).

## 6. Cuenta del costo y del ahorro

**Costo de Jev** (medición de la flota, sin verificar aquí): unos 596 tokens de entrada por llamada y USD 0,0000256 por llamada. La consulta de esta redacción usó 709 tokens porque su estado era más largo. El consenso de 3 respuestas es un cálculo (3 × el costo de una llamada, USD 0,0000767), no una medición. En el Nivel 2 se hace una sola consulta por decisión (VJT-035), y con caché (VJT-034) el costo real es menor.

| Volumen de decisiones al mes (supuesto) | Una consulta cada una | Con consenso de 3 (offline) |
|---|---|---|
| 3 000 | USD 0,08 | USD 0,23 |
| 30 000 | USD 0,77 | USD 2,30 |
| 300 000 | USD 7,68 | USD 23,0 |

**Ahorro posible.** Una decisión solo ahorra si evita una llamada a un modelo más caro: ahorro por decisión = probabilidad de evitar el modelo caro × (precio del caro − precio del barato) − costo de Jev. Los precios por modelo **no están verificados** y las tarifas del asistente están sin configurar; por eso **esta spec no afirma ningún ahorro**.

**Orden de magnitud con lo que sí está escrito.** El tope del asistente (60 000 tokens al día) permite como máximo 1,8 millones de tokens al mes en ese asistente (es un tope del asistente, no de Jev); la parte de LLM del presupuesto es de unos 3 a 7 USD al mes (sin verificar). Aun suprimiendo todo ese gasto, el máximo en juego es de esa magnitud. Hoy, con 0 leads y un solo usuario, el ahorro del CRM es despreciable. El valor de la capa está en el **control de riesgo** y en el **volumen futuro** (asistente Hermes, voz y marketing masivo), no en el CRM actual.

**Cuándo no vale la pena consultar a Jev.** Con una sola opción permitida (VJT-008) o con una base sin ambigüedad, consultar a Jev solo añade 280 ms y centavos. Un tipo se mantiene en `enrutado` únicamente mientras su informe muestre ahorro neto positivo (método: diferencia entre el costo con la base y el costo con las decisiones aplicadas, con tarifas verificadas, menos el costo de Jev) o una reducción medida de riesgo (menos escalamientos tardíos a un modelo superior que con la base).

## 7. Criterios de promoción entre modos

Son criterios de negocio para que el CTO decida; los umbrales son una **propuesta**. Las decisiones de opción única (VJT-008) no cuentan.

- **De `apagado` a `sombra`:** orden del CTO para ese tipo; verificación de privacidad del estado (VJT-020 a VJT-026). Que la herramienta de la flota consulte a Jev con esos estados exige además que la pregunta Q5 esté resuelta.
- **De `sombra` a `sugerencia`:** al menos 200 decisiones del tipo con consenso válido; 0 incidentes de privacidad; informe del tipo con acuerdo con la base y calibración de la confianza.
- **De `sugerencia` a `enrutado` (solo clases B y C, no asesor ni A):** al menos 200 decisiones con juicio humano o resultado medible; en clase C, tasa de «repetir con un modelo superior» no mayor que la de la base más 2 puntos, ahorro neto positivo con tarifas verificadas, error de calibración no mayor que 0,15 y p95 de latencia no mayor que 1 segundo (el tiempo máximo operativo de VJT-031 es otra cosa: el límite a partir del cual se abandona la consulta).
- **Degradación:** automática (VJT-015) o por orden del CTO, en cualquier momento.
- **Realismo:** con el error de calibración de 0,33 medido para la pregunta de modelo, esta promoción es **hoy inalcanzable** para `modelo`; solo se alcanzaría si Jev mejora o si el tipo cambia de pregunta. Nunca se promueve un tipo de clase A.

## 8. Alcance

**Dentro:** la capa común (política base, estado, puerto de decisión, modos, caché, registro), su aplicación al CRM desplegado (`modelo_asistente` inactivo y el módulo CRM-consejero) y los contratos que otras áreas deben cumplir para usarla.

**Fuera:** el router del núcleo y su captura (spec 002, que adopta esta capa cuando el núcleo se despliegue), el cliente de LLM de más de un proveedor, la implementación en el asistente Hermes (spec 005), en marketing (spec 008) y en finanzas (spec 006), la herramienta de desarrollo de la flota, P2, contratos, firma, nube, voz, pagos y todo despliegue.

## 9. Dependencias explícitas con otras specs

| Spec / equipo | Qué necesita esta spec | Qué entrega esta spec |
|---|---|---|
| **002** jev-router-sombra (jer-jev) | Núcleo desplegado y tráfico | El tipo `nivel_turno`; el escritor compartido de archivos |
| **004** crm-cierre-contrato-firma (crm-director) | Confirmar que contratos, firma, bajas y autorizaciones son clase A | VJT-062; OpenAI sigue excluido de los datos de contratos |
| **005** asistente-hermes (`kai-jev`) | Un LLM de más de un proveedor (A1/A6); sus cuatro puntos de decisión; R11 a R14 | La función `decidir` común, la política, las clases, el registro y la promoción por modos |
| **006** catálogo de precios (`kai-jev`) | La herramienta `consultar_catalogo` y el esquema `Cotizacion` | VJT-060 y el tipo `ruta_consulta_financiera` |
| **008** marketing-marca (`kz-marca`) | Su spec, aún sin escribir | VJT-061 y el tipo `riesgo_pieza` |
| **Módulo CRM-consejero** | Q2 y Q5 de ese módulo | Tipo `seguimiento_lead` |
| **Herramienta de la flota** (`kai-jev`) | Leer los registros, aplicar cubos y VJT-026, escribir las respuestas de Jev (VJT-046), informes por tipo, cliente único (Q1) | Registro de decisiones con esquema versionado |
| **Plan maestro** (director) | Tarifas de modelos verificadas (Q2) | Actualizar §4 solo al promover un tipo a `enrutado` |

**Correspondencia con la spec 005:** `modelo` ↔ `modelo`; `habilidad` ↔ `habilidad`; `escalar_humano` ↔ `escalar_humano`; `siguiente_paso_voz` ↔ `siguiente_paso_voz`; el estado de `modelo` de la 005 (tipo de tarea, longitud estimada, si toca datos de clientes) se refina aquí a (tarea, rango de longitud, clase de datos de tres valores); R11 (respaldo y registro) ↔ VJT-002, VJT-030, VJT-040; R12 (DeepSeek solo seudonimizado) ↔ VJT-023 y VJT-024, **con una definición más estricta que se propone** (pregunta Q3); R13 (idempotencia y modo simulado `JERICO_EXTERNAL_COMMS_DRY_RUN`) ↔ VJT-042; R14 (esquemas compartidos `Lead`, `Cotizacion` y precios por herramienta) ↔ VJT-060. **Divergencias que `kai-jev` debe resolver en la 005:** (1) la 005 §3.1 pide `jev-latest` sin condición, y la constitución (principio 5) lo prohíbe: depende de Q8; (2) la 005 deja a cada repositorio con su cliente de Jev, y esta spec propone uno solo (VJT-050, Q1).

## 10. Preguntas abiertas para el CTO

- **Q1 — Un solo cliente de Jev.** Hoy hay tres. Para el Nivel 2 hace falta uno dentro del producto. Opciones: (a) el producto lo posee y la herramienta de la flota lo importa; (b) un paquete compartido que ambos instalen; (c) copiarlo (descartada: duplica). Se propone (a), a confirmar con `kai-jev`.
- **Q2 — Tarifas verificadas** de `gpt-6-luna`, `deepseek-chat`, Gemini y Opus, con fecha. Sin ellas no se afirma ahorro y la promoción de la clase C no procede.
- **Q3 — DeepSeek y datos seudonimizados.** El Plan maestro permite DeepSeek con datos seudonimizados; esta spec propone una definición más estricta (VJT-023): solo contexto construido en origen con campos estructurados, nunca texto libre seudonimizado, porque el seudonimizador declara que no detecta nombres de terceros en texto libre. Mientras no se decida, DeepSeek solo recibe datos de clase `sin_datos_personales`. ¿Se acepta?
- **Q4 — Umbrales** de las secciones 5 y 7.
- **Q5 — Legal.** El estado que recibe Jev no lleva identificadores y usa rangos, pero TypeSafe es un tercero fuera de Colombia. ¿El abogado confirma que ese estado categórico no es dato personal y que no hace falta añadir a TypeSafe como encargado (VJT-055)? Hasta entonces la herramienta de la flota no consulta a Jev con estados de leads.
- **Q6 — Orden de integración.** Se propone: capa común y CRM en `sombra`; después cliente en línea con `sugerencia`; después `enrutado` solo para una tarea de clase C con evidencia; las demás áreas siguen sus propias specs.
- **Q7 — Alerta sin tope.** ¿Se acepta el aviso por volumen anómalo (VJT-044) en lugar de un tope?
- **Q8 — `jev-latest` frente al principio 5 de la constitución (sin `-latest`).** Registrar la versión devuelta no sustituye al pineado previo. Opciones: (a) enmendar la constitución para exceptuar a Jev como servicio de decisión, con ratificación escrita del CTO; (b) pedir una versión fija (por ejemplo la que Jev devuelve) si el servicio la admite (sin verificar). Debe quedar resuelta por escrito **antes de implementar el Nivel 2**; el Nivel 1 no la necesita porque no llama a Jev. Hoy no consta ninguna enmienda ni excepción escrita; lo que existe es la decisión del CTO del 12/10 de usar `jev-latest` en la herramienta de la flota.

## 11. Riesgos

| Riesgo | Mitigación |
|---|---|
| Jev no mejora la tabla base (confianza sin calibrar, poca señal sin texto) | El modo `sombra` lo mide antes de dar control. Un resultado negativo cierra el tipo. |
| Enrutar a un modelo barato filtra datos de clientes | Clase de datos por origen, conjunto permitido, DeepSeek solo con datos sin personales hasta decidir Q3 (VJT-022 a VJT-024). |
| Valores casi identificadores combinados con pocos casos | Rangos obligatorios y mínimo de leads para estados de lead (VJT-020, VJT-026). |
| Dependencia de un tercero en el camino de una petición | Nivel 2 solo tras promoción; tiempo máximo, cortacircuitos y base como respaldo (VJT-030 a VJT-032). |
| Sobreconstrucción para el volumen actual (0 leads, un usuario) | Primero solo el Nivel 1 sin red; el Nivel 2 y el enrutado esperan evidencia. |
| Tres clientes de Jev divergen | VJT-050 y Q1. |
| Una opción de Jev se trata como decisión final | Clases A, B y C, asesor y orden de exigencia; Jev solo elige entre permitidas; la fuente queda en cada registro. |

## 12. Decisión asistida por Jev durante esta redacción (13/10/2026)

Aplicando la regla «Jev decide primero» (Plan maestro §4), se consultó a Jev con un estado breve sin datos personales (tipo de tarea, ausencia de datos personales, sin efecto en producción). Versión de modelo que respondió: `jev-1.13.0`; 709 tokens de entrada.

| Pregunta | Respuesta de Jev | Verificación del director |
|---|---|---|
| Modelo para redactar la spec | Claude Sonnet 5.5 | Coincide con el criterio de `AGENTS.md` (redacción técnica compleja); adoptada. |
| ¿Revisión de seguridad por Opus? | No | Coincide: la spec no toca producción ni datos personales y se audita con el revisor; adoptada. La implementación del cliente en línea sí tocará seguridad y datos; ahí se reevalúa. |
| Forma de integración | Un puerto único de decisión con modos y reglas deterministas como piso | Coincide con el análisis previo y con la spec 005; adoptada. |

> 🕒 **Última modificación:** 13/10/2026 22:41 (Agente Claude Code · Sonnet 5.5)
