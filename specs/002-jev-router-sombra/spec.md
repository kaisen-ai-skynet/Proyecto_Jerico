---
modificado: "13/10/2026 22:38"
---

# Spec 002 — Router de niveles L1/L2/L3 con Jev en modo sombra (P1)

- **Estado:** **BORRADOR — EN ESPERA (13/10/2026).** El núcleo con el router no está desplegado y no hay tráfico; el Plan maestro dirige a Jev primero hacia el CRM desplegado (spec `006-jev-crm-consejero`). Esta spec se retoma cuando el núcleo se despliegue. No se implementa nada hasta que el CTO apruebe.
- **Tipo de cambio:** funcionalidad nueva y acotada sobre el núcleo del agente (observación pasiva; no cambia el comportamiento del router).
- **Fuente:** informe `Proyecto_Jerico_Implementacion_Jev` de la bóveda (caso P1, secciones 8 y 13); decisiones del CTO del 12/10/2026 (primer piloto D1+D2 en la herramienta de la flota; P1 para cuando Jericó esté desplegado; solo categorías y contadores; Jev solo puede pedir más revisión, nunca menos) y mensaje del orquestador del 13/10/2026 que autoriza redactar spec, plan y tareas de P1.
- **Convención de marcas:** `(decisión CTO 12/10)` — decisión ya tomada por el CTO; `(propuesta)` — valor propuesto por el redactor, el CTO decide; `(supuesto)` — dato no verificado, a confirmar.
- **Alcance de esta spec:** solo el lado de Jericó (qué se observa y qué se registra de cada turno). El lado de Jev (consultas, consenso, métricas y bitácora de comparación) pertenece a la herramienta de la flota (`Flota_Jev`, a cargo de `kai-jev`) y aquí se describe únicamente como contrato (sección 6).

## 1. Contexto y problema

El núcleo del agente decide con qué modelo contesta cada turno mediante un router de reglas fijas: respuestas locales para saludos (L0), y para el resto, nivel operativo (L1), código (L2) o alto riesgo (L3), según listas de palabras clave configurables. El nivel decide qué modelo responde y, por tanto, el costo y la calidad.

Debilidades conocidas de la regla actual (verificadas en el código):
- Un prompt sobre dinero o clientes que no contenga una palabra de la lista de alto riesgo cae en el nivel operativo.
- Una palabra de la lista de código en un contexto casual sube el turno al nivel de código.
- Hoy el modelo de alto riesgo (L3) no tiene valor configurado y, si falta, usa el del nivel de código; el beneficio de acertar L3 hoy es de calidad, no de ahorro.

Jev es un modelo de decisión (no redacta texto): recibe datos estructurados y responde preguntas cerradas con probabilidades. La pregunta del piloto es si Jev, viendo **solo categorías y contadores** del turno (decisión CTO 12/10), clasifica el nivel de forma distinta y **mejor** que las reglas.

**Hecho verificado que condiciona el piloto (13/10/2026):** hoy corre en el servidor `kaisen-server` únicamente el servicio del CRM; el núcleo del agente, que contiene el router, **no está desplegado**, y el CRM no ejecuta turnos de modelo de lenguaje. Por lo tanto, no existe aún tráfico real del router. La spec lo trata como dependencia (sección 8, pregunta Q1).

## 2. Hipótesis y riesgo central

- **H1 (hipótesis a probar):** con un estado compacto que incluya banderas de léxico ampliado calculadas localmente, Jev detecta más turnos de alto riesgo que las reglas actuales sin aumentar de forma relevante los falsos positivos.
- **Riesgo central, declarado desde ya:** como Jev no recibe el texto (decisión CTO 12/10), lo único que ve son los mismos indicios que ya usan las reglas más unas banderas ampliadas. Es posible que **no pueda superar a las reglas**. Un resultado negativo es un resultado válido del piloto: cierra P1 con evidencia y deja como única vía enviar texto seudonimizado, lo cual depende de resolver la seudonimización y la Ley 1581 (P2, en espera).

## 3. Alcance

**Dentro:**
- Observación pasiva de cada turno no local: se calcula un estado compacto y se guarda un registro local junto con lo que decidieron las reglas y lo que ocurrió.
- Activación por configuración, apagada por defecto.
- Un mecanismo para que una persona revise, a ciegas, una muestra de turnos buscando el texto en el almacén local.
- Contrato de datos con la herramienta de la flota.

