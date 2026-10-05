# Opciones técnicas — Spec 001 «CRM operativo asistido por IA para ventas»

- **Estado:** Borrador para el Gate 1 (sin aprobar), acompaña a «spec.md»; revisado tras la auditoría QA de la fase 3 y actualizado con las rondas 1 y 2 de respuestas del CTO del 04/10/2026 (ronda 1: correo interno en F1 y sin ruta pública, P-01 y P-10; ronda 2: misma instancia y SQLite en producción como excepción temporal a D1, P-14; buzón por configuración, P-27; reintentos, P-02; autorización con humano en el bucle, N-04). Aquí sí se nombran tecnologías y módulos de Jericó.
- **Fecha:** 04/10/2026. Sin navegación web en esta redacción: **toda cifra de precio o cuota de terceros está marcada [VERIFICAR PRECIO VIGENTE]**, con la fecha aproximada de la fuente (conocimiento del planificador hasta mediados de 2026). Excepción: el recorte de OCI A1 (hecho 0.1), confirmado en la nota de Obsidian citada.
- **Referencias:** `P-NN` (preguntas), `PR-NN` (propuestas a ratificar) y `VCRM-NNN` remiten a la numeración vigente de «spec.md». «(nuevo)» marca piezas que no existen hoy en el repositorio.
- **Leyenda de criterios:** costo mensual estimado · velocidad de despliegue · mantenimiento · encaje con Jericó · encaje con OCI A1 · riesgos.

---

## 0. Hechos del repositorio y del entorno que condicionan todas las decisiones

1. **OCI Always Free recortado (confirmado).** La nota de Obsidian «Decision_Arquitectura_Jerico_Oracle_2026-09-30» (bóveda Kaisen, `02_Proyectos/Infraestructura/`) documenta que Oracle redujo Ampere A1 de **4 OCPU / 24 GB a 2 OCPU / 12 GB**, con fuente en la documentación oficial *Always Free Resources* y el comunicado del foro de clientes de Oracle del 21/07/2026. El encargo de esta línea no da cifras; quien asume 4/24 es **D2** (y el runbook), que la propia nota pide corregir antes de aprovisionar. **Este análisis dimensiona con 2/12** y avisa dónde cambia la recomendación. La misma nota propone «SQLite canónico; PostgreSQL cuando un caso de negocio lo exija», propuesta aún no ratificada: **D1 sigue vigente** (constitución, punto 4), con la excepción temporal que el CTO autorizó para el CRM (P-14, ronda 2; decisión 3).
2. **Ingreso de red cerrado.** El servicio escucha en `127.0.0.1:8000` y el acceso es por Tailscale (MEMORY.md, D2). Cualquier opción que requiera **webhook público HTTPS** (WhatsApp Cloud API, Telegram en modo webhook, formulario web de consentimiento, enlace de baja) obligaría a abrir una ruta pública mínima (Cloudflare Tunnel o Tailscale Funnel). **El CTO no autoriza ninguna ruta pública (decisión P-10, 04/10/2026):** solo caben opciones con conexiones salientes. Detalle en la decisión 6.3.
3. **`gateway/platforms/telegram.py`** es un adaptador delgado: valida `settings.telegram_ids`, transcribe voz y delega en `OmniGateway.handle_inbound_turn`, que exige Bearer y ejecuta **un turno libre del `AgentTurnLoop`**. No implementa la Bot API (polling/webhook), `CallbackQuery`, teclados inline ni envío saliente.
4. **`cron/scheduler.py`** (`CronScheduler`): en memoria, 5 campos, evalúa en UTC, granularidad de 1 minuto, reintentos y timeout; sin persistencia, sin jobs de una sola ejecución y con `job_id` único.
5. **`tools/approval.py`** solo tiene `ToolExecutionContext.confirmed`; el protocolo asíncrono de D5 (botones, expiración 10 min, CLI de respaldo) **no existe aún** y lo construye otra línea.
6. **`state/`**: `StateEngine` es SQLite WAL con escritor serializado y `initialize_schema` del núcleo (`SCHEMA_VERSION = 3`, `PRAGMA user_version`). D1 prevé PostgreSQL 16 en producción vía `DATABASE_URL`, aún no implementado. La nota de Oracle propone «SQLite canónico para el estado del agente; PostgreSQL cuando un caso de negocio lo exija»: **el CRM es el primer caso de negocio con valor probatorio** (evidencias de autorización).
7. **`voice/stt.py`**: faster-whisper, modelo por defecto `small`, `int8`, import perezoso (extra `voice`).
8. **`llm_client.py` + `config.py`**: endpoints y modelos por nivel (`llm_model_l1 = glm-5.3-flash`, `llm_model_l2 = deepseek-flash`), validador que rechaza alias flotantes, overrides por nivel (`JERICO_LLM_BASE_URL_L{n}`).
9. **Riesgo de convivencia:** gateway, approval, state y config los modifican otras líneas. Principio rector de este análisis: **el CRM vive en su propio paquete (nuevo, p. ej. `src/jerico/crm/`) y consume los módulos del núcleo como librería, sin editarlos**. No es posible, en cambio, evitar tocar archivos compartidos de empaquetado, despliegue y verificación: se listan con su propuesta de minimización en la sección 8 «Puntos de coordinación con el núcleo».

---

## Decisión 1 — Canal del comercial

### Alternativas

- **1A. Bot de Telegram propio del CRM** (token separado, long polling, cliente HTTP delgado sobre la Bot API con `httpx`), proceso independiente que reutiliza STT, persistencia y LLM de Jericó como librerías.
- **1B. Reutilizar el adaptador/gateway de Telegram de Jericó** (mismo bot y token; los mensajes del comercial entran como turnos del agente y el CRM se expone como tools con prefijo `crm_`).
- **1C. WhatsApp Cloud API** como interfaz del comercial.
- **1D. WebApp propia** (Kanban/lista, REST + WebSocket), o su variante **Telegram Mini App**.

### Comparativa

| Criterio | 1A Bot Telegram propio | 1B Gateway de Jericó | 1C WhatsApp Cloud API | 1D WebApp / Mini App |
| :--- | :--- | :--- | :--- | :--- |
| Costo mensual | USD 0 (Bot API gratuita) | USD 0 | Mensajes iniciados por la empresa fuera de la ventana de 24 h se cobran como plantilla (avisos del gate y alertas). [VERIFICAR PRECIO VIGENTE] | USD 0 en OCI; dominio y TLS (≈ USD 10–15/año) [VERIFICAR PRECIO VIGENTE] |
| Velocidad de despliegue | Días: token de @BotFather, long polling, teclados inline nativos | Lenta: requiere que el núcleo termine Bot API, `CallbackQuery` y D5 (otra línea) | Semanas: Business Manager verificado, número dedicado, plantillas aprobadas, webhook público | Semanas: autenticación, sesiones, UI, despliegue público |
| Mantenimiento | Bajo: un cliente HTTP de ~6 métodos (`getUpdates`, `sendMessage`, `editMessageReplyMarkup`, `answerCallbackQuery`, `getFile`, `sendDocument`) | Medio-alto: acoplado a cambios del núcleo | Medio: plantillas, calidad del número, políticas de Meta | Alto: frontend + backend + seguridad |
| Encaje con Jericó | Alto: reutiliza `STT`, lista blanca de `config`, `CronScheduler`, `AsyncLLMClient`, auditoría; no edita `gateway/` | Conceptual alto, pero **mal encaje funcional**: cada mensaje dispara un turno LLM (costo, no determinismo) para operaciones que son una máquina de estados con botones | Bajo: no hay adaptador de WhatsApp en Jericó | Medio: `api.py` ya es FastAPI, pero hay que exponerlo |
| Encaje con OCI A1 (2/12) | Excelente: ~100–200 MB RAM; **long polling no abre puertos** (respeta D2) | Igual que 1A | Requiere webhook HTTPS público (túnel) | Requiere ingreso público y más RAM |
| Riesgos | Telegram procesa en su nube los datos del cliente que escribe el comercial (transmisión internacional, ver decisión 6); el comercial y el abogado deben haber hecho `/start` para recibir mensajes; en grupos, el *privacy mode* oculta mensajes que no son comandos | Conflicto de `getUpdates`: **un token solo admite un consumidor**; si el bot del CTO y el del CRM comparten token, hay que construir un despachador en el núcleo | Costo variable; bloqueo del número por calidad; dependencia de aprobación de Meta | Alcance de F4; sobreingeniería para 1–3 usuarios |

