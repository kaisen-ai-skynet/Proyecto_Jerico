# Tareas — Asistente comercial con LLM (TDD: rojo → verde en cada una)
| # | Tarea | Req. | Quién |
|---|---|---|---|
| A01 | Config: campos, alias `OPENAI_*`, validación de topes, prueba de arranque con extras/vacíos | A20,A22-24,A30,A35 | director |
| A02 | `pseudonym.py` (marcadores, patrones, reposición) | A10-A13 | director |
| A03 | `llm.py` cliente Responses API con `httpx.MockTransport` | A14,A32,A34 | director |
| A04 | `assistant_budget.py` | A21-A23,A33 | Gemini (contrato) |
| A05 | `AuditAction.LLM_CALL` + `bot.defer` | A36 | director |
| A06 | `assistant.py`: contexto, prompts y casos de uso | A01-A06,A11,A12 | director + Gemini (tests) |
| A07 | Cableado `app.py` + aviso de llave faltante | A30,A31 | director |
| A08 | Aceptación E2E con LLM falso y verificación de no-fuga de datos personales | todos | Gemini (contrato) |
| A09 | Documentación (privacidad, costos, despliegue) e informe | A15,A16,A24 | director |
