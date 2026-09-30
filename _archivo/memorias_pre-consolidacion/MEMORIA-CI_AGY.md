# Memoria de Frente: Reparación de CI (Higiene Pre-commit Fase 4)
**Proyecto:** Jericó AI-OS — Kaisen AI  
**Frente:** CI / Higiene Pre-commit (Fase 4)  
**Fecha:** 29/09/2026 13:42  
**Responsable:** Santiago Gonzalez (CTO) / Antigravity Agent (Headless)  

---

## 1. Contexto
- **Repositorio:** `kaisen-ai-skynet/Proyecto_Jerico` (rama `main`).
- **Entorno de ejecución:** Worktree aislado `/home/janty-mr/.hermes/cache/scratch/jerico-ci-fix/wt` en rama `ci/higiene-fase4` (base `54ea878` = `origin/main`), para evitar cualquier colisión o interferencia con el frente dev que opera concurrentemente en el árbol principal.
- **Workflow afectado:** `.github/workflows/ci.yml` → job `verify`.

---

## 2. Causa Raíz
- En los runs `36612193556` y `36612263909`, el paso `Check formatting and repository hygiene` (`pre-commit run --all-files`) falló debido al hook `trailing-whitespace`, el cual detectó y modificó espacios en blanco al final de línea en:
  - `docs/SPEC_JERICO_V2.md`
  - `docs/runbook-aprovisionamiento-vps.md`

---

## 3. Fix Aplicado
- Ejecución de `pre-commit run --all-files` en el worktree aislado.
- Limpieza estricta y mínima de trailing whitespace en `docs/SPEC_JERICO_V2.md` (11 inserciones / 11 eliminaciones) y `docs/runbook-aprovisionamiento-vps.md` (7 inserciones / 7 eliminaciones), sin alterar contenido, reflow ni arquitectura.
- No se tocaron archivos del frente dev en curso (`src/`, `tests/`, `docs/architecture/`).
- Re-verificación local: todos los hooks de `pre-commit` pasaron en verde (`ruff format`, `ruff`, `fix end of files`, `trim trailing whitespace`, `check yaml`).
- Commit creado con identidad corporativa (`Santiago Gonzalez <kaisen.ai.santiago.cto@gmail.com>`):
  - Mensaje: `fix(ci): higiene pre-commit — sin espacios finales en docs (Fase 4)`
  - Hash: `6164c748d48f87e8693f070bc62265776f0f6451` (`6164c74`).
- Publicación: Fast-forward exitoso a `origin/main` (`54ea878..6164c74`).

---

## 4. Run Final de CI y Diagnóstico
- **ID de Run:** `36613756836`
- **URL:** https://github.com/kaisen-ai-skynet/Proyecto_Jerico/actions/runs/36613756836
- **Resultado del paso corregido (`Check formatting and repository hygiene`):** ✅ PASÓ (`pre-commit run --all-files` en verde).
- **Estado final del Run:** ❌ `failure` en el paso posterior `Run verification and publish coverage baseline`.
- **Causa del fallo posterior (reportada sin modificar por directiva):**
  ```text
  === Verificando Proyecto Jericó ===
  1. Analizando calidad de código (ruff)...
  ./scripts/verify.sh: line 6: .venv/bin/ruff: No such file or directory
  ##[error]Process completed with exit code 127.
  ```
  `scripts/verify.sh` invoca explícitamente `.venv/bin/ruff`, pero el workflow en CI instala las dependencias globalmente con `python -m pip install -e ".[dev]"` sin instanciar una carpeta `.venv`.

---

---

## 5. Ronda 2: verify.sh sin .venv en el Runner (29/09/2026 13:57)

### 5.1. Contexto y Diagnóstico
- **Workflow afectado:** `.github/workflows/ci.yml` → job `verify` → paso `Run verification and publish coverage baseline` (`./scripts/verify.sh`).
- **Fallo previo (Run 36613756836):**
  `./scripts/verify.sh: line 6: .venv/bin/ruff: No such file or directory` (exit code 127).
- **Causa raíz:** `scripts/verify.sh` asumía una carpeta fija `.venv/bin/` para `ruff`, `mypy` y `python`. En los runners de GitHub Actions, `actions/setup-python` y `pip install -e ".[dev]"` aprovisionan las herramientas en el `PATH` del runner, no en una carpeta local `.venv`.

### 5.2. Fix Aplicado
- **Archivo modificado:** `scripts/verify.sh`.
- **Lógica implementada:**
  - Si existe un virtualenv local (`.venv/bin`), se priorizan sus binarios.
  - Si `$VIRTUAL_ENV/bin` existe, se utiliza.
  - En caso contrario (runner de CI o contenedor), fallback limpio a los binarios del `PATH` (`ruff`, `mypy`, `python`/`python3`).
  - Se exporta `PYTHONPATH="src:${PYTHONPATH:-}"` para asegurar la resolución prioritaria del código fuente local.
- **Alcance:** No se modificaron `src/`, `tests/`, `pyproject.toml`, ni los archivos del árbol principal.

### 5.3. Verificación Local
- Prueba en worktree aislado (sin `.venv`, simulando el runner con PATH):
  - `pre-commit run --all-files` en verde (ruff format, ruff, eof, whitespace, check yaml).
  - `bash scripts/verify.sh` ejecutado al 100%:
    - Ruff check: `All checks passed!`
    - Mypy: `Success: no issues found in 28 source files`.
    - Pytest + Cobertura: 173 passed, 89% de cobertura en baseline.

### 5.4. Commit y Push
- **Identidad:** `Santiago Gonzalez <kaisen.ai.santiago.cto@gmail.com>`.
- **Mensaje:** `fix(ci): verify.sh robusto sin .venv (fallback PATH)`.
- **Commit SHA:** `2ef5d5b0271d83acfdd220612889d5a3b02e39bc` (`2ef5d5b`).
- **Push:** Fast-forward sobre `6164c74` a `origin/main`.

### 5.5. Resultado en GitHub Actions CI
- **Run ID:** `36615459002` (y subsecuente `36615514162`).
- **Estado final:** ✅ `success` (en verde completo).
- **URL:** https://github.com/kaisen-ai-skynet/Proyecto_Jerico/actions/runs/36615459002
- **Todos los pasos completados con éxito:**
  1. `Set up job` ✓
  2. `Checkout` ✓
  3. `Set up Python` ✓
  4. `Install project and development tools` ✓
  5. `Check formatting and repository hygiene` ✓
  6. `Run verification and publish coverage baseline` ✓

---

## 6. Estado Actual y Pendientes
- **CI en `main`:** 100% en verde (higiene pre-commit, linting ruff, tipado mypy, tests pytest y cobertura baseline).
- **Compatibilidad:** `scripts/verify.sh` ahora es completamente agnóstico al entorno, funcionando tanto en local con `.venv` como en runners CI y entornos de producción/testing basados en PATH.
