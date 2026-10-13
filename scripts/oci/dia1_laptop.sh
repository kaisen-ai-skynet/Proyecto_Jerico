#!/usr/bin/env bash
# ==============================================================================
# Día 1 · Preparación de la laptop del CTO (Ubuntu). Se ejecuta en casa, en la
# raíz del repo, con tu usuario normal (pide sudo cuando hace falta).
# Idempotente: lo que ya existe no se toca. No crea nada en Oracle Cloud.
#
#   1. Paquetes: age, git, curl, openssh-client.
#   2. Llave SSH ~/.ssh/id_ed25519_kaisen (para la VM).
#   3. Llave age ~/.config/kaisen/jerico-backup.agekey (para los backups).
#   4. Docker Engine + Compose (para probar el contenedor del CRM, fase 1).
#   5. Tailscale: comprobación.
#   6. Prueba de humo del contenedor jerico-crm (build + arranque sin secretos).
#
# Uso: scripts/oci/dia1_laptop.sh   (SKIP_DOCKER=1 / SKIP_CRM=1 para omitir partes)
# ==============================================================================

set -euo pipefail

ok() { echo -e "\033[0;32m[OK]\033[0m $1"; }
info() { echo -e "\033[0;34m[INFO]\033[0m $1"; }
warn() { echo -e "\033[1;33m[WARN]\033[0m $1"; }
fail() { echo -e "\033[0;31m[ERROR]\033[0m $1" >&2; exit 1; }

[ "$EUID" -ne 0 ] || fail "Ejecútalo con tu usuario normal, no con sudo."
REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
SSH_KEY="$HOME/.ssh/id_ed25519_kaisen"
AGE_KEY="$HOME/.config/kaisen/jerico-backup.agekey"

# Ejecuta docker directo si el usuario ya tiene acceso al daemon; si no (grupo
# docker recién añadido, sin re-login), con sudo. No depende de `sg`.
docker_run() {
    if docker info >/dev/null 2>&1; then
        docker "$@"
    else
        sudo docker "$@"
    fi
}

# 1. Paquetes
info "1/6 Paquetes base..."
sudo apt-get update -qq
sudo apt-get install -qq -y age git curl openssh-client ca-certificates
ok "age, git, curl y openssh-client instalados."

# 2. Llave SSH
info "2/6 Llave SSH para la VM..."
if [ -f "$SSH_KEY" ]; then
    ok "Ya existe $SSH_KEY (no se regenera)."
else
    mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
    ssh-keygen -t ed25519 -C "kaisen.ai.santiago.cto@gmail.com" -f "$SSH_KEY"
    ok "Llave creada (la frase de paso que elegiste protege la privada)."
fi

# 3. Llave age
info "3/6 Llave de cifrado de backups (age)..."
mkdir -p "$(dirname "$AGE_KEY")" && chmod 700 "$(dirname "$AGE_KEY")"
if [ -f "$AGE_KEY" ]; then
    ok "Ya existe $AGE_KEY (no se regenera: los backups dependen de ella)."
else
    age-keygen -o "$AGE_KEY" 2>/dev/null
    chmod 600 "$AGE_KEY"
    ok "Llave age creada."
fi
AGE_PUB="$(age-keygen -y "$AGE_KEY")"

# 4. Docker
if [ "${SKIP_DOCKER:-0}" != "1" ]; then
    info "4/6 Docker Engine + Compose..."
    if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
        ok "Docker ya instalado: $(docker --version)."
    else
        # Repo oficial de Docker; si aún no soporta tu versión de Ubuntu, paquetes de Ubuntu.
        if ! curl -fsSL https://get.docker.com | sudo sh; then
            warn "get.docker.com falló; uso los paquetes de Ubuntu (docker.io + docker-compose-v2)."
            sudo apt-get install -qq -y docker.io docker-compose-v2
        fi
        ok "Docker instalado: $(docker --version)."
    fi
    sudo systemctl enable --now docker
    if ! id -nG "$USER" | grep -qw docker; then
        sudo usermod -aG docker "$USER"
        warn "Te añadí al grupo docker; en terminales nuevas no hará falta sudo (en esta sesión uso 'sudo docker')."
    fi
    docker_run run --rm hello-world >/dev/null || fail "Docker no pudo correr hello-world."
    ok "Docker funciona (hello-world)."
else
    warn "4/6 Docker omitido (SKIP_DOCKER=1)."
fi

# 5. Tailscale
info "5/6 Tailscale..."
if command -v tailscale >/dev/null && tailscale status >/dev/null 2>&1; then
    ok "Tailscale conectado: $(tailscale ip -4 | head -n 1)."
else
    warn "Tailscale no está conectado. Instálalo/ábrelo: curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up"
fi

# 6. Prueba de humo del CRM (fase 1)
if [ "${SKIP_CRM:-0}" != "1" ] && command -v docker >/dev/null; then
    info "6/6 Construyendo la imagen jerico-crm (puede tardar unos minutos)..."
    cd "$REPO_ROOT"
    docker_run build -q --build-arg EXTRAS=crm --build-arg CRM_TOOLS=1 -t jerico-crm:0.2.0 . >/dev/null
    ok "Imagen jerico-crm:0.2.0 construida."
    # Sin token ni clave HMAC, jerico-crm debe negarse a arrancar con código 2
    # (contrato de spec 001). Prueba que la imagen y el entrypoint están bien sin usar secretos.
    set +e
    out="$(docker_run run --rm --env-file /dev/null jerico-crm:0.2.0 jerico-crm 2>&1)"
    code=$?
    set -e
    if [ "$code" -eq 2 ]; then
        ok "jerico-crm arranca y rechaza la configuración vacía (código 2), como manda la spec."
    else
        echo "$out" | tail -n 15
        fail "jerico-crm salió con código $code (se esperaba 2). Pásale esta salida a crm-director."
    fi
    info "Para la prueba completa con tu bot: ver docs/dia-1-oci.md, bloque 6."
else
    warn "6/6 Prueba del CRM omitida."
fi

echo
echo "================== COPIA ESTO (son datos PÚBLICOS) =================="
echo "Llave SSH pública (va en Oracle al crear la VM):"
cat "$SSH_KEY.pub"
echo
echo "Llave age pública (va en /etc/jerico/backup.env de la VM):"
echo "$AGE_PUB"
echo "======================================================================"
warn "Guarda AHORA $AGE_KEY en tu gestor de contraseñas. Sin ella los backups no se pueden abrir."
