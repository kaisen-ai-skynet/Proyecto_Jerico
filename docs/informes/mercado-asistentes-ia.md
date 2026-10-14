# Informe de Investigación: Mercado de Asistentes, Agentes IA y CRMs (Octubre 2026)

**Frente:** F4 — Asistente nivel Hermes + Análisis de mercado + Voz, webs y apps  
**Destino:** `kai-jev` (director de arquitectura)  
**Autor:** `plan-gemini` (apoyo F4)  
**Fecha:** 13 de octubre de 2026  
**Estado:** Entregado (para revisión y diseño de fases de arquitectura)

---

## 1. Objetivo y Alcance

Este informe compara los principales asistentes generalistas, agentes de software y plataformas de CRM con inteligencia artificial del mercado a octubre de 2026. Analiza para cada uno: capacidades, precio, voz, desarrollo de webs/apps, ventas/CRM y fuentes verificadas. Cierra con los diferenciales y requerimientos que Jericó debe incorporar para superarlos, dejando las preguntas de arquitectura abiertas para `kai-jev`.

---

## 2. Matriz Comparativa del Mercado

### 2.1 Grok (xAI)
- **Qué hace:** Asistente conversacional desarrollado por xAI (modelos Grok-2 y Grok-2 mini). Su principal capacidad distintiva es el acceso e indexación en tiempo real de publicaciones, noticias y tendencias de la red social X (Twitter). Modo humorístico y modo normal; generación de imágenes integrada con Flux 1.
- **Precio:**
  - Suscripción individual: Incluido en X Premium ($8 USD/mes o $84 USD/año) y Premium+ ($16 USD/mes o $168 USD/año en web).
  - API (console.x.ai): Grok-2 a $2.00 input / $10.00 output por 1M tokens; Grok-2-mini a $0.20 input / $1.00 output por 1M tokens. Ventana de contexto de 128k tokens.
- **Voz:** Modo de voz conversacional básico en app móvil para suscriptores Premium. Sin API pública documentada para streaming de audio dúplex o telefonía de baja latencia a octubre 2026.
- **Creación de webs/apps:** Limitado a generación de código en la ventana de chat. Sin entorno nativo de renderizado (tipo Artifacts) ni sandboxes de ejecución en la nube.
- **CRM y ventas:** NULO. No cuenta con gestión de contactos, seguimiento de leads ni embudos de ventas.
- **Fuentes:**
  - xAI API Overview & Pricing: https://docs.x.ai/docs/overview (13 de agosto 2024 / verificado octubre 2026).
  - Grok-2 Announcement: https://x.ai/blog/grok-2 (13 de agosto 2024).

### 2.2 Agentes de OpenAI (OpenAI)
- **Qué hace:** Ecosistema compuesto por ChatGPT (modelos GPT-4o, GPT-4o mini, serie de razonamiento o1) y la API de OpenAI. Incluye Canvas (espacio de trabajo interactivo para texto y código), GPTs personalizados, Function Calling avanzado y el framework de agentes Swarm / Agents SDK.
- **Precio:**
  - ChatGPT Plus: $20 USD/mes por usuario. Team: $25-30 USD/mes por asiento.
  - API de texto: GPT-4o a $2.50 input / $10.00 output por 1M tokens; GPT-4o-mini a $0.15 input / $0.60 output por 1M tokens.
  - Realtime API (Voz/Audio): $100.00 input / $200.00 output por 1M tokens de audio (equivalente aproximado a ~$0.06/minuto de entrada y $0.24/minuto de salida en conversación fluida).
- **Voz:** Advanced Voice Mode (AVM) en ChatGPT con entonación emocional y latencia ultrabaja. En la API: OpenAI Realtime API (soporte WebSockets y WebRTC para conversaciones de voz bidireccionales nativas sub-300ms sin cascada ASR->LLM->TTS).
- **Creación de webs/apps:** Canvas permite editar, previsualizar y refinar código HTML/JS/Python en tiempo real junto al modelo. Soporte de ejecución de código en Code Interpreter. No hospeda despliegues web autónomos productivos (requiere exportar código).
- **CRM y ventas:** No tiene CRM nativo. Se integra vía API o conectores (Zapier, HubSpot conector) para clasificar correos o sugerir respuestas.
- **Fuentes:**
  - OpenAI Realtime API Announcement: https://openai.com/index/introducing-the-realtime-api/ (1 de octubre 2024).
  - OpenAI API Pricing: https://openai.com/api/pricing/ (verificado octubre 2026).
  - OpenAI Canvas: https://openai.com/index/introducing-canvas/ (3 de octubre 2024).

