# Plan 008 — Marketing masivo y automatización de marca (F5)

## 1. Ubicación en el Repositorio

El diseño se integra dentro del árbol existente de `Proyecto_Jerico`:

```
schemas/
  marketing.py                    # Esquemas compartidos: IdeaInput, CampanaMarketing, CanalMarketing, MetaAdConfig
src/jerico/marketing/
  __init__.py
  linter.py                       # Verificador algorítmico de marca: nombre, trato único, tokens, cero prohibiciones
  perfeccionador.py               # Generación y pulido de copies con gpt-6-luna y prompts de marca inmutables
  orquestador.py                  # Máquina de estados HITL: genera -> valida -> notifica bot -> espera OK -> despacha
  adaptadores/
    base.py                       # Interfaz abstracta para canales de marketing
    email_adapter.py              # Envío masivo transaccional/prospección (Resend / Brevo) con DRY_RUN
    whatsapp_cloud_adapter.py     # Envío oficial WhatsApp Business Cloud API (Meta) con plantillas HSM
    meta_ads_adapter.py           # Creación de campañas y conjuntos Meta Ads (Click-to-WhatsApp) en estado PAUSED
    social_organic_adapter.py     # Generación de copies y guiones para Instagram/Facebook
src/jerico/tools/
  marketing.py                    # Herramientas del bot: proponer_campana, listar_campanas_pendientes, aprobar_campana
tests/
  test_marketing_linter.py        # Tests del linter de marca y accesibilidad de tokens
  test_marketing_perfeccionador.py# Tests del perfeccionador con mocks de LLM
  test_marketing_adaptadores.py   # Tests herméticos de los adaptadores en DRY_RUN y verificación de idempotencia
  test_marketing_orquestador.py   # Tests del ciclo completo HITL y guardarraíles de presupuesto
```

---

## 2. Decisiones Técnicas y Arquitectura

1. **Reutilización de Activos Existentes (`Kaizen_Activos`):**
   - Conexión con `ACT-CRM-01` (`Proyecto_Jerico`): Registra interacciones de prospección y estado de conversión.
   - Conexión con `ACT-CRM-04` (`Kaisen_AI/scripts/test_oportunidades.py`): Algoritmo para orientar a qué segmento disparar cada campaña.
   - Conexión con `ACT-IA-01` (`Cliente_A/proyecto/13-asistente-ia.md`): Protocolo de notificación bidireccional por Telegram.
   - Conexión con `ACT-IA-03` (`prompts-reutilizables.md`): Inyección de directivas inmutables y control de versiones por hash.
   - Conexión con `ACT-CON-01` (`pgcrypto` / Ley 1581): Cifrado de teléfonos y correos en reposo.

2. **Gobernanza de Presupuesto y Anuncios Pagados:**
   - Todo objeto de campaña publicitaria en `meta_ads_adapter.py` se genera con el parámetro `status="PAUSED"` y `daily_budget=0`.
   - El orquestador valida que el gasto mensual total acumulado + el presupuesto propuesto no exceda el límite del Plan Maestro §6 (10–25 USD/mes total de Jericó).
   - El método `activar_anuncio()` rechaza la ejecución si no recibe el hash de aprobación generado por el comando `/aprobar <id>` del CTO.

3. **Garantía `DRY_RUN` y Entorno Seguro:**
   - La variable `JERICO_EXTERNAL_COMMS_DRY_RUN` rige de forma global. Cuando es `true`, los adaptadores simulan las llamadas HTTP hacia Meta o proveedores de correo, redirigiendo el cuerpo del mensaje y la llamada API al chat privado de Telegram del CTO con la cabecera `[DRY_RUN SIMULADO]`.

4. **Idempotencia Transaccional:**
   - Antes de cualquier envío, se calcula un SHA-256 de los datos del mensaje (`campana_id + canal + destinatario + hash_payload`). Si ya existe un registro con dicho `idempotency_key` en estado exitoso, se bloquea la duplicación para evitar cobros de Meta o correos repetidos.

---

## 3. Fases de Implementación (SDD)

1. **Fase 1: Contratos de Datos y Linter de Marca (TDD)**
   - Definir `schemas/marketing.py` con validaciones estrictas.
   - Implementar `src/jerico/marketing/linter.py` con pruebas unitarias que verifiquen:
     - Detección de variantes prohibidas («Kaisen», «Kaizen AI», «Kaizen.ai»).
     - Detección de mezclas de «tú» y «usted».
     - Verificación del tagline invariable.
     - Detección de combinaciones ilegales de color (`Óxido vivo` y `Oro` sobre fondos claros).

2. **Fase 2: Perfeccionador de Contenido y Adaptadores en `DRY_RUN`**
   - Implementar `src/jerico/marketing/perfeccionador.py` con plantilla de prompts basada en `GUIA_MARCA.md`.
   - Implementar la suite de adaptadores en `src/jerico/marketing/adaptadores/` con soporte nativo de `DRY_RUN` e inyección de encabezados de trazabilidad.

3. **Fase 3: Orquestador y Guardarraíl Humano (HITL)**
   - Implementar `src/jerico/marketing/orquestador.py` gobernando la máquina de estados.
   - Integrar comandos en `@Jericoo_bot` (`/aprobar` y `/rechazar`) en `src/jerico/tools/marketing.py`.
   - Ejecutar suite de pruebas de integración herméticas sin dependencias externas vivas.

---
> 🕒 **Última modificación:** 13/10/2026 22:25 (Agente Antigravity · kz-marca · F5)
