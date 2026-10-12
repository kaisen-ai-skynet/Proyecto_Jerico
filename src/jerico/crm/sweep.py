"""Barrido único de seguimiento de la fase 2 (F2-T25; plan-f2 D-1, D-2 y D-9).

Un solo job (`crm-followup`, cada minuto) en vez de uno por paso: así no hay ejecuciones
concurrentes de pasos que dependen entre sí. En orden: activación de F2 (una sola vez), consulta
del buzón, expiración de propuestas, generación de las vencidas y entrega de los envíos
programados. Cada paso está aislado (el fallo de uno no frena a los demás) y es idempotente por las
restricciones de la base, no por memoria.

Sin buzón de entrada, correo de salida, aviso de privacidad o textos configurados F2 no hace nada
y avisa al CTO una sola vez (D-9): no se puede honrar una baja si no se puede leer el buzón.
"""

import hashlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from loguru import logger

from jerico.crm import compliance, config, delivery, followup, followup_text, gate, replies, repo
from jerico.crm.config import CrmSettings, Params
from jerico.crm.db import CrmDatabase
from jerico.crm.model import LeadState, Outgoing, Role
from jerico.crm.ports import EmailSender, InboxPort, InlineButton, TelegramPort
from jerico.crm.timeutil import to_iso

NOTICE_KIND = "followup_notice"
ACTIVATED_KEY = "f2_activated_at"


@dataclass(frozen=True)
class SweepContext:
    db: CrmDatabase
    telegram: TelegramPort
    email: EmailSender
    inbox: InboxPort
    settings: CrmSettings
    params: Params
    keys: tuple[str, ...]


async def _guard(name: str, step: Callable[[], Awaitable[list[Outgoing]]]) -> list[Outgoing]:
    """Aísla un paso: si falla solo se registra el tipo de error (nunca su texto) y se sigue."""
    try:
        return await step()
    except Exception as exc:  # noqa: BLE001 - un paso roto no puede frenar a los demás (VCRM-170)
        logger.error("crm followup step {} failed: {}", name, type(exc).__name__)
        return []


def _unsub_address(settings: CrmSettings) -> str:
    """Buzón al que llegan las bajas por la cabecera `List-Unsubscribe`: el que se sondea."""
    return settings.imap_username or settings.smtp_from or ""


def _disabled_notice(ctx: SweepContext, now: datetime, missing: Sequence[str]) -> list[Outgoing]:
    """Aviso al CTO, una vez por conjunto de faltantes (D-9)."""
    digest = hashlib.sha256(",".join(sorted(missing)).encode()).hexdigest()[:12]
    key = f"f2_notice:disabled:{digest}"
    with ctx.db.tx() as tx:
        if repo.get_meta(tx, key) is not None:
            return []
        repo.set_meta(tx, key, to_iso(now))
        text = (
            "La fase 2 del CRM está deshabilitada: falta configurar "
            + ", ".join(sorted(missing))
            + ". Mientras tanto no se leen respuestas ni se generan o envían mensajes al cliente."
        )
        return [Outgoing(cto.telegram_id, text) for cto in repo.active_users(tx, Role.CTO)]


def _activate(ctx: SweepContext, now: datetime) -> list[Outgoing]:
    """Activación única (VCRM-160): los rechazados con autorización vigente entran en cadencia."""
    with ctx.db.tx() as tx:
        if repo.get_meta(tx, ACTIVATED_KEY) is not None:
            return []
        repo.set_meta(tx, ACTIVATED_KEY, to_iso(now))  # antes del bucle: start_cadence lo exige
        out: list[Outgoing] = []
        for lead in repo.all_leads(tx):
            if lead.state == LeadState.REJECTED and compliance.may_contact_commercially(
                tx, lead, ctx.keys
            ):
                out += followup.start_cadence(tx, lead, now, ctx.keys)
        return out


def _expire(ctx: SweepContext, now: datetime) -> list[Outgoing]:
    with ctx.db.tx() as tx:
        return gate.expire_due(tx, now, on_step_consumed=followup.on_step_consumed)


def _generate(ctx: SweepContext, now: datetime) -> list[Outgoing]:
    texts = followup_text.load_followup_texts(config.cadence_path(ctx.settings))
    with ctx.db.tx() as tx:
        return followup.generate_due(tx, now, ctx.keys, texts, ctx.settings.sender_name)


async def _deliver(ctx: SweepContext, now: datetime) -> list[Outgoing]:
    return await delivery.deliver_due(
        ctx.db,
        ctx.email,
        now,
        ctx.params,
        ctx.keys,
        unsub_address=_unsub_address(ctx.settings),
        on_step_consumed=followup.on_step_consumed,
    )


def _buttons(item: Outgoing) -> list[list[InlineButton]] | None:
    rows = [[InlineButton(text, data) for text, data in row] for row in item.buttons]
    return rows or None


async def _send(ctx: SweepContext, out: list[Outgoing], now: datetime) -> None:
    """Avisos tras confirmar las transacciones; si no constan entregados, fila fallida sin texto."""
    for item in out:
        result = await ctx.telegram.send_message(item.chat_id, item.text, _buttons(item))
        if result.delivered:
            continue
        with ctx.db.tx() as tx:
            recipient = repo.active_user_by_telegram(tx, item.chat_id)
            if recipient is not None:
                repo.record_failed_noncritical(
                    tx,
                    recipient_user_id=recipient.id,
                    kind=NOTICE_KIND,
                    error=result.error,
                    now=now,
                )


async def followup_sweep(ctx: SweepContext, now: datetime) -> None:
    """Un barrido completo de F2; idempotente y seguro de repetir cada minuto."""
    missing = config.f2_missing(ctx.settings)
    if missing:
        await _send(ctx, _disabled_notice(ctx, now, missing), now)
        return
    out: list[Outgoing] = []
    out += await _guard("activate", _sync(lambda: _activate(ctx, now)))
    out += await _guard(
        "poll",
        lambda: replies.poll_and_process(ctx.db, ctx.inbox, now, ctx.params, ctx.keys),
    )
    out += await _guard("expire", _sync(lambda: _expire(ctx, now)))
    out += await _guard("generate", _sync(lambda: _generate(ctx, now)))
    out += await _guard("deliver", lambda: _deliver(ctx, now))
    await _send(ctx, out, now)


async def deliver_now(ctx: SweepContext, now: datetime) -> None:
    """Primer intento en línea tras un ✅ dentro de franja y cupo (plan-f2 D-3)."""
    if config.f2_missing(ctx.settings):
        return
    with ctx.db.read() as conn:
        if not followup.f2_active(conn):
            return
    await _send(ctx, await _guard("deliver", lambda: _deliver(ctx, now)), now)


def _sync(step: Callable[[], list[Outgoing]]) -> Callable[[], Awaitable[list[Outgoing]]]:
    async def run() -> list[Outgoing]:
        return step()

    return run


__all__ = ["ACTIVATED_KEY", "NOTICE_KIND", "SweepContext", "deliver_now", "followup_sweep"]
