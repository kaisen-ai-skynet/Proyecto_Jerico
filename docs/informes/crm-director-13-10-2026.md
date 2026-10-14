# Informe crm-director — pulido post-despliegue del CRM (13/10/2026)

Rama `crm/pulido-post-despliegue` (commits locales, sin push).

## Hecho y verificado
| Commit | Cambio | Verificación |
|---|---|---|
| `fdf20a9` | Variables vacías de `.env.example` (`SMTP_PORT=`, `SMTP_SECURITY=`) se tratan como no definidas (`env_ignore_empty`). Este commit quedó en `main` local antes de crear la rama. | Test nuevo: rojo sin el arreglo, verde con él |
| `acbe109` | Logs de arranque («jerico-crm iniciado (fase N)») y parada | Test nuevo |
| `887596e` | 20 tests nuevos para huecos de cobertura (hechos por Gemini, revisados) | Cobertura crm 99 %; solo queda `app.py:48` (`utcnow`, el reloj real) |
| `21844d0` | Mensajes del bot en español: tuteo y causa+acción. Sin cambios de reglas ni del gate | Tests actualizados |

Verificación de cada commit: `verify.sh` y pre-commit en verde; 1565 tests. Excepción: `acbe109` se commiteó antes de pasar la puerta y se verificó justo después, en verde.

## Logs del servidor (solo lectura)
`docker logs --tail 200 jerico-crm` salió vacío, con el contenedor `healthy` y 4 min arriba. No hay errores ni avisos que corregir. Sin logs de arranque no se podía distinguir «sano» de «mudo»: de ahí `acbe109`.

## Revisión de la entrega de Gemini
En el pulido de mensajes, Gemini referenció un comando `/ayuda` inexistente y escribió mal la sintaxis de `/editar`. Lo corregí yo antes del commit (`21844d0`). Los tests no detectaban esas referencias.

## Qué falta para activar F2 en producción (depende del CTO)
1. `.env` del servidor: `JERICO_CRM_IMAP_HOST/USERNAME/PASSWORD` (buzón dedicado, contraseña de aplicación), SMTP de salida (`SMTP_HOST/PORT/SECURITY/USERNAME/PASSWORD/FROM`) y `JERICO_CRM_SENDER_NAME` si no es «Kaisen AI». Salida 993/TCP si hay filtro. Sin esto, F2 queda deshabilitada y el CTO recibe un aviso.
2. Datos registrales del responsable en `src/jerico/crm/resources/aviso-privacidad.md` (razón social, NIT, domicilio), hoy `[PENDIENTE]`. Los redacta el CTO o Juan José; no se inventan.
3. Confirmar por escrito la aprobación de Juan José del aviso de privacidad y de los textos de cadencia v1 (constan solo como «autorizado por el CTO el 11/10/2026»).
4. Prueba real con Telegram y correo: baja con cliente de correo real (`List-Unsubscribe`), envío y respuesta de punta a punta.
5. Migración v1→v2 de la base del servidor con el servicio detenido (deja `crm.db.pre-v2.bak`); respaldo previo.
6. Anotar en `DECISIONES_CTO.md` la excepción temporal de SQLite a D1 (archivo de infra; no lo toco).
7. Push de la rama lo hace el CTO. Falta revisar si `main` local, que lleva `fdf20a9`, se reconcilia con la rama.

> 🕒 **Última modificación:** 13/10/2026 10:57 (Claude Code · crm-director, Sonnet 5.5)
