#!/usr/bin/env bash
# ==============================================================================
# 00 · Reintentar la creación de la VM A1 ante "Out of host capacity"
# ==============================================================================
# En sa-bogota-1 la única VM Always Free es A1.Flex (la E2.1.Micro no se ofrece)
# y suele estar sin capacidad. Este script la pide en bucle hasta conseguirla.
#
# Dónde correrlo:
#   - Recomendado: en kaisen-server (24/7), con la CLI `oci` configurada en
#     ~/.oci/config (llave de API creada por el CTO, chmod 600). Dentro de tmux
#     o como servicio; ver docs/dia-1-oci.md.
#   - Alternativa: OCI Cloud Shell (ya autenticada), pero la sesión se cae a
#     las pocas horas.
#
# Uso:
#   export SSH_PUBKEY_FILE=~/.ssh/id_ed25519_kaisen.pub
#   bash 00_retry_launch_a1.sh            # bucle sin fin (MAX_ATTEMPTS=0)
# COMPARTMENT_ID y SUBNET_ID son opcionales: si faltan, se buscan el
# compartimento `kaisen-jerico` (o COMPARTMENT_NAME) y su subred pública.
#
# Opcional: TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID para avisar al conseguirla.
# Nunca crea más de una VM con el mismo nombre y se niega a pedir más de lo
# Always Free (2 OCPU / 12 GB / 200 GB). Pide 1 OCPU / 6 GB por defecto: ese
# hueco aparece antes; luego se amplía a 2/12 desde la consola (Edit shape).
# ==============================================================================

set -euo pipefail

COMPARTMENT_ID="${COMPARTMENT_ID:-${OCI_TENANCY:-}}"
SUBNET_ID="${SUBNET_ID:-}"
SSH_PUBKEY_FILE="${SSH_PUBKEY_FILE:-$HOME/.ssh/id_ed25519_kaisen.pub}"
DISPLAY_NAME="${DISPLAY_NAME:-jerico-core-oracle-01}"
OCPUS="${OCPUS:-1}"
MEMORY_GB="${MEMORY_GB:-6}"
BOOT_GB="${BOOT_GB:-50}"
RETRY_SECONDS="${RETRY_SECONDS:-300}"   # + 0–59 s aleatorios; menos dispara 429
MAX_ATTEMPTS="${MAX_ATTEMPTS:-0}"       # 0 = sin límite
FAULT_DOMAIN="${FAULT_DOMAIN:-}"        # vacío = Oracle elige entre los 3

fail() { echo "[ERROR] $1" >&2; exit 1; }
log() { echo "[$(date '+%d/%m %H:%M:%S')] $1"; }
notify() {
    [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ] || return 0
    # El token va por stdin (-K -): no aparece en `ps`.
    printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$TELEGRAM_BOT_TOKEN" \
        | curl -fsS -m 15 -K - --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
            --data-urlencode "text=$1" >/dev/null || true
}
pause() { sleep $(( $1 + RANDOM % 60 )); }

command -v oci >/dev/null || fail "No hay CLI oci (instálala y configura ~/.oci/config, o usa Cloud Shell)."
# Sin OCIDs explícitos, se resuelven por nombre: compartimento y su subred pública
if [ -z "$COMPARTMENT_ID" ]; then
    COMPARTMENT_ID="$(oci iam compartment list --name "${COMPARTMENT_NAME:-kaisen-jerico}" \
        --compartment-id-in-subtree true --query 'data[0].id' --raw-output 2>/dev/null || true)"
fi
[ -n "$COMPARTMENT_ID" ] || fail "Define COMPARTMENT_ID (OCID del compartimento kaisen-jerico)."
if [ -z "$SUBNET_ID" ]; then
    # shellcheck disable=SC2016  # las comillas invertidas son literales de JMESPath
    SUBNET_ID="$(oci network subnet list --compartment-id "$COMPARTMENT_ID" \
        --query 'data[?"prohibit-public-ip-on-vnic"==`false`] | [0].id' --raw-output 2>/dev/null || true)"
fi
[ -n "$SUBNET_ID" ] || fail "Define SUBNET_ID (OCID de la subred pública de la VCN)."
[ -s "$SSH_PUBKEY_FILE" ] || fail "No encuentro la llave pública en $SSH_PUBKEY_FILE."
grep -q '^ssh-ed25519 ' "$SSH_PUBKEY_FILE" || fail "$SSH_PUBKEY_FILE no es una llave pública ssh-ed25519."

