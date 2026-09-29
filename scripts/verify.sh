#!/usr/bin/env bash
set -e

# Detectar ejecutables: usar .venv local si existe, si no, fallback a PATH
if [ -d ".venv/bin" ]; then
    RUFF=".venv/bin/ruff"
    MYPY=".venv/bin/mypy"
    PYTHON=".venv/bin/python"
elif [ -n "$VIRTUAL_ENV" ] && [ -d "$VIRTUAL_ENV/bin" ]; then
    RUFF="$VIRTUAL_ENV/bin/ruff"
    MYPY="$VIRTUAL_ENV/bin/mypy"
    PYTHON="$VIRTUAL_ENV/bin/python"
else
    RUFF="ruff"
    MYPY="mypy"
    if command -v python >/dev/null 2>&1; then
        PYTHON="python"
    else
        PYTHON="python3"
    fi
fi

export PYTHONPATH="src:${PYTHONPATH:-}"

echo "=== Verificando Proyecto Jericó ==="
echo "1. Analizando calidad de código (ruff)..."
"$RUFF" check src/ tests/
echo "✅ Ruff pasó."

echo "2. Analizando tipos estáticos (mypy)..."
"$MYPY" src/ tests/
echo "✅ Mypy pasó."

echo "3. Ejecutando tests (pytest)..."
"$PYTHON" -m pytest
echo "✅ Tests pasaron."

echo "Todo listo. Proyecto en estado saludable."
