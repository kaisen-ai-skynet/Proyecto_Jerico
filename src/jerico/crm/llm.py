"""Puerto y cliente del LLM del asistente comercial (OpenAI Responses API; VCRM-A14, A32, A34).

Solo `httpx`: el SDK `openai` no forma parte de la imagen del CRM. Sin reintentos (costo) y sin
reproducir nunca cuerpos de respuesta ni cabeceras en los errores, para no filtrar la llave."""

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_TIMEOUT_S = 20.0


@dataclass(frozen=True)
class LlmResult:
    text: str
    input_tokens: int
    output_tokens: int
    truncated: bool = False


class LlmError(Exception):
    """Fallo del proveedor; `code` cerrado: timeout, network, http, bad_response, empty, refused."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class LlmPort(Protocol):
    async def complete(self, *, system: str, user: str, max_output_tokens: int) -> LlmResult: ...


def _extract(data: Any) -> LlmResult:
    if not isinstance(data, dict):
        raise LlmError("bad_response")
    texts: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "refusal":
                raise LlmError("refused")
            if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                texts.append(part["text"])
    text = "".join(texts).strip()
    if not text:
        raise LlmError("empty")
    raw_usage = data.get("usage")
    usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
    return LlmResult(
        text=text,
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        truncated=data.get("status") == "incomplete",
    )


class OpenAIResponsesClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        effort: str,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._effort = effort
        self._timeout_s = timeout_s
        self._transport = transport

    def __repr__(self) -> str:
        return f"OpenAIResponsesClient(model={self._model!r}, effort={self._effort!r})"

    async def complete(self, *, system: str, user: str, max_output_tokens: int) -> LlmResult:
        payload = {
            "model": self._model,
            "instructions": system,
            "input": user,
            "reasoning": {"effort": self._effort},
            "max_output_tokens": max_output_tokens,
            "store": False,  # VCRM-A14: sin retención del lado del proveedor
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_s, transport=self._transport
            ) as client:
                response = await client.post(
                    RESPONSES_URL,
                    json=payload,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
        except httpx.TimeoutException as exc:
            raise LlmError("timeout") from exc
        except httpx.HTTPError as exc:
            raise LlmError("network") from exc
        if response.status_code != 200:
            raise LlmError("http")
        try:
            data = response.json()
        except ValueError as exc:
            raise LlmError("bad_response") from exc
        return _extract(data)
