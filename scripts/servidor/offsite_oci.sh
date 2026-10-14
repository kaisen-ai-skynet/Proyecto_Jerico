#!/usr/bin/env bash
# ==============================================================================
# Copia fuera del servidor de los backups cifrados de Jericó CRM (spec 003):
# sube a OCI Object Storage (bucket Always Free, privado) los crm-*.tar.age que
# aún no estén allí y borra los remotos con más de REMOTE_RETENTION_DAYS (máx. 30,
# tope legal J-08). Solo sube archivos con cabecera age: nunca nada en claro.
# Usa la CLI `oci` con ~/.oci/config. Idempotente. Si falla, avisa al CTO.
#
# Uso: offsite_oci.sh      (cron, justo después de backup_crm.sh)
# ==============================================================================

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"

BACKUP_CONFIG="${BACKUP_CONFIG:-$HOME/.config/jerico/backup-crm.env}"
if [ -f "$BACKUP_CONFIG" ]; then
    # shellcheck disable=SC1090  # archivo de configuración del usuario, sin secretos
    . "$BACKUP_CONFIG"
fi
BACKUP_DIR="${BACKUP_DIR:-$HOME/jerico-backups/crm}"
OCI_BUCKET="${OCI_BUCKET:-jerico-backups}"
OCI_PREFIX="crm/"
REMOTE_RETENTION_DAYS="${REMOTE_RETENTION_DAYS:-30}"
NOTIFY="${NOTIFY:-$HERE/notify_cto.sh}"
export PATH="$HOME/.local/bin:$PATH"

fail() {
    echo "[ERROR] $1" >&2
    "$NOTIFY" "🔴 Jericó CRM: falló la copia de backups fuera del servidor ($(hostname)): $1" >/dev/null \
        || echo "[WARN] Tampoco se pudo avisar al CTO." >&2
    exit 1
}
set -E
trap 'fail "error inesperado en la línea $LINENO de offsite_oci.sh."' ERR

case "$REMOTE_RETENTION_DAYS" in
    '' | *[!0-9]*) fail "REMOTE_RETENTION_DAYS debe ser un número de días." ;;
esac
[ "$REMOTE_RETENTION_DAYS" -le 30 ] || REMOTE_RETENTION_DAYS=30
[ "$REMOTE_RETENTION_DAYS" -ge 1 ] || fail "REMOTE_RETENTION_DAYS debe ser al menos 1."
command -v oci > /dev/null || fail "no está la CLI oci."

errlog="$(mktemp)"
trap 'rm -f "$errlog"' EXIT
# La CLI avisa por stderr cuando el bucket está vacío; stdout queda vacío.
remote_json="$(oci os object list --bucket-name "$OCI_BUCKET" --prefix "$OCI_PREFIX" --all \
    --query 'data[].name' --raw-output 2> "$errlog")" \
    || fail "no se pudo listar el bucket $OCI_BUCKET: $(tail -n 1 "$errlog")"
remote="$(python3 -c 'import json,sys; d=json.loads(sys.stdin.read().strip() or "[]") or []; print("\n".join(d))' <<< "$remote_json")"

uploaded=0
for file in "$BACKUP_DIR"/crm-????????T??????Z.tar.age; do
    [ -e "$file" ] || continue
    name="$(basename "$file")"
    grep -qxF "$OCI_PREFIX$name" <<< "$remote" && continue
    is_age_file "$file" || fail "$name no tiene cabecera age; no se sube nada en claro."
    out="$(oci os object put --bucket-name "$OCI_BUCKET" --name "$OCI_PREFIX$name" --file "$file" \
        --no-overwrite 2>&1)" || fail "no se pudo subir $name: $(tail -n 1 <<< "$out")"
    uploaded=$((uploaded + 1))
done

cutoff="${OCI_PREFIX}crm-$(date -u -d "-$REMOTE_RETENTION_DAYS days" +%Y%m%dT%H%M%SZ).tar.age"
removed=0
while IFS= read -r obj; do
    [[ "$obj" =~ ^crm/crm-[0-9]{8}T[0-9]{6}Z\.tar\.age$ ]] || continue
    if [[ "$obj" < "$cutoff" ]]; then
        out="$(oci os object delete --bucket-name "$OCI_BUCKET" --name "$obj" --force 2>&1)" \
            || fail "no se pudo borrar $obj: $(tail -n 1 <<< "$out")"
        removed=$((removed + 1))
    fi
done <<< "$remote"

echo "[OK] Fuera del servidor (OCI $OCI_BUCKET): $uploaded subido(s), $removed antiguo(s) borrado(s) (retención $REMOTE_RETENTION_DAYS días)."
