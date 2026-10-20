# Guía para evaluadores: Jericó en 10 minutos

Si estás revisando este repositorio para una vacante, aquí tienes un recorrido corto por las partes que mejor muestran cómo trabajo. Cada punto enlaza al archivo concreto.

## 1. Un requisito, de la spec a la prueba (2 min)

El ejemplo es la regla más importante del CRM: *ningún mensaje sale al cliente sin aprobación humana sobre ese texto exacto*.

1. **Requisito** en formato EARS: [`specs/001-ventas-crm/spec.md`](../specs/001-ventas-crm/spec.md), busca `VCRM-036`.
2. **Decisión de diseño** (por qué un hash de contenido y no un id de versión): [`specs/001-ventas-crm/plan-f2.md`](../specs/001-ventas-crm/plan-f2.md), decisión `D-8`.
3. **Implementación:** [`src/jerico/crm/gate.py`](../src/jerico/crm/gate.py) y [`src/jerico/crm/delivery.py`](../src/jerico/crm/delivery.py).
4. **Prueba:** `test_vcrm036_hash_distinto_falla_cerrado` en [`tests/test_crm_delivery.py`](../tests/test_crm_delivery.py). Si alguien altera el texto aprobado en la base de datos, el envío falla cerrado con `content_mismatch`.

Así se trabaja en todo el repositorio: más de 300 requisitos con identificador, citados por las pruebas.

## 2. IA con límites: Jev (3 min)

Lee [`docs/JEV.md`](JEV.md) y luego [`src/jerico/decision/port.py`](../src/jerico/decision/port.py). Muestra cómo integrar un modelo de decisión externo sin perder el control:

- clases de riesgo,
- piso de exigencia,
- cortacircuitos,
- validación de privacidad,
- modo sombra,
- criterios de promoción medidos (Brier, ECE, p95).

## 3. Efectos externos confiables (2 min)

- [`crm/idempotency.py`](../src/jerico/crm/idempotency.py): una clave determinista evita enviar dos veces al abogado, a la firma o al cliente.
- [`crm/outbox.py`](../src/jerico/crm/outbox.py): la notificación se persiste antes del primer intento, se reintenta a los 0, 1 y 5 minutos y luego se escala.
- [`crm/signature.py`](../src/jerico/crm/signature.py): puerto de firma electrónica con adaptador DocuSeal autoalojado, consultado por *polling* para no exponer una ruta pública.

## 4. Privacidad y cumplimiento (1 min)

- [`crm/pseudonym.py`](../src/jerico/crm/pseudonym.py): reemplaza los datos personales por marcadores antes de llamar al LLM y los repone solo localmente.
- [`crm/compliance.py`](../src/jerico/crm/compliance.py): autorización con evidencia, baja y retención según la Ley 1581.
- Las pruebas usan solo datos sintéticos.

## 5. Dinero sin LLM (1 min)

- [`catalogo/cotizar.py`](../src/jerico/catalogo/cotizar.py): cotización con `Decimal`, sin modelos de lenguaje.
- [`catalogo/verificador.py`](../src/jerico/catalogo/verificador.py): contrasta el catálogo con el modelo financiero en Excel mediante su huella SHA-256 y alerta de precios bajo costo.

## 6. Núcleo agéntico sin frameworks (1 min)

- [`src/jerico/agent/`](../src/jerico/agent/): el turn loop está partido en fases (`turn_preflight`, `turn_request_assembly`, `turn_api_call`, `turn_tool_round`, `turn_finalizer`, `turn_recovery`), cada una con sus pruebas.
- [`tests/test_prompt_caching_invariant.py`](../tests/test_prompt_caching_invariant.py): garantiza que el prompt de sistema no cambia entre turnos y así aprovecha la caché del proveedor.

## Habilidades que muestra el repositorio

| Habilidad | Dónde se ve |
|---|---|
| Python moderno (3.12, tipado, dataclasses, async) | Todo `src/jerico/` |
| APIs con FastAPI | [`api.py`](../src/jerico/api.py), [`web/`](../src/jerico/web/) |
| Bots e integraciones | Telegram, IMAP/SMTP, DocuSeal, WhatsApp Cloud, Meta Ads: [`crm/`](../src/jerico/crm/), [`marketing/adaptadores/`](../src/jerico/marketing/adaptadores/) |
| Bases de datos | SQLite WAL, FTS5 y SQL portable a PostgreSQL 16: [`state/`](../src/jerico/state/), [`crm/db.py`](../src/jerico/crm/db.py), [`crm/migrate.py`](../src/jerico/crm/migrate.py) |
| IA aplicada y control de costos | [`router.py`](../src/jerico/router.py), [`llm/token_accounting.py`](../src/jerico/llm/token_accounting.py), [`crm/assistant_budget.py`](../src/jerico/crm/assistant_budget.py), [`decision/`](../src/jerico/decision/) |
| Pruebas y TDD | 2248 pruebas, 96 % de cobertura, relojes inyectados, servicios simulados: [`tests/`](../tests/) |
| DevOps | Docker, Compose, systemd, respaldos cifrados con `age` + rclone, CI: [`deploy/`](../deploy/), [`scripts/`](../scripts/), [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) |
| Seguridad | Secretos solo en el entorno, binds en `127.0.0.1`, Tailscale, permisos por herramienta y aprobación humana: [`tools/approval.py`](../src/jerico/tools/approval.py), [`crm/permissions.py`](../src/jerico/crm/permissions.py) |
| Arquitectura y documentación | [Constitución](constitution.md), [decisiones](decisiones/), [specs](../specs/) |
| Trabajo con agentes de código | [`AGENTS.md`](../AGENTS.md), [`MEMORY.md`](../MEMORY.md), [`.claude/agents/`](../.claude/agents/) |

## Comprobarlo tú mismo

```bash
pip install -e ".[dev]"
pytest -q                 # ~1 minuto, sin red ni llaves
./scripts/verify.sh       # lint + pruebas + cobertura, igual que en CI
```

Contacto: [juansantiagogonzalezmarin@gmail.com](mailto:juansantiagogonzalezmarin@gmail.com)
