# Plan 003 — Catálogo de precios (F6)

## Ubicación en el repo
```
catalogo/
  precios/0.1.0.yaml        # versiones inmutables una vez vigentes
  precios/VIGENTE           # una línea: versión activa (ausente = ninguna)
  README.md                 # cómo proponer y aprobar una versión
src/jerico/catalogo/
  modelo.py                 # Pydantic: Plan, Catalogo, Fuente (precios como int COP)
  repositorio.py            # carga YAML, resuelve VIGENTE, valida
  cotizar.py                # Decimal: mensualidad, total a 12 meses; sin LLM
  vista.py                  # vista por rol: comercial | cto
src/jerico/tools/catalogo.py # herramienta de solo lectura `consultar_catalogo`
scripts/verificar_catalogo.py # compara catálogo contra el Excel (openpyxl, solo dev)
tests/test_catalogo_*.py
```

## Decisiones técnicas
- YAML (revisable y con diff legible) + Pydantic ya presente en `pyproject.toml`; `pyyaml` ya es dependencia.
- `openpyxl` solo para el script de verificación (extra `dev`), nunca en producción.
- El Excel no se copia al repo (fuente de verdad en `~/Documentos/Docs Kaisen.ai/`); se guarda su SHA-256.
- La herramienta se registra en `tools/registry.py` con el rol del usuario ya verificado por el CRM; `comercial` recibe la vista recortada (R7).
- Entregado como datos + código inerte: no se despliega ni se activa en producción sin OK del CTO.

## Fases
1. Esquema y repositorio (TDD con catálogo de prueba, sin Excel).
2. Vista por rol y cotización con Decimal.
3. Herramienta `consultar_catalogo` y prueba de que el rol comercial no ve costos.
4. Script de verificación contra el Excel y primera versión `0.1.0` en `borrador`.
5. Revisión del CTO → versión `1.0.0` vigente (decisión suya).

> 🕒 **Última modificación:** 13/10/2026 22:10 (Claude Code · Sonnet 5.5 · kai-jev)