### 2.3 Claude (Anthropic)
- **Qué hace:** Familia Claude 3.5 (Sonnet, Haiku) y Claude 3 Opus. Líder en razonamiento de código y análisis documental complejo con ventana de 200k tokens. Capacidades destacadas: *Artifacts* (previsualización interactiva de código/diseño), *Computer Use* (API que controla cursor, clics y teclado en entornos de escritorio) y *Claude Code* (agente CLI para ingeniería de software autónoma en terminal).
- **Precio:**
  - Claude Pro: $20 USD/mes por usuario. Team: $25-30 USD/mes por usuario (mínimo 5 usuarios).
  - API: Claude 3.5 Sonnet a $3.00 input / $15.00 output por 1M tokens. Prompt Caching nativo: reduce la lectura de contexto cacheado a $0.30 por 1M tokens (90% de descuento). Claude 3.5 Haiku a $0.80 input / $4.00 output por 1M tokens.
- **Voz:** Sin API de voz en tiempo real nativa. La app móvil ofrece dictado STT y lectura de texto en voz alta estándar. Depende de servicios externos como ElevenLabs o Deepgram.
- **Creación de webs/apps:**
  - *Artifacts:* Renderizado en vivo de aplicaciones React, HTML5, SVG y lógica frontend directamente en la interfaz.
  - *Claude Code:* Agente de desarrollo CLI capaz de ejecutar comandos, explorar repositorios completos, correr suites de tests y aplicar parches de código multi-archivo de forma autónoma.
- **CRM y ventas:** Nulo como CRM propio. Muy utilizado mediante API para extracción estructurada de datos de cotizaciones, resúmenes de llamadas y redacción de propuestas de alto impacto.
- **Fuentes:**
  - Anthropic 3.5 Models and Computer Use: https://www.anthropic.com/news/3-5-models-and-computer-use (22 de octubre 2024).
  - Anthropic Prompt Caching: https://www.anthropic.com/news/prompt-caching (14 de agosto 2024).
  - Anthropic Pricing: https://www.anthropic.com/pricing (verificado octubre 2026).

### 2.4 Gemini (Google)
- **Qué hace:** Ecosistema multimodal nativo de Google (Gemini 1.5 Pro con ventana de contexto de 2 millones de tokens y Gemini 1.5 Flash de 1 millón). Procesa nativamente horas de audio y video. Integración profunda con Google Workspace (Docs, Sheets, Gmail, Drive).
- **Precio:**
  - Gemini Advanced: $19.99 USD/mes (Google One AI Premium con 2TB de almacenamiento).
  - API: Gemini 1.5 Flash gratuito hasta 15 RPM; versión de pago a $0.075 input / $0.30 output por 1M tokens (<128k). Gemini 1.5 Pro a $1.25 input / $5.00 output por 1M tokens. Context Caching disponible con 75% de ahorro.
- **Voz:**
  - *Gemini Live:* Conversación de voz bidireccional continua con interrupciones naturales disponible en apps móviles Android/iOS.
  - *Multimodal Live API:* API bidireccional sobre WebSockets para streaming combinado de audio y vídeo con latencia interactiva.
- **Creación de webs/apps:** Canvas en interfaz web. Integración con Project IDX (entorno de desarrollo basado en web con plantillas full-stack para Flutter, Next.js y emuladores).
- **CRM y ventas:** No dispone de CRM transaccional. Conecta mediante Workspace con Google Sheets y Gmail para seguimiento rudimentario de leads.
- **Fuentes:**
  - Google Gemini API Pricing: https://ai.google.dev/pricing (verificado octubre 2026).
  - Gemini Live Overview: https://blog.google/products/gemini/made-by-google-gemini-ai-updates/ (13 de agosto 2024).
  - Gemini Live API: https://ai.google.dev/gemini-api/docs/live (verificado octubre 2026).

