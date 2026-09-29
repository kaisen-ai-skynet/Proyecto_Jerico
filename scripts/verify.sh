#!/usr/bin/env bash
set -e

echo "=== Verificando Proyecto Jericó ==="
echo "1. Analizando calidad de código (ruff)..."
.venv/bin/ruff check src/ tests/
echo "✅ Ruff pasó."

echo "2. Analizando tipos estáticos (mypy)..."
.venv/bin/mypy src/ tests/
echo "✅ Mypy pasó."

echo "3. Ejecutando tests (pytest)..."
.venv/bin/python -m pytest
echo "✅ Tests pasaron."

echo "Todo listo. Proyecto en estado saludable."
