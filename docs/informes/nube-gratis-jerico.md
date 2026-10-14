---
tipo: informe
proyecto: Jericó — Kaisen AI
frente: F1 infraestructura (plan maestro)
autor: infra-arquitecto (Claude Code · Opus 5.5)
creado: "13/10/2026 22:03"
modificado: "13/10/2026 22:03"
---

# Nube gratis para Jericó: OCI vs Google Cloud vs AWS (13/10/2026)

**Pregunta del CTO:** ¿hay una nube **gratis de verdad** que alcance para Jericó?
**Respuesta corta:** solo **OCI Always Free** alcanza y es gratis de forma permanente. Hoy no hay capacidad en Bogotá, así que **seguimos en `kaisen-server`** y con el reintento A1 activo.
- **Google Cloud** regala para siempre una sola `e2-micro` (1 GB de RAM, en EE. UU.), pide tarjeta y no alcanza para el núcleo.
- **AWS**, con el modelo actual, **no tiene ninguna VM gratis para siempre**: da créditos durante 6 meses y después cierra la cuenta del plan gratis.

Las fuentes son oficiales y las consulté el 13/10/2026 entre las 21:58 y las 22:02 (hora de Bogotá); hay una tabla de fuentes al final. Lo que no confirmé en la fuente va marcado **[sin verificar]**.

## 1. Qué necesita Jericó

| Pieza | Recursos (medidos o configurados) | Estado |
|---|---|---|
| CRM `jerico-crm` 24/7 (bot de Telegram con *polling*, SQLite en WAL, asistente LLM) | `mem_limit: 512m`, `cpus: 0.5` (`docker-compose.yml`) | en producción en `kaisen-server` |
| Núcleo `jerico-core` (FastAPI) + Redis 7 | sin límite fijado; estimación de 0,5–1 GB **[sin verificar: falta medirlo]** | todavía no se despliega |
| Postgres 16 (decisión D2, co-locado en `127.0.0.1`) | estimación de 0,5–1 GB **[sin verificar]** | preparado (`docker-compose.prod.yml`), sin uso |
| Backups cifrados con age, fuera de la máquina | unos pocos GB | scripts listos (`infra/servidor-produccion`) |
| Arquitectura | x86_64 hoy. En ARM64 la imagen se reconstruye y SQLite se puede llevar tal cual (`specs/003-servidor-kaisen/research.md` §7) | — |

**Mínimo razonable para todo junto: unos 2–3 GB de RAM y 1 vCPU constante.** Solo el CRM cabe en 1 GB, pero con poco margen.

## 2. Comparativa

| | **OCI Always Free** | **Google Cloud Free Tier** | **AWS Free Tier (modelo actual)** |
|---|---|---|---|
| **VM gratis para siempre** | **Sí:** A1.Flex ARM con 2 OCPU / 12 GB en total (1.500 OCPU-h y 9.000 GB-h al mes), más 2 × E2.1.Micro x86 (1/8 OCPU, 1 GB) | **Sí, pero mínima:** 1 `e2-micro` (2 vCPU compartidas al 25 %, 1 GB) solo en `us-west1`, `us-central1` y `us-east1` | **No.** EC2 (t3/t4g.micro y small, entre otras) solo con créditos, durante 6 meses |
| **Disco** | 200 GB entre boot y block (en la región de origen), más 5 backups de volumen | 30 GB-mes de disco estándar | por créditos |
| **Almacenamiento de objetos (backups)** | 20 GB (al acabar la prueba), 50.000 peticiones/mes | 5 GB-mes, solo en regiones de EE. UU. | por créditos; S3 no figura en lo comprobado **[sin verificar]** |
| **Base de datos gestionada gratis** | 2 Autonomous DB (20 GB cada una), MySQL HeatWave (50 GB), NoSQL | Firestore (1 GiB); Cloud SQL **no** es gratis (prueba de 30 días) | DynamoDB: 25 GB, 25 WCU/RCU, para siempre |
| **Redis gestionado gratis** | no (se corre en la VM) | no (Memorystore no figura) | no figura **[sin verificar]** |
| **Tráfico de salida** | VM micro: 50 Mbps **[el límite de A1 no está en la página consultada]** | 1 GB/mes desde Norteamérica | por créditos |
| **¿Pide tarjeta?** | La cuenta `kaisen_cloud` se creó **sin tarjeta** (plan maestro §1) y está **en prueba hasta ~20/10/2026** | **Sí:** hace falta una cuenta de facturación con medio de pago | «No se exige medio de pago a la mayoría de clientes nuevos» (puede pedirlo para verificar identidad) |
| **Qué caduca** | La prueba (~20/10): lo que **no** sea Always Free se detiene y se borra. Si al final de la prueba hay más de 20 GB en Object Storage, **se borran todos los objetos** | Crédito de 300 USD en 90 días. El e2-micro sigue gratis después | El plan gratis **se cierra a los 6 meses** o al gastar los créditos (100 USD + hasta 100 más). Los datos se guardan 90 días y luego **se borran**, salvo que pases al plan de pago |
| **Región cercana** | **Bogotá (`sa-bogota-1`)**, que es la región de origen | Solo EE. UU. (unos 80–120 ms desde Colombia) **[latencia sin medir]** | Créditos válidos en varias regiones; no hay Bogotá **[sin verificar]** |
| **Riesgo propio** | **No hay capacidad A1 en Bogotá** (la consola falló con 2/12 y 1/6; el reintento va en curso). La E2.1.Micro no se ofrece en Bogotá (lo comprobó el director el 13/10). Oracle puede reclamar una VM que pase 7 días con el P95 de CPU por debajo del 20 % y la red y la memoria por debajo del 20 % (la memoria cuenta solo en A1) | 1 GB obliga a correr solo el CRM. Lo que se pase del cupo se cobra a la tarjeta | Pasado el sexto mes hay que pagar o perder la cuenta |

