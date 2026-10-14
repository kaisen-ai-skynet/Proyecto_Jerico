"""Bot propio del abogado (@Jericoo_law_bot; spec 004 §8): mismo servicio, segundo bot.

Decidido con Jev: un solo proceso `jerico-crm` con dos clientes de Telegram y dos bucles de
polling sobre la misma `CrmDatabase` (un único escritor, un contenedor, un despliegue). Acceso:
solo los IDs de `JERICO_CRM_LEGAL_ALLOWED_IDS` **y** que además existan en la tabla de usuarios
con rol abogado (el CTO lo da de alta con `/alta`). Un desconocido que escribe `/start` solo
recibe su propio ID para pasárselo al CTO; todo lo demás es silencio y auditoría."""

import sqlite3
from collections.abc import Callable
from datetime import datetime

from jerico.crm.bot import CrmBot
from jerico.crm.closing_contract import (
    CONTRACT_FILE_KIND,
    download_command,
    file_handler,
    return_command,
    special_form_command,
    upload_command,
)
from jerico.crm.closing_flow import (
    ClosingContext,
    as_lawyer,
    as_lawyer_file,
    cases_command,
    legal_basis_command,
    package_command,
)
from jerico.crm.config import CrmSettings, parse_allowed_ids
from jerico.crm.db import CrmDatabase
from jerico.crm.files import LocalFileStore
from jerico.crm.model import Outgoing, Role, User
from jerico.crm.ports import TelegramPort

LEGAL_OFFSET_KEY = "legal_telegram_offset"
LEGAL_NAMESPACE = 1

HELP = (
    "Asistente legal de Kaisen AI. Comandos:\n"
    "• /casos — tus casos con paquete enviado y el estado del contrato.\n"
    "• /paquete L-0042 — leer el paquete de cierre.\n"
    "• /descargar L-0042 — recibir el paquete como archivo para editarlo.\n"
    "• /subircontrato L-0042 — subir el contrato final (PDF o DOCX); llega al comercial.\n"
    "• /devolver L-0042 motivo — devolver el paquete al comercial.\n"
    "• /formaespecial L-0042 — marcar que requiere firma certificada o presencial.\n"
    "• /basejuridica L-0042 — confirmar la base legal si el titular no autorizó.\n"
    "Tu ID de Telegram: {id}."
)


def start_command(
    conn: sqlite3.Connection, actor: User, text: str, now: datetime
) -> list[Outgoing]:
    return [Outgoing(actor.telegram_id, HELP.format(id=actor.telegram_id))]


def register_lawyer_commands(
    bot: CrmBot, db: CrmDatabase, ctx: ClosingContext, telegram: TelegramPort
) -> None:
    bot.register_command(
        "start",
        start_command,
        description="Iniciar y ver ID de Telegram",
        roles=(Role.LAWYER, Role.CTO),
    )
    bot.register_command(
        "casos",
        as_lawyer(ctx, cases_command),
        description="Listar casos con paquete enviado",
        roles=(Role.LAWYER, Role.CTO),
    )
    bot.register_command(
        "paquete",
        package_command,
        description="Consultar paquete de cierre",
        roles=(Role.LAWYER, Role.CTO),
    )
    bot.register_command(
        "descargar",
        download_command(ctx, bot, telegram),
        description="Descargar paquete como archivo",
        roles=(Role.LAWYER, Role.CTO),
    )
    bot.register_command(
        "basejuridica",
        as_lawyer(ctx, legal_basis_command),
        description="Confirmar base legal del contrato",
        roles=(Role.LAWYER, Role.CTO),
    )
    bot.register_command(
        "subircontrato",
        as_lawyer(ctx, upload_command),
        description="Subir contrato final (PDF o DOCX)",
        roles=(Role.LAWYER, Role.CTO),
    )
    bot.register_file_pending(CONTRACT_FILE_KIND, as_lawyer_file(ctx, file_handler(ctx, bot, db)))
    bot.register_command(
        "devolver",
        as_lawyer(ctx, return_command),
        description="Devolver paquete al comercial",
        roles=(Role.LAWYER, Role.CTO),
    )
    bot.register_command(
        "formaespecial",
        as_lawyer(ctx, special_form_command),
        description="Marcar forma especial requerida",
        roles=(Role.LAWYER, Role.CTO),
    )


def build_legal_bot(
    db: CrmDatabase,
    telegram: TelegramPort,
    clock: Callable[[], datetime],
    settings: CrmSettings,
    ctx: ClosingContext,
    files: LocalFileStore,
    *,
    kick: Callable[[], None] | None = None,
) -> CrmBot:
    allowed, _rejected = parse_allowed_ids(settings.legal_allowed_ids)
    bot = CrmBot(
        db,
        telegram,
        clock,
        kick=kick,
        files=files,
        offset_key=LEGAL_OFFSET_KEY,
        update_namespace=LEGAL_NAMESPACE,
        minimal=True,
        allowed_ids=allowed,
        anonymous_start=True,
    )
    register_lawyer_commands(bot, db, ctx, telegram)
    return bot
