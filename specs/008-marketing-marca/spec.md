# Spec 008 — Marketing masivo y automatización de marca para Jericó (F5)

- **Estado:** BORRADOR para revisión del CTO (13/10/2026). Rama `marketing/f5-marca`. Sin código de producción desplegado.
- **Fuentes:**
  - Plan maestro de Jericó (`02_Proyectos/Jerico_Plan_Maestro.md`, §1, §2.9, §4, §6).
  - Manual de Marca Kaizen v1.0 (`04_Recursos/Marca/Manual_de_Marca_Kaizen.md`).
  - Guía de marca para agentes de Jericó (`docs/marca/GUIA_MARCA.md`).
  - Nota de arquitectura de marketing (`02_Proyectos/Marketing/Jerico_Marketing_Automatizado.md`).
  - Catálogo de activos reutilizables (`~/Kaisen_AI/01_Proyectos/Kaizen_Activos/CATALOGO.md`).
- **Numeración:** 008, bloqueada en §1 del Plan Maestro (001 ventas-crm · 002 jev-router · 003 servidor · 004 cierre-contrato · 005 asistente · 006 catálogo-precios · 007 jev-transversal · 008 marketing-marca).
- **Directiva del CTO (13/10/2026 22:22):** «Autorizo absolutamente todo; usar Jev para decidir y ahorrar tokens; el marketing con aprobación humana debe ser masivo».
- **Decisiones previas con Jev (13/10/2026):**
  - Canal WhatsApp: `cloud_api_oficial` (rechaza Evolution API por violación de términos y riesgo de baneo).
  - Modelo de redacción: `gpt-6-luna` (voz de cara al cliente y alineación de marca; `deepseek-chat` solo con datos seudonimizados).
  - Política de anuncios pagados: `dry_run_y_ok_cto` (nace en DRY_RUN, 0 USD de gasto sin OK explícito del CTO por campaña).
  - Origen de contenidos: `hibrido_con_hitl` (grabado por el fundador o asistido/generado con IA, siempre supervisado y aprobado por humano antes de emitir).

---

## 1. Problema

El CTO y el equipo comercial generan ideas estratégicas, guiones preliminares, reflexiones y piezas multimedia para posicionar la marca Kaizen y generar prospectos comerciales. Sin embargo:
1. No existe un pipeline automatizado que transforme una idea en bruto (audio de Telegram, texto rápido o borrador) en piezas estructuradas multicanal bajo las reglas canónicas del Manual de Marca Kaizen v1.0.
2. La difusión masiva manual es lenta y propensa a errores humanos (mezcla indebida de «tú» y «usted», uso obsoleto del nombre «Kaisen AI», afirmación de métricas no verificadas o descontrol de presupuesto).
3. El lanzamiento de campañas masivas por correo, WhatsApp y redes sociales (orgánicas y pagadas en Meta Ads) exige un control estricto de presupuesto Lean (10–25 USD/mes global para Jericó), cumplimiento de la Ley 1581 de 2012 y un mecanismo de **aprobación humana innegociable (Human-in-the-Loop)** antes de emitir cualquier mensaje o debitar saldo.

---

## 2. Alcance

### Dentro del Alcance
- **Ingesta de Ideas del CTO:** Recepción de notas de voz, textos breves o enlaces desde Telegram (`@Jericoo_bot`) o CLI.
- **Estructuración y Perfeccionamiento:** Clasificación en campañas canónicas (C1–C5), validación de tokens de marca, ajuste de tono por canal (Usted vs. Tú) y redacción con `gpt-6-luna`.
- **Canales Soportados:**
  1. *Correo electrónico masivo:* Integración vía Resend / Brevo / Cloudflare Email Routing con plantillas HTML minimalistas en tokens de marca.
  2. *WhatsApp masivo:* Exclusivamente vía **WhatsApp Business Cloud API oficial** de Meta mediante plantillas HSM (Template Messages) aprobadas.
  3. *Instagram y Facebook orgánico:* Generación de copies, carruseles y guiones 9:16 con formato de salida para publicación asistida o Meta Graph API.
  4. *Meta Ads (Campañas pagadas):* Creación de campañas y conjuntos de anuncios dirigidos a WhatsApp o web, con asignación estricta de presupuesto y `DRY_RUN`.
- **Guardarraíl de Aprobación Humana (HITL):** Notificación de vista previa completa por Telegram al CTO; ejecución bloqueada hasta recepción de comando `/aprobar <id_campaña>`.
- **Entorno Seguro `DRY_RUN`:** Modo simulado activo por defecto (`JERICO_EXTERNAL_COMMS_DRY_RUN=true`).
- **Idempotencia:** Llaves deterministas `idempotency_key` para cada despacho y transacción.
- **Integración con Activos:** Conexión con `Kaizen_Activos` (`ACT-CRM-01`, `ACT-CRM-04`, `ACT-IA-01`, `ACT-IA-03`, `ACT-CON-01`, `ACT-CON-02`, `ACT-CON-03`).

