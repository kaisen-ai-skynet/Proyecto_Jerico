#!/usr/bin/env bash
# ==============================================================================
# 01 · Bootstrap y hardening de la VM Oracle Cloud (Fase 0 — Jericó AI-OS)
# Kaisen AI — Santiago González (CTO)
# ==============================================================================
# Se ejecuta UNA vez en la VM recién creada, como root (sudo), con la sesión SSH
# inicial del usuario `ubuntu`. Es idempotente: re-ejecutarlo no rompe nada.
#
# Hace:
#   1. Verifica Ubuntu 24.04 en ARM64 (regla ARM64 estricta de SPEC v2).
#   2. Actualiza el sistema, instala paquetes base y activa parches automáticos.
#   3. Sustituye las reglas iptables de la imagen Oracle por ufw (deny entrante).
#   4. Instala Tailscale (la unión a la tailnet es un paso aparte, ver guía).
#   5. Instala Docker CE + Compose con publicación de puertos por defecto en 127.0.0.1.
#   6. Crea los usuarios del equipo con sus llaves ed25519.
#   7. Endurece SSH (sin root, sin contraseñas).
#   8. Crea /opt/jerico/{app,data,backups,logs,secrets}.
#
# NO hace: unir a Tailscale sin TS_AUTHKEY, crear Postgres (02), backups (03) ni
# cerrar el puerto 22 (04). Coolify quedó fuera de Fase 0 (decisión 30/09/2026).
#
# Uso:
#   sudo KEY_NICOLAS="ssh-ed25519 AAAA..." ./01_bootstrap.sh
#   (KEY_SANTIAGO se hereda de /home/ubuntu/.ssh/authorized_keys si no se pasa)
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_err() { echo -e "${RED}[ERROR]${NC} $1"; }

if [ "$EUID" -ne 0 ]; then
    log_err "Este script debe ejecutarse como root (sudo)."
    exit 1
fi

TAILSCALE_HOSTNAME="${TAILSCALE_HOSTNAME:-jerico-oracle}"

# ------------------------------------------------------------------------------
# 1. Plataforma
# ------------------------------------------------------------------------------
log_info "Paso 1: Verificando plataforma..."
ARCH="$(uname -m)"
if [ "$ARCH" != "aarch64" ] && [ "${ALLOW_NON_ARM:-0}" != "1" ]; then
    log_err "Arquitectura $ARCH: Jericó exige ARM64 (Ampere A1). Aborto. (ALLOW_NON_ARM=1 para forzar)"
    exit 1
fi
# shellcheck disable=SC1091
. /etc/os-release
if [ "${VERSION_ID:-}" != "24.04" ]; then
    log_warn "Ubuntu ${VERSION_ID:-desconocido} detectado; el script está probado para 24.04 LTS."
fi
log_success "Plataforma: $PRETTY_NAME ($ARCH)."

# ------------------------------------------------------------------------------
# 2. Sistema base y parches automáticos
# ------------------------------------------------------------------------------
log_info "Paso 2: Actualizando sistema e instalando paquetes base..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -qq -y
apt-get install -qq -y curl git jq htop ca-certificates gnupg lsb-release \
    unattended-upgrades age rclone

cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
timedatectl set-timezone America/Bogota
log_success "Paquetes base, parches de seguridad automáticos y zona horaria America/Bogota."

# ------------------------------------------------------------------------------
# 3. Firewall: ufw en lugar de las reglas iptables de la imagen Oracle
# ------------------------------------------------------------------------------
# Las imágenes Ubuntu de OCI traen iptables-persistent con un REJECT final en
# INPUT. ufw y iptables-persistent son incompatibles (ufw "Breaks" ese paquete),
# así que se retiran y ufw pasa a ser la única fuente de reglas de entrada.
# La cadena OUTPUT (reglas de 169.254.0.0/16 de Oracle) no se toca.
log_info "Paso 3: Configurando firewall ufw..."
if dpkg -s iptables-persistent &>/dev/null || dpkg -s netfilter-persistent &>/dev/null; then
    apt-get remove -qq -y iptables-persistent netfilter-persistent
fi
apt-get install -qq -y ufw

