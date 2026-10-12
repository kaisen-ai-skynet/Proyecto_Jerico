---
tipo: guia-operativa
proyecto: Jericó — Kaisen AI
estado: lista-para-ejecutar (nada ejecutado contra OCI)
creado: "11/10/2026 17:50"
modificado: "11/10/2026 20:25"
---

# Guía OCI para principiantes — preparar Oracle Cloud para Jericó

**Para quién:** el CTO, sin experiencia previa en Oracle Cloud.
**Decisiones ya cerradas (11/10/2026):** región **Bogotá (`sa-bogota-1`)** y cuenta **Always Free pura** (sin pasar a pago).
**Tiempo estimado:** 2–3 horas repartidas (la activación de la cuenta puede tardar horas; puedes parar entre partes).
**Resultado final:** una VM ARM gratis, sin puertos abiertos a internet, a la que entras solo por Tailscale, con PostgreSQL 16 listo en `127.0.0.1` y backup nocturno cifrado fuera de la máquina.

> **¿Quieres hacerlo todo en una sesión?** Sigue `docs/dia-1-oci.md`, que ordena estas partes en bloques y empieza con `scripts/oci/dia1_laptop.sh`.

> Esta guía reemplaza los pasos de creación del runbook (`docs/runbook-aprovisionamiento-vps.md` §1–§2). El despliegue de Jericó en sí (`.env`, `docker compose up`) sigue en el runbook §3 y es la fase siguiente.

---

## ⚠️ Antes de empezar: 5 reglas de oro

1. **La región no se cambia nunca.** Al crear la cuenta eliges Bogotá y queda así para siempre. Revísalo dos veces.
2. **Una sola cuenta.** Oracle prohíbe tener varias cuentas gratis; si te equivocas, no crees otra: escribe a soporte.
3. **Nada que diga "cobro".** Si la consola muestra un costo distinto de $0 o falta la etiqueta *Always Free-eligible*, detente.
4. **La VM es de 2 OCPU / 12 GB, no de 4 / 24.** Oracle redujo el Always Free ARM el 21/07/2026 (de 4 OCPU / 24 GB a 2 OCPU / 12 GB). En una cuenta gratis pura, una VM de 4/24 la **detiene Oracle** hasta que la reduzcas. Si algún documento viejo dice 4/24, ignóralo.
5. **Nunca se abren a internet los puertos 5432 (Postgres), 6379 (Redis) ni 8000 (API).** Todo pasa por Tailscale.

### Glosario mínimo

| Término | Qué es |
|---|---|
| **Tenancy** | Tu cuenta de Oracle. |
| **Compartment** | Carpeta para ordenar recursos. Usaremos `kaisen-jerico`. |
| **VCN / subred** | La red privada virtual donde vive la VM. |
| **Security List** | El firewall de Oracle *por fuera* de la VM. |
| **ufw** | El firewall *por dentro* de la VM (lo configura el script). |
| **Shape** | El "tamaño" de la VM. El nuestro: `VM.Standard.A1.Flex` (ARM Ampere). |
| **OCID** | El identificador largo de cada recurso (`ocid1....`). Se copia con el botón *Copy*. |
| **Tailscale** | Red privada entre tus equipos y la VM; con ella no hace falta abrir puertos. |

### Mapa de archivos (todo está en el repo, nada se ha ejecutado)

| Archivo | Dónde se ejecuta | Para qué |
|---|---|---|
| `scripts/oci/00_retry_launch_a1.sh` | OCI Cloud Shell | Plan B: reintentar la VM si no hay capacidad |
| `scripts/oci/01_bootstrap.sh` | VM (sudo) | Sistema, ufw, Tailscale, Docker, usuarios, SSH |
| `scripts/oci/sync_repo_to_vps.sh` | Tu laptop | Copiar el repo a la VM sin `git push` |
| `scripts/oci/02_postgres.sh` | VM (santiago) | PostgreSQL 16 solo en 127.0.0.1 |
| `scripts/oci/03_backups.sh` | VM (sudo) | Backup nocturno cifrado fuera de la VM |
| `scripts/oci/04_lockdown.sh` | VM (sudo, por Tailscale) | Cerrar SSH público |
| `scripts/oci/verify_vps.sh` | VM (sudo) | Verificación final PASS/FAIL |
| `scripts/oci/dia1_laptop.sh` | Tu laptop | Día 1: llaves, Docker y prueba de humo del CRM |
| `scripts/oci/lint.sh` | Tu laptop | `bash -n` + ShellCheck de todos los scripts (sin sudo) |
| `docker-compose.prod.yml` | VM | Servicio Postgres |
| `deploy/oci/*` | VM | Timer systemd y plantillas de configuración |

