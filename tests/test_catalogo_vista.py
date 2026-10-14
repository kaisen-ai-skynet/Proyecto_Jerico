"""Pruebas unitarias para las vistas por rol del catálogo (Spec 006, C4).

Verifica que el rol comercial jamás vea costo_directo, margen, honorarios,
caja ni cap table (R7, R8, R9), y que el CTO acceda a la estructura completa.
"""

import json
from pathlib import Path
from typing import Any

import yaml

from jerico.catalogo.modelo import CatalogoPrecios
from jerico.catalogo.vista import (
    PlanComercial,
    PlanCTO,
    VistaComercial,
    VistaCTO,
    obtener_vista,
)


def _catalogo_completo(estado: str = "borrador") -> CatalogoPrecios:
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
                    "interno": {
                        "margen_real_pct": -52.1,
                    },
                },
                {
                    "id": "premium",
                    "nombre": "Premium",
                    "precio_propuesta": 5520000,
                    "precio_formula": 6997855,
                    "margen_objetivo_pct": 30.0,
                    "interno": {
                        "margen_real_pct": 11.3,
                    },
                },
            ],
            "interno": {
                "costo_directo_por_implementacion": 4898499,
                "capacidad_implementaciones_anio": 12,
            },
            "advertencias": [
                (
                    "Planes Estándar y Único se proponen por debajo del costo directo "
                    "(margen real −52 % y −13 %)."
                ),
                "El costo por implementación supone 12 implementaciones al año.",
                "Tarifas ICA y retenciones sujetas a confirmación contable.",
            ],
        }
    )


def test_vista_comercial_no_contiene_campos_financieros_sensibles() -> None:
    cat = _catalogo_completo(estado="vigente")
    vista = obtener_vista(cat, rol="comercial")

    assert isinstance(vista, VistaComercial)
    assert len(vista.planes) == 2
    for p in vista.planes:
        assert isinstance(p, PlanComercial)
        assert p.precio_propuesta > 0
        assert p.mensualidad > 0
        # No debe haber campos sensibles como atributos
        assert not hasattr(p, "costo_directo")
        assert not hasattr(p, "margen_real_pct")
        assert not hasattr(p, "margen_objetivo_pct")
        assert not hasattr(p, "precio_formula")
        assert not hasattr(p, "interno")

    # Inspección estricta de la serialización completa (JSON)
    dump_dict = vista.model_dump()
    json_str = json.dumps(dump_dict).lower()

    assert "costo_directo" not in json_str
    assert "costo_directo_por_implementacion" not in json_str
    assert "margen" not in json_str
    assert "margen_real_pct" not in json_str
    assert "margen_objetivo_pct" not in json_str
    assert "precio_formula" not in json_str
    assert "capacidad_implementaciones" not in json_str
    assert "honorarios" not in json_str
    assert "caja" not in json_str
    assert "cap_table" not in json_str


def test_vista_comercial_filtra_advertencias_internas() -> None:
    cat = _catalogo_completo()
    vista = obtener_vista(cat, rol="comercial")

    # Solo debe quedar la advertencia comercial (ICA / retenciones)
    # y ninguna que hable de costo directo, margen o capacidad
    for adv in vista.advertencias:
        adv_lower = adv.lower()
        assert "costo directo" not in adv_lower
        assert "margen" not in adv_lower
        assert "capacidad" not in adv_lower
        assert "honorarios" not in adv_lower
        assert "caja" not in adv_lower

    assert any("ica" in adv.lower() for adv in vista.advertencias)


def test_vista_cto_contiene_estructura_completa() -> None:
    cat = _catalogo_completo(estado="vigente")
    vista = obtener_vista(cat, rol="cto")

    assert isinstance(vista, VistaCTO)
    assert vista.interno is not None
    assert vista.interno.costo_directo_por_implementacion == 4898499
    assert vista.interno.capacidad_implementaciones_anio == 12

    p0 = vista.planes[0]
    assert isinstance(p0, PlanCTO)
    assert p0.precio_formula == 5762939
    assert p0.margen_objetivo_pct == 15.0
    assert p0.interno is not None
    assert p0.interno.margen_real_pct == -52.1

    # El CTO ve todas las advertencias originales
    assert len(vista.advertencias) == 3


def test_vista_marca_borrador_cuando_estado_no_es_vigente() -> None:
    cat_borrador = _catalogo_completo(estado="borrador")
    vista_com = obtener_vista(cat_borrador, rol="comercial")
    vista_cto = obtener_vista(cat_borrador, rol="cto")

    assert vista_com.aviso == "BORRADOR — no cotizar"
    assert vista_cto.aviso == "BORRADOR — no cotizar"

    cat_vigente = _catalogo_completo(estado="vigente")
    vista_vigente = obtener_vista(cat_vigente, rol="comercial")
    assert vista_vigente.aviso is None


def test_vista_rol_por_defecto_o_desconocido_es_comercial() -> None:
    cat = _catalogo_completo(estado="vigente")
    # Rol desconocido o vacío debe aplicar principio de menor privilegio -> comercial
    vista_desconocido = obtener_vista(cat, rol="cualquiera")
    assert isinstance(vista_desconocido, VistaComercial)

    # Rol insensible a mayúsculas
    vista_cto_upper = obtener_vista(cat, rol="CTO")
    assert isinstance(vista_cto_upper, VistaCTO)


def test_vista_con_catalogo_real_0_1_0() -> None:
    ruta_real = Path(__file__).resolve().parents[1] / "catalogo" / "precios" / "0.1.0.yaml"
    with open(ruta_real, encoding="utf-8") as f:
        datos: dict[str, Any] = yaml.safe_load(f)
    cat = CatalogoPrecios.model_validate(datos)

    vista_com = obtener_vista(cat, rol="comercial")
    assert isinstance(vista_com, VistaComercial)
    assert vista_com.aviso == "BORRADOR — no cotizar"
    assert len(vista_com.planes) == 3

    dump_json = json.dumps(vista_com.model_dump()).lower()
    assert "costo_directo" not in dump_json
    assert "margen" not in dump_json

    vista_cto = obtener_vista(cat, rol="cto")
    assert isinstance(vista_cto, VistaCTO)
    assert vista_cto.interno is not None
    assert vista_cto.interno.costo_directo_por_implementacion == 4898499
