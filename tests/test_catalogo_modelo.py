"""Pruebas unitarias para el modelo Pydantic del catálogo de precios (Spec 006, C1)."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from jerico.catalogo.modelo import CatalogoPrecios, ReglaMensualidad


def _catalogo_valido_dict() -> dict[str, Any]:
    return {
        "version": "0.1.0",
        "estado": "borrador",
        "moneda": "COP",
        "iva": "excluido",
        "vigencia_desde": None,
        "fuente": {
            "archivo": "Kaizen_Modelo_Financiero_5A_8.xlsx",
            "sha256": "02ac6b48ce1454aff6d5df5abe93c68a5eedc55694732cdcc84ff77b62a961dc",
            "extraido": "13/10/2026",
            "estado_modelo": "en pausa por decisión del CTO (13/10/2026)",
        },
        "regla_mensualidad": {
            "porcentaje_de_implementacion_por_mes": 10,
        },
        "planes": [
            {
                "id": "estandar",
                "nombre": "Estándar",
                "precio_propuesta": 3220000,
                "precio_formula": 5762939,
                "margen_objetivo_pct": 15,
                "interno": {"margen_real_pct": -52.1},
            },
            {
                "id": "unico",
                "nombre": "Único",
                "precio_propuesta": 4320000,
                "precio_formula": 6123123,
                "margen_objetivo_pct": 20,
                "interno": {"margen_real_pct": -13.4},
            },
        ],
        "interno": {
            "costo_directo_por_implementacion": 4898499,
            "capacidad_implementaciones_anio": 12,
        },
        "advertencias": [
            "Planes por debajo del costo directo.",
        ],
    }


def test_catalogo_valido_carga_correctamente() -> None:
    data = _catalogo_valido_dict()
    cat = CatalogoPrecios.model_validate(data)
    assert cat.version == "0.1.0"
    assert cat.estado == "borrador"
    assert cat.moneda == "COP"
    assert len(cat.planes) == 2
    assert cat.planes[0].id == "estandar"
    assert cat.planes[0].precio_propuesta == 3220000


def test_catalogo_real_0_1_0_valida() -> None:
    ruta_real = Path(__file__).resolve().parents[1] / "catalogo" / "precios" / "0.1.0.yaml"
    assert ruta_real.is_file(), f"No existe {ruta_real}"
    with open(ruta_real, encoding="utf-8") as f:
        datos = yaml.safe_load(f)
    cat = CatalogoPrecios.model_validate(datos)
    assert cat.version == "0.1.0"
    assert cat.estado == "borrador"
    assert len(cat.planes) == 3
    ids = [p.id for p in cat.planes]
    assert ids == ["estandar", "unico", "premium"]


def test_rechaza_version_invalida_no_semver() -> None:
    data = _catalogo_valido_dict()
    data["version"] = "1.0"  # falta patch
    with pytest.raises(ValidationError, match="semver"):
        CatalogoPrecios.model_validate(data)

    data["version"] = "v0.1.0"  # prefijo v no permitido
    with pytest.raises(ValidationError, match="semver"):
        CatalogoPrecios.model_validate(data)


def test_rechaza_estado_invalido() -> None:
    data = _catalogo_valido_dict()
    data["estado"] = "activo"
    with pytest.raises(ValidationError):
        CatalogoPrecios.model_validate(data)


def test_rechaza_precio_negativo() -> None:
    data = _catalogo_valido_dict()
    data["planes"][0]["precio_propuesta"] = -100
    with pytest.raises(ValidationError):
        CatalogoPrecios.model_validate(data)

    data = _catalogo_valido_dict()
    data["planes"][1]["precio_formula"] = -500
    with pytest.raises(ValidationError):
        CatalogoPrecios.model_validate(data)


def test_rechaza_planes_duplicados() -> None:
    data = _catalogo_valido_dict()
    # Mismo id en dos planes
    data["planes"].append(
        {
            "id": "estandar",
            "nombre": "Otro Estándar",
            "precio_propuesta": 4000000,
            "precio_formula": 5000000,
            "margen_objetivo_pct": 20,
        }
    )
    with pytest.raises(ValidationError, match="duplicado"):
        CatalogoPrecios.model_validate(data)


def test_rechaza_texto_con_nombres_de_personas_r9() -> None:
    data = _catalogo_valido_dict()
    data["advertencias"].append("Revisado por Santiago González")
    with pytest.raises(ValidationError, match="persona|prohibido|privacidad"):
        CatalogoPrecios.model_validate(data)

    data2 = _catalogo_valido_dict()
    data2["planes"][0]["nombre"] = "Plan de Esteban"
    with pytest.raises(ValidationError, match="persona|prohibido|privacidad"):
        CatalogoPrecios.model_validate(data2)


def test_rechaza_moneda_no_cop() -> None:
    data = _catalogo_valido_dict()
    data["moneda"] = "USD"
    with pytest.raises(ValidationError, match="COP"):
        CatalogoPrecios.model_validate(data)


def test_rechaza_regla_mensualidad_invalida() -> None:
    with pytest.raises(ValidationError):
        ReglaMensualidad(porcentaje_de_implementacion_por_mes=0)

    with pytest.raises(ValidationError):
        ReglaMensualidad(porcentaje_de_implementacion_por_mes=150)
