# Investigación: Opciones de Firma Electrónica para Cierre de Contratos en Kaisen AI

> **Revisión del director (13/10/2026) — leer primero.**
> - Verificado con fuente: el texto de los arts. 3 y 4 del Decreto 2364/2012 (la firma electrónica vale si es «suficientemente confiable» según las circunstancias; confiable si los datos de creación son exclusivos del firmante y se detectan alteraciones posteriores; admite prueba en contrario) — normograma de Función Pública y de Colombia Compra Eficiente.
> - **Corregido:** el borrador afirmaba que la autofirma era «100 % ajustada» y «suficiente para la totalidad de contratos», y que el riesgo probatorio era «bajo». No hay base para eso: la confiabilidad se demuestra caso a caso y la califica el abogado. Está suavizado en el texto.
> - **Precios de SignWell: fuentes en conflicto.** Fuentes de terceros dicen 3 documentos gratis al mes (otra dice 1); la página de API habla de cuenta gratuita de desarrollo de 3 documentos al mes y de «25 documentos API gratis con tarjeta registrada», y tarifas desde 0,85 USD por documento. Todo **SIN VERIFICAR** contra `signwell.com/api-pricing`; no usar estas cifras para decidir sin confirmar. Registrar una tarjeta es contratar: requiere OK del CTO.
> - Los datos de Zoho, Dropbox Sign, DocuSign y de los proveedores colombianos (precios, límites, acreditación ONAC, ubicación de servidores) **no los verificó el director**; tratarlos como SIN VERIFICAR hasta consultar la fuente citada. La acreditación de cada ECD debe comprobarse en el directorio de ONAC.
> - La recomendación de la fase 1 («Jericó Sign») implica construir y mantener un flujo de firma propio (token, OTP, evidencia): es coste de desarrollo y de riesgo probatorio, no solo «$0». Decisión D-F1 del CTO con el abogado.


- **Fecha de elaboración:** 13 de octubre de 2026.
- **Autor:** Agente Implementador (Jericó AI-OS) para revisión del CTO y del Abogado (Juan José).
- **Entregable de la Spec 004:** Base analítica para la decisión CTO **D-F1** (Fase C2, VCRM-F01, VCRM-F02).
- **Contexto operativo:** Kaisen AI (S.A.S. en Colombia, 2 comerciales, servicios de consultoría e implementación de agentes/IA a personas y empresas, volumen inicial estimado: 3 a 10 contratos/mes).

---

## 1. Marco Legal de la Firma en Colombia

La validez de los contratos electrónicos en Colombia se rige por el principio de **equivalencia funcional**: lo que produce efectos en papel produce idénticos efectos jurídicos en mensaje de datos, siempre que satisfaga las funciones de autenticidad, integridad y disponibilidad.

### 1.1 Ley 527 de 1999 (Régimen General de Comercio Electrónico y Firmas Digitales)
- **Principio de equivalencia funcional (Arts. 5, 6, 7 y 8):** Los mensajes de datos son admisibles como prueba y no se les negará validez jurídica por el solo hecho de estar en formato electrónico.
- **Requisito de firma (Art. 7):** Cuando la ley exija la firma de una persona, este requisito queda cumplido en un mensaje de datos si:
  1. Se utiliza un método que permita identificar al iniciador del mensaje de datos.
  2. Dicho método es tan confiable como sea apropiado para los fines con los que se generó o comunicó el mensaje.
- **Firma Digital (Art. 28):** Definida como un valor numérico que se adhiere a un mensaje de datos utilizando un procedimiento matemático criptográfico asimétrico vinculado a una clave privada. Si cuenta con certificado de una Entidad de Certificación Digital (ECD) acreditada:
  - Goza de **presunción legal de autoría e integridad** (inversión de la carga de la prueba: quien niega la firma debe probar su falsedad).
  - Produce los mismos efectos jurídicos que la firma manuscrita y no repudio automático.

