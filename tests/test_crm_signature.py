"""Puerto de firma, adaptador DocuSeal (API sin verificar en vivo) y DRY_RUN (VCRM-F01..F03)."""

import asyncio
import base64
import json

import httpx
import pytest

from jerico.crm.signature import (
    DocuSealClient,
    DryRunSignature,
    SignatureError,
    SignRequest,
    SignStatus,
)

REQ = SignRequest(
    contract_id=7,
    document_name="contrato-L-0042.pdf",
    document=b"%PDF-1.7 contenido",
    signer_email="cliente@empresa.co",
    signer_name="Ana Pérez",
    idempotency_key="signature_send:7",
)


def _client(handler: httpx.MockTransport) -> DocuSealClient:
    return DocuSealClient(
        base_url="https://firma.kaisen.co/", token="tok-secreto-xyz", transport=handler
    )


def test_send_pdf_posts_the_document_and_returns_the_submission_id() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["token"] = request.headers["x-auth-token"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=[{"submission_id": 991, "id": 5, "status": "sent"}])

    external_id = asyncio.run(_client(httpx.MockTransport(handler)).send(REQ))
    assert external_id == "991"
    assert seen["url"] == "https://firma.kaisen.co/api/submissions/pdf"
    assert seen["token"] == "tok-secreto-xyz"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["documents"][0]["name"] == "contrato-L-0042.pdf"
    assert base64.b64decode(body["documents"][0]["file"]) == REQ.document
    assert body["submitters"] == [{"email": "cliente@empresa.co", "name": "Ana Pérez"}]
    assert body["send_email"] is True


def test_send_docx_uses_the_docx_endpoint() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"submission_id": 3})

    docx = SignRequest(
        **{**REQ.__dict__, "document_name": "contrato.docx", "document": b"PK\x03\x04"}
    )
    assert asyncio.run(_client(httpx.MockTransport(handler)).send(docx)) == "3"
    assert seen["url"].endswith("/api/submissions/docx")


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(401, json={"error": "bad token tok-secreto-xyz"}), "http"),
        (httpx.Response(500, text="boom"), "http"),
        (httpx.Response(200, text="no json"), "bad_response"),
        (httpx.Response(200, json={"nada": 1}), "bad_response"),
        (httpx.Response(200, json=[]), "bad_response"),
    ],
)
def test_send_failures_use_closed_codes_without_leaking(
    response: httpx.Response, code: str
) -> None:
    with pytest.raises(SignatureError) as info:
        asyncio.run(_client(httpx.MockTransport(lambda _r: response)).send(REQ))
    assert info.value.code == code and "tok-secreto-xyz" not in str(info.value)


def test_timeout_and_network_map_to_codes() -> None:
    def slow(_r: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("x")

    def down(_r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("x")

    for handler, code in ((slow, "timeout"), (down, "network")):
        with pytest.raises(SignatureError) as info:
            asyncio.run(_client(httpx.MockTransport(handler)).send(REQ))
        assert info.value.code == code


def test_status_completed_downloads_signed_document_and_audit_log() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/submissions/991":
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "documents": [{"name": "contrato", "url": "https://firma.kaisen.co/f/doc.pdf"}],
                    "audit_log_url": "https://firma.kaisen.co/f/audit.pdf",
                },
            )
        if path == "/f/doc.pdf":
            return httpx.Response(200, content=b"%PDF firmado")
        if path == "/f/audit.pdf":
            return httpx.Response(200, content=b"%PDF auditoria")
        return httpx.Response(404)

    status = asyncio.run(_client(httpx.MockTransport(handler)).status("991"))
    assert status == SignStatus(
        state="completed", signed_document=b"%PDF firmado", audit_document=b"%PDF auditoria"
    )


@pytest.mark.parametrize(
    ("api_status", "state"),
    [
        ("pending", "pending"),
        ("sent", "pending"),
        ("opened", "pending"),
        ("declined", "declined"),
        ("expired", "expired"),
        ("raro", "pending"),
    ],
)
def test_status_maps_provider_states(api_status: str, state: str) -> None:
    client = _client(
        httpx.MockTransport(lambda _r: httpx.Response(200, json={"status": api_status}))
    )
    assert asyncio.run(client.status("1")).state == state


def test_status_errors_and_missing_urls() -> None:
    with pytest.raises(SignatureError) as http:
        asyncio.run(_client(httpx.MockTransport(lambda _r: httpx.Response(404))).status("1"))
    assert http.value.code == "http"
    with pytest.raises(SignatureError) as bad:
        asyncio.run(
            _client(httpx.MockTransport(lambda _r: httpx.Response(200, text="x"))).status("1")
        )
    assert bad.value.code == "bad_response"
    incomplete = _client(
        httpx.MockTransport(lambda _r: httpx.Response(200, json={"status": "completed"}))
    )
    with pytest.raises(SignatureError) as missing:
        asyncio.run(incomplete.status("1"))
    assert missing.value.code == "bad_response"


def test_client_repr_hides_the_token() -> None:
    assert "tok-secreto-xyz" not in repr(
        _client(httpx.MockTransport(lambda _r: httpx.Response(200)))
    )


def test_dry_run_signature_never_calls_the_provider_and_can_be_completed_by_hand() -> None:
    class Boom:
        async def send(self, req: SignRequest) -> str:
            raise AssertionError("no debe llamarse")

        async def status(self, external_id: str) -> SignStatus:
            raise AssertionError("no debe llamarse")

    port = DryRunSignature(Boom())
    assert asyncio.run(port.send(REQ)) == "dryrun-7"
    assert asyncio.run(port.status("dryrun-7")).state == "pending"


def test_status_with_a_non_object_body_is_a_bad_response() -> None:
    client = _client(httpx.MockTransport(lambda _r: httpx.Response(200, json=[1])))
    with pytest.raises(SignatureError) as info:
        asyncio.run(client.status("1"))
    assert info.value.code == "bad_response"
