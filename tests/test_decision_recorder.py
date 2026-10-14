"""Pruebas de T07: Registro de decisiones (VJT-040, VJT-041, VJT-043, VJT-045, VJT-046)."""

import json
from pathlib import Path

from jerico.decision.recorder import DecisionRecorder


def test_recorder_writes_mandatory_fields(tmp_path: Path):
    """Verifica que se registren todos los campos obligatorios en todos los modos (VJT-040)."""
    recorder = DecisionRecorder(dir_path=tmp_path)

    evento = {
        "event_id": "evt_1000_1_abcd",
        "decision_key": "dkey_1234",
        "kind": "seguimiento_lead",
        "tarea": None,
        "mode": "sombra",
        "state": {"dias_sin_contacto": "3-7", "paso_cadencia": "1"},
        "base_option": "mantener_orden",
        "applied_option": "mantener_orden",
        "suggested_option": None,
        "source": "base",
        "reason": "sombra",
        "policy_version": "1.0.0",
        "cohorte_suficiente": True,
    }

    recorder.record(evento)

    files = list(tmp_path.glob("decision-*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1

    entry = json.loads(lines[0])
    for campo in [
        "event_id",
        "decision_key",
        "kind",
        "mode",
        "state",
        "base_option",
        "applied_option",
        "source",
        "reason",
        "policy_version",
        "timestamp",
    ]:
        assert campo in entry, f"Falta campo obligatorio: {campo}"

    # Verificación de costo sin tarifas (VJT-045, Q2)
    assert entry.get("cost_usd") == "no calculado"


def test_recorder_deduplicates_event_id(tmp_path: Path):
    """Repetir un evento con el mismo event_id no duplica la línea (VJT-041)."""
    recorder = DecisionRecorder(dir_path=tmp_path)

    evento = {
        "event_id": "evt_dup_1",
        "decision_key": "dkey_1",
        "kind": "nivel_turno",
        "tarea": None,
        "mode": "apagado",
        "state": {"tipo_mensaje": "simple"},
        "base_option": "L1",
        "applied_option": "L1",
        "suggested_option": None,
        "source": "base",
        "reason": "apagado",
        "policy_version": "1.0.0",
    }

    recorder.record(evento)
    recorder.record(evento)  # Segunda vez con mismo event_id

    files = list(tmp_path.glob("decision-*.jsonl"))
    lines = files[0].read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1


def test_recorder_does_not_raise_on_disk_error(tmp_path: Path, monkeypatch):
    """El registrador nunca lanza excepción ante fallas de E/S o disco (VJT-030)."""
    recorder = DecisionRecorder(dir_path=tmp_path)

    def bad_open(*args, **kwargs):
        raise OSError("Disco lleno o no accesible")

    monkeypatch.setattr(Path, "open", bad_open)

    evento: dict[str, object] = {
        "event_id": "evt_err_1",
        "decision_key": "dkey_err",
        "kind": "nivel_turno",
        "tarea": None,
        "mode": "apagado",
        "state": {},
        "base_option": "L1",
        "applied_option": "L1",
        "suggested_option": None,
        "source": "base",
        "reason": "apagado",
        "policy_version": "1.0.0",
    }

    # No debe lanzar
    recorder.record(evento)


def test_recorder_prunes_retention(tmp_path: Path):
    """Archivos con antigüedad mayor a retention_days se eliminan (VJT-043)."""
    current_time = 1700000000.0  # Base
    recorder = DecisionRecorder(dir_path=tmp_path, retention_days=90, clock=lambda: current_time)

    # Crear archivo viejo (hace 100 días: 100 * 86400 = 8640000 s)
    old_file = tmp_path / "decision-2023-01-01.jsonl"
    old_file.write_text('{"old": true}\n', encoding="utf-8")
    import os

    old_mtime = current_time - (100 * 86400)
    os.utime(old_file, (old_mtime, old_mtime))

    # Crear archivo reciente (hace 10 días)
    new_file = tmp_path / "decision-2023-11-01.jsonl"
    new_file.write_text('{"new": true}\n', encoding="utf-8")
    new_mtime = current_time - (10 * 86400)
    os.utime(new_file, (new_mtime, new_mtime))

    recorder.prune_retention()

    assert not old_file.exists()
    assert new_file.exists()
