import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from jerico.skills.loader import parse_skill
from jerico.tools import REGISTRY


@dataclass(frozen=True)
class SkillLintIssue:
    code: str
    message: str


def validate_skill_manifest(
    path: Path, native_tools: set[str] | None = None
) -> list[SkillLintIssue]:
    tools = native_tools if native_tools is not None else set(REGISTRY)
    try:
        skill = parse_skill(path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return [SkillLintIssue("INVALID_MANIFEST", str(exc))]
    issues = []
    if len(skill.description) > 60:
        issues.append(SkillLintIssue("DESCRIPTION_TOO_LONG", "description debe ser ≤60 caracteres"))
    if not skill.platforms or not set(skill.platforms) <= {"linux", "macos", "windows"}:
        issues.append(SkillLintIssue("PLATFORMS_REQUIRED", "declara plataformas compatibles"))
    references = set(skill.tools) | set(re.findall(r"tool:([a-zA-Z0-9_]+)", skill.body))
    for name in sorted(references - tools):
        issues.append(SkillLintIssue("NON_NATIVE_TOOL", f"herramienta no nativa: {name}"))
    if re.search(r"(?:/Users/|/home/|[A-Z]:\\Users\\)", skill.body):
        issues.append(SkillLintIssue("NON_PORTABLE_PATH", "no usar rutas absolutas del autor"))
    return issues
