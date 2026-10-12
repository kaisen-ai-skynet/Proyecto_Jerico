"""Máquina de estados del lead (spec §4.2; VCRM-013, 014, 117, 133). Puro, sin E/S."""

from dataclasses import dataclass

from jerico.crm import CURRENT_PHASE
from jerico.crm.model import LeadState

_S = LeadState

# (origen, destino) -> fase en que se habilita (spec §4.2).
TRANSITIONS: dict[tuple[LeadState, LeadState], int] = {
    (_S.NEW, _S.CONTACTED): 1,
    (_S.REJECTED, _S.CONTACTED): 1,
    (_S.NEW, _S.ACCEPTED): 1,
    (_S.CONTACTED, _S.ACCEPTED): 1,
    (_S.REJECTED, _S.ACCEPTED): 1,
    (_S.NEW, _S.REJECTED): 1,
    (_S.CONTACTED, _S.REJECTED): 1,
    (_S.ACCEPTED, _S.REJECTED): 1,  # retractación (VCRM-131)
    (_S.ACCEPTED, _S.WON): 1,
    (_S.NEW, _S.LOST): 1,
    (_S.CONTACTED, _S.LOST): 1,
    (_S.REJECTED, _S.LOST): 1,
    **{(s, _S.OPTED_OUT): 1 for s in _S if s is not _S.OPTED_OUT},
    # Filas de F2: presentes y filtradas por fase.
    (_S.NURTURING, _S.LOST): 2,
    (_S.PAUSED, _S.LOST): 2,
    (_S.REACTIVATED, _S.LOST): 2,
    (_S.REJECTED, _S.NURTURING): 2,
    (_S.NURTURING, _S.PAUSED): 2,
    (_S.PAUSED, _S.NURTURING): 2,
    (_S.NURTURING, _S.REACTIVATED): 2,
    (_S.PAUSED, _S.REACTIVATED): 2,
    (_S.REJECTED, _S.REACTIVATED): 2,
    (_S.REACTIVATED, _S.CONTACTED): 2,
    (_S.REACTIVATED, _S.ACCEPTED): 2,
    (_S.REACTIVATED, _S.REJECTED): 2,
}


@dataclass(frozen=True)
class TransitionCheck:
    ok: bool
    error_code: str | None  # None | 'not_allowed' | 'requires_retraction'
    valid_targets: tuple[LeadState, ...]


def _enabled(src: LeadState, dst: LeadState, phase: int) -> bool:
    enabled_in = TRANSITIONS.get((src, dst))
    return enabled_in is not None and enabled_in <= phase


def valid_targets(src: LeadState, phase: int = CURRENT_PHASE) -> tuple[LeadState, ...]:
    """Destinos habilitados desde `src` en la fase dada, en el orden de `LeadState`."""
    return tuple(dst for dst in LeadState if _enabled(src, dst, phase))


def check_transition(src: LeadState, dst: LeadState, phase: int = CURRENT_PHASE) -> TransitionCheck:
    """Valida una transición; si no procede, devuelve el código y los destinos válidos."""
    if _enabled(src, dst, phase):
        return TransitionCheck(ok=True, error_code=None, valid_targets=())
    targets = valid_targets(src, phase)
    if src is LeadState.ACCEPTED and dst is LeadState.LOST:
        return TransitionCheck(ok=False, error_code="requires_retraction", valid_targets=targets)
    return TransitionCheck(ok=False, error_code="not_allowed", valid_targets=targets)
