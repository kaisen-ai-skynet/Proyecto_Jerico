import pytest

from jerico.tools.approval import ToolExecutionContext
from jerico.tools.base import BaseTool
from jerico.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_model_confirmation_cannot_grant_approval(audit_log_aislado):
    registry = ToolRegistry()
    registry.register(BaseTool(name="write", readonly=False))
    blocked = await registry.dispatch("write", {"confirm": True}, ToolExecutionContext())
    assert blocked["error"] == "CONFIRMATION_REQUIRED"
    accepted = await registry.dispatch("write", {}, ToolExecutionContext(confirmed=True))
    assert accepted["ok"] is True
    assert '"status": "blocked"' in audit_log_aislado.read_text()
    assert '"status": "executed"' in audit_log_aislado.read_text()
    assert (await registry.dispatch("missing", {}, ToolExecutionContext()))["ok"] is False
