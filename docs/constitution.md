# Constitución — Proyecto Jericó
Principios innegociables, derivados de AGENTS.md, DECISIONES_CTO.md y MEMORY.md. Prevalecen sobre cualquier spec, plan o tarea. **RATIFICADA** por delegación del CTO el 04/10/2026, con la enmienda del punto 4.

1. **Simplicidad y cintura estrecha:** la pieza mínima que cumpla la spec; prohibidos LangChain/LlamaIndex y frameworks monolíticos; ningún componente de infraestructura antes de que una fase lo exija.
2. **Primacía de la spec:** ningún código sin requisito EARS aprobado; la spec se actualiza antes que el código y sigue viva (spec-anchored).
3. **Tests primero y herméticos:** TDD; red, LLM y servicios externos siempre simulados; `./scripts/verify.sh` en verde con cobertura ≥ 89 % antes de cada commit.
4. **Integridad de datos:** rige D1: PostgreSQL 16 en producción y SQLite WAL solo para tests y desarrollo local. Excepción temporal y acotada (enmienda del 04/10/2026): el CRM de ventas (spec 001) usa SQLite WAL en producción, con SQL portable a PostgreSQL 16, hasta que el CTO disponga su migración; el resto del núcleo sigue bajo D1. Respaldos cifrados fuera de la máquina (D2).
5. **Modelos pineados:** identificadores exactos, sin alias flotantes (`-latest`, `-preview`); prompts de sistema inmutables y trazables por hash SHA-256.
6. **Secretos fuera del código:** solo variables de entorno; nunca en repositorio, registros ni mensajes.
7. **Humano en el bucle (D5):** las acciones de alto riesgo exigen aprobación explícita del CTO por Telegram con identidad verificada, con la CLI como respaldo; sin respuesta en 10 minutos, se rechazan.
8. **Ejecución aislada:** herramientas en subproceso con timeout y entorno saneado; prohibido exponer el socket de Docker (D3).
9. **Idioma:** español en documentación, specs, commits y minutas; inglés en código e identificadores.
10. **Git:** prohibido `git push`; no tocar archivos sin trackear ajenos; commits solo con autorización del CTO.

> Última modificación: 04/10/2026 17:30 (Planificador SDD)
