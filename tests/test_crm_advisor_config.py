"""Pruebas unitarias para configuración de CRM-consejero (spec 007, VJC-002, VJC-014, VJC-021)."""

from pathlib import Path

from jerico.crm.config import CrmSettings


def test_crm_advisor_config_defaults() -> None:
    settings = CrmSettings()
    assert settings.jev_snapshot_enabled is False
    assert settings.jev_snapshot_key.get_secret_value() == ""
    assert settings.jev_snapshot_dir is None
    assert settings.jev_snapshot_retention_days == 90

    # Si dir es None, la ruta efectiva por convención es data_dir / "jev_snapshot"
    effective_dir = settings.jev_snapshot_dir or (settings.data_dir / "jev_snapshot")
    assert effective_dir == settings.data_dir / "jev_snapshot"


def test_crm_advisor_config_env_vars(monkeypatch) -> None:
    monkeypatch.setenv("JERICO_CRM_JEV_SNAPSHOT_ENABLED", "true")
    monkeypatch.setenv("JERICO_CRM_JEV_SNAPSHOT_KEY", "super-clave-secreta")
    monkeypatch.setenv("JERICO_CRM_JEV_SNAPSHOT_DIR", "/custom/snapshots")
    monkeypatch.setenv("JERICO_CRM_JEV_SNAPSHOT_RETENTION_DAYS", "120")

    settings = CrmSettings()
    assert settings.jev_snapshot_enabled is True
    assert settings.jev_snapshot_key.get_secret_value() == "super-clave-secreta"
    assert settings.jev_snapshot_dir == Path("/custom/snapshots")
    assert settings.jev_snapshot_retention_days == 120


def test_crm_advisor_config_in_env_example() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "JERICO_CRM_JEV_SNAPSHOT_ENABLED" in env_example
    assert "JERICO_CRM_JEV_SNAPSHOT_KEY" in env_example
    assert "JERICO_CRM_JEV_SNAPSHOT_DIR" in env_example
    assert "JERICO_CRM_JEV_SNAPSHOT_RETENTION_DAYS" in env_example
