"""Motor determinista de cotización de precios para Jericó (Spec 006, C3).

Calcula mensualidad (10 % de la implementación) y totales anuales usando Decimal.
Construye el contrato formal Cotizacion de schemas/ sin intervención de modelos de lenguaje.
"""

from datetime import date
from decimal import Decimal

from jerico.catalogo.modelo import CatalogoPrecios, PlanPrecio
from jerico.catalogo.repositorio import CatalogoError
from jerico.schemas import Cotizacion, CotizacionLinea

_TERMINOS_PAGO_DEFECTO = (
    "50% de anticipo al inicio y 50% contra entrega. Mensualidades de soporte mes vencido."
)


class PlanNoEncontradoError(CatalogoError):
    """Lanzado cuando se solicita cotizar un plan inexistente en el catálogo."""

    def __init__(self, plan_id: str, planes_validos: list[str]) -> None:
        self.plan_id = plan_id
        self.planes_validos = planes_validos
        msg = (
            f"El plan '{plan_id}' no existe en el catálogo. "
            f"Planes válidos: {', '.join(planes_validos)}."
        )
        super().__init__(msg)


def _buscar_plan(catalogo: CatalogoPrecios, plan_id: str) -> PlanPrecio:
    pid_norm = plan_id.strip().lower()
    for plan in catalogo.planes:
        if plan.id.lower() == pid_norm:
            return plan

    planes_disponibles = [p.id for p in catalogo.planes]
    raise PlanNoEncontradoError(plan_id, planes_disponibles)


def calcular_mensualidad(catalogo: CatalogoPrecios, plan_id: str) -> Decimal:
    """Calcula la mensualidad en Decimal aplicando la regla del catálogo (R4, R5).

    Regla canónica: 10 % del valor de la implementación por mes.
    """
    plan = _buscar_plan(catalogo, plan_id)
    pct = Decimal(str(catalogo.regla_mensualidad.porcentaje_de_implementacion_por_mes))
    mensualidad = (Decimal(plan.precio_propuesta) * pct) / Decimal("100")
    return mensualidad.quantize(Decimal("1"))


def calcular_total_anual(
    catalogo: CatalogoPrecios,
    plan_id: str,
    *,
    meses: int = 12,
) -> Decimal:
    """Calcula el total en Decimal: implementación + N meses de soporte (R4)."""
    if meses < 0:
        raise ValueError("meses no puede ser negativo")

    plan = _buscar_plan(catalogo, plan_id)
    mensualidad = calcular_mensualidad(catalogo, plan_id)
    return Decimal(plan.precio_propuesta) + (mensualidad * Decimal(meses))


def cotizar_plan(
    catalogo: CatalogoPrecios,
    plan_id: str,
    *,
    meses_mensualidad: int = 12,
    payment_terms: str | None = None,
    valid_until: date | None = None,
    special_conditions: str | None = None,
) -> Cotizacion:
    """Genera la cotización determinista usando el contrato Cotizacion (R4, R11, R12, R14)."""
    if meses_mensualidad < 0:
        raise ValueError("meses_mensualidad no puede ser negativo")

    plan = _buscar_plan(catalogo, plan_id)
    mensualidad_int = int(calcular_mensualidad(catalogo, plan_id))

    lines: list[CotizacionLinea] = [
        CotizacionLinea(
            description=f"Implementación Plan {plan.nombre}",
            quantity=1,
            unit_price=plan.precio_propuesta,
        )
    ]

    if meses_mensualidad > 0:
        lines.append(
            CotizacionLinea(
                description=f"Soporte y evolución mensual ({meses_mensualidad} meses)",
                quantity=meses_mensualidad,
                unit_price=mensualidad_int,
            )
        )

    # Marca R12: si no está vigente, estampar aviso de borrador
    condiciones = special_conditions
    if catalogo.estado != "vigente":
        marca_borrador = "BORRADOR — no cotizar"
        if condiciones:
            condiciones = f"{marca_borrador}. {condiciones}"
        else:
            condiciones = marca_borrador

    terminos = payment_terms if payment_terms is not None else _TERMINOS_PAGO_DEFECTO

    return Cotizacion(
        currency=catalogo.moneda,
        lines=lines,
        payment_terms=terminos,
        valid_until=valid_until,
        special_conditions=condiciones,
    )
