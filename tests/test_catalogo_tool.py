"""Pruebas unitarias para la herramienta consultar_catalogo (Spec 006, C5).

Verifica que sea de solo lectura (R10), registre la versión en cada respuesta,
aplique la marca BORRADOR cuando no sea vigente (R12), aísle costos para comercial (R7),
permita visión integral para CTO (R8), cotice determinísticamente (R14)
y responda error explícito si no hay versión vigente (R3) o el plan no existe (R11).
"""

import json
from pathlib import Path
from typing import Any, cast

import pytest

from jerico.catalogo.modelo import CatalogoPrecios
from jerico.catalogo.repositorio import RepositorioCatalogo
from jerico.tools import REGISTRY, get_tool
from jerico.tools.catalogo import ConsultarCatalogoTool


@pytest.fixture
def repo_con_borrador(tmp_path: Path) -> RepositorioCatalogo:
    dir_precios = tmp_path / "precios"
    dir_precios.mkdir(parents=True)
    cat = CatalogoPrecios.model_validate(
        {
            "version": "0.1.0",
            "estado": "borrador",
            "moneda": "COP",
            "iva": "excluido",
            "vigencia_desde": None,
            "fuente": {
                "archivo": "Kaizen_Modelo_Financiero_5A_8.xlsx",
                "sha256": "02ac6b48ce1454aff6d5df5abe93c68a5eedc55694732cdcc84ff77b62a961dc",
                "extraido": "13/10/2026",
            },
            "regla_mensualidad": {
                "porcentaje_de_implementacion_por_mes": 10.0,
            },
            "planes": [
                {
                    "id": "estandar",
                    "nombre": "Estándar",
                    "precio_propuesta": 3220000,
                    "precio_formula": 5762939,
                    "margen_objetivo_pct": 15.0,
                    "interno": {
                        "margen_real_pct": -52.1,
                    },
                },
                {
                    "id": "unico",
                    "nombre": "Único",
                    "precio_propuesta": 4320000,
                    "precio_formula": 6123123,
                    "margen_objetivo_pct": 20.0,
                    "interno": {
                        "margen_real_pct": -13.4,
                    },
                },
            ],
            "interno": {
                "costo_directo_por_implementacion": 4898499,
                "capacidad_implementaciones_anio": 12,
            },
            "advertencias": [
                "Planes por debajo del costo directo (margen real −52 %).",
                "Tarifas ICA sujetas a confirmación contable.",
            ],
        }
    )
    repo = RepositorioCatalogo(dir_precios)
    repo.guardar_version(cat)
    return repo


@pytest.fixture
def repo_con_vigente(tmp_path: Path) -> RepositorioCatalogo:
    dir_precios = tmp_path / "precios_vigente"
    dir_precios.mkdir(parents=True)
    cat = CatalogoPrecios.model_validate(
        {
            "version": "1.0.0",
            "estado": "vigente",
            "moneda": "COP",
            "iva": "excluido",
            "vigencia_desde": "2026-10-14",
            "fuente": {
                "archivo": "Kaizen_Modelo_Financiero_5A_8.xlsx",
                "sha256": "02ac6b48ce1454aff6d5df5abe93c68a5eedc55694732cdcc84ff77b62a961dc",
                "extraido": "13/10/2026",
            },
            "regla_mensualidad": {
                "porcentaje_de_implementacion_por_mes": 10.0,
            },
            "planes": [
                {
                    "id": "estandar",
                    "nombre": "Estándar",
                    "precio_propuesta": 3220000,
                    "precio_formula": 5762939,
                    "margen_objetivo_pct": 15.0,
                }
            ],
            "advertencias": ["Aviso oficial"],
        }
    )
    repo = RepositorioCatalogo(dir_precios)
    repo.guardar_version(cat)
    repo.marcar_vigente("1.0.0")
    return repo


def test_tool_consultar_catalogo_propiedades_base() -> None:
    tool = ConsultarCatalogoTool()
    assert tool.name == "consultar_catalogo"
    assert tool.readonly is True
    # En el registro global de herramientas
    assert get_tool("consultar_catalogo") is not None
    assert "consultar_catalogo" in REGISTRY


def test_tool_sin_version_vigente_falla_r3(tmp_path: Path) -> None:
    dir_vacio = tmp_path / "precios_vacio"
    dir_vacio.mkdir()
    repo = RepositorioCatalogo(dir_vacio)
    tool = ConsultarCatalogoTool(repositorio=repo)

    res = tool.run()
    assert res["ok"] is False
    assert res["error"] == "CATALOGO_SIN_VERSION_VIGENTE"
    assert "catálogo sin versión vigente" in str(res.get("mensaje", "")).lower()
    assert res.get("version") is None


