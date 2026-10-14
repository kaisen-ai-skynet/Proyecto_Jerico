"""Base transversal de la spec 004: idempotencia, DRY_RUN y esquemas compartidos."""

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crm_support import FakeEmailSender, make_settings
from jerico.crm.db import CrmDatabase
from jerico.crm.dryrun import DryRunEmailSender, dry_run_active
from jerico.crm.idempotency import claim, make_key
from jerico.schemas import Cotizacion, CotizacionLinea, Lead, PaqueteContrato, export_json_schemas

NOW = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith(("JERICO_CRM_", "JERICO_EXTERNAL")):
            monkeypatch.delenv(name)


# --- Idempotencia (Plan Maestro §4) -----------------------------------------------------------


def test_make_key_is_deterministic_and_scoped() -> None:
    assert make_key("package_send", 7, "v2", "telegram") == "package_send:7:v2:telegram"
    assert make_key("a", 1) != make_key("a", 2)
    with pytest.raises(ValueError):
        make_key("")


def test_claim_is_true_once_per_key(tmp_path: Path) -> None:
    db = CrmDatabase(tmp_path / "crm.db")
    try:
        with db.tx() as tx:
            assert claim(tx, "package_send:1:v1:email", NOW) is True
            assert claim(tx, "package_send:1:v1:email", NOW) is False
            assert claim(tx, "package_send:1:v1:telegram", NOW) is True
    finally:
        db.close()


# --- DRY_RUN (Plan Maestro §4) ------------------------------------------------------------


def test_dry_run_is_on_by_default_and_can_be_turned_off(monkeypatch: pytest.MonkeyPatch) -> None:
    assert make_settings().external_comms_dry_run is True
    assert dry_run_active(make_settings()) is True
    monkeypatch.setenv("JERICO_EXTERNAL_COMMS_DRY_RUN", "false")
    assert dry_run_active(make_settings()) is False


def test_dry_run_sender_redirects_everything_to_the_cto() -> None:
    inner = FakeEmailSender()
    sender = DryRunEmailSender(inner, "cto@kaisen.co")
    result = asyncio.run(
        sender.send("cliente@empresa.co", "Hola", "Cuerpo", {"List-Unsubscribe": "<mailto:x>"})
    )
    assert result.delivered is True
    assert [m.to for m in inner.sent] == ["cto@kaisen.co"]
    sent = inner.sent[0]
    assert sent.subject.startswith("[DRY_RUN → cliente@empresa.co] ")
    assert "cliente@empresa.co" not in sent.headers.get("To", "")
    assert "Cuerpo" in sent.body and "DRY_RUN" in sent.body


def test_dry_run_sender_without_cto_address_refuses_to_send() -> None:
    inner = FakeEmailSender()
    result = asyncio.run(DryRunEmailSender(inner, "").send("c@x.co", "s", "b"))
    assert result.delivered is False and result.permanent is True
    assert inner.attempts == []


# --- Esquemas compartidos F2/F4/F6 ----------------------------------------------------------


def _quote() -> Cotizacion:
    return Cotizacion(
        currency="COP",
        lines=[
            CotizacionLinea(description="Chatbot", quantity=2, unit_price=1_500_000),
            CotizacionLinea(description="Soporte", quantity=1, unit_price=500_000),
        ],
        payment_terms="50 % anticipo",
    )


def test_quote_total_is_computed_by_code_not_by_the_model() -> None:
    assert _quote().total == 3_500_000


@pytest.mark.parametrize(
    "bad",
    [
        {"currency": "pesos"},
        {"lines": []},
        {"lines": [{"description": "x", "quantity": 0, "unit_price": 1}]},
        {"lines": [{"description": "x", "quantity": 1, "unit_price": -1}]},
    ],
)
def test_quote_rejects_invalid_values(bad: dict[str, object]) -> None:
    base: dict[str, object] = {
        "currency": "COP",
        "lines": [{"description": "x", "quantity": 1, "unit_price": 1}],
        "payment_terms": "contado",
    }
    with pytest.raises(ValueError):
        Cotizacion(**{**base, **bad})  # type: ignore[arg-type]


def test_package_roundtrips_through_json() -> None:
    package = PaqueteContrato(
        lead=Lead(id=1, name="Ana", state="accepted"),
        cotizacion=_quote(),
        version=1,
        legal_basis="authorization",
        generated_at=NOW,
    )
    again = PaqueteContrato.model_validate_json(package.model_dump_json())
    assert again == package


def test_exported_json_schemas_are_in_sync_with_the_models(tmp_path: Path) -> None:
    export_json_schemas(tmp_path)
    names = sorted(p.name for p in tmp_path.glob("*.json"))
    assert names == ["cotizacion.schema.json", "lead.schema.json", "paquete_contrato.schema.json"]
    committed = Path(__file__).resolve().parents[1] / "schemas"
    for name in names:
        assert json.loads((tmp_path / name).read_text()) == json.loads(
            (committed / name).read_text()
        ), f"schemas/{name} desactualizado: ejecuta export_json_schemas('schemas')"


def test_dry_run_sender_redirects_attachments_too() -> None:
    inner = FakeEmailSender()
    sender = DryRunEmailSender(inner, "cto@kaisen.co")
    result = asyncio.run(
        sender.send_with_attachment(
            "cliente@empresa.co", "Contrato", "Hola", filename="c.pdf", content=b"%PDF-x"
        )
    )
    assert result.delivered is True
    (sent,) = inner.attachments
    assert sent.to == "cto@kaisen.co" and sent.subject.startswith("[DRY_RUN → cliente@empresa.co]")
    assert sent.content == b"%PDF-x" and "Destinatario original: cliente@empresa.co" in sent.body


def test_dry_run_attachment_without_cto_or_support_refuses() -> None:
    inner = FakeEmailSender()
    refused = asyncio.run(
        DryRunEmailSender(inner, "").send_with_attachment(
            "c@x.co", "s", "b", filename="f", content=b""
        )
    )
    assert refused.delivered is False and inner.attachments == []

    class NoAttachments:
        async def send(self, to, subject, body, headers=None):  # type: ignore[no-untyped-def]
            raise AssertionError

    unsupported = asyncio.run(
        DryRunEmailSender(NoAttachments(), "cto@k.co").send_with_attachment(  # type: ignore[arg-type]
            "c@x.co", "s", "b", filename="f", content=b""
        )
    )
    assert unsupported.delivered is False
