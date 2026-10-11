#!/usr/bin/env bash
# ==============================================================================
# 04 · Cierre perimetral: retira SSH público; solo se entra por Tailscale
# ==============================================================================
# Ejecutar con sudo DESDE UNA SESIÓN QUE YA ENTRÓ POR TAILSCALE
# (ssh santiago@jerico-oracle). Después, borra también la regla de ingreso
# TCP 22 en la Security List de OCI (guía, Parte I).
# ==============================================================================

set -euo pipefail

ok() { echo "[OK] $1"; }
fail() { echo "[ERROR] $1" >&2; exit 1; }

[ "$EUID" -eq 0 ] || fail "Ejecútalo con sudo."
tailscale status >/dev/null 2>&1 || fail "Tailscale no está conectado: no cierro el 22 (te quedarías fuera)."
ts_ip="$(tailscale ip -4 | head -n 1)"
[ -n "$ts_ip" ] || fail "Sin IP de Tailscale."

# Comprobar que la sesión actual llega por Tailscale (100.64.0.0/10)
# `who -m` funciona bajo sudo (que limpia SSH_CLIENT del entorno).
client_ip="$(who -m | awk -F'[()]' '{print $2}')"
[ -n "$client_ip" ] || client_ip="${SSH_CLIENT%% *}"
case "$client_ip" in
    100.*) ok "Sesión actual por Tailscale ($client_ip)." ;;
    *) [ "${FORCE:-0}" = "1" ] || fail "Esta sesión no viene por Tailscale ($client_ip). Entra con ssh santiago@jerico-oracle y repite (FORCE=1 para omitir)." ;;
esac

ufw status | grep -q 'tailscale0' || fail "Falta la regla ufw para tailscale0."
if ufw status | grep -q '^22/tcp'; then
    ufw delete allow 22/tcp
    ok "Regla ufw 22/tcp pública eliminada."
else
    ok "La regla ufw 22/tcp ya no existía."
fi
ufw status verbose | head -n 20
echo "[SIGUIENTE] En la consola OCI borra la regla de ingreso TCP 22 de la Security List."
echo "[SIGUIENTE] Acceso: ssh santiago@jerico-oracle  (Tailscale $ts_ip)"