def test_tool_consulta_vista_comercial_aisla_costos_r7_r10_r12(
    repo_con_borrador: RepositorioCatalogo,
) -> None:
    tool = ConsultarCatalogoTool(repositorio=repo_con_borrador)
    # Al estar en borrador y no haber VIGENTE, pasamos version="0.1.0"
    res = tool.run(rol="comercial", version="0.1.0")

    assert res["ok"] is True
    assert res["tool"] == "consultar_catalogo"
    assert res["version"] == "0.1.0"
    assert res["estado"] == "borrador"
    # R12: marca obligatoria de borrador
    assert res["aviso"] == "BORRADOR — no cotizar"

    vista = cast(dict[str, Any], res["vista"])
    assert isinstance(vista, dict)
    assert vista["rol"] == "comercial"
    assert len(vista["planes"]) == 2

    # Verificación estricta de ausencia de datos financieros internos (R7)
    json_vista = json.dumps(vista).lower()
    assert "costo_directo" not in json_vista
    assert "costo_directo_por_implementacion" not in json_vista
    assert "margen" not in json_vista
    assert "margen_real_pct" not in json_vista
    assert "margen_objetivo_pct" not in json_vista
    assert "precio_formula" not in json_vista
    assert "capacidad" not in json_vista


def test_tool_consulta_vista_cto_incluye_estructura_completa_r8(
    repo_con_borrador: RepositorioCatalogo,
) -> None:
    tool = ConsultarCatalogoTool(repositorio=repo_con_borrador)
    res = tool.run(rol="cto", version="0.1.0")

    assert res["ok"] is True
    assert res["version"] == "0.1.0"
    vista = cast(dict[str, Any], res["vista"])
    assert vista["rol"] == "cto"
    assert vista["interno"]["costo_directo_por_implementacion"] == 4898499

    p0 = vista["planes"][0]
    assert p0["precio_formula"] == 5762939
    assert p0["margen_objetivo_pct"] == 15.0
    assert p0["interno"]["margen_real_pct"] == -52.1


def test_tool_cotizar_plan_exitoso_r14(
    repo_con_vigente: RepositorioCatalogo,
) -> None:
    tool = ConsultarCatalogoTool(repositorio=repo_con_vigente)
    # Al tener VIGENTE configurada, no requiere especificar version
    res = tool.run(plan_id="estandar", meses_mensualidad=12)

    assert res["ok"] is True
    assert res["version"] == "1.0.0"
    assert res["estado"] == "vigente"
    assert res["aviso"] is None

    cot = cast(dict[str, Any], res["cotizacion"])
    assert cot["currency"] == "COP"
    assert len(cot["lines"]) == 2
    assert cot["total"] == 7084000
    assert cot["lines"][0]["unit_price"] == 3220000
    assert cot["lines"][1]["unit_price"] == 322000
    assert cot["lines"][1]["quantity"] == 12


def test_tool_cotizar_plan_en_borrador_incluye_marca_r12(
    repo_con_borrador: RepositorioCatalogo,
) -> None:
    tool = ConsultarCatalogoTool(repositorio=repo_con_borrador)
    res = tool.run(plan_id="estandar", version="0.1.0")

    assert res["ok"] is True
    assert res["version"] == "0.1.0"
    assert res["aviso"] == "BORRADOR — no cotizar"

    cot = cast(dict[str, Any], res["cotizacion"])
    assert "BORRADOR — no cotizar" in cot["special_conditions"]


def test_tool_cotizar_plan_inexistente_falla_con_lista_r11(
    repo_con_vigente: RepositorioCatalogo,
) -> None:
    tool = ConsultarCatalogoTool(repo_con_vigente)
    res = tool.run(plan_id="plan_invalido")

    assert res["ok"] is False
    assert res["error"] == "PLAN_NO_ENCONTRADO"
    assert res["plan_solicitado"] == "plan_invalido"
    planes_validos = cast(list[str], res.get("planes_validos", []))
    assert "estandar" in planes_validos
    assert "plan_invalido" in str(res.get("mensaje", ""))


def test_tool_version_inexistente_falla(
    repo_con_borrador: RepositorioCatalogo,
) -> None:
    tool = ConsultarCatalogoTool(repositorio=repo_con_borrador)
    res = tool.run(version="9.9.9")

    assert res["ok"] is False
    assert res["error"] == "VERSION_NO_ENCONTRADA"
    assert "9.9.9" in str(res.get("mensaje", ""))


def test_tool_con_catalogo_real_en_disco() -> None:
    # El repo real de Proyecto Jericó tiene catalogo/precios/0.1.0.yaml
    tool = ConsultarCatalogoTool()
    res = tool.run(version="0.1.0", rol="comercial")

    assert res["ok"] is True
    assert res["version"] == "0.1.0"
    assert res["estado"] == "borrador"
    assert res["aviso"] == "BORRADOR — no cotizar"
    vista = cast(dict[str, Any], res["vista"])
    assert len(vista["planes"]) == 3
