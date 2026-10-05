"""Campos del handoff (spec §4.3): validación (VCRM-112) y completitud (VCRM-111). Puro."""

import unicodedata
from dataclasses import dataclass

from jerico.crm.model import Lead

CLIENT_TYPES: tuple[str, ...] = ("persona natural", "empresa")
DOC_TYPES: tuple[str, ...] = ("cédula de ciudadanía", "NIT", "cédula de extranjería", "pasaporte")

LABEL_TYPE = "tipo de cliente"
LABEL_NAME = "nombre o razón social"
LABEL_DOC = "documento de identificación"
LABEL_REP = "representante legal"
LABEL_PHONE = "teléfono de contacto"
LABEL_EMAIL = "correo de contacto"
LABEL_SERVICE = "servicio contratado"
LABEL_VALUE = "valor acordado"
LABEL_TERM = "plazo o fecha de inicio"
REP_IF_COMPANY = f"{LABEL_REP} (obligatorio si es empresa)"

HANDOFF_LABELS: tuple[str, ...] = (
    LABEL_TYPE,
    LABEL_NAME,
    LABEL_DOC,
    LABEL_REP,
    LABEL_PHONE,
    LABEL_EMAIL,
    LABEL_SERVICE,
    LABEL_VALUE,
    LABEL_TERM,
)

# Campo de «/editar» → columna del lead (texto libre no vacío).
_FREE_TEXT: dict[str, str] = {
    "representante": "legal_rep",
    "servicio": "service",
    "valor": "agreed_value",
    "plazo": "start_term",
}
HANDOFF_EDIT_FIELDS: tuple[str, ...] = ("tipo", "documento", *_FREE_TEXT)


@dataclass(frozen=True)
class HandoffValueError:
    code: str  # empty | invalid
    field: str
    allowed: tuple[str, ...] = ()


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", " ".join(text.split()).lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _parse_document(value: str) -> dict[str, str] | None:
    words = value.split()
    # Prefijo más largo primero (por número de palabras).
    for doc_type in sorted(DOC_TYPES, key=lambda t: len(t.split()), reverse=True):
        n = len(doc_type.split())
        if len(words) > n and _fold(" ".join(words[:n])) == _fold(doc_type):
            return {"doc_type": doc_type, "doc_number": " ".join(words[n:])}
    return None


def validate_handoff_value(field: str, value: str) -> dict[str, str] | HandoffValueError:
    """Columnas del lead a actualizar o el error con los valores admitidos (VCRM-112)."""
    if field not in HANDOFF_EDIT_FIELDS:
        raise ValueError(f"not a handoff field: {field}")
    value = value.strip()
    if not value:
        return HandoffValueError(code="empty", field=field)
    if field == "tipo":
        folded = _fold(value)
        for client_type in CLIENT_TYPES:
            if folded == _fold(client_type):
                return {"client_type": client_type}
        return HandoffValueError(code="invalid", field=field, allowed=CLIENT_TYPES)
    if field == "documento":
        parsed = _parse_document(value)
        if parsed is None:
            return HandoffValueError(code="invalid", field=field, allowed=DOC_TYPES)
        return parsed
    return {_FREE_TEXT[field]: value}


def _filled(value: str | None) -> bool:
    return bool(value and value.strip())


def name_or_company(lead: Lead) -> str | None:
    """Nombre (persona natural) o razón social (empresa); sin tipo, el nombre registrado."""
    if lead.client_type == "empresa":
        return lead.company
    return lead.name


def missing_handoff_fields(lead: Lead) -> tuple[str, ...]:
    """Campos obligatorios del handoff sin valor, en el orden de §4.3 (VCRM-111)."""
    typed = lead.client_type in CLIENT_TYPES
    checks: list[tuple[str, bool]] = [
        (LABEL_TYPE, typed),
        (LABEL_NAME, _filled(name_or_company(lead) if typed else lead.name or lead.company)),
        (LABEL_DOC, _filled(lead.doc_type) and _filled(lead.doc_number)),
    ]
    if not typed:
        checks.append((REP_IF_COMPANY, False))
    elif lead.client_type == "empresa":
        checks.append((LABEL_REP, _filled(lead.legal_rep)))
    checks += [
        (LABEL_PHONE, _filled(lead.phone_e164)),
        (LABEL_EMAIL, _filled(lead.email)),
        (LABEL_SERVICE, _filled(lead.service)),
        (LABEL_VALUE, _filled(lead.agreed_value)),
        (LABEL_TERM, _filled(lead.start_term)),
    ]
    return tuple(label for label, ok in checks if not ok)
