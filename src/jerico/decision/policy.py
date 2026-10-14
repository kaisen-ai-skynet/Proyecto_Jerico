"""Política base versionada para la capa de decisión transversal (spec 007)."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_DEFAULT_POLICY_PATH = Path(__file__).parent / "policy.json"

CLASES_VALIDAS = {"A", "B", "C"}
MODOS_VALIDOS = {"apagado", "sombra", "sugerencia", "enrutado"}


class PolicyValidationError(ValueError):
    """Error emitido cuando una política no cumple las reglas de validación."""


@dataclass(frozen=True)
class PolicyKind:
    """Especificación de un tipo o par (tipo, tarea) de decisión."""

    kind: str
    clase: str
    base: str
    opciones: list[str]
    tarea: str | None = None
    asesor: bool = False
    orden_exigencia: list[str] | None = None
    modo_defecto: str = "apagado"
    clase_datos: str = "sin_datos_personales"
    modelos_aptos_datos_personales: list[str] = field(default_factory=list)
    esquema_estado: dict[str, Any] = field(default_factory=dict)


class Policy:
    """Contenedor y validador de la política declarativa."""

    def __init__(self, raw: dict[str, Any]):
        self.raw = raw
        self.version: str = raw.get("version", "1.0.0")
        self.tipos: dict[str, Any] = raw.get("tipos", {})
        self._parsed_cache: dict[tuple[str, str | None], PolicyKind] = {}
        self.validate()

    def validate(self) -> None:
        """Aplica todas las invariantes de seguridad sobre la política cargada."""
        if not self.version:
            raise PolicyValidationError("La política debe tener una versión válida")
        if not self.tipos:
            raise PolicyValidationError("La política debe contener al menos un tipo")

        for nombre_tipo, conf_tipo in self.tipos.items():
            # Validar nombre contra tipos prohibidos de clase A fuera de la capa (VJT-062)
            prohibidos = ["contrato", "firma", "baja", "supresion", "autorizacion_datos"]
            for p in prohibidos:
                if p in nombre_tipo.lower():
                    raise PolicyValidationError(
                        f"Tipo prohibido '{nombre_tipo}' no debe figurar como consultable a Jev"
                    )

            self._validate_spec(nombre_tipo, conf_tipo, es_tarea=False)

            tareas = conf_tipo.get("tareas", {})
            for nombre_tarea, conf_tarea in tareas.items():
                self._validate_spec(
                    f"{nombre_tipo}:{nombre_tarea}",
                    conf_tarea,
                    padre=conf_tipo,
                    es_tarea=True,
                )

    def _validate_spec(
        self,
        identificador: str,
        conf: dict[str, Any],
        padre: dict[str, Any] | None = None,
        es_tarea: bool = False,
    ) -> None:
        clase = conf.get("clase") or (padre.get("clase") if padre else None)
        asesor = conf.get("asesor", padre.get("asesor", False) if padre else False)

        if not clase or (clase not in CLASES_VALIDAS and not asesor):
            raise PolicyValidationError(f"Clase inválida '{clase}' en '{identificador}'")

        opciones = conf.get("opciones") or (padre.get("opciones") if padre else [])
        base = conf.get("base") or (padre.get("base") if padre else None)

        if not opciones:
            raise PolicyValidationError(f"No hay opciones definidas en '{identificador}'")
        if not base or base not in opciones:
            raise PolicyValidationError(
                f"Base '{base}' fuera de las opciones permitidas en '{identificador}'"
            )

        modo_defecto = conf.get("modo_defecto") or (
            padre.get("modo_defecto") if padre else "apagado"
        )
        if modo_defecto != "apagado":
            raise PolicyValidationError(
                f"Modo por defecto debe ser 'apagado' en '{identificador}' (VJT-010)"
            )

        # Esquema de estado de lista cerrada
        esquema = conf.get("esquema_estado") or (padre.get("esquema_estado") if padre else {})
        if not esquema:
            raise PolicyValidationError(
                f"Esquema de estado debe ser de lista cerrada no vacía en '{identificador}'"
            )

        # Reglas de Clase B: orden_exigencia obligatorio
        if clase == "B":
            orden = conf.get("orden_exigencia") or (
                padre.get("orden_exigencia") if padre else None
            )
            if not orden:
                raise PolicyValidationError(f"Clase B exige orden_exigencia en '{identificador}'")
            if base not in orden:
                raise PolicyValidationError(
                    f"Base '{base}' debe pertenecer a orden_exigencia en '{identificador}'"
                )

        # Reglas por área (VJT-007, VJT-024, VJT-060, VJT-061)
        for op in opciones:
            op_lower = op.lower()
            if "calcular" in op_lower:
                raise PolicyValidationError(
                    f"Opción prohibida '{op}' en '{identificador}' (VJT-060)"
                )
            if "publicar" in op_lower or "gastar" in op_lower:
                raise PolicyValidationError(
                    f"Opción prohibida '{op}' en '{identificador}' (VJT-007, VJT-061)"
                )

        raw_modelos = conf.get("modelos_aptos_datos_personales") or (
            padre.get("modelos_aptos_datos_personales") if padre else []
        )
        modelos_aptos: list[str] = list(raw_modelos or [])
        if "deepseek-chat" in modelos_aptos:
            raise PolicyValidationError(
                f"deepseek-chat no puede ser apto para datos personales en '{identificador}'"
            )

    def par(self, kind: str, tarea: str | None = None) -> PolicyKind:
        """Resuelve el par (tipo, tarea) a su PolicyKind inmutable."""
        cache_key = (kind, tarea)
        if cache_key in self._parsed_cache:
            return self._parsed_cache[cache_key]

        if kind not in self.tipos:
            raise KeyError(f"Tipo desconocido en política: '{kind}'")

        conf_tipo = self.tipos[kind]
        conf_tarea = conf_tipo.get("tareas", {}).get(tarea) if tarea else None

        clase = (conf_tarea.get("clase") if conf_tarea else None) or conf_tipo.get("clase", "A")
        base = (conf_tarea.get("base") if conf_tarea else None) or conf_tipo.get("base")
        opciones = list(conf_tipo.get("opciones", []))
        asesor = bool(conf_tipo.get("asesor", False))
        orden = (conf_tarea.get("orden_exigencia") if conf_tarea else None) or conf_tipo.get(
            "orden_exigencia"
        )
        modo_defecto = conf_tipo.get("modo_defecto", "apagado")
        clase_datos = (conf_tarea.get("clase_datos") if conf_tarea else None) or conf_tipo.get(
            "clase_datos", "sin_datos_personales"
        )
        modelos_aptos = list(conf_tipo.get("modelos_aptos_datos_personales", []))
        esquema = dict(conf_tipo.get("esquema_estado", {}))

        pk = PolicyKind(
            kind=kind,
            tarea=tarea,
            clase=clase,
            base=base,
            opciones=opciones,
            asesor=asesor,
            orden_exigencia=list(orden) if orden else None,
            modo_defecto=modo_defecto,
            clase_datos=clase_datos,
            modelos_aptos_datos_personales=modelos_aptos,
            esquema_estado=esquema,
        )
        self._parsed_cache[cache_key] = pk
        return pk


def load_policy(path: Path | str | None = None) -> Policy:
    """Carga y valida la política base desde un archivo JSON."""
    file_path = Path(path) if path else _DEFAULT_POLICY_PATH
    if not file_path.exists():
        raise FileNotFoundError(f"Archivo de política no encontrado: {file_path}")

    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    return Policy(data)