### Recomendación

**1A: bot de Telegram propio del CRM, con token separado, en long polling, como proceso independiente** (otro servicio de `docker-compose` con la misma imagen y otro entrypoint), reutilizando módulos de Jericó como librería:

- Lista blanca por rol (comercial, CTO, abogado) en configuración propia del CRM, con el mismo patrón que `Settings.telegram_ids`.
- Cliente Bot API delgado con `httpx` (ya es dependencia transitiva de `openai`; en tests, `httpx.MockTransport`). Se descartan `python-telegram-bot` y `aiogram` por peso y por la regla de cintura estrecha; son la alternativa si el cliente propio crece más de lo previsto.
- Chats **individuales** por rol en F1 (evita el *privacy mode* de grupos); el grupo privado que propone el CTO es viable si se desactiva el *privacy mode* o se hace administrador al bot; por delegación del CTO, el gate de F2 usa chat individual (P-16).
- UX de los botones alineada con D5 (identidad verificada, expiración), pero con **persistencia propia del gate de negocio**: el gate del CRM (horas o días de espera, aprobadores distintos del CTO) no es el gate de acciones de alto riesgo de D5 (solo el CTO, 10 min). Cuando D5 exista, se evalúa converger. Así lo recoge la spec en §1.6 («No se reutiliza»).
- **Idempotencia de entrada (VCRM-079):** persistir el último `update_id` confirmado (el `offset` de `getUpdates`) y registrar los `update_id` procesados en la misma transacción que su efecto; las pulsaciones se responden con `answerCallbackQuery` una sola vez. Tras un reinicio, Telegram reentrega lo no confirmado y el registro evita aplicarlo dos veces.
- **«Entregado» (spec 4.5):** respuesta `ok: true` con `message_id` de `sendMessage`/`sendDocument`. Si la llamada expira sin respuesta, el intento cuenta como fallido y se reintenta según el calendario de P-02 (spec, VCRM-127), y puede haber duplicado; es el riesgo aceptado en la spec. Para correo (decisión 2, desde F1 para notificaciones internas), «entregado» es la aceptación por el servidor SMTP o la API del proveedor (identificador de mensaje), no la llegada al buzón.
- **Límites de Telegram que condicionan la UX [VERIFICAR]:** 4.096 caracteres por mensaje (de ahí la paginación de VCRM-090, PR-08, y el troceo de fichas largas con muchas notas); 64 bytes de `callback_data` por botón (los botones llevan un identificador corto, no datos); descarga por bots hasta 20 MB, que coincide con el límite de adjuntos fijado por el CTO (P-12, ronda 2) y subida hasta 50 MB (la exportación de VCRM-074 debe trocearse si lo supera).
- **Punto de extensión futuro (F4, coordinado con el núcleo):** registrar tools de solo lectura `crm_*` (nuevas) en `ToolRegistry` para que el CTO consulte el CRM desde el bot principal de Jericó. Requiere añadir el prefijo a `tools/toolsets.py`, por eso se difiere.
- **1D** se evalúa en F4 (como pide el CTO); si se hace, **Telegram Mini App** reutiliza la identidad de Telegram y evita construir autenticación.

**Trade-offs:** se renuncia a la conversación libre con el agente en F1 a cambio de flujos deterministas, baratos y testeables; se suma un segundo bot que administrar.

---

## Decisión 2 — Correo: notificaciones internas (F1) y canal hacia el cliente final (F2)

### 2.0 Correo interno desde F1 (decisión P-01)

El CTO decidió que el abogado (Juan José) recibe la alerta de aceptación por Telegram y la ficha completa por correo, y que el respaldo cuando Telegram falla es el correo al CTO y al comercial (spec, VCRM-047, 050, 104 a 107 y 127 a 130; VCRM-108, retirado en la ronda 2). Consecuencias:

- **El puerto `EmailSender` (nuevo) se adelanta a F1**, solo para notificaciones internas (CTO, comerciales y abogado). El correo al cliente final sigue en F2 (2A, abajo) y reutiliza el mismo puerto con el mismo u otro adaptador.
- **Adaptador F1:** volumen de unos pocos correos al día; cualquier cuota gratuita alcanza. Opciones: (a) SMTP autenticado (STARTTLS, puerto 587) del buzón remitente que defina el CTO, con `smtplib` de la librería estándar, sin dependencias nuevas; (b) API transaccional (Resend, SES) con `httpx`. Recomendación: **(a)** si el buzón remitente es del dominio de Kaisen o de Workspace, porque no añade proveedor ni encargado; **(b)** si se prefiere separar el remitente del buzón de una persona. **Decisión del CTO (P-27, ronda 2):** el buzón remitente y sus credenciales se configuran después, como parámetros en `.env` (`JERICO_CRM_*`) sin valor por defecto en el código; la elección entre (a) y (b) se hace al configurar (P-22, Workspace). Sin buzón configurado, cada correo queda «fallido» sin reintentos (spec, VCRM-140). [VERIFICAR] que OCI no bloquee el puerto 587 saliente (OCI restringe el 25).
- **Outbox común:** las notificaciones por correo usan el mismo *outbox* persistente que las de Telegram (decisión 3), con estado por canal y destinatario; así el fallo de un canal no bloquea el otro (VCRM-047). **Calendario fijado por el CTO (P-02, ronda 2):** primer intento antes de 1 minuto; 3 reintentos (de inmediato, al minuto y a los 5 minutos del primer fallo; spec, VCRM-127, I-02/I-03); el correo de respaldo al CTO y al comercial sale solo tras agotarlos, nunca en paralelo (VCRM-050, 128); si el respaldo falla, aviso por Telegram y correo (VCRM-129); tras eso no hay más reintentos y queda la alerta persistente (VCRM-130, 087). El reintento indefinido anterior (VCRM-108) queda retirado. En el *outbox* basta un campo `next_attempt_at` por entrega, evaluado por el mismo barrido de la decisión 3 (latencia máxima de 1 minuto, compatible con el plazo de P-02 si el primer intento se hace en línea, no en el barrido).
- **Configuración:** dirección de correo por usuario autorizado junto a su identidad de Telegram y su rol (`JERICO_CRM_*`); un destinatario sin dirección produce una notificación «fallida» sin reintentos (VCRM-106).
- **Datos personales en el correo interno:** el correo al abogado lleva solo los 7 campos del handoff (incluida cédula o NIT); TLS obligatorio hacia el servidor de correo y proveedor tratado como encargado (spec, L-8; J-09, J-10, aceptados por delegación).
- **Sin lectura de buzón en F1:** la lectura de respuestas (IMAP o Gmail API) llega en F2 con el canal al cliente.

