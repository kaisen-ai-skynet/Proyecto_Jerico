---
tipo: informe
proyecto: Jericó — Kaisen AI
frente: F1 infraestructura (plan maestro)
autor: infra-arquitecto (Claude Code · Opus 5.5)
creado: "13/10/2026 22:03"
modificado: "13/10/2026 22:25"
---

# Nube gratis para Jericó: OCI vs Google Cloud vs AWS (13/10/2026)

**Pregunta del CTO:** ¿hay una nube **gratis de verdad** que alcance para Jericó?
**Respuesta corta (ampliada en la ronda 2, con plan B de pago en §6):** solo **OCI Always Free** alcanza y es gratis de forma permanente. Hoy no hay capacidad en Bogotá, así que **seguimos en `kaisen-server`** y con el reintento A1 activo.
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
2. **OCI A1 sigue siendo la meta.** El reintento está **pausado por el CTO** desde el 13/10 a las 22:21 (tmux cerrado y `@reboot` comentado); se reactiva cuando él lo decida. Cuando consiga 1/6, se migra con `docs/migracion-oci.md` y después se amplía a 2/12 editando la shape.
   - **Antes de que acabe la prueba (~20/10):** comprueba que en la tenancy no haya nada de pago y que Object Storage no supere 20 GB.
   - **Riesgo de que Oracle reclame la VM por inactividad:** un CRM con poco tráfico puede quedar por debajo de los umbrales. Hay que vigilarlo con las métricas de la consola durante la primera semana.
3. **No usar AWS para producción.** No da VM gratis permanente, y la cuenta gratis se cierra a los 6 meses. Como mucho sirve para pruebas cortas.
4. **GCP solo como plan C para el CRM aislado** y únicamente con el OK del CTO, porque pide tarjeta. Sería un `e2-micro` en `us-central1` con el CRM y SQLite y backups a GCS (5 GB). El núcleo no cabe.
5. **Sin gasto en ningún caso:** cualquier opción de pago (OCI Pay-As-You-Go, AWS de pago, GCP más allá del cupo) necesita la aprobación explícita del CTO, con el costo documentado (regla «gratis primero» del plan maestro).

## 5. Cuota real de A1 Always Free: 2/12, no 4/24 (verificado el 13/10/2026)

La página oficial *Always Free Resources* dice: «the first **1,500 OCPU hours and 9,000 GB hours per month** … equivalent to **2 OCPUs and 12 GB of memory** for Always Free tenancies». Se puede usar todo en una instancia o en hasta dos de 1 OCPU. La página ya no menciona la cifra de 4/24 (3.000 OCPU-h y 18.000 GB-h) que se citaba antes **[el dato histórico no está en la fuente]**. Una VM de 4/24 en una cuenta Always Free excede el cupo (decisión D2, `DECISIONES_CTO.md`).

## 6. Plan B de pago, dentro del presupuesto de 10–25 USD/mes (nada contratado)

Es lo que pide el plan maestro (§6 y §7) si `kaisen-server` deja de servir antes de que OCI tenga capacidad.

| Opción | Arquitectura y recursos | Precio mensual (sin IVA) | IPv4 | Ubicaciones | Disponibilidad hoy |
|---|---|---|---|---|---|
| **Hetzner CX23** | x86 (Intel/AMD), 2 vCPU, 4 GB, 40 GB NVMe, 20 TB de tráfico | **5,49 €** (6,49 USD) sin IPv4. Antes valía 3,99 €; el cambio rige desde el 15/06/2026 | **Se cobra aparte:** 0,50 €/mes (0,60 USD). **Total ≈ 5,99 € (≈ 7,09 USD)**. IPv6 gratis | Nuremberg y Helsinki (la línea *cost-optimized* no está en EE. UU.) | La página la marcaba **«currently unavailable»** el 13/10 **[comprobar en la consola antes de decidir]** |
| **Hetzner CAX11** | **ARM** (Ampere), 2 vCPU, 4 GB, 40 GB NVMe, 20 TB | **5,99 €** (6,99 USD) sin IPv4. Antes valía 4,49 €; el cambio rige desde el 15/06/2026 | 0,50 € aparte. **Total ≈ 6,49 € (≈ 7,59 USD)** | Falkenstein, Nuremberg y Helsinki | También **«currently unavailable»** el 13/10 **[comprobar]** |
| **Cloudflare R2** (backups `age`) | Almacenamiento de objetos compatible con S3 | **Gratis hasta 10 GB-mes**, 1 M de operaciones clase A y 10 M de clase B. Después, 0,015 USD por GB-mes. **Egreso gratis** | n/a | Global | La página no dice si exige medio de pago para activarlo **[sin verificar; normalmente lo pide]** |