**Fuera (explícito):**
- Que Jev decida o modifique el nivel o el modelo de un turno (el nivel sigue siendo siempre el de las reglas).
- Cualquier llamada a Jev desde el núcleo, y cualquier credencial de TypeSafe en el núcleo.
- Enviar a Jev texto del prompt, fragmentos, nombres, identificadores de persona, correos, teléfonos, rutas, diffs, registros o datos de clientes.
- P2 (triaje de respuestas del CRM) y cualquier cambio al CRM.
- Despliegue del núcleo en ningún servidor.
- Modificar el repositorio de la herramienta de la flota (lo hace `kai-jev`).

## 4. Actores

| Actor | Papel |
|---|---|
| CTO (Santiago Gonzalez) | Aprueba la spec; decide los umbrales de éxito y el cierre del piloto; puede ser el revisor ciego. |
| Núcleo del agente | Ejecuta turnos y, con la captura activada, escribe el registro local de cada turno. |
| Herramienta de la flota (`Flota_Jev`, `kai-jev`) | Lee los registros, consulta a Jev, calcula métricas y produce el informe. |
| Revisor ciego | Persona (CTO u otra designada por él) que juzga el nivel correcto de una muestra de turnos sin ver la opinión de Jev ni de las reglas. |

## 5. Requisitos (EARS)

Prefijo `VRJ-`. Todos corresponden a la única fase de esta spec. Definiciones usadas:
- **Turno:** cada invocación del bucle del agente para un mensaje del usuario. Los reintentos internos hacia el proveedor del modelo dentro de un mismo turno no son turnos nuevos; un reintento del cliente con el mismo texto sí es un turno nuevo.
- **Turno no local:** turno cuyo nivel, según el router de reglas, es 1, 2 o 3. El nivel 0 es el que el router resuelve con una respuesta local.
- **Resultado del turno:** uno de `ok` (respuesta normal), `iteraciones_agotadas` (respuesta de cierre por tope de iteraciones), `error` (excepción distinta de cancelación, incluido historial que sigue superando la ventana tras compactar) y `cancelado` (interrupción del turno).

### 5.1 Captura pasiva

- **VRJ-001** EL SISTEMA no incluye en el paquete de captura ninguna importación de clientes de red (HTTP, sockets, URL) ni de la herramienta de la flota, y ningún turno realiza consulta alguna a Jev o a TypeSafe.
- **VRJ-002** MIENTRAS la captura esté desactivada (valor por defecto), EL SISTEMA no escribe ningún registro de observación y el turno se comporta exactamente igual que sin esta funcionalidad.
- **VRJ-003** CUANDO la captura está activada y un turno no local termina con cualquier resultado, EL SISTEMA escribe un único registro local de ese turno con: la marca de tiempo, el estado compacto (sección 5.2), el nivel y el modelo decididos por las reglas, los tokens de entrada y salida acumulados del turno, el número de rondas de herramientas, la duración del turno en milisegundos, el resultado y la referencia local (VRJ-006).
- **VRJ-004** CUANDO el router de reglas resuelve un turno con nivel 0, EL SISTEMA no escribe registro de observación.
- **VRJ-005** EL SISTEMA decide el nivel y el modelo de cada turno exclusivamente con las reglas actuales, de modo que el contenido, la presencia, la ausencia o el fallo del registro de observación nunca alteren el nivel, el modelo, la respuesta, el resultado ni la excepción que el turno produciría sin la captura (decisión CTO 12/10: la IA propone, el código decide).
- **VRJ-006** CUANDO el mensaje del usuario de un turno llegó a guardarse en el almacén local, EL SISTEMA incluye en el registro el identificador numérico de esa fila; SI el mensaje no llegó a guardarse (por ejemplo, error o cancelación antes de la primera persistencia), ENTONCES EL SISTEMA deja la referencia vacía. La referencia nunca forma parte de lo que se entrega a Jev.
- **VRJ-007** SI la escritura del registro de observación falla por cualquier excepción ordinaria (disco, permisos, formato), ENTONCES EL SISTEMA completa el turno con normalidad, anota en el registro de la aplicación un aviso sin texto del prompt que incluye el contador acumulado de fallos de escritura, y no interfiere con la cancelación del turno.
- **VRJ-008** EL SISTEMA realiza la escritura del registro como una única escritura síncrona de una línea de hasta 4 KB, sin red y sin bloqueo de archivo, y su mediana sobre 100 escrituras reales en un directorio temporal es inferior a 5 ms.
- **VRJ-009** SI el estado compacto de un turno no cumple la validación de 5.2, ENTONCES EL SISTEMA no escribe el registro de ese turno, anota en el registro de la aplicación un aviso sin texto del prompt con el contador acumulado de estados inválidos y completa el turno con normalidad.

