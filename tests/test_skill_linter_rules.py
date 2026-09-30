from jerico.skills.validator import validate_skill_manifest


def test_strict_description_tools_and_platforms(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text(
        "---\nname: test\ndescription: "
        + "x" * 61
        + "\ntools: [invented]\nplatforms: []\n---\nUse /home/author/data"
    )
    assert {issue.code for issue in validate_skill_manifest(path)} == {
        "DESCRIPTION_TOO_LONG",
        "NON_NATIVE_TOOL",
        "PLATFORMS_REQUIRED",
        "NON_PORTABLE_PATH",
    }
    path.write_text(
        "---\nname: test\ndescription: Useful\ntools: []\nplatforms: [linux]\n---\nPortable."
    )
    assert validate_skill_manifest(path) == []
    path.write_text("invalid")
    assert validate_skill_manifest(path)[0].code == "INVALID_MANIFEST"
