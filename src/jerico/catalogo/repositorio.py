"""Repositorio del catálogo de precios (Spec 006, C2).

Gestiona la carga de archivos YAML versionados, la resolución de la versión VIGENTE
y la inmutabilidad de versiones aprobadas.
"""

from pathlib import Path

import yaml

from jerico.catalogo.modelo import CatalogoPrecios

_DIR_PRECIOS_DEFECTO = Path(__file__).resolve().parents[3] / "catalogo" / "precios"


class CatalogoError(Exception):
    """Error base para operaciones del catálogo."""


class CatalogoSinVersionVigenteError(CatalogoError):
    """Lanzado cuando no hay versión vigente configurada en VIGENTE."""


class VersionCatalogoNoEncontradaError(CatalogoError):
    """Lanzado cuando no se encuentra el archivo de la versión solicitada."""


class CatalogoInmutableError(CatalogoError):
    """Lanzado al intentar sobrescribir o modificar una versión inmutable (vigente o retirada)."""


class RepositorioCatalogo:
    """Acceso al almacén de catálogos de precios en disco."""

    def __init__(self, directorio: Path | str | None = None) -> None:
        self.directorio = Path(directorio) if directorio is not None else _DIR_PRECIOS_DEFECTO

    def obtener_version_vigente(self) -> str:
        """Resuelve la versión activa leyendo el archivo VIGENTE.

        R3: Si no existe VIGENTE o está vacío, lanza CatalogoSinVersionVigenteError.
        """
        archivo_vigente = self.directorio / "VIGENTE"
        if not archivo_vigente.is_file():
            raise CatalogoSinVersionVigenteError(
                "catálogo sin versión vigente: no existe el archivo VIGENTE"
            )

        contenido = archivo_vigente.read_text(encoding="utf-8").strip()
        if not contenido:
            raise CatalogoSinVersionVigenteError(
                "catálogo sin versión vigente: archivo VIGENTE vacío"
            )

        return contenido

    def cargar_version(self, version: str) -> CatalogoPrecios:
        """Carga y valida un catálogo por su identificador semver."""
        archivo = self.directorio / f"{version}.yaml"
        if not archivo.is_file():
            raise VersionCatalogoNoEncontradaError(
                f"no existe la versión '{version}' del catálogo"
            )

        with open(archivo, encoding="utf-8") as f:
            datos = yaml.safe_load(f)

        catalogo = CatalogoPrecios.model_validate(datos)
        if catalogo.version != version:
            raise ValueError(
                f"la versión declarada en el catálogo ('{catalogo.version}') "
                f"no coincide con el archivo '{version}.yaml'"
            )
        return catalogo

    def cargar_vigente(self) -> CatalogoPrecios:
        """Carga la versión actualmente marcada en VIGENTE."""
        version = self.obtener_version_vigente()
        return self.cargar_version(version)

    def guardar_version(self, catalogo: CatalogoPrecios) -> Path:
        """Persiste un catálogo en disco respetando la inmutabilidad de versiones.

        R2: Una versión con estado 'vigente' o 'retirada' es inmutable.
        """
        archivo = self.directorio / f"{catalogo.version}.yaml"
        if archivo.is_file():
            existente = self.cargar_version(catalogo.version)
            if existente.estado in ("vigente", "retirada"):
                raise CatalogoInmutableError(
                    f"la versión '{catalogo.version}' ya está en estado "
                    f"'{existente.estado}' y es inmutable"
                )

        self.directorio.mkdir(parents=True, exist_ok=True)
        with open(archivo, "w", encoding="utf-8") as f:
            yaml.safe_dump(catalogo.model_dump(), f, sort_keys=False, allow_unicode=True)

        return archivo

    def marcar_vigente(self, version: str) -> None:
        """Apunta el archivo VIGENTE a la versión indicada."""
        self.cargar_version(version)
        self.directorio.mkdir(parents=True, exist_ok=True)
        archivo_vigente = self.directorio / "VIGENTE"
        archivo_vigente.write_text(f"{version.strip()}\n", encoding="utf-8")