---

## Parte A — En tu laptop (15 min, antes de la cuenta)

**A1. Llave SSH para la VM**
```bash
ssh-keygen -t ed25519 -C "kaisen.ai.santiago.cto@gmail.com" -f ~/.ssh/id_ed25519_kaisen
cat ~/.ssh/id_ed25519_kaisen.pub     # esta línea (ssh-ed25519 AAAA...) es la que pegas en Oracle
```
El archivo **sin** `.pub` es privado: nunca se copia ni se comparte.

**A2. Llave de cifrado de backups (age)**
```bash
sudo apt install -y age
mkdir -p ~/.config/kaisen && chmod 700 ~/.config/kaisen
age-keygen -o ~/.config/kaisen/jerico-backup.agekey
age-keygen -y ~/.config/kaisen/jerico-backup.agekey    # imprime la PÚBLICA: age1...
```
- La **privada** (`AGE-SECRET-KEY-...`) se queda en tu laptop **y** en tu gestor de contraseñas. Si la pierdes, los backups no se pueden abrir.
- La **pública** (`age1...`) es la única que va a la VM.

**A3. Tailscale**: verifica que tu laptop está en la tailnet de Kaisen (`tailscale status`) y que puedes entrar a la consola de administración (login.tailscale.com) para aprobar la VM.

**A4. Llaves del equipo (opcional ahora)**: pide a Nicolás, Juan Pablo, Esteban y Santiago Jr su línea `ssh-ed25519 ...` **pública**. Si no las tienes, se pueden añadir después.

---

## Parte B — Crear la cuenta (30 min + espera de activación)

1. Abre **oracle.com/cloud/free** → *Start for free*.
2. Datos:
   - **Correo:** `kaisen.ai.santiago.cto@gmail.com` (empresa, no personal).
   - **Account name (tenancy):** algo como `kaisenai` (será parte de tu URL de acceso).
   - **Home region:** **Colombia Central (Bogotá)**. ← irreversible.
   - Datos reales de dirección y teléfono.
3. **Tarjeta**: solo verifica identidad (puede aparecer una retención temporal pequeña que se devuelve). Si la rechaza, prueba otra tarjeta física de crédito; las virtuales o de débito a veces fallan.
4. Espera el correo **"Your Oracle Cloud account is fully provisioned"**. Hasta entonces muchas pantallas fallan: es normal.
5. Ya dentro de la consola (cloud.oracle.com):
   - **MFA:** perfil (arriba a la derecha) → *My profile* → *Security* / *Multi-factor authentication* → activar con una app (Google Authenticator, 1Password...).
   - **Alerta de presupuesto:** menú ☰ → *Billing & Cost Management* → *Budgets* → *Create Budget* → monto **1 USD**, alerta al 100 % al correo de empresa.
   - **Compartment:** ☰ → *Identity & Security* → *Compartments* → *Create* → nombre `kaisen-jerico`. Copia su **OCID** a un bloc de notas.

✅ **Listo cuando:** puedes entrar con MFA, la alerta de $1 existe y ves el compartment `kaisen-jerico`.

---

## Parte C — Red (15 min)

1. ☰ → *Networking* → *Virtual cloud networks* → selecciona el compartment `kaisen-jerico` (filtro a la izquierda) → **Start VCN Wizard** → *Create VCN with Internet Connectivity*.
2. Nombre `jerico-vcn`; deja los rangos por defecto → *Create*.
3. Abre la subred **pública** creada → su **Security List** → *Ingress Rules*:
   - Edita la regla TCP **22**: cambia *Source CIDR* de `0.0.0.0/0` a **tu IP pública + `/32`** (tu IP: `curl -4 ifconfig.me` en la laptop).
   - Añade regla **UDP 41641** desde `0.0.0.0/0` (Tailscale directo; opcional pero mejora velocidad).
   - Confirma que **no** existen reglas para 5432, 6379 u 8000.
