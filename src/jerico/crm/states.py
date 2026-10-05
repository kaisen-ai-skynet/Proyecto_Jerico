"""Máquina de estados del lead (spec §4.2; VCRM-013, 014, 117, 133). Puro, sin E/S."""

from dataclasses import dataclass

from jerico.crm import CURRENT_PHASE
from jerico.crm.model import LeadState

_S = LeadState

# (origen, destino) -> fase en que se habilita (spec §4.2).
TRANSITIONS: dict[tuple[LeadState, LeadState], int] = {
    (_S.NUEVO, _S.CONTACTADO): 1,
    (_S.RECHAZADO, _S.CONTACTADO): 1,
    (_S.NUEVO, _S.ACEPTADO): 1,
    (_S.CONTACTADO, _S.ACEPTADO): 1,
    (_S.RECHAZADO, _S.ACEPTADO): 1,
    (_S.NUEVO, _S.RECHAZADO): 1,
    (_S.CONTACTADO, _S.RECHAZADO): 1,
    (_S.ACEPTADO, _S.RECHAZADO): 1,  # retractación (VCRM-131)
    (_S.ACEPTADO, _S.GANADO): 1,
    (_S.NUEVO, _S.PERDIDO): 1,
    (_S.CONTACTADO, _S.PERDIDO): 1,
    (_S.RECHAZADO, _S.PERDIDO): 1,
    **{(s, _S.BAJA): 1 for s in _S if s is not _S.BAJA},
    # Filas de F2: presentes y filtradas por fase.
    (_S.EN_NUTRICION, _S.PERDIDO): 2,
    (_S.PAUSADO, _S.PERDIDO): 2,
    (_S.REACTIVADO, _S.PERDIDO): 2,
    (_S.RECHAZADO, _S.EN_NUTRICION): 2,
    (_S.EN_NUTRICION, _S.PAUSADO): 2,
    (_S.PAUSADO, _S.EN_NUTRICION): 2,
    (_S.EN_NUTRICION, _S.REACTIVADO): 2,
    (_S.PAUSADO, _S.REACTIVADO): 2,
    (_S.RECHAZADO, _S.REACTIVADO): 2,
    (_S.REACTIVADO, _S.CONTACTADO): 2,
    (_S.REACTIVADO, _S.ACEPTADO): 2,
    (_S.REACTIVADO, _S.RECHAZADO): 2,
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
    if src is LeadState.ACEPTADO and dst is LeadState.PERDIDO:
        return TransitionCheck(ok=False, error_code="requires_retraction", valid_targets=targets)
    return TransitionCheck(ok=False, error_code="not_allowed", valid_targets=targets)
