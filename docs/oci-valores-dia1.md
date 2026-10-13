---
tipo: valores-operativos
proyecto: Jericó — Kaisen AI
estado: listo-para-consola (nada creado por agentes)
creado: "13/10/2026 00:25"
modificado: "13/10/2026 00:29"
---

# Valores exactos para la consola OCI — Día 1

**Tenancy:** `kaisen_cloud` · **Región:** `sa-bogota-1` (Colombia Central, 1 AD) · **Cuenta:** en periodo de prueba (fin aprox. ~20/10/2026).
**Uso:** quien cree los recursos (el CTO o el orquestador con su aprobación) copia estos valores tal cual. Si una pantalla ofrece algo que no está aquí, se deja el valor por defecto **solo** si no cambia el costo; ante la duda, **detenerse**.
**Pasos detallados:** `docs/guia-oci-principiantes.md` (Partes B–D y H). **Checklist:** `docs/dia-1-oci.md`.

### Leyenda de la columna «Costo»

- ✅ **AF**: dentro del cupo Always Free (sigue gratis después de la prueba si no se supera el cupo).
- 🆓 **Sin cargo**: servicio o componente que Oracle no factura (no consume cupo).
- ⛔ **Pago**: consume créditos de prueba y desaparece al acabar la prueba. **No crear.**

> En la cuenta en prueba, la consola **no avisa** al crear algo de pago. La etiqueta *Always Free-eligible* de la pantalla de creación es la comprobación que manda. Los límites se verificaron por última vez el 30/09/2026 (Always Free ARM: 2 OCPU / 12 GB); conviene revisar de nuevo la página oficial *Always Free Resources* el mismo día.

---

## 1. Cuenta y gobierno

| Recurso | Campo | Valor | Costo |
|---|---|---|---|
| MFA | Método | App TOTP en el usuario administrador | 🆓 |
| Presupuesto ✅ **creado el 13/10/2026** (orquestador, con OK del CTO) | Nombre | `kaisen-alerta-1usd` | 🆓 |
| | Objetivo | Compartment **raíz** `kaisen_cloud` (toda la tenancy) | |
| | Periodo / monto | Mensual · **1 USD** | |
| | Regla de alerta | Gasto **real** (*Actual spend*) ≥ **1 %** del presupuesto (**0,01 USD**: avisa ante cualquier cobro) → correo `kaisen.ai.santiago.cto@gmail.com` | |
| Compartment ✅ **creado el 13/10/2026** (orquestador, con OK del CTO) | Nombre | `kaisen-jerico` | 🆓 |
| | Padre | raíz `kaisen_cloud` | |
| | Descripción | `Proyecto Jerico (Kaisen AI) - solo recursos Always Free` | |

## 2. Red (VCN Wizard → *Create VCN with Internet Connectivity*)

> **Estado 13/10/2026:** la VCN **no está creada**. Se bloqueó el permiso para crearla desde el navegador, y el CTO decide cómo seguir. Los valores de abajo no cambian.

| Campo | Valor | Costo |
|---|---|---|
| Compartment | `kaisen-jerico` | |
| Nombre VCN | `jerico-vcn` | ✅ AF (hasta 2 VCN) |
| CIDR de la VCN | `10.0.0.0/16` (por defecto del wizard) | |
| Subred pública | `10.0.0.0/24` (por defecto del wizard) · aquí va la VM | 🆓 |
| Subred privada | `10.0.1.0/24` (la crea el wizard; Fase 0 no la usa) | 🆓 |
| Gateways | Internet Gateway (necesario). El wizard también crea NAT y Service Gateway: no se usan | 🆓 componentes de red. Si el wizard falla por límite de NAT o Service Gateway, crear la VCN a mano solo con Internet Gateway y la subred pública. |
| IPv6 | **No** | |
| DNS | Resolución DNS activada (por defecto) | 🆓 |

### 2.1 Security List de la subred pública — reglas de entrada (Ingress)

| # | Stateless | Origen (Source CIDR) | Protocolo | Puerto destino | Motivo | Acción |
|---|---|---|---|---|---|---|
| 1 | No | **`<IP_PUBLICA_DEL_CTO>/32`** (`curl -4 ifconfig.me` en la laptop) | TCP | **22** | SSH inicial; se **borra** al terminar la Parte I | **Editar** la regla por defecto, que trae `0.0.0.0/0` |
| 2 | No | `0.0.0.0/0` | UDP | **41641** | Tailscale WireGuard directo (opcional, mejora la latencia) | Añadir |
| 3 | No | `0.0.0.0/0` | ICMP tipo 3, código 4 | — | Path MTU (por defecto del wizard) | Conservar |
| 4 | No | `10.0.0.0/16` | ICMP tipo 3 | — | Diagnóstico interno (por defecto del wizard) | Conservar |

**Prohibido en Ingress (no debe existir ninguna regla así):**

