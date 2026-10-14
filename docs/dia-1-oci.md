---
tipo: checklist-operativa
proyecto: Jericó — Kaisen AI
estado: en-pausa (VM OCI aplazada; CRM desplegado en kaisen-server)
creado: "11/10/2026 20:20"
modificado: "13/10/2026 19:50"
---

# Día 1 — Oracle Cloud + laptop en una sola sesión

> 🔀 **Cambio de rumbo (13/10/2026 10:10, decisión del CTO).** Como no hubo capacidad A1 en OCI, **Jericó CRM se desplegó en `kaisen-server`** (`100.79.169.121`): directorio `~/jerico`, `docker compose -p jerico`, **solo el servicio `jerico-crm`**, estado `healthy` (según el orquestador). La **VM de OCI queda como migración futura**. El reintento en Cloud Shell (`00_retry_launch_a1.sh`) **se cortó en el intento 153/200** sin conseguir capacidad.
> Lo que ya existe en OCI se conserva (presupuesto, compartment `kaisen-jerico`, `jerico-vcn` y su Security List); no consume nada. Los bloques 4 y 5 quedan en pausa hasta que se retome la migración. Hasta entonces, el CRM corre en `kaisen-server`, sin el Postgres ni los backups de este checklist.

**Duración:** 3–4 h con pausas. **Dónde:** en casa, con la laptop que tiene este repo (los commits no están en GitHub hasta que alguien haga push; `sync_repo_to_vps.sh` copia desde la laptop).
**Detalle de cada paso:** `docs/guia-oci-principiantes.md` (las letras A–J remiten a sus partes).
Si un bloque falla, **detente ahí**: todo lo anterior queda bien hecho y se retoma otro día.

## Antes de sentarte (5 min)

- [ ] Tarjeta de crédito física a mano (solo verifica; Oracle no cobra en Always Free).
- [ ] Celular con app de autenticación (Google Authenticator, 1Password...) para MFA.
- [ ] Acceso al correo `kaisen.ai.santiago.cto@gmail.com`.
- [ ] Gestor de contraseñas abierto (vas a guardar la llave age y el *secret key* de Oracle).
- [ ] Opcional: llaves SSH públicas de Nicolás, Juan Pablo, Esteban y Santiago Jr.

## Bloque 1 · Laptop (20–30 min) — guía, Parte A

```bash
cd ~/Kaisen_AI/01_Proyectos/Proyecto_Jerico
scripts/oci/dia1_laptop.sh
```
Instala age y **Docker**, crea la llave SSH y la llave age, comprueba Tailscale y hace la **prueba de humo del contenedor CRM de la fase 1**: construye la imagen `jerico-crm:0.2.0` y verifica que se niega a arrancar sin secretos (código 2, como pide la spec).

- [ ] El script termina imprimiendo tu llave SSH pública y tu llave age pública.
- [ ] Guardaste `~/.config/kaisen/jerico-backup.agekey` en el gestor de contraseñas.
- [ ] Copiaste las dos llaves **públicas** a un bloc de notas para los pasos siguientes.

## Bloque 2 · Cuenta Oracle (30 min + espera) — Parte B

- [x] Cuenta creada: tenancy `kaisen_cloud`, **home region Bogotá** (20/09/2026; verificado el 13/10/2026).
- [ ] ⚠️ La cuenta está en **periodo de prueba** (fin aprox. ~20/10/2026): la consola deja crear recursos de pago sin avisar y, al acabar la prueba, lo que no sea Always Free se detiene y se elimina. **Crea solo lo de `docs/oci-valores-dia1.md`** y no pulses "Upgrade". Detalle: guía, sección "Estado real de la cuenta y periodo de prueba".
- [x] Presupuesto `kaisen-alerta-1usd` sobre la raíz `kaisen_cloud`: mensual, 1 USD, alerta por **gasto real al 1 %** (0,01 USD) a `kaisen.ai.santiago.cto@gmail.com` (creado por el orquestador el 13/10/2026, con OK del CTO).
- [x] Compartment `kaisen-jerico` bajo la raíz, descripción «Proyecto Jerico (Kaisen AI) - solo recursos Always Free» (creado por el orquestador el 13/10/2026, con OK del CTO). Anota su OCID para el Plan B.
- [ ] MFA activado en el usuario administrador (sin confirmar a 13/10/2026).

> **Reparto acordado:** el orquestador (Claude en Chrome) crea en la consola el presupuesto, el compartment, la VCN y, cuando exista la llave SSH del bloque 1, la VM. Tú aprobarás cada paso; **la llave SSH y la llave age las creas tú** con `dia1_laptop.sh`. Ningún agente las crea ni las lee.

## Bloque 3 · Red y VM (30 min) — Partes C y D