ufw default deny incoming
ufw default allow outgoing
ufw allow in on tailscale0 comment 'Tailscale (red privada)'
ufw allow 22/tcp comment 'SSH temporal: se cierra con 04_lockdown.sh'
ufw allow 41641/udp comment 'Tailscale WireGuard directo'

# Solo la primera vez: vaciar las reglas Oracle de INPUT/FORWARD (incluyen
# REJECT icmp-host-prohibited). Política ACCEPT antes de vaciar para no cortar
# la sesión SSH; ufw aplica deny a continuación.
if iptables -S INPUT | grep -q 'icmp-host-prohibited' || iptables -S FORWARD | grep -q 'icmp-host-prohibited'; then
    log_info "Retirando reglas iptables heredadas de la imagen Oracle..."
    iptables -P INPUT ACCEPT
    iptables -F INPUT
    iptables -F FORWARD
fi
ufw --force enable
ufw reload
log_success "ufw activo: entrante denegado salvo tailscale0, 22/tcp (temporal) y 41641/udp."

# ------------------------------------------------------------------------------
# 4. Tailscale
# ------------------------------------------------------------------------------
log_info "Paso 4: Instalando Tailscale..."
if ! command -v tailscale &>/dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
    log_success "Tailscale instalado."
else
    log_info "Tailscale ya está instalado."
fi
systemctl enable --now tailscaled
if [ -n "${TS_AUTHKEY:-}" ]; then
    tailscale up --authkey "$TS_AUTHKEY" --hostname "$TAILSCALE_HOSTNAME"
    log_success "Nodo unido a la tailnet como $TAILSCALE_HOSTNAME."
else
    log_warn "Sin TS_AUTHKEY: une el nodo a mano con: sudo tailscale up --hostname=$TAILSCALE_HOSTNAME"
fi

# ------------------------------------------------------------------------------
# 5. Docker CE + Compose
# ------------------------------------------------------------------------------
log_info "Paso 5: Instalando Docker Engine y Docker Compose..."
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
    log_success "Docker Engine instalado."
else
    log_info "Docker ya está instalado."
fi

# Docker publica puertos saltándose ufw. Defensa en profundidad: todo puerto
# publicado sin IP explícita queda en 127.0.0.1, y los logs rotan.
DAEMON_JSON='{
  "ip": "127.0.0.1",
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}'
mkdir -p /etc/docker
if [ ! -f /etc/docker/daemon.json ] || [ "$(cat /etc/docker/daemon.json)" != "$DAEMON_JSON" ]; then
    echo "$DAEMON_JSON" > /etc/docker/daemon.json
    systemctl restart docker
fi
systemctl enable --now docker
log_success "Docker activo con bind por defecto 127.0.0.1 y rotación de logs."

# ------------------------------------------------------------------------------
# 6. Usuarios del equipo
# ------------------------------------------------------------------------------
log_info "Paso 6: Configurando cuentas individuales del equipo técnico..."

create_team_user() {
    local username="$1"
    local is_sudo="$2"
    local pubkey="$3"

    if id "$username" &>/dev/null; then
        log_warn "El usuario $username ya existe. Verificando llaves..."
    else
        log_info "Creando usuario: $username"
        useradd -m -s /bin/bash "$username"
    fi

    usermod -aG docker "$username"

    if [ "$is_sudo" = "true" ]; then
        usermod -aG sudo "$username"
        # Sudo sin contraseña: los usuarios no tienen contraseña (solo llave SSH).
        echo "$username ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/99-$username"
        chmod 0440 "/etc/sudoers.d/99-$username"
        log_success "Usuario $username con sudo."
    else
        log_info "Usuario $username con permisos estándar + Docker."
    fi

    local ssh_dir="/home/$username/.ssh"
    mkdir -p "$ssh_dir"
    chmod 700 "$ssh_dir"

    local auth_keys="$ssh_dir/authorized_keys"
    touch "$auth_keys"
    chmod 600 "$auth_keys"

    if [ -n "$pubkey" ]; then
        if ! grep -Fxq "$pubkey" "$auth_keys"; then
            echo "$pubkey" >> "$auth_keys"
            log_success "Clave SSH agregada para $username."
        fi
    else
        log_warn "Sin clave pública para $username. Añádela después en $auth_keys"
    fi

    chown -R "$username:$username" "$ssh_dir"
}

