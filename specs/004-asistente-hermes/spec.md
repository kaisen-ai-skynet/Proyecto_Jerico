# Spec 004 — Arquitectura por fases del asistente de Jericó (nivel Hermes y superior) (F4)

- **Estado:** BORRADOR para revisión del CTO (13/10/2026). Rama `asistente/f4-arquitectura-hermes`. Solo arquitectura y specs: sin código ni despliegue.
- **Insumos:** `docs/architecture/hermes_master_architecture.md`; informe de mercado de `plan-gemini` (`docs/informes/mercado-asistentes-ia.md`, ver §7); código actual del repo (verificado: `src/jerico/agent/`, `memory.py`, `skills/{loader,validator,curator}.py`, `tools/registry.py`, `voice/{stt,tts}.py`, `crm/assistant.py`).
- **Numeración:** 004 porque 003 se toma para `003-catalogo-precios` (F6). Reconfirmar con `git branch -a` antes de integrar.
- **Reglas:** constitución de Jericó (Postgres en producción, sin alias `-latest`, humano en el bucle D5, subproceso aislado D3, sin `git push`), Ley 1581 y «gratis primero» (nada de pago sin OK del CTO).

## 1. Punto de partida (verificado)

| Pieza | Hoy |
|---|---|
| Asistente CRM `/asistente` | Encendido en producción (`gpt-6-luna`, esfuerzo bajo, tope 60.000 tokens/día), rama `crm/asistente-comercial-llm` |
| Bucle de agente | `src/jerico/agent/` con turnos, compactación y recuperación ya partidos como en Hermes |
| Memoria | `memory.py` (102 líneas): en memoria, no persistente |
| Habilidades | `skills/` con cargador, validador y curador (existen; uso real sin verificar) |
| Herramientas | `tools/registry.py`, aprobación (`approval.py`), entorno aislado |
| Voz | `voice/stt.py` (faster-whisper local, funcional); `voice/tts.py` es un **stub** («TTS_NOT_IMPLEMENTED_V0») |
| Interfaz | Solo Telegram (`@Jericoo_bot`, un usuario: el CTO) |

## 2. Objetivo y criterio de «superior»

Un solo asistente que, con el mismo núcleo, atienda por Telegram, web y voz. No se compite en generalidad contra los asistentes de mercado; «superior» significa, medible: (a) conoce y cita el catálogo de precios (F6) y el CRM sin inventar; (b) toda acción con efecto externo pasa por aprobación humana (D5); (c) cuesta una fracción: tope de tokens por usuario y modelo barato por defecto; (d) deja trazabilidad por turno (modelo, tokens, herramientas). Los criterios se miden contra el informe de mercado.

## 3. Arquitectura por fases

```
 Telegram ─┐
 Web (PWA) ─┼─► Gateway (rol + identidad) ─► Núcleo del agente ─► Herramientas (registro, aprobación, subproceso)
 Voz ──────┘        │                         │  memoria (Postgres)   ├ CRM / leads
                    │                         │  habilidades SKILL.md ├ catálogo de precios (F6)
                    └─ Jev (decide modelo)    │  curador              ├ generador web/app (sandbox)
                                              └─ presupuesto tokens   └ correo (F2, por niveles)
```

**Fase A0 — hecho:** asistente CRM con presupuesto de tokens; probado por el CTO.

**Fase A1 — Núcleo y memoria (2 semanas).** Unir el bucle de `agent/` con el asistente CRM (hoy son piezas separadas). Memoria persistente en **PostgreSQL 16** (la constitución manda; la hoja de ruta de Hermes propone SQLite WAL, que se queda solo para pruebas). Tablas: sesiones, mensajes (con hash del prompt de sistema, invariante de caché), resúmenes de compactación. Memoria por usuario y rol: el comercial nunca ve la del CTO. Prompt de sistema inmutable; lo variable (fecha, usuario) va en el mensaje de usuario.
*Criterio de salida:* reiniciar el servicio no pierde la conversación; prueba de aislamiento entre dos comerciales.

