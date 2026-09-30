from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    tools: tuple[str, ...]
    platforms: tuple[str, ...]
    body: str
    path: Path
    pinned: bool = False
    status: str = "active"


def parse_skill(path: Path) -> SkillDefinition:
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) != 3 or parts[0].strip():
        raise ValueError("SKILL.md requiere frontmatter YAML")
    metadata = yaml.safe_load(parts[1])
    if not isinstance(metadata, dict):
        raise ValueError("manifest debe ser un objeto")
    name, description = metadata.get("name"), metadata.get("description")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name requerido")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("description requerida")
    fields = []
    for key in ("tools", "platforms"):
        value = metadata.get(key, [])
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError(f"{key} debe ser lista de strings")
        fields.append(tuple(value))
    pinned = metadata.get("pinned", False)
    if not isinstance(pinned, bool):
        raise ValueError("pinned debe ser booleano")
    status = metadata.get("status", "active")
    if status not in {"active", "stale", "archived"}:
        raise ValueError("status inválido")
    return SkillDefinition(
        name, description, fields[0], fields[1], parts[2].strip(), path, pinned, status
    )


class SkillEngine:
    def discover_skills(self, directory: Path) -> dict[str, SkillDefinition]:
        skills: dict[str, SkillDefinition] = {}
        for path in sorted(directory.glob("*/*/SKILL.md")):
            if any(part.startswith(".") for part in path.relative_to(directory).parts):
                continue
            skill = parse_skill(path)
            if skill.name in skills:
                raise ValueError(f"skill duplicada: {skill.name}")
            skills[skill.name] = skill
        return skills

    def validate_skill_manifest(self, manifest_path: Path) -> list["SkillLintIssue"]:
        from jerico.skills.validator import validate_skill_manifest

        return validate_skill_manifest(manifest_path)


if TYPE_CHECKING:
    from jerico.skills.validator import SkillLintIssue