### 2.1 Canal hacia el cliente final (F2)

### Alternativas

- **2A. Correo transaccional por API** (proveedor externo) detrás de un puerto propio `EmailSender` (nuevo).
- **2B. Correo desde el buzón del comercial vía Gmail API** (solo si Kaisen tiene Google Workspace, P-22).
- **2C. WhatsApp Cloud API** (plantillas aprobadas por Meta).
- **2D. Envío manual por el comercial:** el sistema prepara el texto y el enlace y el comercial lo envía por su cuenta desde su WhatsApp/correo.

### Proveedores de correo (referencia, cifras de 2024–2025) [VERIFICAR PRECIO VIGENTE]

| Proveedor | Cuota gratuita aprox. | Precio de pago aprox. | Notas |
| :--- | :--- | :--- | :--- |
| Amazon SES | 3.000 mensajes/mes los primeros 12 meses (esquema desde 2023) | ≈ USD 0,10 por 1.000 correos | Requiere salir del *sandbox* (aprobación de AWS, que pregunta por el uso comercial). Lo más barato a escala. |
| Brevo | ≈ 300 correos/día | Planes desde ≈ USD 9–25/mes | Empresa de la UE (RGPD). El plan gratuito puede incluir marca de Brevo en campañas. |
| Resend | ≈ 3.000/mes con tope ≈ 100/día | ≈ USD 20/mes por 50.000 | API mínima y sencilla; empresa de EE. UU. |
| Postmark | ≈ 100/mes (prueba) | ≈ USD 15/mes por 10.000 | Alta entregabilidad transaccional; separa *streams* de *broadcast*. |
| OCI Email Delivery | Cuota incluida en Always Free (orden de miles/mes; cifra exacta por verificar) | ≈ USD 0,085 por 1.000 | Mismo proveedor que el hosting; región Bogotá posible; límites de envío iniciales bajos en cuentas nuevas. |
| Gmail API (Workspace) | Incluido en la licencia; ≈ 2.000 correos/día por usuario | Licencia Workspace existente | Respuestas llegan al buzón del comercial; parece un correo 1:1. |

Todos exigen SPF, DKIM y DMARC en el dominio de Kaisen.

### WhatsApp Cloud API (referencia, cifras de 2025) [VERIFICAR PRECIO VIGENTE]

- Desde el **1 de julio de 2025** Meta cobra **por mensaje de plantilla entregado** (ya no por conversación de 24 h). Categorías: *marketing*, *utility* y *authentication*.
- Mensajes de servicio (respuestas dentro de la **ventana de 24 h** abierta por el cliente) gratuitos; plantillas *utility* dentro de esa ventana, gratuitas.
- Tarifa orientativa para Colombia: *marketing* ≈ USD 0,0125 por mensaje; *utility* y *authentication* ≈ USD 0,001 o menos. [VERIFICAR PRECIO VIGENTE]
- Los seguimientos de nutrición son **marketing**: requieren plantilla aprobada, **opt-in explícito del cliente para WhatsApp**, y Meta aplica topes de mensajes de marketing por usuario.
- Requiere Business Manager verificado, número dedicado (o la función de coexistencia con la app WhatsApp Business, lanzada en 2025 [VERIFICAR]) y **webhook HTTPS público** para estados de entrega y respuestas de baja.

### Comparativa

| Criterio | 2A Correo por API | 2B Gmail API | 2C WhatsApp Cloud API | 2D Envío manual |
| :--- | :--- | :--- | :--- | :--- |
| Costo mensual | USD 0 con volumen bajo (cuotas gratuitas) | USD 0 si ya hay Workspace | ≈ USD 0,0125 × mensajes de marketing (100 seguimientos/mes ≈ USD 1,25) [VERIFICAR PRECIO VIGENTE] + verificación | USD 0 |
| Velocidad de despliegue | 1–2 días (DNS + API key) | 2–4 días (proyecto GCP, OAuth o delegación, revisión de *scopes*) | 2–4 semanas (verificación, plantillas, webhook público) | Inmediata |
| Mantenimiento | Bajo | Medio (tokens OAuth, *scopes* restringidos) | Medio-alto (plantillas, calidad, políticas) | Nulo técnico; alto humano |
| Encaje con Jericó | Alto: puerto `EmailSender` (nuevo) + adaptador, tests con transporte simulado | Alto si F3 ya usa Google | Bajo hoy; sin adaptador | Alto, pero el sistema no registra el envío ni aplica franja, tope y supresión |
| Encaje con OCI A1 | Excelente (solo salida HTTPS) | Excelente | Requiere ingreso público (túnel) | Excelente |
| Cumplimiento | Autorización por respuesta al correo confirmada por el comercial y baja por respuesta al correo (decisiones P-10 y N-04); fácil de probar | Igual; trazabilidad en el buzón | Opt-in específico de WhatsApp + Ley 2300; baja por palabra clave | Sin registro del envío en el sistema |
| Riesgos | Entregabilidad si el dominio no está calentado; filtro de spam | Revisión de seguridad de Google para *scopes* sensibles si la app es externa | Costo variable, bloqueo del número, dependencia de Meta | Envíos no registrados; incumple OBJ-2 y OBJ-5 |

### Recomendación

**2A en F2: correo transaccional por API detrás del puerto propio `EmailSender` (nuevo; ya existente desde F1 para notificaciones internas, 2.0), con un único adaptador para el cliente final.** Todo correo al cliente final pasa por el gate ✅/❌ (decisión P-09).

- Proveedor por defecto: **Amazon SES** si P-15 indica más de ≈ 100 correos/día o si se prioriza el menor costo a escala; **Resend** si el volumen es bajo y se prioriza la velocidad (sin trámite de *sandbox*). Si P-22 confirma Workspace y P-18 prefiere que el correo salga del buzón del comercial, **2B** es mejor para nutrición 1:1 (las respuestas llegan a quien vende).
- **Respuestas entrantes (VCRM-102/103):** el `Reply-To` apunta a un buzón que el CRM lee por sondeo saliente (IMAP o Gmail API), sin ruta pública; ver 6.3.
- **2C WhatsApp en F4**, como dice la ruta del CTO, solo con opt-in de WhatsApp registrado y plantillas de marketing aprobadas.
- **2D** se mantiene como degradación: si el canal de correo falla de forma persistente (VCRM-038), el aprobador puede copiar el texto aprobado y enviarlo a mano, y lo registra.

**Trade-offs:** el correo tiene menor tasa de apertura que WhatsApp en Colombia, pero es casi gratis, no exige ingreso público y la prueba de consentimiento y baja es más simple.

---

## Decisión 3 — Motor de cadencias y persistencia de estados del lead

### Alternativas del motor

- **3A. Tabla persistente de «próxima acción» + barrido periódico** registrado como **un único job** del `CronScheduler` de Jericó (p. ej. `* * * * *`), que selecciona los leads con `next_action_at <= ahora` y genera propuestas de forma idempotente.
- **3B. Un job del `CronScheduler` por lead.**
- **3C. APScheduler 3.x con `SQLAlchemyJobStore`.**
- **3D. Cola diferida en Redis (arq o RQ).**

