"""Tests de la máquina de estados F1 (spec §4.2; VCRM-013, 014, 117, 133)."""

import pytest

from jerico.crm import CURRENT_PHASE
from jerico.crm.model import LeadState as S
from jerico.crm.states import TRANSITIONS, TransitionCheck, check_transition, valid_targets

F1_TRANSITIONS = [
    (S.NEW, S.CONTACTED),
    (S.REJECTED, S.CONTACTED),
    (S.NEW, S.ACCEPTED),
    (S.CONTACTED, S.ACCEPTED),
    (S.REJECTED, S.ACCEPTED),
    (S.NEW, S.REJECTED),
    (S.CONTACTED, S.REJECTED),
    (S.ACCEPTED, S.REJECTED),
    (S.ACCEPTED, S.WON),
    (S.NEW, S.LOST),
    (S.CONTACTED, S.LOST),
    (S.REJECTED, S.LOST),
] + [(s, S.OPTED_OUT) for s in S if s is not S.OPTED_OUT]

F2_TRANSITIONS = [
    (S.NURTURING, S.LOST),
    (S.PAUSED, S.LOST),
    (S.REACTIVATED, S.LOST),
    (S.REJECTED, S.NURTURING),
    (S.NURTURING, S.PAUSED),
    (S.PAUSED, S.NURTURING),
    (S.NURTURING, S.REACTIVATED),
    (S.PAUSED, S.REACTIVATED),
    (S.REJECTED, S.REACTIVATED),
    (S.REACTIVATED, S.CONTACTED),
    (S.REACTIVATED, S.ACCEPTED),
    (S.REACTIVATED, S.REJECTED),
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
    assert CURRENT_PHASE == 2
    assert check_transition(S.REJECTED, S.NURTURING).ok  # fila de F2, habilitada por defecto
    assert not check_transition(S.REJECTED, S.NURTURING, phase=1).ok
    assert check_transition(S.NEW, S.CONTACTED).ok


def test_vcrm014_not_allowed_returns_valid_targets() -> None:
    result = check_transition(S.NEW, S.WON, phase=1)
    assert not result.ok
    assert result.error_code == "not_allowed"
    assert result.valid_targets == (S.CONTACTED, S.ACCEPTED, S.REJECTED, S.LOST, S.OPTED_OUT)


def test_vcrm014_valid_targets_filtered_by_phase() -> None:
    assert valid_targets(S.REJECTED, phase=1) == (
        S.CONTACTED,
        S.ACCEPTED,
        S.LOST,
        S.OPTED_OUT,
    )
    assert S.NURTURING in valid_targets(S.REJECTED, phase=2)
    assert valid_targets(S.NURTURING, phase=1) == (S.OPTED_OUT,)


def test_vcrm014_same_state_is_not_allowed() -> None:
    result = check_transition(S.CONTACTED, S.CONTACTED, phase=1)
    assert result.error_code == "not_allowed"
    assert result.valid_targets == (S.ACCEPTED, S.REJECTED, S.LOST, S.OPTED_OUT)


@pytest.mark.parametrize("final", [S.WON, S.LOST])
@pytest.mark.parametrize("phase", [1, 2])
def test_vcrm117_final_states_only_allow_baja(final: S, phase: int) -> None:
    assert valid_targets(final, phase=phase) == (S.OPTED_OUT,)
    for dst in S:
        if dst is S.OPTED_OUT:
            continue
        result = check_transition(final, dst, phase=phase)
        assert not result.ok
        assert result.valid_targets == (S.OPTED_OUT,)


@pytest.mark.parametrize("phase", [1, 2])
def test_vcrm117_baja_has_no_targets(phase: int) -> None:
    assert valid_targets(S.OPTED_OUT, phase=phase) == ()
    for dst in S:
        result = check_transition(S.OPTED_OUT, dst, phase=phase)
        assert result == TransitionCheck(ok=False, error_code="not_allowed", valid_targets=())


@pytest.mark.parametrize("phase", [1, 2])
def test_vcrm133_aceptado_to_perdido_requires_retraction(phase: int) -> None:
    result = check_transition(S.ACCEPTED, S.LOST, phase=phase)
    assert not result.ok
    assert result.error_code == "requires_retraction"
    assert result.valid_targets == (S.REJECTED, S.WON, S.OPTED_OUT)
