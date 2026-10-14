"""Pruebas unitarias para el repositorio del catálogo de precios (Spec 006, C2)."""

from pathlib import Path

import pytest
import yaml

from jerico.catalogo.modelo import CatalogoPrecios
from jerico.catalogo.repositorio import (
    CatalogoInmutableError,
    CatalogoSinVersionVigenteError,
    RepositorioCatalogo,
    VersionCatalogoNoEncontradaError,
)


def _crear_catalogo_ejemplo(version: str = "0.1.0", estado: str = "borrador") -> dict[str, object]:
    return {
        "version": version,
        "estado": estado,
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
                "id": "unico",
                "nombre": "Único",
                "precio_propuesta": 4320000,
                "precio_formula": 6123123,
                "margen_objetivo_pct": 20,
            }
        ],
    }


def test_sin_archivo_vigente_lanza_error(tmp_path: Path) -> None:
    repo = RepositorioCatalogo(tmp_path)
    with pytest.raises(CatalogoSinVersionVigenteError, match="catálogo sin versión vigente"):
        repo.obtener_version_vigente()

    with pytest.raises(CatalogoSinVersionVigenteError, match="catálogo sin versión vigente"):
        repo.cargar_vigente()


def test_archivo_vigente_vacio_lanza_error(tmp_path: Path) -> None:
    (tmp_path / "VIGENTE").write_text("   \n", encoding="utf-8")
    repo = RepositorioCatalogo(tmp_path)
    with pytest.raises(CatalogoSinVersionVigenteError, match="catálogo sin versión vigente"):
        repo.obtener_version_vigente()


def test_cargar_version_inexistente_lanza_error(tmp_path: Path) -> None:
    repo = RepositorioCatalogo(tmp_path)
    with pytest.raises(VersionCatalogoNoEncontradaError, match="no existe la versión '9.9.9'"):
        repo.cargar_version("9.9.9")


def test_cargar_version_exitosa(tmp_path: Path) -> None:
    datos = _crear_catalogo_ejemplo("0.1.0", "borrador")
    (tmp_path / "0.1.0.yaml").write_text(yaml.safe_dump(datos), encoding="utf-8")

    repo = RepositorioCatalogo(tmp_path)
    cat = repo.cargar_version("0.1.0")
    assert cat.version == "0.1.0"
    assert cat.estado == "borrador"
    assert cat.planes[0].precio_propuesta == 4320000


def test_resolucion_vigente_carga_catalogo(tmp_path: Path) -> None:
    datos = _crear_catalogo_ejemplo("1.0.0", "vigente")
    (tmp_path / "1.0.0.yaml").write_text(yaml.safe_dump(datos), encoding="utf-8")
    (tmp_path / "VIGENTE").write_text("1.0.0\n", encoding="utf-8")

    repo = RepositorioCatalogo(tmp_path)
    assert repo.obtener_version_vigente() == "1.0.0"
    cat = repo.cargar_vigente()
    assert cat.version == "1.0.0"
    assert cat.estado == "vigente"


def test_inmutabilidad_version_vigente_no_se_reescribe(tmp_path: Path) -> None:
    datos_vigentes = _crear_catalogo_ejemplo("1.0.0", "vigente")
    (tmp_path / "1.0.0.yaml").write_text(yaml.safe_dump(datos_vigentes), encoding="utf-8")

    repo = RepositorioCatalogo(tmp_path)
    nuevo_intento = CatalogoPrecios.model_validate(_crear_catalogo_ejemplo("1.0.0", "vigente"))

    with pytest.raises(CatalogoInmutableError, match="inmutable"):
        repo.guardar_version(nuevo_intento)


def test_inmutabilidad_version_retirada_no_se_reescribe(tmp_path: Path) -> None:
    datos_retirados = _crear_catalogo_ejemplo("0.9.0", "retirada")
    (tmp_path / "0.9.0.yaml").write_text(yaml.safe_dump(datos_retirados), encoding="utf-8")

    repo = RepositorioCatalogo(tmp_path)
    nuevo_intento = CatalogoPrecios.model_validate(_crear_catalogo_ejemplo("0.9.0", "retirada"))

    with pytest.raises(CatalogoInmutableError, match="inmutable"):
        repo.guardar_version(nuevo_intento)


def test_guardar_version_borrador_y_marcar_vigente(tmp_path: Path) -> None:
    repo = RepositorioCatalogo(tmp_path)
    cat = CatalogoPrecios.model_validate(_crear_catalogo_ejemplo("0.2.0", "borrador"))

    archivo = repo.guardar_version(cat)
    assert archivo.is_file()
    assert (tmp_path / "0.2.0.yaml").exists()

    repo.marcar_vigente("0.2.0")
    assert repo.obtener_version_vigente() == "0.2.0"
    assert (tmp_path / "VIGENTE").read_text(encoding="utf-8").strip() == "0.2.0"


def test_repositorio_por_defecto_encuentra_catalogo_del_repo() -> None:
    repo = RepositorioCatalogo()
    cat = repo.cargar_version("0.1.0")
    assert cat.version == "0.1.0"
    assert cat.estado == "borrador"
    # En el repo actual VIGENTE no debe existir aún (o no estar marcado)
    with pytest.raises(CatalogoSinVersionVigenteError):
        repo.cargar_vigente()