| Criterio | 3A Tabla + barrido | 3B Job por lead | 3C APScheduler + jobstore SQL | 3D arq / RQ en Redis |
| :--- | :--- | :--- | :--- | :--- |
| Costo mensual | USD 0 | USD 0 | USD 0 | USD 0 (Redis ya está en compose) |
| Velocidad de despliegue | Alta | Alta, pero incorrecta | Media | Media |
| Mantenimiento | Bajo: SQL y una función pura `due_actions(hoy)` | Alto: estado en memoria | Medio: SQLAlchemy nuevo, jobs serializados con *pickle*, APScheduler 4 lleva años en pre-release [VERIFICAR] | Medio: worker adicional; arq en modo mantenimiento [VERIFICAR] |
| Encaje con Jericó | **Máximo**: usa `CronScheduler.register_job` sin modificarlo; sin dependencias nuevas | Malo: `CronScheduler` no persiste, no tiene ejecuciones únicas ni baja de jobs; «30 días desde X» no se expresa en cron de 5 campos | Bajo: segundo planificador y dependencia nueva (contra la cintura estrecha) | Bajo: Redis es memoria de corto plazo en la arquitectura, no fuente de verdad |
| Encaje con OCI A1 | Excelente (consulta indexada por minuto) | Bueno | Bueno | Bueno |
| Riesgos | Latencia de hasta 1 min (irrelevante para cadencias de días); requiere *claim* atómico si hay más de un proceso | Pérdida total de cadencias al reiniciar | Duplicados si la idempotencia no se diseña; *pickle* | Pérdida de jobs si Redis pierde datos; doble fuente de verdad |

### Alternativas de persistencia

- **P1. Tablas `crm_*` (nuevas) dentro de `jerico_state.db`** añadidas a `state/schema.py` del núcleo.
- **P2. Base de datos propia del CRM** (nueva; archivo SQLite WAL separado en local/tests; esquema o base propia en PostgreSQL cuando llegue D1), con un repositorio del CRM con SQL ANSI portable y migraciones propias.
- **P3. PostgreSQL desde el día uno solo para el CRM.**

| Criterio | P1 Tablas en el núcleo | P2 Base propia del CRM | P3 PostgreSQL ya |
| :--- | :--- | :--- | :--- |
| Costo | USD 0 | USD 0 | USD 0 en OCI, pero consume RAM/CPU del envelope 2/12 |
| Velocidad | Alta | Alta | Baja: depende de D1 (otra línea) y aprovisionamiento |
| Mantenimiento | **Conflictos**: `SCHEMA_VERSION` y `initialize_schema` los editan otras líneas | Bajo: migraciones propias (`crm_schema_version`) | Medio-alto: dos motores en paralelo |
| Encaje con Jericó | Alto en teoría; mala convivencia | Alto: mismas PRAGMAs (WAL, `busy_timeout`, `foreign_keys`) y patrón de escritor serializado de `StateEngine` | Alineado con D1, adelantado |
| Riesgos | Choques de migración entre líneas | Duplicar algo de código de conexión (≈ 40 líneas) | Bloquea F1 hasta que D1 exista |

### Recomendación

**3A + P2.**

- Tablas conceptuales, **todas nuevas** (prefijo `crm_` si se comparte motor): `leads`, `lead_contacts` (normalizados E.164/correo, índice único para duplicados), `lead_events` (historial inmutable de estados y de cambios de datos, VCRM-015/080), `attachments`, `consents` (append-only), `suppression_list` (solo huella, ver abajo), `cadences` (lead, motivo, frecuencia, paso, `next_action_at`), `proposals` (gate) con **`UNIQUE(lead_id, cadence_step, version)`** y marca de versión vigente (VCRM-033/099), `outbox` (notificaciones y envíos con clave de idempotencia y estado), `processed_updates` (identificadores de eventos entrantes, VCRM-079), `materials` (F3).
- **Idempotencia:** clave única por paso de cadencia; *outbox* con transición `pendiente → enviando → entregado/fallido` en transacción; la pulsación de botón resuelve la propuesta con `UPDATE ... WHERE status = 'pendiente' AND version = vigente` (una sola fila afectada gana; una versión reemplazada no afecta filas → VCRM-099).
- **Huella de contacto (VCRM-095, spec 4.5):** HMAC-SHA-256 del contacto normalizado con una clave secreta en variable de entorno (constitución, punto 6). Un hash sin clave no basta: los teléfonos colombianos son enumerables (≈ 10⁹ combinaciones) y se revertirían por fuerza bruta. Rotar la clave invalida la lista; si se rota, hay que conservar la clave anterior para comprobar huellas antiguas. La bitácora guarda solo identificadores de lead y actor (VCRM-096).
- **Respaldo (VCRM-097/098):** el script de D2 (`pg_dump`) no cubre una base SQLite del CRM. Propuesta: job nocturno del mismo barrido que hace copia en caliente consistente (`VACUUM INTO` o API de *backup* de SQLite), empaqueta adjuntos, cifra con `age` (clave pública en el servidor, privada fuera) y sube a **OCI Object Storage** (20 GB Always Free según la nota de Oracle) u otro destino de D2; rotación según PR-12. Cuando el CRM migre a PostgreSQL, pasa a cubrirlo el respaldo de D2 más los adjuntos.
- **Portabilidad a PostgreSQL (D1):** SQL ANSI, sin FTS5 ni tipos exclusivos de SQLite, fechas como texto ISO-8601 UTC (o `timestamptz` en PG), *claim* con `SELECT ... FOR UPDATE SKIP LOCKED` en PG y escritor serializado en SQLite. La suite corre sobre SQLite (constitución, punto 4).
- **Zona horaria:** almacenamiento en UTC; cálculo con `zoneinfo("America/Bogota")` (UTC−5 sin horario de verano) en funciones puras con parámetro `hoy`. El `CronScheduler` evalúa en UTC, lo cual es irrelevante para un barrido cada minuto.
- **Festivos de Colombia (Ley 51 de 1983, «Ley Emiliani»):** paquete `holidays` (Python puro, sin red, versión fijada) o función propia con Pascua + traslados. Recomendado: `holidays`, por exactitud y bajo mantenimiento; alternativa sin dependencias: tabla anual en configuración.

**Choque con D1 — RESUELTO por el CTO (P-14, ronda 2, 04/10/2026):** D1 reserva SQLite para tests y desarrollo local. Salidas que se analizaron: (a) esperar a D1 o aprovisionar PostgreSQL solo para el CRM (P3, más RAM en 2/12); (b) excepción temporal documentada (SQLite en producción hasta D1). **Decisión del CTO: (b).** SQLite en producción queda autorizado para el CRM como excepción temporal a D1, con SQL portable a PostgreSQL 16 (reglas de portabilidad de arriba), y el CRM corre en la misma instancia de OCI que Jericó. Pendiente: reflejar la excepción en la constitución cuando se ratifique (su punto 4 cita D1 sin excepciones).

**Trade-offs:** el barrido por minuto es menos «elegante» que un temporizador por lead, pero sobrevive a reinicios, es testeable con un reloj inyectado y no toca el núcleo.

---

