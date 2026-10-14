#!/usr/bin/env bash
# ==============================================================================
# Vigía de salud de jerico-crm (spec 003, SRV-12, SRV-13). Corre desde cron cada 5 min.
#
#   OK         healthy
#   ARRANCANDO starting (fallo solo si dura más de STARTING_GRACE_MIN)
#   FALLO      unhealthy, detenido o inexistente
#
# Avisa al pasar a FALLO, recuerda cada REMIND_MIN mientras siga y avisa al
# recuperarse con la duración. Si el aviso falla, se reintenta en la siguiente pasada.
# NOW_EPOCH fija el reloj (tests).
# ==============================================================================

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"

CONTAINER="${CONTAINER:-jerico-crm}"
STATE_FILE="${STATE_FILE:-$HOME/.local/state/jerico/healthwatch.state}"
REMIND_MIN="${REMIND_MIN:-60}"
STARTING_GRACE_MIN="${STARTING_GRACE_MIN:-10}"
NOTIFY="${NOTIFY:-$HERE/notify_cto.sh}"
now="${NOW_EPOCH:-$(date +%s)}"
host="$(hostname)"

# Estado previo: status (OK|STARTING|FAIL), since (epoch), alerted (epoch del último aviso, 0 = ninguno).
prev="OK" since="$now" alerted=0
if [ -f "$STATE_FILE" ]; then
    while IFS='=' read -r key value; do
        case "$key" in
            status) prev="$value" ;;
            since) since="$value" ;;
            alerted) alerted="$value" ;;
        esac
    done < "$STATE_FILE"
fi

save() {  # save <status> <since> <alerted>
    mkdir -p "$(dirname "$STATE_FILE")"
    printf 'status=%s\nsince=%s\nalerted=%s\n' "$1" "$2" "$3" > "$STATE_FILE.tmp"
    mv "$STATE_FILE.tmp" "$STATE_FILE"
}

minutes() { echo $(( ($1) / 60 )); }
clock() { date -d "@$1" +%H:%M; }

notify() {
    if "$NOTIFY" "$1" > /dev/null; then
        return 0
    fi
    echo "[ERROR] No se pudo avisar: $1" >&2
    return 1
}

if ! docker info > /dev/null 2>&1; then
    current="FAIL"; detail="Docker no responde"
elif state="$(container_state "$CONTAINER")"; then
    case "$state" in
        "running healthy") current="OK" ;;
        "running starting") current="STARTING" ;;
        *) current="FAIL"; detail="estado: $state" ;;
    esac
else
    current="FAIL"; detail="el contenedor no existe"
fi

if [ "$current" = "STARTING" ]; then
    if [ "$prev" = "FAIL" ]; then
        current="FAIL"; detail="sigue arrancando tras el fallo"
    elif [ "$prev" != "STARTING" ]; then
        save STARTING "$now" 0
        exit 0
    elif [ $((now - since)) -gt $((STARTING_GRACE_MIN * 60)) ]; then
        current="FAIL"; detail="lleva $(minutes "now - since") min arrancando (starting)"
        prev="STARTING_EXPIRED"
    else
        exit 0
    fi
fi

case "$current" in
    OK)
        if [ "$prev" = "FAIL" ] && [ "$alerted" -gt 0 ]; then
            notify "🟢 Jericó CRM en $host: recuperado tras $(minutes "now - since") min (caído desde las $(clock "$since"))." \
                || exit 1
        fi
        [ "$prev" = "OK" ] && [ -f "$STATE_FILE" ] || save OK "$now" 0
        ;;
    FAIL)
        if [ "$prev" = "FAIL" ]; then
            [ $((now - alerted)) -ge $((REMIND_MIN * 60)) ] || exit 0
            message="🔴 Jericó CRM en $host sigue con fallo ($detail) desde las $(clock "$since"), $(minutes "now - since") min."
        else
            [ "$prev" = "STARTING_EXPIRED" ] || since="$now"
            message="🔴 Jericó CRM en $host: $detail desde las $(clock "$since")."
        fi
        message="$message Revisa: docker logs --tail 50 $CONTAINER (runbook docs/despliegue-servidor-kaisen.md §6)."
        if notify "$message"; then
            save FAIL "$since" "$now"
        else
            save FAIL "$since" "$alerted"
            exit 1
        fi
        ;;
esac