### 5.2 Estado compacto (sin texto libre)

- **VRJ-010** EL SISTEMA construye el estado compacto de un turno únicamente con valores enumerados, booleanos y enteros acotados, calculados localmente a partir del prompt y del contexto del turno.
- **VRJ-011** EL SISTEMA incluye en el estado compacto exactamente los siguientes campos (lista cerrada) y ningún otro:
  - versión del esquema (entero);
  - nivel que dieron las reglas (1, 2 o 3);
  - banderas de coincidencia con la lista de código, con la lista de alto riesgo y con las frases exceptuadas de código;
  - tamaño del prompt en caracteres y en palabras (palabra = secuencia de caracteres no blancos separada por espacios);
  - número de mensajes del historial de la sesión antes del turno (cuenta todos los roles) y tokens estimados de ese historial con el estimador existente, antes de cualquier compactación;
  - nivel de presión de tokens, con los valores `low`, `elevated` u `overflow`;
  - superficie de la petición, con los valores `rest`, `cli`, `telegram` o `siri`;
  - postura de herramientas activa, con los valores `coding`, `ops`, `personal` o `default`;
  - banderas de léxico ampliado, configurables y calculadas localmente: menciona dinero, menciona cliente o lead, menciona contrato o tema legal;
  - banderas estructurales: contiene bloque de código, contiene cifras, es pregunta.
- **VRJ-012** EL SISTEMA aplica a cada entero del estado compacto un tope máximo fijo (propuesta: 10 000 caracteres, 2 000 palabras, 200 mensajes, 200 000 tokens) y calcula las banderas de léxico y estructurales sobre, como máximo, los primeros 10 000 caracteres del prompt, de modo que el costo del cálculo está acotado.
- **VRJ-013** EL SISTEMA no incluye en el estado compacto ningún valor que no pertenezca a la lista cerrada de VRJ-011; en particular, ningún texto del prompt, subcadena, nombre, correo, teléfono, documento, identificador de sesión o de usuario, ruta o secreto.
- **VRJ-014** EL SISTEMA permite cambiar las listas de léxico ampliado por configuración sin tocar el código, y registra en cada registro una huella (hash) de la versión de las listas usada, no las listas; la huella no es un dato personal porque solo depende de la configuración.

### 5.3 Contrato con la herramienta de la flota

- **VRJ-020** EL SISTEMA produce los registros en líneas independientes, con una versión de esquema en cada línea, en archivos con rotación diaria, de modo que la herramienta de la flota pueda leerlos sin depender de código del núcleo e ignorar una última línea incompleta.
- **VRJ-021** EL SISTEMA no incluye la herramienta de la flota entre las dependencias del proyecto ni la importa en ningún módulo, de modo que el núcleo arranca, pasa sus pruebas y construye su imagen sin ella.
- **VRJ-022** EL SISTEMA documenta en esta spec el estado compacto y las preguntas que se formularán a Jev como contrato para `kai-jev` (sección 6), sin duplicar en el núcleo el cliente de Jev, el consenso ni las métricas.
- **VRJ-023** EL SISTEMA no contiene en el código del núcleo ni la variable `TYPESAFE_API_KEY`, ni la dirección del servicio de TypeSafe, ni el identificador del modelo de Jev.
- **VRJ-024** CUANDO varios turnos terminan de forma simultánea, EL SISTEMA escribe cada registro como una línea completa sin intercalarse con otra.

### 5.4 Revisión ciega

