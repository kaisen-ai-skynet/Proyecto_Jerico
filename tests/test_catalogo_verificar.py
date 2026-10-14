"""Pruebas para el verificador de catálogo contra el Excel y SHA-256 (Spec 006, C6).

Verifica:
1. Comprobación del hash SHA-256 del archivo Excel (R6).
2. Detección de discrepancias en cifras de precios y costos contra el modelo (R6).
3. Verificación de las advertencias obligatorias del modelo financiero (R13).
4. Ejecución del script CLI scripts/verificar_catalogo.py con catálogo 0.1.0 real.
"""

from hashlib import sha256
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from jerico.catalogo.verificador import (
    SHA256_MODELO_FINANCIERO_CANONICO,
    ResultadoVerificacion,
    verificar_catalogo,
)


@pytest.fixture
def catalogo_valido_dict() -> dict:
    adv1 = (
        "Planes Estándar y Único se proponen por debajo del costo directo "
        "(margen real −52 % y −13 %)."
    )
    adv2 = (
        "El costo por implementación supone 12 implementaciones al año; "
        "si la capacidad real es otra, cambia."
    )
    adv3 = (
        "Modelo sin churn (0 %); ICA 'CONFIRMAR con contador'; "
        "tarifas RST por validar con el contador."
    )
    return {
        "version": "0.1.0",
        "estado": "borrador",
        "moneda": "COP",
        "iva": "excluido",
        "vigencia_desde": None,
        "fuente": {
            "archivo": "Kaizen_Modelo_Financiero_5A_8.xlsx",
            "sha256": SHA256_MODELO_FINANCIERO_CANONICO,
            "extraido": "13/10/2026",
            "estado_modelo": "en pausa por decisión del CTO (13/10/2026)",
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
        "advertencias": [adv1, adv2, adv3],
    }


def test_verificar_catalogo_valido_exitoso(tmp_path: Path, catalogo_valido_dict: dict) -> None:
    cat_file = tmp_path / "0.1.0.yaml"
    cat_file.write_text(yaml.safe_dump(catalogo_valido_dict), encoding="utf-8")

    res: ResultadoVerificacion = verificar_catalogo(cat_file)
    assert res.valido is True
    assert res.sha256_coincide is True
    assert res.valores_coinciden is True
    assert res.advertencias_validas is True
    assert len(res.discrepancias) == 0


def test_verificar_catalogo_sha256_discrepante(tmp_path: Path, catalogo_valido_dict: dict) -> None:
    catalogo_valido_dict["fuente"]["sha256"] = "f" * 64
    cat_file = tmp_path / "0.1.0.yaml"
    cat_file.write_text(yaml.safe_dump(catalogo_valido_dict), encoding="utf-8")

    res = verificar_catalogo(cat_file)
    assert res.valido is False
    assert res.sha256_coincide is False
    assert any("SHA-256" in d for d in res.discrepancias)


def test_verificar_catalogo_precio_discrepante(tmp_path: Path, catalogo_valido_dict: dict) -> None:
    catalogo_valido_dict["planes"][0]["precio_propuesta"] = 9999999
    cat_file = tmp_path / "0.1.0.yaml"
    cat_file.write_text(yaml.safe_dump(catalogo_valido_dict), encoding="utf-8")

    res = verificar_catalogo(cat_file)
    assert res.valido is False
    assert res.valores_coinciden is False
    assert any("precio_propuesta" in d and "estandar" in d for d in res.discrepancias)


def test_verificar_catalogo_falta_advertencia_r13(
    tmp_path: Path, catalogo_valido_dict: dict
) -> None:
    catalogo_valido_dict["advertencias"] = ["Solo una advertencia genérica."]
    cat_file = tmp_path / "0.1.0.yaml"
    cat_file.write_text(yaml.safe_dump(catalogo_valido_dict), encoding="utf-8")

    res = verificar_catalogo(cat_file)
    assert res.valido is False
    assert res.advertencias_validas is False
    assert any("advertencia" in d.lower() for d in res.discrepancias)


def test_verificar_catalogo_con_archivo_excel_real(
    tmp_path: Path, catalogo_valido_dict: dict
) -> None:
    # Crear archivo dummy simulando el Excel con hash exacto
    excel_dummy = tmp_path / "Kaizen_Modelo_Financiero_5A_8.xlsx"
    contenido = b"Kaizen Financial Model Fake Excel Content"
    calc_hash = sha256(contenido).hexdigest()
    excel_dummy.write_bytes(contenido)

    catalogo_valido_dict["fuente"]["sha256"] = calc_hash
    cat_file = tmp_path / "0.1.0.yaml"
    cat_file.write_text(yaml.safe_dump(catalogo_valido_dict), encoding="utf-8")

    res = verificar_catalogo(cat_file, excel_path=excel_dummy, solo_hash=True)
    assert res.valido is True
    assert res.sha256_coincide is True


def test_verificar_catalogo_con_openpyxl_mockeado(
    tmp_path: Path, catalogo_valido_dict: dict
) -> None:
    cat_file = tmp_path / "0.1.0.yaml"
    cat_file.write_text(yaml.safe_dump(catalogo_valido_dict), encoding="utf-8")

    wb_mock = MagicMock()
    ws_desglose = MagicMock()
    ws_intro = MagicMock()

    celdas_desglose = {
        "D5": 12,
        "D9": 4898498.5,
        "D13": 0.15,
        "E13": 5762939,
        "G13": 3220000,
        "H13": -0.521,
        "D14": 0.20,
        "E14": 6123123,
        "G14": 4320000,
        "H14": -0.134,
        "D15": 0.30,
        "E15": 6997855,
        "G15": 5520000,
        "H15": 0.113,
    }
    celdas_intro = {
        "C11": 0.10,
    }

    def desglose_getitem(key: str) -> MagicMock:
        c = MagicMock()
        c.value = celdas_desglose.get(key)
        return c

    def intro_getitem(key: str) -> MagicMock:
        c = MagicMock()
        c.value = celdas_intro.get(key)
        return c

    ws_desglose.__getitem__.side_effect = desglose_getitem
    ws_intro.__getitem__.side_effect = intro_getitem

    def wb_getitem(sheet_name: str) -> MagicMock:
        if sheet_name == "Desglose_Precios":
            return ws_desglose
        if sheet_name == "Introducción":
            return ws_intro
        raise KeyError(sheet_name)

    wb_mock.__getitem__.side_effect = wb_getitem
    wb_mock.sheetnames = ["Desglose_Precios", "Introducción"]

    openpyxl_mock = MagicMock()
    openpyxl_mock.load_workbook.return_value = wb_mock

    fake_excel = tmp_path / "test.xlsx"
    fake_excel.write_bytes(b"content")
    catalogo_valido_dict["fuente"]["sha256"] = sha256(b"content").hexdigest()
    cat_file.write_text(yaml.safe_dump(catalogo_valido_dict), encoding="utf-8")

    with patch.dict("sys.modules", {"openpyxl": openpyxl_mock}):
        res = verificar_catalogo(cat_file, excel_path=fake_excel, solo_hash=False)
        assert res.valido is True
        assert res.valores_coinciden is True


def test_verificar_catalogo_repo_real() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    cat_file = repo_root / "catalogo" / "precios" / "0.1.0.yaml"
    assert cat_file.exists(), f"Debe existir {cat_file}"

    res = verificar_catalogo(cat_file)
    assert res.valido is True, f"El catálogo real 0.1.0 debe ser válido: {res.discrepancias}"
    assert res.sha256_coincide is True
    assert res.valores_coinciden is True
    assert res.advertencias_validas is True