### Fuera del Alcance
- Publicar en redes o enviar mensajes a terceros de forma 100% autónoma sin visto bueno del CTO.
- Utilizar librerías no oficiales de WhatsApp (como Baileys, Evolution API, WhatsApp-web.js).
- Contratar tarjetas de crédito, pasarelas de pago o sobrepasar el presupuesto de 10–25 USD/mes sin autorización escrita del CTO.
- Generar avatares sintéticos o clones de voz no autorizados; el vocero principal en video es humano (Santiago González).

---

## 3. Requisitos del Sistema (EARS)

### Ingesta y Estructuración de Contenido
- **R1** WHEN el CTO envíe una idea o borrador (texto, nota de voz o enlace), el sistema SHALL registrar la idea con un identificador único `IDEA-<timestamp>-<hash>` y transcribir el audio (si aplica) mediante `whisper-large-v3-turbo` o transcripción local.
- **R2** El sistema SHALL categorizar la idea en una de las cinco campañas oficiales de Kaizen:
  - `C1`: Primero entendemos (Diagnóstico operativo / Solución).
  - `C2`: Del papel al sistema (Evolución / Radar de Vencimientos).
  - `C3`: Alguien responde (Integridad / Responsabilidad humana).
  - `C4`: Tus datos, bajo llave (Seguridad / Privacidad Ley 1581).
  - `C5`: Aquí crece quien construye (Mérito / Cultura y equipo).
- **R3** El sistema SHALL perfeccionar la idea generando variantes adaptadas a cada canal requerido utilizando el modelo `gpt-6-luna`.

### Reglas Inviolables de Marca
- **R4** El sistema SHALL verificar que todo texto generado use exclusivamente el nombre **Kaizen** (con Z, sin «AI») en texto corrido y **KAIZEN** en logotipo. IF el texto contiene «Kaisen», «Kaizen AI», «Kaizen.ai» o «KaizenAI», THEN el sistema SHALL rechazar la pieza y autocorregir antes de presentarla al humano.
- **R5** El sistema SHALL mantener un trato estrictamente uniforme sin mezclas: **Usted** para propuestas, LinkedIn y correos formales; **Tú** para Instagram, TikTok, guiones 9:16 y WhatsApp comercial.
- **R6** El sistema SHALL verificar que el tagline sea idéntico e invariable: *«Da el paso. Nosotros respondemos.»*
- **R7** El sistema SHALL rechazar terminantemente cualquier afirmación que contenga cifras no verificadas, clientes no autorizados o testimonios falsos; IF se requieren ejemplos, THEN SHALL marcarlos explícitamente como «ejemplo ilustrativo».
- **R8** El sistema SHALL validar que las piezas visuales o código CSS cumplan la proporción áurea de tokens (70% neutros: Noche `#14100C`, Papel `#FFFFFF`; 20% Óxido `#A8481F`; 10% apoyo) y prohíba el uso de `Óxido vivo` y `Oro` como color de texto sobre fondos claros.

### Canales de Difusión Masiva
- **R9** El sistema SHALL gestionar envíos masivos por correo electrónico a listas de prospectos verificados, inyectando enlace de baja voluntaria (opt-out) y dirección fiscal verificada.
- **R10** El sistema SHALL enviar mensajes masivos de WhatsApp **únicamente** a través de la Cloud API oficial de Meta, utilizando plantillas pre-aprobadas (HSM) para mensajes salientes (outbound) fuera de la ventana de 24 horas.
- **R11** El sistema SHALL generar guiones técnicos de video 9:16 (duración 25–45 s) con desglose de hook (0–5s), desarrollo (5–25s), llamado al método (25–35s) y outro con `outro_9x16.png`.

### Campañas Pagadas (Meta Ads) y Presupuesto
- **R12** WHEN se configure una campaña de anuncios pagados (Meta Ads / Click-to-WhatsApp), el sistema SHALL estructurar la campaña con objetivo `MESSAGES` o `OUTCOME_TRAFFIC`, delimitando el presupuesto diario en COP o USD.
- **R13** Toda campaña de Meta Ads SHALL crearse en estado `PAUSED` con presupuesto `gasto_autorizado_usd = 0.00`.
- **R14** El sistema SHALL NOT activar campañas en Meta Ads ni consumir saldo publicitario IF el gasto mensual proyectado de Jericó supera el límite presupuestal establecido en el Plan Maestro §6 (10–25 USD/mes) o IF no existe aprobación explícita del CTO con comando de autorización.