**Latencia medida** desde la laptop del CTO en Colombia, el 13/10/2026 a las 22:25, con `ping -c 5` por Wi-Fi doméstico (es orientativa):

| Destino | Latencia media |
|---|---|
| Hillsboro (EE. UU.) | 167 ms |
| Helsinki | 197 ms |
| Falkenstein | 203 ms |
| Nuremberg | 218 ms |
| Ashburn | 231 ms (con mucha variación) |

Para un bot de Telegram con *polling* ese retraso no se nota; para una interfaz web sí sería perceptible.

**Decisión consultada a Jev** (`jev_decidir.py`, `jev-1.13.0`, 13/10/2026 22:26):
- Plan B de servidor: **Hetzner CX23**. Es x86 como hoy, así que no hay que reconstruir la imagen, y es la opción más barata.
- Backups fuera de la máquina: **Cloudflare R2**.
- Cuándo pagar: **al crecer**, cuando haya comerciales activos y leads reales.

**Mi comentario como director F1:** coincido con Jev en lo del servidor y en lo de cuándo pagar.
- Para los backups hay una alternativa **sin tarjeta y ya creada**: el bucket de OCI (20 GB Always Free en la cuenta `kaisen_cloud`, que no necesita VM). Si R2 pide medio de pago, el bucket de OCI es mejor primer paso.
- El costo del plan B sería **≈ 7 USD/mes por el CX23**, más 0 USD de R2 mientras no pase de 10 GB. Así quedan unos 3–18 USD del tope para la voz y el LLM.
- Para contratarlo hace falta el OK explícito del CTO.

## 7. Fuentes (consultadas el 13/10/2026)

| Nube | Fuente oficial | Fecha de la página |
|---|---|---|
| OCI | [Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) | sin fecha (© 2026) |
| GCP | [Free cloud features](https://docs.cloud.google.com/free/docs/free-cloud-features) | actualizada el 13/10/2026 (UTC) |
| GCP | [General-purpose machines (e2-micro)](https://docs.cloud.google.com/compute/docs/general-purpose-machines) | según el buscador, actualizada hace unos 5 días |
| AWS | [AWS Free Tier](https://aws.amazon.com/free/) | sin fecha (© 2026) |
| AWS | [Explore AWS services with AWS Free Tier](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier.html) | sin fecha |
| AWS | [AWS Free Tier FAQs](https://aws.amazon.com/free/free-tier-faqs/) | sin fecha (menciona un registro nuevo en octubre de 2026) |
| AWS | [Free compute](https://aws.amazon.com/free/compute/), [Free databases](https://aws.amazon.com/free/database/), [Free Tier antes del 15/07/2025](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/billing-free-tier.html) | sin fecha |
| Hetzner | [Price Adjustment 15 June 2026](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/) | rige desde el 15/06/2026 |
| Hetzner | [IP pricing](https://docs.hetzner.com/general/infrastructure-and-availability/ipv4-pricing/) | última modificación 13/04/2023 (© 2026) |
| Hetzner | [Cost-Optimized (CX23, CAX11)](https://www.hetzner.com/cloud/cost-optimized/) | sin fecha; «currently unavailable» el 13/10/2026 |
| Cloudflare | [R2 pricing](https://developers.cloudflare.com/r2/pricing/) | actualizada el 01/10/2026 |
| Propias | `docs/dia-1-oci.md`, plan maestro (§1), `docker-compose.yml` | 13/10/2026 |

> Las páginas de AWS no coinciden del todo en qué ofertas tiene activas el plan gratis (unas hablan solo de «Always Free», otras de EC2 cubierto con créditos). La conclusión no cambia: con AWS no hay VM gratis para siempre.

---
> 🕒 **Última modificación:** 13/10/2026 22:25 (Claude Code · Opus 5.5)
