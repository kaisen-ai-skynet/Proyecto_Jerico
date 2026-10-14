"""Pruebas unitarias para cableado y scheduler del CRM-consejero.

Requisitos: VJC-002, VJC-006, VJC-009, VJC-014.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from jerico.crm.config import CrmSettings
from jerico.crm.jobs import SNAPSHOT_CRON, SNAPSHOT_JOB, register_jobs


def test_jobs_registration_with_and_without_snapshot() -> None:
    scheduler = MagicMock()
    daily = AsyncMock()
    backup = AsyncMock()
    snapshot = AsyncMock()

    # Sin snapshot callback
    register_jobs(scheduler, daily=daily, backup=backup)
    assert not any(call.args[0] == SNAPSHOT_JOB for call in scheduler.register_job.call_args_list)

    # Con snapshot callback
    scheduler.reset_mock()
    register_jobs(scheduler, daily=daily, backup=backup, snapshot=snapshot)
    snapshot_calls = [c for c in scheduler.register_job.call_args_list if c.args[0] == SNAPSHOT_JOB]
    assert len(snapshot_calls) == 1
    call = snapshot_calls[0]
    assert call.args[0] == SNAPSHOT_JOB
    assert call.args[1] == SNAPSHOT_CRON
    assert call.args[2] == snapshot
    assert call.kwargs.get("max_retries") == 1


def test_snapshot_cron_expression() -> None:
    # 30 minutos después de crm-daily (0 13 * * * -> 30 13 * * *)
    assert SNAPSHOT_CRON == "30 13 * * *"


@pytest.mark.asyncio
async def test_app_wiring_disabled_by_default(tmp_path: Path) -> None:
    from jerico.crm.app import CrmApp

    settings = CrmSettings(
        telegram_bot_token=SecretStr("fake-token"),
        fingerprint_key=SecretStr("fake-key"),
        seed_cto_telegram_id="12345",
        data_dir=tmp_path / "data",
    )

    with patch("jerico.crm.app.CronScheduler") as mock_sched_cls:
        mock_sched = mock_sched_cls.return_value
        app = CrmApp(settings, telegram=MagicMock(), email=MagicMock(), runner=MagicMock())
        try:
            # Job no registrado en scheduler
            calls = [c for c in mock_sched.register_job.call_args_list if c.args[0] == SNAPSHOT_JOB]
            assert len(calls) == 0
        finally:
            app.db.close()


@pytest.mark.asyncio
async def test_app_wiring_enabled_with_key(tmp_path: Path) -> None:
    from jerico.crm.app import CrmApp

    settings = CrmSettings(
        telegram_bot_token=SecretStr("fake-token"),
        fingerprint_key=SecretStr("fake-key"),
        seed_cto_telegram_id="12345",
        data_dir=tmp_path / "data",
        jev_snapshot_enabled=True,
        jev_snapshot_key=SecretStr("valid-key-for-snapshot"),
    )

    with patch("jerico.crm.app.CronScheduler") as mock_sched_cls:
        mock_sched = mock_sched_cls.return_value
        app = CrmApp(settings, telegram=MagicMock(), email=MagicMock(), runner=MagicMock())
        try:
            calls = [c for c in mock_sched.register_job.call_args_list if c.args[0] == SNAPSHOT_JOB]
            assert len(calls) == 1
            assert calls[0].args[1] == "30 13 * * *"
        finally:
            app.db.close()


@pytest.mark.asyncio
async def test_app_wiring_enabled_missing_key_notice(tmp_path: Path) -> None:
    from jerico.crm.app import CrmApp

    settings = CrmSettings(
        telegram_bot_token=SecretStr("fake-token"),
        fingerprint_key=SecretStr("fake-key"),
        seed_cto_telegram_id="12345",
        data_dir=tmp_path / "data",
        jev_snapshot_enabled=True,
        jev_snapshot_key=SecretStr(""),  # Falta clave
    )

    with patch("jerico.crm.app.CronScheduler") as mock_sched_cls:
        mock_sched = mock_sched_cls.return_value
        app = CrmApp(settings, telegram=MagicMock(), email=MagicMock(), runner=MagicMock())
        try:
            # Job NO se registra
            calls = [c for c in mock_sched.register_job.call_args_list if c.args[0] == SNAPSHOT_JOB]
            assert len(calls) == 0

            # Al arrancar, avisa al CTO
            with (
                patch.object(app, "_notify_cto") as mock_notify,
                patch.object(app, "run_daily_job"),
                patch.object(app, "run_followup_job"),
            ):
                await app.startup()
                notices_sent = mock_notify.call_args[0][0]
                assert any("JERICO_CRM_JEV_SNAPSHOT_KEY" in n for n in notices_sent)
        finally:
            app.db.close()


@pytest.mark.asyncio
async def test_run_snapshot_job_catches_exception_and_counts_failure(tmp_path: Path) -> None:
    from jerico.crm.app import CrmApp

    settings = CrmSettings(
        telegram_bot_token=SecretStr("fake-token"),
        fingerprint_key=SecretStr("fake-key"),
        seed_cto_telegram_id="12345",
        data_dir=tmp_path / "data",
        jev_snapshot_enabled=True,
        jev_snapshot_key=SecretStr("valid-key"),
    )

    app = CrmApp(settings, telegram=MagicMock(), email=MagicMock(), runner=MagicMock())
    try:
        assert app._snapshot_fail_count == 0

        with patch("jerico.crm.app.run_snapshot", side_effect=OSError("Disk failure")):
            # No debe lanzar excepción
            await app.run_snapshot_job()
            assert app._snapshot_fail_count == 1
    finally:
        app.db.close()
