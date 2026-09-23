# Estructura y rutas canónicas — Proyecto Jericó (v2 23/09/2026)

> Único índice válido. La spec canónica vive en `docs/spec/` del repo (migrada desde `Boceto_jerico/` el 23/09/2026). `Boceto_jerico/` queda como puntero inverso.

## Estructura actual `Proyecto_Jerico/`

```
Proyecto_Jerico/
├── .github/muse-instructions.md       # reglas Copilot
├── .github/prompts/generar-readme.prompt.md  # prompt pegar-y-generar README
├── .pi/                               # config local agente Pi (gitignore)
├── .env.example
├── .gitignore
├── pyproject.toml
├── Dockerfile / docker-compose.yml    # Oracle ARM64, red skynet_skynet_net
├── src/jerico/                        # config, llm_client, router, memory, main, api,
│                                      # tools/{base,youtrack,notion,docker}, voice/{stt,tts}
├── tests/                             # test_router, test_tools_readonly
├── voices/                            # gitignore; solo consent.txt trackeado
├── docs/
│   ├── ESTRUCTURA_Y_RUTAS.md          # este archivo
│   ├── ARQUITECTURA.md                # puntero
│   ├── ESPECIFICACIONES_TECNICAS.md   # puntero
│   ├── bocetos/README.md              # puntero
│   └── spec/                          # ⬅️ SPEC CANÓNICA (migrada del boceto)
│       ├── ORGANIZACION_IDEAS_Y_VISION.md
│       ├── ANALISIS_CRITICO_JARVIS_VS_JERICO.md
│       ├── EL_COMO_ARQUITECTURA_Y_PLAN.md     (banner v2: menciones v1 deprecadas)
│       ├── ARQUITECTURA.md                    (banner v2)
│       ├── ESPECIFICACIONES_TECNICAS.md
│       ├── MAPA_RUTAS_INVENTARIO.md
│       └── PLAN_CONEXION_VPS_ORACLE_EQUIPO.md
├── scripts/bootstrap_vps_oracle.sh    # Fase 0 (canónico único; copia del boceto eliminada)
└── README.md
```

## Dónde está cada cosa (no duplicar)

| Qué | Ruta canónica |
| :--- | :--- |
| Visión 9 pilares | `docs/spec/ORGANIZACION_IDEAS_Y_VISION.md` |
| Auditoría + revalorización v2 | `docs/spec/ANALISIS_CRITICO_JARVIS_VS_JERICO.md` |
| Stack v2 + plan 5 fases + Fase 0 Oracle | `docs/spec/EL_COMO_ARQUITECTURA_Y_PLAN.md` |
| Arquitectura + router L0/L1/L2 + voz | `docs/spec/ARQUITECTURA.md` |
| Notion DBs + YouTrack + guardrails | `docs/spec/ESPECIFICACIONES_TECNICAS.md` |
| Plan conexión VPS Oracle equipo (Fase 0) | `docs/spec/PLAN_CONEXION_VPS_ORACLE_EQUIPO.md` |
| Inventario rutas Jarvis/Jerico/server | `docs/spec/MAPA_RUTAS_INVENTARIO.md` |
| Script bootstrap VPS Oracle | `scripts/bootstrap_vps_oracle.sh` |
| Nota viva ejecutiva | `~/Kaisen_AI/02_Obsidian_Kaisen/01_Proyectos/Proyecto_Jerico.md` |
| Reglas Copilot | `.github/muse-instructions.md` |
| Prompt generar README | `.github/prompts/generar-readme.prompt.md` |
| Boceto original (puntero inverso) | `~/Kaisen_AI/01_Proyectos/Boceto_jerico/README.md` |

`docs/ARQUITECTURA.md` y `docs/ESPECIFICACIONES_TECNICAS.md` son punteros a `docs/spec/`, no copias.
`docs/bocetos/` contiene solo `README.md` puntero.
