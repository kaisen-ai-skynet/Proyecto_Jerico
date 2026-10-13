"""Asistente comercial con LLM dentro del bot (spec-asistente.md; VCRM-A01..A36).

Solo consultivo: resume, redacta borradores para el comercial y responde dudas del pipeline.
Nunca envía al cliente ni crea propuestas (A01): lo que salga al cliente sigue el gate ✅/❌.
Los datos personales se sustituyen por marcadores antes de salir (A10..A12) y se reponen solo en
la respuesta local (A13). La llamada de red corre tras el *commit* del manejador (A36)."""

import re
import sqlite3
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from loguru import logger

from jerico.crm import leads, permissions, repo
from jerico.crm.assistant_budget import AssistantBudget
from jerico.crm.bot import CrmBot, deny
from jerico.crm.config import CrmSettings
from jerico.crm.db import CrmDatabase
from jerico.crm.llm import LlmError, LlmPort
from jerico.crm.model import (
    AuditAction,
    AuditOutcome,
    EventKind,
    Lead,
    Outgoing,
    Role,
    User,
)
from jerico.crm.parsing import parse_short_id
from jerico.crm.pseudonym import Redactor
from jerico.crm.render import state_label
from jerico.crm.timeutil import from_iso

COMMAND = "asistente"
MIN_OUTPUT_TOKENS = 50
MAX_OUTPUT_TOKENS = 2000  # tope duro (A20)
MAX_CONTEXT_CHARS = 6000  # A20
MAX_USER_TEXT = 500
MAX_REPLY_CHARS = 3500  # holgura bajo el límite de Telegram
MAX_EVENTS = 10
MAX_NOTES = 5
MAX_NOTE_CHARS = 300

HELP = (
    "Asistente comercial (IA). Usos:\n"
    "• /asistente resumen L-0042 — resume el historial del lead.\n"
    "• /asistente borrador L-0042 [indicación] — borrador de correo de seguimiento para ti; "
    "no se envía.\n"
    "• /asistente pregunta <texto> — dudas sobre tu pipeline (solo cifras agregadas).\n"
    "Privacidad: no escribas nombres, teléfonos, correos ni documentos de personas en tu texto. "
    "El asistente solo recibe datos anonimizados. Revisa siempre la respuesta; lo que vaya al "
    "cliente pasa por la aprobación ✅/❌."
)
DISABLED = "El asistente no está activado."
UNAVAILABLE = "El asistente no está disponible en este momento. Inténtalo más tarde."
CAP_REASONS = {
    "daily_cap": "El asistente alcanzó su tope diario de uso. Inténtalo de nuevo mañana.",
    "user_cap": "Alcanzaste tu límite diario de consultas al asistente. Inténtalo de nuevo mañana.",
    "breaker": "El asistente está en pausa por fallos recientes. Inténtalo en unos minutos.",
}
NOT_FOUND = "No encontré ese lead entre los que puedes ver."
NOT_ALLOWED_LEAD = "El asistente no puede trabajar con ese lead."
WORKING = "Consultando al asistente…"
FOOTER = "— Generado por IA: revísalo antes de usarlo."
DRAFT_HEADER = "Borrador (no enviado)"

_SYSTEM_BASE = (
    "Eres el asistente comercial de Kaisen AI. Responde siempre en español, con tono "
    "profesional y cercano, sin inventar datos que no estén en el contexto. Los marcadores como "
    "[CLIENTE], [EMPRESA] o [NUM] sustituyen datos reales: consérvalos tal cual y no intentes "
    "adivinar a qué datos corresponden. No des asesoría legal ni prometas precios o plazos."
)
SYSTEM_PROMPTS = {
    "resumen": _SYSTEM_BASE
    + " Resume el historial del lead en máximo 120 palabras y termina con una línea "
    "«Próximo paso sugerido:».",
    "borrador": _SYSTEM_BASE
    + " Redacta un correo breve de seguimiento (máximo 150 palabras) con una línea «Asunto:» "
    "y el cuerpo. No incluyas firma, teléfonos ni enlaces: los agrega el comercial.",
    "pregunta": _SYSTEM_BASE
    + " Responde la duda sobre el pipeline usando solo las cifras del contexto, en máximo "
    "120 palabras.",
}


@dataclass
class AssistantContext:
    settings: CrmSettings
    db: CrmDatabase
    client: LlmPort | None
    budget: AssistantBudget
    clock: Callable[[], datetime]


def _days_ago(iso: str, now: datetime) -> int:
    return max((now - from_iso(iso)).days, 0)


