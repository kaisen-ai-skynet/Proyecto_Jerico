#!/usr/bin/env bash
# ==============================================================================
# Lint reproducible de scripts/oci/*.sh: `bash -n` + ShellCheck (todas las
# severidades). Instala shellcheck-py en un venv TEMPORAL fuera del proyecto
# (no toca .venv) y lo reutiliza en ejecuciones siguientes. No necesita sudo.
# Uso: scripts/oci/lint.sh        (sale con código != 0 si hay hallazgos)
# ==============================================================================

set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
LINT_VENV="${LINT_VENV:-${TMPDIR:-/tmp}/jerico-shellcheck-venv}"
SC="$LINT_VENV/bin/shellcheck"

if [ ! -x "$SC" ]; then
    echo "[INFO] Instalando shellcheck-py en $LINT_VENV ..."
    python3 -m venv "$LINT_VENV" >/dev/null 2>&1 || true
    if [ -x "$LINT_VENV/bin/pip" ]; then
        "$LINT_VENV/bin/pip" install -q shellcheck-py
    elif command -v uv >/dev/null; then
        # Algunos Python del sistema crean el venv sin pip (sin ensurepip).
        uv pip install -q --python "$LINT_VENV/bin/python" shellcheck-py
    else
        echo "[ERROR] El venv no tiene pip y no hay uv: instala python3-venv o uv." >&2
        exit 1
    fi
fi

cd "$REPO_ROOT"
"$SC" --version | sed -n 2p
for f in scripts/oci/*.sh; do bash -n "$f"; done
echo "[OK] bash -n sin errores de sintaxis."
"$SC" scripts/oci/*.sh
echo "[OK] ShellCheck sin hallazgos en $(find scripts/oci -name '*.sh' | wc -l) scripts."
