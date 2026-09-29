---
titulo: "Informe HERDR — Revisión adversarial y endurecimiento (Claude)"
proyecto: Proyecto Jericó
autor: Claude Code (Opus 5.5), por encargo del CTO vía Hermes
revisor: Santiago Gonzalez (CTO)
creado: "29/09/2026 09:25"
modificado: "29/09/2026 09:25"
---

# INFORME HERDR (Claude): revisión adversarial y endurecimiento

**Base revisada:** `ee4f1da` (rama `main`, árbol limpio al empezar). Complementa, sin reemplazar, a `INFORME-HERDR-2026-09-29.md` (Antigravity).
**Alcance:** `src/jerico/` (api, router, config, llm_client, memory, tools) y `tests/`. No se tocaron el servidor, otros proyectos ni `~/Personal`. Sin push.

## 0. Resumen

| | Antes | Después |
|---|---|---|
| Tests | 31 pasan | **167 pasan** (31 originales intactos + 136 nuevos) |
| Hallazgos corregidos (§1) | — | 20 (1 alta, 9 media, 10 baja) |
| Pendientes para el CTO (§4) | — | 10 (1 alta, 3 media, 6 baja) |
| `ruff` | 4 errores (orden de imports; `verify.sh` fallaba en el paso 1) | limpio |
| `mypy` | limpio | limpio |
| Tests escribiendo en `logs/audit.log` real | sí (cada corrida) | no (`tests/conftest.py`) |

Cada hallazgo se reprodujo antes de corregirlo. Luego se corrieron los tests nuevos contra el código de `HEAD` para confirmar que detectan los bugs: **81 de los 136 tests nuevos fallan contra `HEAD`** (cada uno reproduce un hallazgo); los 55 restantes son guardas de regresión, y los 31 originales pasan en ambas versiones.

**Nota sobre el informe de Antigravity:** dice que `POST /api/v1/ask` "bloquea el event loop". No es así. El endpoint es `def` síncrono y FastAPI lo corre en un threadpool (40 hilos por defecto), no en el loop. El riesgo real era otro: estado compartido (`RateLimiter`, `MemoryManager`) sin locks, accedido desde varios hilos. Se reprodujo (`RuntimeError: dictionary changed size during iteration` y 51 de 50 requests permitidos) y quedó corregido (H-02, H-03). La migración a `AsyncOpenAI` pasa a ser una mejora y deja de ser un bloqueo.

## 1. Hallazgos corregidos

Severidad: **Alta** = seguridad o integridad explotable; **Media** = error 500, fuga de secreto por configuración, o fallo con uso normal; **Baja** = robustez, costo o higiene.

