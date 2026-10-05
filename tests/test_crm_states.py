"""Tests de la máquina de estados F1 (spec §4.2; VCRM-013, 014, 117, 133)."""

import pytest

from jerico.crm.model import LeadState as S
from jerico.crm.states import TRANSITIONS, TransitionCheck, check_transition, valid_targets

F1_TRANSITIONS = [
    (S.NUEVO, S.CONTACTADO),
    (S.RECHAZADO, S.CONTACTADO),
    (S.NUEVO, S.ACEPTADO),
    (S.CONTACTADO, S.ACEPTADO),
    (S.RECHAZADO, S.ACEPTADO),
    (S.NUEVO, S.RECHAZADO),
    (S.CONTACTADO, S.RECHAZADO),
    (S.ACEPTADO, S.RECHAZADO),
    (S.ACEPTADO, S.GANADO),
    (S.NUEVO, S.PERDIDO),
    (S.CONTACTADO, S.PERDIDO),
    (S.RECHAZADO, S.PERDIDO),
] + [(s, S.BAJA) for s in S if s is not S.BAJA]

F2_TRANSITIONS = [
    (S.EN_NUTRICION, S.PERDIDO),
    (S.PAUSADO, S.PERDIDO),
    (S.REACTIVADO, S.PERDIDO),
    (S.RECHAZADO, S.EN_NUTRICION),
    (S.EN_NUTRICION, S.PAUSADO),
    (S.PAUSADO, S.EN_NUTRICION),
    (S.EN_NUTRICION, S.REACTIVADO),
    (S.PAUSADO, S.REACTIVADO),
    (S.RECHAZADO, S.REACTIVADO),
    (S.REACTIVADO, S.CONTACTADO),
    (S.REACTIVADO, S.ACEPTADO),
    (S.REACTIVADO, S.RECHAZADO),
]


@pytest.mark.parametrize(("src", "dst"), F1_TRANSITIONS)
def test_vcrm013_f1_transition_allowed(src: S, dst: S) -> None:
    result = check_transition(src, dst, phase=1)
    assert result == TransitionCheck(ok=True, error_code=None, valid_targets=())


@pytest.mark.parametrize(("src", "dst"), F2_TRANSITIONS)
def test_vcrm013_f2_transition_rejected_in_phase1(src: S, dst: S) -> None:
    result = check_transition(src, dst, phase=1)
    assert not result.ok
    assert result.error_code == "not_allowed"


@pytest.mark.parametrize(("src", "dst"), F2_TRANSITIONS)
def test_vcrm013_f2_transition_enabled_in_phase2(src: S, dst: S) -> None:
    assert check_transition(src, dst, phase=2).ok


def test_vcrm013_table_contains_only_section_4_2_rows() -> None:
    assert set(TRANSITIONS) == set(F1_TRANSITIONS) | set(F2_TRANSITIONS)
    assert all(TRANSITIONS[pair] == 1 for pair in F1_TRANSITIONS)
    assert all(TRANSITIONS[pair] == 2 for pair in F2_TRANSITIONS)


def test_vcrm013_default_phase_is_current_phase() -> None:
    assert not check_transition(S.RECHAZADO, S.EN_NUTRICION).ok
    assert check_transition(S.NUEVO, S.CONTACTADO).ok


def test_vcrm014_not_allowed_returns_valid_targets() -> None:
    result = check_transition(S.NUEVO, S.GANADO, phase=1)
    assert not result.ok
    assert result.error_code == "not_allowed"
    assert result.valid_targets == (S.CONTACTADO, S.ACEPTADO, S.RECHAZADO, S.PERDIDO, S.BAJA)


def test_vcrm014_valid_targets_filtered_by_phase() -> None:
    assert valid_targets(S.RECHAZADO, phase=1) == (
        S.CONTACTADO,
        S.ACEPTADO,
        S.PERDIDO,
        S.BAJA,
    )
    assert S.EN_NUTRICION in valid_targets(S.RECHAZADO, phase=2)
    assert valid_targets(S.EN_NUTRICION, phase=1) == (S.BAJA,)


def test_vcrm014_same_state_is_not_allowed() -> None:
    result = check_transition(S.CONTACTADO, S.CONTACTADO, phase=1)
    assert result.error_code == "not_allowed"
    assert result.valid_targets == (S.ACEPTADO, S.RECHAZADO, S.PERDIDO, S.BAJA)


@pytest.mark.parametrize("final", [S.GANADO, S.PERDIDO])
@pytest.mark.parametrize("phase", [1, 2])
def test_vcrm117_final_states_only_allow_baja(final: S, phase: int) -> None:
    assert valid_targets(final, phase=phase) == (S.BAJA,)
    for dst in S:
        if dst is S.BAJA:
            continue
        result = check_transition(final, dst, phase=phase)
        assert not result.ok
        assert result.valid_targets == (S.BAJA,)


@pytest.mark.parametrize("phase", [1, 2])
def test_vcrm117_baja_has_no_targets(phase: int) -> None:
    assert valid_targets(S.BAJA, phase=phase) == ()
    for dst in S:
        result = check_transition(S.BAJA, dst, phase=phase)
        assert result == TransitionCheck(ok=False, error_code="not_allowed", valid_targets=())


@pytest.mark.parametrize("phase", [1, 2])
def test_vcrm133_aceptado_to_perdido_requires_retraction(phase: int) -> None:
    result = check_transition(S.ACEPTADO, S.PERDIDO, phase=phase)
    assert not result.ok
    assert result.error_code == "requires_retraction"
    assert result.valid_targets == (S.RECHAZADO, S.GANADO, S.BAJA)
