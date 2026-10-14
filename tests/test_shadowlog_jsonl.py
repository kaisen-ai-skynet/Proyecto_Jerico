"""Pruebas unitarias para DailyJsonlWriter (spec 007, CRM-consejero, VJC-020 a 023)."""

import threading
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from jerico.shadowlog.jsonl import DailyJsonlWriter

BOGOTA = ZoneInfo("America/Bogota")


def test_append_single_record(tmp_path: Path) -> None:
    clock_time = datetime(2026, 10, 14, 12, 0, 0, tzinfo=BOGOTA).timestamp()
    writer = DailyJsonlWriter(tmp_path, clock=lambda: clock_time)

    writer.append({"lead_ref": "abc123", "score": 42})

    day_file = tmp_path / "2026-10-14.jsonl"
    assert day_file.exists()
    content = day_file.read_text(encoding="utf-8")
    assert content == '{"lead_ref": "abc123", "score": 42}\n'

    records = writer.read_day("2026-10-14")
    assert len(records) == 1
    assert records[0] == {"lead_ref": "abc123", "score": 42}


def test_append_after_partial_line(tmp_path: Path) -> None:
    day_file = tmp_path / "2026-10-14.jsonl"
    day_file.write_text('{"lead_ref": "partial"', encoding="utf-8")  # no termina en \n

    clock_time = datetime(2026, 10, 14, 12, 0, 0, tzinfo=BOGOTA).timestamp()
    writer = DailyJsonlWriter(tmp_path, clock=lambda: clock_time)
    writer.append({"lead_ref": "good_record"})

    # read_day descarta la línea parcial/ilegible y lee la válida
    records = writer.read_day("2026-10-14")
    assert len(records) == 1
    assert records[0] == {"lead_ref": "good_record"}

    # Verifica que el archivo tiene salto de línea separando
    raw_lines = day_file.read_text(encoding="utf-8").splitlines()
    assert len(raw_lines) == 2
    assert raw_lines[0] == '{"lead_ref": "partial"'
    assert raw_lines[1] == '{"lead_ref": "good_record"}'


def test_date_in_bogota_time(tmp_path: Path) -> None:
    # 23:30 local en Bogotá el 13 de Octubre (04:30 UTC del 14)
    dt_13 = datetime(2026, 10, 13, 23, 30, 0, tzinfo=BOGOTA)
    writer_13 = DailyJsonlWriter(tmp_path, clock=lambda: dt_13.timestamp())
    writer_13.append({"tag": "dia_13"})
    assert (tmp_path / "2026-10-13.jsonl").exists()

    # 00:30 local en Bogotá el 14 de Octubre (05:30 UTC del 14)
    dt_14 = datetime(2026, 10, 14, 0, 30, 0, tzinfo=BOGOTA)
    writer_14 = DailyJsonlWriter(tmp_path, clock=lambda: dt_14.timestamp())
    writer_14.append({"tag": "dia_14"})
    assert (tmp_path / "2026-10-14.jsonl").exists()


def test_line_over_4kb_rejected(tmp_path: Path) -> None:
    writer = DailyJsonlWriter(tmp_path)
    huge_data = {"data": "x" * 5000}

    with pytest.raises(ValueError, match="4 KB"):
        writer.append(huge_data)


def test_purge_retention(tmp_path: Path) -> None:
    clock_time = datetime(2026, 10, 14, 12, 0, 0, tzinfo=BOGOTA).timestamp()
    writer = DailyJsonlWriter(tmp_path, retention_days=30, clock=lambda: clock_time)

    # Crear archivos viejos y nuevos
    f_old = tmp_path / "2026-08-01.jsonl"
    f_old.write_text('{"old": true}\n', encoding="utf-8")

    f_recent = tmp_path / "2026-10-01.jsonl"
    f_recent.write_text('{"recent": true}\n', encoding="utf-8")

    f_today = tmp_path / "2026-10-14.jsonl"
    f_today.write_text('{"today": true}\n', encoding="utf-8")

    purged = writer.purge()
    assert purged == 1
    assert not f_old.exists()
    assert f_recent.exists()
    assert f_today.exists()


def test_rewrite_without_atomicity(tmp_path: Path) -> None:
    f1 = tmp_path / "2026-10-13.jsonl"
    f1.write_text(
        '{"lead_ref": "keep1"}\n{"lead_ref": "remove1"}\n{"lead_ref": "keep2"}\n',
        encoding="utf-8",
    )
    f2 = tmp_path / "2026-10-14.jsonl"
    f2.write_text('{"lead_ref": "remove2"}\n{"lead_ref": "keep3"}\n', encoding="utf-8")

    writer = DailyJsonlWriter(tmp_path)
    removed = writer.rewrite_without(lambda r: r.get("lead_ref") in {"remove1", "remove2"})

    assert len(removed) == 2
    refs_removed = {r["lead_ref"] for r in removed}
    assert refs_removed == {"remove1", "remove2"}

    records_13 = writer.read_day("2026-10-13")
    assert [r["lead_ref"] for r in records_13] == ["keep1", "keep2"]

    records_14 = writer.read_day("2026-10-14")
    assert [r["lead_ref"] for r in records_14] == ["keep3"]


def test_rewrite_without_failure_deletes_file(tmp_path: Path) -> None:
    f1 = tmp_path / "2026-10-13.jsonl"
    f1.write_text('{"lead_ref": "remove1"}\n', encoding="utf-8")

    writer = DailyJsonlWriter(tmp_path)

    # Simular fallo durante reemplazo atómico
    with patch.object(Path, "replace", side_effect=OSError("Disk write error")):
        _ = writer.rewrite_without(lambda r: r.get("lead_ref") == "remove1")
        # El archivo que no pudo reescribirse se elimina
        assert not f1.exists()


def test_concurrency_20_threads(tmp_path: Path) -> None:
    writer = DailyJsonlWriter(tmp_path, clock=lambda: 1728900000.0)

    def worker(worker_id: int) -> None:
        for i in range(50):
            writer.append({"worker": worker_id, "idx": i})

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Todos los 1000 registros deben haberse escrito limpiamente
    day_file = list(tmp_path.glob("*.jsonl"))[0]
    records = writer.read_day(day_file.stem)
    assert len(records) == 1000
