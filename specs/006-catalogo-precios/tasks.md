# Tareas 006 — Catálogo de precios (F6)

Delegables a Gemini: SÍ en C1–C4 (con tests primero); C5–C6 las revisa el director.

- [x] **C1** Test + `modelo.py`: rechaza precios negativos, planes duplicados, estado inválido, texto con nombres de persona (R1, R9).
- [x] **C2** Test + `repositorio.py`: resuelve `VIGENTE`; sin archivo → error «sin versión vigente»; versión vigente no se reescribe (R2, R3).
- [x] **C3** Test + `cotizar.py`: mensualidad = 10 % de la implementación; Decimal; plan inexistente → error con lista (R4, R5, R11).
- [x] **C4** Test + `vista.py`: `comercial` no contiene `costo_directo`, `margen`, honorarios, caja (R7, R8).
- [ ] **C5** Herramienta `consultar_catalogo` solo lectura + marca «BORRADOR — no cotizar» (R10, R12).
- [ ] **C6** `verificar_catalogo.py` contra el Excel y SHA-256 (R6); primera versión `0.1.0` en borrador con advertencias (R13).

Verificación: `./scripts/verify.sh` en verde, cobertura ≥ 80 %, sin red ni secretos.

> 🕒 **Última modificación:** 14/10/2026 07:53 (Gemini 3.8 Flash · kai-jev-gem)
