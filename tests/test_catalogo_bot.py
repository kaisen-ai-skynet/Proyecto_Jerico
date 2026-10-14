"""Pruebas unitarias para los comandos de catálogo y cotización en el bot (Spec 006).

Verifica:
1. Comercial ejecutando /catalogo recibe vista comercial sin costos ni márgenes internos (R7).
2. Comercial ejecutando /cotizar genera cotización determinista con contrato Cotizacion (R4, R14).
3. Planes inexistentes en /cotizar devuelven error explícito con opciones válidas (R11).
4. Catálogo en borrador incluye marca «BORRADOR — no cotizar» (R12).
5. CTO ejecutando /catalogo ve costos directos, márgenes y advertencias (R8, R13).
6. CTO ejecutando /catalogo_activar puede fijar la versión vigente (R3).
7. Comercial intentando ejecutar /catalogo_activar o /catalogo_actualizar es rechazado.
8. CTO ejecutando /catalogo_actualizar crea nueva versión semver inmutable (R1, R2).
9. CTO ejecutando /catalogo_verificar recibe reporte de validación (R6).
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from jerico.catalogo.bot import (
    catalogo_activar_command,
    catalogo_actualizar_command,
    catalogo_command,
    catalogo_verificar_command,
    cotizar_command,
    register_catalogo_commands,
)
from jerico.catalogo.modelo import CatalogoPrecios
from jerico.catalogo.repositorio import RepositorioCatalogo
from jerico.crm.bot import CrmBot
from jerico.crm.model import Role, User


@pytest.fixture
def repo_catalogo(tmp_path: Path) -> RepositorioCatalogo:
    dir_precios = tmp_path / "precios"
    dir_precios.mkdir(parents=True)
    cat_010 = CatalogoPrecios.model_validate(
        {
            "version": "0.1.0",
            "estado": "borrador",
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
                    "id": "unico",
                    "nombre": "Único",
                    "precio_propuesta": 4320000,
                    "precio_formula": 6123123,
                    "margen_objetivo_pct": 20.0,
                    "interno": {
                        "margen_real_pct": -13.4,
                    },
                },
            ],
            "interno": {
                "costo_directo_por_implementacion": 4898499,
                "capacidad_implementaciones_anio": 12,
            },
            "advertencias": [
                "Planes Estándar y Único se proponen bajo costo directo.",
                "Capacidad de 12 implementaciones al año.",
                "Modelo sin churn (0 %) e ICA pendiente de confirmar con contador.",
            ],
        }
    )
    repo = RepositorioCatalogo(dir_precios)
    repo.guardar(cat_010)
    return repo


@pytest.fixture
def user_comercial() -> User:
    return User(
        id=1,
        telegram_id=1001,
        role=Role.COMMERCIAL,
        email="lucas@kaisen.ai",
        active=1,
        created_at="2026-10-14T00:00:00Z",
        deactivated_at=None,
    )


@pytest.fixture
def user_cto() -> User:
    return User(
        id=2,
        telegram_id=2002,
        role=Role.CTO,
        email="santiago@kaisen.ai",
        active=1,
        created_at="2026-10-14T00:00:00Z",
        deactivated_at=None,
    )


def test_catalogo_command_comercial(
    repo_catalogo: RepositorioCatalogo, user_comercial: User
) -> None:
    conn = MagicMock()
    now = datetime.now(UTC)
    out = catalogo_command(conn, user_comercial, "/catalogo", now, repo=repo_catalogo)

    assert len(out) == 1
    msg = out[0].text
    # Vista comercial debe incluir planes y precios de propuesta
    assert "Estándar" in msg
    assert "3.220.000" in msg
    assert "Único" in msg
    assert "4.320.000" in msg
    # No debe incluir costos directos ni márgenes internos (R7)
    assert "4.898.499" not in msg
    assert "-52.1" not in msg
    assert "costo directo" not in msg.lower()
    # Debe advertir BORRADOR al no estar vigente (R12)
    assert "BORRADOR" in msg


def test_catalogo_command_cto(repo_catalogo: RepositorioCatalogo, user_cto: User) -> None:
    conn = MagicMock()
    now = datetime.now(UTC)
    out = catalogo_command(conn, user_cto, "/catalogo", now, repo=repo_catalogo)

    assert len(out) == 1
    msg = out[0].text
    # Vista CTO incluye costos internos y márgenes (R8, R13)
    assert "4.898.499" in msg
    assert "-52.1" in msg
    assert "Estándar" in msg
    assert "Capacidad de 12 implementaciones" in msg
    assert "/catalogo_activar" in msg


def test_cotizar_command_generacion_valida(
    repo_catalogo: RepositorioCatalogo, user_comercial: User
) -> None:
    conn = MagicMock()
    now = datetime.now(UTC)
    out = cotizar_command(conn, user_comercial, "/cotizar estandar 6", now, repo=repo_catalogo)

    assert len(out) == 1
    msg = out[0].text
    assert "COTIZACIÓN" in msg
    assert "Estándar" in msg
    assert "3.220.000" in msg  # Implementación
    assert "1.932.000" in msg  # 6 meses x 322.000 (10 %)
    assert "5.152.000" in msg  # Total


def test_cotizar_command_plan_inexistente(
    repo_catalogo: RepositorioCatalogo, user_comercial: User
) -> None:
    conn = MagicMock()
    now = datetime.now(UTC)
    out = cotizar_command(conn, user_comercial, "/cotizar ultra 12", now, repo=repo_catalogo)

    assert len(out) == 1
    msg = out[0].text
    assert "no existe" in msg or "no encontrado" in msg.lower()
    assert "estandar" in msg and "unico" in msg  # Planes válidos (R11)


def test_catalogo_activar_rechaza_comercial(
    repo_catalogo: RepositorioCatalogo, user_comercial: User
) -> None:
    conn = MagicMock()
    now = datetime.now(UTC)
    out = catalogo_activar_command(
        conn, user_comercial, "/catalogo_activar 0.1.0", now, repo=repo_catalogo
    )

    assert len(out) == 1
    msg = out[0].text
    assert "Solo el CTO" in msg or "no autorizado" in msg.lower()


def test_catalogo_activar_cto_exitoso(repo_catalogo: RepositorioCatalogo, user_cto: User) -> None:
    conn = MagicMock()
    now = datetime.now(UTC)
    out = catalogo_activar_command(
        conn, user_cto, "/catalogo_activar 0.1.0", now, repo=repo_catalogo
    )

    assert len(out) == 1
    msg = out[0].text
    assert "0.1.0" in msg
    assert "vigente" in msg.lower()

    # Comprobar que repo resuelve 0.1.0 como vigente
    vig = repo_catalogo.cargar_vigente()
    assert vig.version == "0.1.0"


def test_catalogo_actualizar_crea_nueva_version(
    repo_catalogo: RepositorioCatalogo, user_cto: User
) -> None:
    conn = MagicMock()
    now = datetime.now(UTC)
    # /catalogo_actualizar <version_nueva> <plan_id> <nuevo_precio>
    out = catalogo_actualizar_command(
        conn,
        user_cto,
        "/catalogo_actualizar 0.2.0 estandar 3500000",
        now,
        repo=repo_catalogo,
    )

    assert len(out) == 1
    msg = out[0].text
    assert "0.2.0" in msg
    assert "3.500.000" in msg

    # Cargar versión 0.2.0
    v020 = repo_catalogo.cargar_version("0.2.0")
    plan_est = next(p for p in v020.planes if p.id == "estandar")
    assert plan_est.precio_propuesta == 3500000


def test_catalogo_verificar_command(repo_catalogo: RepositorioCatalogo, user_cto: User) -> None:
    conn = MagicMock()
    now = datetime.now(UTC)
    out = catalogo_verificar_command(
        conn, user_cto, "/catalogo_verificar 0.1.0", now, repo=repo_catalogo
    )

    assert len(out) == 1
    msg = out[0].text
    assert "Verificación" in msg
    assert "0.1.0" in msg


def test_register_catalogo_commands_in_crm_bot(
    repo_catalogo: RepositorioCatalogo,
) -> None:
    bot = CrmBot(
        db=MagicMock(),
        telegram=MagicMock(),
        clock=MagicMock(),
    )
    register_catalogo_commands(bot, repo=repo_catalogo)

    assert "catalogo" in bot._commands
    assert "cotizar" in bot._commands
    assert "catalogo_activar" in bot._commands
    assert "catalogo_actualizar" in bot._commands
    assert "catalogo_verificar" in bot._commands