### Guardarraíl de Aprobación Humana (HITL) y DRY_RUN
- **R15** WHILE `JERICO_EXTERNAL_COMMS_DRY_RUN=true` (valor por defecto), el sistema SHALL simular todos los envíos (email, WhatsApp, posts, anuncios), redirigiendo la carga útil al bot de Telegram del CTO (`@Jericoo_bot`) o a un buzón de prueba.
- **R16** WHEN una campaña esté perfeccionada y haya superado el linter de marca, el sistema SHALL enviar una notificación a `@Jericoo_bot` con el resumen ejecutivo, vista previa del texto/anuncio, audiencia objetivo, costo estimado y comandos de acción: `/aprobar <id>` y `/rechazar <id> <motivo>`.
- **R17** El sistema SHALL ejecutar la difusión externa o activación publicitaria ONLY IF recibe el comando `/aprobar <id>` firmado por un usuario con rol `cto`.

### Idempotencia y Protección de Datos
- **R18** Cada acción de despacho o creación de anuncio SHALL requerir un `idempotency_key` determinista generado mediante SHA-256 (`id_campana + destinatario_o_adset + hash_contenido`).
- **R19** Los datos de contacto de prospectos para campañas SHALL almacenarse cifrados en base de datos (`ACT-CON-01`) y el sistema SHALL registrar la base legal de tratamiento bajo la Ley 1581 de 2012.

---

## 4. Arquitectura y Esquemas de Datos

### 4.1 Máquina de Estados de Campaña
```
[IDEA_INGESTADA]
       │
       ▼
[PERFECCIONADA_POR_JERICO]
       │
       ▼
[LINTER_MARCA_PASADO]
       │
       ▼
[ENVIADA_A_REVISION_HITL] ──(Rechazo: /rechazar)──► [ARCHIVADA / AJUSTADA]
       │
       ▼ (Aprobación: /aprobar del CTO)
[AUTORIZADA]
       │
       ▼
[DESPACHADA_DRY_RUN / REAL]
```

### 4.2 Modelo de Campaña (Pydantic / schemas/marketing.py)
```python
class CanalMarketing(str, Enum):
    CORREO = "correo"
    WHATSAPP_OFICIAL = "whatsapp_oficial"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    META_ADS = "meta_ads"

class CampanaMarketing(BaseModel):
    id: str  # CAMP-YYYYMMDD-XXXX
    nombre: str
    clasificacion_campana: str  # C1 a C5
    canal: CanalMarketing
    trato: str  # "tu" o "usted"
    copy_principal: str
    activo_multimedia_uri: Optional[str]
    presupuesto_estimado_usd: Decimal = Decimal("0.00")
    gasto_autorizado_usd: Decimal = Decimal("0.00")
    estado: str  # borrador, en_revision, aprobada, rechazada, ejecutada
    idempotency_key: str
    aprobado_por: Optional[str]
    fecha_aprobacion: Optional[datetime]
```

---

## 5. Decisiones Pendientes del CTO

1. **Meta Business Manager:** Confirmar cuándo el CTO enlazará la cuenta comercial de Facebook/Instagram y registrará la WhatsApp Business Cloud API con número verificado.
2. **Presupuesto Inicial de Pruebas Meta Ads:** Definir el monto de prueba para los primeros anuncios a WhatsApp (se sugiere rango Lean de 5 USD a 10 USD dentro del tope global de 25 USD/mes).
3. **Paso de DRY_RUN a Producción:** Jericó permanecerá en `JERICO_EXTERNAL_COMMS_DRY_RUN=true` hasta que el CTO emita orden explícita para el canal comercial.

---

## 6. Matriz de Riesgos y Mitigaciones

| Riesgo | Impacto | Mitigación Técnica en Spec 008 |
|---|---|---|
| Sobrecosto inesperado en Meta Ads | Crítico | Campañas nacen pausadas; tope presupuestal duro; activación solo con `/aprobar` y monto explícito (R12-R14). |
| Baneo de número telefónico por spam en WhatsApp | Crítico | Uso exclusivo de WhatsApp Cloud API oficial de Meta con plantillas HSM aprobadas y opt-out (R10). |
| Dilución de la identidad o uso de nombres obsoletos («Kaisen AI») | Medio | Linter algorítmico previo obligatorio que bloquea la presentación de piezas que no cumplan la guía de marca (R4). |
| Envío duplicado a prospectos | Medio | `idempotency_key` SHA-256 en motor de despacho (R18). |
| Infracción Ley 1581 por contacto no consentido | Alto | Base legal documentada, minimización y canal opt-out inmediato (R19). |

---
> 🕒 **Última modificación:** 13/10/2026 22:25 (Agente Antigravity · kz-marca · F5)