## Decisión 4 — Transcripción de voz (STT)

### Alternativas

- **4A. faster-whisper local** (ya integrado en `voice/stt.py`).
- **4B. whisper.cpp local** (C/C++, optimizado con NEON en ARM, modelos cuantizados).
- **4C. APIs externas:** OpenAI, Groq, Deepgram.

### Estimaciones en OCI A1 (2 OCPU / 12 GB) — **[MEDIR EN A1]**, sin benchmark propio

| Modelo (faster-whisper, int8) | RAM aprox. | Factor de tiempo real estimado con 2 núcleos ARM | Calidad en español |
| :--- | :--- | :--- | :--- |
| `base` | ≈ 0,3–0,5 GB | ≈ 0,2–0,5× (2 min de audio en 25–60 s) | Aceptable para notas claras; falla con nombres propios |
| `small` (actual) | ≈ 0,6–1 GB | ≈ 0,5–1,5× (2 min de audio en 1–3 min) | Buena para notas de reunión |
| `medium` | ≈ 1,5–2,5 GB | ≈ 2–4× | Mejor, demasiado lento para 2 OCPU compartidos |
| `large-v3-turbo` | ≈ 1,5–2 GB | ≈ 1,5–3× | Muy buena; costosa en CPU |

CTranslate2 en ARM no tiene la aceleración de MKL de x86; whisper.cpp con cuantización `q5`/`q8` suele rendir mejor en ARM. Los modelos *distil-whisper* están orientados a inglés y no sirven aquí.

### Precios de APIs (referencia 2025) [VERIFICAR PRECIO VIGENTE]

| API | Precio aprox. | 600 min/mes (escenario: 10 audios/día × 2 min) |
| :--- | :--- | :--- |
| OpenAI `gpt-4o-mini-transcribe` | ≈ USD 0,003/min | ≈ USD 1,8 |
| OpenAI `whisper-1` / `gpt-4o-transcribe` | ≈ USD 0,006/min | ≈ USD 3,6 |
| Groq `whisper-large-v3-turbo` | ≈ USD 0,04/hora | ≈ USD 0,4 |
| Deepgram Nova-3 (pregrabado) | ≈ USD 0,0043/min | ≈ USD 2,6 |

### Comparativa

| Criterio | 4A faster-whisper local | 4B whisper.cpp local | 4C API externa |
| :--- | :--- | :--- | :--- |
| Costo mensual | USD 0 (CPU del envelope) | USD 0 | USD 0,4–4 en el escenario [VERIFICAR PRECIO VIGENTE] |
| Velocidad de despliegue | Inmediata: ya existe | Media: binario ARM + subproceso (D3) | Inmediata |
| Mantenimiento | Bajo | Medio: compilar y actualizar binario | Bajo; modelos pineados |
| Encaje con Jericó | Máximo (`STT.transcribe` devuelve `ok/error`) | Medio | Medio: cliente nuevo |
| Encaje con OCI A1 | Compite por 2 OCPU con el resto; procesar en cola de un solo worker | Mejor rendimiento por núcleo | Sin carga local |
| Soberanía | Total: el audio no sale del servidor | Total | **Audio con datos de clientes sale a EE. UU.** (transmisión internacional, decisión 6) |
| Riesgos | Latencia de minutos con `small`; picos de CPU que afectan al bot | Mantenimiento del binario | Costo, dependencia, cumplimiento |

### Recomendación

**4A en F4 con `small` int8, en una cola de un solo worker asíncrono** (la nota de voz es asíncrona: el comercial recibe la transcripción cuando esté lista), más una **tarea de benchmark en A1** antes de comprometer la latencia de VCRM-057 (P-23). Si el benchmark da más de la latencia aceptada: probar `base` o 4B. **4C (Groq) solo como respaldo opcional**, desactivado por defecto, condicionado a la autorización del CTO (P-23) y del abogado (L-8). En F1 los audios se guardan solo como adjuntos (sin transcribir).

**Trade-offs:** costo cero y soberanía a cambio de latencia de minutos y consumo de CPU.

---

## Decisión 5 — Google Drive (materiales) y contratos desde plantillas

### 5.1 Autenticación con Google

| Criterio | Cuenta de servicio | OAuth de usuario (refresh token) | Cuenta de servicio + delegación de dominio |
| :--- | :--- | :--- | :--- |
| Requiere Workspace | No para leer; **sí para crear archivos** (las cuentas de servicio no tienen cuota propia en «Mi unidad»: hay que usar una unidad compartida) [VERIFICAR] | No | Sí |
| Despliegue | Rápido: JSON de clave como secreto; compartir carpetas con la cuenta | Medio: pantalla de consentimiento; **si la app queda en estado «Testing», el refresh token caduca a los 7 días** → publicarla o marcarla «Internal» | Medio: lo configura el administrador del dominio |
| Riesgos | Clave JSON de larga vida (rotación) | Token ligado a una persona; si se va, se rompe | Poder amplio: limitar *scopes* |

### 5.2 Generación del borrador de contrato

| Criterio | Google Docs API (copiar plantilla + `replaceAllText` + exportar PDF) | docx local (`docxtpl`/`python-docx`) + LibreOffice *headless* → PDF | HTML → PDF (WeasyPrint) |
| :--- | :--- | :--- | :--- |
| Costo | USD 0 (cuotas de API) | USD 0 | USD 0 |
| Despliegue | Rápido si ya hay Google | Medio: LibreOffice en la imagen ARM (≈ 400–600 MB) | Medio: dependencias Pango/Cairo |
| Mantenimiento | Bajo: **el abogado edita la plantilla en Docs** y el borrador queda editable en Docs | Medio: plantillas Word versionadas; conversiones con picos de RAM y 2–5 s por documento | Alto: el abogado no edita HTML |
| Encaje con Jericó / A1 | Alto; sin binarios pesados en 2/12 | Pesa en imagen y RAM | Medio |
| Detección de campos faltantes (VCRM-054/055) | Leer el documento y listar marcadores `{{campo}}` antes de reemplazar | `docxtpl` permite listar variables de la plantilla | Trivial con plantillas |
| Soberanía | Contrato en Google (EE. UU.) | Local | Local |

### Recomendación

- **Materiales (F3):** Drive API v3 de solo lectura (`drive.readonly`) con **cuenta de servicio** a la que se comparten las carpetas de materiales; sincronización periódica por el mismo barrido de la decisión 3 (p. ej. cada hora) y catálogo en la tabla `materials`. Enlaces: compartir cada material «con cualquiera que tenga el enlace» en una carpeta pública de solo lectura, o compartir por correo con el cliente (más trazable, más fricción) — decisión del CTO al aprobar el plan.
- **Contratos (F3, sujeto a P-22):** **Google Docs API** si P-22 confirma Workspace (cuenta de servicio + unidad compartida «Contratos-Borradores» visible solo para abogado y CTO). Si el abogado trabaja en Word o no hay Workspace: **`docxtpl` + LibreOffice** en un contenedor aparte o bajo demanda.
- **Firma electrónica (futuro, fuera de alcance):** Ley 527 de 1999 y Decreto 2364 de 2012 (compilado en el Decreto 1074 de 2015). Opciones: DocuSign, Dropbox Sign, Yousign o proveedores colombianos de firma digital certificada (p. ej. Certicámara, GSE); fuera de alcance según el abogado (J-13). [VERIFICAR PRECIO VIGENTE]

