"""Tests de la matriz de permisos y visibilidad (spec §4.4; VCRM-085, 086, 109, 134, 136)."""

from dataclasses import replace

import pytest

from jerico.crm.model import Lead, Role, User
from jerico.crm.permissions import (
    MATRIX,
    Action,
    Decision,
    Scope,
    authorize,
    commercial_recipients,
    is_visible,
)

A = Action

CTO = User(1, 100, Role.CTO, "cto@example.com", 1, "2026-01-01T00:00:00Z", None)
COM = User(2, 200, Role.COMMERCIAL, "com@example.com", 1, "2026-01-01T00:00:00Z", None)
COM2 = User(3, 300, Role.COMMERCIAL, "com2@example.com", 1, "2026-01-01T00:00:00Z", None)
LAW = User(4, 400, Role.LAWYER, "law@example.com", 1, "2026-01-01T00:00:00Z", None)
USERS = {Role.CTO: CTO, Role.COMMERCIAL: COM, Role.LAWYER: LAW}

LEAD = Lead(
    id=10,
    assigned_user_id=COM.id,
    state="aceptado",
    name=None,
    phone_e164=None,
    email=None,
    company=None,
    client_type=None,
    doc_type=None,
    doc_number=None,
    legal_rep=None,
    service=None,
    agreed_value=None,
    start_term=None,
    reject_reason=None,
    reject_text=None,
    rejection_is_retraction=0,
    auth_status="sin_autorizacion",
    ever_accepted=1,
    registered_at="2026-01-01T00:00:00Z",
    last_interaction_at="2026-01-01T00:00:00Z",
    accepted_exit_at=None,
    won_at=None,
    final_state_at=None,
    legal_hold_basis=None,
    commercial_block=0,
    suppressed_at=None,
    suppression_cause=None,
)
FOREIGN = replace(LEAD, id=11, assigned_user_id=COM2.id)

# Filas F1 de §4.4: acción -> (comercial, cto, abogado).
EXPECTED: dict[Action, tuple[Scope, Scope, Scope]] = {
    A.REGISTER: (Scope.ALL, Scope.ALL, Scope.NONE),
    A.NOTE_ATTACH: (Scope.OWN, Scope.ALL, Scope.NONE),
    A.EDIT: (Scope.OWN, Scope.ALL, Scope.NONE),
    A.VIEW: (Scope.OWN, Scope.ALL, Scope.VISIBLE),
    A.CONTACT_REJECT: (Scope.OWN, Scope.ALL, Scope.NONE),
    A.RETRACT: (Scope.OWN, Scope.ALL, Scope.VISIBLE),
    A.ACCEPT: (Scope.OWN, Scope.ALL, Scope.NONE),
    A.MARK_WON: (Scope.NONE, Scope.ALL, Scope.VISIBLE),
    A.MARK_LOST: (Scope.OWN, Scope.ALL, Scope.NONE),
    A.REGISTER_OPT_OUT: (Scope.OWN, Scope.ALL, Scope.NONE),
    A.REGISTER_REQUEST: (Scope.OWN, Scope.ALL, Scope.NONE),
    A.REGISTER_AUTH: (Scope.OWN, Scope.ALL, Scope.NONE),
    A.ATTEND_REQUEST: (Scope.NONE, Scope.ALL, Scope.NONE),
    A.EXPORT: (Scope.NONE, Scope.ALL, Scope.NONE),
    A.SUPPRESS: (Scope.NONE, Scope.ALL, Scope.NONE),
    A.MANAGE_USERS: (Scope.NONE, Scope.ALL, Scope.NONE),
    A.REASSIGN: (Scope.NONE, Scope.ALL, Scope.NONE),
    A.RESOLVE_ALERT: (Scope.NONE, Scope.ALL, Scope.NONE),
}
ROLES = (Role.COMMERCIAL, Role.CTO, Role.LAWYER)


def _expected_decision(scope: Scope, own: bool) -> Decision:
    if scope is Scope.NONE:
        return Decision(False, "role")
    if scope is Scope.ALL or own:
        return Decision(True, None)
    return Decision(False, "foreign_lead")


CASES = [
    pytest.param(action, role, own, id=f"{action.value}-{role.value}-{'own' if own else 'foreign'}")
    for action in EXPECTED
    for role in ROLES
    for own in (True, False)
]


def test_vcrm085_matrix_covers_all_f1_rows_exactly() -> None:
    assert set(MATRIX) == set(EXPECTED)
    for action, scopes in EXPECTED.items():
        assert MATRIX[action] == dict(zip(ROLES, scopes, strict=True))


@pytest.mark.parametrize(("action", "role", "own"), CASES)
def test_vcrm085_authorize_matrix(action: Action, role: Role, own: bool) -> None:
    user = USERS[role]
    scope = EXPECTED[action][ROLES.index(role)]
    # «Propio»: asignado al comercial; para el abogado, visible (alguna vez aceptado).
    if role is Role.LAWYER:
        lead = LEAD if own else replace(LEAD, ever_accepted=0)
    else:
        lead = replace(LEAD, assigned_user_id=user.id) if own else FOREIGN
    assert authorize(user, action, lead) == _expected_decision(scope, own)


