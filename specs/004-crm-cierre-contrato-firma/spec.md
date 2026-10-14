# Spec 004 — CRM: cierre de venta → abogado → contrato → firma; correo por niveles; rol abogado

- **Estado:** BORRADOR para revisión del CTO. **No se implementa nada hasta su OK** (instrucción del Plan Maestro, frente F2).
- **Rama:** `crm/spec-cierre-contrato-firma` (desde `crm/asistente-comercial-llm`, HEAD `d0aeab3`).
- **Número:** 004 y no 003 a propósito: existe un conflicto conocido entre `002-servidor-kaisen` y `002-jev-router-sombra` y una de las dos se renumerará a 003.
- **Relación con la spec 001:** extiende la línea «CRM operativo de ventas». Sustituye el alcance de F3 (HU-D2: «borrador del contrato desde plantilla») por una versión más amplia; reutiliza el rol abogado, el estado «aceptado» y la alerta de cierre de F1 (VCRM-156), el gate ✅/❌, el correo saliente/entrante de F2 y la bitácora. Prefijos nuevos: `VCRM-C` (cierre/contrato), `VCRM-F` (firma), `VCRM-M` (correo por niveles), `VCRM-R` (rol abogado), `VCRM-P` (datos personales).
- **Visión del CTO (Plan Maestro, 13/10/2026):** al cerrar una venta Jericó arma el paquete con todo lo ofertado y lo envía al abogado por Telegram o correo; el abogado genera el contrato y se firma electrónicamente. Cada comercial ve solo su buzón; el CTO ve todos; los leads entran por el buzón del comercial.

## 1. Alcance
Entra: (A) paquete de cierre, entrega al abogado, seguimiento del contrato y envío a firma; (B) buzones por comercial con visibilidad por niveles y entrada de leads por correo; (C) ampliación del rol abogado en el bot; (D) tratamiento de datos personales de todo lo anterior.
Fuera de alcance: contratar ningún servicio de pago; redactar el texto del contrato (lo hace el abogado); generar contratos con IA; facturación; marketing y voz (otros frentes); integrar el buscador de precios del frente F6 (se deja el punto de enganche, §4.3).

## 2. Actores
CTO (Santiago Gonzalez); comercial (Duván; se esperan 2); abogado (Juan José, externo); cliente (titular de los datos, sin acceso al bot). Un panel de apoyo (Gemini) no es actor del sistema.

## 3. Flujo de punta a punta
1. El comercial acepta el lead (estado «aceptado», ya existe). 2. El sistema arma el **paquete de cierre** (§4). 3. El comercial lo confirma con ✅/❌ (el paquete lleva datos del cliente: nada sale sin confirmación). 4. Se entrega al abogado por Telegram y/o correo (§6). 5. El abogado prepara el contrato **fuera** del sistema y lo sube al bot. 6. El comercial o el CTO aprueban con ✅/❌ el envío a firma (sale al cliente: gate obligatorio). 7. El cliente firma electrónicamente (§5). 8. La evidencia de firma se archiva y el CTO o el abogado marcan «ganado» (existente, VCRM-115).

## 4. Paquete de cierre
**4.1 Contenido (minimizado, VCRM-P01).** Datos del handoff ya validados en F1 (tipo de cliente, nombre o razón social, documento, representante legal, contacto, servicio, valor, plazo) **más** la oferta: líneas de servicio (descripción, cantidad, precio unitario, moneda), descuentos, forma de pago, vigencia de la oferta, condiciones especiales y supuestos. No incluye notas libres del lead, historial de conversación ni el contenido de los correos, salvo que el comercial adjunte expresamente un archivo.
**4.2 Requisitos**
- **VCRM-C01** CUANDO un lead pasa a «aceptado», EL SISTEMA propone al comercial armar el paquete y le pide los datos de oferta que falten, un campo por mensaje y con ejemplo (como el handoff de F1).
- **VCRM-C02** EL SISTEMA no genera el paquete mientras falte algún campo obligatorio del handoff o de la oferta; informa cuáles faltan.
- **VCRM-C03** CUANDO el paquete está completo, EL SISTEMA lo presenta al comercial (o al CTO si el lead no tiene comercial) con ✅ Enviar al abogado / ✏️ Editar / ❌ Cancelar; sin ✅ no sale nada.
- **VCRM-C04** EL SISTEMA versiona el paquete: toda edición posterior al envío crea una versión nueva, avisa al abogado y exige nueva confirmación; el contrato queda ligado a una versión.
- **VCRM-C05** EL SISTEMA registra en la bitácora (códigos cerrados, sin texto libre) la creación, envío, edición y cancelación del paquete.
**4.3 Precios.** El importe lo escribe el comercial. [DECISIÓN CTO D-C1] Cuando el frente F6 entregue el catálogo de precios, el campo «precio unitario» podrá proponerse desde ahí; hasta entonces el sistema solo valida formato y moneda.