4. Copia el **OCID de la subred pública** (lo necesitas solo para el Plan B).

> Si tu IP de casa cambia y pierdes el SSH antes de terminar la Parte F, vuelve aquí y actualiza la IP.

---

## Parte D — Crear la VM (15 min, o más si no hay capacidad)

☰ → *Compute* → *Instances* → compartment `kaisen-jerico` → **Create instance**:

| Campo | Valor |
|---|---|
| Name | `jerico-core-oracle-01` |
| Image | *Change image* → **Canonical Ubuntu 24.04** (la variante aarch64 aparece al elegir shape Ampere) |
| Shape | *Change shape* → **Ampere** → `VM.Standard.A1.Flex` → **2 OCPU, 12 GB** |
| Networking | `jerico-vcn`, subred **pública**, *Assign public IPv4 address* = Sí |
| SSH keys | *Paste public keys* → pega `~/.ssh/id_ed25519_kaisen.pub` |
| Boot volume | *Specify a custom boot volume size* → **100 GB** |

Revisa que diga *Always Free-eligible* y **Create**. Cuando quede en `RUNNING`, copia la **Public IP address**.

### 🅱️ Plan B si sale "Out of host capacity"

Es habitual con ARM gratis y **no es culpa tuya**. Bogotá tiene un solo datacenter (AD), así que se juega con *fault domains* y horarios. En orden:

1. **Reintenta a mano** cambiando *Placement → Fault domain* (1, 2, 3). Prueba en otro horario: madrugada y fines de semana suelen ir mejor.
2. **Script de reintento automático** en Cloud Shell (no requiere instalar nada):
   - Consola → icono **`>_`** (Cloud Shell) arriba a la derecha.
   - En Cloud Shell, menú ⚙ → *Upload* → sube `scripts/oci/00_retry_launch_a1.sh` y tu `id_ed25519_kaisen.pub` (renómbralo `jerico_ssh.pub`).
   ```bash
   export COMPARTMENT_ID=ocid1.compartment...   # Parte B
   export SUBNET_ID=ocid1.subnet...             # Parte C
   export SSH_PUBKEY_FILE=~/jerico_ssh.pub
   bash 00_retry_launch_a1.sh
   ```
   Reintenta cada 90 s, rota fault domains, se niega a pedir más de 2/12 y nunca crea una segunda VM con el mismo nombre. Si Cloud Shell se cierra, vuelve a lanzarlo.
3. **Empezar más pequeño:** 1 OCPU / 6 GB (también gratis) y ampliar a 2/12 después con *Edit → Shape* (la ampliación también depende de capacidad, pero suele pasar).
4. **Lo que NO hacemos:** la micro x86 `E2.1.Micro` (1 GB, rompe la regla ARM64 de Jericó), otra región (la cuenta gratis solo tiene Bogotá) ni pasar a pago (decisión del CTO). Si nada funciona en 1–2 semanas, se reabre esa decisión con evidencia.

✅ **Listo cuando:** la VM está `RUNNING` y tienes su IP pública.

---

## Parte E — Primer ingreso y bootstrap (20 min)

Desde tu laptop, en la carpeta del repo:
```bash
IP=<IP_PUBLICA>
scp -i ~/.ssh/id_ed25519_kaisen scripts/oci/01_bootstrap.sh ubuntu@$IP:~
ssh -i ~/.ssh/id_ed25519_kaisen ubuntu@$IP
```
Dentro de la VM:
```bash
chmod +x 01_bootstrap.sh
sudo KEY_NICOLAS="ssh-ed25519 AAAA... nicolas" \
     KEY_JPABLO="ssh-ed25519 AAAA... jpablo" \
     ./01_bootstrap.sh          # las KEY_* que no tengas, omítelas
```
Qué hace: actualiza el sistema, cambia el firewall de Oracle por **ufw** (entrante denegado), instala Tailscale y Docker (con puertos por defecto solo en 127.0.0.1), crea los usuarios del equipo y desactiva el login por contraseña y root. Tarda 5–10 min.

✅ **Listo cuando:** termina con `BOOTSTRAP COMPLETADO`. **No cierres esta sesión todavía.**

---

## Parte F — Tailscale (10 min)