### 2.5 Hermes Agent (Nous Research)
- **Qué hace:** Agente autónomo de código abierto orientado a soberanía e ingeniería de sistemas (`nousresearch/hermes-agent`). Construido sobre una arquitectura de "cintura estrecha" (*narrow waist*): bucle de turnos sincrónico desacoplado en más de 25 fases modulares (`agent/turn_*.py`), persistencia en SQLite WAL con FTS5 (`state.db`), estricta inmutabilidad del system prompt para maximizar *prompt caching*, catálogo de habilidades (`SKILL.md`) con auditoría estricta y curador autónomo (`curator.py`) que archiva habilidades obsoletas durante periodos de inactividad.
- **Precio:**
  - Software: Código abierto, 100% gratuito (licencia Apache 2.0 / MIT).
  - Inferencia: Costo de API según el proveedor configurado (OpenAI, Anthropic, Fireworks) o $0 costo marginal si corre sobre inferencia local privada (vLLM / Ollama con pesos Hermes 3 / Llama 3).
- **Voz:** Herramienta interna `text_to_speech` con múltiples backends desacoplados: Edge-TTS (gratuito), Piper (offline/local), ElevenLabs y OpenAI TTS. No incluye por defecto protocolo WebSocket para voz dúplex en tiempo real, operando por turnos discretos.
- **Creación de webs/apps:** Alta potencia en generación y mantenimiento de software. Incluye herramientas de núcleo `read_file`, `write_file`, `patch` (fuzzy matching), `search_files`, `terminal` y 7 entornos de ejecución de terminal (`tools/environments/`): PTY local, contenedores Docker con aislamiento de red, servidores remotos SSH, sandboxes serverless de Modal, Daytona y micro-VMs de Vercel. Despliega páginas estáticas automáticamente en Cloudflare.
- **CRM y ventas:** NULO como sistema CRM. No incluye conceptos de leads, embudos, etapas de cierre, cotizaciones ni cobranza.
- **Fuentes:**
  - Nous Research Hermes Agent: https://github.com/nousresearch/hermes-agent (septiembre 2026).
  - Arquitectura Maestra de Hermes en Jericó: `docs/architecture/hermes_master_architecture.md` (29 de septiembre de 2026).

### 2.6 CRMs con IA Integrada

#### 2.6.1 HubSpot (Breeze AI)
- **Qué hace:** Suite de inteligencia artificial embebida en HubSpot CRM. Compuesta por:
  - *Breeze Copilot:* Asistente conversacional para consultas de clientes y redacción.
  - *Breeze Agents:* Agentes autónomos especializados: *Prospecting Agent* (investiga empresas y redacta correos de prospección fríos personalizados), *Customer Agent* (soporte 24/7 con bases de conocimiento), *Content Agent* (artículos y landing pages) y *Social Media Agent*.
  - *Breeze Intelligence:* Enriquecimiento de datos comerciales y análisis de intención de compra (basado en la adquisición de Clearbit).
- **Precio:**
  - Nivel Free: Básico sin agentes avanzados.
  - Sales Hub Professional: desde ~$90–$100 USD/mes por usuario (requiere paquete mínimo de asientos, coste de entrada típico ~$450–$500 USD/mes).
  - Sales Hub Enterprise: desde ~$150 USD/mes por usuario.
  - Paquetes de créditos Breeze adicionales: para prospección e inteligencia de datos (desde $100 USD/mes en consumo extra).
- **Voz:** Grabación, transcripción y análisis de sentimientos en llamadas mediante telefonía VoIP integrada en Sales Hub Professional/Enterprise. No cuenta con agente autónomo de voz saliente por IA en español nativo (depende de integraciones de telefonía externa).
- **Creación de webs/apps:** El *Content Agent* genera páginas web y landing pages dentro del CMS propietario de HubSpot. No genera código de software general ni aplicaciones completas.
- **CRM y ventas:** Excelente gestión de embudos visuales, automatización de secuencias de correo, asignación de leads por territorio y reportes de atribución de ingresos.
- **Fuentes:**
  - HubSpot Spotlight Inbound 2024: https://www.hubspot.com/spotlight (septiembre 2024).
  - HubSpot Pricing Guide: https://legal.hubspot.com/hubspot-pricing-model (verificado octubre 2026).

