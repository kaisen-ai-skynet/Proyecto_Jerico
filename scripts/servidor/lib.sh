#!/usr/bin/env bash
# Funciones comunes de scripts/servidor (spec 003). Se carga con `. lib.sh`; no se ejecuta.

# Formato único de estado: "<State.Status> <Health.Status|none>", p. ej. "running healthy".
STATE_FORMAT='{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}'

# Imprime el estado del contenedor; código 1 si no existe.
container_state() {
    docker inspect -f "$STATE_FORMAT" "$1" 2>/dev/null
}

# SRV-03: el archivo de destinatarios age existe, tiene al menos una llave PÚBLICA y
# ninguna privada. En el servidor nunca debe haber una llave privada.
check_recipients() {
    local file="$1"
    if [ ! -r "$file" ]; then
        echo "no se puede leer el archivo de destinatarios $file" >&2
        return 1
    fi
    if grep -q 'AGE-SECRET-KEY' "$file"; then
        echo "$file contiene una llave PRIVADA (AGE-SECRET-KEY): bórrala del servidor; aquí solo va la pública age1..." >&2
        return 1
    fi
    if ! grep -qE '^[[:space:]]*age1[0-9a-z]+' "$file"; then
        echo "$file no tiene ninguna llave pública age1..." >&2
        return 1
    fi
}

# SRV-04: el archivo empieza por la cabecera del formato age v1.
is_age_file() {
    [ "$(head -n 1 "$1" 2>/dev/null)" = "age-encryption.org/v1" ]
}
