"""Configuración para la capa de decisión transversal (spec 007, sección 4)."""

import os
from pathlib import Path

from jerico.decision.policy import MODOS_VALIDOS


class DecisionSettings:
    """Ajustes de configuración para modos, directorios y cortes de decisión."""

    def __init__(
        self,
        modes: dict[str, str] | None = None,
        kill: bool = False,
        base_dir: Path | str | None = None,
        retention_days: int = 90,
        online: bool = False,
        min_leads: int = 20,
        timeout_s: float = 3.0,
        breaker_threshold: int = 3,
        breaker_cooldown_s: float = 300.0,
        api_key: str | None = None,
        endpoint: str | None = None,
        model: str = "jev-1.13.0",
    ) -> None:
        self.modes = modes or {}
        self.kill = kill
        self.base_dir = Path(base_dir) if base_dir is not None else Path("logs/decision")
        self.retention_days = retention_days
        self.online = online
        self.min_leads = min_leads
        self.timeout_s = timeout_s
        self.breaker_threshold = breaker_threshold
        self.breaker_cooldown_s = breaker_cooldown_s
        self.api_key = api_key
        self.endpoint = endpoint
        self.model = model

    def is_kill_active(self) -> bool:
        """Comprueba si el interruptor general está activo por variable o marcador (VJT-014)."""
        if self.kill:
            return True
        marker1 = self.base_dir / "decision.KILL"
        marker2 = Path("decision.KILL")
        return marker1.exists() or marker2.exists()

    def is_degraded(self, kind: str) -> bool:
        """Comprueba si un tipo sufrió degradación persistente a sombra (VJT-015)."""
        marker = self.base_dir / f"degraded_{kind}.marker"
        return marker.exists()

    def set_degraded(self, kind: str) -> None:
        """Escribe el marcador persistente de degradación a sombra (VJT-015)."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        marker = self.base_dir / f"degraded_{kind}.marker"
        marker.write_text("degradado_por_fallos", encoding="utf-8")

    def mode_for(self, kind: str, default: str = "apagado") -> str:
        """Devuelve el modo operativo para un tipo, considerando kill switch y degradación."""
        if self.is_kill_active():
            return "apagado"
        if self.is_degraded(kind):
            return "sombra"

        configured = self.modes.get(kind)
        if configured and configured in MODOS_VALIDOS:
            return configured
        return default


def load_settings() -> DecisionSettings:
    """Carga la configuración desde las variables de entorno de Jericó."""
    raw_modes = os.getenv("JERICO_DECISION_MODES", "").strip()
    modes: dict[str, str] = {}
    if raw_modes:
        for item in raw_modes.split(","):
            if "=" in item:
                k, v = item.split("=", 1)
                modes[k.strip()] = v.strip().lower()

    kill = os.getenv("JERICO_DECISION_KILL", "false").lower() in ("true", "1", "yes")
    dir_path = os.getenv("JERICO_DECISION_DIR", "logs/decision")
    retention = int(os.getenv("JERICO_DECISION_RETENTION_DAYS", "90"))
    online = os.getenv("JERICO_DECISION_ONLINE", "false").lower() in ("true", "1", "yes")
    min_leads = int(os.getenv("JERICO_DECISION_MIN_LEADS", "20"))
    timeout_s = float(os.getenv("JERICO_DECISION_TIMEOUT_S", "3"))

    raw_breaker = os.getenv("JERICO_DECISION_BREAKER", "3,300").strip()
    breaker_threshold = 3
    breaker_cooldown_s = 300.0
    if "," in raw_breaker:
        parts = raw_breaker.split(",", 1)
        try:
            breaker_threshold = int(parts[0].strip())
            breaker_cooldown_s = float(parts[1].strip())
        except ValueError:
            pass

    api_key = os.getenv("TYPESAFE_API_KEY")
    endpoint = os.getenv("TYPESAFE_ENDPOINT")
    model = os.getenv("TYPESAFE_MODEL", "jev-1.13.0")

    return DecisionSettings(
        modes=modes,
        kill=kill,
        base_dir=Path(dir_path),
        retention_days=retention,
        online=online,
        min_leads=min_leads,
        timeout_s=timeout_s,
        breaker_threshold=breaker_threshold,
        breaker_cooldown_s=breaker_cooldown_s,
        api_key=api_key,
        endpoint=endpoint,
        model=model,
    )
