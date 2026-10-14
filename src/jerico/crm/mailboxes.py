"""Correo por niveles (spec 004 §7): un buzón por comercial, el CTO ve todos, el abogado ninguno.

Los leads entran como *candidatos* por el buzón del comercial: nada se registra ni se responde sin
su ✅ (VCRM-M04). Las contraseñas viven solo en el entorno (`.env`); la base guarda únicamente el
nombre de la variable, y ese nombre debe seguir `JERICO_MAILBOX_*_PASSWORD` para que ningún alta
pueda apuntar a otro secreto (p. ej. el token de Telegram). No se replica el buzón (VCRM-M03)."""

import os
import re
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from loguru import logger
from pydantic import SecretStr

from jerico.crm import closing_repo as crepo
from jerico.crm import repo
from jerico.crm.bot import CrmBot, deny
from jerico.crm.closing_model import CandidateStatus, Mailbox, MailCandidate
from jerico.crm.config import CrmSettings
from jerico.crm.db import CrmDatabase
from jerico.crm.fingerprint import fingerprint
from jerico.crm.idempotency import claim, make_key
from jerico.crm.inbox import build_inbox
from jerico.crm.model import (
    AuditAction,
    AuditOutcome,
    Channel,
    LeadState,
    Outgoing,
    Role,
    User,
)
from jerico.crm.outbox import enqueue_critical
from jerico.crm.parsing import build_callback
from jerico.crm.permissions import Action, authorize
from jerico.crm.ports import InboxError, InboxPort
from jerico.crm.timeutil import from_iso, local_date

CAND_OK = "candok"
CAND_NO = "candno"
SECRET_ENV = re.compile(r"^JERICO_MAILBOX_[A-Z0-9_]+_PASSWORD$")
ADDRESS = re.compile(r"^[^@\s;]+@[^@\s;]+\.[^@\s;]+$")
AUTOMATED = re.compile(r"(no-?reply|mailer-daemon|postmaster|bounce|notifications?@)", re.I)
SUBJECT_MAX = 80
USAGE_ADD = "Uso: /buzon alta correo_del_usuario; buzon@dominio.co; JERICO_MAILBOX_NOMBRE_PASSWORD"
NO_CANDIDATES = "No hay correos nuevos de remitentes desconocidos."
GONE = "Ese correo ya no está pendiente."
MailboxInboxFactory = Callable[[Mailbox], InboxPort | None]


@dataclass
class MailContext:
    settings: CrmSettings
    keys: Sequence[str]
    clock: Callable[[], datetime]
    environ: Mapping[str, str] = field(default_factory=lambda: os.environ)
    inbox_factory: MailboxInboxFactory | None = None


def _audit(
    conn: sqlite3.Connection, actor: str, lead_id: int | None, outcome: AuditOutcome, now: datetime
) -> None:
    repo.audit(
        conn,
        actor=actor,
        action=AuditAction.MAILBOX_EVENT,
        outcome=outcome,
        at=now,
        lead_id=lead_id,
    )


def default_inbox(ctx: MailContext) -> MailboxInboxFactory:
    """Lector IMAP de solo lectura con las credenciales del propio buzón."""

    def factory(mailbox: Mailbox) -> InboxPort | None:
        secret = ctx.environ.get(mailbox.secret_env, "").strip()
        if not secret:
            return None
        scoped = ctx.settings.model_copy(
            update={"imap_username": mailbox.address, "imap_password": SecretStr(secret)}
        )
        return build_inbox(scoped)  # sin servidor IMAP configurado, leer lanza InboxError

    return factory


# --- Administración (CTO) y consulta -----------------------------------------------------------


def _mailbox_line(conn: sqlite3.Connection, mailbox: Mailbox) -> str:
    owner = repo.get_user(conn, mailbox.user_id)
    state = "activo" if mailbox.active else "inactivo"
    last = mailbox.last_ok_at or "sin lectura aún"
    return f"{mailbox.address} · {owner.email if owner else '?'} · {state} · última lectura: {last}"