**Trade-offs:** Docs API es lo más rápido y cómodo para el abogado, pero deja los contratos en Google; la ruta local es soberana pero más pesada para 2/12.

---

## Decisión 6 — Cumplimiento en Colombia: autorización y consentimiento comercial

### 6.1 Captura y prueba de la autorización

| Criterio | 6A Enlace único al correo del titular → página mínima de aceptación (doble opt-in) — **DESCARTADA por decisión del CTO (P-10)** | 6B Google Forms — **DESCARTADA por decisión del CTO (P-10)** | 6C Documento firmado o captura (anexo de autorización junto al contrato o en la reunión, foto/PDF/captura adjunta vía bot) — **MEDIO VÁLIDO (b) por decisión del CTO (N-04)** | 6D Autorización verbal declarada por el comercial — **NO es medio válido por decisión del CTO (N-04)** |
| :--- | :--- | :--- | :--- | :--- |
| Costo | USD 0 | USD 0 | USD 0 | USD 0 |
| Despliegue | Medio: requiere **ruta pública mínima** (Cloudflare Tunnel o Tailscale Funnel solo para `/consent/*`) | Rápido | Inmediato (F1) | Inmediato |
| Fuerza probatoria (Decreto 1377, arts. 7–8) | **Alta**: prueba control del correo, guarda fecha-hora, IP, versión del aviso y huella del texto | Media: el correo escrito no se verifica salvo inicio de sesión de Google | Alta para quien firma; depende de la custodia del archivo | **Baja**: es la palabra del comercial |
| Encaje | Alto: tabla `consents` append-only | Bajo: datos fuera del CRM; requiere importar | Alto: es un adjunto con tipo «autorización» | Alto pero sin evidencia documental |
| Riesgos | Abrir una ruta pública (superficie de ataque mínima, limitar a un endpoint sin datos) | Datos en Google; enlace reenviable | Fotos ilegibles; versión del texto incierta | Impugnable ante la SIC |

### 6.2 Recomendación

- **Medios válidos fijados por el CTO (N-04, ronda 2):** (a) respuesta del titular al correo de solicitud, con humano en el bucle; (b) documento firmado o captura adjuntados por el comercial (6C). La autorización verbal (6D) no es medio válido.
- **F1:** registrar la autorización solo con evidencia adjunta (6C como adjunto tipificado «autorización»; spec, VCRM-138 y VCRM-139). Los leads previos que el comercial carga uno a uno quedan «sin autorización» hasta que la registre (P-13).
- **F2:** autorización por correo como requisito para activar cadencias: mensaje con el aviso de privacidad versionado, que pasa por el gate ✅/❌ como todo mensaje al cliente final (decisión P-09; spec, VCRM-068). Mecanismo fijado por el CTO (P-10 y N-04): **la respuesta al correo se asocia al lead y se propone al comercial, que confirma con ✅/❌**; no hay detección automática de «ACEPTO» (PR-25 reemplazada; spec, VCRM-119 y VCRM-141 a VCRM-143). Al confirmar se guardan en `consents` las cabeceras, la fecha-hora UTC de la respuesta y de la confirmación, quién confirmó, la versión del aviso, las finalidades y la huella SHA-256 del texto enviado. El abogado acepta esta prueba (J-03, aceptado por delegación).
- **Baja:** instrucción «responda BAJA» en cada correo (PR-20) + cabecera `List-Unsubscribe` con `mailto:` (no requiere ruta pública; en la spec, PR-26 ratificada, VCRM-123 y VCRM-124) + orden del comercial en el bot. Sin enlace de baja de un clic: el CTO no autoriza rutas públicas (decisión P-10). La baja por palabra clave y por cabecera se aplica de inmediato y sin confirmación humana (spec, P-31 resuelta por delegación; J-06), con el riesgo aceptado de falsos positivos («temporada baja», «prioridad baja»). Las consultas y reclamos del titular se registran con plazo legal y escalado al CTO a los 2 días hábiles (spec, VCRM-150 a VCRM-153; J-05); la respuesta al titular, si sale por el sistema, pasa por el gate (decisión P-09). La baja escribe en `suppression_list` **solo la huella HMAC** del contacto (VCRM-095) **antes** de responder; el barrido y el envío consultan esa lista justo antes de cada envío (VCRM-037, VCRM-071).
- **Supresión:** borrado de datos personales y conservación mínima de la evidencia y de la huella de supresión (L-5); excepción por deber legal o contractual en leads aceptados o ganados (VCRM-094); la supresión cubre adjuntos y retractados y notifica la supresión de las copias enviadas (J-07); los respaldos conservan datos suprimidos como máximo 30 días (PR-12; J-08); conservación de adjuntos de «ganado» 10 años, supresión de «perdido» o «baja» a los 12 meses (J-01) y de leads sin autorización a los 30 días (J-14).
- **Ley 2300:** función pura `next_allowed_slot(hoy, festivos)` con la franja L–V 07–19 y sáb 08–15; tope semanal configurable, máximo 1 (P-19); semana calendario de lunes 00:00 a domingo 23:59 en Bogotá (PR-19); aplica también a B2B, con máximo 1 contacto por semana y lead (J-11, aceptado por delegación).
- **Transmisión internacional (L-8):** Telegram (comercial), proveedor de correo, Google y, si se usan, APIs de IA y STT son encargados fuera de Colombia. Acciones: inventario de encargados en el aviso de privacidad, contratos de transmisión (Decreto 1377, art. 25) y minimización (VCRM-064). **Hospedar en la región OCI Bogotá (`sa-bogota-1`)** mantiene la base de datos en Colombia. Telegram y Google aceptados como encargados y mencionados en la autorización; a la IA externa solo datos seudonimizados (J-10, aceptado por delegación).

### 6.3 Ruta pública para autorización y baja — DECIDIDO: 6.3-B (decisión P-10, 04/10/2026)

MEMORY.md y D2 fijan binds en `127.0.0.1` y acceso solo por Tailscale. La autorización por enlace y la baja de un clic chocan con eso.

| Criterio | 6.3-A Túnel acotado (Cloudflare Tunnel o Tailscale Funnel) solo para `/consent/*` y `/baja/*`, servido por un proceso mínimo sin acceso a otras rutas — **DESCARTADA por decisión del CTO** | 6.3-B Sin ruta pública: autorización y baja por respuesta al correo (buzón leído por sondeo saliente) — **ELEGIDA por el CTO** | 6.3-C Formulario externo (Google Forms, Tally u otro) con importación al CRM — **DESCARTADA por decisión del CTO** |
| :--- | :--- | :--- | :--- |
| Costo | USD 0 (ambos túneles tienen nivel gratuito) [VERIFICAR PRECIO VIGENTE] | USD 0 | USD 0 en planes gratuitos [VERIFICAR PRECIO VIGENTE] |
| Despliegue | Medio: túnel, dominio, *token* de un solo uso, limitación de tasa | Rápido: lectura IMAP o Gmail API, asociación de la respuesta al lead, propuesta al comercial para la autorización (N-04) y detección de «BAJA» (P-31) | Rápido para el formulario; medio para la importación |
| Fuerza probatoria | Alta (control del correo + IP + agente + versión del aviso) | Media-alta (control del buzón; cabeceras del correo); aceptada como prueba por el abogado (J-03) | Media (correo no verificado salvo inicio de sesión) |
| Encaje con MEMORY.md / D2 | Excepción explícita a «sin ingreso público»; requiere decisión del CTO | **Total**: solo conexiones salientes | Total en el servidor, pero los datos pasan por un tercero |
| Riesgos | Superficie de ataque nueva; enlaces reenviables; escáneres de correo que «pulsan» enlaces (mitigar con confirmación en la página) | Respuestas ambiguas («no gracias», «quítenme») que no contienen la palabra clave → van al comercial (VCRM-103); falsos positivos de «BAJA» («temporada baja») aplicarían una baja no pedida (P-31) | Encargado adicional fuera de Colombia (L-8); doble fuente de verdad |