#### 2.6.2 Salesforce (Agentforce)
- **Qué hace:** Plataforma de agentes autónomos empresariales lanzada en Dreamforce 2024 como reemplazo de Einstein Copilot. Permite desplegar *Service Agents*, *Sales Development Rep (SDR) Agents* y *Sales Coaches*. Opera sobre el motor de razonamiento *Atlas Reasoning Engine*, que interpreta consultas, recupera contexto empresarial desde Data Cloud y dispara flujos automatizados de Salesforce Flow sin requerir código procedural.
- **Precio:**
  - Tarifa estándar de Agentforce: **$2.00 USD por conversación iniciada por el agente**.
  - Requiere licencias base de Salesforce Enterprise o Unlimited ($165 a $330+ USD/mes por usuario) más suscripción a Data Cloud.
  - Modelo de precios sumamente oneroso, pensado exclusivamente para corporaciones de gran escala.
- **Voz:** Service Cloud Voice integra telefonía de voz con transcripción y asistencia en vivo al operador humano (conectores con Amazon Connect y Genesys). Dispone de pilotos de voz autónoma para centros de llamadas empresariales.
- **Creación de webs/apps:** No genera aplicaciones independientes de software. Genera componentes Lightning Web Components (LWC) y flujos declarativos dentro de la plataforma Salesforce.
- **CRM y ventas:** Estándar de la industria corporativa. Control total de cuentas, contactos, procesos de cotización complejos (CPQ), forecasting de ingresos y cumplimiento de contratos multinivel.
- **Fuentes:**
  - Salesforce Agentforce Launch: https://www.salesforce.com/news/stories/agentforce-ai-agents-launch/ (12 de septiembre 2024).
  - Salesforce Sales Cloud Pricing: https://www.salesforce.com/editions-pricing/sales-cloud/ (verificado octubre 2026).

---

## 3. Tabla Resumen de Capacidades

| Plataforma / Agente | Enfoque Central | Costo Base / Entrada | Soporte de Voz | Creación de Webs / Apps | Potencia CRM y Ventas |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Grok (xAI)** | Información en tiempo real (X) | $8–$16 USD/mes | Básico en app móvil | Nula (solo texto) | Nula |
| **OpenAI (ChatGPT/API)** | Asistente multimodal general | $20 USD/mes ($100/1M tok audio) | Excelente (Realtime API sub-300ms) | Media (Canvas / sin hosting) | Baja (vía plugins) |
| **Claude (Anthropic)** | Razonamiento y código agéntico | $20 USD/mes ($3/1M tok texto) | Nula nativa | Alta (Artifacts + Claude Code CLI) | Baja (vía API) |
| **Gemini (Google)** | Contexto masivo y multimodalidad | $19.99 USD/mes ($0.075/1M tok) | Muy alta (Gemini Live API) | Media (Canvas + Project IDX) | Baja (integración Sheets) |
| **Hermes Agent** | Agente autónomo auto-evolutivo | Gratis / Open Source (+ API LLM) | Turnos TTS (Edge/ElevenLabs) | Muy alta (7 entornos, Docker/Modal) | Nula |
| **HubSpot (Breeze)** | CRM y marketing inbound | ~$450–$500 USD/mes base | Transcripción VoIP (sin bot voz) | Landing pages en su propio CMS | Muy alta (PYME y escala) |
| **Salesforce (Agentforce)** | Agentes corporativos autónomos | $2 USD/conversación (+ licencias) | Telefonía CTI / Service Voice | Componentes LWC propietarios | Máxima (Enterprise) |

---

## 4. Qué Tendría que Tener Jericó para Superarlos

Para superar tanto a los asistentes de propósito general (OpenAI, Claude, Hermes) como a los CRMs corporativos costosos (HubSpot, Salesforce), Jericó debe capitalizar las siguientes ventajas estratégicas:

