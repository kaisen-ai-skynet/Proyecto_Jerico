"""Configuración propia del CRM (prefijo `JERICO_CRM_`) y topes legales (VCRM-162)."""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class CrmSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JERICO_CRM_", env_file=".env", extra="ignore")

    # Secretos: sin valor por defecto; `app.py` exige token y clave al arrancar.
    telegram_bot_token: SecretStr | None = None
    fingerprint_key: SecretStr | None = None
    fingerprint_previous_keys: SecretStr = SecretStr("")
    seed_cto_telegram_id: str = ""
    seed_cto_email: str = ""
    data_dir: Path = Path("data/crm")

    # Correo interno: sin valor por defecto (decisión P-27).
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_security: Literal["starttls", "ssl"] | None = None
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None

    backup_age_recipient: str | None = None
    backup_remote: str | None = None

    # Plazos sin restricciones de pydantic: el tope lo aplica `effective_params` (VCRM-162).
    query_deadline_business_days: int = 10
    claim_deadline_business_days: int = 15
    escalation_business_days: int = 2
    won_attachments_retention_years: int = 10
    final_state_suppression_months: int = 12
    unauthorized_warning_days: int = 25
    unauthorized_max_days: int = 30
    backup_retention_days: int = 30
    outbox_interval_s: float = 5.0
    poll_timeout_s: int = 25

    # Festivos extraordinarios: fechas ISO y/o rutas de archivo separadas por comas (VCRM-167).
    extra_holidays: str = ""

    # --- Fase 2 ---
    # Buzón de respuestas: sondeo IMAP saliente de solo lectura, sin ruta pública (Q-2, VCRM-169).
    imap_host: str | None = None
    imap_port: int = 993
    imap_username: str | None = None
    imap_password: SecretStr | None = None
    imap_mailbox: str = "INBOX"
    inbox_poll_minutes: int = 5  # mínimo 1 (LIMITS)

    # Aviso de privacidad (VCRM-148, 149): por defecto el del paquete (resources/); un archivo
    # propio lo sustituye y, si no se puede leer, F2 queda deshabilitada (falla cerrado).
    privacy_notice_ref: str = ""  # URL de la política publicada, si existe (opcional)
    privacy_notice_version: str = "1.0"
    privacy_notice_file: Path | None = None
    data_processors: str = "Telegram,Google"
    # Textos de seguimiento por motivo y paso (VCRM-161): por defecto los del paquete.
    cadence_file: Path | None = None


@dataclass(frozen=True)
class Params:
    query_deadline_business_days: int
    claim_deadline_business_days: int
    escalation_business_days: int
    won_attachments_retention_years: int
    final_state_suppression_months: int
    unauthorized_warning_days: int
    unauthorized_max_days: int
    backup_retention_days: int
    outbox_interval_s: float
    poll_timeout_s: int
    extra_holidays: frozenset[date] = field(default_factory=frozenset)
    inbox_poll_minutes: int = 5


@dataclass(frozen=True)
class ConfigWarning:
    param: str
    rejected: float
    effective: float


class _Kind(Enum):
    MAX = "max"
    MIN = "min"


# param -> (valor por defecto, tipo de límite legal, límite legal); None = sin límite legal.
LIMITS: dict[str, tuple[float, _Kind | None, float | None]] = {
    "query_deadline_business_days": (10, _Kind.MAX, 10),
    "claim_deadline_business_days": (15, _Kind.MAX, 15),
    "escalation_business_days": (2, _Kind.MAX, 2),
    "won_attachments_retention_years": (10, _Kind.MIN, 10),
    "final_state_suppression_months": (12, _Kind.MAX, 12),
    "unauthorized_max_days": (30, _Kind.MAX, 30),
    "unauthorized_warning_days": (25, None, None),
    "backup_retention_days": (30, _Kind.MAX, 30),
    "outbox_interval_s": (5.0, None, None),
    "poll_timeout_s": (25, None, None),
    "inbox_poll_minutes": (5, _Kind.MIN, 1),  # VCRM-169: no menos de 1 minuto
}


def _bounded(value: float, default: float, kind: _Kind | None, bound: float | None) -> float:
    if value <= 0:
        return default
    if bound is not None and kind is _Kind.MAX and value > bound:
        return bound
    if bound is not None and kind is _Kind.MIN and value < bound:
        return bound
    return value


def effective_params(
    settings: CrmSettings, extra_holidays: frozenset[date] = frozenset()
) -> tuple[Params, list[ConfigWarning]]:
    """Valor vigente de cada parámetro y lista de avisos para el CTO (VCRM-162). Pura.

    `extra_holidays` es el resultado de `parse_extra_holidays` (VCRM-167).
    """
    raw = {name: getattr(settings, name) for name in LIMITS}
    values = {
        name: _bounded(raw[name], default, kind, bound)
        for name, (default, kind, bound) in LIMITS.items()
    }
    # J-14: el aviso debe llegar antes del plazo máximo vigente.
    max_days = values["unauthorized_max_days"]
    if values["unauthorized_warning_days"] >= max_days:
        default_warning = LIMITS["unauthorized_warning_days"][0]
        values["unauthorized_warning_days"] = min(default_warning, max_days - 1)
    warnings = [
        ConfigWarning(name, raw[name], values[name]) for name in LIMITS if values[name] != raw[name]
    ]
    params = Params(
        query_deadline_business_days=int(values["query_deadline_business_days"]),
        claim_deadline_business_days=int(values["claim_deadline_business_days"]),
        escalation_business_days=int(values["escalation_business_days"]),
        won_attachments_retention_years=int(values["won_attachments_retention_years"]),
        final_state_suppression_months=int(values["final_state_suppression_months"]),
        unauthorized_warning_days=int(values["unauthorized_warning_days"]),
        unauthorized_max_days=int(values["unauthorized_max_days"]),
        backup_retention_days=int(values["backup_retention_days"]),
        outbox_interval_s=float(values["outbox_interval_s"]),
        poll_timeout_s=int(values["poll_timeout_s"]),
        extra_holidays=extra_holidays,
        inbox_poll_minutes=int(values["inbox_poll_minutes"]),
    )
    return params, warnings