**Decisión del CTO (P-10, 04/10/2026):** **6.3-B en F2** (cero ingreso público; se mantiene la postura Zero-Trust de MEMORY.md y D2), complementada con la orden del comercial en el bot. **6.3-A y 6.3-C quedan descartadas por decisión del CTO.** El abogado acepta la respuesta al correo como prueba (J-03, aceptado por delegación); 6.3-A no se reabre sin decisión expresa del CTO.

---

## Decisión 7 — Uso del LLM (extracción, tipificación y copys)

| Criterio | 7A `AsyncLLMClient` de Jericó, nivel L1 (`glm-5.3-flash`) | 7B Proveedor en país con nivel adecuado de protección vía override de endpoint por nivel | 7C Modelo local en A1 (p. ej. Qwen3 4B vía Ollama) | 7D Sin LLM: reglas y plantillas |
| :--- | :--- | :--- | :--- | :--- |
| Costo | ≈ USD 0,075 / 0,25 por millón de tokens (entrada/salida, cifra del repo, 2026); extracción de ~2.000 tokens ≈ USD 0,0003 [VERIFICAR PRECIO VIGENTE] | Similar o algo mayor | USD 0; consume ≈ 3–5 GB RAM y la CPU de 2 OCPU | USD 0 |
| Despliegue | Inmediato | Configuración (`JERICO_LLM_BASE_URL_L1` y clave) | Medio | Inmediato |
| Calidad | Buena para JSON estructurado | Buena | Limitada y lenta en 2 OCPU | Solo plantillas fijas |
| Cumplimiento | **Datos de clientes a proveedores con infraestructura en China**: transferencia a país sin nivel adecuado según la SIC; solo se admite con datos seudonimizados (J-10) | Mejor encaje | Soberano | Soberano |

### Recomendación

**7A con minimización obligatoria (VCRM-064) para F4**, migrando a **7B** si el abogado lo exige (P-23): basta con cambiar configuración, no código. Reglas:

- Modelo pineado (identificador exacto; el validador de `config.py` ya rechaza `-latest`/`-preview`).
- Prompt de sistema propio del CRM construido con `PromptBuilder` (huella SHA-256 registrada con cada salida, VCRM-063); salida en JSON validada con Pydantic contra un esquema cerrado (resultado ∈ {aceptado, rechazado, seguimiento}, motivo ∈ matriz).
- Sin LangChain/LlamaIndex; llamadas directas por `AsyncLLMClient`.
- Seudonimización antes del envío: el nombre del cliente se reemplaza por un marcador y se restituye localmente.
- **7D** es la degradación de VCRM-062 (PR-22) y la base de F2 (los textos de F2 son plantillas fijas por motivo, cuya autoría define P-21; la IA llega en F4, incluido el registro por texto libre).

---

## 8. Puntos de coordinación con el núcleo

El CRM no edita módulos del núcleo (`gateway/`, `tools/`, `state/`, `config.py`), pero sí necesita tocar archivos compartidos. Cada cambio se propone como parte de la tarea que lo exige, mínimo y revisable por las demás líneas.

| Archivo compartido | Cambio necesario | Fase | Propuesta para minimizarlo |
| :--- | :--- | :---: | :--- |
| `docker-compose.yml` | Servicio nuevo `jerico-crm` (misma imagen, otro `command`), volumen nuevo `jerico_crm_data`, sin `ports`. | F1 | Bloque aditivo; no cambia `jerico-core` ni `redis`. Alternativa: archivo `docker-compose.crm.yml` superpuesto con `-f`, que deja intacto el compartido. |
| `Dockerfile` | La imagen instala solo `[project].dependencies`; los extras del CRM no entrarían. Además, el `HEALTHCHECK` consulta `127.0.0.1:8000/health`, que el proceso del CRM no sirve. | F1 | Argumento de construcción `EXTRAS` con valor vacío por defecto (la imagen de `jerico-core` no cambia); `healthcheck` propio del servicio `jerico-crm` en compose (p. ej. latido en archivo). |
| `pyproject.toml` — `[project.scripts]` | Punto de entrada `jerico-crm`. | F1 | Una línea aditiva; alternativa: subcomando `crm` en la CLI `jerico` (pero eso toca `main.py`, peor). |
| `pyproject.toml` — dependencias | `httpx` explícito (hoy solo está en `dev` y llega transitivo por `openai`); `holidays` (F2); `google-api-python-client` y `google-auth` (F3); `docxtpl` (F3, solo sin Workspace). | F1–F3 | **Extras opcionales** `crm` (`httpx`), `crm-f2` (`holidays`), `crm-google`, `crm-docs`, con import perezoso como el extra `voice`; las dependencias base del núcleo no crecen. `httpx` puede ir en `crm` en lugar de la base. |
| `pyproject.toml` — `[tool.mypy]` | Módulos de Google sin *stubs*. | F3 | `[[tool.mypy.overrides]]` con `ignore_missing_imports` limitado a esos módulos. |
| `scripts/verify.sh` y cobertura | La suite del CRM entra en `tests/` y en la cobertura global; AGENTS.md exige ≥ 89 %, pero hoy `verify.sh` ejecuta `pytest` sin `--cov` ni umbral. | F1 | El CRM llega con cobertura propia ≥ 89 % de su paquete para no bajar la global; tests herméticos que no requieren instalar extras (dobles de prueba para Telegram, correo y Google). Añadir el umbral a `verify.sh` es una decisión del núcleo, no de esta línea. |
| `.env` / `.env.example` | Token del bot del CRM, lista blanca por rol con la dirección de correo de cada usuario, clave HMAC de huellas, buzón remitente y credenciales del correo interno (F1; decisión P-27: parámetros sin valor fijo, se configuran después) y del correo al cliente (F2), credenciales de Google, clave pública de cifrado del respaldo. | F1–F3 | Prefijo `JERICO_CRM_*` y configuración propia del CRM (no se toca `config.py`); en `.env.example` solo nombres de variables, sin valores. |
| Respaldo (D2) | El script de D2 cubre PostgreSQL, no la base SQLite ni los adjuntos del CRM. | F1 | Job de respaldo propio del CRM (decisión 3); converger con D2 cuando el CRM migre a PostgreSQL. |
| Motor de producción (D1) | Excepción temporal autorizada por el CTO (P-14, ronda 2): SQLite WAL en producción solo para el CRM, con SQL portable a PostgreSQL 16. | F1 | Base propia del CRM (P2, decisión 3), sin tocar `state/`; migración a PostgreSQL cuando el CTO lo disponga. La constitución, ratificada el 04/10/2026, recoge la excepción en su punto 4 (decisión A.4). |
| Instancia OCI 2/12 | Decidido (P-14, ronda 2): el CRM convive con Jericó en la misma instancia; comparte CPU y RAM con el núcleo y, en F4, con el STT. | F1 | Límites de memoria y CPU por servicio en compose; STT en cola de un solo worker. |

