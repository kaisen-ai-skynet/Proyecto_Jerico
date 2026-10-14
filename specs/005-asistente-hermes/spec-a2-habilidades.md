# Spec Hija A2 — Habilidades de Ventas y Curador de Jericó (F4)

- **Estado:** IMPLEMENTACIÓN TDD (14/10/2026). Rama `impl/005-asistente-hermes`.
- **Insumos:** `specs/005-asistente-hermes/spec.md` (§3 Fase A2, §3.1), `specs/006-catalogo-precios/spec.md`, `DECISIONES_CTO.md` (D3, D5), `docs/architecture/hermes_master_architecture.md`.
- **Reglas del Proyecto:** Estándar `SKILL.md` (descripción ≤ 60 caracteres, plataformas compatibles, herramientas nativas o vacías), constitución de Jericó (humano en el bucle D5, cero eliminación destructiva de archivos, guardarraíl de confirmación del CTO), Ley 1581 y Ley 2300 de 2023.

---

## 1. Problema y Objetivos

El asistente comercial de Jericó (F4) necesita directivas operativas estandarizadas para cuatro tareas frecuentes del ciclo comercial:
1. **Calificar lead:** Determinar si un prospecto cumple con el perfil de cliente ideal mediante BANT adaptado a PYMEs colombianas, sin exigir datos sensibles excesivos (Ley 1581).
2. **Redactar seguimiento:** Producir mensajes y correos cercanos y profesionales según la cadencia comercial activa, respetando horarios y derechos del titular (Ley 2300 de 2023).
3. **Preparar propuesta:** Construir el borrador de cotización citando obligatoriamente los precios y planes del catálogo oficial versionado (F6, spec 006) y la regla del 10% mensual de mantenimiento/soporte; **el LLM nunca inventa ni calcula precios**.
4. **Resumir reunión:** Sintetizar notas o transcripciones extrayendo acuerdos, compromisos con fecha/responsable y próximos pasos.

Adicionalmente, el **Curador de Habilidades** (`Curator`) debe monitorizar el uso de las habilidades del repositorio, proponiendo transicionar a `stale` (14 días sin uso) o `archived` (30 días sin uso).
**Principio de diseño:** El Curador **propone, nunca borra ni auto-archiva**. Toda mutación en disco exige aprobación explícita y documentada del CTO (`approved_by_cto=True`).

---

## 2. Requisitos EARS

- **A2-R1** Las habilidades de ventas SHALL ubicarse en paquetes autónomos bajo `skills/ventas/<nombre>/SKILL.md`.
- **A2-R2** Cada archivo `SKILL.md` SHALL contener un frontmatter YAML válido con `name`, `description` (longitud $\le 60$ caracteres), `platforms` (`linux`, `macos`, `windows`), `tools`, `pinned` y `status`.
- **A2-R3** Toda habilidad SHALL superar el linter determinista `validate_skill_manifest` con 0 incidencias.
- **A2-R4** La habilidad `preparar-propuesta` SHALL referenciar el catálogo oficial de precios (`jerico.catalogo`, spec 006), la regla del 10 % mensual y SHALL prohibir expresamente la invención o estimación libre de tarifas.
- **A2-R5** La habilidad `calificar-lead` SHALL implementar criterios BANT (presupuesto, autoridad, necesidad, plazo) con salvaguardas de datos mínimos conforme a la Ley 1581.
- **A2-R6** La habilidad `redactar-seguimiento` SHALL adherir a la política de contacto ético y límites de la Ley 2300 de 2023 (horarios hábiles y respeto inmediato al retiro/baja).
- **A2-R7** La habilidad `resumir-reunion` SHALL estructurar acuerdos, compromisos con responsable y fecha, y próximos pasos del pipeline.
- **A2-R8** El Curador SHALL evaluar la inactividad de las habilidades y generar transiciones propuestas (`SkillTransition`) con justificación y cálculo de días inactivos.
- **A2-R9** El Curador SHALL proteger de cualquier transición a aquellas habilidades marcadas como `pinned: true`.
- **A2-R10** El Curador SHALL formatear las propuestas en un informe claro para revisión y decisión del CTO (`format_cto_report`).
- **A2-R11** IF un intento de aplicar transiciones no cuenta con la bandera explícita `approved_by_cto=True`, THEN el Curador SHALL lanzar `PermissionError` y NO mutar ningún archivo en disco.
- **A2-R12** WHEN el CTO apruebe las transiciones (`approved_by_cto=True`), el Curador SHALL actualizar el frontmatter del archivo `SKILL.md` sin eliminar jamás el archivo (`no deletion`).

---

## 3. Catálogo de Habilidades de Ventas Iniciales

| Directorio | Nombre | Descripción ($\le 60$ car.) | Pinned |
|---|---|---|---|
| `skills/ventas/calificar-lead` | `calificar-lead` | `Criterios BANT y perfil de cliente ideal para calificar lead` (59 car.) | `false` |
| `skills/ventas/redactar-seguimiento` | `redactar-seguimiento` | `Redacción de seguimiento comercial cercano y profesional` (57 car.) | `false` |
| `skills/ventas/preparar-propuesta` | `preparar-propuesta` | `Preparación de propuesta comercial con precios de catálogo` (59 car.) | `false` |
| `skills/ventas/resumir-reunion` | `resumir-reunion` | `Extracción de acuerdos, compromisos y próximos pasos` (53 car.) | `false` |

---

## 4. Protocolo del Curador (HITL)

```
[Inactividad >2h / ciclo 7d]
         │
         ▼
[Curator.maybe_run_maintenance()]
         │
         ├─► ¿pinned: true? ──► Ignorar
         ├─► ¿archived? ──────► Ignorar
         ├─► Inactiva ≥30d ──► Propone 'archived'
         └─► Inactiva ≥14d ──► Propone 'stale'
         │
         ▼
[CuratorRunSummary con SkillTransition(es)]
         │
         ▼
[format_cto_report()] ──► Enviado al CTO para revisión (Telegram / Bitácora)
         │
         ├───► Rechazado por CTO ──► No se toca disco
         │
         └───► Aprobado por CTO ──► Curator.apply_approved_transitions(..., approved_by_cto=True)
                                     └─► Actualiza 'status' en frontmatter YAML de SKILL.md
                                     └─► CERO eliminación de archivos
```
