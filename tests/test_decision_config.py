from pathlib import Path

from jerico.decision.config import DecisionSettings, load_settings


def test_load_settings_from_env(monkeypatch, tmp_path: Path):
    """load_settings parsea correctamente las variables JERICO_DECISION_*."""
    monkeypatch.setenv("JERICO_DECISION_MODES", "nivel_turno=sombra,modelo_asistente=sugerencia")
    monkeypatch.setenv("JERICO_DECISION_KILL", "true")
    monkeypatch.setenv("JERICO_DECISION_DIR", str(tmp_path))
    monkeypatch.setenv("JERICO_DECISION_RETENTION_DAYS", "45")
    monkeypatch.setenv("JERICO_DECISION_ONLINE", "true")
    monkeypatch.setenv("JERICO_DECISION_MIN_LEADS", "30")

    settings = load_settings()
    assert settings.modes == {"nivel_turno": "sombra", "modelo_asistente": "sugerencia"}
    assert settings.kill is True
    assert settings.base_dir == tmp_path
    assert settings.retention_days == 45
    assert settings.online is True
    assert settings.min_leads == 30
    assert settings.mode_for("nivel_turno") == "apagado"  # Por kill activo


def test_kill_active_via_local_marker_file(tmp_path: Path, monkeypatch):
    """is_kill_active detecta archivo marcador en directorio actual."""
    monkeypatch.chdir(tmp_path)
    marker = tmp_path / "decision.KILL"
    marker.write_text("kill", encoding="utf-8")

    settings = DecisionSettings(base_dir=tmp_path / "sub")
    assert settings.is_kill_active() is True
