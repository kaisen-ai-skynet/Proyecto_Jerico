"""Herramienta de solo lectura para consulta del catálogo de precios (Spec 006, C5).

Permite al asistente y a los componentes del CRM (F2, F4):
1. Consultar los planes y advertencias según el rol del usuario (R7, R8, R10).
2. Generar cotizaciones deterministas bajo el contrato compartido Cotizacion (R4, R14).
3. Registrar la versión en cada respuesta y la marca «BORRADOR — no cotizar» (R10, R12).
4. Fallar explícitamente si no hay versión vigente (R3) o el plan no existe (R11).
"""

from typing import Any

from pydantic import PrivateAttr

from jerico.catalogo.cotizar import (
    PlanNoEncontradoError,
    cotizar_plan,
)
from jerico.catalogo.repositorio import (
    CatalogoSinVersionVigenteError,
    RepositorioCatalogo,
    VersionCatalogoNoEncontradaError,
)
from jerico.catalogo.vista import obtener_vista
from jerico.tools.base import BaseTool


class ConsultarCatalogoTool(BaseTool):
    """Herramienta determinista y de solo lectura para el catálogo de precios."""

    name: str = "consultar_catalogo"
    description: str = (
        "Consulta de solo lectura del catálogo de precios de Kaizen por rol (comercial o cto). "
        "Permite ver planes disponibles o cotizar un plan determinísticamente."
    )
    readonly: bool = True

    _repositorio: RepositorioCatalogo | None = PrivateAttr(default=None)

    def __init__(
        self,
        repositorio: RepositorioCatalogo | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        object.__setattr__(self, "_repositorio", repositorio)

    def _get_repo(self) -> RepositorioCatalogo:
        if self._repositorio is not None:
            return self._repositorio
        return RepositorioCatalogo()

    def _execute(  # type: ignore[override]
        self,
        rol: str = "comercial",
        plan_id: str = "",
        meses_mensualidad: int = 12,
        version: str = "",
    ) -> dict[str, Any]:
        repo = self._get_repo()

        try:
            if version.strip():
                catalogo = repo.cargar_version(version.strip())
            else:
                catalogo = repo.cargar_vigente()
        except CatalogoSinVersionVigenteError:
            return {
                "ok": False,
                "error": "CATALOGO_SIN_VERSION_VIGENTE",
                "mensaje": "catálogo sin versión vigente",
                "version": None,
            }
        except VersionCatalogoNoEncontradaError as err:
            return {
                "ok": False,
                "error": "VERSION_NO_ENCONTRADA",
                "mensaje": str(err),
                "version": version.strip(),
            }

        aviso_borrador = "BORRADOR — no cotizar" if catalogo.estado != "vigente" else None
        pid = plan_id.strip()

        if pid:
            try:
                cot = cotizar_plan(catalogo, pid, meses_mensualidad=meses_mensualidad)
            except PlanNoEncontradoError as err:
                return {
                    "ok": False,
                    "error": "PLAN_NO_ENCONTRADO",
                    "mensaje": str(err),
                    "plan_solicitado": pid,
                    "planes_validos": err.planes_validos,
                    "version": catalogo.version,
                }
            except ValueError as err:
                return {
                    "ok": False,
                    "error": "VALOR_INVALIDO",
                    "mensaje": str(err),
                    "version": catalogo.version,
                }

            cot_dict = cot.model_dump()
            cot_dict["total"] = cot.total
            return {
                "ok": True,
                "tool": self.name,
                "version": catalogo.version,
                "estado": catalogo.estado,
                "aviso": aviso_borrador,
                "cotizacion": cot_dict,
            }

        vista = obtener_vista(catalogo, rol=rol)
        return {
            "ok": True,
            "tool": self.name,
            "version": catalogo.version,
            "estado": catalogo.estado,
            "aviso": aviso_borrador,
            "vista": vista.model_dump(),
        }


CATALOGO_TOOLS: list[BaseTool] = [ConsultarCatalogoTool()]
