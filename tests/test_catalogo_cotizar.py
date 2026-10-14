"""Pruebas unitarias para el motor determinista de cotización (Spec 006, C3).

Verifica cálculo en Decimal de mensualidad (10 %), total anual,
manejo de planes inexistentes y generación del contrato Cotizacion.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from jerico.catalogo.cotizar import (
    PlanNoEncontradoError,
    calcular_mensualidad,
    calcular_total_anual,
    cotizar_plan,
)
from jerico.catalogo.modelo import CatalogoPrecios
from jerico.schemas import Cotizacion


def _catalogo_prueba(estado: str = "borrador") -> CatalogoPrecios:
    return CatalogoPrecios.model_validate(
        {
            "version": "0.1.0",
            "estado": estado,
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
                },
                {
                    "id": "unico",
                    "nombre": "Único",
                    "precio_propuesta": 4320000,
                    "precio_formula": 6123123,
                    "margen_objetivo_pct": 20.0,
                },
                {
                    "id": "premium",
                    "nombre": "Premium",
                    "precio_propuesta": 5520000,
                    "precio_formula": 6997855,
                    "margen_objetivo_pct": 30.0,
                },
            ],
            "advertencias": ["Aviso de prueba"],
        }
    )


def test_calcular_mensualidad_decimal() -> None:
    cat = _catalogo_prueba()
    # 10 % de 3.220.000 = 322.000
    assert calcular_mensualidad(cat, "estandar") == Decimal("322000")
    # 10 % de 4.320.000 = 432.000
    assert calcular_mensualidad(cat, "unico") == Decimal("432000")
    # 10 % de 5.520.000 = 552.000
    assert calcular_mensualidad(cat, "premium") == Decimal("552000")


def test_calcular_total_anual_decimal() -> None:
    cat = _catalogo_prueba()
    # Total 12 meses: 3.220.000 + 12 * 322.000 = 7.084.000
    total_12 = calcular_total_anual(cat, "estandar", meses=12)
    assert total_12 == Decimal("7084000")

    # Total 0 meses (solo implementación): 3.220.000
    total_0 = calcular_total_anual(cat, "estandar", meses=0)
    assert total_0 == Decimal("3220000")


def test_plan_inexistente_lanza_error_con_lista() -> None:
    cat = _catalogo_prueba()
    with pytest.raises(PlanNoEncontradoError) as exc_info:
        cotizar_plan(cat, "no_existe")

    err = exc_info.value
    assert err.plan_id == "no_existe"
    assert err.planes_validos == ["estandar", "unico", "premium"]
    msg = str(err)
    assert "no_existe" in msg
    assert "estandar" in msg
    assert "unico" in msg
    assert "premium" in msg


def test_cotizar_plan_produce_cotizacion_schema() -> None:
    cat = _catalogo_prueba(estado="vigente")
    fecha_validez = date(2026, 11, 30)
    cotizacion = cotizar_plan(
        cat,
        "estandar",
        meses_mensualidad=12,
        valid_until=fecha_validez,
    )

    assert isinstance(cotizacion, Cotizacion)
    assert cotizacion.currency == "COP"
    assert cotizacion.valid_until == fecha_validez
    assert len(cotizacion.lines) == 2

    l1 = cotizacion.lines[0]
    assert "Estándar" in l1.description
    assert l1.quantity == 1
    assert l1.unit_price == 3220000

    l2 = cotizacion.lines[1]
    assert "mensual" in l2.description.lower()
    assert l2.quantity == 12
    assert l2.unit_price == 322000

    assert cotizacion.total == 7084000


def test_cotizar_plan_meses_cero_solo_incluye_implementacion() -> None:
    cat = _catalogo_prueba(estado="vigente")
    cotizacion = cotizar_plan(cat, "unico", meses_mensualidad=0)
    assert len(cotizacion.lines) == 1
    assert cotizacion.lines[0].unit_price == 4320000
    assert cotizacion.total == 4320000


def test_cotizar_plan_marca_borrador_en_condiciones_cuando_no_vigente() -> None:
    cat_borrador = _catalogo_prueba(estado="borrador")
    cot = cotizar_plan(cat_borrador, "premium", meses_mensualidad=12)
    assert cot.special_conditions is not None
    assert "BORRADOR — no cotizar" in cot.special_conditions


def test_cotizar_plan_meses_negativos_invalido() -> None:
    cat = _catalogo_prueba()
    with pytest.raises(ValueError, match="meses_mensualidad no puede ser negativo"):
        cotizar_plan(cat, "estandar", meses_mensualidad=-1)


def test_cotizar_con_catalogo_real_0_1_0() -> None:
    ruta_real = Path(__file__).resolve().parents[1] / "catalogo" / "precios" / "0.1.0.yaml"
    with open(ruta_real, encoding="utf-8") as f:
        datos: dict[str, Any] = yaml.safe_load(f)
    cat = CatalogoPrecios.model_validate(datos)

    cot = cotizar_plan(cat, "estandar", meses_mensualidad=12)
    assert cot.total == 7084000
    assert cot.special_conditions is not None
    assert "BORRADOR — no cotizar" in cot.special_conditions
