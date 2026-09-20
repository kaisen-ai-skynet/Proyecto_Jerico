# 📋 Especificaciones Técnicas y Catálogo de Integraciones

Este documento consolida las especificaciones técnicas, esquemas de bases de datos, credenciales e identificadores requeridos para el funcionamiento de **Proyecto Jericó**.

---

## 1. Bases de Datos Notion ("Segundo Cerebro / Panita OS")

Página Padre Raíz: `e59a8560-3ffc-40fe-9d98-abff1c4b7561`

| Base de Datos | UUID | Propósito | Campos Clave y Tipos |
| :--- | :--- | :--- | :--- |
| **DB-01 SANCTUM** | `6006c308-5caf-4fa9-b67b-a4fbcd4acec4` | Devocional matutino | `Título` (title), `Fecha` (date), `Tipo` (select), `Pasaje Bíblico` (rich_text), `Revelación Central` (rich_text), `Aplicación a la Conducta` (rich_text), `Estado de Integración` (select). |
| **DB-02 MODO CUEVA** | `1ffa5bed-6d24-417c-a62b-ae9087ed113c` | Rendición de cuentas y hábitos | `Fecha` (ID único), `Día Cueva (Nº)` (number), `Foco Matutino` (checkbox), `Detox Innegociable` (checkbox), `Integridad Radical` (checkbox), `Métrica Física` (number), `Cigarrillos` (number), `Estado del Entorno` (select), `Vía de Escape Sana` (select), `Log del Día` (rich_text). |
| **DB-03 SOMPAN** | `3e16469a-d55e-46e8-aa45-c89642818f22` | Mapeo de proyectos y visión | `Nombre` (title), `Estado` (status), `Área` (select). |
| **DB-04 KAISEN/SKYNET** | `76591789-bfcd-4de3-a8cf-1131beed9d9e` | Registro de clientes y entregables | `Cliente` (title), `Estado` (status), `Servicios` (multi-select), `Enlace Vault` (url). |
| **DB-05 INCUBADORA** | `ebf3b948-6790-4781-a3dc-31b18a0624e2` | Ideas de producto y experimentación | `Idea` (title), `Potencial` (select), `Notas` (rich_text). |
| **DB-07 FINANZAS** | `3a5d70da-1b09-8111-90af-ce8a3b437d6e` | Auditoría financiera diaria | `Concepto` (title), `Monto` (number, format COP), `Tipo` (select: Ingreso/Gasto/Deuda), `Ámbito` (select: Personal/Kaisen), `Categoría` (select), `Fecha` (date), `Estado` (select: Pendiente/Pagado), `Nota` (rich_text). |

---

## 2. YouTrack Cloud (Gestión del Equipo)

* **URL Instancia:** `https://kaisensky.youtrack.cloud`
* **Proyecto Principal:** `DEMO` (ID interno `0-0`)
* **Proyectos Adicionales en Plan:** `CSB`, `COM`, `OPS`, `TAXIS`
* **Logins del Equipo:**
  * Santiago (CTO): `kaisen.ai.santiago.cto`
  * Daniel (Gerencia / Extracción): `kaisen.ai.daniel.gerencia`
  * Esteban (n8n / Workflows): `kaisen.ai.esteban.n8n`
  * Santiago Jr (Auditoría / BD): `kaisen.ai.santiagojr.auditoryoper`
  * Juan Pablo (Backend / Seguridad): `kaisen.ia.pablo.back` *(OJO: dominio 'ia')*
  * Duván (Comercial): `kaisen.ai.comercial`
  * Juan José (Jurídica): `kaisen.ai.juanjose.juridica`
  * Lucas (Operaciones): `lucasjaramillolol@gmail.com`

---

## 3. Servidor de Producción y Red

* **Hostname:** `desktop-8f1b898`
* **Dirección IP Tailscale:** `100.79.169.121`
* **Acceso SSH:** `ssh kaisenai@100.79.169.121`
* **Red Interna Docker:** `skynet_skynet_net`
* **Servicios de Datos:**
  * PostgreSQL interno: `skynet-postgres-1:5432`
  * Redis interno: `skynet-redis-1:6379`
  * Gateway IA local: `bolivar-ai-gateway` (puerto 8080/11434, modelo `qwen3:4b` vía Ollama cuando se configure el GPU toolkit).

---

## 4. Reglas Críticas de Seguridad y Operación (Guardrails)

1. **Protocolo de Confirmación Obligatoria (Escritura):**
   * Antes de ejecutar cualquier mutación (crear/modificar tickets en YouTrack, registrar filas en Notion, modificar eventos de Calendar o enviar correos/mensajes masivos), Jericó debe presentar el resumen exacto al usuario y esperar su aprobación explícita.
2. **Aislamiento de Clientes:**
   * Las bases de datos de clientes (`segurosbolivar-db`, `mundodeoro-db`) están estrictamente aisladas del backend del asistente.
3. **Manejo de Secretos:**
   * Nunca almacenar credenciales en texto claro en repositorios. Consumir variables de entorno inyectadas mediante Docker o `.env` protegido.