## 3. Qué es gratis para siempre, qué pide tarjeta y qué caduca

- **Gratis para siempre y suficiente para Jericó: solo OCI A1** (2/12). En una VM caben el CRM, el núcleo, Redis, Postgres y los backups, además de 20 GB de objetos para backups.
- **Gratis para siempre pero insuficiente:** el `e2-micro` de GCP (1 GB, en EE. UU.) y las E2.1.Micro de OCI (1 GB, que además no se ofrecen en Bogotá). Solo servirían para el CRM aislado.
- **Piden tarjeta:** GCP siempre. AWS, normalmente no. OCI no la pidió en nuestro caso: la cuenta se creó sin tarjeta.
- **Caducan:** los créditos de GCP (90 días), la cuenta gratis de AWS (6 meses) y la prueba de OCI (~20/10/2026). Lo Always Free de OCI no caduca.

## 4. Recomendación

1. **Seguir en `kaisen-server` como producción** (decisión vigente del CTO). Instalar ya los backups y la alerta de salud (runbook `docs/despliegue-servidor-kaisen.md` en `infra/servidor-produccion`, listo para aprobar). Es lo que reduce el riesgo hoy.
2. **OCI A1 sigue siendo la meta.** El reintento corre 24/7 en `kaisen-server` (tmux `oci-a1`). Cuando consiga 1/6, se migra con `docs/migracion-oci.md` y después se amplía a 2/12 editando la shape.
   - **Antes de que acabe la prueba (~20/10):** comprueba que en la tenancy no haya nada de pago y que Object Storage no supere 20 GB.
   - **Riesgo de que Oracle reclame la VM por inactividad:** un CRM con poco tráfico puede quedar por debajo de los umbrales. Hay que vigilarlo con las métricas de la consola durante la primera semana.
3. **No usar AWS para producción.** No da VM gratis permanente, y la cuenta gratis se cierra a los 6 meses. Como mucho sirve para pruebas cortas.
4. **GCP solo como plan C para el CRM aislado** y únicamente con el OK del CTO, porque pide tarjeta. Sería un `e2-micro` en `us-central1` con el CRM y SQLite y backups a GCS (5 GB). El núcleo no cabe.
5. **Sin gasto en ningún caso:** cualquier opción de pago (OCI Pay-As-You-Go, AWS de pago, GCP más allá del cupo) necesita la aprobación explícita del CTO, con el costo documentado (regla «gratis primero» del plan maestro).

## 5. Fuentes (consultadas el 13/10/2026)

| Nube | Fuente oficial | Fecha de la página |
|---|---|---|
| OCI | [Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) | sin fecha (© 2026) |
| GCP | [Free cloud features](https://docs.cloud.google.com/free/docs/free-cloud-features) | actualizada el 13/10/2026 (UTC) |
| GCP | [General-purpose machines (e2-micro)](https://docs.cloud.google.com/compute/docs/general-purpose-machines) | según el buscador, actualizada hace unos 5 días |
| AWS | [AWS Free Tier](https://aws.amazon.com/free/) | sin fecha (© 2026) |
| AWS | [Explore AWS services with AWS Free Tier](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier.html) | sin fecha |
| AWS | [AWS Free Tier FAQs](https://aws.amazon.com/free/free-tier-faqs/) | sin fecha (menciona un registro nuevo en octubre de 2026) |
| AWS | [Free compute](https://aws.amazon.com/free/compute/), [Free databases](https://aws.amazon.com/free/database/), [Free Tier antes del 15/07/2025](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/billing-free-tier.html) | sin fecha |
| Propias | `docs/dia-1-oci.md`, plan maestro (§1), `docker-compose.yml` | 13/10/2026 |

> Las páginas de AWS no coinciden del todo en qué ofertas tiene activas el plan gratis (unas hablan solo de «Always Free», otras de EC2 cubierto con créditos). La conclusión no cambia: con AWS no hay VM gratis para siempre.

---
> 🕒 **Última modificación:** 13/10/2026 22:03 (Claude Code · Opus 5.5)