| ID | Sev. | Componente | Hallazgo (reproducido) | Corrección |
|---|---|---|---|---|
| H-01 | **Alta** | `tools/base.py` | `run(confirm="false")` **ejecutaba la escritura**. El chequeo era `not confirm` y cualquier string no vacío es truthy. Cuando los argumentos vengan de un LLM (tool-calling), esto rompe la regla "escrituras solo con confirm=True". | `confirm is not True` estricto. |
| H-02 | Media | `memory.py` | Sin lock. Bajo concurrencia, `_evict_if_needed`/`_purge` iteran `_seen` mientras otro hilo lo modifica: 7 `RuntimeError` en 8 hilos. En la API eso es un 500. | `threading.RLock` en todas las operaciones. |
| H-03 | Media | `api.py` `RateLimiter` | Carrera leer-filtrar-escribir: 51 de 50 permitidos con 16 hilos, y actualizaciones perdidas (subconteo). | `threading.Lock` en `allow`/`reset`. |
| H-04 | Media | `api.py` auth | `secrets.compare_digest` con `str` no-ASCII lanza `TypeError`. Un header `Authorization` con bytes latin-1 daba **500** en vez de 401, sin autenticación. | Comparación en bytes (`.encode()`). |
| H-05 | Media | router / api / llm | Un prompt vacío o de solo espacios pasaba como L0 con `answer=None`. La API **llamaba al LLM con `model="none"`** (error del proveedor, 500, request cobrado). | El router siempre responde en L0 (`EMPTY_ANSWER`), y `LLMClient.complete` rechaza `level <= 0`. |
| H-06 | Media | `config.py` | Con L3 sin modelo propio, el modelo caía a L2 pero el endpoint iba al gateway. Con L2 en proveedor directo (p. ej. DeepSeek), **todas las consultas legales/financieras** mandaban un ID de DeepSeek a OpenRouter y fallaban. | Si L3 cae a L2, usa también el endpoint de L2. |
| H-07 | Media | `config.py` | Override parcial por nivel: `LLM_BASE_URL_L2` sin `LLM_API_KEY_L2` **enviaba la key del gateway al proveedor directo** (y al revés). Fuga de credencial a un tercero por un error de `.env`. | `model_validator`: base y key de cada nivel van juntas o ninguna. Falla al arrancar. |
| H-08 | Media | `router.py` | Los plurales escapaban del nivel: "revisa los **contratos**", "temas **legales**" → L1 (modelo barato para temas de alto riesgo); "dos **bugs**" → L1. | Sufijo plural opcional `(?:s\|es)?`. |
| H-09 | Media | `router.py` | Las excepciones de L2 se aplicaban antes del escaneo de L3. Una excepción configurada que contenga una palabra L3 degradaba consultas de alto riesgo. | L3 escanea el texto original; las excepciones solo afectan a L2. |
| H-10 | Media | `llm_client.py` / `api.py` | Errores del proveedor (timeout, 429, conexión) y respuestas con `choices=[]` (frecuente en OpenRouter) daban `IndexError`/500 genérico. | `LLMError` tipado. La API responde **502 `llm_unavailable`**, registra el motivo en el log y no guarda el turno en memoria. |
| H-11 | Baja | `tools/base.py` | Audit log falsificable: `run(tool="youtrack_list_issues")` sobrescribía el campo `tool` (una escritura quedaba registrada como lectura). Igual con `ts`. | Los kwargs van anidados en `args`; `ts/tool/status/confirm` no se pueden pisar. **Cambia el formato del audit log** (ver §3). |
| H-12 | Baja | `tools/base.py` | Los intentos de escritura bloqueados no se auditaban. | Se registran con `status: "blocked"`. |
| H-13 | Baja | `tools/base.py` | Las tools del `REGISTRY` (singletons) eran mutables: `tool.readonly = True` en una tool de escritura saltaba la confirmación. | `ConfigDict(frozen=True)`. |
| H-14 | Baja | `llm_client.py` | El dedupe descartaba el prompt del usuario si coincidía con el *contenido* del último mensaje, aunque fuera del assistant. El LLM recibía un historial sin la pregunta. | Solo se omite si el último mensaje es del `user` con el mismo contenido. |
| H-15 | Baja | `memory.py` / `api.py` | 1) `append` user/assistant en dos pasos: dos requests concurrentes en la misma sesión intercalaban turnos. 2) `context()` creaba la sesión como efecto lateral, así que leer sesiones inexistentes podía expulsar sesiones reales. | `record_turn()` atómico (API y CLI). `context()` es de solo lectura y devuelve copia defensiva. |
| H-16 | Baja | `memory.py` | `JERICO_MEMORY_TTL_HOURS` y `JERICO_MEMORY_MAX_SESSIONS` estaban declaradas pero **no se usaban**: siempre regían 24 h / 100. | La instancia global se construye desde `get_settings()`. |
| H-17 | Baja | `api.py` | Sin límites de entrada: un prompt de varios MB iba al LLM (costo) y se guardaba en memoria (hasta 20 mensajes × 100 sesiones). `session_id` sin límite. | `prompt` ≤ 20 000 caracteres, `session_id` de 1 a 128 (422 si se excede). |
| H-18 | Baja | `api.py` / `llm_client.py` | Se creaba un `LLMClient` y un `OpenAI` por request: sin reutilizar conexiones, con clientes HTTP sin cerrar, y regex del router recompiladas cada vez. | `lru_cache` en `get_llm()` y `get_router()`. |
| H-19 | Baja | `api.py` | `/health` era síncrono y compartía el threadpool con `/ask` (hasta ~90 s por request: 30 s × 3 intentos). Con el pool saturado, el `HEALTHCHECK` de Docker (3 s) fallaba y reiniciaba el contenedor bajo carga. | `/health` es `async def`. |
| H-20 | Baja | router / config | 1) "Hola!", "gracias.", "¿Qué tal?" no eran L0 (iban al LLM). 2) `\b` nunca matchea tras keywords como `c++`/`c#`. 3) Alias flotantes `llama3:latest`, `x@latest` y `"m-latest "` (espacio) pasaban la validación. 4) `CHANGEME` en mayúsculas contaba como token válido. | Clave L0 sin puntuación; lookarounds `(?<!\w)…(?!\w)`; regex `[-:@](latest\|preview)$` con `strip`; `token_configured` ignora mayúsculas. |

Higiene extra: `tests/conftest.py` redirige `AUDIT_LOG` a `tmp_path` (antes cada `pytest` agregaba entradas falsas al audit log real), y orden de imports en `stt.py`, `test_api.py` y `test_router.py`, más el `type: ignore` de `stt.py` compactado para caber en 100 columnas. Con eso `scripts/verify.sh` vuelve a pasar completo.

## 2. Tests nuevos (archivos nuevos; los 4 originales intactos salvo el orden de imports)

