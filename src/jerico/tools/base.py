from datetime import UTC, datetime
from pathlib import Path

from loguru import logger
from pydantic import BaseModel

AUDIT_LOG = Path("logs/audit.log")


class BaseTool(BaseModel):
    """Tool de Jericó. Read-only por defecto; writes exigen confirm=True + audit log."""

    name: str
    description: str = ""
    readonly: bool = True

    def run(self, confirm: bool = False, **kwargs: object) -> dict[str, object]:
        if not self.readonly and not confirm:
            return {
                "ok": False,
                "error": "CONFIRMATION_REQUIRED",
                "message": "Tool de escritura: requiere confirm=True tras aprobación explícita.",
            }
        self._audit(confirm=confirm, **kwargs)
        return self._execute(**kwargs)

    def _execute(self, **kwargs: object) -> dict[str, object]:
        return {"ok": True, "tool": self.name, "note": "stub v0 sin integración externa"}

    def _audit(self, **payload: object) -> None:
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "tool": self.name,
            **payload,
        }
        logger.info(f"[audit] {entry}")
        try:
            AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
            with AUDIT_LOG.open("a", encoding="utf-8") as fh:
                fh.write(str(entry) + "\n")
        except OSError as exc:
            logger.warning(f"audit log no escribible: {exc}")
