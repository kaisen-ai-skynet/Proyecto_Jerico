"""Parser del formato estructurado F1 (spec §4.3; VCRM-003–005, 081, 082). Puro, sin E/S."""

import re
import unicodedata
from dataclasses import dataclass

EXAMPLE_REGISTER = (
    "/nuevo Ana Pérez; 300 123 4567; ana@empresa.co; Empresa SAS; Interesada en el plan anual"
)
EXAMPLE_EDIT = "/editar L-0042; correo; ana.perez@empresa.co"

EDITABLE: tuple[str, ...] = (
    "nombre",
    "telefono",
    "correo",
    "empresa",
    "tipo",
    "documento",
    "representante",
    "servicio",
    "valor",
    "plazo",
)

MAX_CALLBACK_BYTES = 64  # límite de Telegram para callback_data
CALLBACK_VERSION = "v1"

_EMAIL_RE = re.compile(r"^[^@\s;]+@[^@\s;]+\.[^@\s;]+$")
_PHONE_STRIP_RE = re.compile(r"[\s\-.()]")
_SHORT_ID_RE = re.compile(r"^[Ll]-(\d+)$")


@dataclass(frozen=True)
class ParseError:
    code: str  # missing | invalid | field_not_editable | invalid_lead_id | bad_format
    field: str | None = None
    example: str | None = None
    editable: tuple[str, ...] = ()


@dataclass(frozen=True)
class RegisterCommand:
    name: str
    phone: str | None
    email: str | None
    company: str | None
    note: str | None


@dataclass(frozen=True)
class EditCommand:
    short_id: int
    field: str
    value: str


@dataclass(frozen=True)
class CallbackData:
    action: str
    args: tuple[str, ...]


def normalize_phone(raw: str, default_cc: str = "57") -> str | None:
    """E.164 o None: `+`/`00` + 8..15 dígitos (sin 0 inicial) o 10 dígitos locales."""
    s = _PHONE_STRIP_RE.sub("", raw)
    if s.startswith("00"):
        s = "+" + s[2:]
    if s.startswith("+"):
        digits = s[1:]
        if digits.isascii() and digits.isdigit() and 8 <= len(digits) <= 15 and digits[0] != "0":
            return "+" + digits
        return None
    if s.isascii() and s.isdigit() and len(s) == 10:
        return f"+{default_cc}{s}"
    return None


def normalize_email(raw: str) -> str | None:
    s = raw.strip().lower()
    return s if _EMAIL_RE.match(s) else None


def parse_short_id(raw: str) -> int | None:
    m = _SHORT_ID_RE.match(raw.strip())
    if m is None:
        return None
    value = int(m.group(1))
    return value if value > 0 else None


def _command_body(text: str, command: str) -> str | None:
    m = re.match(rf"^/{command}(?:@\w+)?(?:\s+|$)(.*)$", text.strip(), re.DOTALL)
    return m.group(1) if m else None


def _ascii_fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def parse_register(text: str) -> RegisterCommand | ParseError:
    body = _command_body(text, "nuevo")
    if body is None:
        return ParseError(code="bad_format", example=EXAMPLE_REGISTER)
    fields = [f.strip() for f in body.split(";", maxsplit=4)]
    fields += [""] * (5 - len(fields))
    name, phone_raw, email_raw, company, note = fields
    if not name:
        return ParseError(code="missing", field="nombre", example=EXAMPLE_REGISTER)
    if not phone_raw and not email_raw:
        return ParseError(code="missing", field="contacto", example=EXAMPLE_REGISTER)
    phone = normalize_phone(phone_raw) if phone_raw else None
    if phone_raw and phone is None:
        return ParseError(code="invalid", field="telefono", example=EXAMPLE_REGISTER)
    email = normalize_email(email_raw) if email_raw else None
    if email_raw and email is None:
        return ParseError(code="invalid", field="correo", example=EXAMPLE_REGISTER)
    return RegisterCommand(
        name=name, phone=phone, email=email, company=company or None, note=note or None
    )


def parse_edit(text: str) -> EditCommand | ParseError:
    body = _command_body(text, "editar")
    if body is None:
        return ParseError(code="bad_format", example=EXAMPLE_EDIT, editable=EDITABLE)
    parts = [p.strip() for p in body.split(";", maxsplit=2)]
    parts += [""] * (3 - len(parts))
    raw_id, raw_field, value = parts
    short_id = parse_short_id(raw_id)
    if short_id is None:
        return ParseError(code="invalid_lead_id", example=EXAMPLE_EDIT, editable=EDITABLE)
    field = _ascii_fold(raw_field)
    if field not in EDITABLE:
        return ParseError(
            code="field_not_editable", field=raw_field, example=EXAMPLE_EDIT, editable=EDITABLE
        )
    if not value:
        return ParseError(code="missing", field="valor", example=EXAMPLE_EDIT)
    if field == "telefono":
        normalized = normalize_phone(value)
        if normalized is None:
            return ParseError(code="invalid", field="telefono", example=EXAMPLE_EDIT)
        value = normalized
    elif field == "correo":
        normalized = normalize_email(value)
        if normalized is None:
            return ParseError(code="invalid", field="correo", example=EXAMPLE_EDIT)
        value = normalized
    return EditCommand(short_id=short_id, field=field, value=value)


def build_callback(action: str, *args: str) -> str:
    """`v1:<acción>:<arg>[:<arg>]`; error si hay segmento vacío, con `:` o > 64 bytes."""
    segments = (action, *args)
    if not args or any(not s or ":" in s for s in segments):
        raise ValueError("invalid callback segment")
    data = ":".join((CALLBACK_VERSION, *segments))
    if len(data.encode("utf-8")) > MAX_CALLBACK_BYTES:
        raise ValueError("callback data exceeds 64 bytes")
    return data


def parse_callback(data: str) -> CallbackData | None:
    if len(data.encode("utf-8")) > MAX_CALLBACK_BYTES:
        return None
    parts = data.split(":")
    if len(parts) < 3 or parts[0] != CALLBACK_VERSION or any(not p for p in parts[1:]):
        return None
    return CallbackData(action=parts[1], args=tuple(parts[2:]))