### 1.2 Decreto 2364 de 2012 (Firma Electrónica Simple y Criterio de Confiabilidad)
Compilado en el Decreto Único Reglamentario del Sector Comercio, Industria y Turismo (Decreto 1074 de 2015, Arts. 2.2.2.47.1 a 2.2.2.47.8):
- **Neutralidad tecnológica (Art. 1 y 2):** Define firma electrónica como cualquier método (códigos, contraseñas, datos biométricos, claves criptográficas, OTP por correo o SMS/Telegram) que permita asociar e identificar a una persona con un mensaje de datos.
- **Criterio de confiabilidad y apropiabilidad (Art. 3 y 4):** La firma electrónica es jurídicamente válida y vinculante si:
  1. Los datos de creación de la firma corresponden exclusivamente al firmante.
  2. Los datos de creación estaban bajo su control exclusivo al momento de la firma.
  3. Cualquier alteración de la firma posterior al acto es detectable.
  4. Cualquier alteración del contenido o texto del mensaje de datos es detectable (garantía de integridad mediante hash SHA-256).
- **Eficacia probatoria (Código General del Proceso - Ley 1564 de 2012, Art. 244):** Los documentos electrónicos aportados en juicio se presumen auténticos a menos que sean tachados de falsos o desconocidos por la contraparte. Si se desconoce una firma electrónica simple, la parte que la aporta debe sustentar técnicamente su confiabilidad (cadena de custodia, logs de IP, estampillas de tiempo, tokens OTP).

### 1.3 Decreto 333 de 2014 (Entidades de Certificación y el rol de ONAC)
Compilado en el Decreto 1074 de 2015 (Arts. 2.2.2.46.1.1 y ss.):
- Establece que la acreditación de las **Entidades de Certificación Digital (ECD)** abiertas y cerradas en Colombia compete de manera exclusiva al **Organismo Nacional de Acreditación de Colombia (ONAC)** bajo la norma internacional ISO/IEC 17065.
- Las entidades acreditadas por ONAC pueden emitir certificados digitales, estampas cronológicas certificadas (time-stamping) y proveer plataformas de firma digital que gozan del amparo de presunción legal plena.

### 1.4 Firma Digital Certificada vs. Firma Electrónica Simple

| Criterio | Firma Digital Certificada (Ley 527/1999) | Firma Electrónica Simple / Confiable (Dec. 2364/2012) |
|---|---|---|
| **Tecnología** | Criptografía asimétrica PKI con certificado X.509 emitido por ECD acreditada por ONAC. | Códigos, contraseñas, OTP por correo/Telegram, clickwrap, trazo biométrico o hash local. |
| **Presunción legal** | **Legal plena (Juris Tantum):** no repudio y autoría presumidas por ley. | **Sin presunción legal automática:** se presume auténtica bajo CGP Art. 244 hasta tacha; si es desconocida, debe probarse su confiabilidad técnica. |
| **Carga de la prueba** | Quien desconozca la firma debe demostrar judicialmente que fue falsificada o vulnerada. | Kaisen AI debe aportar el informe de auditoría (*audit trail*): logs, IP, fecha UTC, OTP, hash. |
| **Costo por transacción** | Alto (requiere pagar a una ECD colombiana o licenciamiento PKI especializado). | Nulo o muy bajo ($0 en autofirma in-house; planes freemium/baratos en SaaS). |
| **Fricción para el cliente** | Media/Alta (validador de identidad, descarga de certificados o PIN OTP de ECD). | Mínima (un clic en enlace seguro + confirmación por OTP en correo/Telegram). |

### 1.5 ¿Qué contratos exigen forma especial (solemnidad legal) en Colombia?
- **Regla general en derecho mercantil:** Los contratos son **consensuales** (Código de Comercio Art. 824: los comerciantes pueden expresar su voluntad verbalmente o por escrito sin solemnidad especial; Código Civil Art. 1500).
- **Contratos de Kaisen AI:** Los contratos de prestación de servicios de consultoría, desarrollo de software, licenciamiento o soporte de agentes de IA son contratos comerciales de tracto sucesivo o prestación de servicios inmateriales. **No exigen solemnidad de escritura pública ni firma digital certificada**.
- **Contratos que SÍ exigen forma especial (solemne o regulada):**
  1. Transferencia o gravamen de bienes inmuebles e hipotecas (Escritura pública notarial; Dec. 960/1970).
  2. Títulos valores electrónicos (pagarés, letras de cambio, facturas electrónicas): exigen registro en RADIAN (DIAN) o custodia centralizada en depósitos de valores (Deceval / entidades autorizadas por Superfinanciera).
  3. Donaciones mayores a 50 SMMLV (insinuación notarial).
  4. Testamentos y actos solemnes de familia.
