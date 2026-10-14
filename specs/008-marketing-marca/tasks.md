# Tareas 008 — Marketing masivo y automatización de marca (F5)

Delegables a Gemini: SÍ en M1–M5 (aplicando TDD estricto con tests primero); M6 y revisión final a cargo del director.

- [ ] **M1** Test + `schemas/marketing.py`: Definir esquemas Pydantic `IdeaInput`, `CampanaMarketing`, `CanalMarketing`, `MetaAdConfig` y `LinterResult` con validaciones de tipos, estados y presupuesto no negativo. (R1, R12, R18).
- [ ] **M2** Test + `src/jerico/marketing/linter.py`: Validador algorítmico determinista. Rechaza nombres obsoletos («Kaisen», «AI»), valida exclusividad de trato (tú vs. usted), comprueba invariabilidad del tagline y verifica contraste de tokens de color. (R4, R5, R6, R7, R8).
- [ ] **M3** Test + `src/jerico/marketing/perfeccionador.py`: Ingesta de ideas en audio/texto, categorización en campañas C1–C5 y generación de copies adaptados por canal mediante prompts inmutables y mock de `gpt-6-luna`. (R1, R2, R3, R11).
- [ ] **M4** Test + `src/jerico/marketing/adaptadores/`: Implementar interfaz base y adaptadores para Email, WhatsApp Cloud API oficial de Meta (plantillas HSM) y Meta Ads (con campañas en estado PAUSED). Todo con soporte `DRY_RUN` e `idempotency_key` SHA-256. (R9, R10, R12, R13, R15, R18).
- [ ] **M5** Test + `src/jerico/marketing/orquestador.py`: Orquestador de la máquina de estados. Garantiza que ninguna emisión salga a la red si `aprobado_por` es nulo o si el gasto excede el presupuesto Lean mensual del Plan Maestro §6. (R14, R16, R17).
- [ ] **M6** Herramientas de bot en `src/jerico/tools/marketing.py`: Comandos `/proponer_campana`, `/aprobar <id>` y `/rechazar <id> <motivo>` expuestos para `@Jericoo_bot` con verificación de rol `cto`. (R16, R17).

**Criterios de Verificación:**
- Tests herméticos sin llamadas vivas a la red (mocks completos de APIs de Meta, WhatsApp y Resend).
- Cobertura de tests ≥ 80% en `src/jerico/marketing/`.
- Cero secretos o credenciales en el repositorio.
- `./scripts/verify.sh` en verde.

---
> 🕒 **Última modificación:** 13/10/2026 22:25 (Agente Antigravity · kz-marca · F5)
