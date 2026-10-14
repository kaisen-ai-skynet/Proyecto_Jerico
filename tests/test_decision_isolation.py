"""Pruebas de T09: Aislamiento del Nivel 1 sin red (VJT-050, VJT-054, VJT-091)."""

import ast
from pathlib import Path

from jerico.decision.port import decidir


def test_no_network_imports_in_decision_package():
    """Ningún módulo de jerico.decision importa módulos o clientes de red en F0 (VJT-054)."""
    decision_dir = Path(__file__).parent.parent / "src" / "jerico" / "decision"
    prohibited_modules = {
        "urllib",
        "requests",
        "httpx",
        "http.client",
        "aiohttp",
        "socket",
        "asyncio.streams",
    }

    for py_file in decision_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prohibited in prohibited_modules:
                        assert not alias.name.startswith(prohibited), (
                            f"Importación de red prohibida '{alias.name}' en {py_file.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                for prohibited in prohibited_modules:
                    assert not module_name.startswith(prohibited), (
                        f"Importación de red prohibida '{module_name}' en {py_file.name}"
                    )


def test_decision_package_adds_no_dependencies():
    """jerico.decision solo importa la biblioteca estándar o el propio jerico (VJT-091).

    No depende del historial de git: el CI clona sin historia.
    """
    import sys

    decision_dir = Path(__file__).parent.parent / "src" / "jerico" / "decision"
    foreign: set[str] = set()
    for py_file in decision_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots = [node.module.split(".")[0]]
            else:
                continue
            foreign.update(r for r in roots if r != "jerico" and r not in sys.stdlib_module_names)
    assert not foreign, f"jerico.decision importa dependencias externas: {sorted(foreign)}"


def test_no_network_calls_in_apagado_and_sombra(tmp_path: Path):
    """En modos apagado y sombra no hay interacción externa de red (VJT-054)."""
    # Ejecutamos llamadas sobre varios tipos en modos apagado y sombra
    d_apagado = decidir(
        "nivel_turno",
        {"tipo_mensaje": "simple", "longitud_rango": "corta"},
    )
    assert d_apagado.source == "base"

    d_sombra = decidir(
        "seguimiento_lead",
        {
            "dias_sin_contacto": "0",
            "paso_cadencia": "0",
            "estado_lead": "nuevo",
            "intentos_fallidos": "0",
        },
    )
    assert d_sombra.source == "base"


def test_typesafe_url_not_present_in_f0_source():
    """La dirección del servicio TypeSafe no aparece en los módulos de F0 (VJT-050)."""
    decision_dir = Path(__file__).parent.parent / "src" / "jerico" / "decision"
    for py_file in decision_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8").lower()
        assert "api.typesafe" not in content, f"URL de TypeSafe encontrada en {py_file.name}"
        assert "typesafe.ai" not in content, f"URL de TypeSafe encontrada en {py_file.name}"