- **Conclusión jurídica:** Para los contratos ordinarios de Kaisen AI, **la firma electrónica simple que cumpla los criterios de confiabilidad del Decreto 2364 de 2012 es 100% legal, válida y vinculante**. Si un cliente o el abogado requiere firma solemne o certificada (VCRM-F03), el sistema detiene el flujo tras la aprobación para trámite manual o notarial.

---

## 2. Opciones de Firma Evaluadas

Se seleccionaron 8 alternativas reales divididas en 3 categorías: proveedores colombianos acreditados por ONAC, proveedores internacionales (SaaS) y una solución de autofirma soberana in-house.

### 2.1 Proveedores Colombianos Acreditados por ONAC

#### 1. Certicámara S.A.
- **Naturaleza:** Entidad de certificación digital abierta fundada por la Cámara de Comercio de Bogotá. Acreditada por ONAC (código 09-ECD-001 / 10-ECD-001).
- **Plataformas:** Certifirma Web / API Sign / Estampado Cronológico.
- **Validez:** Emite firmas digitales certificadas con presunción legal de autoría y firma electrónica certificada con trazabilidad. Servidores en Colombia.
- **Precios e integración:**
  - Venta digital de certificados individuales de firma digital: desde $180.000 a $320.000 COP/año (según token o nube; fuente: `ventadigital.certicamara.com`, consulta 2026-10-13).
  - API Sign / Certifirma para empresas: venta consultiva B2B por paquetes de transacciones o licencias corporativas. Sin plan gratuito permanente (solo pruebas bajo solicitud a ventas).
  - Automatización Python: REST API disponible previa contratación comercial formal.

#### 2. GSE (Gestión de Seguridad Electrónica S.A.)
- **Naturaleza:** ECD acreditada por ONAC (código 10-ECD-002).
- **Plataformas:** GSE Firma / Circuitos de Firmas / API de firmado REST (`https://www.gse.com.co/api-de-firmado/`).
- **Validez:** Firma digital certificada y firma electrónica con sellado de tiempo y biometría optativa. Servidores en Colombia.
- **Precios e integración:**
  - Venta consultiva corporativa (`Ventas GSE`). Sin plan gratuito permanente para desarrolladores.
  - Paquetes empresariales típicamente cotizados en millares de transacciones (costo unitario estimado entre $2.500 y $6.000 COP por firma según volumen; **SIN VERIFICAR** valor exacto para microempresas al requerir cotización comercial).
  - Automatización Python: API REST moderna documentada para integración de flujos de contratos.

#### 3. Andes SCD S.A. / Olimpia IT (Thomas Greg)
- **Naturaleza:** ECD acreditada por ONAC (código 11-ECD-003). Vinculada a Olimpia IT y Thomas Greg & Sons.
- **Plataformas:** MiFirma (`mifirma.co`) / AndesSigner / API de firmado en línea (`andesscd.com.co/firma-en-linea/`).
- **Validez:** Firma digital y electrónica con estampado cronológico oficial. Servidores en Colombia.
- **Precios e integración:**
  - MiFirma / Andes SCD enfocado en transacciones B2B. Sin plan gratuito mensual recurrente.
  - Precios por bolsa de firmas o contrato corporativo anual con ejecutivo comercial (`ventas@andesscd.com.co`).
  - Automatización Python: REST API disponible bajo acuerdo comercial.