1. **Soberanía y Economía Radical (Cero "Rent-Seeking" para LATAM):**
   - Salesforce ($2 por conversación) y HubSpot (> $500/mes) resultan inviables para las microempresas y PYMEs de la región.
   - Jericó corre en infraestructura propia económica (WSL2 en servidor local o VM ARM Always Free de Oracle a $0 de costo de cómputo base), con base de datos SQLite WAL local y modelos pineados económicos (`gpt-6-luna`, Gemini Flash o vLLM local). El coste operativo por lead/conversación es inferior a $0.005 USD.
2. **Cero Fricción de Adopción (100% sobre Telegram / WhatsApp):**
   - El gran fracaso de HubSpot y Salesforce en equipos de venta pequeños es la resistencia a llenar formularios extensos en pantallas de escritorio.
   - Jericó opera desde la app que el comercial ya tiene abierta todo el día (Telegram). Permite crear leads, consultar resúmenes (`/asistente resumen L-1`), registrar notas y recibir recordatorios con botones interactivos (✅/❌) en segundos.
3. **Flujo Integral Cerrado: De la Prospección al Contrato y la Firma Electrónica:**
   - Ningún asistente generalista (ChatGPT, Claude, Hermes) tiene integración de pipeline comercial y legal.
   - Ni HubSpot ni Salesforce generan de forma autónoma el paquete de cierre y lo derivan al abogado de la empresa con generación automática de minuta de contrato y firma electrónica en el mismo canal. Jericó cierra el círculo:
     $$\text{Lead} \longrightarrow \text{Calificación} \longrightarrow \text{Propuesta} \longrightarrow \text{Cierre} \longrightarrow \text{Paquete al Abogado} \longrightarrow \text{Contrato} \longrightarrow \text{Firma}$$
4. **Patrones de Ingeniería de Nivel Hermes:**
   - Inmutabilidad estricta del *system prompt* para maximizar el *prompt caching* (reducción del 80-90% de costes de tokens).
   - Catálogo de habilidades estandarizado (`SKILL.md`) y curador autónomo de fondo para mantener capacidades al día.
   - Persistencia local ACID en SQLite WAL con búsqueda FTS5 trigram para memoria histórica sin fugas de contexto.
5. **Cumplimiento de Privacidad Estricta (Ley 1581 de Colombia):**
   - Capa de seudonimización activa antes de salir hacia cualquier LLM (`src/jerico/crm/pseudonym.py`). Los CRMs multinacionales almacenan datos planos de clientes en servidores extranjeros sin control fino del usuario local.
6. **Capacidades de Fabricación (Webs, Apps y Llamadas de Voz):**
   - Incorporar sandboxes efímeros (patrón Docker/Modal de Hermes) para que Jericó pueda generar páginas de aterrizaje y mini-aplicaciones para clientes en minutos.
   - Integrar canal de voz saliente para prospección y confirmación de citas.

---

## 5. Preguntas de Arquitectura Abiertas (para `kai-jev`)

Como planificador de apoyo y respetando la separación de roles, se trasladan las siguientes preguntas técnicas de arquitectura al director `kai-jev`:

1. **Estrategia de Voz Comercial:** ¿Se adoptará una arquitectura de voz en tiempo real nativa mediante la OpenAI Realtime API (WebSockets con latencia <300ms a coste variable de ~$0.06/minuto de entrada) o se utilizará un pipeline desacoplado por turnos (STT con Whisper/Deepgram $\rightarrow$ LLM comercial $\rightarrow$ TTS con ElevenLabs/Edge-TTS) para optimizar costos en llamadas breves?
2. **Aislamiento en Creación de Webs/Apps:** Para dotar a Jericó de la capacidad de crear páginas y aplicaciones desde cero, ¿se desplegará un motor de sandboxes Docker locales en `kaisen-server` gestionado por el núcleo de Jericó o se delegará a entornos efímeros serverless externos (tipo Modal o Vercel Micro-VMs)?
3. **Persistencia Unificada vs Desacoplada:** ¿El bucle de turnos del asistente tipo Hermes compartirá la misma base SQLite WAL del CRM (`crm.db`) o mantendrá una base de persistencia de estado independiente (`state.db`) conectada mediante un bus de eventos interno para evitar bloqueos de contención entre el bot de Telegram y las tareas en segundo plano?
