#!/usr/bin/env bash
# ==============================================================================
# Backup nocturno de PostgreSQL: pg_dump → cifrado age → fuera de la VM (rclone)
# ==============================================================================
# Lo dispara el timer systemd jerico-backup-postgres.timer (03_backups.sh lo
# instala). Headless: sin agente ni LLM; si falla, systemd marca la unidad
# como failed y el error queda en `journalctl -u jerico-backup-postgres`.
#
# Configuración en /etc/jerico/backup.env (fuera de Git, 600):
#   AGE_RECIPIENT=age1...            # llave PÚBLICA age; la privada nunca entra a la VM
#   RCLONE_REMOTE=oci-backups:jerico-backups   # remoto:bucket configurado en rclone
#   RCLONE_CONFIG=/etc/jerico/rclone.conf
#   LOCAL_RETENTION_DAYS=7           # opcional
#   REMOTE_RETENTION_DAYS=30         # opcional
# ==============================================================================

set -euo pipefail

CONFIG_FILE="${CONFIG_FILE:-/etc/jerico/backup.env}"
BACKUP_DIR="${BACKUP_DIR:-/opt/jerico/backups}"
CONTAINER="${PG_CONTAINER:-jerico-postgres}"
PG_USER="${PG_USER:-jerico}"
PG_DB="${PG_DB:-jerico}"

log() { echo "[$(date '+%F %T')] $1"; }
fail() { log "ERROR: $1" >&2; exit 1; }

[ -r "$CONFIG_FILE" ] || fail "No se puede leer $CONFIG_FILE."
# shellcheck disable=SC1090
. "$CONFIG_FILE"
: "${AGE_RECIPIENT:?AGE_RECIPIENT vacío en $CONFIG_FILE}"
: "${RCLONE_REMOTE:?RCLONE_REMOTE vacío en $CONFIG_FILE}"
export RCLONE_CONFIG="${RCLONE_CONFIG:-/etc/jerico/rclone.conf}"
LOCAL_RETENTION_DAYS="${LOCAL_RETENTION_DAYS:-7}"
REMOTE_RETENTION_DAYS="${REMOTE_RETENTION_DAYS:-30}"

case "$AGE_RECIPIENT" in
    age1*) ;;
    *) fail "AGE_RECIPIENT debe ser una llave pública age (age1...), nunca la privada." ;;
esac

# Una sola ejecución a la vez
exec 9>/run/lock/jerico-backup-postgres.lock
flock -n 9 || fail "Ya hay un backup en curso."

docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -q true \
    || fail "El contenedor $CONTAINER no está corriendo."

mkdir -p "$BACKUP_DIR"
umask 077
stamp="$(date '+%Y%m%d_%H%M%S')"
target="$BACKUP_DIR/jerico_${stamp}.dump.age"
partial="$target.partial"

log "Volcando $PG_DB (formato custom) y cifrando con age..."
docker exec "$CONTAINER" pg_dump -U "$PG_USER" -d "$PG_DB" -Fc \
    | age -r "$AGE_RECIPIENT" -o "$partial"

[ -s "$partial" ] || fail "El volcado cifrado salió vacío."
head -c 21 "$partial" | grep -q '^age-encryption.org/v1' || fail "El archivo no tiene cabecera age."
mv "$partial" "$target"
log "Backup local: $target ($(du -h "$target" | cut -f1))."

log "Copiando fuera de la VM a $RCLONE_REMOTE ..."
rclone copy "$target" "$RCLONE_REMOTE" --no-traverse
rclone lsf "$RCLONE_REMOTE" --include "$(basename "$target")" | grep -q . \
    || fail "La copia remota no aparece en $RCLONE_REMOTE."
log "Copia remota verificada."

find "$BACKUP_DIR" -maxdepth 1 -name 'jerico_*.dump.age' -mtime +"$LOCAL_RETENTION_DAYS" -delete
find "$BACKUP_DIR" -maxdepth 1 -name '*.partial' -mmin +60 -delete
rclone delete "$RCLONE_REMOTE" --include 'jerico_*.dump.age' --min-age "${REMOTE_RETENTION_DAYS}d"
log "Retención aplicada (local ${LOCAL_RETENTION_DAYS} d, remoto ${REMOTE_RETENTION_DAYS} d). Fin."