## 5. Contrato y firma electrónica
**5.1 Estados del contrato** (tabla propia, sin tocar el `CHECK` de estados del lead): `package_sent` → `contract_uploaded` → `approved_for_signature` → `sent_for_signature` → `signed` | `declined` | `expired` | `cancelled`.
- **VCRM-C10** CUANDO el abogado sube el contrato (PDF o DOCX, tope de tamaño de F1) y lo vincula a un lead visible para él, EL SISTEMA lo guarda, calcula su hash SHA-256 y avisa al comercial y al CTO.
- **VCRM-C11** SI el abogado devuelve el paquete con un motivo (código + texto breve), ENTONCES EL SISTEMA avisa al comercial y reabre la edición del paquete.
- **VCRM-C12** CUANDO el comercial o el CTO pulsan ✅ Enviar a firma, EL SISTEMA verifica que el hash coincide con el aprobado y que el lead no está suprimido, en retractación ni bloqueado (reutiliza `may_contact_commercially`), y recién entonces envía.
- **VCRM-C13** EL SISTEMA no envía a firma contratos que el abogado no haya subido: ni IA ni plantilla generan el texto jurídico.
- **VCRM-C14** SI el cliente no firma en 15 días (configurable), ENTONCES EL SISTEMA marca `expired`, avisa al comercial y no reenvía sin nuevo ✅.
- **VCRM-C15** CUANDO se confirma la firma, EL SISTEMA archiva el contrato firmado y la evidencia (§5.3), notifica a comercial, CTO y abogado, y propone marcar «ganado» (el cambio de estado sigue siendo una decisión humana, VCRM-115).
**5.2 Opciones de firma.** Comparativa con fuentes en `investigacion-firma.md` (Colombia: Ley 527/1999, Decreto 2364/2012, Decreto 333/2014; firma electrónica simple frente a firma digital certificada). Regla del Plan Maestro: **no se contrata nada sin OK del CTO**.
- **VCRM-F01** EL SISTEMA define un puerto `SignaturePort` (enviar, consultar estado, descargar evidencia) para no atar el CRM a un proveedor.
- **VCRM-F02** Fase 1 (gratis): firma electrónica propia o plan gratuito de un proveedor (decisión **D-F1** del CTO tras leer la comparativa). Fase 2 (robusta): proveedor acreditado en Colombia, solo si el CTO lo aprueba y conoce el costo.
- **VCRM-F03** CUANDO el contrato exija forma especial o el abogado lo indique, EL SISTEMA no ofrece firma simple: el abogado lo marca «firma certificada o presencial» y el flujo se detiene tras `approved_for_signature`.
**5.3 Evidencia mínima (VCRM-F10).** Hash del documento, identidad del firmante declarada (nombre, correo), canal de verificación y resultado, marca de tiempo UTC y hora local, IP/agente si el medio las provee, registro de consentimiento a firmar electrónicamente y copia firmada con su hash. Sin biometría ni documentos de identidad escaneados salvo que el proveedor elegido los exija por ley (se documenta).