def mailbox_command(
    conn: sqlite3.Connection, actor: User, text: str, now: datetime
) -> list[Outgoing]:
    chat = actor.telegram_id
    body = re.sub(r"^/\w+(?:@\w+)?", "", text.strip()).strip()
    if not body:  # cada usuario ve solo el suyo (VCRM-M02)
        mine = crepo.mailbox_for_user(conn, actor.id)
        if mine is None:
            return [Outgoing(chat, "No tienes un buzón configurado.")]
        return [Outgoing(chat, _mailbox_line(conn, mine))]
    if actor.role != Role.CTO or not authorize(actor, Action.MAILBOX_VIEW, None).allowed:
        return deny(conn, actor, now)
    verb, _, rest = body.partition(" ")
    parts = [p.strip() for p in rest.split(";")]
    users = {u.email.lower(): u for u in repo.active_users(conn)}
    if verb.lower() == "alta":
        if len(parts) != 3 or not all(parts):
            return [Outgoing(chat, USAGE_ADD)]
        email, address, secret_env = parts
        owner = users.get(email.lower())
        if owner is None or owner.role != Role.COMMERCIAL:
            return [Outgoing(chat, "Ese correo no es de un comercial activo.")]
        if not ADDRESS.match(address):
            return [Outgoing(chat, "La dirección del buzón no es válida.")]
        if not SECRET_ENV.match(secret_env):
            return [Outgoing(chat, "El nombre de la variable debe ser JERICO_MAILBOX_*_PASSWORD.")]
        crepo.upsert_mailbox(conn, user_id=owner.id, address=address, secret_env=secret_env)
        _audit(conn, f"user:{actor.id}", None, AuditOutcome.OK, now)
        return [
            Outgoing(
                chat, f"Buzón {address} asignado a {owner.email}. Pon la contraseña en el .env."
            )
        ]
    if verb.lower() == "baja":
        owner = users.get(parts[0].lower())
        mailbox = None if owner is None else crepo.mailbox_for_user(conn, owner.id)
        if mailbox is None:
            return [Outgoing(chat, "Ese usuario no tiene buzón.")]
        crepo.set_mailbox_active(conn, mailbox.id, False)
        _audit(conn, f"user:{actor.id}", None, AuditOutcome.OK, now)
        return [Outgoing(chat, f"Buzón {mailbox.address} desactivado.")]
    return [Outgoing(chat, USAGE_ADD)]


def mailboxes_command(
    conn: sqlite3.Connection, actor: User, text: str, now: datetime
) -> list[Outgoing]:
    if actor.role != Role.CTO:  # el CTO ve todos los buzones (VCRM-M02)
        return deny(conn, actor, now)
    lines = [_mailbox_line(conn, m) for m in crepo.all_mailboxes(conn)]
    return [Outgoing(actor.telegram_id, "\n".join(lines) if lines else "No hay buzones.")]


# --- Candidatos de lead -----------------------------------------------------------------------


def _visible_mailbox_ids(conn: sqlite3.Connection, actor: User) -> list[int]:
    if actor.role == Role.CTO:
        return [m.id for m in crepo.all_mailboxes(conn)]
    if actor.role == Role.COMMERCIAL:
        mine = crepo.mailbox_for_user(conn, actor.id)
        return [] if mine is None else [mine.id]
    return []


def _can_see(conn: sqlite3.Connection, actor: User, candidate: MailCandidate) -> bool:
    return candidate.mailbox_id in _visible_mailbox_ids(conn, actor)


def candidates_command(
    conn: sqlite3.Connection, actor: User, text: str, now: datetime
) -> list[Outgoing]:
    chat = actor.telegram_id
    pending = crepo.pending_candidates(conn, _visible_mailbox_ids(conn, actor))
    if not pending:
        return [Outgoing(chat, NO_CANDIDATES)]
    return [
        Outgoing(
            chat,
            f"De: {c.sender_email}\nAsunto: {c.subject or '(sin asunto)'}\n"
            "¿Registrarlo como lead? Si lo registras, aún no se le escribe nada.",
            (
                (
                    ("✅ Registrar como lead", build_callback(CAND_OK, str(c.id))),
                    ("❌ Descartar", build_callback(CAND_NO, str(c.id))),
                ),
            ),
        )
        for c in pending
    ]


