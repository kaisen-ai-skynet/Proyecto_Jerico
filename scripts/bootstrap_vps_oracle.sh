#!/usr/bin/env bash
# ==============================================================================
# Script de Bootstrap y Hardening para VPS Oracle Cloud (Fase 0 - Jericó AI-OS)
# Kaisen AI — Santiago González (CTO / Sudo Supremo)
# ==============================================================================
# Este script automatiza:
# 1. Actualización y paquetes base del sistema (Ubuntu 22.04 / 24.04 LTS ARM64 o AMD64).
# 2. Desbloqueo de reglas de firewall restrictivas de Oracle Cloud (iptables).
# 3. Instalación de Tailscale VPN Mesh.
# 4. Creación de usuarios del equipo con llaves SSH individuales (ed25519).
# 5. Instalación de Docker CE y Docker Compose Plugin.
# 6. Despliegue de Coolify (Control Plane auto-hospedado).
# 7. Hardening de SSH (desactivar login root y login por password).
# ==============================================================================

set -euo pipefail

# Colores de salida
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_err() { echo -e "${RED}[ERROR]${NC} $1"; }

# Verificar privilegios de root
if [ "$EUID" -ne 0 ]; then
    log_err "Este script debe ejecutarse como root (o con sudo)."
    exit 1
fi

echo -e "${GREEN}======================================================${NC}"
echo -e "${GREEN}   🚀 INICIALIZANDO VPS ORACLE — PROYECTO JERICÓ      ${NC}"
echo -e "${GREEN}   Kaisen AI — Infraestructura Segura Multi-Ingeniero  ${NC}"
echo -e "${GREEN}======================================================${NC}"

# 1. Actualización del Sistema
log_info "Paso 1: Actualizando paquetes del sistema base..."
export DEBIAN_FRONTEND=noninteractive
apt update -y && apt upgrade -y
apt install -y curl wget git jq ufw iptables-persistent net-tools htop ca-certificates gnupg lsb-release

# 2. Corrección de Firewall de Oracle Cloud (Oracle aplica reglas iptables por defecto)
log_info "Paso 2: Ajustando reglas de iptables internas de Oracle..."
# Permitir todo el tráfico a través de la interfaz privada de Tailscale
iptables -I INPUT 1 -i tailscale0 -j ACCEPT 2>/dev/null || true
# Permitir tráfico local y establecido
iptables -I INPUT 2 -m state --state ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || true
# Guardar reglas iptables
netfilter-persistent save 2>/dev/null || true

# 3. Instalación de Tailscale
log_info "Paso 3: Instalando Tailscale..."
if ! command -v tailscale &>/dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
    log_success "Tailscale instalado exitosamente."
else
    log_info "Tailscale ya está instalado."
fi

# 4. Instalación de Docker CE y Docker Compose
log_info "Paso 4: Instalando Docker Engine y Docker Compose..."
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    log_success "Docker Engine instalado correctamente."
else
    log_info "Docker ya está instalado."
fi

# 5. Creación de Usuarios Individuales
log_info "Paso 5: Configurando cuentas de usuario individuales para el equipo técnico..."

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

    # Asignar grupo docker
    usermod -aG docker "$username"

    # Asignar sudo si aplica
    if [ "$is_sudo" = "true" ]; then
        usermod -aG sudo "$username"
        # Permitir sudo sin password para automatizaciones controladas del CTO
        echo "$username ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/99-$username"
        chmod 0440 "/etc/sudoers.d/99-$username"
        log_success "Usuario $username configurado como SUDO SUPREMO."
    else
        log_info "Usuario $username configurado con permisos estándar + Docker."
    fi

    # Configurar directorio SSH
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
        log_warn "No se proporcionó clave pública para $username. Se debe añadir en $auth_keys"
    fi

    chown -R "$username:$username" "$ssh_dir"
}