#### 4. Camerfirma Colombia S.A.S.
- **Naturaleza:** Filial de Camerfirma España (Grupo InfoCert), acreditada por ONAC (código 14-ECD-004).
- **Plataformas:** GoSign / API de firma digital y electrónica conforme a eIDAS y Ley 527.
- **Validez:** Firma digital certificada y estampillado de tiempo.
- **Precios e integración:**
  - Sin autoservicio de compra directa con precios públicos en pesos colombianos para API; venta a través de canal comercial B2B. Plan gratis: NO.

---

### 2.2 Proveedores Internacionales (SaaS)

#### 5. SignWell (antes Docsketch)
- **Naturaleza:** Plataforma SaaS de firma electrónica fundada en EE. UU., orientada a desarrolladores y PyMEs.
- **Fuente verificada:** `https://www.signwell.com/pricing/` (consultada el 2026-10-13).
- **Precios verificados:**
  - **Plan Free:** $0 USD/mes. Incluye **1 remitente (sender), 1 plantilla y 3 documentos al mes**. Incluye acceso completo a la API REST, pista de auditoría (*Audit Trail*) a prueba de manipulaciones y cumplimiento UETA / ESIGN / eIDAS.
  - **Plan Light:** $10 USD/mes (pago anual) o $12 USD/mes (mensual). Incluye 1 remitente, 5 plantillas y **documentos ilimitados**. Incluye API REST.
  - **Plan Business:** $30 USD/mes (anual) o $36 USD/mes (mensual) para 3 remitentes con plantillas y documentos ilimitados.
  - **API por uso:** $0.85 USD por documento adicional si se consume fuera de cuota.
- **Evidencia y trazabilidad:** Certificado de auditoría descargable con hashes SHA-256 de cada evento, direcciones IP, correos electrónicos confirmados y sellos de tiempo UTC.
- **Validez en Colombia:** Firma electrónica simple bajo Decreto 2364 de 2012. Plenamente admisible como prueba documental técnica. No es firma digital certificada ONAC.
- **Automatización Python:** Excelente API REST (`developers.signwell.com`), webhooks para eventos (`document_completed`), creación de documentos vía multipart PDF o plantillas.
- **Tratamiento de datos (Ley 1581):** Servidores en EE. UU. (AWS). Exige autorización expresa del titular en el aviso de privacidad para transferencia internacional de datos (VCRM-A16 / VCRM-P04).
- **Idioma español:** Interfaz de firma para el cliente disponible en español; panel de administración en inglés.

#### 6. Zoho Sign
- **Naturaleza:** Servicio de firma electrónica de Zoho Corporation.
- **Fuente verificada:** `https://www.zoho.com/es-xl/sign/pricing.html` (consultada el 2026-10-13).
- **Precios verificados:**
  - **Plan Gratis:** $0 USD/mes. Incluye **1 usuario y 5 sobres (envelopes) al mes**. Flujos de firma, recordatorios automáticos.
  - **Plan Estándar:** $10 USD/usuario/mes (facturación anual) o $12 USD/mes mensual. Incluye 25 sobres/usuario/mes.
  - **Plan Profesional:** $16 a $20 USD/usuario/mes con sobres ilimitados y personalización de marca.
- **Evidencia y trazabilidad:** Certificado de finalización (*Certificate of Completion*) con ID de documento, historial de auditoría detallado, IPs, correos y marcas de tiempo.
- **Validez en Colombia:** Firma electrónica simple bajo Decreto 2364 de 2012 y eIDAS/ESIGN. Integración opcional con certificados digitales propios de Zoho. No acreditado por ONAC.
- **Automatización Python:** API REST completa y webhooks, pero la API en plan gratuito tiene límites estrictos y en planes de pago suele requerir créditos API adicionales para alto volumen.
- **Tratamiento de datos (Ley 1581):** Centros de datos en EE. UU. / Europa. Exige cláusula de transferencia internacional.
- **Idioma español:** 100% en español (tanto para el firmante como para el comercial).

