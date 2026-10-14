"""Elegibilidad y vector con validación para CRM-consejero (spec 007, VJC-007, VJC-011 a 016)."""

import hashlib
import hmac
from typing import Any

SCHEMA_VERSION = "1.0"

CAPS: dict[str, int] = {
    "antiguedad_dias": 365,
    "dias_sin_interaccion": 365,
    "dias_etapa_actual": 365,
    "eventos_30d": 50,
    "notas": 50,
    "envios": 50,
    "propuestas_pendientes": 50,
    "alertas_pendientes": 50,
    "solicitudes_pendientes": 50,
    "pasos_hechos": 50,
    "pasos_totales": 50,
    "campos_faltantes_handoff": 9,
    "dia_semana": 6,
}

STAGES = {
    "new",
    "contacted",
    "accepted",
    "rejected",
    "nurturing",
    "paused",
    "reactivated",
    "won",
    "lost",
}

CLIENT_TYPES = {"persona_natural", "empresa", "ninguno"}
REJECT_REASONS = {"precio", "momento", "proveedor", "no_interesado", "otro", "ninguno"}
AUTH_STATUSES = {"unauthorized", "authorized"}
CADENCE_STATUSES = {"active", "paused", "completed", "stopped", "ninguna"}


class InvalidVector(ValueError):
    """Excepción lanzada cuando el vector no cumple con la especificación cerrada VJC-012."""


def lead_ref(lead_id: int, key: str) -> str:
    """Calcula la referencia anónima y estable del lead (HMAC-SHA256, 16 hex chars) (VJC-016)."""
    h = hmac.new(key.encode("utf-8"), str(lead_id).encode("utf-8"), hashlib.sha256)
    return h.hexdigest()[:16]


def is_eligible(lead_dict: dict[str, Any]) -> bool:
    """Determina si un lead es elegible para la instantánea (VJC-007, VJC-014).

    Leads suprimidos, en baja (opted_out) o con autorización revocada no son elegibles.
    Leads en estados finales (won, lost) sí son elegibles.
    """
    if lead_dict.get("suppressed_at") is not None:
        return False
    if lead_dict.get("opted_out") is True:
        return False
    if lead_dict.get("authorization_status") == "revoked":
        return False
    return True


def _clamp(val: int | None, min_val: int, max_val: int) -> int:
    if val is None:
        return min_val
    return max(min_val, min(val, max_val))


