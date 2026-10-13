#!/usr/bin/env bash
# ==============================================================================
# Backup cifrado del volumen jerico_crm_data en kaisen-server (spec 002, SRV-01..09).
#
#   1. Instantánea consistente de crm.db con la API de backup de SQLite, dentro
#      del contenedor vivo (crm_volume.py pack), más el resto del volumen.
#   2. El tar sale por una tubería directo a `age -R`: nunca queda en disco sin cifrar.
#   3. Comprueba la cabecera age, renombra de forma atómica y aplica 600/700.
#   4. Retención por la fecha del nombre (RETENTION_DAYS, máx. 30); siempre se
#      conserva el más reciente.
#   Si falla, avisa al CTO (notify_cto.sh) y sale con código != 0.
#
# Uso: backup_crm.sh   (cron diario; configuración en BACKUP_CONFIG, sin secretos)
#      ALLOW_STOPPED=1 backup_crm.sh   → con el contenedor detenido (corte de migración)
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
CONTAINER="${CONTAINER:-jerico-crm}"
DATA_DIR="${DATA_DIR:-/app/crm-data}"
VOLUME="${VOLUME:-jerico_crm_data}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/jerico-backups/crm}"
AGE_RECIPIENTS_FILE="${AGE_RECIPIENTS_FILE:-$HOME/.config/jerico/backup-recipients.txt}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
NOTIFY="${NOTIFY:-$HERE/notify_cto.sh}"
MAX_RETENTION_DAYS=30  # tope legal J-08 (spec 001)

fail() {
    echo "[ERROR] $1" >&2
    "$NOTIFY" "🔴 Jericó CRM: falló el backup en $(hostname): $1" >/dev/null \
        || echo "[WARN] Tampoco se pudo avisar al CTO." >&2
    exit 1
}

case "$RETENTION_DAYS" in
    '' | *[!0-9]*) fail "RETENTION_DAYS debe ser un número entero de días (vale '$RETENTION_DAYS')." ;;
esac
[ "$RETENTION_DAYS" -ge 1 ] || fail "RETENTION_DAYS debe ser al menos 1."
if [ "$RETENTION_DAYS" -gt "$MAX_RETENTION_DAYS" ]; then
    echo "[WARN] RETENTION_DAYS=$RETENTION_DAYS supera el tope de $MAX_RETENTION_DAYS días; uso $MAX_RETENTION_DAYS."
    RETENTION_DAYS=$MAX_RETENTION_DAYS
fi
recipients_error="$(check_recipients "$AGE_RECIPIENTS_FILE" 2>&1)" || fail "$recipients_error"

umask 077
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

exec 9> "$BACKUP_DIR/.lock"
if ! flock -n 9; then
    echo "[ERROR] Ya hay un backup en curso (lock $BACKUP_DIR/.lock)." >&2
    exit 1
fi

state="$(container_state "$CONTAINER")" || fail "el contenedor $CONTAINER no existe."
code="$(cat "$HERE/crm_volume.py")"
if [ "${state%% *}" = "running" ]; then
    pack() { docker exec "$CONTAINER" python -c "$code" pack "$DATA_DIR"; }
elif [ "${ALLOW_STOPPED:-0}" = "1" ]; then
    # Corte de migración: contenedor detenido a propósito; se lee el volumen con su imagen.
    image="$(docker inspect -f '{{.Config.Image}}' "$CONTAINER")" || fail "no se pudo leer la imagen de $CONTAINER."
    pack() { docker run --rm -v "$VOLUME:/data" "$image" python -c "$code" pack /data; }
else
    fail "el contenedor $CONTAINER no está corriendo (estado: $state)."
fi

name="crm-$(date -u +%Y%m%dT%H%M%SZ).tar.age"
partial="$BACKUP_DIR/.$name.partial"
trap 'rm -f "$partial"' EXIT

if ! pack | age -R "$AGE_RECIPIENTS_FILE" -o "$partial"; then
    fail "no se pudo empaquetar o cifrar los datos (ver la salida de arriba)."
fi
is_age_file "$partial" || fail "el resultado no tiene la cabecera age; se descarta."
mv "$partial" "$BACKUP_DIR/$name"
chmod 600 "$BACKUP_DIR/$name"
echo "[OK] Backup $BACKUP_DIR/$name ($(du -h "$BACKUP_DIR/$name" | cut -f1))."

# Retención: los nombres llevan la fecha UTC, así que se comparan como texto.
cutoff="crm-$(date -u -d "-$RETENTION_DAYS days" +%Y%m%dT%H%M%SZ).tar.age"
removed=0
for file in "$BACKUP_DIR"/crm-????????T??????Z.tar.age; do
    base="$(basename "$file")"
    if [ "$base" != "$name" ] && [[ "$base" < "$cutoff" ]]; then
        rm -f "$file"
        removed=$((removed + 1))
    fi
done
echo "[OK] Retención de $RETENTION_DAYS días: $removed backup(s) antiguos borrados."