def _candidate(
    conn: sqlite3.Connection, actor: User, args: tuple[str, ...]
) -> MailCandidate | None:
    if len(args) != 1 or not args[0].isdigit():
        return None
    candidate = crepo.get_candidate(conn, int(args[0]))
    if candidate is None or candidate.status != CandidateStatus.PENDING:
        return None
    return candidate if _can_see(conn, actor, candidate) else None


def discard_callback(
    conn: sqlite3.Connection, actor: User, args: tuple[str, ...], now: datetime
) -> list[Outgoing]:
    candidate = _candidate(conn, actor, args)
    if candidate is None:
        return [Outgoing(actor.telegram_id, GONE)]
    crepo.set_candidate_status(conn, candidate.id, CandidateStatus.DISCARDED)
    _audit(conn, f"user:{actor.id}", None, AuditOutcome.OK, now)
    return [Outgoing(actor.telegram_id, "Correo descartado.")]


def register_callback(ctx: MailContext) -> Callable[..., list[Outgoing]]:
    def handler(
        conn: sqlite3.Connection, actor: User, args: tuple[str, ...], now: datetime
    ) -> list[Outgoing]:
        chat = actor.telegram_id
        candidate = _candidate(conn, actor, args)
        if candidate is None:
            return [Outgoing(chat, GONE)]
        mailbox = crepo.get_mailbox(conn, candidate.mailbox_id)
        owner_id = mailbox.user_id if mailbox is not None else actor.id
        email = candidate.sender_email
        if repo.any_suppressed(conn, [fingerprint(k, email) for k in ctx.keys]):
            crepo.set_candidate_status(conn, candidate.id, CandidateStatus.DISCARDED)
            return [Outgoing(chat, "Esa persona pidió no ser contactada. No se registró.")]
        if repo.leads_by_email(conn, email):
            crepo.set_candidate_status(conn, candidate.id, CandidateStatus.DISCARDED)
            return [Outgoing(chat, "Ya existe un lead con ese correo. Revísalo con /lista.")]
        if not claim(conn, make_key("lead_from_mail", candidate.id), now):
            return [Outgoing(chat, GONE)]
        lead_id = repo.insert_lead(
            conn,
            assigned_user_id=owner_id,
            state=LeadState.NEW,
            now=now,
            fields={"email": email},
        )
        crepo.set_candidate_status(conn, candidate.id, CandidateStatus.REGISTERED, lead_id=lead_id)
        repo.audit(
            conn,
            actor=f"user:{actor.id}",
            action=AuditAction.LEAD_CREATED,
            outcome=AuditOutcome.OK,
            at=now,
            lead_id=lead_id,
        )
        label = f"L-{lead_id:04d}"
        return [
            Outgoing(
                chat,
                f"Lead {label} registrado desde el correo. Antes de escribirle, completa sus datos "
                f"con /editar y pide su autorización con /pedirautorizacion {label} "
                "(lleva el aviso de privacidad).",
            )
        ]

    return handler


# --- Lectura periódica de los buzones ----------------------------------------------------------


def _meta(mailbox: Mailbox, name: str) -> str:
    return f"mbox:{mailbox.id}:{name}"


def _notify(
    conn: sqlite3.Connection, mailbox: Mailbox, kind: str, text: str, tag: str, now: datetime
) -> None:
    recipients: dict[int, User] = {}
    owner = repo.get_user(conn, mailbox.user_id)
    if owner is not None and owner.active:
        recipients[owner.id] = owner
    for cto in repo.active_users(conn, Role.CTO):
        recipients[cto.id] = cto
    for user in recipients.values():
        enqueue_critical(
            conn,
            kind=kind,
            channel=Channel.TELEGRAM,
            recipient_user_id=user.id,
            lead_id=None,
            subject=None,
            body=text,
            key=make_key(kind, mailbox.id, tag, user.id),
            now=now,
        )


