#!/usr/bin/env bash
# Guardián del planner (equipo SDD · Claude Code): escritura SOLO en specs/** y docs/constitution.md
set -u
exec python3 -c '
import json, os, sys
project = sys.argv[1]
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
ti = data.get("tool_input") or {}
f = ti.get("file_path") or ti.get("notebook_path") or ""
if not f:
    sys.exit(0)
absp = os.path.normpath(f if os.path.isabs(f) else os.path.join(project, f))
rel = os.path.relpath(absp, os.path.normpath(project))
parts = rel.split(os.sep)
if rel == "docs/constitution.md" or rel.endswith("/docs/constitution.md") or "specs" in parts[:-1]:
    sys.exit(0)
print("BLOQUEADO por el guardián del planner: «%s» está fuera de specs/ y docs/constitution.md. No busques otro camino: reporta el bloqueo al coordinador." % rel, file=sys.stderr)
sys.exit(2)
' "${CLAUDE_PROJECT_DIR:-$(pwd)}"
