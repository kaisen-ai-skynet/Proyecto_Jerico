from pathlib import Path

from jerico.skills.loader import SkillEngine, parse_skill
from jerico.skills.validator import validate_skill_manifest

SALES_SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills" / "ventas"
EXPECTED_SKILLS = {
    "calificar-lead",
    "redactar-seguimiento",
    "preparar-propuesta",
    "resumir-reunion",
}


def test_sales_skills_directory_and_files_exist():
    assert SALES_SKILLS_DIR.is_dir(), f"Directorio {SALES_SKILLS_DIR} no existe"
    for name in EXPECTED_SKILLS:
        skill_file = SALES_SKILLS_DIR / name / "SKILL.md"
        assert skill_file.is_file(), f"Falta archivo {skill_file}"


def test_sales_skills_audit_passes_linter_without_issues():
    for name in EXPECTED_SKILLS:
        skill_file = SALES_SKILLS_DIR / name / "SKILL.md"
        issues = validate_skill_manifest(skill_file)
        assert issues == [], f"Skill {name} tiene problemas de linter: {issues}"


def test_sales_skills_discovered_by_skill_engine():
    root_skills = SALES_SKILLS_DIR.parent
    discovered = SkillEngine().discover_skills(root_skills)
    for name in EXPECTED_SKILLS:
        assert name in discovered, f"Skill {name} no descubierta por SkillEngine"
        skill = discovered[name]
        assert skill.name == name
        assert len(skill.description) <= 60
        assert set(skill.platforms) == {"linux", "macos", "windows"}
        assert skill.status == "active"
        assert not skill.pinned


def test_sales_skill_preparar_propuesta_references_catalog_and_forbids_hallucination():
    skill_file = SALES_SKILLS_DIR / "preparar-propuesta" / "SKILL.md"
    skill = parse_skill(skill_file)
    body_lower = skill.body.lower()
    assert "catálogo" in body_lower or "catalogo" in body_lower
    assert "precio" in body_lower
    assert "10" in body_lower  # regla del 10% mensualidad
    assert "invent" in body_lower or "cálculo" in body_lower or "calculo" in body_lower


def test_sales_skill_calificar_lead_has_bant_and_privacy_safeguards():
    skill_file = SALES_SKILLS_DIR / "calificar-lead" / "SKILL.md"
    skill = parse_skill(skill_file)
    body_lower = skill.body.lower()
    assert "bant" in body_lower or ("presupuesto" in body_lower and "autoridad" in body_lower)
    assert "1581" in body_lower or "privacidad" in body_lower or "datos personales" in body_lower


def test_sales_skill_redactar_seguimiento_has_commercial_ethics_and_rules():
    skill_file = SALES_SKILLS_DIR / "redactar-seguimiento" / "SKILL.md"
    skill = parse_skill(skill_file)
    body_lower = skill.body.lower()
    assert "seguimiento" in body_lower
    assert "2300" in body_lower or "horario" in body_lower or "baja" in body_lower


def test_sales_skill_resumir_reunion_structures_agreements_and_actions():
    skill_file = SALES_SKILLS_DIR / "resumir-reunion" / "SKILL.md"
    skill = parse_skill(skill_file)
    body_lower = skill.body.lower()
    assert "acuerdo" in body_lower or "compromiso" in body_lower
    assert "próximo" in body_lower or "proximo" in body_lower or "paso" in body_lower
