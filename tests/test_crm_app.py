"""Tests del cableado, jobs, arranque y reinicio (T24).

Requisitos: VCRM-162 y 168 (aviso al CTO), VCRM-078 y 049 (de extremo a extremo).
"""

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from loguru import logger

from crm_support import (
    FakeClock,
    FakeEmailSender,
    FakeRunner,
    FakeTelegram,
    build_v1_database,
    make_settings,
)
from f2_support import make_lead, make_proposal
from jerico.crm import app as app_mod
from jerico.crm import leads, repo
from jerico.crm.app import (
    EXIT_CONFIG,
    CrmApp,
    fingerprint_keys,
    main,
    missing_secrets,
    run_service,
)
from jerico.crm.jobs import (
    BACKUP_CRON,
    DAILY_CRON,
    FOLLOWUP_CRON,
    FOLLOWUP_JOB,
    register_jobs,
)
from jerico.crm.model import LeadState, Role, User
from jerico.crm.ports import Update
from jerico.crm.timeutil import to_iso
from jerico.cron.scheduler import CronScheduler

NOW = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
CTO_TG = 1000
COM_TG = 2000
LAW_TG = 3000
SECRET_TOKEN = "123:token-super-secreto"
SECRET_KEY = "clave-hmac-secreta"
COMPLETE: dict[str, Any] = {
    "client_type": "persona natural",
    "doc_type": "cédula de ciudadanía",
    "doc_number": "1020304050",
    "phone_e164": "+573001112233",
    "email": "ana@cliente.co",
    "service": "Desarrollo de chatbot",
    "agreed_value": "12.000.000 COP",
    "start_term": "01/04/2026",
}


def _settings(tmp_path: Path, **overrides: Any) -> Any:
    base: dict[str, Any] = {
        "telegram_bot_token": SECRET_TOKEN,
        "fingerprint_key": SECRET_KEY,
        "seed_cto_telegram_id": str(CTO_TG),
        "seed_cto_email": "cto@k.co",
        "data_dir": tmp_path / "crm-data",
        **overrides,
    }
    return make_settings(**base)


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.tg = FakeTelegram()
        self.mail = FakeEmailSender()
        self.runner = FakeRunner()
        self.clock = FakeClock(NOW)
        self.apps: list[CrmApp] = []

    def build(self, assistant_llm: Any = None, **overrides: Any) -> CrmApp:
        app = CrmApp(
            _settings(self.tmp_path, **overrides),
            telegram=self.tg,
            email=self.mail,
            runner=self.runner,
            clock=self.clock.now,
            assistant_llm=assistant_llm,
        )
        self.apps.append(app)
        return app


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith(("JERICO_CRM_", "OPENAI_")):
            monkeypatch.delenv(name)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    e = Env(tmp_path)
    yield e
    for app in e.apps:
        app.close()


def _texts(tg: FakeTelegram, chat_id: int) -> list[str]:
    return [s.text for s in tg.sent if s.chat_id == chat_id]


# --- Jobs (plan §9) -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vcrm078_register_jobs_crons_fire_on_tick() -> None:
    calls: list[str] = []

    async def daily() -> None:
        calls.append("daily")

    async def backup() -> None:
        calls.append("backup")

    scheduler = CronScheduler()
    register_jobs(scheduler, daily=daily, backup=backup)
    assert (DAILY_CRON, BACKUP_CRON) == ("0 13 * * *", "0 8 * * *")
    assert set(scheduler.jobs) == {"crm-daily", "crm-backup"}
    await scheduler.tick(datetime(2026, 3, 2, 8, 0, tzinfo=UTC))
    await asyncio.gather(*scheduler.tasks.values())
    assert calls == ["backup"]
    await scheduler.tick(datetime(2026, 3, 2, 13, 0, tzinfo=UTC))
    await asyncio.gather(*scheduler.tasks.values())
    assert calls == ["backup", "daily"]
    await scheduler.tick(datetime(2026, 3, 2, 13, 1, tzinfo=UTC))
    assert calls == ["backup", "daily"]