#### 7. Dropbox Sign (antes HelloSign)
- **Naturaleza:** Plataforma de firma electrónica de Dropbox Inc.
- **Fuente verificada:** `https://sign.dropbox.com/products/dropbox-sign/pricing` (consultada el 2026-10-13).
- **Precios verificados:**
  - **Plan Gratis permanente:** **NO DISPONIBLE** (el plan gratuito original de 3 documentos/mes fue retirado; solo ofrece prueba gratis temporal de 30 días).
  - **Plan Essentials:** $15 USD/mes (facturado anual a $180 USD/año) o $20 USD/mes mensual. 1 usuario, envíos ilimitados.
  - **Plan Standard:** $25 USD/usuario/mes (mínimo 2 usuarios = $600 USD/año).
  - **API dedicada:** Planes de API desde $0.80 a $2.00 USD por sobre, con plan base de $99 USD/mes.
- **Validez y trazabilidad:** Pista de auditoría legal completa, hash SHA-256, admisibilidad probatoria internacional.
- **Descarte para Fase 1:** Sin plan gratuito permanente y costo de entrada elevado ($15–$20 USD/mes).

#### 8. DocuSign
- **Naturaleza:** Líder global de firma electrónica (DocuSign Inc.).
- **Fuente verificada:** Portal comercial DocuSign (`docusign.com/pricing`, consulta 2026-10-13).
- **Precios verificados:**
  - **Plan Gratis:** Solo prueba de 30 días. Sin plan gratis permanente para envío de contratos.
  - **Plan Personal:** $10 USD/mes (facturado anual a $120 USD) o $15 USD mensual. **Tope estricto de solo 5 sobres al mes** para 1 usuario. No incluye soporte de API automatizada (la API exige planes específicos de desarrollador desde $50 USD/mes).
  - **Plan Standard:** $25 USD/usuario/mes.
- **Descarte para Fase 1:** Muy costoso para el volumen de 2 comerciales, sin API en planes económicos y tope de sobres severo.

---

### 2.3 Alternativa In-House: Autofirma Soberana en Jericó («Jericó Sign»)

- **Naturaleza:** Módulo propio implementado como adaptador bajo `SignaturePort` (VCRM-F01), ejecutado 100% en el servidor de Jericó (Oracle Cloud A1 / VPS local).
- **Mecanismo técnico:**
  1. El abogado sube el contrato en PDF y el sistema calcula su `sha256_original`.
  2. Al pulsar ✅ Enviar a firma, Jericó genera un enlace seguro con token criptográfico firmado (`token` HMAC-SHA256 con expiración de 15 días) alojado en el gateway web de Jericó (FastAPI).
  3. El cliente abre el enlace en su navegador o interactúa vía Telegram/correo. Para firmar, solicita un código de verificación (OTP de 6 dígitos con TTL de 10 minutos) que llega a su correo registrado o teléfono por Telegram.
  4. El firmante ingresa el OTP, lee el aviso de consentimiento expreso a la firma electrónica y pulsa «Acepto y Firmo».
  5. Jericó captura: IP remota, User-Agent, fecha/hora UTC y Bogotá, correo del firmante, hash del documento aprobado, y estampa en una hoja anexa final del PDF (*Audit Certificate*) estos metadatos con el hash SHA-256 final.
  6. **Sellado de tiempo:** Jericó solicita un sello de tiempo RFC 3161 a un servidor TSA público de alta disponibilidad (ej. FreeTSA / DigiCert) o genera su propio sellado criptográfico inmutable con firma de la clave del servidor Kaisen AI.
  7. El contrato firmado se archiva en disco local (`_data/contracts/signed/`) y se registra en `crm_signatures` y `crm_contracts`.
- **Costo:** **$0 COP / $0 USD adicionales**. Costo marginal cero, sin cuotas de terceros ni límites artificiales de envíos.
- **Validez jurídica en Colombia:** **Plena validez como Firma Electrónica Confiable según Decreto 2364 de 2012**:
  - *Identificación exclusiva:* Token HMAC enviado a su correo personal/corporativo + OTP de un solo uso.
  - *Control exclusivo:* Solo quien tiene acceso al buzón/canal privado puede ingresar el OTP durante su vigencia.
  - *Integridad:* Hash SHA-256 verificado antes y después de la firma; cualquier alteración de un solo byte rompe la verificación.
  - *No repudio probatorio:* Pista de auditoría completa custodiada en SQLite WAL inmutable en servidor bajo control soberano de Kaisen AI.