def test_vcrm109_commercial_on_foreign_lead_is_foreign_lead() -> None:
    for action in (A.VIEW, A.EDIT, A.NOTE_ATTACH, A.CONTACT_REJECT, A.MARK_LOST):
        assert authorize(COM, action, FOREIGN) == Decision(False, "foreign_lead")


def test_vcrm109_commercial_on_unassigned_lead_is_foreign_lead() -> None:
    lead = replace(LEAD, assigned_user_id=None)
    assert authorize(COM, A.VIEW, lead) == Decision(False, "foreign_lead")
    assert not is_visible(COM, lead)


def test_vcrm136_lawyer_never_accepted_is_foreign_lead() -> None:
    never = replace(LEAD, state="nuevo", ever_accepted=0)
    assert authorize(LAW, A.VIEW, never) == Decision(False, "foreign_lead")
    assert authorize(LAW, A.MARK_WON, never) == Decision(False, "foreign_lead")
    assert not is_visible(LAW, never)


def test_vcrm136_lawyer_once_accepted_is_visible() -> None:
    # Estuvo en «aceptado» y hoy está en «perdido»/«rechazado»: sigue visible (decisión A.1).
    for state in ("aceptado", "ganado", "perdido", "rechazado"):
        lead = replace(LEAD, state=state, ever_accepted=1, assigned_user_id=COM2.id)
        assert is_visible(LAW, lead)
        assert authorize(LAW, A.VIEW, lead) == Decision(True, None)


def test_vcrm134_commercial_mark_won_is_role_even_on_own_lead() -> None:
    assert authorize(COM, A.MARK_WON, LEAD) == Decision(False, "role")


def test_vcrm086_role_denial_for_disallowed_action() -> None:
    assert authorize(LAW, A.REGISTER, None) == Decision(False, "role")
    assert authorize(COM, A.EXPORT, LEAD) == Decision(False, "role")
    assert authorize(LAW, A.MARK_LOST, LEAD) == Decision(False, "role")


def test_vcrm085_actions_without_lead_are_allowed_when_role_permits() -> None:
    assert authorize(COM, A.REGISTER, None) == Decision(True, None)
    assert authorize(CTO, A.MANAGE_USERS, None) == Decision(True, None)
    # Lista de leads: permitido; el filtrado lo hace is_visible.
    assert authorize(COM, A.VIEW, None) == Decision(True, None)
    assert authorize(LAW, A.VIEW, None) == Decision(True, None)


def test_vcrm085_cto_sees_every_lead() -> None:
    for lead in (LEAD, FOREIGN, replace(LEAD, assigned_user_id=None, ever_accepted=0)):
        assert is_visible(CTO, lead)


def test_vcrm085_commercial_sees_only_own() -> None:
    assert is_visible(COM, LEAD)
    assert not is_visible(COM, FOREIGN)


def test_vcrm085_unknown_role_is_denied() -> None:
    ghost = replace(COM, role="intruso")
    assert authorize(ghost, A.VIEW, LEAD) == Decision(False, "role")
    assert not is_visible(ghost, LEAD)


# commercial_recipients (decisión A.2): lo dirigido al comercial va al CTO cuando el lead es
# suyo, no tiene comercial o su comercial está inactivo.
ALL_USERS = [CTO, COM, COM2, LAW]


def test_vcrm085_recipients_active_commercial() -> None:
    assert commercial_recipients(LEAD, ALL_USERS) == [COM]


def test_vcrm085_recipients_cto_own_lead() -> None:
    lead = replace(LEAD, assigned_user_id=CTO.id)
    assert commercial_recipients(lead, ALL_USERS) == [CTO]


def test_vcrm085_recipients_inactive_commercial_goes_to_cto() -> None:
    inactive = replace(COM, active=0, deactivated_at="2026-02-01T00:00:00Z")
    assert commercial_recipients(LEAD, [CTO, inactive, LAW]) == [CTO]


def test_vcrm085_recipients_unassigned_goes_to_cto() -> None:
    lead = replace(LEAD, assigned_user_id=None)
    assert commercial_recipients(lead, ALL_USERS) == [CTO]


def test_vcrm085_recipients_assignee_missing_or_not_commercial_goes_to_cto() -> None:
    assert commercial_recipients(replace(LEAD, assigned_user_id=999), ALL_USERS) == [CTO]
    assert commercial_recipients(replace(LEAD, assigned_user_id=LAW.id), ALL_USERS) == [CTO]


def test_vcrm085_recipients_without_active_cto_is_empty() -> None:
    inactive_cto = replace(CTO, active=0)
    assert commercial_recipients(replace(LEAD, assigned_user_id=None), [inactive_cto, COM]) == []