def test_vcrm078_app_scheduler_has_all_jobs(env: Env) -> None:
    app = env.build()
    assert set(app.scheduler.jobs) == {"crm-daily", "crm-backup", "crm-followup"}
    assert app.scheduler.timeout == 1800 and app.scheduler.interval == 20


# --- Secretos y claves ----------------------------------------------------------------------


def test_vcrm162_missing_secrets_names_only(tmp_path: Path) -> None:
    assert missing_secrets(_settings(tmp_path)) == []
    names = missing_secrets(_settings(tmp_path, telegram_bot_token=None, fingerprint_key=""))
    assert names == ["JERICO_CRM_TELEGRAM_BOT_TOKEN", "JERICO_CRM_FINGERPRINT_KEY"]


def test_fingerprint_keys_current_first_then_previous(tmp_path: Path) -> None:
    s = _settings(tmp_path, fingerprint_previous_keys=" k0 , ,k-1")
    assert fingerprint_keys(s) == [SECRET_KEY, "k0", "k-1"]


@pytest.mark.parametrize("missing", ["telegram_bot_token", "fingerprint_key"])
def test_vcrm162_main_exits_2_without_secret_and_logs_no_secret(
    tmp_path: Path, missing: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines: list[str] = []
    sink = logger.add(lines.append, level="DEBUG")
    called: list[Any] = []

    async def fake_service(settings: Any) -> None:
        called.append(settings)

    monkeypatch.setattr(app_mod, "run_service", fake_service)
    try:
        with pytest.raises(SystemExit) as exc:
            main(_settings(tmp_path, **{missing: None}))
    finally:
        logger.remove(sink)
    assert exc.value.code == EXIT_CONFIG == 2
    assert called == []
    log = "".join(lines)
    assert f"JERICO_CRM_{missing.upper()}" in log
    assert SECRET_TOKEN not in log and SECRET_KEY not in log


def test_main_runs_service_with_complete_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[Any] = []

    async def fake_service(settings: Any) -> None:
        called.append(settings)

    monkeypatch.setattr(app_mod, "run_service", fake_service)
    settings = _settings(tmp_path)
    main(settings)
    assert called == [settings]


# --- Arranque: avisos al CTO (VCRM-162, 168), siembra, barrido y latido ------------------------


def test_vcrm162_startup_warns_cto_of_out_of_bound_params(env: Env) -> None:
    app = env.build(query_deadline_business_days=12, backup_retention_days=60)
    asyncio.run(app.startup())
    texts = _texts(env.tg, CTO_TG)
    query = [t for t in texts if "query_deadline_business_days" in t]
    backup = [t for t in texts if "backup_retention_days" in t]
    assert len(query) == 1 and "12" in query[0] and "10" in query[0]
    assert len(backup) == 1 and "60" in backup[0] and "30" in backup[0]
    assert app.params.query_deadline_business_days == 10


def test_vcrm168_invalid_extra_holiday_warns_cto_and_startup_continues(
    env: Env, tmp_path: Path
) -> None:
    missing_file = tmp_path / "no-existe.txt"
    app = env.build(extra_holidays=f"2026-12-24, 2026-02-30, {missing_file}")
    asyncio.run(app.startup())
    texts = _texts(env.tg, CTO_TG)
    assert any("2026-02-30" in t and "AAAA-MM-DD" in t for t in texts)
    assert any(str(missing_file) in t and "no legible" in t for t in texts)
    assert app.params.extra_holidays == frozenset({datetime(2026, 12, 24).date()})
    assert (app.data_dir / "heartbeat").exists()


def test_startup_without_warnings_only_notes_that_f2_is_disabled_and_seeds_cto(env: Env) -> None:
    app = env.build()
    asyncio.run(app.startup())
    # Sin avisos de configuración de F1, lo único que llega es que F2 está deshabilitada (D-9).
    assert [s.chat_id for s in env.tg.sent] == [CTO_TG]
    assert "deshabilitada" in env.tg.sent[0].text
    with app.db.read() as conn:
        ctos = repo.active_users(conn, Role.CTO)
    assert [c.telegram_id for c in ctos] == [CTO_TG]


def test_startup_warning_failed_delivery_is_recorded(env: Env) -> None:
    env.tg.fail_next(CTO_TG)
    app = env.build(escalation_business_days=3)
    asyncio.run(app.startup())
    with app.db.read() as conn:
        rows = conn.execute(
            "SELECT status FROM crm_outbox WHERE kind = ?", (app_mod.STARTUP_NOTICE_KIND,)
        ).fetchall()
    assert [r["status"] for r in rows] == ["failed"]


def test_vcrm078_startup_runs_recovery_daily_sweep(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict[str, Any]] = []

    async def fake_sweep(db: Any, telegram: Any, now: datetime, params: Any, **kw: Any) -> None:
        seen.append({"now": now, "params": params, **kw})

    monkeypatch.setattr(app_mod, "daily_sweep", fake_sweep)
    app = env.build(fingerprint_previous_keys="k0")
    asyncio.run(app.startup())
    assert len(seen) == 1
    assert seen[0]["now"] == NOW and seen[0]["params"] is app.params
    assert seen[0]["keys"] == [SECRET_KEY, "k0"] and seen[0]["store"] is app.files


def test_heartbeat_updates_mtime(env: Env) -> None:
    app = env.build()
    path = app.data_dir / "heartbeat"
    app.heartbeat()
    os.utime(path, (0, 0))
    app.heartbeat()
    assert path.stat().st_mtime > 0


# --- Respaldo cableado (VCRM-097, 098) --------------------------------------------------------


def test_backup_job_uses_config_paths_and_runner(env: Env) -> None:
    app = env.build(backup_age_recipient="age1destinatario", backup_remote="remoto:crm")
    asyncio.run(app.startup())
    asyncio.run(app.run_backup_job())
    progs = [c[:2] for c in env.runner.calls]
    assert ["age", "--encrypt"] in progs
    age = next(c for c in env.runner.calls if c[0] == "age")
    assert "age1destinatario" in age
    assert any(c[0] == "rclone" and any("remoto:crm/" in a for a in c) for c in env.runner.calls)
    assert not list((app.data_dir / "backup-tmp").glob("*"))


def test_vcrm098_backup_without_config_warns_cto(env: Env) -> None:
    app = env.build()
    asyncio.run(app.startup())
    asyncio.run(app.run_backup_job())
    assert any("JERICO_CRM_BACKUP_AGE_RECIPIENT" in t for t in _texts(env.tg, CTO_TG))
    mails = [m for m in env.mail.sent if m.to == "cto@k.co"]
    assert any("JERICO_CRM_BACKUP_AGE_RECIPIENT" in m.body for m in mails)


# --- Servicio --------------------------------------------------------------------------------


class StoppingTelegram(FakeTelegram):
    def __init__(self, stop: asyncio.Event) -> None:
        super().__init__()
        self.stop = stop

    async def get_updates(self, offset: int | None, timeout_s: int) -> list[Update]:
        self.stop.set()
        return await super().get_updates(offset, timeout_s)


@pytest.mark.asyncio
async def test_run_service_starts_and_stops_cleanly(tmp_path: Path) -> None:
    stop = asyncio.Event()
    tg = StoppingTelegram(stop)
    settings = _settings(tmp_path)
    await run_service(
        settings,
        telegram=tg,
        email=FakeEmailSender(),
        runner=FakeRunner(),
        clock=FakeClock(NOW).now,
        stop=stop,
    )
    assert (settings.data_dir / "heartbeat").exists()
    assert (settings.data_dir / "crm.db").exists()


@pytest.mark.asyncio
async def test_run_service_logs_start_and_stop(tmp_path: Path) -> None:
    """El arranque y la parada dejan rastro en los logs del contenedor (sin secretos)."""
    from loguru import logger

    lines: list[str] = []
    sink = logger.add(lines.append, format="{message}", level="INFO")
    try:
        stop = asyncio.Event()
        await run_service(
            _settings(tmp_path),
            telegram=StoppingTelegram(stop),
            email=FakeEmailSender(),
            runner=FakeRunner(),
            clock=FakeClock(NOW).now,
            stop=stop,
        )
    finally:
        logger.remove(sink)
    text = "".join(lines)
    assert "jerico-crm iniciado" in text
    assert "jerico-crm detenido" in text


# --- De extremo a extremo: reinicio (VCRM-078, 049) --------------------------------------------


def _msg(update_id: int, user_tg: int, text: str = "", data: str | None = None) -> Update:
    return Update(
        update_id=update_id,
        user_id=user_tg,
        chat_id=user_tg,
        chat_type="private",
        text=text or None,
        callback_data=data,
        callback_id=f"cb{update_id}" if data else None,
    )


def _yes(out: list[Any]) -> str:
    for row in out[-1].buttons:
        for text, data in row:
            if text == "✅":
                return str(data)
    raise AssertionError("sin ✅")


def test_vcrm078_vcrm049_restart_keeps_leads_history_and_resumes_pending(env: Env) -> None:
    env.tg.fail_next(LAW_TG, 2)  # el Telegram del abogado cae en los dos primeros intentos
    app1 = env.build()
    asyncio.run(app1.startup())
    with app1.db.tx() as tx:
        com = repo.insert_user(
            tx, telegram_id=COM_TG, role=Role.COMMERCIAL, email="c@k.co", now=NOW
        )
        repo.insert_user(tx, telegram_id=LAW_TG, role=Role.LAWYER, email="l@k.co", now=NOW)
    asyncio.run(app1.bot.process_update(_msg(1, COM_TG, "/nuevo Ana Pérez; 3001234567")))
    with app1.db.read() as conn:
        (lead,) = repo.leads_of_user(conn, com.id)
    with app1.db.tx() as tx:
        repo.update_lead(tx, lead.id, {"state": LeadState.CONTACTED, **COMPLETE}, now=NOW)
        out = leads.request_accept(tx, com, lead.id, NOW)
    asyncio.run(app1.bot.process_update(_msg(2, COM_TG, data=_yes(out))))
    asyncio.run(app1.worker.deliver_due())
    law_item = _lawyer_telegram_item(app1, LAW_TG)
    assert law_item["status"] != "delivered" and law_item["attempts"] == 1
    app1.close()

    env.clock.advance(seconds=61)
    app2 = env.build()
    asyncio.run(app2.startup())
    with app2.db.read() as conn:
        again = repo.get_lead(conn, lead.id)
        events = conn.execute(
            "SELECT COUNT(*) FROM crm_lead_events WHERE lead_id = ?", (lead.id,)
        ).fetchone()[0]
    assert again is not None and again.state == LeadState.ACCEPTED and events >= 1
    asyncio.run(app2.worker.deliver_due())
    assert _lawyer_telegram_item(app2, LAW_TG)["attempts"] == 2
    env.clock.advance(seconds=300)
    asyncio.run(app2.worker.deliver_due())
    final = _lawyer_telegram_item(app2, LAW_TG)
    assert final["attempts"] == 3 and final["status"] == "delivered"
    assert any(f"L-{lead.id:04d}" in t for t in _texts(env.tg, LAW_TG))


def _lawyer_telegram_item(app: CrmApp, law_tg: int) -> Any:
    with app.db.read() as conn:
        law: User | None = repo.active_user_by_telegram(conn, law_tg)
        assert law is not None
        row = conn.execute(
            "SELECT status, attempts FROM crm_outbox WHERE critical = 1 AND channel = 'telegram' "
            "AND recipient_user_id = ? AND kind = 'aceptacion'",
            (law.id,),
        ).fetchone()
    assert row is not None
    return dict(row)


def test_close_is_idempotent(env: Env) -> None:
    app = env.build()
    app.close()
    app.close()


# --- Fase 2: job, activación y primer intento en línea (F2-T25, T26) -----------------------------

F2_SETTINGS: dict[str, Any] = {
    "imap_host": "imap.example.invalid",
    "imap_username": "buzon@kaisen.test",
    "imap_password": "secreto-imap-no-real",
    "smtp_host": "smtp.example.invalid",
    "smtp_port": 465,
    "smtp_from": "crm@kaisen.test",
}


@pytest.mark.asyncio
async def test_followup_job_se_registra_cada_minuto_con_un_reintento() -> None:
    calls: list[str] = []

    async def noop() -> None:
        return None

    async def followup() -> None:
        calls.append("followup")

    scheduler = CronScheduler()
    register_jobs(scheduler, daily=noop, backup=noop, followup=followup)

    assert FOLLOWUP_CRON == "* * * * *" and FOLLOWUP_JOB == "crm-followup"
    assert scheduler.jobs["crm-followup"].retries == 1
    await scheduler.tick(datetime(2026, 3, 2, 8, 5, tzinfo=UTC))
    await asyncio.gather(*scheduler.tasks.values())
    await scheduler.tick(datetime(2026, 3, 2, 8, 6, tzinfo=UTC))
    await asyncio.gather(*scheduler.tasks.values())
    assert calls == ["followup", "followup"]  # cada minuto


def test_register_jobs_sin_followup_no_cambia_f1() -> None:
    async def noop() -> None:
        return None

    scheduler = CronScheduler()
    register_jobs(scheduler, daily=noop, backup=noop)
    assert set(scheduler.jobs) == {"crm-daily", "crm-backup"}


def test_vcrm160_arranque_registra_job_y_activa(env: Env) -> None:
    app = env.build(**F2_SETTINGS)
    asyncio.run(app.startup())

    with app.db.read() as conn:
        assert repo.get_meta(conn, "f2_activated_at") == to_iso(NOW)
    assert "crm-followup" in app.scheduler.jobs


def test_arranque_sin_configuracion_f2_no_falla_y_deja_f2_deshabilitada(env: Env) -> None:
    app = env.build()  # solo configuración de F1: sin buzón IMAP
    asyncio.run(app.startup())  # no falla

    with app.db.read() as conn:
        assert repo.get_meta(conn, "f2_activated_at") is None
    disabled = [t for t in _texts(env.tg, CTO_TG) if "fase 2" in t and "deshabilitada" in t]
    assert len(disabled) == 1 and "JERICO_CRM_IMAP_HOST" in disabled[0]
    asyncio.run(app.run_followup_job())  # un barrido más: no repite el aviso
    assert len([t for t in _texts(env.tg, CTO_TG) if "deshabilitada" in t]) == 1


def test_vcrm171_arranque_con_base_v1_migra_y_opera(env: Env, tmp_path: Path) -> None:
    data_dir = tmp_path / "crm-data"
    data_dir.mkdir()
    build_v1_database(data_dir / "crm.db")

    app = env.build(**F2_SETTINGS)
    asyncio.run(app.startup())

    with app.db.read() as conn:
        assert repo.get_meta(conn, "schema_version") == "2"
        assert repo.get_lead(conn, 3).state == "accepted"  # type: ignore[union-attr]
        assert repo.get_meta(conn, "f2_activated_at") is not None


def test_el_bot_de_la_app_conoce_los_botones_y_el_comando_de_f2(env: Env) -> None:
    app = env.build(**F2_SETTINGS)
    for action in ("gok", "gno", "gcan", "grew", "freint", "fcancel", "aok", "ano", "rbaja"):
        assert action in app.bot._callbacks  # noqa: SLF001
    assert "pedirautorizacion" in app.bot._commands  # noqa: SLF001
    assert "rewrite" in app.bot._pending  # noqa: SLF001


@pytest.mark.asyncio
async def test_un_ok_dentro_de_franja_dispara_el_primer_intento_en_linea(env: Env) -> None:
    app = env.build(**F2_SETTINGS)
    await app.startup()
    with app.db.tx() as tx:
        com = repo.insert_user(
            tx, telegram_id=COM_TG, role=Role.COMMERCIAL, email="m@k.co", now=NOW
        )
    lead_id = make_lead(app.db, com)
    proposal_id = make_proposal(app.db, lead_id, com)
    update = Update(
        update_id=900,
        user_id=COM_TG,
        chat_id=COM_TG,
        chat_type="private",
        callback_id="cb",
        callback_data=f"v1:gok:{proposal_id}:1",
    )

    await app.bot.process_update(update)
    for _ in range(50):  # el envío corre en una tarea aparte
        if env.mail.sent:
            break
        await asyncio.sleep(0.01)

    assert len(env.mail.sent) == 1  # salió sin esperar al siguiente barrido


# --- Asistente comercial con LLM (VCRM-A30, A31, A35) -----------------------------------------


class _EchoLlm:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, *, system: str, user: str, max_output_tokens: int) -> Any:
        from jerico.crm.llm import LlmResult

        self.calls += 1
        return LlmResult(text="Todo en orden.", input_tokens=10, output_tokens=5)


