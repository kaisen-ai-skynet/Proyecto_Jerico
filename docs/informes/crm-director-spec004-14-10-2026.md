# Informe crm-director — Implementación de la spec 004 (14/10/2026)

Rama `crm/spec-cierre-contrato-firma` (HEAD `363418b`). Commits locales, sin push, **sin desplegar**. `verify.sh` y pre-commit en verde antes de cada commit; 1895 tests; los módulos nuevos al 99–100 % de cobertura.

## Construido
| Fase | Qué | Módulos |
|---|---|---|
| Base | Tablas aditivas, idempotencia, DRY_RUN, esquemas compartidos | `closing_schema`, `idempotency`, `dryrun`, `schemas/` |
| C1 | `/oferta` → paquete versionado con hash → ✅/❌ → abogado (Telegram+correo); base legal; `/casos` `/paquete` | `package`, `closing_flow`, `closing_repo` |
| C2 | Contrato del abogado (PDF/DOCX por magia), devolución, forma especial, ✅ de envío a firma con verificación de huella, `SignaturePort` + DocuSeal + DRY_RUN, sondeo, evidencia, vencimiento | `closing_contract`, `signature` |
| C3 | Buzón por comercial (contraseña solo en entorno), visibilidad por rol, candidatos de lead con ✅/❌ | `mailboxes` |
| Añadido CTO | `@Jericoo_law_bot` en el mismo servicio (Jev), lista blanca + tabla de usuarios, `/start` entrega el ID, `/descargar`, entrega automática del contrato al comercial y, por venta, al cliente por correo con adjunto | `legal_bot`, cambios en `bot`, `outbox`, `mail`, `app` |

Detalle de desviaciones y pendientes: `specs/004-crm-cierre-contrato-firma/implementacion.md`.

## Decisiones consultadas a Jev
SQLite se mantiene; paquete en Markdown; DRY_RUN al Telegram del CTO; bot del abogado en el mismo servicio (todas coinciden con mi criterio).

## Delegación (Flota_Jev, origen jericom)
Registradas y cerradas: `jericom-firma-investigacion` (repetir: sobreafirmaba), `jericom-004-repo-cierre` (ok). Gemini hizo la comparativa de firma y la capa de repositorio; el resto, por seguridad y arquitectura, lo hice yo.

## Variables nuevas (solo en el `.env` del servidor; ninguna leída ni impresa)
| Variable | Para qué | Obligatoria |
|---|---|---|
| `JERICO_CRM_LEGAL_BOT_TOKEN` | Token de `@Jericoo_law_bot` (el CTO dice que ya está en el servidor) | Para activar el bot del abogado |
| `JERICO_CRM_LEGAL_ALLOWED_IDS` | IDs de Telegram permitidos, separados por comas | Sí para que entre el abogado; vacía = modo registro |
| `JERICO_EXTERNAL_COMMS_DRY_RUN` | `true` por defecto: lo externo va al CTO | Ya tiene valor seguro |
| `JERICO_CRM_DOCUSEAL_URL`, `JERICO_CRM_DOCUSEAL_TOKEN` | DocuSeal autoalojado | Solo fuera de DRY_RUN |
| `JERICO_CRM_SIGNATURE_VALIDITY_DAYS`, `JERICO_CRM_MAIL_CANDIDATE_DAYS` | 15 y 30 por defecto | No |
| `JERICO_MAILBOX_<NOMBRE>_PASSWORD` | Contraseña de cada buzón de comercial (el nombre debe seguir ese patrón) | Con C3 |
| `JERICO_CRM_IMAP_HOST`/`PORT` | Servidor IMAP de los buzones | Con C3 |
Sin las variables nuevas el servicio se comporta como antes (todo apagado).

## Para activar en producción (nada hecho)
1. Pasos de despliegue con OK explícito del CTO; reiniciar `jerico-crm` con la rama.
2. Que el abogado escriba `/start` a `@Jericoo_law_bot`, copiar su ID a `JERICO_CRM_LEGAL_ALLOWED_IDS` y darlo de alta con `/alta abogado; <id>; <correo>` en el bot principal.
3. Probar el flujo completo **en DRY_RUN** con un lead de prueba (`/firmaprueba` simula la firma).
4. Instalar y probar DocuSeal (no está en `docker-compose.yml`) y confirmar la API real.
5. Abogado: base legal, encargados, transferencias y validez de la firma (spec §9).
6. Para apagar DRY_RUN: OK explícito del CTO.

## Pendiente / sin verificar
SMTP por buzón del comercial; precios desde F6; DocuSeal real; respuestas de clientes a los buzones por comercial; nada probado contra Telegram, IMAP/SMTP ni DocuSeal reales.

> 🕒 **Última modificación:** 14/10/2026 (Claude Code · crm-director, Sonnet 5.5)