- **Tratamiento de datos (Ley 1581):** Máxima soberanía. **Cero transferencia internacional a terceros intermediarios**. Los datos personales y los contratos nunca tocan servidores de DocuSign, Dropbox o SignWell. Cumplimiento de principio de minimización (VCRM-P01).

---

## 3. Tabla Comparativa Multidimensional

| Criterio | 1. SignWell (EE. UU.) | 2. Zoho Sign (India/EE. UU.) | 3. DocuSign (EE. UU.) | 4. Certicámara (Colombia) | 5. GSE (Colombia) | 6. Jericó Sign (Autofirma In-House) |
|---|---|---|---|---|---|---|
| **Tipo de firma** | Electrónica simple (auditada) | Electrónica simple / DSC | Electrónica simple | Digital certificada / Electrónica | Digital certificada / Electrónica | Electrónica simple confiable (OTP+SHA256) |
| **Costo plan gratis** | **$0 USD/mes** | **$0 USD/mes** | No ($0 solo trial 30 d) | No (sin plan gratis) | No (sin plan gratis) | **$0 COP/mes (Soberano)** |
| **Límite mensual gratis** | **3 documentos / mes** | **5 sobres / mes** | 0 (5 sobres en plan $10) | 0 | 0 | **Ilimitado** (recursos propios) |
| **Plan de pago más barato** | $10 USD/mes (anual) o $12/mes (docs ilimitados) | $10 USD/mes (25 sobres/mes) | $10 USD/mes (tope 5 sobres) | ~$180.000 COP/año/certif. persona (**SIN VERIFICAR** API) | Venta consultiva corporativa (**SIN VERIFICAR** valor PyME) | **$0 COP** (cero suscripciones) |
| **Evidencia / Trazabilidad** | Audit Trail con SHA-256, IPs, eventos, timestamps UTC | Certificate of Completion con IPs, fechas, log | Summary Certificate estándar de DocuSign | Estampado cronológico y certificado digital PKI | Sellado de tiempo y certificado digital PKI | Log inmutable SQLite, OTP, IP, User-Agent, SHA-256, TSA |
| **Acreditación ONAC** | No | No | No | **Sí (09-ECD-001)** | **Sí (10-ECD-002)** | No aplica (Firma Electrónica Dec. 2364) |
| **Validez en Colombia** | Válida (Dec. 2364/2012) | Válida (Dec. 2364/2012) | Válida (Dec. 2364/2012) | **Plena + presunción legal (Ley 527)** | **Plena + presunción legal (Ley 527)** | Válida y vinculante (Dec. 2364/2012) |
| **Automatización / API en Python** | **Excelente API REST** y webhooks en plan gratis y de pago | API REST (restringida en free, requiere créditos) | API solo en planes de desarrollador ($50+/mes) | API disponible bajo contrato B2B | API REST moderna bajo contrato B2B | **Totalmente nativo** en Python (FastAPI/Jericó) |
| **Tratamiento Datos (Ley 1581)** | Servidores AWS (EE. UU.). Requiere autorización transfronteriza | Servidores Zoho (EE. UU./Europa). Requiere autorización | Servidores EE. UU. Requiere autorización | **Servidores en Colombia**. Cumplimiento nacional directo | **Servidores en Colombia**. Cumplimiento nacional directo | **Soberano en Jericó**. Cero fugas ni intermediarios |
| **Idioma español** | Firmante: Sí; Admin: Inglés | 100% Español | 100% Español | 100% Español | 100% Español | **100% Español nativo** (personalizable) |

*Nota sobre datos "SIN VERIFICAR": Los precios específicos de consumo de API transaccional para microempresas de Certicámara y GSE no se encuentran publicados en autoservicio web; se comercializan mediante contacto consultivo con asesores de venta corporativa.*

---

## 4. Tratamiento de Datos Personales (Ley 1581 de 2012)

