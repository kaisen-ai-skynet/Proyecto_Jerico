---
name: preparar-propuesta
description: Preparación de propuesta comercial con precios de catálogo
tools: []
platforms:
  - linux
  - macos
  - windows
pinned: false
status: active
---

# Preparar Propuesta Comercial

Usa esta habilidad para estructurar propuestas comerciales y cotizaciones formales para clientes potenciales de Kaisen AI, asegurando coherencia financiera y técnica.

## Regla de Oro: Cero Invención de Precios

- **El asistente de IA NUNCA inventa, aproxima ni calcula precios libres:** Toda cifra económica debe originarse estrictamente en el catálogo oficial de precios versionado (`jerico.catalogo`, spec 006).
- Utiliza únicamente los planes definidos en el catálogo vigente (ej. Estándar, Único, Premium).
- **Regla de mensualidad:** La tarifa mensual de mantenimiento y soporte equivale exactamente al 10 % del valor de implementación acordado.
- Si el catálogo se encuentra en estado `borrador`, incluye explícitamente la advertencia «BORRADOR — no cotizar formalmente».

## Estructura de la Propuesta

1. **Contexto y Diagnóstico:**
   - Resumen del objetivo de negocio y necesidades operativas identificadas.
2. **Alcance y Entregables:**
   - Detalle de agentes, flujos, integraciones y modelos incluidos en la solución.
3. **Inversión y Condiciones:**
   - Valores en pesos colombianos (COP), especificando que no incluyen IVA.
   - Desglose: Implementación inicial + Cuota de mantenimiento mensual (10 %).
   - Términos de pago estándar (ej. 50 % anticipo, 50 % contra entrega validada).
4. **Cronograma Estimado:**
   - Hitos de entrega por fases.

## Guardarraíl de Aprobación
- Ninguna propuesta se despacha automáticamente: todo borrador generado requiere revisión y visto bueno humano antes de su envío.