| Archivo | Cubre |
|---|---|
| `tests/conftest.py` | Aislamiento del audit log (autouse). |
| `tests/test_hardening_api.py` | Auth (no-ASCII, variantes del token, placeholder), 401 no consume cupo, validación 422, prompts vacíos o de puntuación sin LLM, 502 sin ensuciar memoria, pares de turnos, aislamiento entre sesiones, rate limiter exacto bajo 16 hilos, ventana deslizante, cacheo de clientes. |
| `tests/test_hardening_config_router.py` | Endpoints por nivel y fallback L3→L2, overrides parciales, niveles fuera de rango, alias flotantes, plurales, excepciones que no degradan L3, saludos con puntuación, keywords con caracteres regex, prompt de 400 KB en menos de 2 s. |
| `tests/test_hardening_memory.py` | TTL (expira, se renueva, 0 = desactivado), tope de mensajes, LRU, `context` sin efectos laterales y con copia defensiva, wiring de config, concurrencia (evict/purge y turnos no intercalados). |
| `tests/test_hardening_llm_tools.py` | Dedupe, filtro de roles del historial, `choices` vacío, envoltura de errores de openai (timeout, conexión, 429), nivel 0 nunca llama, `confirm` estricto (6 valores truthy × 3 tools), inmutabilidad, audit no falsificable, bloqueos auditados, audit no escribible no rompe la tool. |

## 3. Cambios de comportamiento que el CTO debe conocer

1. **Arranque más estricto:** un `.env` con `JERICO_LLM_BASE_URL_Lx` sin su `JERICO_LLM_API_KEY_Lx` (o al revés) ahora **no arranca** (falla cerrado). Revisar el `.env` del VPS antes de desplegar.
2. **Formato del audit log:** antes `{"ts","tool","confirm", ...kwargs}`; ahora `{"ts","tool","status","confirm","args":{...}}`. Si n8n u otro proceso lee `logs/audit.log`, hay que ajustarlo.
3. **Nuevas respuestas de la API:** `422` para prompt > 20 000 caracteres o `session_id` inválido; `502 llm_unavailable` cuando falla el proveedor (antes era 500).
4. **Router:** los plurales ahora suben de nivel (más consultas a L2/L3, con algo más de costo y más calidad en temas de riesgo).

## 4. Pendiente / requiere decisión del CTO

| ID | Sev. | Tema | Recomendación |
|---|---|---|---|
| P-01 | **Alta** | `docker-compose.yml` publica `"8000:8000"` en todas las interfaces. **Docker salta UFW**, así que en el VPS la API queda expuesta a Internet aunque el firewall diga lo contrario. | Publicar en `127.0.0.1:8000:8000` o en la IP de Tailscale. Decidir según quién consume la API (¿n8n en el mismo host?). |
| P-02 | Media | Los intentos fallidos de autenticación **no tienen rate limit** (el limiter corre después de la auth), así que el token admite fuerza bruta sin freno. `token_configured` acepta tokens de 1 carácter. | Limitar los 401 por IP, y exigir ≥ 32 caracteres en `JERICO_API_TOKEN` al arrancar. No se aplicó: puede bloquear clientes legítimos detrás de un proxy o cambiar tokens en uso. |
| P-03 | Media | Un único token compartido, y el `session_id` lo elige el cliente: **cualquier poseedor del token puede usar el historial de cualquier sesión** (el LLM lo recibe como contexto). Hoy es aceptable porque hay un solo usuario, pero no para multiusuario o Telegram (`allowed_telegram_ids` existe y no se usa). | Tokens por identidad y `session_id` con namespace por identidad. |
| P-04 | Media | Estado en memoria del proceso: con más de 1 worker, el rate limit se multiplica y la memoria se fragmenta. | Mantener 1 worker en el MVP, o pasar a Redis (coincide con Antigravity §4.2). |
| P-05 | Baja | `/docs` y `/openapi.json` son públicos sin auth. | `docs_url=None` en producción. |
| P-06 | Baja | `.env.example` apunta a OpenRouter con IDs sin prefijo de vendor (`glm-5.3-flash`, `deepseek-flash`). OpenRouter exige `vendor/modelo`. | Verificar los IDs reales antes del despliegue. |
| P-07 | Baja | El router no cubre género ni sinónimos ("jurídica", "abogado", "pleito"). La clasificación por keywords tiene un techo. | Ampliar las keywords en `.env`, o usar un clasificador L1 barato como segunda opinión para L3. |
| P-08 | Baja | Audit log: ruta relativa al CWD; en Docker, el volumen `./logs` del host puede no ser escribible por el usuario `jerico` (solo produce un warning, y el audit se pierde en silencio). Los `args` podrían contener secretos. | Ruta absoluta configurable, `chown` del volumen y redacción de claves sensibles. |
| P-09 | Baja | Latencia máxima de ~90 s por request (`timeout 30 × (1 + 2 reintentos)`). | Bajar `JERICO_LLM_MAX_RETRIES` a 1 o usar un timeout total. La migración a `AsyncOpenAI` queda como mejora, no como bug. |
| P-10 | Baja | La CLI `jerico ask` usa memoria de proceso: `--session-id` no persiste entre invocaciones. | Documentarlo, o compartir el backend de memoria cuando exista Redis. |

## 5. Verificación

```
.venv/bin/ruff check src tests      → All checks passed!
.venv/bin/mypy src tests            → Success: no issues found in 26 source files
.venv/bin/python -m pytest -q       → 167 passed
```

Commit local con identidad `Santiago Gonzalez <kaisen.ai.santiago.cto@gmail.com>`, **sin push**.

---

> 🕒 **Última modificación:** 29/09/2026 09:25 (Agente Claude Code)
