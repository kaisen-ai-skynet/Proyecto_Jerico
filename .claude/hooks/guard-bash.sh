#!/usr/bin/env bash
# Guardián de comandos destructivos (equipo SDD · Claude Code)
set -u
exec python3 -c '
import json, re, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
cmd = (data.get("tool_input") or {}).get("command") or ""
if not cmd:
    sys.exit(0)
blocked = [
    r"(^|[^0-9A-Za-z_.-])rm([\s]|$)",
    r"(^|[^0-9A-Za-z_.-])sudo([\s]|$)",
    r"git\s+push(\s|$)",
    r"git\s+reset\s+--hard(\s|$)",
    r"(^|[^0-9A-Za-z_.-])(pkill|kill)([\s]|$)",
]
for p in blocked:
    if re.search(p, cmd):
        print("BLOQUEADO por el guardián SDD: comando destructivo no permitido («%s»). Reporta el bloqueo al coordinador." % cmd, file=sys.stderr)
        sys.exit(2)
sys.exit(0)
'