> ✅ **Pendiente crítico resuelto (13/10/2026):** la Security List por defecto de `jerico-vcn` ya está ajustada (lo hizo el orquestador). Hoy tiene:
> - **TCP 22 solo desde la IP pública del CTO (`/32`)**. La regla `0.0.0.0/0` fue **borrada**.
> - ICMP 3,4 desde `0.0.0.0/0` e ICMP 3 desde `10.0.0.0/16` (las que trae el wizard por defecto).
> - Ninguna regla para 5432, 6379 u 8000.
>
> **UDP 41641 queda opcional:** no se añadió porque el permiso quedó bloqueado. Sin esa regla, Tailscale funciona por los relays DERP (algo más de latencia, sin efecto en la seguridad). Se puede añadir más adelante para tener conexión directa.
> Si tu IP pública cambia antes de terminar el bloque 5 (cierre perimetral), actualiza la regla 22 o no podrás entrar por SSH directo.
> 🔑 La llave `~/.ssh/id_ed25519_kaisen.pub` ya existe (bloque 1 ejecutado el 13/10/2026).

> ⏳ **VM sin crear por falta de capacidad (13/10/2026 00:56).** La consola respondió «Capacidad insuficiente en VM.Standard.A1.Flex en AD-1» **con 2 OCPU / 12 GB y también con 1 OCPU / 6 GB**: 100 GB de disco, Ubuntu 24.04, subred pública y la llave `id_ed25519_kaisen.pub`. Es la falta de capacidad ARM habitual en la capa gratis; no es un error de configuración.
> **Se pasa al Plan B** (guía, Parte D): el CTO corre `scripts/oci/00_retry_launch_a1.sh` en **OCI Cloud Shell**:
> ```bash
> export COMPARTMENT_ID=<OCID de kaisen-jerico>
> export SUBNET_ID=<OCID de la subred pública de jerico-vcn>
> export SSH_PUBKEY_FILE=~/jerico_ssh.pub      # id_ed25519_kaisen.pub subido a Cloud Shell
> bash 00_retry_launch_a1.sh                   # 2 OCPU / 12 GB por defecto
> # Variante más pequeña (también Always Free; se amplía después): OCPUS=1 MEMORY_GB=6 bash 00_retry_launch_a1.sh
> ```
> El script reintenta cada 90 s, rota los fault domains 1→2→3, se niega a pedir más de 2/12 y nunca crea una segunda VM con el mismo nombre. Si Cloud Shell se cierra, se relanza sin riesgo. Las madrugadas y los fines de semana suelen tener más capacidad. Mientras tanto, se puede avanzar con el bloque 6 (CRM en la laptop).
> 🛑 **Resultado (13/10/2026):** el CTO corrió el script en Cloud Shell y lo cortó en el intento **153/200**, todavía sin capacidad. Que llegara al intento 153 indica que el script reconocía las respuestas de la API como falta de capacidad o límite de peticiones (no se detuvo con «Error distinto a capacidad»). Para retomar la migración basta con relanzarlo con los mismos `export`.
> Si el script se detiene con «Error distinto a capacidad» pero el texto habla de capacidad, el mensaje de la API no coincide con el que busca el script: guarda las últimas líneas y pásalas para ajustarlo.

