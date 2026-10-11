#!/usr/bin/env bash
# ==============================================================================
# 00 · Plan B: reintentar la creación de la VM A1 ante "Out of host capacity"
# ==============================================================================
# Se ejecuta en OCI Cloud Shell (consola OCI → icono ">_" arriba a la derecha),
# que ya trae la CLI `oci` autenticada. Solo se usa si la creación desde la
# consola falla por capacidad. Nunca crea más de una VM con el mismo nombre y
# se niega a pedir más de lo Always Free (2 OCPU / 12 GB / 200 GB).
#
# Uso (en Cloud Shell):
#   export COMPARTMENT_ID=ocid1.compartment.oc1..xxxx
#   export SUBNET_ID=ocid1.subnet.oc1.sa-bogota-1.xxxx
#   export SSH_PUBKEY_FILE=~/jerico_ssh.pub     # sube tu .pub a Cloud Shell
#   bash 00_retry_launch_a1.sh
# Si Cloud Shell se cierra por inactividad, vuelve a lanzarlo: es seguro.
# ==============================================================================

set -euo pipefail

COMPARTMENT_ID="${COMPARTMENT_ID:-${OCI_TENANCY:-}}"
SUBNET_ID="${SUBNET_ID:-}"
SSH_PUBKEY_FILE="${SSH_PUBKEY_FILE:-$HOME/jerico_ssh.pub}"
DISPLAY_NAME="${DISPLAY_NAME:-jerico-core-oracle-01}"
OCPUS="${OCPUS:-2}"
MEMORY_GB="${MEMORY_GB:-12}"
BOOT_GB="${BOOT_GB:-100}"
RETRY_SECONDS="${RETRY_SECONDS:-90}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-200}"

fail() { echo "[ERROR] $1" >&2; exit 1; }
log() { echo "[$(date '+%H:%M:%S')] $1"; }

command -v oci >/dev/null || fail "No hay CLI oci: ejecútalo dentro de OCI Cloud Shell."
[ -n "$COMPARTMENT_ID" ] || fail "Define COMPARTMENT_ID (OCID del compartimento kaisen-jerico)."
[ -n "$SUBNET_ID" ] || fail "Define SUBNET_ID (OCID de la subred pública de la VCN)."
[ -s "$SSH_PUBKEY_FILE" ] || fail "No encuentro la llave pública en $SSH_PUBKEY_FILE."
grep -q '^ssh-ed25519 ' "$SSH_PUBKEY_FILE" || fail "$SSH_PUBKEY_FILE no es una llave pública ssh-ed25519."

# Guardas Always Free: nunca pedir algo que cobre
[ "$OCPUS" -le 2 ] && [ "$MEMORY_GB" -le 12 ] && [ "$BOOT_GB" -ge 50 ] && [ "$BOOT_GB" -le 200 ] \
    || fail "Fuera del Always Free (máx. 2 OCPU / 12 GB; disco 50–200 GB). Aborto."

existing="$(oci compute instance list --compartment-id "$COMPARTMENT_ID" --display-name "$DISPLAY_NAME" \
    --query "length(data[?\"lifecycle-state\"!='TERMINATED'])" --raw-output 2>/dev/null || true)"
if [ -n "$existing" ] && [ "$existing" != "0" ]; then
    fail "Ya existe una instancia '$DISPLAY_NAME' no terminada. No creo otra."
fi

AD="$(oci iam availability-domain list --compartment-id "$COMPARTMENT_ID" --query 'data[0].name' --raw-output)"
IMAGE_ID="$(oci compute image list --compartment-id "$COMPARTMENT_ID" \
    --operating-system "Canonical Ubuntu" --operating-system-version "24.04" \
    --shape "VM.Standard.A1.Flex" --sort-by TIMECREATED --sort-order DESC --limit 1 \
    --query 'data[0].id' --raw-output)"
[ -n "$AD" ] && [ -n "$IMAGE_ID" ] || fail "No pude resolver AD o imagen Ubuntu 24.04 ARM."
log "AD: $AD · Imagen: $IMAGE_ID · Shape: A1.Flex ${OCPUS}/${MEMORY_GB} GB · Disco ${BOOT_GB} GB"

FAULT_DOMAINS=(FAULT-DOMAIN-1 FAULT-DOMAIN-2 FAULT-DOMAIN-3)
for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
    fd="${FAULT_DOMAINS[$(( (attempt - 1) % 3 ))]}"
    log "Intento $attempt/$MAX_ATTEMPTS en $fd..."
    if out="$(oci compute instance launch \
        --compartment-id "$COMPARTMENT_ID" \
        --availability-domain "$AD" \
        --fault-domain "$fd" \
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
        exit 0
    fi
    if grep -qi 'out of host capacity' <<<"$out"; then
        log "Sin capacidad. Reintento en ${RETRY_SECONDS}s."
        sleep "$RETRY_SECONDS"
    elif grep -qi 'TooManyRequests' <<<"$out"; then
        log "Demasiadas peticiones. Espero $((RETRY_SECONDS * 3))s."
        sleep $((RETRY_SECONDS * 3))
    else
        echo "$out" | tail -n 15
        fail "Error distinto a capacidad (p. ej. LimitExceeded = ya usas tu cuota A1). Revisa antes de reintentar."
    fi
done
fail "Se agotaron $MAX_ATTEMPTS intentos. Prueba en otro horario (madrugada suele ir mejor)."
