"""Usuarios autorizados: siembra del CTO, alta, baja y reasignación (plan §8.1).

Requisitos: VCRM-125, 126, 144, 091, 092, 093. Cada caso de uso recibe la conexión de
`CrmDatabase.tx()` y `now`, y devuelve los mensajes de respuesta (`Outgoing`).
"""

import logging
import re
import sqlite3
from datetime import datetime

from jerico.crm import repo
from jerico.crm.config import CrmSettings
from jerico.crm.model import AuditAction, AuditOutcome, EventKind, Outgoing, Role, User
from jerico.crm.parsing import build_callback, normalize_email, parse_short_id
from jerico.crm.permissions import Action, authorize
from jerico.crm.render import NO_VALUE, PAGE_SIZE, short_id

logger = logging.getLogger(__name__)

SEED_TG_VAR = "JERICO_CRM_SEED_CTO_TELEGRAM_ID"
SEED_EMAIL_VAR = "JERICO_CRM_SEED_CTO_EMAIL"
UNASSIGNED = "sin comercial asignado"
DENIED = "No tiene permiso para esta acción."
_NOT_ADDED = " No se dio de alta al usuario."
_ROLE_WORDS = {"comercial": Role.COMMERCIAL, "abogado": Role.LAWYER}
_TG_RE = re.compile(r"^\d{1,19}$", re.ASCII)
_REASSIGN_USAGE = "Use: /reasignar L-n; telegram_id|cto"


def _body(text: str, command: str) -> str:
    m = re.match(rf"^/{command}(?:@\w+)?(?:\s+|$)(.*)$", text.strip(), re.DOTALL)
    return m.group(1).strip() if m else ""


def _parse_tg(raw: str) -> int | None:
    raw = raw.strip()
    if not _TG_RE.match(raw) or int(raw) <= 0:
        return None
    return int(raw)


def _deny(conn: sqlite3.Connection, actor: User, now: datetime) -> list[Outgoing]:
    repo.audit(
        conn,
        actor=f"user:{actor.id}",
        action=AuditAction.PERMISSION_DENIED,
        outcome=AuditOutcome.DENIED,
        at=now,
    )
    return [Outgoing(actor.telegram_id, DENIED)]


def assignee_label(user: User | None) -> str:
    """«del CTO», «comercial <correo>» o «sin comercial asignado» si está inactivo (VCRM-092)."""
    if user is None or not user.active:
        return UNASSIGNED
    if user.role == Role.CTO:
        return "del CTO"
    return f"comercial {user.email}"


# --- Siembra del CTO (VCRM-125, VCRM-126) -------------------------------------------------


def seed_cto(conn: sqlite3.Connection, settings: CrmSettings, now: datetime) -> User | None:
    """Siembra el CTO inicial solo si no hay CTO activo; registra nombres, nunca valores."""
    if repo.active_users(conn, Role.CTO):
        return None
    problems: list[str] = []
    raw_tg = settings.seed_cto_telegram_id.strip()
    raw_email = settings.seed_cto_email.strip()
    telegram_id = _parse_tg(raw_tg)
    email = normalize_email(raw_email)
    if telegram_id is None:
        problems.append(f"{'faltante' if not raw_tg else 'inválido'}: {SEED_TG_VAR}")
    if email is None:
        problems.append(f"{'faltante' if not raw_email else 'inválido'}: {SEED_EMAIL_VAR}")
    if telegram_id is not None and repo.active_user_by_telegram(conn, telegram_id) is not None:
        problems.append(f"repetido: {SEED_TG_VAR}")
    if problems or telegram_id is None or email is None:
        logger.warning("Siembra del CTO omitida; dato %s", "; ".join(problems))
        return None
    return repo.insert_user(conn, telegram_id=telegram_id, role=Role.CTO, email=email, now=now)


# --- Alta (VCRM-144, VCRM-126) ------------------------------------------------------------


