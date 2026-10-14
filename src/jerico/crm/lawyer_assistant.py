"""Asistente IA para el rol abogado en el bot legal (spec 004/005).

Requisitos:
(1) Resumen del paquete de un caso: /asistente resumen L-n
(2) Borrador de cláusula o contrato a partir del paquete: /asistente clausula L-n <instrucción>,
    rotulado «Borrador (no enviado)» y nunca enviado a nadie automáticamente.
(3) Pregunta libre: /asistente pregunta <texto>

Reutiliza el asistente existente (gpt-6-luna, seudonimización, topes, auditoría):
el abogado SOLO ve casos que le llegaron por el flujo F2 (paquete enviado), nunca otros leads.
Los datos personales se seudonimizan antes de enviar al LLM y se restauran localmente al responder.
"""

import re
import sqlite3
from collections.abc import Callable
from datetime import datetime

from loguru import logger

from jerico.crm import closing_repo as crepo
from jerico.crm import repo
from jerico.crm.assistant import (
    CAP_REASONS,
    DISABLED,
    FOOTER,
    MAX_OUTPUT_TOKENS,
    MAX_REPLY_CHARS,
    MAX_USER_TEXT,
    MIN_OUTPUT_TOKENS,
    UNAVAILABLE,
    WORKING,
    AssistantContext,
    _audit,
    _cto_notice,
)
from jerico.crm.bot import CrmBot, deny
from jerico.crm.closing_flow import rebuild_package, render_markdown
from jerico.crm.closing_model import PackageStatus
from jerico.crm.llm import LlmError
from jerico.crm.model import AuditOutcome, Lead, Outgoing, Role, User
from jerico.crm.parsing import parse_short_id
from jerico.crm.pseudonym import Redactor
from jerico.decision.config import load_settings
from jerico.decision.port import decidir

HELP = (
    "Asistente legal (IA). Usos:\n"
    "• /asistente resumen L-0042 — resume el paquete del contrato del caso.\n"
    "• /asistente clausula L-0042 [instrucción] — borrador de cláusula o contrato; no se envía.\n"
    "• /asistente pregunta <texto> — dudas sobre los casos asignados.\n"
    "Privacidad: el asistente solo recibe datos anonimizados. "
    "Lo generado es un borrador para tu revisión."
)
NOT_FOUND_CASE = "No encontré ese caso entre los que te han llegado."
DRAFT_HEADER = "Borrador (no enviado)"

SYSTEM_PROMPTS = {
    "resumen": (
        "Eres el asistente legal de Kaisen AI. Resume el paquete del contrato del caso "
        "en máximo 150 palabras, destacando partes, objeto, valor acordado, forma de pago "
        "y base legal. Los marcadores como [CLIENTE], [EMPRESA] sustituyen datos reales: "
        "consérvalos tal cual."
    ),
    "clausula": (
        "Eres el asistente legal de Kaisen AI. Redacta el borrador de la cláusula o contrato "
        "solicitado a partir del paquete del caso y la indicación del abogado. Usa redacción "
        "jurídica rigurosa conforme al derecho colombiano. Los marcadores como [CLIENTE], "
        "[EMPRESA] sustituyen datos reales: consérvalos tal cual."
    ),
    "pregunta": (
        "Eres el asistente legal de Kaisen AI. Responde la duda del abogado usando el contexto "
        "de los casos asignados en máximo 150 palabras. Los marcadores sustituyen datos reales: "
        "consérvalos tal cual."
    ),
}


def _clamp_tokens(value: int) -> int:
    return max(MIN_OUTPUT_TOKENS, min(value, MAX_OUTPUT_TOKENS))


def _split(rest: str) -> tuple[str, str]:
    head, _, tail = rest.strip().partition(" ")
    return head.lower(), tail.strip()


def lawyer_assistant_command(
    ctx: AssistantContext, bot: CrmBot
) -> Callable[[sqlite3.Connection, User, str, datetime], list[Outgoing]]:
    def command(conn: sqlite3.Connection, actor: User, text: str, now: datetime) -> list[Outgoing]:
        return _handle_lawyer_assistant(ctx, bot, conn, actor, text, now)

    return command


