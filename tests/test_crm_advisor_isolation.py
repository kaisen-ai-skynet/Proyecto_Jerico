"""Pruebas de aislamiento estático para CRM-consejero (spec 007, VJC-001, VJC-030 a 032)."""

import ast
from pathlib import Path


def _get_imports(path: Path) -> set[str]:
    content = path.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(path))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                imports.add(name.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    return imports


def test_advisor_modules_no_network_imports() -> None:
    forbidden = {"requests", "httpx", "socket", "urllib", "flota_jev", "aiohttp"}
    modules_to_check = [
        Path("src/jerico/shadowlog/jsonl.py"),
        Path("src/jerico/crm/advisor_state.py"),
        Path("src/jerico/crm/advisor_queries.py"),
        Path("src/jerico/crm/advisor_snapshot.py"),
    ]

    for mod_path in modules_to_check:
        assert mod_path.exists(), f"El módulo {mod_path} debe existir"
        imports = _get_imports(mod_path)
        overlap = imports & forbidden
        assert not overlap, (
            f"El módulo {mod_path} importa módulos de red o flota prohibidos: {overlap}"
        )


def test_crm_and_shadowlog_no_forbidden_strings() -> None:
    # VJC-031: ningún módulo de CRM ni shadowlog debe contener estas cadenas
    forbidden_terms = ["flota_jev", "api.typesafe.ai", "jev-latest"]
    paths_to_scan = list(Path("src/jerico/shadowlog").glob("**/*.py")) + [
        Path("src/jerico/crm/advisor_state.py"),
        Path("src/jerico/crm/advisor_queries.py"),
        Path("src/jerico/crm/advisor_snapshot.py"),
    ]

    for p in paths_to_scan:
        content = p.read_text(encoding="utf-8").lower()
        for term in forbidden_terms:
            assert term not in content, f"Encontrado término prohibido '{term}' en {p}"