En la misma sesión de la VM:
```bash
sudo tailscale up --hostname=jerico-oracle
```
Abre el enlace que imprime, inicia sesión con la cuenta de Kaisen y aprueba el equipo. Luego, **desde otra terminal de tu laptop**:
```bash
ssh -i ~/.ssh/id_ed25519_kaisen santiago@jerico-oracle
```
Si entra, ya tienes acceso privado. Añade a `~/.ssh/config` de tu laptop para no repetir la llave:
```
Host jerico-oracle
    User santiago
    IdentityFile ~/.ssh/id_ed25519_kaisen
```
Recomendado en la consola de Tailscale: en la máquina `jerico-oracle` → *Disable key expiry* (si no, a los 180 días se desconecta).

✅ **Listo cuando:** `ssh jerico-oracle` funciona por Tailscale.

---

## Parte G — Subir el repo y PostgreSQL 16 (15 min)

Desde tu laptop (copia lo commiteado, sin `.env` ni archivos sin trackear):
```bash
scripts/oci/sync_repo_to_vps.sh santiago@jerico-oracle
```
En la VM, como `santiago`:
```bash
/opt/jerico/app/scripts/oci/02_postgres.sh
```
Qué hace: genera una contraseña aleatoria en `/opt/jerico/secrets/postgres_password` (fuera de Git), levanta `postgres:16-alpine` publicando **solo** `127.0.0.1:5432`, verifica que esté *healthy* y que el puerto no salga de loopback, y deja la URL para Jericó en `/opt/jerico/secrets/postgres_url` (irá a `JERICO_POSTGRES_URL` del `.env` en la fase de despliegue).

Para entrar a la base desde tu laptop sin exponer nada: `ssh -L 5432:127.0.0.1:5432 jerico-oracle` y conecta a `localhost:5432`.

✅ **Listo cuando:** el script imprime `5432 solo en 127.0.0.1`.

---

## Parte H — Backup nocturno cifrado fuera de la VM (25 min)

Los backups van a **OCI Object Storage** (20 GB gratis), separado de la VM. Están cifrados con tu llave age: Oracle no puede leerlos y si la VM cae, siguen ahí.

**H1. Bucket** — ☰ → *Storage* → *Buckets* → compartment `kaisen-jerico` → *Create Bucket* → nombre `jerico-backups`, *Standard*, **sin** acceso público. Anota el **Namespace** que aparece en los detalles del bucket.

**H2. Credenciales S3** — perfil → *My profile* → *Customer secret keys* → *Generate secret key* → nombre `jerico-backup`. Copia la **secret** en ese momento (no se vuelve a mostrar) y el **Access key** de la tabla.

**H3. Configuración en la VM** (como `santiago`, con sudo):
```bash
sudo mkdir -p /etc/jerico
sudo cp /opt/jerico/app/deploy/oci/backup.env.example /etc/jerico/backup.env
sudo cp /opt/jerico/app/deploy/oci/rclone.conf.example /etc/jerico/rclone.conf
sudo chmod 600 /etc/jerico/*
sudo nano /etc/jerico/backup.env     # AGE_RECIPIENT = tu llave PÚBLICA age1... (Parte A2)
sudo nano /etc/jerico/rclone.conf    # access key, secret, <NAMESPACE>
```
Para no dejar secretos en el historial: antes de editar, `set +o history`; al terminar, `set -o history`.

**H4. Instalar y probar**:
```bash
sudo /opt/jerico/app/scripts/oci/03_backups.sh
```
Valida la configuración (rechaza valores sin completar o una llave privada por error), instala el timer (todos los días 03:15 hora Bogotá) y hace un backup de prueba que debe aparecer en el bucket.

**H5. Probar que puedes restaurar** (una vez, desde tu laptop): descarga el `.dump.age` del bucket desde la consola y:
```bash
age -d -i ~/.config/kaisen/jerico-backup.agekey jerico_XXXX.dump.age > prueba.dump
pg_restore --list prueba.dump | head      # debe listar el contenido, sin errores
```
Restauración real en la VM (solo en una emergencia):
`age -d -i <llave> archivo.dump.age | docker exec -i jerico-postgres pg_restore -U jerico -d jerico --clean --if-exists`