def add_user(conn: sqlite3.Connection, actor: User, text: str, now: datetime) -> list[Outgoing]:
    """`/alta comercial|abogado; telegram_id; correo` (solo CTO)."""
    if not authorize(actor, Action.MANAGE_USERS, None).allowed:
        return _deny(conn, actor, now)
    parts = [p.strip() for p in _body(text, "alta").split(";")]
    parts += [""] * (3 - len(parts))
    raw_role, raw_tg, raw_email = parts[:3]
    error: str | None = None
    role = _ROLE_WORDS.get(raw_role.lower())
    telegram_id = _parse_tg(raw_tg)
    email = normalize_email(raw_email)
    if not raw_role:
        error = "Falta el rol (comercial o abogado)."
    elif role is None:
        error = "El rol no es válido: use comercial o abogado."
    elif not raw_tg:
        error = "Falta el identificador de Telegram."
    elif telegram_id is None:
        error = "El identificador de Telegram no es válido."
    elif not raw_email:
        error = "Falta el correo."
    elif email is None:
        error = "El correo no tiene la forma usuario@dominio."
    elif repo.active_user_by_telegram(conn, telegram_id) is not None:
        error = "El identificador de Telegram ya pertenece a un usuario autorizado."
    if error is not None or role is None or telegram_id is None or email is None:
        return [Outgoing(actor.telegram_id, f"{error}{_NOT_ADDED}")]
    repo.insert_user(conn, telegram_id=telegram_id, role=role, email=email, now=now)
    repo.audit(
        conn,
        actor=f"user:{actor.id}",
        action=AuditAction.USER_ADDED,
        outcome=AuditOutcome.OK,
        at=now,
    )
    return [Outgoing(actor.telegram_id, f"Alta registrada: {raw_role.lower()} {email}.")]


# --- Baja (VCRM-091) ----------------------------------------------------------------------


