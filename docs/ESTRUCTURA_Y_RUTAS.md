# Estructura y rutas canónicas — Proyecto Jericó (26/09/2026)

> Único índice válido. La spec canónica vive en `docs/spec/` del repo. `Boceto_jerico/` es hub de coordinación (sin spec duplicada). La nota viva está en Obsidian.

## Estructura actual `Proyecto_Jerico/`

```
Proyecto_Jerico/
├── .github/muse-instructions.md       # reglas Copilot (L0-L3, jerico_net, no duplicar)
├── .github/prompts/generar-readme.prompt.md
├── .pi/                               # config local agente Pi (gitignore)
├── .env.example                       # plantilla con gateway compartido + overrides por nivel
├── .gitignore
├── pyproject.toml                     # v0.2.0, Python >=3.12
├── Dockerfile
├── docker-compose.yml                 # red jerico_net (skynet comentada)
├── src/jerico/
│   ├── config.py                      # Settings + endpoint_for(level) + token_configured()
│   ├── llm_client.py                  # cliente por nivel, timeout, reintentos, history
│   ├── router.py                      # L0 directo / L1 operativo / L2 código / L3 legal-finanzas
│   ├── textutil.py                    # normalize() NFD + strip diacríticos
│   ├── memory.py                      # sesiones con TTL 24h y max_sessions=100
│   ├── api.py                         # FastAPI def ask (threadpool) + rate limiter + secrets.compare_digest
│   ├── main.py                        # Typer CLI: serve (fail-fast token) + ask --verbose
│   ├── __main__.py
│   ├── tools/{__init__,base,youtrack,notion,docker}.py
│   └── voice/{__init__,stt,tts}.py
├── tests/
│   ├── test_router.py                 # 11 tests (tildes, falsos positivos, L3, alias prohibidos)
│   ├── test_api.py                    # 7 tests (auth, historial, rate limit, bind)
│   ├── test_tools_readonly.py         # 11 tests (registry, readonly, confirm, audit)
│   └── test_memory.py                 # 2 tests (evicción, contexto)
├── voices/                            # gitignore salvo consent.txt
├── docs/
│   ├── ESTRUCTURA_Y_RUTAS.md          # este archivo
│   ├── ARQUITECTURA.md                # puntero → docs/spec/ARQUITECTURA.md
│   ├── ESPECIFICACIONES_TECNICAS.md   # puntero → docs/spec/ESPECIFICACIONES_TECNICAS.md
│   ├── bocetos/README.md              # puntero → docs/spec/
│   └── spec/                          # SPEC CANÓNICA (7 archivos, migrada del boceto 23/09)
│       ├── ORGANIZACION_IDEAS_Y_VISION.md
│       ├── ANALISIS_CRITICO_JARVIS_VS_JERICO.md
│       ├── EL_COMO_ARQUITECTURA_Y_PLAN.md     (banner v2)
│       ├── ARQUITECTURA.md                    (banner v2)
│       ├── ESPECIFICACIONES_TECNICAS.md       (UUIDs Notion, YouTrack, RBAC — ÚNICA fuente)
│       ├── MAPA_RUTAS_INVENTARIO.md
│       └── PLAN_CONEXION_VPS_ORACLE_EQUIPO.md
├── scripts/oci/01_bootstrap.sh    # Fase 0 (canónico único)
└── README.md
```

## Dónde está cada cosa (no duplicar)

| Qué | Ruta canónica |
| :--- | :--- |
| Visión 9 pilares | `docs/spec/ORGANIZACION_IDEAS_Y_VISION.md` |
| Auditoría Jarvis vs Jericó | `docs/spec/ANALISIS_CRITICO_JARVIS_VS_JERICO.md` |
| Stack + plan 5 fases + Fase 0 Oracle | `docs/spec/EL_COMO_ARQUITECTURA_Y_PLAN.md` |
| Arquitectura + router L0-L3 + voz | `docs/spec/ARQUITECTURA.md` |
| Notion DBs + YouTrack + guardrails | `docs/spec/ESPECIFICACIONES_TECNICAS.md` |
| Plan conexión VPS Oracle equipo | `docs/spec/PLAN_CONEXION_VPS_ORACLE_EQUIPO.md` |
| Inventario rutas Jarvis/Jerico | `docs/spec/MAPA_RUTAS_INVENTARIO.md` |
| Script bootstrap VPS Oracle | `scripts/oci/01_bootstrap.sh` |
| Nota viva ejecutiva | `~/Kaisen_AI/02_Obsidian_Kaisen/01_Proyectos/Proyecto_Jerico.md` |
| Reglas Copilot | `.github/muse-instructions.md` |
| Prompt generar README | `.github/prompts/generar-readme.prompt.md` |
| Hub de coordinación multi-agente | `~/Kaisen_AI/01_Proyectos/Boceto_jerico/` |

`docs/ARQUITECTURA.md` y `docs/ESPECIFICACIONES_TECNICAS.md` son punteros, no copias.

---
> 🕒 **Última modificación:** 11/10/2026 18:25 (Claude Code · Opus 5.5)
