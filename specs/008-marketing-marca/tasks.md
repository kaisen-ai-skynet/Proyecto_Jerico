# Tareas 008 — Marketing masivo y automatización de marca (F5)

Delegables a Gemini: SÍ en M1–M5 (aplicando TDD estricto con tests primero); M6 y revisión final a cargo del director.

- [x] **M1** Test + `schemas/marketing.py`: Definir esquemas Pydantic `IdeaInput`, `CampanaMarketing`, `CanalMarketing`, `MetaAdConfig` y `LinterResult` con validaciones de tipos, estados y presupuesto no negativo. (R1, R12, R18).
- [x] **M2** Test + `src/jerico/marketing/linter.py`: Validador algorítmico determinista. Rechaza nombres obsoletos («Kaisen», «AI»), valida exclusividad de trato (tú vs. usted), comprueba invariabilidad del tagline y verifica contraste de tokens de color. (R4, R5, R6, R7, R8).
- [x] **M3** Test + `src/jerico/marketing/perfeccionador.py`: Ingesta de ideas en audio/texto, categorización en campañas C1–C5 y generación de copies adaptados por canal mediante prompts inmutables y mock de `gpt-6-luna`. (R1, R2, R3, R11).
- [x] **M4** Test + `src/jerico/marketing/adaptadores/`: Implementar interfaz base y adaptadores para Email, WhatsApp Cloud API oficial de Meta (plantillas HSM) y Meta Ads (con campañas en estado PAUSED). Todo con soporte `DRY_RUN` e `idempotency_key` SHA-256. (R9, R10, R12, R13, R15, R18).
- [x] **M5** Test + `src/jerico/marketing/orquestador.py`: Orquestador de la máquina de estados. Garantiza que ninguna emisión salga a la red si `aprobado_por` es nulo o si el gasto excede el presupuesto Lean mensual del Plan Maestro §6. (R14, R16, R17).
- [x] **M6** Herramientas de bot en `src/jerico/tools/marketing.py` y `src/jerico/marketing/bot.py`: Comandos `/campana`, `/campanas`, `/aprobarcampana`, `/rechazarcampana` y `/despachar` expuestos en `@Jericoo_bot` para rol `cto`. (R16, R17).
- [x] **M7** Plantillas de Marca Kaizen (`src/jerico/marketing/plantillas.py`): Formato estándar de ficha de lead y mensajes con identidad Kaizen, plantillas canónicas de cotización/correo/WhatsApp, comandos `/plantillas` y `/plantilla nueva` con linter determinista, aprobación HITL por CTO (`/aprobarplantilla`, `/rechazarplantilla`) y cotizaciones automáticas desde el catálogo (006).

**Criterios de Verificación:**
- Tests herméticos sin llamadas vivas a la red (mocks completos de APIs de Meta, WhatsApp y Resend).
- Cobertura de tests ≥ 80% en `src/jerico/marketing/`.
- Cero secretos o credenciales en el repositorio.
- `./scripts/verify.sh` en verde (2173 tests pasando, mypy y ruff en verde).

---
> 🕒 **Última modificación:** 14/10/2026 09:50 (Agente Antigravity · kz-marca · F5)