**Fase A2 — Habilidades y curador (1–2 semanas).** Estándar `SKILL.md` (descripción ≤ 60 caracteres, validador ya existente). Habilidades iniciales de ventas: calificar lead, redactar seguimiento, preparar propuesta con precios del catálogo, resumir reunión. Curador por inactividad que propone archivar habilidades sin uso; **propone, no borra**: el CTO aprueba.
*Criterio:* 4 habilidades auditadas; el curador no elimina nada sin aprobación.

**Fase A3 — Acciones: leads, webs y apps (3–4 semanas).**
- *Leads:* herramienta `crear_lead` sobre el CRM existente; el comercial confirma el borrador antes de guardar (humano en el bucle, Ley 1581: solo datos mínimos y base legal registrada).
- *Webs y apps:* generador en subproceso aislado (D3), sobre plantillas aprobadas; produce un repo local y una vista previa; **nunca publica solo**: el despliegue exige OK del CTO. Modelo fuerte (Sonnet) solo para generar; Gemini para borradores y pruebas.
*Criterio:* una web de muestra generada de punta a punta en sandbox, con vista previa y sin tocar producción.

**Fase A4 — Voz (3 semanas, tras decisión del CTO).** Dos niveles:
1. *Notas de voz en Telegram* (entrada con `faster-whisper` local, gratis; respuesta de texto). Primero porque no cuesta y no es llamada.
2. *Voz de salida y venta por voz* (TTS + llamadas): requiere elegir proveedor (ver §7), consentimiento y aviso de que habla una IA, y no contrata ningún servicio de pago sin OK del CTO.
*Criterio:* nota de voz → respuesta correcta en el piloto; medición de latencia extremo a extremo.

**Fase A5 — Interfaz gráfica (3 semanas).** PWA servida por el mismo API (FastAPI ya existente) y el mismo gateway: mismo núcleo, mismos roles, mismas aprobaciones. Pantallas mínimas: chat, lista de leads, cola de aprobaciones, consumo de tokens. Autenticación por rol; nada nuevo en la nube.
*Criterio:* el comercial hace en la PWA lo mismo que en Telegram, con la misma trazabilidad.

**Fase A6 — Mejora continua.** Jev decide qué modelo usa cada tarea del asistente (reutiliza `Flota_Jev`); tablero de costo por turno; revisión trimestral contra el informe de mercado.

## 4. Requisitos (EARS)

- **R1** El asistente SHALL mantener la memoria de cada usuario en PostgreSQL, aislada por usuario y rol.
- **R2** El prompt de sistema SHALL ser inmutable dentro de una sesión; lo variable SHALL ir en mensajes de usuario o de herramienta.
- **R3** WHEN el asistente vaya a ejecutar una acción con efecto externo (crear lead, enviar correo, generar o publicar web), el sistema SHALL pedir aprobación humana con identidad verificada (D5).
- **R4** El asistente SHALL consultar precios solo mediante la herramienta del catálogo (spec 003) y NO SHALL calcular ni inventar precios.
- **R5** La generación de webs y apps SHALL ocurrir en subproceso aislado, sin `docker.sock` y sin acceso a secretos ni a datos de clientes; el resultado SHALL quedar como borrador local.
- **R6** WHILE un usuario supere su tope diario de tokens, el asistente SHALL responder con aviso y no llamar al modelo.
- **R7** La voz SHALL registrar consentimiento y avisar al interlocutor que habla una IA; las grabaciones de clientes quedan fuera del repositorio.
- **R8** Todo proveedor de pago (voz, nube, firma) SHALL requerir aprobación explícita del CTO documentada antes de integrarse.
- **R9** Cada turno SHALL registrar modelo, tokens, herramientas usadas y versión del prompt.
- **R10** La interfaz web SHALL usar el mismo gateway, roles y aprobaciones que Telegram.

