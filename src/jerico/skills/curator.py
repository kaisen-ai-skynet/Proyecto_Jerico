import time
from collections.abc import Callable
from dataclasses import dataclass

from jerico.skills.loader import SkillDefinition


@dataclass(frozen=True)
class SkillTransition:
    name: str
    previous: str
    target: str


@dataclass(frozen=True)
class CuratorRunSummary:
    ran: bool
    transitions: tuple[SkillTransition, ...] = ()


class Curator:
    """Idle-triggered recommendations. Mutation requires an explicit CTO policy."""

    def __init__(
        self, skills: dict[str, SkillDefinition], *, clock: Callable[[], float] = time.time
    ) -> None:
        self.skills = skills
        self.clock = clock
        self.last_activity = clock()
        self.last_run: float | None = None
        self.last_used = {name: clock() for name in skills}

    def record_activity(self, skill_name: str | None = None) -> None:
        self.last_activity = self.clock()
        if skill_name is not None:
            if skill_name not in self.skills:
                raise KeyError(skill_name)
            self.last_used[skill_name] = self.last_activity

    def maybe_run_maintenance(
        self, min_idle_hours: int = 2, interval_hours: int = 168
    ) -> CuratorRunSummary:
        if min_idle_hours < 0 or interval_hours <= 0:
            raise ValueError("intervalos inválidos")
        now = self.clock()
        if now - self.last_activity <= min_idle_hours * 3600:
            return CuratorRunSummary(False)
        if self.last_run is not None and now - self.last_run < interval_hours * 3600:
            return CuratorRunSummary(False)
        self.last_run = now
        return CuratorRunSummary(True, tuple(self.apply_lifecycle_transitions()))

    def apply_lifecycle_transitions(
        self, stale_days: int = 14, archive_days: int = 30
    ) -> list[SkillTransition]:
        if stale_days < 0 or archive_days < stale_days:
            raise ValueError("umbrales inválidos")
        transitions = []
        for name, skill in sorted(self.skills.items()):
            if skill.pinned or skill.status == "archived":
                continue
            days = (self.clock() - self.last_used[name]) / 86400
            target = "archived" if days >= archive_days else "stale" if days >= stale_days else None
            if target is not None and target != skill.status:
                transitions.append(SkillTransition(name, skill.status, target))
        return transitions
