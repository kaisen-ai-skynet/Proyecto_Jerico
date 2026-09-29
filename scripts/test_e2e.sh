#!/usr/bin/env bash
set -e

# Este script prueba el servidor local usando curl.
# Requiere que el servidor esté corriendo (make run o python -m jerico)

API_TOKEN=${JERICO_API_TOKEN:-"changeme"}
PORT=${JERICO_PORT:-8000}
HOST=${JERICO_HOST:-"127.0.0.1"}

if ! curl -s "http://$HOST:$PORT/health" > /dev/null; then
    echo "❌ Error: El servidor no está corriendo en http://$HOST:$PORT"
    echo "   Inícialo con: .venv/bin/python -m jerico"
    exit 1
fi

echo "✅ Servidor detectado. Ejecutando prueba E2E (L0, sin LLM)..."

RESPONSE=$(curl -s -X POST "http://$HOST:$PORT/api/v1/ask" \
    -H "Authorization: Bearer $API_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"prompt": "Hola", "session_id": "test_e2e_01"}')

echo "$RESPONSE" | grep -i "level" > /dev/null || (echo "❌ Fallo en la respuesta L0" && exit 1)

echo "✅ Prueba E2E (L0) exitosa: $RESPONSE"

echo "✅ E2E Completo."