| Puerto | Servicio | Motivo |
|---|---|---|
| TCP 5432 | PostgreSQL | Solo `127.0.0.1` dentro de la VM (D2) |
| TCP 6379 | Redis | Solo `127.0.0.1` / red Docker |
| TCP 8000 | API Jericó | Solo `127.0.0.1`; acceso por Tailscale |
| TCP/UDP *cualquiera* desde `0.0.0.0/0` | — | Salvo UDP 41641 y los ICMP de la tabla |

**Salida (Egress):** la regla por defecto, *All protocols* hacia `0.0.0.0/0`. Se necesita para actualizaciones, Docker y Tailscale.

**Estado final, tras la Parte I:** se borra la regla #1. Quedan #2, #3 y #4. No queda ningún TCP abierto a internet.

## 3. VM (Compute → Instances → Create instance)

| Campo | Valor | Costo |
|---|---|---|
| Name | `jerico-core-oracle-01` | |
| Compartment | `kaisen-jerico` | |
| Placement | AD-1 (Bogotá tiene un solo AD); fault domain: automático. En el Plan B, rotar FD-1/2/3 | |
| Image | **Canonical Ubuntu 24.04** (la consola elige la build **aarch64** al usar shape Ampere). **No** usar la variante *Minimal* ni Oracle Linux | 🆓 |
| Shape | **`VM.Standard.A1.Flex`** (Ampere, ARM64) | ✅ AF |
| OCPU | **2** | ✅ AF (máximo vigente) |
| Memoria | **12 GB** | ✅ AF (máximo vigente) |
| ⛔ No usar | Más de 2 OCPU o 12 GB (p. ej. 4/24); cualquier shape AMD, Intel o GPU (`VM.Standard.E*`, `VM.Standard3`, `VM.GPU*`), salvo la micro `E2.1.Micro`, que es gratis pero x86 y no sirve para Jericó; *capacity reservation* | ⛔ Pago (en prueba no avisa) |
| VCN / Subred | `jerico-vcn` / **subred pública** `10.0.0.0/24` | |
| Public IPv4 | **Assign a public IPv4 address = Sí** (efímera). **No** reservar IP | 🆓 IP efímera |
| Private IPv4 | Automática | |
| SSH keys | *Paste public keys* → contenido de `~/.ssh/id_ed25519_kaisen.pub`. La crea el CTO con `dia1_laptop.sh`; solo se pega la línea **pública** `ssh-ed25519 ...` | |
| Boot volume | *Specify a custom boot volume size* = **100 GB** | ✅ AF (200 GB en total entre boot y bloque) |
| Rendimiento del boot volume | **Balanced** (10 VPU/GB, por defecto). **No** *Higher/Ultra High Performance* | ⛔ si se sube |
| Cifrado en tránsito | Por defecto | 🆓 |
| Block volumes adicionales | **Ninguno** en Fase 0 | |
| Oracle Cloud Agent | Por defecto | 🆓 |
| Comprobación final | La pantalla muestra **Always Free-eligible** antes de *Create* | |

**Reservado para después (no crear el Día 1):** una segunda VM A1 (consumiría el cupo de 2 OCPU), las micro `E2.1.Micro` (x86, no sirven para Jericó), bases de datos *Autonomous* y balanceadores.

## 4. Backups (Parte H, al final del Día 1)

| Recurso | Campo | Valor | Costo |
|---|---|---|---|
| Bucket | Nombre | `jerico-backups` | ✅ AF (20 GB entre todos los niveles) |
| | Compartment | `kaisen-jerico` | |
| | Storage tier | **Standard** | |
| | Visibilidad | **Privado** (sin *pre-authenticated requests* públicas) | |
| | Versionado | **Desactivado** (duplicaría el espacio) | |
| | Cifrado | Llaves gestionadas por Oracle (por defecto) | 🆓 |
| Customer secret key | Nombre | `jerico-backup` (perfil del usuario → *Customer secret keys*) | 🆓 |
| | Uso | `access_key_id` y `secret_access_key` de `/etc/jerico/rclone.conf` en la VM. El *secret* se muestra **una sola vez**: va al gestor de contraseñas, nunca a Git ni a un chat | |
| Endpoint S3 | Valor | `https://<NAMESPACE>.compat.objectstorage.sa-bogota-1.oraclecloud.com` | |
| Retención | Local / remota | 7 días / 30 días (`backup.env`) | |

## 5. Nombres fuera de OCI (referencia)

| Elemento | Valor |
|---|---|
| Nodo Tailscale | `jerico-oracle` |
| Usuario de administración en la VM | `santiago` (más `nicolas`, `jpablo`, `esteban`, `santiagojr`) |
| Llave SSH (laptop) | `~/.ssh/id_ed25519_kaisen` (privada, no sale de la laptop) |
| Llave age (laptop) | `~/.config/kaisen/jerico-backup.agekey` (privada, laptop + gestor de contraseñas) |
| Ruta de la app en la VM | `/opt/jerico/app` |

---
> 🕒 **Última modificación:** 13/10/2026 00:29 (Claude Code · Opus 5.5)
