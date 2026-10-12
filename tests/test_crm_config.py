import os
import tomllib
from datetime import date
from pathlib import Path

import pytest

from crm_support import make_settings
from jerico.crm import CURRENT_PHASE
from jerico.crm.config import (
    ConfigWarning,
    HolidayWarning,
    Params,
    cadence_path,
    effective_params,
    f2_enabled,
    f2_missing,
    load_privacy_notice,
    parse_extra_holidays,
    processors,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith("JERICO_CRM_"):
            monkeypatch.delenv(name)


def test_vcrm162_package_declares_phase_one() -> None:
    assert CURRENT_PHASE == 1


def test_vcrm162_defaults_match_spec_4_6() -> None:
    params, warnings = effective_params(make_settings())
    assert warnings == []
    assert params == Params(
        query_deadline_business_days=10,
        claim_deadline_business_days=15,
        escalation_business_days=2,
        won_attachments_retention_years=10,
        final_state_suppression_months=12,
        unauthorized_warning_days=25,
        unauthorized_max_days=30,
        backup_retention_days=30,
        outbox_interval_s=5.0,
        poll_timeout_s=25,
    )


@pytest.mark.parametrize(
    ("field", "configured", "bound"),
    [
        ("query_deadline_business_days", 12, 10),
        ("claim_deadline_business_days", 20, 15),
        ("escalation_business_days", 3, 2),
        ("final_state_suppression_months", 18, 12),
        ("unauthorized_max_days", 45, 30),
        ("backup_retention_days", 60, 30),
    ],
)
def test_vcrm162_value_above_legal_max_uses_bound(field: str, configured: int, bound: int) -> None:
    params, warnings = effective_params(make_settings(**{field: configured}))
    assert getattr(params, field) == bound
    assert warnings == [ConfigWarning(field, configured, bound)]


def test_vcrm162_won_attachments_below_legal_min_uses_bound() -> None:
    params, warnings = effective_params(make_settings(won_attachments_retention_years=5))
    assert params.won_attachments_retention_years == 10
    assert warnings == [ConfigWarning("won_attachments_retention_years", 5, 10)]


@pytest.mark.parametrize(
    ("field", "default"),
    [
        ("query_deadline_business_days", 10),
        ("claim_deadline_business_days", 15),
        ("escalation_business_days", 2),
        ("won_attachments_retention_years", 10),
        ("final_state_suppression_months", 12),
        ("unauthorized_warning_days", 25),
        ("unauthorized_max_days", 30),
        ("backup_retention_days", 30),
        ("outbox_interval_s", 5.0),
        ("poll_timeout_s", 25),
    ],
)
@pytest.mark.parametrize("configured", [0, -3])
def test_vcrm162_non_positive_value_uses_default(
    field: str, default: float, configured: int
) -> None:
    params, warnings = effective_params(make_settings(**{field: configured}))
    assert getattr(params, field) == default
    assert warnings == [ConfigWarning(field, configured, default)]


def test_vcrm162_j14_warning_not_before_max_is_corrected() -> None:
    params, warnings = effective_params(make_settings(unauthorized_warning_days=30))
    assert params.unauthorized_warning_days == 25
    assert warnings == [ConfigWarning("unauthorized_warning_days", 30, 25)]


def test_vcrm162_j14_warning_corrected_against_stricter_max() -> None:
    params, warnings = effective_params(
        make_settings(unauthorized_warning_days=25, unauthorized_max_days=20)
    )
    assert params.unauthorized_max_days == 20
    assert params.unauthorized_warning_days == 19
    assert warnings == [ConfigWarning("unauthorized_warning_days", 25, 19)]


def test_vcrm162_j14_warning_uses_effective_max_after_cap() -> None:
    params, warnings = effective_params(
        make_settings(unauthorized_warning_days=40, unauthorized_max_days=45)
    )
    assert params.unauthorized_max_days == 30
    assert params.unauthorized_warning_days == 25
    assert warnings == [
        ConfigWarning("unauthorized_max_days", 45, 30),
        ConfigWarning("unauthorized_warning_days", 40, 25),
    ]


def test_vcrm162_stricter_values_are_accepted_without_warning() -> None:
    params, warnings = effective_params(
        make_settings(
            query_deadline_business_days=5,
            claim_deadline_business_days=8,
            escalation_business_days=1,
            won_attachments_retention_years=12,
            final_state_suppression_months=6,
            unauthorized_warning_days=10,
            unauthorized_max_days=15,
            backup_retention_days=7,
        )
    )
    assert warnings == []
    assert params.query_deadline_business_days == 5
    assert params.claim_deadline_business_days == 8
    assert params.escalation_business_days == 1
    assert params.won_attachments_retention_years == 12
    assert params.final_state_suppression_months == 6
    assert params.unauthorized_warning_days == 10
    assert params.unauthorized_max_days == 15
    assert params.backup_retention_days == 7


def test_vcrm162_params_are_immutable() -> None:
    params, _ = effective_params(make_settings())
    with pytest.raises(AttributeError):
        params.query_deadline_business_days = 99  # type: ignore[misc]


def test_vcrm162_smtp_has_no_default_values() -> None:
    settings = make_settings()
    assert settings.smtp_host is None
    assert settings.smtp_port is None
    assert settings.smtp_security is None
    assert settings.smtp_username is None
    assert settings.smtp_password is None
    assert settings.smtp_from is None


def test_vcrm162_secrets_have_no_default_values() -> None:
    settings = make_settings()
    assert settings.telegram_bot_token is None
    assert settings.fingerprint_key is None
    assert settings.fingerprint_previous_keys.get_secret_value() == ""
    assert settings.data_dir == Path("data/crm")


def test_vcrm162_env_prefix_is_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JERICO_CRM_QUERY_DEADLINE_BUSINESS_DAYS", "12")
    params, warnings = effective_params(make_settings())
    assert params.query_deadline_business_days == 10
    assert warnings == [ConfigWarning("query_deadline_business_days", 12, 10)]


def test_vcrm162_local_env_file_is_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text("JERICO_CRM_BACKUP_RETENTION_DAYS=7\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    params, _ = effective_params(make_settings())
    assert params.backup_retention_days == 30


def test_vcrm162_pyproject_declares_entrypoint_and_crm_extra() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["scripts"]["jerico-crm"] == "jerico.crm.app:main"
    assert data["project"]["optional-dependencies"]["crm"] == ["httpx>=0.27,<1"]


# --- Festivos extraordinarios (T02b; VCRM-167, 168) -----------------------------------------


def _no_files(path: Path) -> str:
    raise AssertionError(f"no debía leer {path}")


def test_vcrm167_without_variable_no_extra_holidays() -> None:
    settings = make_settings()
    assert settings.extra_holidays == ""
    assert parse_extra_holidays(settings.extra_holidays, _no_files) == (frozenset(), [])
    params, _ = effective_params(settings)
    assert params.extra_holidays == frozenset()


def test_vcrm167_variable_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JERICO_CRM_EXTRA_HOLIDAYS", "2026-12-24, 2026-12-31")
    assert make_settings().extra_holidays == "2026-12-24, 2026-12-31"


def test_vcrm167_inline_dates() -> None:
    dates, warnings = parse_extra_holidays("2026-12-24, 2026-12-31", _no_files)
    assert dates == frozenset({date(2026, 12, 24), date(2026, 12, 31)})
    assert warnings == []


def test_vcrm167_file_with_comments_and_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "festivos.txt"
    path.write_text("# decretos 2026\n\n2026-11-20  # puente\n  \n2026-12-24\n", encoding="utf-8")
    dates, warnings = parse_extra_holidays(str(path))
    assert dates == frozenset({date(2026, 11, 20), date(2026, 12, 24)})
    assert warnings == []


def test_vcrm167_mixed_dates_and_file_merge_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "festivos.txt"
    path.write_text("2026-12-24\n2026-11-20\n", encoding="utf-8")
    dates, warnings = parse_extra_holidays(f"2026-12-31,{path}, 2026-12-24")
    assert dates == frozenset({date(2026, 12, 31), date(2026, 12, 24), date(2026, 11, 20)})
    assert warnings == []


@pytest.mark.parametrize("entry", ["2026-02-30", "24/12/2026", "2026-1-5", "20261224"])
def test_vcrm168_invalid_date_is_ignored_with_warning(entry: str) -> None:
    dates, warnings = parse_extra_holidays(f"2026-12-24, {entry}", _no_files)
    assert dates == frozenset({date(2026, 12, 24)})
    assert len(warnings) == 1
    assert isinstance(warnings[0], HolidayWarning)
    assert warnings[0].entry == entry
    assert "AAAA-MM-DD" in warnings[0].reason


def test_vcrm168_missing_file_is_ignored_with_warning(tmp_path: Path) -> None:
    missing = tmp_path / "no_existe.txt"
    dates, warnings = parse_extra_holidays(f"{missing}, 2026-12-31")
    assert dates == frozenset({date(2026, 12, 31)})
    assert [w.entry for w in warnings] == [str(missing)]
    assert "archivo no legible" in warnings[0].reason


def test_vcrm168_undecodable_file_is_ignored_with_warning(tmp_path: Path) -> None:
    path = tmp_path / "festivos.txt"
    path.write_bytes(b"\xff\xfe\x00bad")
    dates, warnings = parse_extra_holidays(str(path))
    assert dates == frozenset()
    assert [w.entry for w in warnings] == [str(path)]
    assert "archivo no legible" in warnings[0].reason


def test_vcrm168_invalid_line_in_file_reports_path_and_line(tmp_path: Path) -> None:
    path = tmp_path / "festivos.txt"
    path.write_text("2026-11-20\n# nota\n24/12/2026\n", encoding="utf-8")
    dates, warnings = parse_extra_holidays(str(path))
    assert dates == frozenset({date(2026, 11, 20)})
    assert [w.entry for w in warnings] == [f"{path}:3: 24/12/2026"]
    assert "AAAA-MM-DD" in warnings[0].reason


def test_vcrm167_effective_params_carries_extra_holidays() -> None:
    extra = frozenset({date(2026, 12, 24)})
    params, warnings = effective_params(make_settings(), extra_holidays=extra)
    assert params.extra_holidays == extra
    assert warnings == []


# --- Fase 2: buzón, aviso de privacidad y textos (VCRM-148, 149, 161, 169, 170) ---------------


def _f2_ready(**overrides: object):  # noqa: ANN202 - helper de prueba
    base: dict[str, object] = {
        "imap_host": "imap.example.invalid",
        "imap_username": "crm@example.invalid",
        "imap_password": "secreto-imap-no-real",
        "smtp_host": "smtp.example.invalid",
        "smtp_port": 465,
        "smtp_from": "crm@example.invalid",
    }
    return make_settings(**{**base, **overrides})


def test_vcrm170_repr_no_expone_password() -> None:
    settings = _f2_ready()
    assert "secreto-imap-no-real" not in repr(settings)
    assert "secreto-imap-no-real" not in str(settings)
    assert "secreto-imap-no-real" not in repr(settings.model_dump())
    assert settings.imap_password is not None
    assert settings.imap_password.get_secret_value() == "secreto-imap-no-real"


def test_vcrm169_valores_por_defecto_de_f2() -> None:
    settings = make_settings()
    assert settings.imap_host is None
    assert settings.imap_port == 993
    assert settings.imap_username is None
    assert settings.imap_password is None  # sin valor por defecto
    assert settings.imap_mailbox == "INBOX"
    assert settings.inbox_poll_minutes == 5
    assert settings.privacy_notice_ref == ""
    assert settings.privacy_notice_version == "1.0"
    assert settings.privacy_notice_file is None
    assert settings.cadence_file is None
    assert processors(settings) == ("Telegram", "Google")
    assert effective_params(settings)[0].inbox_poll_minutes == 5


def test_vcrm169_periodo_minimo_1() -> None:
    params, warnings = effective_params(make_settings(inbox_poll_minutes=0))
    assert params.inbox_poll_minutes == 5  # no positivo: rige el valor por defecto
    assert ConfigWarning("inbox_poll_minutes", 0, 5) in warnings
    params, _ = effective_params(make_settings(inbox_poll_minutes=-3))
    assert params.inbox_poll_minutes == 5
    params, warnings = effective_params(make_settings(inbox_poll_minutes=1))
    assert params.inbox_poll_minutes == 1  # el mínimo se acepta
    assert warnings == []
    params, _ = effective_params(make_settings(inbox_poll_minutes=15))
    assert params.inbox_poll_minutes == 15


def test_vcrm149_sin_buzon_ni_correo_deshabilita_y_lista_variables() -> None:
    settings = make_settings()
    assert f2_enabled(settings) is False
    assert f2_missing(settings) == [
        "JERICO_CRM_IMAP_HOST",
        "JERICO_CRM_IMAP_USERNAME",
        "JERICO_CRM_IMAP_PASSWORD",
        "JERICO_CRM_SMTP_HOST",
        "JERICO_CRM_SMTP_PORT",
        "JERICO_CRM_SMTP_FROM",
    ]


def test_vcrm149_configuracion_completa_habilita_con_aviso_y_textos_del_paquete() -> None:
    settings = _f2_ready()
    assert f2_missing(settings) == []
    assert f2_enabled(settings) is True
    notice = load_privacy_notice(settings)
    assert notice is not None and "Ley 1581 de 2012" in notice
    assert tomllib.loads(cadence_path(settings).read_text(encoding="utf-8"))["version"] == "v1"


def test_vcrm149_sin_aviso_deshabilita(tmp_path: Path) -> None:
    missing_file = tmp_path / "no-existe.md"
    settings = _f2_ready(privacy_notice_file=missing_file)
    assert load_privacy_notice(settings) is None  # falla cerrado: NO recurre al aviso del paquete
    assert f2_enabled(settings) is False
    assert f2_missing(settings) == ["JERICO_CRM_PRIVACY_NOTICE_FILE"]

    empty = tmp_path / "vacio.md"
    empty.write_text("  \n", encoding="utf-8")
    assert f2_enabled(_f2_ready(privacy_notice_file=empty)) is False

    own = tmp_path / "aviso.md"
    own.write_text("Aviso propio v2", encoding="utf-8")
    settings = _f2_ready(privacy_notice_file=own)
    assert load_privacy_notice(settings) == "Aviso propio v2"
    assert f2_enabled(settings) is True

    assert f2_missing(_f2_ready(privacy_notice_version="  ")) == [
        "JERICO_CRM_PRIVACY_NOTICE_VERSION"
    ]


def test_vcrm161_sin_textos_de_seguimiento_deshabilita(tmp_path: Path) -> None:
    settings = _f2_ready(cadence_file=tmp_path / "no-existe.toml")
    assert f2_enabled(settings) is False
    assert f2_missing(settings) == ["JERICO_CRM_CADENCE_FILE"]
    own = tmp_path / "cadences.toml"
    own.write_text('version = "propia"\n', encoding="utf-8")
    assert f2_enabled(_f2_ready(cadence_file=own)) is True


def test_vcrm148_encargados_configurables() -> None:
    assert processors(make_settings(data_processors=" Telegram , Google,Zoho ")) == (
        "Telegram",
        "Google",
        "Zoho",
    )
    assert f2_missing(_f2_ready(data_processors=" , ")) == ["JERICO_CRM_DATA_PROCESSORS"]


def test_vcrm148_version_del_aviso_del_paquete_coincide_con_la_configuracion() -> None:
    settings = make_settings()
    notice = load_privacy_notice(settings)
    assert notice is not None
    assert f"Versión {settings.privacy_notice_version}" in notice
    assert "Ley 1581 de 2012" in notice and "BAJA" in notice