# --- CLAVES PÚBLICAS (Reemplazar o inyectar las llaves del equipo) ---
# Santiago González (CTO / Sudo Supremo)
KEY_SANTIAGO="${KEY_SANTIAGO:-}"
# Juan Pablo (Backend / Seguridad)
KEY_JPABLO="${KEY_JPABLO:-}"
# Esteban (Infra / Workflows)
KEY_ESTEBAN="${KEY_ESTEBAN:-}"
# Nicolás (Equipo Técnico / Compañero)
KEY_NICOLAS="${KEY_NICOLAS:-}"
# Santiago Jr (Auditoría / Bases de Datos / Operaciones)
KEY_SANTIAGOJR="${KEY_SANTIAGOJR:-}"

# Si la variable de entorno está vacía, se intenta heredar la llave del usuario 'ubuntu' inicial para Santiago
if [ -z "$KEY_SANTIAGO" ] && [ -f /home/ubuntu/.ssh/authorized_keys ]; then
    KEY_SANTIAGO=$(cat /home/ubuntu/.ssh/authorized_keys | head -n 1)
    log_info "Usando la llave SSH inicial de /home/ubuntu para Santiago."
fi

create_team_user "santiago" "true" "$KEY_SANTIAGO"
create_team_user "jpablo" "false" "$KEY_JPABLO"
create_team_user "esteban" "false" "$KEY_ESTEBAN"
create_team_user "nicolas" "false" "$KEY_NICOLAS"
create_team_user "santiagojr" "false" "$KEY_SANTIAGOJR"

# 6. Hardening de SSH
log_info "Paso 6: Aplicando directivas de Hardening a SSH..."
cat << 'EOF' > /etc/ssh/sshd_config.d/01-kaisen-security.conf
# Seguridad estricta Kaisen AI
PermitRootLogin no
PasswordAuthentication no
ChallengeResponseAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
MaxAuthTries 3
ClientAliveInterval 300
ClientAliveCountMax 2
X11Forwarding no
AllowUsers santiago jpablo esteban nicolas santiagojr ubuntu
EOF

# Validar sintaxis y recargar SSH
if sshd -t; then
    systemctl restart ssh || systemctl restart sshd
    log_success "Configuración SSH endurecida y reiniciada."
else
    log_err "Error en la sintaxis de sshd_config. Revisa la configuración."
fi

# 7. Instalación de Coolify
log_info "Paso 7: Instalando Coolify (Control Plane auto-hospedado)..."
if [ ! -d "/data/coolify" ]; then
    curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash
    log_success "Coolify instalado exitosamente."
else
    log_info "Coolify ya se encuentra instalado en /data/coolify."
fi

# 8. Directorio compartido del proyecto
log_info "Paso 8: Estructurando directorio de trabajo /opt/jerico..."
mkdir -p /opt/jerico/{data,backups,logs}
chown -R santiago:docker /opt/jerico
chmod -R 775 /opt/jerico

echo -e "\n${GREEN}======================================================${NC}"
echo -e "${GREEN}   🎉 ¡BOOTSTRAP DEL VPS COMPLETADO CON ÉXITO!        ${NC}"
echo -e "${GREEN}======================================================${NC}"
echo -e "Próximos pasos obligatorios:"
echo -e "1. Conecta el servidor a Tailscale ejecutando:"
echo -e "   ${YELLOW}sudo tailscale up --hostname=jerico-oracle --ssh${NC}"
echo -e "2. Verifica que cada ingeniero pueda ingresar vía Tailscale:"
echo -e "   - Santiago:    ${BLUE}ssh santiago@jerico-oracle${NC}"
echo -e "   - Juan Pablo:  ${BLUE}ssh jpablo@jerico-oracle${NC}"
echo -e "   - Esteban:     ${BLUE}ssh esteban@jerico-oracle${NC}"
echo -e "   - Nicolás:     ${BLUE}ssh nicolas@jerico-oracle${NC}"
echo -e "   - Santiago Jr: ${BLUE}ssh santiagojr@jerico-oracle${NC}"
echo -e "3. Ingresa a la interfaz web de Coolify:"
echo -e "   ${BLUE}http://jerico-oracle:8000${NC} (vía red Tailscale)"
echo -e "4. Elimina el puerto 22 de la Security List pública de Oracle Cloud."
echo -e "${GREEN}======================================================${NC}\n"