def lead_context(
    conn: sqlite3.Connection,
    lead: Lead,
    red: Redactor,
    now: datetime,
    *,
    include_notes: bool,
) -> str:
    """Datos mínimos y ya seudonimizados del lead (A10, A11). Sin identificadores del CRM."""
    lines = [
        f"Estado: {state_label(lead.state)}",
        f"Registrado hace {_days_ago(lead.registered_at, now)} días; "
        f"última interacción hace {_days_ago(lead.last_interaction_at, now)} días.",
    ]
    for label, value in (
        ("Servicio", lead.service),
        ("Plazo de inicio", lead.start_term),
        ("Valor acordado", lead.agreed_value),
        ("Motivo de rechazo", leads.REJECT_REASONS.get(lead.reject_reason or "", None)),
    ):
        if value:
            lines.append(f"{label}: {red.scrub(value)}")
    cadence = repo.get_cadence(conn, lead.id)
    if cadence is not None:
        lines.append(
            f"Seguimiento: {cadence.status}, cada {cadence.interval_days} días, "
            f"paso {cadence.steps_done} de {cadence.total_steps}."
        )
    for event in repo.lead_events(conn, lead.id)[-MAX_EVENTS:]:
        when = f"hace {_days_ago(event.at, now)} días"
        if event.kind == EventKind.STATE and event.new_value:
            lines.append(f"- {when}: cambio a «{state_label(event.new_value)}»")
        elif event.kind == EventKind.FIELD and event.field:
            lines.append(f"- {when}: se actualizó el dato «{event.field}»")  # nunca el valor
        elif event.kind == EventKind.REASSIGN:
            lines.append(f"- {when}: reasignación de comercial")
        elif event.kind == EventKind.TITULAR_REQUEST:
            lines.append(f"- {when}: solicitud del titular")
    if include_notes:  # A11: apagado por defecto; si se activa, depuradas
        for note in repo.lead_notes(conn, lead.id)[-MAX_NOTES:]:
            lines.append(
                f"- nota hace {_days_ago(note.at, now)} días: "
                f"{red.scrub(note.body)[:MAX_NOTE_CHARS]}"
            )
    return "\n".join(lines)[:MAX_CONTEXT_CHARS]


def pipeline_context(conn: sqlite3.Connection, actor: User, now: datetime) -> str:
    """Solo cifras agregadas de los leads que el actor puede ver (A05): cero datos personales."""
    visible = leads.visible_leads(conn, actor)
    by_state = Counter(state_label(lead.state) for lead in visible)
    stale = sum(1 for lead in visible if _days_ago(lead.last_interaction_at, now) > 14)
    lines = [f"Leads visibles: {len(visible)}"]
    lines += [f"- {name}: {count}" for name, count in sorted(by_state.items())]
    lines.append(f"Sin interacción hace más de 14 días: {stale}")
    lines.append(
        f"Propuestas de seguimiento pendientes de aprobación: {_pending(conn, actor, now)}"
    )
    return "\n".join(lines)


def _pending(conn: sqlite3.Connection, actor: User, now: datetime) -> int:
    visible_ids = {lead.id for lead in leads.visible_leads(conn, actor)}
    return sum(1 for p in repo.pending_proposals(conn, now) if p.lead_id in visible_ids)


def _clamp_tokens(value: int) -> int:
    return max(MIN_OUTPUT_TOKENS, min(value, MAX_OUTPUT_TOKENS))


def _cto_notice(conn: sqlite3.Connection, ctx: AssistantContext, now: datetime) -> list[Outgoing]:
    """Un único aviso al CTO por día cuando se alcanza el tope (A22)."""
    if not ctx.budget.cap_notice_due(conn, now):
        return []
    ctos = repo.active_users(conn, role=Role.CTO)
    if not ctos:
        return []
    return [
        Outgoing(
            ctos[0].telegram_id,
            "El asistente comercial alcanzó su tope diario de uso y quedó pausado hasta mañana. "
            "Si necesitas más margen, ajusta JERICO_CRM_ASSISTANT_DAILY_TOKEN_CAP.",
        )
    ]


def _audit(
    conn: sqlite3.Connection, user: User, lead_id: int | None, outcome: AuditOutcome, now: datetime
) -> None:
    repo.audit(
        conn,
        actor=f"user:{user.id}",
        action=AuditAction.LLM_CALL,
        outcome=outcome,
        at=now,
        lead_id=lead_id,
    )


def _split(rest: str) -> tuple[str, str]:
    head, _, tail = rest.strip().partition(" ")
    return head.lower(), tail.strip()


def handle(
    ctx: AssistantContext, bot: CrmBot
) -> Callable[[sqlite3.Connection, User, str, datetime], list[Outgoing]]:
    def command(conn: sqlite3.Connection, user: User, text: str, now: datetime) -> list[Outgoing]:
        return _handle(ctx, bot, conn, user, text, now)

    return command