def _handle_lawyer_assistant(
    ctx: AssistantContext,
    bot: CrmBot,
    conn: sqlite3.Connection,
    user: User,
    text: str,
    now: datetime,
) -> list[Outgoing]:
    chat = user.telegram_id
    if not ctx.settings.assistant_enabled:
        return [Outgoing(chat, DISABLED)]
    if user.role not in (Role.LAWYER, Role.CTO):
        return deny(conn, user, now)

    rest = re.sub(r"^/\w+(?:@\w+)?", "", text).strip()
    sub, arg = _split(rest)
    if sub not in ("resumen", "clausula", "pregunta"):
        return [Outgoing(chat, HELP)]
    if ctx.client is None:
        return [Outgoing(chat, UNAVAILABLE)]

    lead: Lead | None = None
    prompt_user_content: str = ""
    red: Redactor = Redactor(values=(), parts=())

    if sub in ("resumen", "clausula"):
        ref, _, instruction = arg.partition(" ")
        lead_id = parse_short_id(ref)
        if lead_id is None:
            return [Outgoing(chat, NOT_FOUND_CASE)]
        lead = repo.get_lead(conn, lead_id)
        package = crepo.live_package(conn, lead_id) if lead is not None else None
        if (
            lead is None
            or package is None
            or package.status != PackageStatus.SENT
            or not lead.ever_accepted
        ):
            return [Outgoing(chat, NOT_FOUND_CASE)]

        built = rebuild_package(conn, lead, package, now)
        if built is None:
            return [Outgoing(chat, NOT_FOUND_CASE)]

        red = Redactor.for_lead(lead)
        package_md = render_markdown(built)
        scrubbed_package = red.scrub(package_md)

        if sub == "resumen":
            prompt_user_content = f"Paquete del caso:\n{scrubbed_package}"
        else:
            free_inst = red.scrub(instruction.strip())[:MAX_USER_TEXT]
            if not free_inst:
                return [Outgoing(chat, "Indica la instrucción para redactar la cláusula.")]
            prompt_user_content = (
                f"Paquete del caso:\n{scrubbed_package}\n\nInstrucción del abogado: {free_inst}"
            )
    else:  # pregunta
        query = arg.strip()
        if not query:
            return [Outgoing(chat, "Indica tu pregunta para el asistente legal.")]
        free_query = red.scrub(query)[:MAX_USER_TEXT]
        packages = crepo.packages_sent(conn)
        lines = [f"Total casos con paquete enviado: {len(packages)}"]
        for pkg in packages:
            c = crepo.contract_for_package(conn, pkg.id)
            c_status = c.status if c is not None else "sin contrato"
            lines.append(f"- Caso L-{pkg.lead_id:04d}: versión {pkg.version}, contrato: {c_status}")
        cases_ctx = "\n".join(lines)
        prompt_user_content = f"Contexto de casos:\n{cases_ctx}\n\nPregunta: {free_query}"

    decision = ctx.budget.check(conn, user.id, now)
    if not decision.allowed:
        reason = decision.reason or "daily_cap"
        extra = _cto_notice(conn, ctx, now) if reason == "daily_cap" else []
        return [Outgoing(chat, CAP_REASONS.get(reason, UNAVAILABLE)), *extra]

    lead_id_for_audit = None if lead is None else lead.id
    session_id = (
        f"crm:lawyer:{user.id}:lead:{lead_id_for_audit}"
        if lead_id_for_audit is not None
        else f"crm:lawyer:{user.id}:{sub}"
    )

    async def job() -> list[Outgoing]:
        return await _run_lawyer_assistant(
            ctx, user, sub, prompt_user_content, red, lead_id_for_audit, session_id=session_id
        )

    bot.defer(job)
    return [Outgoing(chat, WORKING)]


async def _run_lawyer_assistant(
    ctx: AssistantContext,
    user: User,
    sub: str,
    prompt: str,
    red: Redactor,
    lead_id: int | None,
    session_id: str | None = None,
) -> list[Outgoing]:
    chat = user.telegram_id
    client = ctx.client
    if client is None:
        return [Outgoing(chat, UNAVAILABLE)]

    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    system_prompt = SYSTEM_PROMPTS[sub]
    selected_model = ctx.settings.openai_model
    try:
        dec_settings = load_settings()
        dec = decidir(
            "modelo_asistente",
            state={"tipo_tarea": f"legal_{sub}", "longitud_contexto": "media"},
            tarea=f"legal_{sub}",
            settings=dec_settings,
            user_role=role_str,
        )
        if dec.option:
            selected_model = dec.option
    except Exception as exc:  # noqa: BLE001
        logger.debug("asistente legal: decidir fallback a modelo base ({})", exc)

    memory_ready = False
    if ctx.memory is not None and session_id is not None:
        try:
            ctx.memory.get_or_create_session(
                session_id=session_id,
                user_id=user.id,
                role=role_str,
                system_prompt=system_prompt,
                model=selected_model,
            )
            memory_ready = True
        except Exception as exc:
            logger.warning("asistente legal: memoria degradada ({})", exc)

    try:
        result = await client.complete(
            system=system_prompt,
            user=prompt,
            max_output_tokens=_clamp_tokens(ctx.settings.assistant_max_output_tokens),
        )
    except LlmError as exc:
        now = ctx.clock()
        logger.warning("asistente legal: llamada fallida ({})", exc.code)
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

    if memory_ready and ctx.memory is not None and session_id is not None:
        try:
            ctx.memory.record_turn(
                session_id=session_id,
                user_id=user.id,
                role=role_str,
                user_prompt=prompt,
                assistant_response=result.text,
                model=selected_model,
                prompt_tokens=result.input_tokens,
                completion_tokens=result.output_tokens,
            )
        except Exception as exc:
            logger.warning("asistente legal: record_turn degradado ({})", exc)

    body = red.restore(result.text)[:MAX_REPLY_CHARS]
    if sub == "clausula":
        body = f"{DRAFT_HEADER}:\n\n{body}"
    return [Outgoing(chat, f"{body}\n\n{FOOTER}"), *notice]
