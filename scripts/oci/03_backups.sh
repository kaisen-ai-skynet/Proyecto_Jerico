#!/usr/bin/env bash
# ==============================================================================
# 03 · Instala el backup nocturno de PostgreSQL (timer systemd) y lo prueba
# ==============================================================================
# Se ejecuta como root con /etc/jerico/backup.env y /etc/jerico/rclone.conf ya
# creados a partir de deploy/oci/*.example (guía, Parte H). Idempotente.
# ==============================================================================

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/jerico/app}"
UNIT_SRC="$APP_DIR/deploy/oci/systemd"

ok() { echo "[OK] $1"; }
fail() { echo "[ERROR] $1" >&2; exit 1; }

[ "$EUID" -eq 0 ] || fail "Ejecútalo con sudo."
for f in /etc/jerico/backup.env /etc/jerico/rclone.conf; do
    [ -f "$f" ] || fail "Falta $f (copia el .example de deploy/oci/ y complétalo)."
    chown root:root "$f"
    chmod 600 "$f"
done
grep -q 'REEMPLAZAR\|<NAMESPACE>' /etc/jerico/backup.env /etc/jerico/rclone.conf \
    && fail "Quedan valores REEMPLAZAR/<NAMESPACE> sin completar en /etc/jerico/."
grep -q '^AGE-SECRET-KEY' /etc/jerico/backup.env \
    && fail "backup.env contiene una llave PRIVADA age. Bórrala: en la VM solo va la pública."

# shellcheck disable=SC1091
. /etc/jerico/backup.env
export RCLONE_CONFIG="${RCLONE_CONFIG:-/etc/jerico/rclone.conf}"
rclone lsd "${RCLONE_REMOTE%%:*}:" >/dev/null || fail "rclone no puede listar ${RCLONE_REMOTE%%:*}: revisa llaves y endpoint."
ok "Remoto rclone accesible."

chmod 750 "$APP_DIR/scripts/oci/backup_postgres.sh"
install -m 644 "$UNIT_SRC/jerico-backup-postgres.service" /etc/systemd/system/
install -m 644 "$UNIT_SRC/jerico-backup-postgres.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now jerico-backup-postgres.timer
ok "Timer instalado: $(systemctl list-timers jerico-backup-postgres.timer --no-legend | awk '{print $1, $2, $3}')"

echo "[INFO] Ejecutando un backup de prueba ahora..."
if ! systemctl start jerico-backup-postgres.service; then
    journalctl -u jerico-backup-postgres.service -n 15 --no-pager
    fail "El backup de prueba falló."
fi
journalctl -u jerico-backup-postgres.service -n 8 --no-pager
ok "Backup de prueba completado y copiado fuera de la VM."