def _known_internal(conn: sqlite3.Connection, address: str) -> bool:
    lowered = address.lower()
    if any(u.email.lower() == lowered for u in repo.active_users(conn)):
        return True
    return any(m.address.lower() == lowered for m in crepo.all_mailboxes(conn))


async def poll_mailboxes(db: CrmDatabase, ctx: MailContext, now: datetime) -> None:
    """Lee cada buzón activo (como mucho cada `inbox_poll_minutes`) y crea candidatos."""
    interval = timedelta(minutes=max(ctx.settings.inbox_poll_minutes, 1))
    with db.tx() as tx:
        crepo.purge_expired_candidates(tx, now)
        due: list[Mailbox] = []
        for mailbox in crepo.active_mailboxes(tx):
            last = repo.get_meta(tx, _meta(mailbox, "polled_at"))
            if last is None or now - from_iso(last) >= interval:
                repo.set_meta(tx, _meta(mailbox, "polled_at"), now.isoformat())
                due.append(mailbox)
    factory = ctx.inbox_factory or default_inbox(ctx)
    for mailbox in due:
        inbox = factory(mailbox)
        if inbox is None:
            continue
        with db.read() as conn:
            raw_validity = repo.get_meta(conn, _meta(mailbox, "uidvalidity"))
            last_uid = int(repo.get_meta(conn, _meta(mailbox, "last_uid")) or 0)
        try:
            batch = await inbox.fetch_new(int(raw_validity) if raw_validity else None, last_uid)
        except InboxError as exc:
            logger.warning("buzón {}: lectura fallida ({})", mailbox.id, type(exc).__name__)
            with db.tx() as tx:
                day = local_date(now).isoformat()
                _notify(
                    tx,
                    mailbox,
                    "mailbox_error",
                    f"No pude leer el buzón {mailbox.address}. Revisa la contraseña o la conexión.",
                    day,
                    now,
                )
            continue
        with db.tx() as tx:
            created = 0
            for message in batch.messages:
                sender = message.from_addr.strip().lower()
                if (
                    not sender
                    or AUTOMATED.search(sender)
                    or _known_internal(tx, sender)
                    or repo.leads_by_email(tx, sender)
                    or repo.any_suppressed(tx, [fingerprint(k, sender) for k in ctx.keys])
                ):
                    continue
                candidate = crepo.insert_candidate(
                    tx,
                    mailbox_id=mailbox.id,
                    message_id=message.rfc_message_id,
                    sender_email=sender,
                    sender_name=None,
                    subject=message.subject[:SUBJECT_MAX],
                    received_at=message.date or now,
                    expires_at=now + timedelta(days=ctx.settings.mail_candidate_days),
                )
                created += candidate is not None
            top = max((m.uid for m in batch.messages), default=last_uid)
            repo.set_meta(tx, _meta(mailbox, "uidvalidity"), str(batch.uidvalidity))
            repo.set_meta(tx, _meta(mailbox, "last_uid"), str(max(top, last_uid)))
            crepo.set_mailbox_ok(tx, mailbox.id, now)
            if created:
                _notify(
                    tx,
                    mailbox,
                    "mail_candidates",
                    f"Hay {created} correo(s) nuevo(s) de remitentes desconocidos en "
                    f"{mailbox.address}. Revísalos con /candidatos.",
                    f"{batch.uidvalidity}-{max(top, last_uid)}",
                    now,
                )


def register_mailboxes(bot: CrmBot, ctx: MailContext) -> None:
    bot.register_command("buzon", mailbox_command)
    bot.register_command("buzones", mailboxes_command)
    bot.register_command("candidatos", candidates_command)
    bot.register_callback(CAND_OK, register_callback(ctx))
    bot.register_callback(CAND_NO, discard_callback)
