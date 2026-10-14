"""Validación de estado y clases de datos para privacidad (spec 007, VJT-020 a VJT-025)."""

from enum import StrEnum
from typing import Any

from jerico.decision.policy import PolicyKind


class DataClass(StrEnum):
    """Clasificación de datos según su sensibilidad de privacidad (VJT-022)."""

    SIN_DATOS_PERSONALES = "sin_datos_personales"
    SEUDONIMIZADO_VERIFICADO = "seudonimizado_verificado"
    CON_DATOS_PERSONALES = "con_datos_personales"


class InvalidState(ValueError):
    """Error emitido cuando el estado no cumple el esquema de lista cerrada."""


def validate_state(
    spec: PolicyKind, state: dict[str, Any], *, strict: bool = False
) -> tuple[bool, str]:
    """Valida que el estado cumpla estrictamente el esquema de lista cerrada del tipo.

    Rechaza enteros exactos fuera de cubo, tipos erróneos, claves extra o faltantes
    y cualquier valor no enumerado en la política base.
    """
    esquema = spec.esquema_estado
    if not isinstance(state, dict):
        motivo = "estado_no_es_diccionario"
        if strict:
            raise InvalidState(motivo)
        return False, motivo

    # Validar claves faltantes
    for campo in esquema:
        if campo not in state:
            motivo = f"clave_faltante: {campo}"
            if strict:
                raise InvalidState(motivo)
            return False, motivo

    # Validar claves extra
    for campo in state:
        if campo not in esquema:
            motivo = f"clave_extra: {campo}"
            if strict:
                raise InvalidState(motivo)
            return False, motivo

    # Validar cada valor
    for campo, valor in state.items():
        valores_permitidos = esquema[campo]

        # Validaciones de tipo estrictas
        # En Python, bool es subclase de int (True == 1), lo prevenimos explícitamente:
        if isinstance(valor, bool) and not any(isinstance(p, bool) for p in valores_permitidos):
            motivo = f"tipo_invalido_bool_en_{campo}"
            if strict:
                raise InvalidState(motivo)
            return False, motivo

        if isinstance(valor, int) and not isinstance(valor, bool):
            # Si el esquema espera cadenas (cubos), un entero no coincide salvo
            # que esté explícitamente en permitidos
            if valor not in valores_permitidos and str(valor) not in [
                str(p) for p in valores_permitidos
            ]:
                motivo = f"valor_invalido_entero_en_{campo}"
                if strict:
                    raise InvalidState(motivo)
                return False, motivo

        # Valor general en permitidos (como str o valor exacto)
        str_permitidos = [str(p) for p in valores_permitidos]
        if str(valor) not in str_permitidos and valor not in valores_permitidos:
            motivo = f"valor_invalido_en_{campo}"
            if strict:
                raise InvalidState(motivo)
            return False, motivo

    return True, "ok"