def default_params() -> Params:
    """Parámetros por defecto (los de `LIMITS`), sin festivos extraordinarios."""
    values = {name: default for name, (default, _, _) in LIMITS.items()}
    return Params(
        query_deadline_business_days=int(values["query_deadline_business_days"]),
        claim_deadline_business_days=int(values["claim_deadline_business_days"]),
        escalation_business_days=int(values["escalation_business_days"]),
        won_attachments_retention_years=int(values["won_attachments_retention_years"]),
        final_state_suppression_months=int(values["final_state_suppression_months"]),
        unauthorized_warning_days=int(values["unauthorized_warning_days"]),
        unauthorized_max_days=int(values["unauthorized_max_days"]),
        backup_retention_days=int(values["backup_retention_days"]),
        outbox_interval_s=float(values["outbox_interval_s"]),
        poll_timeout_s=int(values["poll_timeout_s"]),
        inbox_poll_minutes=int(values["inbox_poll_minutes"]),
    )


# --- Festivos extraordinarios (VCRM-167, 168; decisión K-6) ---------------------------------

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INVALID_DATE_REASON = "fecha no válida; formato AAAA-MM-DD"


@dataclass(frozen=True)
class HolidayWarning:
    entry: str  # entrada, ruta o `ruta:línea: valor` rechazada
    reason: str


def _read_utf8(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_date(text: str) -> date | None:
    if not _ISO_DATE_RE.match(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_extra_holidays(
    raw: str, read_text: Callable[[Path], str] = _read_utf8
) -> tuple[frozenset[date], list[HolidayWarning]]:
    """Fechas ISO y/o archivos (una fecha por línea, `#` comentario). Nunca lanza (VCRM-168)."""
    dates: set[date] = set()
    warnings: list[HolidayWarning] = []
    for token in (t.strip() for t in raw.split(",")):
        if not token:
            continue
        if token[0].isdigit():
            parsed = _parse_date(token)
            if parsed is None:
                warnings.append(HolidayWarning(token, INVALID_DATE_REASON))
            else:
                dates.add(parsed)
            continue
        try:
            text = read_text(Path(token))
        except (OSError, UnicodeDecodeError) as exc:
            warnings.append(HolidayWarning(token, f"archivo no legible: {exc}"))
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            value = line.split("#", 1)[0].strip()
            if not value:
                continue
            parsed = _parse_date(value)
            if parsed is None:
                warnings.append(HolidayWarning(f"{token}:{number}: {value}", INVALID_DATE_REASON))
            else:
                dates.add(parsed)
    return frozenset(dates), warnings


# --- Habilitación de la fase 2 (VCRM-148, 149, 161; plan-f2 D-9) ----------------------------

RESOURCES_DIR = Path(__file__).parent / "resources"
BUNDLED_PRIVACY_NOTICE = RESOURCES_DIR / "aviso-privacidad.md"
BUNDLED_CADENCES = RESOURCES_DIR / "cadences.toml"


def _env(field_name: str) -> str:
    return f"JERICO_CRM_{field_name.upper()}"


def _read_text(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return text if text.strip() else None


def load_privacy_notice(settings: CrmSettings) -> str | None:
    """Texto del aviso de privacidad vigente; `None` si el archivo configurado no se puede leer.

    Sin `privacy_notice_file` rige el aviso del paquete. Un archivo configurado que falla NO
    recurre al del paquete: se prefiere dejar F2 deshabilitada a enviar un aviso no esperado.
    """
    path = settings.privacy_notice_file or BUNDLED_PRIVACY_NOTICE
    return _read_text(path)


def cadence_path(settings: CrmSettings) -> Path:
    """Archivo TOML con los textos de seguimiento (`cadence_file` o el del paquete)."""
    return settings.cadence_file or BUNDLED_CADENCES


def processors(settings: CrmSettings) -> tuple[str, ...]:
    """Encargados del tratamiento que se mencionan en la solicitud de autorización."""
    return tuple(p.strip() for p in settings.data_processors.split(",") if p.strip())


def f2_missing(settings: CrmSettings) -> list[str]:
    """Variables de entorno que impiden activar la fase 2 (nombres, nunca valores)."""
    missing: list[str] = []
    checks: tuple[tuple[str, object], ...] = (
        ("imap_host", settings.imap_host),
        ("imap_username", settings.imap_username),
        ("imap_password", settings.imap_password and settings.imap_password.get_secret_value()),
        ("smtp_host", settings.smtp_host),
        ("smtp_port", settings.smtp_port),
        ("smtp_from", settings.smtp_from),
        ("privacy_notice_version", settings.privacy_notice_version.strip()),
        ("data_processors", processors(settings)),
    )
    missing.extend(_env(name) for name, value in checks if not value)
    if load_privacy_notice(settings) is None:
        missing.append(_env("privacy_notice_file"))
    if _read_text(cadence_path(settings)) is None:
        missing.append(_env("cadence_file"))
    return missing


def f2_enabled(settings: CrmSettings) -> bool:
    """La fase 2 solo se activa con buzón, correo de salida, aviso y textos disponibles (D-9)."""
    return not f2_missing(settings)
