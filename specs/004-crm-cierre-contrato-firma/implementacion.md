# Spec 004 — Estado de la implementación y desviaciones (14/10/2026)

Rama `crm/spec-cierre-contrato-firma`. La spec fue aprobada por el CTO el 13/10; esto documenta lo construido, las decisiones tomadas al implementar y lo que falta. Sin desplegar.

## Añadido del CTO (13/10): bot propio del abogado
- **Bot aparte, mismo servicio** (decidido con Jev; ver `plan.md`): `@Jericoo_law_bot` corre dentro de `jerico-crm` como segundo cliente de Telegram con su propio bucle de polling, sobre la misma `CrmDatabase`. Offset (`legal_telegram_offset`) e ids de update propios (espacio `1·10¹³`), para no chocar con el bot principal.
- **Acceso (doble candado):** el ID debe estar en `JERICO_CRM_LEGAL_ALLOWED_IDS` **y** existir en `crm_users` con rol abogado (el CTO lo da de alta con `/alta`). Cualquier otro: silencio y auditoría. Único caso especial: `/start` de un desconocido devuelve **solo su propio ID** para que se lo pase al CTO. Sin IDs en la variable el bot arranca en «modo registro» (solo responde `/start`) y avisa al CTO.
- **Comandos del abogado:** `/start`, `/casos`, `/paquete`, `/descargar` (paquete en Markdown como archivo), `/subircontrato`, `/devolver`, `/formaespecial`, `/basejuridica`. Los comandos de ventas no existen en ese bot.
- **«Leer, descargar, modificar»:** leer = `/paquete`; descargar = `/descargar`; modificar = el abogado edita el archivo fuera del sistema y sube el contrato final (el sistema no edita el paquete: lo cambia el comercial con `/oferta`, o lo devuelve el abogado con `/devolver`).
- **Entrega al subir el contrato:** el archivo va **siempre** al comercial por el bot principal; y **también al cliente por correo con adjunto si esa venta lo eligió** (`/oferta … ; entrega cliente`, por defecto `comercial`). Cada destino reserva una clave idempotente (contrato + huella + destino); reenviar el mismo archivo no duplica, uno distinto sí; si un envío falla, la clave se libera para reintentar y se avisa al abogado.
- **DRY_RUN:** el correo al cliente se redirige al correo del CTO con `[DRY_RUN → destino]`; el paquete por Telegram al abogado se redirige al CTO. Los avisos del flujo F1 al abogado no cambian.
- Los avisos de la cola de salida al abogado salen por **su** bot (si no hay bot del abogado, por el principal, como hasta ahora).

## Desviaciones deliberadas de la spec
| Spec | Construido | Motivo |
|---|---|---|
| Migración v3 con copia previa | Tablas **aditivas** `IF NOT EXISTS`, sin subir `schema_version` | Una imagen anterior sigue abriendo la base: la reversión del despliegue es trivial |
| Oferta un campo por mensaje (C01) | Oferta en **una línea** (`/oferta L-n; pago …; linea … x1 @precio; …`) | Más rápido para el comercial; los errores muestran ejemplo |
| Paquete en PDF/archivo cifrado | **Markdown** como cuerpo del correo/mensaje y archivo descargable | Decisión con Jev: sin dependencia nueva |
| Importes en unidad menor | **Pesos enteros** (sin decimales) | COP; F6 debe confirmar si necesita centavos |
| Webhook de DocuSeal | **Sondeo saliente** cada 5 min | Principio de «sin ruta pública» |
| Remitente en huella HMAC | `sender_email` en claro **30 días** (se anonimiza si se registra) | Hace falta para crear el lead; retención mínima |
| Aprobador del primer correo | El lead nace «nuevo» y el aviso de privacidad sigue en `/pedirautorizacion` (gate de F2) | Reutiliza el gate existente |

## Reglas del Plan Maestro aplicadas
Idempotencia (`crm_idempotency`, claves `package_send`, `signature_send`, `contract_delivery`, `lead_from_mail`); `JERICO_EXTERNAL_COMMS_DRY_RUN=true` por defecto (correo saliente, firma, entrega al cliente); esquemas compartidos `Lead`/`Cotizacion`/`PaqueteContrato` en `src/jerico/schemas/` y `schemas/*.json` (con prueba de sincronía); el LLM no calcula precios ni ve paquetes o contratos; sin DeepSeek ni WhatsApp en este alcance; DocuSeal detrás de `SignaturePort`.

## Lo que NO está hecho (y por qué)
1. **Envío por el buzón propio del comercial (SMTP por usuario, M01):** hoy todo el correo saliente sale por el SMTP único del CRM. Requiere cambiar el puerto de salida y credenciales reales.
2. **Precios desde el catálogo de F6 (D-C1):** el comercial escribe los importes; el punto de enganche es `Cotizacion`. Falta la herramienta determinista de F6.
3. **DocuSeal real:** el adaptador sigue la API pública documentada y **no se probó contra una instancia**. DocuSeal no está en `docker-compose.yml` (no se tocó la infraestructura).
4. **Respuestas de clientes a los buzones por comercial:** la asociación de respuestas de F2 sigue usando el buzón único; los buzones por comercial solo generan candidatos.
5. **Cierre jurídico:** base legal, encargados y validez de la firma siguen pendientes del abogado (spec §9).
6. No se ha probado nada contra Telegram, IMAP/SMTP ni DocuSeal reales.
