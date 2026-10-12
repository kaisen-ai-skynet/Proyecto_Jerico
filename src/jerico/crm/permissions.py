"""Matriz de permisos y visibilidad (spec §4.4; VCRM-085, 086, 109, 134, 136). Puro, sin E/S."""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from jerico.crm.model import Lead, Role, User


class Scope(StrEnum):
    NONE = "none"
    OWN = "own"
    VISIBLE = "visible"
    ALL = "all"


class Action(StrEnum):
    REGISTER = "register"
    NOTE_ATTACH = "note_attach"
    EDIT = "edit"
    VIEW = "view"
    CONTACT_REJECT = "contact_reject"  # contacto, rechazo y reactivación
    RETRACT = "retract"
    ACCEPT = "accept"
    MARK_WON = "mark_won"
    MARK_LOST = "mark_lost"
    REGISTER_OPT_OUT = "register_opt_out"
    REGISTER_REQUEST = "register_request"
    REGISTER_AUTH = "register_auth"
    ATTEND_REQUEST = "attend_request"
    EXPORT = "export"
    SUPPRESS = "suppress"
    MANAGE_USERS = "manage_users"
    REASSIGN = "reassign"
    RESOLVE_ALERT = "resolve_alert"
    MANAGE_CADENCE = "manage_cadence"  # F2: pausar, reanudar, frecuencia y reactivar


Denial = Literal["role", "foreign_lead"]

_N, _O, _V, _A = Scope.NONE, Scope.OWN, Scope.VISIBLE, Scope.ALL


def _row(commercial: Scope, cto: Scope, lawyer: Scope) -> dict[Role, Scope]:
    return {Role.COMMERCIAL: commercial, Role.CTO: cto, Role.LAWYER: lawyer}


# Filas de la matriz §4.4 (F1 y F2).
MATRIX: dict[Action, dict[Role, Scope]] = {
    Action.REGISTER: _row(_A, _A, _N),
    Action.NOTE_ATTACH: _row(_O, _A, _N),
    Action.EDIT: _row(_O, _A, _N),
    Action.VIEW: _row(_O, _A, _V),
    Action.CONTACT_REJECT: _row(_O, _A, _N),
    Action.RETRACT: _row(_O, _A, _V),
    Action.ACCEPT: _row(_O, _A, _N),
    Action.MARK_WON: _row(_N, _A, _V),  # VCRM-134
    Action.MARK_LOST: _row(_O, _A, _N),
    Action.REGISTER_OPT_OUT: _row(_O, _A, _N),
    Action.REGISTER_REQUEST: _row(_O, _A, _N),
    Action.REGISTER_AUTH: _row(_O, _A, _N),
    Action.ATTEND_REQUEST: _row(_N, _A, _N),
    Action.EXPORT: _row(_N, _A, _N),
    Action.SUPPRESS: _row(_N, _A, _N),
    Action.MANAGE_USERS: _row(_N, _A, _N),
    Action.REASSIGN: _row(_N, _A, _N),
    Action.RESOLVE_ALERT: _row(_N, _A, _N),
    Action.MANAGE_CADENCE: _row(_O, _A, _N),  # el abogado no accede al seguimiento (plan-f2 §5.9)
}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    denial: Denial | None


_ALLOWED = Decision(True, None)
_ROLES = {role.value: role for role in Role}


def is_visible(user: User, lead: Lead) -> bool:
    """CTO ve todo; comercial, sus leads; abogado, los que alguna vez estuvieron en «aceptado»."""
    if user.role == Role.CTO:
        return True
    if user.role == Role.COMMERCIAL:
        return lead.assigned_user_id == user.id
    if user.role == Role.LAWYER:
        return bool(lead.ever_accepted)
    return False


def authorize(user: User, action: Action, lead: Lead | None) -> Decision:
    """Decide la acción según la matriz; `lead=None` para acciones sin lead concreto."""
    role = _ROLES.get(user.role)
    scope = MATRIX[action][role] if role is not None else Scope.NONE
    if scope is Scope.NONE:
        return Decision(False, "role")
    if scope is Scope.ALL or lead is None:
        return _ALLOWED
    if scope is Scope.OWN:
        ok = lead.assigned_user_id == user.id
    else:
        ok = is_visible(user, lead)
    return _ALLOWED if ok else Decision(False, "foreign_lead")


def commercial_recipients(lead: Lead, users: Iterable[User]) -> list[User]:
    """Comercial asignado si está activo y es comercial; si no, el CTO activo (decisión A.2)."""
    pool = list(users)
    for user in pool:
        if user.id == lead.assigned_user_id and user.active and user.role == Role.COMMERCIAL:
            return [user]
    return [user for user in pool if user.role == Role.CTO and user.active]
