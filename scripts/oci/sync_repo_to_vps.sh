#!/usr/bin/env bash
# ==============================================================================
# Copia a la VM exactamente lo commiteado en HEAD (git archive): sin .env, sin
# archivos sin trackear, sin depender de `git push`. Se ejecuta en TU LAPTOP.
# Uso: scripts/oci/sync_repo_to_vps.sh [usuario@host]   (por defecto santiago@jerico-oracle)
# ==============================================================================

set -euo pipefail

TARGET="${1:-santiago@jerico-oracle}"
REMOTE_DIR="${REMOTE_DIR:-/opt/jerico/app}"
REPO_ROOT="$(git rev-parse --show-toplevel)"

cd "$REPO_ROOT"
rev="$(git rev-parse --short HEAD)"
if ! git diff --quiet HEAD -- . ; then
    echo "[WARN] Tienes cambios sin commitear: NO se copian (solo va HEAD $rev)."
fi

echo "[INFO] Enviando HEAD $rev a $TARGET:$REMOTE_DIR ..."
git archive --format=tar HEAD \
    | ssh "$TARGET" "mkdir -p '$REMOTE_DIR' && tar -x -C '$REMOTE_DIR' && echo '$rev' > '$REMOTE_DIR/.deployed_rev'"
ssh "$TARGET" "chmod +x '$REMOTE_DIR'/scripts/oci/*.sh && cat '$REMOTE_DIR/.deployed_rev'"
echo "[OK] Repo en $TARGET:$REMOTE_DIR (rev $rev)."
