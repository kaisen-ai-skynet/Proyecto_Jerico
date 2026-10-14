# Despliegue y Operación — Módulo CRM-consejero (Spec 007)

Este documento detalla la configuración, despliegue, medidas de privacidad y procedimientos operativos para el módulo **CRM-consejero** (captura diaria de instantáneas estructuradas en modo sombra).

---

## 1. Variables de Configuración

Todas las variables llevan el prefijo `JERICO_CRM_` y se configuran exclusivamente en el entorno del servidor (`.env` con permisos `600`), nunca en el repositorio:

| Variable | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `JERICO_CRM_JEV_SNAPSHOT_ENABLED` | booleano | `false` | Interruptor del módulo. **En pausa legal por Q5**: permanece en `false` hasta aprobación formal del abogado y orden del CTO. |
| `JERICO_CRM_JEV_SNAPSHOT_KEY` | secreto | `""` | Clave secreta para derivar la referencia anónima `lead_ref` (HMAC-SHA256, 16 hex chars). Sin clave, el CRM no activa la instantánea y avisa al CTO al arrancar. |
| `JERICO_CRM_JEV_SNAPSHOT_DIR` | ruta | `data/crm/jev_snapshot` | Directorio local donde se almacenan las instantáneas y los archivos de retiros. |
| `JERICO_CRM_JEV_SNAPSHOT_RETENTION_DAYS` | entero | `90` | Días de retención para los archivos de instantánea (`AAAA-MM-DD.jsonl`). |

---

## 2. Formato de Archivos y Almacenamiento

1. **Instantáneas (`AAAA-MM-DD.jsonl`):**
   - Una línea JSON por lead elegible capturado en el día calendario de Bogotá (UTC−5).
   - Estrictamente sin datos personales en texto libre (solo booleanos, enumerados cerrados y enteros acotados).
   - Identificación única vía `lead_ref` (pseudónimo HMAC no reversible sin la clave).
   - Inmune a líneas parciales: descartadas automáticamente en lecturas posteriores.

2. **Archivo de retiros (`retiros-AAAA-MM-DD.jsonl`):**
   - Registra leads suprimidos, revocados o que pasaron a baja (`opted_out`), o líneas asociadas a claves antiguas tras un re-keying.
   - Campos mínimos: `lead_ref` y `withdrawal_day`.
   - Retención fija de 30 días.

---

## 3. Programación y Ejecución

- **Cron:** `30 13 * * *` (08:30 hora de Bogotá).
- Se ejecuta exactamente 30 minutos después del barrido legal diario del CRM (`crm-daily`, 08:00 Bogotá).
- **Aislamiento:** Se ejecuta en un hilo de trabajo (`asyncio.to_thread`), dentro de una transacción SQLite de solo lectura (`with db.read()`), garantizando que la base de datos permanezca inmutable.
- **Tolerancia a fallos:** Cualquier excepción ordinaria no tumba el proceso del CRM ni interrumpe otros trabajos; se registra un aviso en logs sin datos personales y se incrementa el contador de fallos en memoria.

---

## 4. Procedimiento de Activación y Apagado

### Activación (Requiere desbloqueo de Q5 por el abogado)
1. Generar una clave criptográfica de 32 bytes (ej. `openssl rand -hex 32`).
2. Configurar en el `.env` del servidor:
   ```bash
   JERICO_CRM_JEV_SNAPSHOT_ENABLED=true
   JERICO_CRM_JEV_SNAPSHOT_KEY=<clave_generada>
   ```
3. Reiniciar el servicio CRM.

### Apagado
1. En el `.env` del servidor, fijar:
   ```bash
   JERICO_CRM_JEV_SNAPSHOT_ENABLED=false
   ```
2. **Procedimiento obligatorio de higiene (VJC-022, VJC-023):**
   Al desactivar la funcionalidad, el operador debe eliminar o vaciar inmediatamente la carpeta de instantáneas (`data/crm/jev_snapshot/`) ese mismo día para evitar conservar datos derivados sin ciclo diario de reconciliación y retiros.
3. Reiniciar el servicio CRM.

---

> 🕒 **Última modificación:** 14/10/2026 09:46 (Gemini 3.8 Flash · impl-007)