## 6. Entrega al abogado
- **VCRM-C20** EL SISTEMA envía el paquete al abogado por Telegram (resumen + archivo) y, si está configurado, por correo, con los mismos datos y nunca más datos que el paquete.
- **VCRM-C21** Si el abogado no es un usuario activo del bot, el paquete no sale y el comercial recibe el aviso.
- **VCRM-C22** El archivo adjunto del paquete usa un nombre sin datos personales (`paquete-L-NNNN-vN.pdf`).
- **VCRM-C23** [DECISIÓN CTO D-C2] Canal por defecto: Telegram + correo. Telegram guarda los archivos en servidores de terceros; el correo, en el proveedor del buzón. Se recomienda **ambos solo con el resumen y el archivo cifrado con contraseña por Telegram**; alternativa: solo correo.

## 7. Correo por niveles
**Modelo.** Un buzón por comercial (`usuario ↔ dirección ↔ credenciales`). Las contraseñas **solo en `.env`** (`JERICO_MAILBOX_<ID>_PASSWORD`); la base guarda dirección y nombre de la variable, nunca el secreto.
- **VCRM-M01** EL SISTEMA lee cada buzón activo por IMAP de solo lectura y envía desde el buzón del propio comercial por SMTP.
- **VCRM-M02** Visibilidad: el comercial ve solo mensajes de su buzón; el CTO, los de todos; el abogado, ninguno (solo el paquete). Comprobado por el servidor en cada consulta, no solo por la interfaz.
- **VCRM-M03** EL SISTEMA no replica buzones: guarda únicamente remitente, asunto truncado, fecha, identificador del mensaje y su asociación a un lead; el cuerpo se muestra bajo demanda y no se persiste fuera de lo ya definido en F2 (inbound).
- **VCRM-M04** Entrada de leads: CUANDO llega al buzón de un comercial un mensaje de un remitente desconocido, EL SISTEMA crea un **candidato** visible solo para ese comercial (y el CTO) con ✅ Registrar como lead / ❌ Descartar; no se escribe ningún lead ni se responde al remitente sin ✅.
- **VCRM-M05** Descartar un candidato borra sus metadatos en un máximo de 30 días (configurable) y registra solo un contador en la bitácora.
- **VCRM-M06** CUANDO se registra el lead desde un candidato, EL SISTEMA aplica el flujo normal de F1/F2 (autorización, aviso de privacidad por el gate); el primer correo saliente al titular lleva el aviso de privacidad vigente.
- **VCRM-M07** Un lead conserva su buzón de origen; reasignarlo (VCRM-091) transfiere la visibilidad pero no mueve credenciales.
- **VCRM-M08** [DECISIÓN CTO D-M1] Proveedor: Gmail/Google Workspace (contraseña de aplicación o OAuth) frente a otro. Con Gmail personal gratuito OAuth exige verificación de la app; se recomienda contraseña de aplicación y buzones dedicados `@kaisen…`. Sin verificar el estado real de los buzones de Kaisen.
- **VCRM-M09** Los avisos de buzón (credenciales caducadas, bandeja inalcanzable) llegan al comercial y al CTO una vez por día, sin contenido.

## 8. Rol abogado en el bot
Hoy el abogado recibe la alerta de cierre (VCRM-156), ve leads que alguna vez estuvieron «aceptado» (VCRM-136) y puede marcar «ganado». Se añade:
- **VCRM-R01** `/casos`: lista de cierres con paquete, con estado del contrato; solo leads con paquete enviado a él.
- **VCRM-R02** `/paquete L-n`: reenvía la última versión del paquete; `/subircontrato L-n` y el siguiente archivo adjuntan el contrato (C10); `/devolver L-n` pide el motivo (C11).
- **VCRM-R03** `/formaespecial L-n`: marca el contrato como «firma certificada o presencial» (F03).
- **VCRM-R04** El abogado no puede: ver notas, historial comercial, correos de comerciales ni cadencias; aprobar envíos a firma ni mensajes a clientes; esas acciones siguen siendo del comercial y del CTO.
- **VCRM-R05** Toda acción del abogado queda en la bitácora con su actor.
- **VCRM-R06** Los mensajes al abogado cumplen la matriz de permisos (se amplía §4.4 de la spec 001 con las filas nuevas).

