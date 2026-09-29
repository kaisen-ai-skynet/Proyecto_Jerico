import pytest

import jerico.tools.base as tools_base


@pytest.fixture(autouse=True)
def audit_log_aislado(tmp_path, monkeypatch):
    """Ningún test escribe en el logs/audit.log real del proyecto."""
    path = tmp_path / "logs" / "audit.log"
    monkeypatch.setattr(tools_base, "AUDIT_LOG", path)
    return path
