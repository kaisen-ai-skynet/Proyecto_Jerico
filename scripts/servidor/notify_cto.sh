#!/usr/bin/env bash
# ==============================================================================
# Aviso al CTO (spec 002, SRV-14 y SRV-15): Telegram (sendMessage) y, si falla,
# correo SMTP. Usa las credenciales del .env del despliegue, que se lee SIN
# ejecutarlo (nunca `source`). El token y la clave SMTP van a curl por stdin
# (-K -): no aparecen en `ps` ni en los logs.
#
# Uso: notify_cto.sh "<texto>"          (ENV_FILE=~/jerico/.env por defecto)
# Sale con 0 si algún canal entregó el aviso y con 1 si fallaron todos.
# ==============================================================================

set -euo pipefail

ENV_FILE="${ENV_FILE:-$HOME/jerico/.env}"
text="${1:?uso: notify_cto.sh \"<texto>\"}"

if [ ! -r "$ENV_FILE" ]; then
    echo "[ERROR] No se puede leer $ENV_FILE: no hay credenciales para avisar." >&2
    exit 1
fi

# Valor literal de CLAVE=valor (última aparición): entre comillas, lo de dentro; sin
# comillas, hasta un comentario ` # ...`.
env_get() {
    local line value
    line="$(grep -E "^[[:space:]]*(export[[:space:]]+)?$1=" "$ENV_FILE" | tail -n 1 || true)"
    value="${line#*=}"
    value="${value%$'\r'}"
    case "$value" in
        \"*) value="${value#\"}"; value="${value%%\"*}" ;;
        \'*) value="${value#\'}"; value="${value%%\'*}" ;;
        *)
            value="${value%%[[:space:]]#*}"
            value="${value%"${value##*[![:space:]]}"}"
            ;;
    esac
    printf '%s' "$value"
}

# Escapa un valor para una cadena entre comillas de un archivo de configuración de curl.
curl_quote() {
    local v="${1//\\/\\\\}"
    printf '"%s"' "${v//\"/\\\"}"
}

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
printf '%s\n' "$text" > "$work/text"

send_telegram() {
    local token chat
    token="$(env_get JERICO_CRM_TELEGRAM_BOT_TOKEN)"
    chat="$(env_get JERICO_CRM_SEED_CTO_TELEGRAM_ID)"
    if [ -z "$token" ] || [ -z "$chat" ]; then
        echo "[WARN] Telegram sin configurar en $ENV_FILE." >&2
        return 1
    fi
    printf 'url = %s\n' "$(curl_quote "https://api.telegram.org/bot$token/sendMessage")" \
        | curl -sS --max-time 20 -K - \
            --data-urlencode "text@$work/text" \
            --data-urlencode "chat_id=$chat" > "$work/telegram.json" 2> "$work/telegram.err" \
        || { echo "[WARN] Telegram no respondió: $(tail -n 1 "$work/telegram.err")" >&2; return 1; }
    grep -q '"ok":true' "$work/telegram.json" \
        || { echo "[WARN] Telegram rechazó el aviso." >&2; return 1; }
}

send_email() {
    local host port security user pass from to scheme
    host="$(env_get JERICO_CRM_SMTP_HOST)"
    from="$(env_get JERICO_CRM_SMTP_FROM)"
    to="$(env_get JERICO_CRM_SEED_CTO_EMAIL)"
    if [ -z "$host" ] || [ -z "$from" ] || [ -z "$to" ]; then
        echo "[WARN] Correo SMTP sin configurar en $ENV_FILE." >&2
        return 1
    fi
    security="$(env_get JERICO_CRM_SMTP_SECURITY)"
    port="$(env_get JERICO_CRM_SMTP_PORT)"
    user="$(env_get JERICO_CRM_SMTP_USERNAME)"
    pass="$(env_get JERICO_CRM_SMTP_PASSWORD)"
    if [ "$security" = "ssl" ]; then
        scheme="smtps"; port="${port:-465}"
    else
        scheme="smtp"; port="${port:-587}"
    fi
    {
        printf 'From: %s\r\nTo: %s\r\n' "$from" "$to"
        printf 'Subject: [Jerico] %s\r\n' "$(head -n 1 "$work/text" | tr -cd '[:print:]' | cut -c1-120)"
        printf 'Date: %s\r\nMIME-Version: 1.0\r\n' "$(LC_ALL=C date -R)"
        printf 'Content-Type: text/plain; charset=UTF-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\n'
        cat "$work/text"
    } > "$work/mail"
    {
        if [ -n "$user" ]; then
            printf 'user = %s\n' "$(curl_quote "$user:$pass")"
        fi
    } | curl -sS --max-time 30 -K - --url "$scheme://$host:$port" --ssl-reqd \
        --mail-from "$from" --mail-rcpt "$to" --upload-file "$work/mail" 2> "$work/smtp.err" \
        || { echo "[WARN] El correo falló: $(tail -n 1 "$work/smtp.err")" >&2; return 1; }
}

if send_telegram; then
    echo "[OK] Aviso enviado por Telegram."
elif send_email; then
    echo "[OK] Aviso enviado por correo."
else
    echo "[ERROR] No se pudo avisar al CTO por ningún canal." >&2
    exit 1
fi
