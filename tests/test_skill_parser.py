import pytest

from jerico.skills.loader import SkillEngine, parse_skill


def test_discovers_skill_packages_and_rejects_duplicates(tmp_path):
    path = tmp_path / "ops" / "health" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\nname: health\ndescription: Checks health\ntools: [docker_list_containers]\n"
        "platforms: [linux]\npinned: true\n---\nUse tool:docker_list_containers."
    )
    skill = SkillEngine().discover_skills(tmp_path)["health"]
    assert skill.pinned
    assert skill.platforms == ("linux",)
    other = tmp_path / "ops" / "other" / "SKILL.md"
    other.parent.mkdir()
    other.write_text(path.read_text())
    with pytest.raises(ValueError, match="duplicada"):
        SkillEngine().discover_skills(tmp_path)


@pytest.mark.parametrize("text", ["no yaml", "---\n[]\n---\nx", "---\nname: x\n---\nx"])
def test_invalid_manifests(tmp_path, text):
    path = tmp_path / "SKILL.md"
    path.write_text(text)
    with pytest.raises(ValueError):
        parse_skill(path)