> 🔁 **Segundo intento y reintento continuo (13/10/2026 19:50).** Con apoyo de Gemini Argon se volvió a probar desde la consola con lo mínimo: **A1.Flex 1 OCPU / 6 GB**, Ubuntu 24.04, disco por defecto (46,6 GB) y fault domain elegido por Oracle → otra vez «Capacidad insuficiente en AD-1». La **VM.Standard.E2.1.Micro no se ofrece en `sa-bogota-1`**: la lista «Siempre gratis» sale vacía, aunque la página de límites muestra 2 núcleos. En Bogotá la única VM gratis es la A1.
> El script ahora sirve para correr **días seguidos en `kaisen-server`**: bucle sin límite (`MAX_ATTEMPTS=0`), 1 OCPU / 6 GB y 50 GB por defecto, espera de 300 s + 0–59 s aleatorios (el triple ante `TooManyRequests`), sin fijar fault domain, reintenta errores de red y se detiene solo ante cuota, permisos o parámetros. Busca solo el compartimento `kaisen-jerico` y su subred pública, y puede avisar por Telegram (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`).
> **Falta la llave de API (la crea el CTO):** consola → perfil → *Tokens y claves* → *Agregar clave de API* → *Generar par de claves* → *Descargar clave privada* → *Agregar*, y copiar el bloque *Vista previa del archivo de configuración*. En el servidor van a `~/.oci/oci_api_key.pem` y `~/.oci/config` (ambos `chmod 600`, nunca en el repo). Luego:
> ```bash
> pipx install oci-cli    # o: python3 -m venv ~/.oci-venv && ~/.oci-venv/bin/pip install oci-cli
> oci iam region list --query 'data[0].name'    # prueba de la llave
> tmux new -d -s oci-a1 'SSH_PUBKEY_FILE=~/.ssh/id_ed25519_kaisen.pub bash ~/jerico/scripts/oci/00_retry_launch_a1.sh 2>&1 | tee -a ~/oci-a1.log'
> ```
> Cuando salga la VM, se amplía a 2 OCPU / 12 GB desde la consola (*Editar unidad*, con reinicio).

- [x] VCN `jerico-vcn` creada con el wizard en `kaisen-jerico`: `10.0.0.0/16`, subred pública `10.0.0.0/24`, privada `10.0.1.0/24`, sin IPv6 (orquestador, 13/10/2026).
- [x] Security List ajustada: TCP 22 solo desde la `/32` del CTO (la regla `0.0.0.0/0` está borrada) y nada en 5432/6379/8000 (orquestador, 13/10/2026).
- [ ] *(Opcional)* Regla UDP 41641 desde `0.0.0.0/0` para que Tailscale conecte directo. Sin ella usa relays DERP.
- [ ] VM `jerico-core-oracle-01` (**aplazada a migración futura**: la consola falló por capacidad y el Plan B se cortó en el intento 153/200 el 13/10/2026): Ubuntu 24.04 aarch64, A1.Flex **2 OCPU / 12 GB**, 100 GB Balanced, llave SSH pública pegada, etiqueta *Always Free-eligible* visible.
- [ ] `RUNNING` e IP pública anotada. *Si sale "Out of host capacity": Plan B de la Parte D (Cloud Shell + `00_retry_launch_a1.sh`) y sigue con el bloque 6 mientras reintenta.*

## Bloque 4 · VM segura (40 min) — Partes E, F y G

```bash
IP=<IP_PUBLICA>
scp -i ~/.ssh/id_ed25519_kaisen scripts/oci/01_bootstrap.sh ubuntu@$IP:~
ssh -i ~/.ssh/id_ed25519_kaisen ubuntu@$IP
#   en la VM:  chmod +x 01_bootstrap.sh && sudo ./01_bootstrap.sh
#   en la VM:  sudo tailscale up --hostname=jerico-oracle    (aprueba el enlace)
# en OTRA terminal de la laptop (sin cerrar la anterior):
ssh -i ~/.ssh/id_ed25519_kaisen santiago@jerico-oracle
scripts/oci/sync_repo_to_vps.sh santiago@jerico-oracle
#   en la VM como santiago:  /opt/jerico/app/scripts/oci/02_postgres.sh
```
- [ ] `BOOTSTRAP COMPLETADO` · `ssh santiago@jerico-oracle` entra por Tailscale · *key expiry* desactivado en Tailscale.
- [ ] `02_postgres.sh` termina con `5432 solo en 127.0.0.1`.

## Bloque 5 · Backups y cierre (40 min) — Partes H, I y J

- [ ] Bucket privado `jerico-backups` · Namespace anotado · *Customer secret key* generada y guardada en el gestor.
- [ ] `/etc/jerico/backup.env` (llave age **pública**) y `/etc/jerico/rclone.conf` completados desde `deploy/oci/*.example`.
- [ ] `sudo /opt/jerico/app/scripts/oci/03_backups.sh` → backup de prueba visible en el bucket.
- [ ] Restauración probada en la laptop: `age -d -i ~/.config/kaisen/jerico-backup.agekey <archivo> > prueba.dump` (y `pg_restore --list prueba.dump` si tienes `postgresql-client`).
- [ ] Desde la sesión por Tailscale: `sudo /opt/jerico/app/scripts/oci/04_lockdown.sh`, y después borrar la regla TCP 22 en la Security List.
- [ ] `sudo /opt/jerico/app/scripts/oci/verify_vps.sh` → `RESULTADO: OK`.

## Bloque 6 · Prueba completa del CRM en la laptop (20 min, opcional)

La prueba de humo del bloque 1 no usa secretos. Para ver el bot funcionando de verdad en tu laptop:

1. En la raíz del repo, crea o actualiza `.env` (nunca se commitea) con, como mínimo, `JERICO_CRM_TELEGRAM_BOT_TOKEN`, `JERICO_CRM_FINGERPRINT_KEY` (p. ej. `openssl rand -hex 32`), `JERICO_CRM_SEED_CTO_TELEGRAM_ID` y `JERICO_CRM_SEED_CTO_EMAIL` (plantilla: `.env.example`).
2. `docker compose up -d --build jerico-crm`
3. `docker compose ps jerico-crm` → `healthy` al cabo de 1–2 min; `docker compose logs --tail=25 jerico-crm` sin errores.
4. Escríbele al bot desde tu Telegram y comprueba que responde.
5. `docker compose down` al terminar.

> Un mismo token de bot no puede hacer *polling* en dos sitios a la vez (Telegram responde 409). Si el bot ya corre en otro lado, usa un bot de pruebas.

- [ ] Contenedor `jerico-crm` healthy y el bot responde.

## Cierre del día

- [ ] Checklist de la guía (Parte J) completo.
- [ ] Avisar al equipo: acceso solo por `ssh <usuario>@jerico-oracle` vía Tailscale.
- [ ] **No dejar la VM ociosa muchos días:** el siguiente paso es desplegar Jericó (runbook §3). Oracle puede recuperar VMs gratis que pasan 7 días casi sin uso.

---
> 🕒 **Última modificación:** 13/10/2026 19:50 (Claude Code · Opus 5.5)
