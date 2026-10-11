#!/usr/bin/env bash
# ==============================================================================
# Verificación de la VM Oracle (solo lectura). Imprime PASS/FAIL/WARN por control
# y sale con código 1 si algún control crítico falla.
# Uso: sudo /opt/jerico/app/scripts/oci/verify_vps.sh
# ==============================================================================

set -uo pipefail

FAILS=0
pass() { echo "PASS  $1"; }
warn() { echo "WARN  $1"; }
fail() { echo "FAIL  $1"; FAILS=$((FAILS + 1)); }
check() { if eval "$2" &>/dev/null; then pass "$1"; else fail "$1"; fi; }

[ "$EUID" -eq 0 ] || { echo "Ejecútalo con sudo."; exit 2; }

check "Arquitectura ARM64 (aarch64)" '[ "$(uname -m)" = aarch64 ]'
check "ufw activo" 'ufw status | grep -q "Status: active"'
check "ufw deniega entrante por defecto" 'ufw status verbose | grep -q "deny (incoming)"'
check "ufw permite tailscale0" 'ufw status | grep -q tailscale0'
if ufw status | grep -q '^22/tcp'; then
    warn "22/tcp público sigue abierto en ufw (normal hasta correr 04_lockdown.sh)"
else
    pass "22/tcp público cerrado en ufw"
fi
check "SSH sin contraseña" 'sshd -T | grep -qx "passwordauthentication no"'
check "SSH sin login root" 'sshd -T | grep -qx "permitrootlogin no"'
check "Tailscale conectado" 'tailscale status'
check "Docker activo" 'systemctl is-active --quiet docker'
check "Docker publica por defecto en 127.0.0.1" 'jq -e ".ip == \"127.0.0.1\"" /etc/docker/daemon.json'
check "Parches automáticos activos" 'grep -q "Unattended-Upgrade \"1\"" /etc/apt/apt.conf.d/20auto-upgrades'

# Puertos TCP en escucha fuera de loopback/Tailscale (solo se tolera sshd en 22)
exposed="$(ss -ltnH | awk '{print $4}' \
    | grep -vE '^(127\.|\[::1\]|100\.|\[fd7a:115c:a1e0)' \
    | grep -vE '^(0\.0\.0\.0|\*|\[::\]):22$' || true)"
if [ -z "$exposed" ]; then
    pass "Sin puertos TCP expuestos aparte de 22"
else
    fail "Puertos expuestos fuera de loopback/Tailscale: $(echo "$exposed" | tr '\n' ' ')"
fi

pg5432="$(ss -ltnH 'sport = :5432' | awk '{print $4}')"
if [ -z "$pg5432" ]; then
    warn "Postgres no escucha en el host (¿falta 02_postgres.sh?)"
elif echo "$pg5432" | grep -vq '^127\.0\.0\.1:5432$'; then
    fail "5432 expuesto fuera de 127.0.0.1: $pg5432"
else
    pass "5432 solo en 127.0.0.1"
fi

if docker inspect jerico-postgres &>/dev/null; then
    check "Postgres healthy" '[ "$(docker inspect -f "{{.State.Health.Status}}" jerico-postgres)" = healthy ]'
fi

if systemctl list-unit-files jerico-backup-postgres.timer &>/dev/null \
    && systemctl is-enabled --quiet jerico-backup-postgres.timer; then
    pass "Timer de backup habilitado"
    latest="$(find /opt/jerico/backups -maxdepth 1 -name 'jerico_*.dump.age' -mmin -1560 | head -n 1)"
    if [ -n "$latest" ]; then pass "Backup de las últimas 26 h: $(basename "$latest")"; else fail "No hay backup de las últimas 26 h"; fi
else
    warn "Timer de backup no instalado (¿falta 03_backups.sh?)"
fi

echo "----"
if [ "$FAILS" -eq 0 ]; then echo "RESULTADO: OK"; else echo "RESULTADO: $FAILS control(es) en FAIL"; exit 1; fi