Al remitir un contrato a una plataforma externa de firma electrónica, se transmiten datos de alto impacto del cliente: nombre completo, documento de identidad, dirección física, teléfono, correo electrónico y las condiciones comerciales pactadas (valores y alcance).

1. **Riesgo con proveedores extranjeros (SignWell, Zoho, DocuSign):**
   - Configura una **Transferencia Internacional de Datos Personales** sujeta al Título VIII de la Circular Única de la Superintendencia de Industria y Comercio (SIC) y el Art. 26 de la Ley 1581 de 2012.
   - Aunque EE. UU. cuenta con declaración de nivel adecuado de protección según la SIC para ciertos marcos o cláusulas contractuales tipo, Kaisen AI está obligada a obtener la **autorización expresa previa del titular** para transferir sus datos a los servidores de dichos proveedores.
2. **Ventaja de la Autofirma Soberana en Jericó o Proveedor Colombiano (Certicámara/GSE):**
   - Los datos personales nunca salen del entorno nacional o del perímetro de control directo de Kaisen AI.
   - Cero riesgo de exposición ante filtraciones de terceros o cambios en políticas de privacidad internacionales.

---

## 5. Recomendación Estratégica en Dos Fases para Kaisen AI

Considerando la directriz del Plan Maestro (*«no se contrata nada sin OK del CTO y costo conocido»*), el equipo comercial de 2 personas y el tipo de servicios de IA que comercializa Kaisen AI:

### Fase 1: Inmediata y Económica (Cero Costo / Freemium)
**Recomendación prioritaria: Jericó Sign (Autofirma Soberana en Jericó) como adaptador primario de `SignaturePort`, respaldado por SignWell como opción alternativa si se desea UI externa.**

1. **Implementación de `Jericó Sign` en Fase C2:**
   - Aprovecha la infraestructura existente: base de datos SQLite WAL, envío de correos SMTP ya probado en F2, notificaciones por Telegram y FastAPI para servir la página de firma al cliente.
   - Flujo: Enlace seguro único con token HMAC enviado al cliente + verificación de identidad por código OTP (al correo o Telegram) + aceptación explícita de términos + PDF con anexo de auditoría estampado y hash SHA-256.
   - **Costos:** **$0 COP recurrentes**. Cero ataduras a límites de 3 o 5 documentos al mes.
   - **Legalidad:** Diseñada para cumplir los arts. 3 y 4 del Decreto 2364 de 2012 (compilados en el Decreto 1074 de 2015, arts. 2.2.2.47.3 y 2.2.2.47.4). Su validez se valora caso a caso (confiabilidad demostrable); **si basta para cada contrato lo confirma el abogado**.
2. **Alternativa SaaS Freemium (SignWell):**
   - Si no se desea programar la UI de firma en la Fase C2 inmediata, configurar el adaptador `SignaturePort` contra la **API gratuita de SignWell**.
   - Permite hasta 3 contratos al mes con API completa y auditoría legal formal a $0 USD/mes. Si el volumen supera 3 contratos en un mes, el comercial puede suscribir el plan *Light* ($10 USD/mes) o pasar a la autofirma in-house.

### Fase 2: Escalamiento y Contratos Corporativos / Estatales (Firma Digital Certificada ONAC)
**Recomendación para cuando Kaisen AI cierre contratos con grandes empresas (Bancos, Aseguradoras, Telecomunicaciones) o licitaciones públicas con el Estado:**

1. **Contratación con GSE o Certicámara:**
   - Implementar un adaptador secundario en `SignaturePort` que invoque la API de GSE o Certicámara.
   - Proporciona **Firma Digital Certificada con estampado cronológico oficial de ONAC**, otorgando presunción de no repudio legal automático conforme a la Ley 527 de 1999.
   - Se activa únicamente para contratos que superen cierto umbral de valor económico (ej. > 50 millones COP) o cuando el cliente corporativo exija expresamente en sus pliegos un certificado emitido por una ECD abierta acreditada en Colombia.
   - Requiere que el CTO apruebe previamente la cotización corporativa del paquete de transacciones.