def _command(app: CrmApp, text: str, uid: int = 1) -> None:
    asyncio.run(
        app.bot.process_update(
            Update(update_id=uid, user_id=CTO_TG, chat_id=CTO_TG, chat_type="private", text=text)
        )
    )


def test_vcrma30_assistant_is_off_by_default_and_silent_at_startup(env: Env) -> None:
    app = env.build()
    asyncio.run(app.startup())
    assert all("asistente" not in s.text.lower() for s in env.tg.sent)
    _command(app, "/asistente pregunta cuántos leads hay")
    assert env.tg.sent[-1].text == "El asistente no está activado."


def test_vcrma31_enabled_without_key_warns_cto_once_and_degrades(env: Env) -> None:
    app = env.build(assistant_enabled=True)
    asyncio.run(app.startup())
    notices = [s.text for s in env.tg.sent if "asistente" in s.text.lower()]
    assert len(notices) == 1 and "OPENAI_API_KEY" in notices[0]
    _command(app, "/asistente pregunta hola")
    assert "no está disponible" in env.tg.sent[-1].text


def test_vcrma30_enabled_with_injected_client_answers_the_cto(env: Env) -> None:
    llm = _EchoLlm()
    app = env.build(assistant_llm=llm, assistant_enabled=True)
    asyncio.run(app.startup())
    assert all("asistente" not in s.text.lower() for s in env.tg.sent)
    _command(app, "/asistente pregunta cómo va el pipeline")
    assert llm.calls == 1
    assert "Todo en orden." in env.tg.sent[-1].text


def test_vcrma34_enabled_with_key_builds_the_real_client_without_leaking_it(env: Env) -> None:
    from jerico.crm.llm import OpenAIResponsesClient

    app = env.build(assistant_enabled=True, openai_api_key="sk-live-secreto")
    assert isinstance(app.assistant_llm, OpenAIResponsesClient)
    assert "sk-live-secreto" not in repr(app.assistant_llm)
    asyncio.run(app.startup())
    assert all("sk-live-secreto" not in s.text for s in env.tg.sent)


def test_outbound_email_wraps_in_dry_run_by_default_and_not_when_disabled(tmp_path: Path) -> None:
    from jerico.crm.app import outbound_email
    from jerico.crm.dryrun import DryRunEmailSender
    from jerico.crm.mail import UnconfiguredEmailSender

    assert isinstance(outbound_email(_settings(tmp_path)), DryRunEmailSender)
    off = _settings(tmp_path, external_comms_dry_run=False)
    assert isinstance(outbound_email(off), UnconfiguredEmailSender)


def test_spec004_closing_commands_are_registered_in_the_real_app(env: Env) -> None:
    app = env.build()
    asyncio.run(app.startup())
    _command(app, "/oferta")
    assert "Ejemplo" in env.tg.sent[-1].text