def _handle(
    ctx: AssistantContext,
    bot: CrmBot,
    conn: sqlite3.Connection,
    user: User,
    text: str,
    now: datetime,
) -> list[Outgoing]:
    chat = user.telegram_id
    if not ctx.settings.assistant_enabled:  # A30: sin tocar la red
        return [Outgoing(chat, DISABLED)]
    if user.role not in (Role.CTO, Role.COMMERCIAL):  # A04
        return deny(conn, user, now)
    rest = re.sub(r"^/\w+(?:@\w+)?", "", text).strip()
    sub, arg = _split(rest)
    if sub not in SYSTEM_PROMPTS:
        return [Outgoing(chat, HELP)]
    if ctx.client is None:  # A31: flag encendido sin llave
        return [Outgoing(chat, UNAVAILABLE)]

    lead: Lead | None = None
    instruction = arg
    if sub in ("resumen", "borrador"):
        ref, _, instruction = arg.partition(" ")
        lead_id = parse_short_id(ref)
        lead = None if lead_id is None else repo.get_lead(conn, lead_id)
        if lead is None or not permissions.is_visible(user, lead):  # A05
            return [Outgoing(chat, NOT_FOUND)]
        if lead.suppressed_at is not None or (sub == "borrador" and lead.commercial_block):  # A06
            return [Outgoing(chat, NOT_ALLOWED_LEAD)]
    elif not arg:
        return [Outgoing(chat, HELP)]

    decision = ctx.budget.check(conn, user.id, now)
    if not decision.allowed:
        reason = decision.reason or "daily_cap"
        extra = _cto_notice(conn, ctx, now) if reason == "daily_cap" else []
        return [Outgoing(chat, CAP_REASONS.get(reason, UNAVAILABLE)), *extra]

    red = Redactor.for_lead(lead) if lead is not None else Redactor(values=(), parts=())
    free = red.scrub(instruction.strip())[:MAX_USER_TEXT]  # A12
    if lead is not None:
        context = lead_context(
            conn, lead, red, now, include_notes=ctx.settings.assistant_include_notes
        )
    else:
        context = pipeline_context(conn, user, now)
    prompt = {
        "resumen": context,
        "borrador": f"{context}\n\nIndicación del comercial: {free}",
        "pregunta": f"{context}\n\nPregunta: {free}",
    }[sub][:MAX_CONTEXT_CHARS]
    lead_id_for_audit = None if lead is None else lead.id

    async def job() -> list[Outgoing]:
        return await _run(ctx, user, sub, prompt, red, lead_id_for_audit)

    bot.defer(job)
    return [Outgoing(chat, WORKING)]


async def _run(
    ctx: AssistantContext,
    user: User,
    sub: str,
    prompt: str,
    red: Redactor,
    lead_id: int | None,
) -> list[Outgoing]:
    chat = user.telegram_id
    client = ctx.client
    if client is None:  # el manejador ya lo descarta; defensa ante un cambio de cableado
        return [Outgoing(chat, UNAVAILABLE)]  # pragma: no cover
    try:
        result = await client.complete(
            system=SYSTEM_PROMPTS[sub],
            user=prompt,
            max_output_tokens=_clamp_tokens(ctx.settings.assistant_max_output_tokens),
        )
    except LlmError as exc:  # A32: degradación limpia; solo el código, jamás el cuerpo
        now = ctx.clock()
        logger.warning("asistente: llamada fallida ({})", exc.code)
        ctx.budget.record_failure(now)
        with ctx.db.tx() as tx:
            _audit(tx, user, lead_id, AuditOutcome.ERROR, now)
        return [Outgoing(chat, UNAVAILABLE)]
    now = ctx.clock()
    notice: list[Outgoing] = []
    with ctx.db.tx() as tx:
        outcome = ctx.budget.record(tx, user.id, now, result)
        _audit(tx, user, lead_id, AuditOutcome.OK, now)
        if outcome.cap_reached:
            notice = _cto_notice(tx, ctx, now)
    cost = "no calculado" if outcome.cost_usd is None else f"{outcome.cost_usd:.4f} USD"
    logger.info(  # A21: sin texto del prompt ni de la respuesta
        "asistente: caso={} usuario={} entrada={} salida={} costo={}",
        sub,
        user.id,
        result.input_tokens,
        result.output_tokens,
        cost,
    )
    body = red.restore(result.text)[:MAX_REPLY_CHARS]  # A13: reposición solo local
    if sub == "borrador":
        body = f"{DRAFT_HEADER}:\n\n{body}"
    return [Outgoing(chat, f"{body}\n\n{FOOTER}"), *notice]


def register_assistant(bot: CrmBot, ctx: AssistantContext) -> None:
    bot.register_command(COMMAND, handle(ctx, bot))


__all__ = ["AssistantContext", "lead_context", "pipeline_context", "register_assistant"]
