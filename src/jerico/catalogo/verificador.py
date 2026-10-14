"""Verificador del catálogo contra el modelo financiero y SHA-256 (Spec 006, C6).

Cumple los requisitos:
- R6: Guarda la huella SHA-256 del Excel y verifica que los valores coincidan.
- R13: Registra y valida advertencias obligatorias (precios bajo costo, capacidad 12, churn/ICA).
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml

from jerico.catalogo.modelo import CatalogoPrecios

# Huella SHA-256 canónica del archivo Kaizen_Modelo_Financiero_5A_8.xlsx
SHA256_MODELO_FINANCIERO_CANONICO = (
    "02ac6b48ce1454aff6d5df5abe93c68a5eedc55694732cdcc84ff77b62a961dc"
)

# Valores canónicos extraídos del modelo financiero (Santiago Jaimes Beltrán / Desglose_Precios)
VALORES_CANONICOS_MODELO: dict[str, Any] = {
    "regla_mensualidad_pct": 10.0,
    "costo_directo_por_implementacion": 4898499,
    "capacidad_implementaciones_anio": 12,
    "planes": {
        "estandar": {
            "nombre": "Estándar",
            "precio_propuesta": 3220000,
            "precio_formula": 5762939,
            "margen_objetivo_pct": 15.0,
            "margen_real_pct": -52.1,
        },
        "unico": {
            "nombre": "Único",
            "precio_propuesta": 4320000,
            "precio_formula": 6123123,
            "margen_objetivo_pct": 20.0,
            "margen_real_pct": -13.4,
        },
        "premium": {
            "nombre": "Premium",
            "precio_propuesta": 5520000,
            "precio_formula": 6997855,
            "margen_objetivo_pct": 30.0,
            "margen_real_pct": 11.3,
        },
    },
}


@dataclass(frozen=True)
class ResultadoVerificacion:
    """Resultado del proceso de verificación del catálogo."""

    valido: bool
    sha256_coincide: bool
    valores_coinciden: bool
    advertencias_validas: bool
    discrepancias: list[str] = field(default_factory=list)
    detalles: dict[str, Any] = field(default_factory=dict)


def _calcular_sha256(archivo: Path) -> str:
    h = sha256()
    with open(archivo, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _validar_advertencias_r13(advertencias: list[str]) -> tuple[bool, list[str]]:
    """Valida la presencia de las advertencias obligatorias del modelo financiero (R13)."""
    discrepancias: list[str] = []
    t = " ".join(advertencias).lower()

    if not ("bajo el costo" in t or "debajo del costo" in t or "margen real" in t):
        discrepancias.append(
            "Falta advertencia R13: Estándar y Único se proponen bajo costo directo."
        )

    if not ("12 implementaciones" in t or "capacidad" in t):
        discrepancias.append(
            "Falta advertencia R13: costo por implementación asume capacidad de 12 al año."
        )

    if not (("churn" in t or "0 %" in t or "0%" in t) and "contador" in t):
        discrepancias.append(
            "Falta advertencia R13: modelo sin churn (0 %) e ICA/RST a confirmar con contador."
        )

    return len(discrepancias) == 0, discrepancias


def _extraer_valores_excel_openpyxl(excel_path: Path) -> dict[str, Any]:
    """Extrae las celdas clave del modelo financiero usando openpyxl."""
    import openpyxl  # type: ignore[import-untyped]

    wb = openpyxl.load_workbook(excel_path, data_only=True)
    ws_desglose = wb["Desglose_Precios"]
    ws_intro = wb["Introducción"]

    def _num(val: Any) -> float:
        if val is None:
            return 0.0
        return float(val)

    def _entero_cop(val: Any) -> int:
        if val is None:
            return 0
        return int(Decimal(str(val)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    pct_mensualidad = _num(ws_intro["C11"].value)
    if pct_mensualidad < 1.0:
        pct_mensualidad *= 100.0

    capacidad = int(_num(ws_desglose["D5"].value))
    costo_directo = _entero_cop(ws_desglose["D9"].value)

    filas = {
        "estandar": 13,
        "unico": 14,
        "premium": 15,
    }
    planes_excel: dict[str, dict[str, Any]] = {}
    for pid, fila in filas.items():
        m_obj = _num(ws_desglose[f"D{fila}"].value)
        if abs(m_obj) < 1.0:
            m_obj *= 100.0
        p_form = _entero_cop(ws_desglose[f"E{fila}"].value)
        p_prop = _entero_cop(ws_desglose[f"G{fila}"].value)
        m_real = _num(ws_desglose[f"H{fila}"].value)
        if abs(m_real) < 1.0:
            m_real *= 100.0

        planes_excel[pid] = {
            "precio_propuesta": p_prop,
            "precio_formula": p_form,
            "margen_objetivo_pct": round(m_obj, 1),
            "margen_real_pct": round(m_real, 1),
        }

    return {
        "regla_mensualidad_pct": round(pct_mensualidad, 1),
        "costo_directo_por_implementacion": costo_directo,
        "capacidad_implementaciones_anio": capacidad,
        "planes": planes_excel,
    }


def verificar_catalogo(
    catalogo_path: Path | str,
    excel_path: Path | str | None = None,
    solo_hash: bool = False,
) -> ResultadoVerificacion:
    """Verifica el catálogo YAML contra la fuente del modelo financiero (R6, R13)."""
    cat_p = Path(catalogo_path)
    if not cat_p.exists():
        return ResultadoVerificacion(
            valido=False,
            sha256_coincide=False,
            valores_coinciden=False,
            advertencias_validas=False,
            discrepancias=[f"El archivo de catálogo no existe: {cat_p}"],
        )

    with open(cat_p, encoding="utf-8") as f:
        datos = yaml.safe_load(f)

    catalogo = CatalogoPrecios.model_validate(datos)
    discrepancias: list[str] = []
    detalles: dict[str, Any] = {"version": catalogo.version, "estado": catalogo.estado}

    # 1. Comprobación SHA-256 (R6)
    sha256_coincide = True
    hash_en_catalogo = catalogo.fuente.sha256.lower()

    if excel_path is not None:
        exp_p = Path(excel_path)
        if exp_p.exists():
            hash_calculado = _calcular_sha256(exp_p).lower()
            detalles["excel_path"] = str(exp_p)
            detalles["sha256_calculado"] = hash_calculado
            if hash_calculado != hash_en_catalogo:
                sha256_coincide = False
                discrepancias.append(
                    f"Discrepancia SHA-256: cat={hash_en_catalogo} vs archivo={hash_calculado}."
                )
        else:
            discrepancias.append(f"El archivo Excel especificado no existe: {exp_p}")
            sha256_coincide = False
    else:
        if hash_en_catalogo != SHA256_MODELO_FINANCIERO_CANONICO.lower():
            sha256_coincide = False
            discrepancias.append(
                f"Discrepancia SHA-256: {hash_en_catalogo} != {SHA256_MODELO_FINANCIERO_CANONICO}."
            )

    # 2. Comprobación de valores de precios y costos (R6)
    valores_coinciden = True
    valores_referencia = VALORES_CANONICOS_MODELO

    if excel_path is not None and not solo_hash:
        try:
            valores_referencia = _extraer_valores_excel_openpyxl(Path(excel_path))
            detalles["fuente_valores"] = "excel_openpyxl"
        except Exception:
            valores_referencia = VALORES_CANONICOS_MODELO
            detalles["fuente_valores"] = "canonicos_fallback"
    else:
        detalles["fuente_valores"] = "canonicos"

    # Regla mensualidad
    pct_cat = catalogo.regla_mensualidad.porcentaje_de_implementacion_por_mes
    pct_ref = valores_referencia["regla_mensualidad_pct"]
    if abs(pct_cat - pct_ref) > 0.01:
        valores_coinciden = False
        discrepancias.append(
            f"Regla mensualidad discrepante: catálogo={pct_cat}% vs modelo={pct_ref}%."
        )

    # Sección interno
    if catalogo.interno:
        c_cat = catalogo.interno.costo_directo_por_implementacion
        c_ref = valores_referencia["costo_directo_por_implementacion"]
        if c_cat != c_ref:
            valores_coinciden = False
            discrepancias.append(f"Costo directo discrepante: catálogo={c_cat} vs modelo={c_ref}.")
        cap_cat = catalogo.interno.capacidad_implementaciones_anio
        cap_ref = valores_referencia["capacidad_implementaciones_anio"]
        if cap_cat != cap_ref:
            valores_coinciden = False
            discrepancias.append(
                f"Capacidad anual discrepante: catálogo={cap_cat} vs modelo={cap_ref}."
            )

    # Planes
    planes_ref = valores_referencia["planes"]
    planes_cat = {p.id: p for p in catalogo.planes}

    for pid, p_ref in planes_ref.items():
        if pid not in planes_cat:
            valores_coinciden = False
            discrepancias.append(f"Falta el plan obligatorio {pid} en el catálogo.")
            continue

        p_actual = planes_cat[pid]
        if p_actual.precio_propuesta != p_ref["precio_propuesta"]:
            valores_coinciden = False
            discrepancias.append(
                f"Plan {pid}: precio_propuesta {p_actual.precio_propuesta} != "
                f"{p_ref['precio_propuesta']}."
            )
        if p_actual.precio_formula != p_ref["precio_formula"]:
            valores_coinciden = False
            discrepancias.append(
                f"Plan {pid}: precio_formula {p_actual.precio_formula} != "
                f"{p_ref['precio_formula']}."
            )
        if abs(p_actual.margen_objetivo_pct - p_ref["margen_objetivo_pct"]) > 0.1:
            valores_coinciden = False
            discrepancias.append(
                f"Plan {pid}: margen_obj {p_actual.margen_objetivo_pct}% != "
                f"{p_ref['margen_objetivo_pct']}%."
            )
        if (
            p_actual.interno
            and abs(p_actual.interno.margen_real_pct - p_ref["margen_real_pct"]) > 0.1
        ):
            valores_coinciden = False
            discrepancias.append(
                f"Plan {pid}: margen_real {p_actual.interno.margen_real_pct}% != "
                f"{p_ref['margen_real_pct']}%."
            )

    # 3. Comprobación de advertencias obligatorias (R13)
    advertencias_validas, disc_adv = _validar_advertencias_r13(catalogo.advertencias)
    if not advertencias_validas:
        discrepancias.extend(disc_adv)

    valido = sha256_coincide and valores_coinciden and advertencias_validas

    return ResultadoVerificacion(
        valido=valido,
        sha256_coincide=sha256_coincide,
        valores_coinciden=valores_coinciden,
        advertencias_validas=advertencias_validas,
        discrepancias=discrepancias,
        detalles=detalles,
    )
