# Spec 006 — Catálogo versionado de precios y estructuras para Jericó (F6)

- **Estado:** BORRADOR para revisión del CTO (13/10/2026). Rama `finanzas/f6-catalogo-precios`. Sin código de producción.
- **Fuente:** modelo financiero `Kaizen_Modelo_Financiero_5A_8.xlsx` (8 hojas) y su desglose en la bóveda (`02_Proyectos/Finanzas/Modelo_Financiero_5A_Desglose.md`). Plan maestro: frente F6.
- **Numeración:** 006, decidida con Jev el 13/10/2026 (plan maestro §1: 001 ventas-crm · 002 jev-router · 003 servidor · 004 cierre-contrato · 005 asistente · 006 catálogo). Renumerada desde 003.
- **Aviso del CTO (13/10/2026):** el modelo financiero está **en pausa** hasta que haya ingresos. El catálogo nace en estado `borrador`; nada se cotiza con él hasta que el CTO lo marque `vigente`.

## 1. Problema

Jericó (asistente comercial por Telegram, F2) necesita citar precios y estructuras a los comerciales y armar el paquete del cierre. Hoy los precios viven en un Excel y en propuestas sueltas: el asistente no puede consultarlos y, si los inventara, vendería a un precio equivocado. Además el propio modelo advierte que los precios reales de propuesta (3,22 / 4,32 / 5,52 M COP) están por debajo del precio de fórmula (5,76 / 6,12 / 7,00 M COP).

## 2. Alcance

Dentro: formato, ubicación, versionado y reglas de consulta del catálogo; esquema de validación; herramienta de solo lectura `consultar_catalogo`; verificación de que el catálogo coincide con el Excel.
Fuera: cambiar precios, decidir cuál es el precio oficial, editar el Excel, tocar producción, el CRM desplegado o n8n. El modelo interno de costos, honorarios y caja **no** entra al catálogo que ve el comercial.

## 3. Requisitos (EARS)

- **R1** El sistema SHALL guardar el catálogo como archivos YAML versionados con semver en `catalogo/precios/<MAJOR.MINOR.PATCH>.yaml`, validados contra un esquema Pydantic.
- **R2** Una versión con estado `vigente` o `retirada` SHALL ser inmutable; cualquier cambio crea una versión nueva (el historial lo da git).
- **R3** WHEN el CTO marque una versión como vigente, el sistema SHALL apuntar a ella con el archivo `catalogo/precios/VIGENTE` (una línea con la versión). IF no existe `VIGENTE`, la herramienta SHALL responder «catálogo sin versión vigente» y no devolver precios.
- **R4** El catálogo SHALL guardar dinero como entero en pesos colombianos (COP, sin IVA) y calcular con `Decimal`; el modelo de lenguaje NO calcula precios: llama a la herramienta y cita el resultado.
- **R5** El catálogo SHALL declarar por cada plan: identificador, nombre, precio de propuesta (real), precio de fórmula (referencia), mensualidad y regla de mensualidad (10 % del valor de implementación al mes), con su fuente (hoja y celda del Excel).
- **R6** El catálogo SHALL guardar la huella SHA-256 del Excel de origen y la fecha de extracción; un script de verificación SHALL fallar si los valores del catálogo no coinciden con el Excel indicado.
- **R7** WHILE el rol del usuario sea `comercial`, la herramienta SHALL devolver solo planes, precios, mensualidad, condiciones y advertencias comerciales; NO SHALL devolver costos directos, márgenes, honorarios, caja ni cap table.
- **R8** WHILE el rol sea `cto`, la herramienta MAY devolver además costo directo por implementación y margen por plan.
- **R9** El catálogo SHALL NOT contener nombres de personas con su remuneración individual, datos de clientes ni secretos.
- **R10** La herramienta `consultar_catalogo` SHALL ser de solo lectura, sin aprobación humana, y SHALL registrar la versión consultada en cada respuesta.
- **R11** IF una cotización pide un plan inexistente, THEN SHALL responder error explícito con los planes válidos; nunca aproximar.
- **R12** WHEN el estado de la versión no sea `vigente`, la respuesta SHALL llevar la marca «BORRADOR — no cotizar».
- **R13** El catálogo SHALL registrar las advertencias del modelo (precio real bajo el costo, capacidad de 12 implementaciones al año, churn 0 %, ICA «CONFIRMAR con contador») para que el CTO las vea al aprobar.
- **R14** La cotización que devuelve la herramienta SHALL usar el esquema compartido `Cotizacion` del directorio `schemas/` (plan maestro §4), el mismo que consumen F2 y F4; el LLM NO SHALL calcular precios (R4) y la herramienta es determinista y sin efectos (no requiere `idempotency_key`).

## 4. Formato propuesto (resumen; detalle en `plan.md`)

```yaml
version: 0.1.0
estado: borrador            # borrador | vigente | retirada
moneda: COP
iva: excluido
vigencia_desde: null
fuente: {archivo: Kaizen_Modelo_Financiero_5A_8.xlsx, sha256: "<huella>", extraido: "13/10/2026"}
planes:
  - id: mdo-estandar
    nombre: Estándar
    precio_propuesta: 3220000      # Desglose_Precios (precio real propuesto)
    precio_formula: 5762939        # referencia, no se cotiza
    mensualidad_pct: 10
```

## 5. Decisiones que necesita el CTO (no las tomo yo)

1. ¿Qué precio es el oficial: el de propuesta (3,22 / 4,32 / 5,52 M) o el de fórmula (5,76 / 6,12 / 7,00 M)? El catálogo guarda ambos; solo `precio_propuesta` se cotiza hasta que decida.
2. ¿Los planes de Mundo de Oro y Olmax son planes del catálogo general o precios por cliente? Propuesta: planes generales (Estándar, Único, Premium) y los precios por cliente en el CRM, no en el catálogo.
3. ¿Quién aprueba una versión `vigente`? Propuesta: solo el CTO, por commit en rama propia.

## 6. Riesgos

- Publicar un precio bajo el costo (margen −52 % Estándar, −13 % Único) sin que el CTO lo sepa: mitigado por R12/R13.
- Filtrar la estructura de costos al comercial: mitigado por R7/R9.
- Catálogo desactualizado frente al Excel: mitigado por R6.
- Ley 1581: el catálogo no trata datos personales (R9); no requiere base legal propia.

> 🕒 **Última modificación:** 13/10/2026 22:10 (Claude Code · Sonnet 5.5 · kai-jev)