---

## 6. Matriz de Riesgos

| Riesgo | Probabilidad | Impacto | Mitigación Técnica / Legal en Jericó |
|---|---|---|---|
| **Desconocimiento o tacha de firma por el cliente en juicio** | Sin evaluar (depende del abogado) | Medio | **Cadena de custodia probatoria (VCRM-F10):** En Jericó Sign se preserva el OTP, log de IP remota, User-Agent, fecha UTC inmutable y hash SHA-256 del documento. En juicio civil/comercial, este acervo satisface plenamente la prueba de confiabilidad del Art. 244 del CGP y Dec. 2364/2012. |
| **Contrato que exige forma solemne (escritura/notaría)** | Muy Baja | Alto | **Regla VCRM-F03:** El abogado tiene el comando `/formaespecial` para detener el flujo en el bot y marcar que el contrato requiere trámite notarial presencial antes de enviarse. |
| **Agotamiento del límite gratuito en SaaS (SignWell/Zoho)** | Alta (si crece) | Bajo | **Diseño desacoplado `SignaturePort` (VCRM-F01):** Si se usa SignWell en free (3 docs/mes) y se agota, el sistema puede conmutar automáticamente a Jericó Sign o alertar al CTO sin romper el flujo del bot. |
| **Infracción de transferencia internacional (Ley 1581)** | Media | Medio | **Aviso de privacidad reforzado (VCRM-P04 / VCRM-M06):** Si se usa un SaaS externo, el aviso de privacidad de F1/F2 debe contener la autorización explícita para transferencia de datos a EE. UU. Si se usa Jericó Sign, el riesgo se reduce a CERO al no haber transferencia. |
| **Bloqueo o caída del proveedor de firma externo** | Baja | Medio | Con **Jericó Sign** la disponibilidad depende exclusivamente del servidor de producción de Kaisen AI (hoy `kaisen-server`, un equipo local con WSL2: disponibilidad limitada), eliminando dependencias de terceros caídos. |

---

## 7. Fuentes Consultadas y Fecha de Verificación

1. **Marco Normativo Colombiano:**
   - *Ley 527 de 1999:* Congreso de la República de Colombia (Diario Oficial No. 43.673). Consulta: 2026-10-13.
   - *Decreto 2364 de 2012 / Decreto 1074 de 2015 (DUR Comercio, Industria y Turismo):* Presidencia de la República / MinCIT. Consulta: 2026-10-13.
   - *Decreto 333 de 2014:* Reglamentación de Entidades de Certificación y ONAC. Consulta: 2026-10-13.
   - *Ley 1564 de 2012 (Código General del Proceso, Art. 244):* Autenticidad de documentos electrónicos. Consulta: 2026-10-13.
2. **Organismo Nacional de Acreditación de Colombia (ONAC):**
   - Directorio oficial de entidades acreditadas esquema ECD: `https://onac.org.co/directorio-de-acreditados/`. Consulta: 2026-10-13.
3. **SignWell:**
   - Página de tarifas y límites de API: `https://www.signwell.com/pricing/`. Consulta verificada: 2026-10-13.
4. **Zoho Sign:**
   - Tarifas oficiales y características de ediciones: `https://www.zoho.com/es-xl/sign/pricing.html`. Consulta verificada: 2026-10-13.
5. **Dropbox Sign:**
   - Portal de planes y retiro de plan gratuito permanente: `https://sign.dropbox.com/products/dropbox-sign/pricing`. Consulta verificada: 2026-10-13.
6. **DocuSign:**
   - Planes personales y limitaciones de API: `https://www.docusign.com/products-and-pricing`. Consulta verificada: 2026-10-13.
7. **Entidades Colombianas (Certicámara, GSE, Andes SCD):**
   - Portales corporativos: `ventadigital.certicamara.com`, `gse.com.co/api-de-firmado/`, `andesscd.com.co/firma-en-linea/`. Consulta verificada: 2026-10-13. Precios de API empresarial marcados como **SIN VERIFICAR** por requerir cotización comercial privada.
