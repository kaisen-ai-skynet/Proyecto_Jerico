from pathlib import Path

import pytest

from jerico.skills.curator import Curator, CuratorRunSummary, SkillTransition, format_cto_report
from jerico.skills.loader import SkillDefinition, parse_skill


def _make_skill_file(
    tmp_path: Path, name: str, pinned: bool = False, status: str = "active"
) -> SkillDefinition:
    skill_dir = tmp_path / "ventas" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    file_path = skill_dir / "SKILL.md"
    file_path.write_text(
        f"---\n"
        f"name: {name}\n"
        f"description: Skill {name}\n"
        f"tools: []\n"
        f"platforms:\n"
        f"  - linux\n"
        f"pinned: {'true' if pinned else 'false'}\n"
        f"status: {status}\n"
        f"---\n\n"
        f"# {name}\n\n"
        f"Instrucciones de la habilidad {name}.\n",
        encoding="utf-8",
    )
    return parse_skill(file_path)


def test_curator_proposes_transitions_without_mutating_disk(tmp_path):
    s1 = _make_skill_file(tmp_path, "lead-qualifier", pinned=False)
    s2 = _make_skill_file(tmp_path, "core-pricing", pinned=True)

    now = [1000.0]
    skills = {"lead-qualifier": s1, "core-pricing": s2}
    curator = Curator(skills, clock=lambda: now[0])

    # 15 days of inactivity for lead-qualifier
    now[0] += 15 * 86400
    summary = curator.maybe_run_maintenance(min_idle_hours=1, interval_hours=24)
    assert summary.ran
    assert len(summary.transitions) == 1
    t = summary.transitions[0]
    assert t.name == "lead-qualifier"
    assert t.previous == "active"
    assert t.target == "stale"
    assert t.days_inactive >= 15.0
    assert "inactividad" in t.reason.lower()

    # Disk must NOT be mutated!
    on_disk = parse_skill(s1.path)
    assert on_disk.status == "active"
    assert s1.status == "active"


def test_format_cto_report_empty_and_with_proposals():
    empty_summary = CuratorRunSummary(ran=True, transitions=())
    empty_report = format_cto_report(empty_summary)
    assert "no hay habilidades inactivas" in empty_report.lower()

    summary_with_proposals = CuratorRunSummary(
        ran=True,
        transitions=(
            SkillTransition(
                name="calificar-lead",
                previous="active",
                target="stale",
                days_inactive=16.5,
                reason="Inactiva durante 16.5 días",
            ),
            SkillTransition(
                name="vieja-skill",
                previous="stale",
                target="archived",
                days_inactive=32.0,
                reason="Inactiva durante 32.0 días",
            ),
        ),
    )
    report = format_cto_report(summary_with_proposals)
    assert "calificar-lead" in report
    assert "stale" in report
    assert "vieja-skill" in report
    assert "archived" in report
    assert "aprobación" in report.lower() or "cto" in report.lower()


def test_apply_approved_transitions_requires_explicit_cto_flag(tmp_path):
    s1 = _make_skill_file(tmp_path, "test-skill")
    skills = {"test-skill": s1}
    curator = Curator(skills)

    transition = SkillTransition(
        name="test-skill",
        previous="active",
        target="stale",
        days_inactive=15.0,
        reason="Inactiva",
    )

    # Without approved_by_cto=True, must raise PermissionError
    with pytest.raises(PermissionError, match="aprobación explícita del CTO"):
        curator.apply_approved_transitions([transition], approved_by_cto=False)

    # Disk must remain unchanged
    assert parse_skill(s1.path).status == "active"


def test_apply_approved_transitions_mutates_disk_only_when_approved_and_never_deletes(tmp_path):
    s1 = _make_skill_file(tmp_path, "proposal-skill")
    skills = {"proposal-skill": s1}
    curator = Curator(skills)

    transition = SkillTransition(
        name="proposal-skill",
        previous="active",
        target="archived",
        days_inactive=31.0,
        reason="Inactiva por 31 días",
    )

    applied = curator.apply_approved_transitions([transition], approved_by_cto=True)
    assert len(applied) == 1
    assert applied[0].name == "proposal-skill"
    assert applied[0].target == "archived"

    # Disk must be safely updated to archived
    assert s1.path.is_file(), "El archivo de la skill NUNCA debe ser eliminado"
    on_disk = parse_skill(s1.path)
    assert on_disk.status == "archived"
    assert "Instrucciones de la habilidad" in on_disk.body


def test_pinned_skills_are_immune_to_curator_transitions(tmp_path):
    s_pinned = _make_skill_file(tmp_path, "pinned-skill", pinned=True)
    skills = {"pinned-skill": s_pinned}
    curator = Curator(skills)

    transition = SkillTransition(
        name="pinned-skill",
        previous="active",
        target="stale",
        days_inactive=40.0,
        reason="Inactiva",
    )

    with pytest.raises(ValueError, match="protegida"):
        curator.apply_approved_transitions([transition], approved_by_cto=True)

    assert parse_skill(s_pinned.path).status == "active"
