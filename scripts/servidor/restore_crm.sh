#!/usr/bin/env bash
# ==============================================================================
# Prueba de restauración y restauración real de Jericó CRM (spec 003, SRV-10, SRV-11).
#
#   restore_crm.sh verify <backup.tar.age> <identidad>
#       En la laptop del CTO (donde está la llave privada): descifra en un temporal,
#       comprueba crm.db (integrity_check + tablas) e imprime un resumen. No toca nada.
#
#   restore_crm.sh apply <backup.tar.age|backup.tar> [identidad]
#       En el servidor. Sin CONFIRM=1 solo muestra lo que haría. Con CONFIRM=1:
#       verifica el archivo, detiene el contenedor, guarda lo actual en
#       pre-restore-*.tar.age (cifrado), reemplaza el volumen, arranca y espera healthy.
#       SKIP_PRE_RESTORE=1 omite la copia previa (solo para un volumen nuevo y vacío).
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
VOLUME="${VOLUME:-jerico_crm_data}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/jerico-backups/crm}"
AGE_RECIPIENTS_FILE="${AGE_RECIPIENTS_FILE:-$HOME/.config/jerico/backup-recipients.txt}"
HEALTH_WAIT_S="${HEALTH_WAIT_S:-300}"

usage() {
    sed -n '4,13p' "$0" >&2
    exit 2
}
die() {
    echo "[ERROR] $1" >&2
    exit 1
}

mode="${1:-}"
archive="${2:-}"
identity="${3:-}"
[ -n "$mode" ] && [ -n "$archive" ] || usage
[ -f "$archive" ] || die "no existe $archive"

umask 077
work="$(mktemp -d "${TMPDIR:-/tmp}/jerico-restore-XXXXXX")"
trap 'rm -rf "$work"' EXIT

# Deja en $work/crm.tar el contenido en claro y lo verifica.
prepare() {
    case "$archive" in
        *.age)
            [ -n "$identity" ] || die "falta la identidad age para descifrar $archive"
            [ -r "$identity" ] || die "no se puede leer la identidad $identity"
            is_age_file "$archive" || die "$archive no tiene la cabecera age"
            age -d -i "$identity" -o "$work/crm.tar" "$archive" || die "no se pudo descifrar $archive"
            ;;
        *.tar) cp "$archive" "$work/crm.tar" ;;
        *) die "formato no reconocido: $archive (se espera .tar.age o .tar)" ;;
    esac
    python3 "$HERE/crm_volume.py" verify "$work/crm.tar" || die "el backup no pasó la verificación"
}

volume_python() {  # volume_python <subcomando>: crm_volume.py dentro de la imagen, con el volumen
    docker run --rm -i -v "$VOLUME:/data" "$image" python -c "$(cat "$HERE/crm_volume.py")" "$1" /data
}

case "$mode" in
    verify)
        prepare
        echo "[OK] RESTAURACIÓN VERIFICADA: $archive"
        ;;
    apply)
        prepare
        if [ "${CONFIRM:-0}" != "1" ]; then
            echo "[PLAN] Se detendría $CONTAINER, se guardaría el volumen $VOLUME en"
            echo "       $BACKUP_DIR/pre-restore-*.tar.age, se reemplazaría por $archive y se arrancaría."
            echo "[PLAN] Para ejecutarlo: CONFIRM=1 $0 apply $archive ${identity:-}"
            exit 0
        fi
        if [ "${SKIP_PRE_RESTORE:-0}" != "1" ]; then
            recipients_error="$(check_recipients "$AGE_RECIPIENTS_FILE" 2>&1)" || die "$recipients_error"
        fi
        image="$(docker inspect -f '{{.Config.Image}}' "$CONTAINER")" || die "no existe el contenedor $CONTAINER"
        echo "[INFO] Deteniendo $CONTAINER..."
        docker stop "$CONTAINER" > /dev/null
        if [ "${SKIP_PRE_RESTORE:-0}" != "1" ]; then
            mkdir -p "$BACKUP_DIR"
            pre="$BACKUP_DIR/pre-restore-$(date -u +%Y%m%dT%H%M%SZ).tar.age"
            if ! volume_python pack-raw | age -R "$AGE_RECIPIENTS_FILE" -o "$pre" || ! is_age_file "$pre"; then
                rm -f "$pre"
                docker start "$CONTAINER" > /dev/null
                die "no se pudo guardar el estado actual; no se restauró nada y $CONTAINER volvió a arrancar."
            fi
            chmod 600 "$pre"
            echo "[OK] Estado anterior guardado en $pre"
        fi
        volume_python unpack < "$work/crm.tar" || die "falló la extracción; revisa $VOLUME antes de arrancar (copia previa: ${pre:-ninguna})."
        echo "[OK] Volumen $VOLUME restaurado desde $archive. Arrancando $CONTAINER..."
        docker start "$CONTAINER" > /dev/null
        waited=0
        while :; do
            state="$(container_state "$CONTAINER" || true)"
            [ "$state" = "running healthy" ] && break
            if [ "$waited" -ge "$HEALTH_WAIT_S" ]; then
                die "$CONTAINER no llegó a healthy en ${HEALTH_WAIT_S}s (estado: $state). Revisa: docker logs --tail 50 $CONTAINER"
            fi
            sleep 5
            waited=$((waited + 5))
        done
        echo "[OK] $CONTAINER healthy con los datos restaurados."
        ;;
    *) usage ;;
esac