## 5. Decisiones que necesita el CTO

1. **Venta por voz:** ¿notas de voz primero (gratis) y llamadas después? Propuesta: sí.
2. **Proveedor de voz:** pendiente de §7; ningún pago hasta su OK.
3. **PostgreSQL ya (A1) o seguir en SQLite hasta la migración D1:** propuesta, empezar con PostgreSQL en desarrollo para no repetir la migración.
4. **Prioridad entre A3 (webs/apps) y A5 (interfaz):** propuesta, A5 antes si se suman más comerciales; A3 antes si el interés es producir webs.

## 6. Riesgos

- Alcance «hace todo»: se controla con fases y criterios de salida medibles.
- Costo de tokens: tope por usuario ya existe; se extiende por fase.
- Datos de clientes en memoria del asistente (Ley 1581): memoria mínima, sin copiar documentos; retención definida en la spec de F2.
- Voz: llamadas automatizadas tienen reglas de consentimiento y de contacto comercial en Colombia; **sin verificar con el abogado** (no se afirma qué norma aplica).
- Superposición con la spec de F2 (CRM) y con F3 (Jev en el núcleo): se coordina por el plan maestro.

## 7. Voz y mercado

Base: `docs/informes/mercado-asistentes-ia.md` (plan-gemini) más una verificación mía el 13/10/2026.

**Correcciones al informe.** (a) Sus cifras de voz de OpenAI (100/200 USD por millón de tokens de audio, ~0,06 USD/min) vienen del anuncio de 2024 y están desactualizadas: la página oficial de precios lista `gpt-realtime-2` (lanzado el 07/05/2026) a **32 USD de entrada y 64 USD de salida por millón de tokens de audio**; `GPT-Realtime-Whisper` (voz a texto en streaming) a 0,017 USD/min. Un modelo «mini» a 10/20 USD aparece en una fuente de terceros: **sin verificar**. (b) Propone SQLite WAL, pero la constitución de Jericó (D1) manda PostgreSQL 16 en producción. (c) Sus fuentes son anuncios de 2024; las marcas «verificado octubre 2026» no las pude confirmar una a una.

| Criterio | OpenAI (Realtime) | ElevenLabs |
|---|---|---|
| Costo | Audio 32/64 USD por 1M tokens (oficial); el costo por minuto depende de los tokens usados — **sin verificar** | TTS 0,04 USD por 1.000 caracteres (Flash/Turbo y v4 Turbo) a 0,08 (v4); agentes conversacionales 0,08 USD/min (página oficial) |
| Latencia | Informe: <300 ms (anuncio de 2024); **sin medir** | Página oficial: ~75 ms Flash/Turbo, ~100 ms v4 Turbo (solo síntesis, no ida y vuelta) |
| Español | **Sin verificar** calidad ni acento colombiano | La página no nombra el español; **sin verificar** |
| Arquitectura | Voz a voz en un solo modelo | Solo voz de salida; hay que sumar STT y LLM |
| Plan gratuito | No hay | «Free» existe, pero la página no dice cuánto incluye |

**Recomendación.** (1) A4.1 sin costo: notas de voz en Telegram con `faster-whisper` local (ya está en el repo) y respuesta de texto. (2) Antes de pagar nada, una **prueba ciega de 20 frases en español colombiano** con ambos (calidad, latencia medida, costo por minuto real) usando datos ficticios: solo con OK del CTO por ser servicio de pago. (3) Para venta por llamada en vivo, probable pipeline por turnos (STT local → LLM barato → TTS) por costo; voz a voz solo si la prueba muestra una diferencia que lo justifique. Ninguna cifra de esta tabla autoriza un gasto.

> 🕒 **Última modificación:** 13/10/2026 22:25 (Claude Code · Sonnet 5.5 · kai-jev)