## 9. Datos personales (Ley 1581 de 2012)
- **VCRM-P01 Minimización.** Cada flujo lleva solo los campos necesarios para su fin (§4.1); el paquete no incluye notas libres; los adjuntos con nombre neutro; el LLM del asistente no recibe el paquete ni el contrato (el seudonimizador de la spec del asistente no cubre documentos).
- **VCRM-P02 Responsable y encargados.** Kaisen AI es el **responsable**. Son **encargados o terceros receptores** y se enumeran en el aviso y en `JERICO_CRM_DATA_PROCESSORS`: Telegram (mensajería y archivos), el proveedor de correo, el proveedor de firma elegido y el proveedor de nube del servidor. OpenAI queda fuera de este alcance. **Pendiente del abogado:** contratos o cláusulas de encargo con cada uno y la calificación jurídica de cada proveedor (SIN VERIFICAR).
- **VCRM-P03 Base legal.** La autorización previa, expresa e informada del titular (art. 9) ya está modelada como `auth_status`; el paquete solo puede generarse si el lead tiene autorización vigente **o** el abogado confirma por escrito otra base (campo `legal_basis` con código cerrado). **Qué base cubre el contrato es decisión del abogado (SIN VERIFICAR).**
- **VCRM-P04 Transferencia internacional (art. 26).** Preferir proveedores con servidor en Colombia o con nivel adecuado; si no, requiere autorización del titular o una excepción legal. Cada proveedor candidato indica ubicación en la comparativa. **Pendiente del abogado.**
- **VCRM-P05 Retención.** Paquetes y contratos firmados: conservación según la política de la spec 001 (`final_state_suppression_months` y obligación contractual/comercial); lo no firmado ni ganado se borra con el lead. Candidatos de correo: 30 días (M05).
- **VCRM-P06 Derechos del titular.** Consulta, rectificación y supresión alcanzan al paquete, el contrato y los metadatos de correo; un contrato firmado en vigor puede conservarse por obligación legal, con el aviso correspondiente (decide el abogado).
- **VCRM-P07 Seguridad.** Secretos solo en `.env` (`chmod 600`); archivos en disco con permisos 600 bajo `data/`; copias de seguridad cifradas (backup de F1); nada de datos personales en logs ni en la bitácora; cifrado en tránsito (TLS) en IMAP/SMTP/API de firma.
- **VCRM-P08 Incidentes.** Pérdida o acceso indebido a un paquete o buzón: aviso inmediato al CTO por el bot y registro; el reporte a la SIC (RNBD) es decisión del CTO con el abogado.

## 10. Decisiones abiertas (para el OK del CTO)
| Id | Pregunta | Recomendación del director |
|---|---|---|
| D-C1 | ¿Precios escritos a mano ahora y desde F6 después? | Sí |
| D-C2 | Canal al abogado | Telegram (resumen) + correo (archivo); alternativa solo correo |
| D-F1 | Firma de la fase 1 | Opción barata: autofirma propia (OTP + hash + evidencia) o plan gratuito de un proveedor; **cifras de la comparativa sin verificar** y validez a confirmar por el abogado. No elegir sin ambos |
| D-M1 | Proveedor y credenciales de buzones | Buzones dedicados; contraseña de aplicación en `.env` |
| D-P1 | Base legal y encargados | Lo decide el abogado antes de activar |
| D-X1 | ¿Absorbe esta spec el F3 de la 001? | Sí, F3 pasa a esta línea |

## 11. Criterios de aceptación globales
Nada sale al cliente sin ✅; ningún comercial ve el buzón de otro (prueba negativa); el abogado no ve nada fuera de sus casos (prueba negativa); un paquete incompleto no se envía; el contrato enviado a firma coincide por hash con el aprobado; sin servicio de pago activado; cobertura ≥99 % del código nuevo del paquete `crm`.