# Guardas Always Free: nunca pedir algo que cobre
[ "$OCPUS" -le 2 ] && [ "$MEMORY_GB" -le 12 ] && [ "$BOOT_GB" -ge 50 ] && [ "$BOOT_GB" -le 200 ] \
    || fail "Fuera del Always Free (máx. 2 OCPU / 12 GB; disco 50–200 GB). Aborto."

check_existing() {
    local existing
    existing="$(oci compute instance list --compartment-id "$COMPARTMENT_ID" --display-name "$DISPLAY_NAME" \
        --query "length(data[?\"lifecycle-state\"!='TERMINATED'])" --raw-output 2>/dev/null || true)"
    if [ -n "$existing" ] && [ "$existing" != "0" ]; then
        notify "ℹ️ Oracle: ya existe '$DISPLAY_NAME'; el reintento se detiene."
        fail "Ya existe una instancia '$DISPLAY_NAME' no terminada. No creo otra."
    fi
}
check_existing

AD="$(oci iam availability-domain list --compartment-id "$COMPARTMENT_ID" --query 'data[0].name' --raw-output)"
IMAGE_ID="$(oci compute image list --compartment-id "$COMPARTMENT_ID" \
    --operating-system "Canonical Ubuntu" --operating-system-version "24.04" \
    --shape "VM.Standard.A1.Flex" --sort-by TIMECREATED --sort-order DESC --limit 1 \
    --query 'data[0].id' --raw-output)"
[ -n "$AD" ] && [ -n "$IMAGE_ID" ] || fail "No pude resolver AD o imagen Ubuntu 24.04 ARM."
log "AD: $AD · Imagen: $IMAGE_ID · Shape: A1.Flex ${OCPUS}/${MEMORY_GB} GB · Disco ${BOOT_GB} GB"

fd_args=()
[ -n "$FAULT_DOMAIN" ] && fd_args=(--fault-domain "$FAULT_DOMAIN")

attempt=0
while [ "$MAX_ATTEMPTS" -eq 0 ] || [ "$attempt" -lt "$MAX_ATTEMPTS" ]; do
    attempt=$((attempt + 1))
    [ "$MAX_ATTEMPTS" -eq 0 ] && label="$attempt" || label="$attempt/$MAX_ATTEMPTS"
    log "Intento $label..."
    if out="$(oci compute instance launch \
        --compartment-id "$COMPARTMENT_ID" \
        --availability-domain "$AD" \
        "${fd_args[@]}" \
        --display-name "$DISPLAY_NAME" \
        --shape "VM.Standard.A1.Flex" \
        --shape-config "{\"ocpus\": $OCPUS, \"memoryInGBs\": $MEMORY_GB}" \
        --image-id "$IMAGE_ID" \
        --boot-volume-size-in-gbs "$BOOT_GB" \
        --subnet-id "$SUBNET_ID" \
        --assign-public-ip true \
        --ssh-authorized-keys-file "$SSH_PUBKEY_FILE" \
        --query 'data.id' --raw-output 2>&1)"; then
        log "✅ VM creada: $out"
        log "Mira su IP pública en la consola (Compute → Instances → $DISPLAY_NAME)."
        notify "✅ Oracle: VM $DISPLAY_NAME creada tras $attempt intentos (A1 ${OCPUS}/${MEMORY_GB} GB)."
        exit 0
    fi
    if grep -qiE 'LimitExceeded|NotAuthorized|NotAuthenticated|InvalidParameter' <<<"$out"; then
        echo "$out" | tail -n 15
        notify "❌ Oracle: el reintento de $DISPLAY_NAME se detuvo por un error que no es de capacidad."
        fail "Error que no se arregla reintentando (cuota, permisos o parámetros). Revisa antes de relanzar."
    elif grep -qi 'out of host capacity' <<<"$out"; then
        log "Sin capacidad."
        pause "$RETRY_SECONDS"
    elif grep -qi 'TooManyRequests' <<<"$out"; then
        log "Demasiadas peticiones. Espero el triple."
        pause $((RETRY_SECONDS * 3))
    else
        echo "$out" | tail -n 5
        log "Error transitorio (red o servicio). Reintento."
        pause "$RETRY_SECONDS"
        check_existing   # por si el launch llegó a crear la VM aunque la respuesta fallara
    fi
done
fail "Se agotaron $MAX_ATTEMPTS intentos."