✅ **Listo cuando:** el backup de prueba está en el bucket y `pg_restore --list` lo abre.

---

## Parte I — Cierre perimetral (10 min)

Desde una sesión **que entró por Tailscale** (`ssh jerico-oracle`):
```bash
sudo /opt/jerico/app/scripts/oci/04_lockdown.sh
```
El script se niega a cerrar si Tailscale no está conectado o si tu sesión no viene por Tailscale, para que no te quedes fuera.

Después, en la consola OCI → Security List de la subred → **borra la regla TCP 22**. Desde ese momento la VM no acepta ninguna conexión entrante desde internet; solo por Tailscale.

---

## Parte J — Verificación final (5 min)

```bash
sudo /opt/jerico/app/scripts/oci/verify_vps.sh
```
Debe terminar en `RESULTADO: OK`. Revisa: ARM64, ufw activo, SSH sin contraseña ni root, Tailscale, Docker en 127.0.0.1, sin puertos expuestos, 5432 solo en loopback, Postgres healthy, timer y backup de las últimas 26 h.

### Checklist para dar la fase por cerrada

- [ ] Cuenta en Bogotá, MFA, alerta de $1, compartment `kaisen-jerico`
- [ ] VM `jerico-core-oracle-01` A1.Flex 2/12, Ubuntu 24.04 ARM, 100 GB
- [ ] `ssh jerico-oracle` por Tailscale; key expiry desactivado
- [ ] Postgres 16 healthy, solo en 127.0.0.1
- [ ] Backup en el bucket y restauración probada con la llave age
- [ ] Regla 22 borrada de la Security List; `verify_vps.sh` → OK
- [ ] Llave privada age guardada en el gestor de contraseñas

---

## Si algo sale mal

| Síntoma | Qué hacer |
|---|---|
| No entro por SSH después del bootstrap | Usa la sesión `ubuntu` que dejaste abierta. Si se cerró: consola → instancia → *Console connection* (consola serie, no depende de la red). |
| Me quedé fuera tras cerrar el 22 | Comprueba Tailscale en la laptop (`tailscale status`). Como emergencia, vuelve a añadir la regla 22 con tu IP en la Security List y `sudo ufw allow 22/tcp` desde la consola serie. |
| "Out of host capacity" | Plan B (Parte D). |
| La alerta de $1 se dispara | Billing → *Cost Analysis* para ver qué recurso cobra y bórralo o redúcelo; casi siempre es un shape o disco por encima de lo gratis. |
| `03_backups.sh` dice que rclone no lista el remoto | Revisa Namespace, access key y secret en `/etc/jerico/rclone.conf`; la región del endpoint debe ser `sa-bogota-1`. |
| Correo de Oracle por instancia "idle" | Ver siguiente sección. |

## Riesgo de "VM inactiva" (leer)

Oracle puede **recuperar** VMs Always Free que en 7 días tengan a la vez CPU, red y memoria por debajo del 20 %. Una VM recién creada sin Jericó corriendo cae en ese caso. Por eso: (1) desplegar Jericó (runbook §3) poco después de cerrar esta guía, y (2) tratar la VM como **desechable**: todo está en scripts y los datos en backups fuera de ella, así que reconstruirla es repetir esta guía.

## Mantenimiento mensual (10 min)

- Billing → costo del mes = **$0**.
- Revisar la página oficial *Always Free Resources* por si Oracle cambia límites otra vez.
- Comprobar que el último backup del bucket se abre con la llave age.
- `sudo /opt/jerico/app/scripts/oci/verify_vps.sh`.

## Cómo se revisaron los scripts

- `scripts/oci/lint.sh` instala ShellCheck (`shellcheck-py`) en un venv temporal fuera del proyecto y pasa `bash -n` y ShellCheck **en todas las severidades** sobre `scripts/oci/*.sh`. Resultado al 11/10/2026: ShellCheck 0.11.0, 0 hallazgos (las 4 notas informativas intencionales están anotadas con `# shellcheck disable=` y su motivo).
- **No probado todavía:** ninguna ejecución real en una VM ni en Cloud Shell, ni `docker compose config` del override de producción (no había Docker en la laptop de revisión). El primer uso real es el Día 1.

---
> 🕒 **Última modificación:** 11/10/2026 20:25 (Claude Code · Opus 5.5)
