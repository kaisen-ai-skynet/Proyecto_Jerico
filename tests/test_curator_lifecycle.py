from pathlib import Path

import pytest

from jerico.skills.curator import Curator
from jerico.skills.loader import SkillDefinition


def test_idle_weekly_gating_and_pinned_protection():
    now = [0.0]
    skills = {
        name: SkillDefinition(name, "desc", (), ("linux",), "body", Path(name), pinned)
        for name, pinned in [("normal", False), ("emergency", True)]
    }
    curator = Curator(skills, clock=lambda: now[0])
    assert not curator.maybe_run_maintenance().ran
    now[0] = 15 * 86400
    result = curator.maybe_run_maintenance()
    assert result.ran
    assert [(t.name, t.target) for t in result.transitions] == [("normal", "stale")]
    assert skills["normal"].status == "active"  # recommendation only, awaiting CTO policy
    assert not curator.maybe_run_maintenance().ran
    now[0] = 31 * 86400
    assert curator.maybe_run_maintenance().transitions[0].target == "archived"
    curator.record_activity("normal")
    assert not curator.maybe_run_maintenance().ran
    with pytest.raises(KeyError):
        curator.record_activity("missing")
    with pytest.raises(ValueError):
        curator.apply_lifecycle_transitions(30, 14)
