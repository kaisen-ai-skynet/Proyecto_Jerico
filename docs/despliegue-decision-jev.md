# Despliegue y Operación — Capa de Decisión Transversal con Jev (Spec 007)

Este documento detalla la configuración en producción, los mecanismos de seguridad,
los modos de operación, el cortacircuitos y los procedimientos de emergencia
para la capa de decisión transversal con Jev (`jerico.decision`).

---

## 1. Variables de Configuración

Todas las variables de entorno de la capa de decisión llevan el prefijo `JERICO_DECISION_`
(excepto las credenciales de proveedor `TYPESAFE_*`) y deben configurarse exclusivamente
en el entorno del host o contenedor (`.env` con permisos `600`), nunca dentro del repositorio:

| Variable | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `JERICO_DECISION_MODES` | lista clave=valor | `""` | Modos por tipo de decisión separados por coma (ej. `modelo_asistente=sombra,seguimiento_lead=sombra`). |
| `JERICO_DECISION_KILL` | booleano | `false` | Interruptor general de emergencia (Kill Switch). En `true`, todas las consultas retornan inmediatamente a la regla base sin red ni cómputo. |
| `JERICO_DECISION_DIR` | ruta | `logs/decision` | Directorio local donde se persisten los registros JSONL de auditoría y marcadores de estado. |
| `JERICO_DECISION_RETENTION_DAYS` | entero | `90` | Días de retención automática para los archivos de auditoría `decision-AAAA-MM-DD.jsonl`. |
| `JERICO_DECISION_ONLINE` | booleano | `false` | Habilita el cliente en línea de Nivel 2. En `false`, opera en Nivel 1 hermético sin red. |
| `JERICO_DECISION_MIN_LEADS` | entero | `20` | Umbral mínimo de volumen requerido para lectura de lotes analíticos. |
| `JERICO_DECISION_TIMEOUT_S` | flotante | `3.0` | Tiempo límite estricto por consulta HTTP hacia el servicio Jev (VJT-031). |
| `JERICO_DECISION_BREAKER` | entero,flotante | `3,300` | Umbral de fallos consecutivos y segundos de enfriamiento para el cortacircuitos (ej. 3 fallos, 300 s). |
| `TYPESAFE_API_KEY` | secreto | `None` | Llave de autenticación para el servicio Jev de TypeSafe. Protegida contra fugas en logs y trazas. |
| `TYPESAFE_ENDPOINT` | URL | `None` | Endpoint HTTPS del servicio Jev de TypeSafe. |
| `TYPESAFE_MODEL` | cadena | `jev-1.13.0` | Versión semver pineada del modelo Jev (Principio 5 de la constitución y decisión Q8). Prohibido usar `jev-latest`. |

---

## 2. Modos de Operación y Transiciones

Cada tipo de decisión opera bajo uno de los cuatro modos estandarizados (VJT-010):

1. **`apagado` (Modo por defecto obligatorio, VJT-010):**
   - No consulta a Jev ni realiza registro en disco.
   - Retorna directamente la opción base de la regla determinista.
2. **`sombra`:**
   - La opción base se aplica de forma determinista al usuario o flujo.
   - Si está configurado, consulta a Jev y registra la comparación en el log diario `decision-AAAA-MM-DD.jsonl`.
   - Cero impacto en el tiempo de respuesta o comportamiento visible del sistema.
3. **`sugerencia` (Exclusivo para el CTO, VJT-012):**
   - La opción aplicada sigue siendo la opción base.
   - La sugerencia de Jev (`suggested`) solo se expone en la interfaz cuando el usuario tiene rol verificado `cto`. Nunca a clientes ni comerciales.
4. **`enrutado` (Solo clases B y C, nunca clase A ni asesor, VJT-003, VJT-010a):**
   - Requiere haber alcanzado al menos 200 decisiones evaluadas, acuerdo alto y calibración verificada (VJT-013).
   - Aplica la función de piso (`apply_floor`), garantizando que la salida nunca exceda las opciones permitidas ni baje de exigencia en clase B.
   - DeepSeek solo se permite bajo clase de datos `sin_datos_personales` y contexto estructurado en origen (Q3, VJT-022, VJT-023).

---

## 3. Resiliencia, Cortacircuitos y Degradación Automática

1. **Invariante de No Interrupción (VJT-030):**
   - La función `decidir(...)` atrapa internamente cualquier fallo inesperado y retorna la opción base. Jamás propaga una excepción hacia los módulos consumidores.
2. **Cortacircuitos (`CircuitBreaker`):**
   - Ante fallos de red o errores HTTP 5xx/429, incrementa el contador de fallos.
   - Al acumular 3 fallos consecutivos, el cortacircuitos se abre y bloquea llamadas externas durante 300 segundos, devolviendo la opción base con motivo `cortacircuitos`.
3. **Marcador de Degradación Automática (VJT-015):**
   - Al dispararse el cortacircuitos en un tipo que operaba en `enrutado` o `sugerencia`, el sistema escribe automáticamente un archivo marcador:
     ```
     logs/decision/degraded_{kind}.marker
     ```
   - Este marcador degrada inmediatamente el tipo a modo `sombra`, protegiendo la operación.
   - **Recuperación:** Para restaurar el modo configurado, el operador debe verificar la estabilidad del servicio externo y eliminar el archivo marcador.

---

## 4. Interruptor General de Emergencia (Kill Switch) y Reversa

Existen dos mecanismos independientes para apagar la capa de decisión transversal:

1. **Vía Variable de Entorno:**
   ```bash
   JERICO_DECISION_KILL=true
   ```
   Forzar reinicio o recarga de la aplicación.
2. **Vía Archivo Marcador en Caliente (sin reinicio):**
   Crear un archivo vacío con el nombre `decision.KILL` en el directorio de decisiones:
   ```bash
   touch logs/decision/decision.KILL
   ```
   Al detectarse el archivo, `decidir(...)` desactiva de inmediato todas las consultas y llamadas externas, retornando la opción base en todos los tipos.
   Para reanudar la operación normal:
   ```bash
   rm logs/decision/decision.KILL
   ```

---

## 5. Idempotencia y Simulación de Acciones (`DRY_RUN`)

1. **Clave de Decisión Determinista (`decision_key`, SHA-256):**
   - Toda decisión deriva una clave criptográfica a partir del par `(kind, tarea)`, el estado validado y la versión de la política.
   - En modos activos (`sugerencia`, `enrutado`), `decidir(...)` utiliza `SingleFlight` y una caché TTL para evitar consultas duplicadas idénticas durante el mismo intervalo.
2. **Comunicaciones y Acciones Externas (VJT-042):**
   - Cualquier acción o envío disparado como consecuencia de una decisión transversal debe ser idempotente y verificar la variable:
     ```bash
     JERICO_EXTERNAL_COMMS_DRY_RUN=true
     ```
   - En modo `DRY_RUN`, las acciones externas no se emiten hacia proveedores externos (WhatsApp, correo, Meta Ads, etc.), registrándose exclusivamente en auditoría.

---

## 6. Estado Legal y Gobernanza (Pregunta Q5)

- **Pausa Legal Activa:** La consulta hacia el servicio externo TypeSafe con vectores de leads (módulo CRM-consejero) permanece **en pausa legal** a la espera de la confirmación escrita por parte del abogado y la posterior ratificación del CTO.
- Las variables `JERICO_CRM_JEV_SNAPSHOT_ENABLED` permanecen en `false` por defecto en todos los entornos.

---

> 🕒 **Última modificación:** 14/10/2026 10:05 (Agente Antigravity · jer-jev-gem)
