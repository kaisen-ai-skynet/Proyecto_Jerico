"""Lógica de conjunto permitido y piso de exigencia por clase (spec 007, VJT-001 a 008, 024)."""

from typing import Any

from jerico.decision.policy import PolicyKind
from jerico.decision.state import DataClass

_HIERARCHY = {
    DataClass.CON_DATOS_PERSONALES: 3,
    DataClass.SEUDONIMIZADO_VERIFICADO: 2,
    DataClass.SIN_DATOS_PERSONALES: 1,
}


def _extract_data_class(item: Any) -> DataClass:
    """Extrae y normaliza la DataClass, aplicando la verificación de texto libre (VJT-023)."""
    if hasattr(item, "clase_datos"):
        # Si tiene marca explícita sin_texto_libre y es False, degrada a CON_DATOS_PERSONALES
        sin_texto = getattr(item, "sin_texto_libre", None)
        if sin_texto is False:
            return DataClass.CON_DATOS_PERSONALES
        item = item.clase_datos

    if isinstance(item, DataClass):
        return item

    if isinstance(item, str):
        for dc in DataClass:
            if dc.value == item:
                return dc

    return DataClass.CON_DATOS_PERSONALES


def mas_restrictiva(clase1: Any, clase2: Any) -> DataClass:
    """Devuelve la clase de datos más restrictiva entre dos fuentes (VJT-022)."""
    dc1 = _extract_data_class(clase1)
    dc2 = _extract_data_class(clase2)

    return dc1 if _HIERARCHY[dc1] >= _HIERARCHY[dc2] else dc2


def allowed_options(
    spec: PolicyKind, ctx: Any = None, data_class: DataClass | str | None = None
) -> list[str]:
    """Calcula el conjunto de opciones permitidas según política, contexto y privacidad."""
    dc = mas_restrictiva(data_class or spec.clase_datos, ctx) if ctx else _extract_data_class(
        data_class or spec.clase_datos
    )

    if spec.clase == "A" and not spec.asesor:
        return [spec.base]

    opciones = list(spec.opciones)

    # Filtro por clase de datos (VJT-024)
    if dc == DataClass.CON_DATOS_PERSONALES:
        # Nunca admite deepseek-chat
        opciones = [op for op in opciones if op != "deepseek-chat"]
        if spec.modelos_aptos_datos_personales:
            opciones = [op for op in opciones if op in spec.modelos_aptos_datos_personales]

    if not opciones or spec.base not in opciones:
        return [spec.base]

    return opciones


def apply_floor(
    clase: str, orden: list[str] | None, base: str, jev_option: str, allowed: list[str]
) -> tuple[str, str]:
    """Aplica la función de piso por clase sobre la opción propuesta por Jev."""
    if jev_option not in allowed:
        return base, "fuera_de_permitidas"

    if clase == "A":
        return base, "clase_a_fija"

    if clase == "B":
        if not orden or jev_option not in orden or base not in orden:
            return base, "sin_orden"
        if orden.index(jev_option) >= orden.index(base):
            return jev_option, "piso_cumplido"
        return base, "piso_exigencia"

    if clase == "C":
        return jev_option, "enrutado_valido"

    return base, "clase_desconocida"
