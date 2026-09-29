import json
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, ConfigDict

AUDIT_LOG = Path("logs/audit.log")


class BaseTool(BaseModel):
    """Tool de Jericó. Read-only por defecto; writes exigen confirm=True + audit log."""

    # Inmutable: las instancias del REGISTRY son compartidas; nadie apaga `readonly`.
    model_config = ConfigDict(frozen=True)

    name: str
    description: str = ""
    readonly: bool = True

    def run(self, confirm: bool = False, **kwargs: object) -> dict[str, object]:
        # `is True` estricto: args de un LLM pueden traer confirm="false" (truthy).
        if not self.readonly and confirm is not True:
            self._audit(status="blocked", confirm=confirm, args=kwargs)
            return {
                "ok": False,
                "error": "CONFIRMATION_REQUIRED",
                "message": "Tool de escritura: requiere confirm=True tras aprobación explícita.",
            }
        self._audit(status="executed", confirm=confirm, args=kwargs)
        return self._execute(**kwargs)

    def _execute(self, **kwargs: object) -> dict[str, object]:
        return {"ok": True, "tool": self.name, "note": "stub v0 sin integración externa"}

    def _audit(self, *, status: str, confirm: object, args: dict[str, object]) -> None:
        # Los kwargs del llamador van anidados en `args`: no pueden pisar ts/tool/status.
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "tool": self.name,
            "status": status,
            "confirm": confirm,
            "args": args,
        }
        logger.info(f"[audit] {entry}")
        try:
            AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
            with AUDIT_LOG.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except OSError as exc:
            logger.warning(f"audit log no escribible: {exc}")
