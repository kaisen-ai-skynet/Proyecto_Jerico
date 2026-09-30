import pytest

from jerico.tools.base import BaseTool
from jerico.tools.registry import ToolRegistry


def test_gating_ttl_refresh_and_errors(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("jerico.tools.registry.time.monotonic", lambda: clock[0])
    calls = []
    available = [False]

    def check():
        calls.append(1)
        return available[0]

    registry = ToolRegistry()
    registry.register(BaseTool(name="test"), check_fn=check, check_ttl_s=10)
    assert registry.get("test") is None
    available[0] = True
    assert registry.get("test") is None
    clock[0] = 10
    assert registry.get("test") is not None
    assert len(calls) == 2
    assert registry.get("missing") is None
    with pytest.raises(ValueError):
        registry.register(BaseTool(name="bad"), check_ttl_s=-1)


def test_failed_check_is_unavailable():
    def fail():
        raise OSError("offline")

    registry = ToolRegistry()
    registry.register(BaseTool(name="test"), check_fn=fail)
    assert registry.get("test") is None
