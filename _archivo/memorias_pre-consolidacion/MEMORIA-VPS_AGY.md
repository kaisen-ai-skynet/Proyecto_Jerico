# Memoria de Frente: Infraestructura & Aprovisionamiento VPS Oracle
**Proyecto:** Jericó AI-OS — Kaisen AI
**Frente:** Fase 4 · Frente 3 (Infraestructura / Ops)
**Fecha:** 29/09/2026
**Responsable:** Santiago González (CTO / Sudo Supremo) & Frente Infraestructura

---

## 1. Misión
Dejar listo para ejecución determinista el runbook de aprovisionamiento del VPS Oracle de Jericó, integrando los insumos operacionales y de seguridad del equipo (bootstrap, hardening, Tailscale, Compose con Redis y binds de red privada). Operación 100% en modo preparación, sin ejecución contra servidores remotos.

---

## 2. Insumos
- `docs/despliegue-vps.md`: Guía de despliegue y actualización con Docker Compose en red interna.
- `scripts/bootstrap_vps_oracle.sh`: Script automatizado de aprovisionamiento (paquetes base, iptables Oracle, Tailscale, Docker CE, creación de 5 usuarios ed25519, hardening SSH, Coolify y directorios en `/opt/jerico`).
- `docs/decisiones/03-despliegue-vps.md`: Dossier de decisión técnica (Docker Compose, binds en `127.0.0.1:8000`, Zero-Trust con Tailscale).
- Commits `e802572` y `6ff425e`: Registro histórico de la guía VPS y ajustes de formato.
- `docker-compose.yml`: Inventario de servicios (`jerico-core:0.2.0`, `redis:7.4-alpine`), red `jerico_net`, volumen `jerico_redis_data` y publicación estricta en `127.0.0.1`.
- `.env.example`: Inventario de las 30 variables de configuración sin valores expuestos.
- `docs/spec/PLAN_CONEXION_VPS_ORACLE_EQUIPO.md`: Matriz de roles del equipo Kaisen AI, topología de red OCI y políticas de seguridad.

---

## 3. Estado
- **Completado:** `docs/runbook-aprovisionamiento-vps.md` creado y estructurado bajo los 6 ejes del contrato:
  1. **Pre-vuelo:** Checklist binaria completa (tenancy OCI, shape ARM64 Ampere `VM.Standard.A1.Flex`, 50-100 GB disco, 5 llaves SSH `ed25519`, reglas de NSG/Security List, Tailscale MagicDNS, presupuesto en $0 y ventana de 60 min).
  2. **Pasos numerados de aprovisionamiento:** Comandos exactos, idempotentes y con criterios demostrables de verificación (inyección de variables de llaves para `bootstrap_vps_oracle.sh`, login en Tailnet `kaisen.ai`, verificación de usuarios y eliminación de regla Ingress puerto 22 en OCI).
  3. **Puesta en marcha de Jericó:** Despliegue con Docker Compose en `/opt/jerico/app`, chequeos de salud con ping real a Redis (`PONG`), validación de almacenamiento de claves de sesión para descartar el fallback de RAM, verificación de binds exclusivos en `127.0.0.1` y prueba E2E L0 autenticada.
  4. **Datos y secretos:** Inventario de las 30 variables de entorno requeridas por la aplicación, protocolo de carga segura eludiendo el historial de bash (`set +o history` / scp cifrado) con permisos `600`.
  5. **Rollback y recuperación:** Procedimientos específicos para fallos en OCI, pérdida de conectividad Tailscale (vía consola OOB serie de OCI), errores en Docker Compose y fallos de persistencia en Redis.
  6. **Criterios de ventana exitosa y plantilla de reporte:** 8 verificaciones de cierre binarias y formato estándar de informe para elevación al CTO.

---

## 4. Pendientes
- [ ] Programación y apertura formal de la ventana operativa autorizada por el CTO (Santiago González).
- [ ] Provisión efectiva de la instancia en la consola de OCI y ejecución en vivo de `scripts/bootstrap_vps_oracle.sh`.
- [ ] Autorización del nodo `jerico-oracle` en la consola administrativa de Tailscale.
- [ ] Cierre definitivo del puerto 22 público en la Security List de OCI tras corroborar acceso SSH de los 5 ingenieros.
- [ ] Inyección de secretos de producción y ejecución de `scripts/test_e2e.sh` en el nodo remoto.

---

## 5. Invocación
Para continuar o auditar este frente en la ventana operativa:
```bash
# Verificar estado del árbol git y artefactos del frente
git status
git log -1 --stat

# Consultar el runbook antes de la ejecución
less docs/runbook-aprovisionamiento-vps.md
```
*Nota de coexistencia:* El frente paralelo mantiene su trabajo en `docs/SPEC_JERICO_V2.md` y `.agents/agy/MEMORIA.md`. No colisionar con dichos archivos.
