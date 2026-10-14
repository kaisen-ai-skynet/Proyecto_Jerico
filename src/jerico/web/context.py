from jerico.crm.assistant import AssistantContext

_context: AssistantContext | None = None


def set_web_context(ctx: AssistantContext) -> None:
    global _context
    _context = ctx


def get_web_context() -> AssistantContext:
    if _context is None:
        raise RuntimeError("Contexto web de Jericó no inicializado")
    return _context