- **VRJ-030** CUANDO una persona solicita la revisión de una muestra, EL SISTEMA le presenta por cada turno de la muestra el texto del mensaje del usuario recuperado del almacén local y le pide el nivel que considera correcto (operativo, código o alto riesgo), sin mostrar el nivel de las reglas ni la opinión de Jev.
- **VRJ-031** CUANDO la persona registra su juicio sobre un turno, EL SISTEMA guarda ese juicio en un registro separado, con la referencia local del turno, el juicio, el rol declarado del revisor y la fecha-hora, sin copiar el texto del prompt.
- **VRJ-032** SI la referencia del turno está vacía o el texto ya no existe en el almacén local, ENTONCES EL SISTEMA marca ese turno como «no revisable» y no lo cuenta en las métricas.
- **VRJ-033** EL SISTEMA permite la revisión únicamente desde la línea de comandos local con acceso al almacén del núcleo y no la expone por la API.
- **VRJ-034** EL SISTEMA exige para la revisión que el revisor sea una persona; SI se propone que la revise un modelo de lenguaje, ENTONCES se requiere antes la aprobación explícita del CTO sobre privacidad (pregunta Q2).
- **VRJ-035** CUANDO se arma una muestra, EL SISTEMA admite dos formas: una lista de referencias entregada por la herramienta de la flota (desacuerdos) o una muestra aleatoria con tamaño y semilla indicados, de modo que la misma semilla reproduce la misma muestra.

### 5.5 Retención, privacidad y calidad

- **VRJ-040** EL SISTEMA elimina los archivos de registros de observación y de juicios con fecha anterior al número de días de retención configurado (propuesta: 90), al crear el registrador y una vez por día de reloj mientras la captura esté activa.
- **VRJ-041** EL SISTEMA no incluye en el registro de observación ningún dato personal directo; la referencia local de VRJ-006 es el único vínculo indirecto y solo es resoluble dentro del almacén local.
- **VRJ-042** SI en una prueba el estado compacto contiene un campo de tipo cadena fuera de los valores enumerados de VRJ-011, ENTONCES la prueba de contrato falla (guarda contra regresiones de privacidad).
- **VRJ-050** EL SISTEMA mantiene la verificación completa del proyecto en verde y la cobertura total por encima del 89 % con el código añadido por esta spec.

## 6. Contrato con la herramienta de la flota (para `kai-jev`)

Esta sección no es una tarea para el núcleo y no es verificable con pruebas de Jericó. Es lo que Jericó necesita que la herramienta de la flota ofrezca, sin que se duplique nada en Jericó:

1. **Lectura** de los registros de observación (VRJ-020), ignorando una última línea incompleta, y **eliminación** de la referencia local antes de cualquier consulta (VRJ-006).
2. **Esquema de estado** propio del router, con los campos de VRJ-011. El esquema vigente de la herramienta (14 campos) es de tareas de desarrollo y no coincide.
3. **Preguntas a Jev** (propuesta):
   - `nivel` — de tipo `choice`: «operativo» (consultas del día a día), «codigo» (programación, arquitectura, bases de datos, depuración) y «alto_riesgo» (finanzas, contratos, temas legales, decisiones con consecuencias económicas o jurídicas).
   - `riesgo` — de tipo `score`: «bajo», «moderado», «alto», «extremo».
4. **Consenso** de tres respuestas por turno, como en la herramienta actual; los turnos sin consenso se cuentan aparte y no entran en las métricas de acierto.
5. **Informe** con: acuerdo reglas-Jev, matriz de confusión, falsos negativos y positivos de alto riesgo frente al juicio del revisor, Brier y calibración de la confianza, latencia p95 y costo.
6. **Archivo de referencias** de la muestra de desacuerdos para la revisión ciega (VRJ-035).
7. **Modelo `jev-latest`** y sin tope diario (decisión CTO 12/10). La excepción a «modelos pineados» (constitución, principio 5) corresponde a la herramienta de la flota y debe quedar registrada allí como decisión del CTO del 12/10/2026. Como el núcleo no llama a Jev ni contiene su identificador (VRJ-001, VRJ-023), esta spec no enmienda la constitución de Jericó.

## 7. Criterios de decisión al cierre del piloto

Son **criterios de negocio** para que el CTO decida, no requisitos verificables con pruebas del núcleo. Todos los umbrales son una **propuesta**; el CTO decide.

