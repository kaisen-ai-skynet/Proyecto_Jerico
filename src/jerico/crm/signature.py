"""Puerto de firma electrónica y adaptador DocuSeal (spec 004 §5; VCRM-F01..F03).

DocuSeal autoalojado es el objetivo (Plan Maestro §6); el CRM solo conoce `SignaturePort`. Sin ruta
pública: el estado se consulta saliendo (polling), no por webhook. **La forma de la API de DocuSeal
(`/api/submissions/pdf|docx`, `GET /api/submissions/{id}`) sigue la documentación pública y NO se
probó contra una instancia real**: la primera ejecución real debe confirmarla.

Con DRY_RUN activo `DryRunSignature` sustituye al proveedor: no sale nada a terceros."""

import base64
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx

DEFAULT_TIMEOUT_S = 30.0
SignState = Literal["pending", "completed", "declined", "expired"]


@dataclass(frozen=True)
class SignRequest:
    contract_id: int
    document_name: str
    document: bytes
    signer_email: str
    signer_name: str
    idempotency_key: str


@dataclass(frozen=True)
class SignStatus:
    state: SignState
    signed_document: bytes | None = None
    audit_document: bytes | None = None


class SignatureError(Exception):
    """Fallo del proveedor; `code` cerrado: timeout, network, http, bad_response."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SignaturePort(Protocol):
    async def send(self, req: SignRequest) -> str: ...

    async def status(self, external_id: str) -> SignStatus: ...


_STATES: dict[str, SignState] = {
    "completed": "completed",
    "declined": "declined",
    "expired": "expired",
}


class DocuSealClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout_s
        self._transport = transport

    def __repr__(self) -> str:
        return f"DocuSealClient(base_url={self._base!r})"

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as c:
                response = await c.request(
                    method, url, headers={"X-Auth-Token": self._token}, **kwargs
                )
        except httpx.TimeoutException as exc:
            raise SignatureError("timeout") from exc
        except httpx.HTTPError as exc:
            raise SignatureError("network") from exc
        if response.status_code != 200:
            raise SignatureError("http")
        return response

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise SignatureError("bad_response") from exc

    async def send(self, req: SignRequest) -> str:
        kind = "docx" if req.document_name.lower().endswith(".docx") else "pdf"
        payload = {
            "documents": [
                {"name": req.document_name, "file": base64.b64encode(req.document).decode("ascii")}
            ],
            "submitters": [{"email": req.signer_email, "name": req.signer_name}],
            "send_email": True,
        }
        response = await self._request("POST", f"{self._base}/api/submissions/{kind}", json=payload)
        data = self._json(response)
        item = data[0] if isinstance(data, list) and data else data
        submission = item.get("submission_id") if isinstance(item, dict) else None
        if submission is None:
            raise SignatureError("bad_response")
        return str(submission)

    async def status(self, external_id: str) -> SignStatus:
        data = self._json(await self._request("GET", f"{self._base}/api/submissions/{external_id}"))
        if not isinstance(data, dict):
            raise SignatureError("bad_response")
        state = _STATES.get(str(data.get("status")), "pending")
        if state != "completed":
            return SignStatus(state=state)
        documents = data.get("documents")
        doc_url = documents[0].get("url") if isinstance(documents, list) and documents else None
        audit_url = data.get("audit_log_url")
        if not isinstance(doc_url, str) or not isinstance(audit_url, str):
            raise SignatureError("bad_response")
        signed = (await self._request("GET", doc_url)).content
        audit = (await self._request("GET", audit_url)).content
        return SignStatus(state="completed", signed_document=signed, audit_document=audit)


class DryRunSignature:
    """Sustituye al proveedor mientras DRY_RUN esté activo: nada sale a terceros."""

    def __init__(self, inner: SignaturePort | None = None) -> None:
        self._inner = inner  # se conserva para que el cableado sea idéntico; nunca se invoca

    async def send(self, req: SignRequest) -> str:
        return f"dryrun-{req.contract_id}"

    async def status(self, external_id: str) -> SignStatus:
        return SignStatus(state="pending")