# --- Claves públicas (se inyectan por variable de entorno; nunca en Git) ---
KEY_SANTIAGO="${KEY_SANTIAGO:-}"     # Santiago González (CTO)
KEY_NICOLAS="${KEY_NICOLAS:-}"       # Nicolás (Sysadmin)
KEY_JPABLO="${KEY_JPABLO:-}"         # Juan Pablo (Backend / Seguridad)
KEY_ESTEBAN="${KEY_ESTEBAN:-}"       # Esteban (Infra / Workflows)
KEY_SANTIAGOJR="${KEY_SANTIAGOJR:-}" # Santiago Jr (Auditoría / BD / Ops)

# Si no se pasa la llave del CTO, se hereda la que se pegó al crear la VM.
if [ -z "$KEY_SANTIAGO" ] && [ -f /home/ubuntu/.ssh/authorized_keys ]; then
    KEY_SANTIAGO="$(head -n 1 /home/ubuntu/.ssh/authorized_keys)"
    log_info "Usando la llave SSH inicial de /home/ubuntu para santiago."
fi

create_team_user "santiago" "true" "$KEY_SANTIAGO"
create_team_user "nicolas" "true" "$KEY_NICOLAS"
create_team_user "jpablo" "true" "$KEY_JPABLO"
create_team_user "esteban" "false" "$KEY_ESTEBAN"
create_team_user "santiagojr" "false" "$KEY_SANTIAGOJR"

# ------------------------------------------------------------------------------
# 7. Hardening de SSH
# ------------------------------------------------------------------------------
log_info "Paso 7: Endureciendo SSH..."
# Prefijo 01- para ganar a 50-cloud-init.conf (sshd usa el primer valor leído).
cat << 'EOF' > /etc/ssh/sshd_config.d/01-kaisen-security.conf
# Seguridad estricta Kaisen AI
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
MaxAuthTries 3
ClientAliveInterval 300
ClientAliveCountMax 2
X11Forwarding no
AllowUsers santiago jpablo esteban nicolas santiagojr ubuntu
EOF

if sshd -t; then
    systemctl restart ssh || systemctl restart sshd
    log_success "SSH endurecido y reiniciado."
else
    log_err "sshd_config inválido: se retira el archivo para no bloquear el acceso."
    rm -f /etc/ssh/sshd_config.d/01-kaisen-security.conf
    exit 1
fi

# ------------------------------------------------------------------------------
# 8. Directorios del proyecto
# ------------------------------------------------------------------------------
log_info "Paso 8: Estructurando /opt/jerico..."
mkdir -p /opt/jerico/{app,data,backups,logs,secrets}
chown -R santiago:docker /opt/jerico
chmod 775 /opt/jerico /opt/jerico/{app,data,logs}
chmod 750 /opt/jerico/backups
chmod 700 /opt/jerico/secrets

cat > /etc/profile.d/jerico-compose.sh <<'EOF'
# Atajo de Compose de producción de Jericó (base + override con Postgres).
alias jc='docker compose -p jerico -f /opt/jerico/app/docker-compose.yml -f /opt/jerico/app/docker-compose.prod.yml'
EOF
log_success "Directorios listos y alias 'jc' disponible en nuevas sesiones."

echo -e "\n${GREEN}======================================================${NC}"
echo -e "${GREEN}   ✅ BOOTSTRAP COMPLETADO                              ${NC}"
echo -e "${GREEN}======================================================${NC}"
echo -e "Siguientes pasos (ver docs/guia-oci-principiantes.md):"
echo -e "1. Unir a Tailscale (si no pasaste TS_AUTHKEY): ${YELLOW}sudo tailscale up --hostname=$TAILSCALE_HOSTNAME${NC}"
echo -e "2. Desde tu laptop, probar: ${BLUE}ssh santiago@$TAILSCALE_HOSTNAME${NC}  (NO cierres esta sesión antes)"
echo -e "3. Subir el repo y ejecutar ${BLUE}scripts/oci/02_postgres.sh${NC}"
echo -e "${GREEN}======================================================${NC}\n"