def orphan_leads_message(
    conn: sqlite3.Connection, chat_id: int, commercial_id: int, page: int
) -> Outgoing:
    """Página de leads (estado ≠ baja) del comercial con botón «Reasignar» por lead."""
    leads = repo.leads_of_user(conn, commercial_id)
    if not leads:
        return Outgoing(chat_id, "El comercial no tiene leads por reasignar.")
    total = -(-len(leads) // PAGE_SIZE)
    page = min(max(page, 1), total)
    chunk = leads[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
    lines = ["Leads del comercial dado de baja:"]
    lines += [f"{short_id(lead.id)} · {lead.name or NO_VALUE} · {lead.state}" for lead in chunk]
    lines.append(f"página {page} de {total}")
    rows: list[tuple[tuple[str, str], ...]] = [
        ((f"Reasignar {short_id(lead.id)}", build_callback("reasignar", str(lead.id))),)
        for lead in chunk
    ]
    nav: list[tuple[str, str]] = []
    if page > 1:
        nav.append(("Anterior", build_callback("baja_leads", str(commercial_id), str(page - 1))))
    if page < total:
        nav.append(("Siguiente", build_callback("baja_leads", str(commercial_id), str(page + 1))))
    if nav:
        rows.append(tuple(nav))
    return Outgoing(chat_id, "\n".join(lines), tuple(rows))


def deactivate_user(
    conn: sqlite3.Connection, actor: User, text: str, now: datetime
) -> list[Outgoing]:
    """`/baja_usuario telegram_id` (solo CTO; el rol CTO no se da de baja)."""
    if not authorize(actor, Action.MANAGE_USERS, None).allowed:
        return _deny(conn, actor, now)
    telegram_id = _parse_tg(_body(text, "baja_usuario"))
    target = None if telegram_id is None else repo.active_user_by_telegram(conn, telegram_id)
    if target is None:
        return [
            Outgoing(
                actor.telegram_id,
                "No hay un usuario autorizado con ese identificador de Telegram.",
            )
        ]
    if target.role == Role.CTO:
        return [Outgoing(actor.telegram_id, "El rol CTO no se da de baja por el bot.")]
    repo.deactivate_user(conn, target.id, now=now)
    repo.audit(
        conn,
        actor=f"user:{actor.id}",
        action=AuditAction.USER_DEACTIVATED,
        outcome=AuditOutcome.OK,
        at=now,
    )
    out = [Outgoing(actor.telegram_id, f"Baja registrada: {target.email}.")]
    if target.role == Role.COMMERCIAL:
        out.append(orphan_leads_message(conn, actor.telegram_id, target.id, 1))
    return out


# --- Reasignación (VCRM-093) --------------------------------------------------------------


def _missing_lead(actor: User, lead_id: int) -> list[Outgoing]:
    return [Outgoing(actor.telegram_id, f"No existe el lead {short_id(lead_id)}.")]


def _targets(conn: sqlite3.Connection) -> list[User]:
    return [u for u in repo.active_users(conn) if u.role in (Role.CTO, Role.COMMERCIAL)]


def reassign_keyboard(
    conn: sqlite3.Connection, actor: User, lead_id: int, now: datetime
) -> list[Outgoing]:
    """Teclado de destinos (CTO y comerciales activos) para reasignar un lead."""
    if not authorize(actor, Action.REASSIGN, None).allowed:
        return _deny(conn, actor, now)
    lead = repo.get_lead(conn, lead_id)
    if lead is None:
        return _missing_lead(actor, lead_id)
    current = None if lead.assigned_user_id is None else repo.get_user(conn, lead.assigned_user_id)
    rows = tuple(
        (
            (
                "A mí (CTO)" if user.role == Role.CTO else user.email,
                build_callback("reasignar", str(lead_id), str(user.id)),
            ),
        )
        for user in _targets(conn)
    )
    text = f"Reasignar {short_id(lead_id)} ({assignee_label(current)}). Elija el destino:"
    return [Outgoing(actor.telegram_id, text, rows)]


def reassign(
    conn: sqlite3.Connection, actor: User, lead_id: int, target_user_id: int, now: datetime
) -> list[Outgoing]:
    """Cambia el comercial del lead y registra anterior, nuevo, autor y fecha-hora."""
    if not authorize(actor, Action.REASSIGN, None).allowed:
        return _deny(conn, actor, now)
    lead = repo.get_lead(conn, lead_id)
    if lead is None:
        return _missing_lead(actor, lead_id)
    target = repo.get_user(conn, target_user_id)
    if target is None or not target.active or target.role not in (Role.CTO, Role.COMMERCIAL):
        return [Outgoing(actor.telegram_id, "El destino no es un comercial activo ni el CTO.")]
    repo.set_assignee(conn, lead_id, target.id)
    old = lead.assigned_user_id
    repo.add_event(
        conn,
        lead_id=lead_id,
        kind=EventKind.REASSIGN,
        actor_user_id=actor.id,
        at=now,
        field="assigned_user_id",
        old_value=None if old is None else str(old),
        new_value=str(target.id),
    )
    label = "el CTO" if target.role == Role.CTO else f"comercial {target.email}"
    return [Outgoing(actor.telegram_id, f"Lead {short_id(lead_id)} reasignado a {label}.")]


def reassign_command(
    conn: sqlite3.Connection, actor: User, text: str, now: datetime
) -> list[Outgoing]:
    """`/reasignar L-n; telegram_id|cto`."""
    if not authorize(actor, Action.REASSIGN, None).allowed:
        return _deny(conn, actor, now)
    parts = [p.strip() for p in _body(text, "reasignar").split(";")]
    lead_id = parse_short_id(parts[0])
    if len(parts) != 2 or lead_id is None:
        return [Outgoing(actor.telegram_id, _REASSIGN_USAGE)]
    if parts[1].lower() == "cto":
        return reassign(conn, actor, lead_id, actor.id, now)
    telegram_id = _parse_tg(parts[1])
    target = None if telegram_id is None else repo.active_user_by_telegram(conn, telegram_id)
    if target is None:
        return [Outgoing(actor.telegram_id, "El destino no es un comercial activo ni el CTO.")]
    return reassign(conn, actor, lead_id, target.id, now)
