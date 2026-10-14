"""Pruebas unitarias de esquemas de marketing (Spec 008, M1)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from jerico.schemas.marketing import (
    CampanaMarketing,
    CanalMarketing,
    ClasificacionCampana,
    EstadoCampana,
    IdeaInput,
    LinterResult,
    LinterViolation,
    MetaAdConfig,
    Trato,
    export_marketing_json_schemas,
    generar_idempotency_key,
)


def test_idea_input_valida() -> None:
    idea = IdeaInput(
        id="IDEA-20261014-001",
        texto="Explicar por qué en Kaizen primero entendemos antes de construir software.",
        autor="cto",
        creado_en=datetime(2026, 10, 14, 1, 0, tzinfo=UTC),
    )
    assert idea.id == "IDEA-20261014-001"
    assert "primero entendemos" in idea.texto
    assert idea.autor == "cto"


def test_meta_ad_config_debe_nacer_en_paused() -> None:
    # Por defecto status="PAUSED" y gasto_autorizado_usd=0.00
    cfg = MetaAdConfig()
    assert cfg.status == "PAUSED"
    assert cfg.gasto_autorizado_usd == Decimal("0.00")

    # Rechazar si intenta nacer activo
    with pytest.raises(ValidationError, match="status inicial debe ser 'PAUSED'"):
        MetaAdConfig(status="ACTIVE")


def test_meta_ad_config_rechaza_presupuesto_negativo() -> None:
    with pytest.raises(ValidationError):
        MetaAdConfig(presupuesto_diario_usd=Decimal("-5.00"))

    with pytest.raises(ValidationError):
        MetaAdConfig(gasto_autorizado_usd=Decimal("-1.00"))


def test_campana_marketing_creacion_valida() -> None:
    key = generar_idempotency_key("CAMP-01", CanalMarketing.CORREO, "dest@pyme.co", "texto")
    campana = CampanaMarketing(
        id="CAMP-20261014-001",
        nombre="C1 Prospección PYMES",
        clasificacion_campana=ClasificacionCampana.C1,
        canal=CanalMarketing.CORREO,
        trato=Trato.USTED,
        copy_principal="Estimado gerente, primero entendemos su operación.",
        idempotency_key=key,
        dry_run=True,
    )
    assert campana.estado == EstadoCampana.BORRADOR
    assert campana.dry_run is True
    assert campana.gasto_autorizado_usd == Decimal("0.00")
    assert campana.aprobado_por is None


def test_campana_marketing_meta_ads_requiere_config() -> None:
    key = generar_idempotency_key("CAMP-02", CanalMarketing.META_ADS, "adset1", "texto")
    campana = CampanaMarketing(
        id="CAMP-20261014-002",
        nombre="C1 Anuncio WhatsApp",
        clasificacion_campana=ClasificacionCampana.C1,
        canal=CanalMarketing.META_ADS,
        trato=Trato.TU,
        copy_principal="¿Tu operación vive en papel? Da el paso.",
        meta_ad_config=MetaAdConfig(presupuesto_diario_usd=Decimal("2.00")),
        idempotency_key=key,
    )
    assert campana.meta_ad_config is not None
    assert campana.meta_ad_config.status == "PAUSED"


def test_linter_result_estructura() -> None:
    res = LinterResult(
        valido=False,
        errores=[LinterViolation(regla="nombre", mensaje="Uso prohibido de Kaisen AI")],
        nombre_valido=False,
    )
    assert res.valido is False
    assert len(res.errores) == 1
    assert res.nombre_valido is False
    assert res.tagline_valido is True


def test_export_marketing_json_schemas(tmp_path) -> None:  # type: ignore[no-untyped-def]
    export_marketing_json_schemas(tmp_path)
    assert (tmp_path / "campana_marketing.schema.json").exists()
    assert (tmp_path / "idea_input.schema.json").exists()
    assert (tmp_path / "meta_ad_config.schema.json").exists()
    assert (tmp_path / "linter_result.schema.json").exists()