- **Métrica principal:** recall de alto riesgo = (turnos que el revisor marca «alto riesgo» y que el sistema evaluado también marca «alto riesgo») dividido entre (turnos que el revisor marca «alto riesgo»). Se calcula por separado para las reglas y para Jev, sobre los turnos juzgados y con consenso válido.
- **Muestra mínima:** 200 turnos no locales con consenso válido, 100 turnos juzgados a ciegas y al menos **20 turnos que el revisor marque «alto riesgo»**; o 4 semanas con tráfico real —lo que ocurra último—, con un máximo de 8 semanas; pasado ese máximo se cierra con lo disponible y se declara la muestra insuficiente. Si el revisor marca menos de 20 turnos de alto riesgo, el recall no se considera concluyente.
- **Éxito (continuar a una spec posterior de control limitado):**
  1. El recall de alto riesgo de Jev es al menos 80 % y supera al de las reglas por 15 puntos o más.
  2. Entre las alertas de alto riesgo de Jev, no más de un 20 % son falsos positivos según el revisor.
  3. El Brier de la probabilidad de alto riesgo es menor que el de predecir siempre la tasa base.
  4. El costo medido en el periodo no supera USD 5 al mes.
- **Cierre negativo:** si no se cumple el punto 1, P1 se cierra con el informe y la conclusión «el estado sin texto no basta»; la siguiente vía (texto seudonimizado) queda condicionada a P2.
- **Regla permanente para cualquier spec futura de control:** Jev solo podrá subir el nivel de un turno, nunca bajar un nivel que las reglas hayan fijado (decisión CTO 12/10).

## 8. Preguntas abiertas para el CTO

- **Q1 — Tráfico.** El núcleo con el router no está desplegado hoy (solo el CRM). Opciones: (a) construir y probar ahora la captura de forma hermética y medir cuando el núcleo se despliegue; (b) desplegar el núcleo en `kaisen-server` antes de medir. Esta spec propone (a); la medición queda bloqueada hasta que existan turnos reales.
- **Q2 — Revisor ciego.** ¿Quién revisa la muestra? Debe ser una persona (VRJ-034); si el CTO quisiera delegarla en un modelo, el texto de los prompts pasaría a otro proveedor y exige antes su aprobación de privacidad.
- **Q3 — Retención.** ¿Se acepta 90 días (propuesta)?
- **Q4 — Léxico ampliado.** ¿El CTO aporta o aprueba las listas iniciales (dinero, cliente/lead, contrato/legal)? Hasta entonces se usa una lista inicial mínima de la que se deja constancia.
- **Q5 — Umbrales de la sección 7.** ¿Se aceptan o se ajustan?

## 9. Riesgos

| Riesgo | Mitigación |
|---|---|
| Sin texto, Jev no mejora a las reglas (riesgo central) | Se declara H1 como hipótesis; el cierre negativo es un resultado válido (sección 7). |
| El registro filtra datos personales | Validación estricta del estado (VRJ-009, VRJ-013), prueba de contrato (VRJ-042) y retención (VRJ-040). |
| El registro afecta la latencia o la estabilidad del turno | Captura apagada por defecto, escritura de una línea y tolerancia a fallos (VRJ-002, VRJ-007, VRJ-008). |
| Acoplamiento con la herramienta de la flota rompe el despliegue | El núcleo no la importa (VRJ-021); el contacto es solo el formato de archivo (VRJ-020). |
| Muestra insuficiente por bajo volumen | Máximo de 8 semanas y cierre declarado (sección 7). |
| Que alguien trate la opinión de Jev como decisión | VRJ-005 y la regla permanente de la sección 7. |

## 10. Trazabilidad con el informe

| Requisito | Decisión o hallazgo de origen |
|---|---|
| VRJ-001, VRJ-005 | La IA propone, el código decide; siempre con respaldo (lecciones de Trading 1 y 6). |
| VRJ-010 a VRJ-014 | State compacto sin texto libre (lección 5; decisión CTO 12/10). |
| VRJ-006, VRJ-040, VRJ-041, VRJ-034 | Ley 1581: sin datos personales hacia el tercero; registro de cada decisión para auditar (lecciones 7 y 8). |
| Sección 7 | Modo sombra, medir contra la línea base y calibrar la confianza (lecciones 2 y 3). |

> 🕒 **Última modificación:** 13/10/2026 22:38 (Agente Claude Code · Sonnet 5.5)