def build_vector(
    raw_lead: dict[str, Any],
    key: str,
    capture_day: str,
    weekday: int,
) -> dict[str, Any]:
    """Construye el vector estructurado y sin texto libre del lead (VJC-011 a 015)."""
    raw_id = int(raw_lead["id"])
    ref = lead_ref(raw_id, key)

    stage = str(raw_lead.get("stage", "new"))
    if stage not in STAGES:
        stage = "new"

    antiguedad = _clamp(raw_lead.get("created_at_days", 0), 0, CAPS["antiguedad_dias"])
    dias_sin_interaccion = _clamp(
        raw_lead.get("days_since_interaction", 0), 0, CAPS["dias_sin_interaccion"]
    )
    dias_etapa = _clamp(raw_lead.get("days_in_stage", 0), 0, CAPS["dias_etapa_actual"])

    client_type_raw = str(raw_lead.get("client_type", "")).strip().lower()
    if client_type_raw == "persona natural":
        client_type = "persona_natural"
    elif client_type_raw == "empresa":
        client_type = "empresa"
    else:
        client_type = "ninguno"

    reject_reason_raw = str(raw_lead.get("reject_reason", "")).strip().lower()
    if not reject_reason_raw:
        reject_reason = "ninguno"
    elif reject_reason_raw in {"precio", "momento", "proveedor", "no_interesado"}:
        reject_reason = reject_reason_raw
    else:
        reject_reason = "otro"

    auth_raw = str(raw_lead.get("authorization_status", "unauthorized")).strip().lower()
    auth_status = "authorized" if auth_raw == "authorized" else "unauthorized"

    handoff = _clamp(raw_lead.get("missing_handoff_fields", 0), 0, CAPS["campos_faltantes_handoff"])
    eventos_30d = _clamp(raw_lead.get("events_30d", 0), 0, CAPS["eventos_30d"])
    notas = _clamp(raw_lead.get("notes_count", 0), 0, CAPS["notas"])

    cadence_raw = raw_lead.get("cadence_status")
    if cadence_raw in {"active", "paused", "completed", "stopped"}:
        cadence_status = str(cadence_raw)
    else:
        cadence_status = "ninguna"

    cad_pasos_hechos = _clamp(raw_lead.get("cadence_steps_done", 0), 0, CAPS["pasos_hechos"])
    cad_pasos_totales = _clamp(raw_lead.get("cadence_steps_total", 0), 0, CAPS["pasos_totales"])
    cad_envios = _clamp(raw_lead.get("cadence_shipments_done", 0), 0, CAPS["envios"])
    cad_tiene_proxima = bool(raw_lead.get("cadence_has_next_action", False))
    cad_dias_proxima = _clamp(raw_lead.get("cadence_days_next_action", 0), -365, 365)

    propuestas = _clamp(raw_lead.get("pending_proposals", 0), 0, CAPS["propuestas_pendientes"])
    alertas = _clamp(raw_lead.get("pending_alerts", 0), 0, CAPS["alertas_pendientes"])
    solicitudes = _clamp(raw_lead.get("pending_requests", 0), 0, CAPS["solicitudes_pendientes"])

    weekday_val = _clamp(weekday, 0, CAPS["dia_semana"])

    return {
        "schema_version": SCHEMA_VERSION,
        "capture_day": capture_day,
        "lead_ref": ref,
        "stage": stage,
        "antiguedad_dias": antiguedad,
        "dias_sin_interaccion": dias_sin_interaccion,
        "dias_etapa_actual": dias_etapa,
        "aceptado_alguna_vez": bool(raw_lead.get("ever_accepted", False)),
        "rechazo_fue_retractacion": bool(raw_lead.get("retraction", False)),
        "bloqueo_comercial": bool(raw_lead.get("commercial_block", False)),
        "tiene_telefono": bool(str(raw_lead.get("phone", "")).strip()),
        "tiene_correo": bool(str(raw_lead.get("email", "")).strip()),
        "tiene_valor_pactado": bool(str(raw_lead.get("agreed_value", "")).strip()),
        "tiene_servicio_definido": bool(str(raw_lead.get("service", "")).strip()),
        "tiene_comercial_asignado": bool(str(raw_lead.get("assigned_commercial", "")).strip()),
        "client_type": client_type,
        "reject_reason": reject_reason,
        "authorization_status": auth_status,
        "campos_faltantes_handoff": handoff,
        "actividad_eventos_30d": eventos_30d,
        "actividad_notas": notas,
        "cadencia_estado": cadence_status,
        "cadencia_pasos_hechos": cad_pasos_hechos,
        "cadencia_pasos_totales": cad_pasos_totales,
        "cadencia_envios_hechos": cad_envios,
        "cadencia_tiene_proxima_accion": cad_tiene_proxima,
        "cadencia_dias_proxima_accion": cad_dias_proxima,
        "pendientes_propuestas": propuestas,
        "pendientes_alertas": alertas,
        "pendientes_solicitudes": solicitudes,
        "dia_semana": weekday_val,
    }


