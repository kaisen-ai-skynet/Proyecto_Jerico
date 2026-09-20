# Estructura y rutas canónicas — Proyecto Jericó (v2 20/09/2026)

> Único índice válido. Todo lo duplicado en `docs/bocetos/*.md` fue eliminado. La spec vive en `Boceto_jerico/`.

## Estructura objetivo `Proyecto_Jerico/`

```
Proyecto_Jerico/
├── .github/muse-instructions.md       # reglas Copilot
├── .github/prompts/generar-readme.prompt.md  # prompt pegar-y-generar README
├── .env.example
├── pyproject.toml
├── Dockerfile / docker-compose.yml    # Oracle ARM64
├── src/jerico/{config,llm_client,router,memory,main,api,tools/base,youtrack,notion,docker,voice/stt,tts}.py
├── tests/{test_router,test_tools_readonly}.py
├── voices/                            # gitignore, samples + consent.txt
├── docs/ESTRUCTURA_Y_RUTAS.md         # este archivo
└── README.md
```

## Dónde está cada cosa (no duplicar)

| Qué | Ruta canónica |
| :--- | :--- |
| Visión 9 pilares | `~/Kaisen_AI/01_Proyectos/Boceto_jerico/ORGANIZACION_IDEAS_Y_VISION.md` |
| Auditoría + revalorización v2 | `~/Kaisen_AI/01_Proyectos/Boceto_jerico/ANALISIS_CRITICO_JARVIS_VS_JERICO.md` |
| Stack v2 + plan 5 fases + Fase 0 Oracle | `~/Kaisen_AI/01_Proyectos/Boceto_jerico/EL_COMO_ARQUITECTURA_Y_PLAN.md` |
| Arquitectura + router L0/L1/L2 + voz | `~/Kaisen_AI/01_Proyectos/Boceto_jerico/ARQUITECTURA.md` |
| Notion DBs + YouTrack + guardrails | `~/Kaisen_AI/01_Proyectos/Boceto_jerico/ESPECIFICACIONES_TECNICAS.md` |
| Plan conexión VPS Oracle equipo (Fase 0) | `~/Kaisen_AI/01_Proyectos/Boceto_jerico/PLAN_CONEXION_VPS_ORACLE_EQUIPO.md` |
| Inventario rutas Jarvis/Jerico/server | `~/Kaisen_AI/01_Proyectos/Boceto_jerico/MAPA_RUTAS_INVENTARIO.md` |
| Nota viva ejecutiva | `~/Kaisen_AI/02_Obsidian_Kaisen/01_Proyectos/Proyecto_Jerico.md` |
| Reglas Copilot | `Proyecto_Jerico/.github/muse-instructions.md` |
| Prompt generar README | `Proyecto_Jerico/.github/prompts/generar-readme.prompt.md` |

`docs/ARQUITECTURA.md` y `docs/ESPECIFICACIONES_TECNICAS.md` son punteros, no copias.
`docs/bocetos/` contiene solo `README.md` puntero.
