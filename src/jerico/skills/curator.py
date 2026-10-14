import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from jerico.skills.loader import SkillDefinition


@dataclass(frozen=True)
class SkillTransition:
    name: str
    previous: str
    target: str
    days_inactive: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class CuratorRunSummary:
    ran: bool
    transitions: tuple[SkillTransition, ...] = ()


def format_cto_report(summary: CuratorRunSummary) -> str:
    """Genera un informe para revisión y decisión del CTO."""
    if not summary.transitions:
        return (
            "📋 Informe del Curador de Habilidades:\n"
            "No hay habilidades inactivas que requieran transición."
        )
    lines = [
        "📋 Informe del Curador de Habilidades (Propuesta para revisión del CTO):",
        "Se detectaron las siguientes habilidades con inactividad prolongada:",
    ]
    for t in summary.transitions:
        detalle = t.reason if t.reason else f"inactiva durante {t.days_inactive:.1f} días"
        lines.append(f"• `{t.name}`: transicionar de `{t.previous}` a `{t.target}` ({detalle}).")
    lines.append(
        "\n⚠️ Acción requerida: Requiere aprobación explícita del CTO "
        "antes de aplicar cualquier cambio en disco."
    )
    return "\n".join(lines)


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
                reason = f"Inactividad detectada durante {days:.1f} días"
                transitions.append(SkillTransition(name, skill.status, target, days, reason))
        return transitions

    def apply_approved_transitions(
        self,
        transitions: Sequence[SkillTransition],
        *,
        approved_by_cto: bool = False,
    ) -> list[SkillTransition]:
        """Aplica transiciones aprobadas por el CTO, editando frontmatter en disco sin borrar."""
        if not approved_by_cto:
            raise PermissionError(
                "Se requiere la aprobación explícita del CTO (approved_by_cto=True) "
                "para modificar habilidades en disco."
            )
        applied = []
        for t in transitions:
            if t.name not in self.skills:
                raise KeyError(t.name)
            skill = self.skills[t.name]
            if skill.pinned:
                raise ValueError(
                    f"La habilidad '{t.name}' está protegida (pinned=True) "
                    "y no puede transicionarse."
                )
            self._update_skill_status_on_disk(skill.path, t.target)
            new_skill = SkillDefinition(
                name=skill.name,
                description=skill.description,
                tools=skill.tools,
                platforms=skill.platforms,
                body=skill.body,
                path=skill.path,
                pinned=skill.pinned,
                status=t.target,
            )
            self.skills[t.name] = new_skill
            applied.append(t)
        return applied

    def _update_skill_status_on_disk(self, path: Path, new_status: str) -> None:
        text = path.read_text(encoding="utf-8")
        parts = text.split("---", 2)
        if len(parts) != 3 or parts[0].strip():
            raise ValueError(f"El archivo {path} no tiene un frontmatter YAML válido")
        frontmatter = parts[1]
        lines = frontmatter.splitlines()
        status_found = False
        new_lines = []
        for line in lines:
            if line.strip().startswith("status:"):
                new_lines.append(f"status: {new_status}")
                status_found = True
            else:
                new_lines.append(line)
        if not status_found:
            new_lines.append(f"status: {new_status}")
        new_frontmatter = "\n".join(new_lines) + "\n"
        updated_text = f"---{new_frontmatter}---{parts[2]}"
        path.write_text(updated_text, encoding="utf-8")