---

## Resumen de recomendaciones

| Decisión | Recomendación | Por qué | Riesgo principal |
| :--- | :--- | :--- | :--- |
| 1. Canal del comercial | Bot de Telegram propio del CRM (token separado, long polling, cliente `httpx` delgado), proceso aparte que reutiliza módulos de Jericó | USD 0, días de despliegue, no abre puertos, no depende de D5 ni edita el gateway | Datos de clientes en la nube de Telegram; un bot más que operar |
| 2. Correo | F1: `EmailSender` (nuevo) para notificaciones internas (SMTP del buzón remitente o API; buzón y credenciales por configuración, P-27). F2, canal al cliente: correo por API detrás del mismo `EmailSender` (SES o Resend según volumen; Gmail API si hay Workspace y se prefiere el buzón del comercial); respuestas leídas por sondeo saliente; WhatsApp en F4 | Casi gratis, sin ingreso público, consentimiento y baja simples | Entregabilidad del dominio; menor apertura que WhatsApp |
| 3. Cadencias y estados | Tabla `next_action_at` + un job de barrido en `CronScheduler`; base propia del CRM (nueva) con SQL portable a PostgreSQL; respaldo cifrado propio | Sobrevive reinicios, idempotente, sin dependencias nuevas en F1, sin chocar con `schema.py` | SQLite en producción como excepción temporal a D1 autorizada por el CTO (P-14), aún no reflejada en la constitución; divergencia si D1 elige otra abstracción de conexión |
| 4. STT | faster-whisper `small` local en cola de un worker (F4), benchmark previo en A1; Groq solo como respaldo autorizado | USD 0 y soberano; ya integrado | Latencia de minutos y CPU en 2/12 |
| 5. Drive y contratos | Drive API readonly con cuenta de servicio; Google Docs API para borradores (o docxtpl + LibreOffice si no hay Workspace) | El abogado edita en Docs; sin binarios pesados | Cuota de cuentas de servicio y contratos alojados en Google |
| 6. Cumplimiento | F1: autorización solo con documento o captura adjuntos, supresión por huella HMAC, bitácora sin datos personales; F2: autorización por respuesta al correo confirmada por el comercial y baja por respuesta al correo, sin ruta pública (decisiones P-10 y N-04), y todo mensaje al cliente por el gate (decisión P-09); franja Ley 2300 | Fuerza probatoria suficiente con costo cero y sin abrir ingreso público | Prueba por respuesta al correo pendiente de validar con el abogado; interpretación jurídica pendiente |
| 7. LLM | `AsyncLLMClient` L1 pineado + `PromptBuilder` + JSON validado + minimización; override a proveedor «adecuado» si el abogado lo pide | Costo despreciable; cero frameworks; reversible por configuración | Transferencia internacional de datos a China |
| 8. Coordinación | Extras opcionales, servicio y entrypoint aditivos, configuración `JERICO_CRM_*`, cobertura propia ≥ 89 % | Minimiza el roce con otras líneas | Cambios en archivos compartidos que otras líneas también editan |

## Propuesta de MVP (F1) mínima

1. **Proceso `jerico-crm`** (nuevo; misma imagen, otro servicio de compose, sin puertos expuestos) con bot de Telegram propio en long polling e idempotencia de eventos entrantes (VCRM-079).
2. **Roles por lista blanca y matriz de permisos** (PR-04): comercial, CTO, abogado (VCRM-001/002, 085/086).
3. **Leads:** registro con formato estructurado (PR-01), validación, duplicados (aviso y sin alta; aviso al CTO si es de otro comercial, P-11) y contactos suprimidos, edición con historial (incluidos los campos del handoff, P-05), notas y adjuntos de hasta 20 MB (foto, documento, voz como archivo; P-12), listados paginados y visibilidad por comercial (P-04) y del abogado (leads que alguna vez estuvieron en «aceptado», decisión A.1) (VCRM-003–012, 080–083, 088, 090, 109, 110, 112, 135–137).
4. **Estados F1:** nuevo → contactado → aceptado → ganado; rechazado con motivo, incluida la retractación confirmada de un aceptado (P-08, N-11); vuelta de un rechazado a contactado o aceptado (N-01); perdido, marcado solo por el comercial del lead o el CTO; el abogado marca «ganado» y registra la retractación (P-07, P-25, PR-23 ratificada, A.1); baja; «Registrar contacto» (PR-07) (VCRM-013–017, 089, 113–118, 131–135).
5. **Handoff:** confirmación ✅/❌ (PR-05 ratificada); notificación al CTO por Telegram y al abogado por Telegram y correo (P-01) por *outbox* persistente, primer intento antes de 1 minuto y 3 intentos en total a los 0, 1 y 5 minutos, solo para notificaciones críticas (P-02, A.3); correo de respaldo solo tras fallar el tercero; lo dirigido al comercial del lead va al CTO si el lead es suyo o no tiene comercial (A.2); aviso de fallo del respaldo y alerta persistente; notificación aunque falten campos y aviso al completarlos (PR-06 ratificada) (VCRM-046–052, 084, 087, 104, 105, 107, 111, 127–130, 140, 156).
6. **Equipo:** lista de usuarios autorizados persistida en la base de datos, con alta y baja por el bot y reasignación de leads (PR-09, A.5; VCRM-091–093, 125, 126, 144).
7. **Cumplimiento mínimo:** estado y evidencia de autorización (solo con documento o captura, N-04), baja, lista de supresión por huella, exportación y supresión por orden del CTO con excepción contractual, auditoría sin datos personales; solicitudes de titulares con plazos y escalado (J-05); notificación de supresión de copias (J-07); conservación de adjuntos de «ganado» 10 años y supresión de «perdido» o «baja» a los 12 meses (J-01); supresión automática de leads sin autorización a los 30 días, con aviso a los 25 (J-14); plazos configurables con topes legales (VCRM-065, 066, 070, 071, 073–075, 094–096, 138, 139, 145–147, 150–152, 154, 155, 158, 159, 162).
8. **Persistencia propia** SQLite WAL (portable a PostgreSQL 16; excepción temporal a D1 autorizada por el CTO, P-14), fechas UTC presentadas en America/Bogota y respaldo cifrado nocturno fuera de la máquina con retención de 30 días (J-08) (VCRM-077/078, 097/098).
9. **Fuera del MVP:** cadencias, gate de mensajes al cliente, correo al cliente y lectura de buzón, Drive, contratos, STT, IA, texto libre.

**Costo estimado del MVP:** USD 0/mes (Telegram + OCI Always Free + SQLite + Object Storage dentro de la cuota gratuita [VERIFICAR PRECIO VIGENTE]). **Lo que desbloquea F1:** nada bloqueante. Tras la ronda final (04/10/2026) la spec está aprobada: P-30 y P-32 quedan resueltas por las decisiones A.2 y A.1, la conservación por J-01 y las interpretaciones I-01 a I-07 confirmadas o reemplazadas (A.3); todas las propuestas están ratificadas y la constitución, ratificada (R-07). Siguiente paso: pasada final del reviewer y plan de F1.

---

> Última modificación: 04/10/2026 20:20 (Planificador SDD)
