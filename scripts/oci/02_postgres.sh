#!/usr/bin/env bash
# ==============================================================================
# 02 · PostgreSQL 16 en la VM Oracle, solo en 127.0.0.1 (decisiones D1/D2)
# ==============================================================================
# Se ejecuta como `santiago` (grupo docker) con el repo ya copiado en
# /opt/jerico/app. Idempotente.
#
#   1. Genera la contraseña de Postgres en /opt/jerico/secrets (fuera de Git).
#   2. Levanta solo el servicio `postgres` de docker-compose.prod.yml.
#   3. Verifica salud y que 5432 escuche ÚNICAMENTE en 127.0.0.1.
#   4. Escribe la URL de conexión para Jericó en /opt/jerico/secrets/postgres_url
#      (se copia a mano al .env en la fase de despliegue).
# ==============================================================================

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/jerico/app}"
SECRETS_DIR="${JERICO_SECRETS_DIR:-/opt/jerico/secrets}"
PASSWORD_FILE="$SECRETS_DIR/postgres_password"
URL_FILE="$SECRETS_DIR/postgres_url"

ok() { echo "[OK] $1"; }
info() { echo "[INFO] $1"; }
fail() { echo "[ERROR] $1" >&2; exit 1; }

[ "$EUID" -ne 0 ] || fail "Ejecútalo como 'santiago', no como root."
command -v docker &>/dev/null || fail "Docker no está instalado: corre antes 01_bootstrap.sh."
[ -f "$APP_DIR/docker-compose.prod.yml" ] || fail "Falta $APP_DIR/docker-compose.prod.yml: sube el repo primero (guía, Parte G)."
[ -d "$SECRETS_DIR" ] || fail "Falta $SECRETS_DIR: corre antes 01_bootstrap.sh."

# 1. Contraseña (solo si no existe: rotarla rompe el volumen ya inicializado)
umask 077
if [ ! -s "$PASSWORD_FILE" ]; then
    openssl rand -base64 48 | tr -d '/+=\n' | head -c 40 > "$PASSWORD_FILE"
    ok "Contraseña generada en $PASSWORD_FILE."
else
    info "Contraseña existente conservada."
fi
# El contenedor (uid 70) debe poder leer el secreto montado; el directorio
# padre (700, santiago) impide que otros usuarios del host lo lean.
chmod 644 "$PASSWORD_FILE"
chmod 700 "$SECRETS_DIR"

# 2. Levantar Postgres
cd "$APP_DIR"
export JERICO_SECRETS_DIR="$SECRETS_DIR"
docker compose -p jerico -f docker-compose.prod.yml config --quiet
docker compose -p jerico -f docker-compose.prod.yml up -d postgres

# 3. Salud y exposición
info "Esperando a que Postgres esté healthy..."
for _ in $(seq 1 30); do
    status="$(docker inspect -f '{{.State.Health.Status}}' jerico-postgres 2>/dev/null || echo starting)"
    [ "$status" = "healthy" ] && break
    sleep 2
done
[ "${status:-}" = "healthy" ] || fail "Postgres no llegó a healthy (docker logs jerico-postgres | tail -n 25)."
ok "Postgres healthy."

listeners="$(ss -ltnH 'sport = :5432' | awk '{print $4}')"
[ -n "$listeners" ] || fail "Nada escucha en 5432 del host (docker compose -p jerico ps)."
if echo "$listeners" | grep -vq '^127\.0\.0\.1:5432$'; then
    fail "5432 escucha fuera de 127.0.0.1: $listeners. Detén con: docker stop jerico-postgres"
fi
ok "5432 solo en 127.0.0.1."

docker exec jerico-postgres psql -U jerico -d jerico -tAc 'SELECT version();' | head -n 1

# 4. URL para el .env de Jericó (red interna jerico_net)
printf 'postgresql://jerico:%s@postgres:5432/jerico\n' "$(cat "$PASSWORD_FILE")" > "$URL_FILE"
chmod 600 "$URL_FILE"
ok "URL de conexión en $URL_FILE (va a JERICO_POSTGRES_URL del .env; nunca a Git)."