_EXPECTED_KEYS = {
    "schema_version",
    "capture_day",
    "lead_ref",
    "stage",
    "antiguedad_dias",
    "dias_sin_interaccion",
    "dias_etapa_actual",
    "aceptado_alguna_vez",
    "rechazo_fue_retractacion",
    "bloqueo_comercial",
    "tiene_telefono",
    "tiene_correo",
    "tiene_valor_pactado",
    "tiene_servicio_definido",
    "tiene_comercial_asignado",
    "client_type",
    "reject_reason",
    "authorization_status",
    "campos_faltantes_handoff",
    "actividad_eventos_30d",
    "actividad_notas",
    "cadencia_estado",
    "cadencia_pasos_hechos",
    "cadencia_pasos_totales",
    "cadencia_envios_hechos",
    "cadencia_tiene_proxima_accion",
    "cadencia_dias_proxima_accion",
    "pendientes_propuestas",
    "pendientes_alertas",
    "pendientes_solicitudes",
    "dia_semana",
}

_BOOL_FIELDS = {
    "aceptado_alguna_vez",
    "rechazo_fue_retractacion",
    "bloqueo_comercial",
    "tiene_telefono",
    "tiene_correo",
    "tiene_valor_pactado",
    "tiene_servicio_definido",
    "tiene_comercial_asignado",
    "cadencia_tiene_proxima_accion",
}

_INT_FIELDS_CAPS = {
    "antiguedad_dias": (0, 365),
    "dias_sin_interaccion": (0, 365),
    "dias_etapa_actual": (0, 365),
    "campos_faltantes_handoff": (0, 9),
    "actividad_eventos_30d": (0, 50),
    "actividad_notas": (0, 50),
    "cadencia_pasos_hechos": (0, 50),
    "cadencia_pasos_totales": (0, 50),
    "cadencia_envios_hechos": (0, 50),
    "cadencia_dias_proxima_accion": (-365, 365),
    "pendientes_propuestas": (0, 50),
    "pendientes_alertas": (0, 50),
    "pendientes_solicitudes": (0, 50),
    "dia_semana": (0, 6),
}


def validate_vector(vector: dict[str, Any]) -> None:
    """Valida estrictamente el vector según VJC-012. Lanza InvalidVector ante cualquier anomalía."""
    keys = set(vector.keys())
    missing = _EXPECTED_KEYS - keys
    if missing:
        raise InvalidVector(f"Claves faltantes en vector: {missing}")
    extra = keys - _EXPECTED_KEYS
    if extra:
        raise InvalidVector(f"Claves extra no permitidas en vector: {extra}")

    if vector["schema_version"] != SCHEMA_VERSION:
        raise InvalidVector(f"Versión de esquema inválida: {vector['schema_version']}")

    if not isinstance(vector["lead_ref"], str) or len(vector["lead_ref"]) != 16:
        raise InvalidVector("lead_ref debe ser un string hexadecimal de 16 caracteres")

    for bf in _BOOL_FIELDS:
        val = vector[bf]
        if not isinstance(val, bool):
            raise InvalidVector(f"Campo {bf} debe ser de tipo bool")

    for int_f, (min_v, max_v) in _INT_FIELDS_CAPS.items():
        val = vector[int_f]
        if type(val) is not int:  # rechaza bool y floats
            raise InvalidVector(f"Error de tipo: {int_f} debe ser entero estricto")
        if not (min_v <= val <= max_v):
            raise InvalidVector(f"Entero fuera de tope en {int_f}: {val} not in [{min_v}, {max_v}]")

    if vector["stage"] not in STAGES:
        raise InvalidVector(f"Valor no enumerado para stage: {vector['stage']}")
    if vector["client_type"] not in CLIENT_TYPES:
        raise InvalidVector(f"Valor no enumerado para client_type: {vector['client_type']}")
    if vector["reject_reason"] not in REJECT_REASONS:
        raise InvalidVector(f"Valor no enumerado para reject_reason: {vector['reject_reason']}")
    if vector["authorization_status"] not in AUTH_STATUSES:
        raise InvalidVector(
            f"Valor no enumerado para authorization_status: {vector['authorization_status']}"
        )
    if vector["cadencia_estado"] not in CADENCE_STATUSES:
        raise InvalidVector(f"Valor no enumerado para cadencia_estado: {vector['cadencia_estado']}")
