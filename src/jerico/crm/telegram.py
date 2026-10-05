"""Cliente delgado de la Bot API de Telegram sobre httpx (plan §6.1; VCRM-008, 012).

El token solo forma parte de la URL interna: nunca se registra ni aparece en errores
(se informa el método y el código HTTP o el tipo de excepción).
"""

import contextlib
import logging
import os
import uuid
from pathlib import Path
from typing import Any

import httpx

from jerico.crm.ports import DownloadResult, FileKind, FileRef, InlineButton, SendResult, Update

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"
DEFAULT_TIMEOUT_S = 30.0
_FILE_KINDS: tuple[FileKind, ...] = ("photo", "document", "voice")


class TelegramApiError(Exception):
    """Fallo de la Bot API con mensaje saneado (sin token)."""


def _fail(method: str, cause: str) -> TelegramApiError:
    logger.warning("telegram %s failed: %s", method, cause)
    return TelegramApiError(f"{method}: {cause}")


def _cause(exc: httpx.HTTPError) -> str:
    return "timeout" if isinstance(exc, httpx.TimeoutException) else type(exc).__name__


def _file_ref(message: dict[str, Any]) -> FileRef | None:
    for kind in _FILE_KINDS:
        item = message.get(kind)
        if not item:
            continue
        if kind == "photo":  # lista de tamaños: el último es el mayor
            item = item[-1]
        return FileRef(file_id=item["file_id"], size=item.get("file_size"), kind=kind)
    return None


def normalize_update(raw: dict[str, Any]) -> Update:
    """Normaliza un `Update` de la Bot API (mensaje, archivo o `callback_query`)."""
    update_id = int(raw["update_id"])
    if "callback_query" in raw:
        cb = raw["callback_query"]
        chat = (cb.get("message") or {}).get("chat") or {}
        return Update(
            update_id=update_id,
            user_id=(cb.get("from") or {}).get("id"),
            chat_id=chat.get("id"),
            chat_type=chat.get("type"),
            callback_id=cb.get("id"),
            callback_data=cb.get("data"),
        )
    message = raw.get("message") or {}
    chat = message.get("chat") or {}
    return Update(
        update_id=update_id,
        user_id=(message.get("from") or {}).get("id"),
        chat_id=chat.get("id"),
        chat_type=chat.get("type"),
        text=message.get("text"),
        caption=message.get("caption"),
        file=_file_ref(message),
    )


def _send_result(method: str, result: Any) -> SendResult:
    message_id = result.get("message_id") if isinstance(result, dict) else None
    if message_id is None:
        _fail(method, "missing message_id")
        return SendResult(delivered=False, error=f"{method}: missing message_id")
    return SendResult(delivered=True, message_id=str(message_id))


class HttpxTelegramClient:
    def __init__(
        self,
        token: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._token = token
        self._client = httpx.AsyncClient(transport=transport, timeout=timeout_s)

    def __repr__(self) -> str:
        return "HttpxTelegramClient(token=***)"

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, timeout_s: float | None = None, **kwargs: Any) -> Any:
        """Devuelve `result` si `ok=true`; si no, lanza `TelegramApiError` saneado."""
        url = f"{API_BASE}/bot{self._token}/{method}"
        if timeout_s is not None:
            kwargs["timeout"] = timeout_s
        try:
            response = await self._client.post(url, **kwargs)
        except httpx.HTTPError as exc:
            raise _fail(method, _cause(exc)) from None
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code != 200 or not payload.get("ok"):
            raise _fail(method, f"HTTP {response.status_code}") from None
        return payload.get("result")

    async def get_updates(self, offset: int | None, timeout_s: int) -> list[Update]:
        body: dict[str, Any] = {
            "timeout": timeout_s,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            body["offset"] = offset
        result = await self._call("getUpdates", timeout_s=timeout_s + 10, json=body)
        return [normalize_update(raw) for raw in result or []]

    async def send_message(
        self, chat_id: int, text: str, buttons: list[list[InlineButton]] | None = None
    ) -> SendResult:
        body: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if buttons:
            body["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": b.text, "callback_data": b.callback_data} for b in row]
                    for row in buttons
                ]
            }
        try:
            result = await self._call("sendMessage", json=body)
        except TelegramApiError as exc:
            return SendResult(delivered=False, error=str(exc))
        return _send_result("sendMessage", result)

    async def answer_callback(self, callback_id: str, text: str | None = None) -> None:
        body: dict[str, Any] = {"callback_query_id": callback_id}
        if text is not None:
            body["text"] = text
        with contextlib.suppress(TelegramApiError):
            await self._call("answerCallbackQuery", json=body)

    async def send_document(self, chat_id: int, path: Path, caption: str) -> SendResult:
        try:
            with path.open("rb") as fh:
                result = await self._call(
                    "sendDocument",
                    data={"chat_id": str(chat_id), "caption": caption},
                    files={"document": (path.name, fh)},
                )
        except TelegramApiError as exc:
            return SendResult(delivered=False, error=str(exc))
        return _send_result("sendDocument", result)

    async def download_file(self, file_id: str, dest: Path, max_bytes: int) -> DownloadResult:
        """Descarga en *streaming* a un temporal junto a `dest`; nunca deja archivos parciales."""
        try:
            info = await self._call("getFile", json={"file_id": file_id})
        except TelegramApiError as exc:
            return DownloadResult(ok=False, error=str(exc))
        declared = info.get("file_size") if isinstance(info, dict) else None
        if declared is not None and declared > max_bytes:
            return DownloadResult(ok=False, size=declared, error="too_large")
        file_path = info.get("file_path") if isinstance(info, dict) else None
        if not file_path:
            return DownloadResult(ok=False, error=str(_fail("getFile", "missing file_path")))

        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.part")
        url = f"{API_BASE}/file/bot{self._token}/{file_path}"
        size = 0
        try:
            async with self._client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise _fail("downloadFile", f"HTTP {response.status_code}")
                with part.open("wb") as fh:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            break
                        fh.write(chunk)
            if size > max_bytes:
                part.unlink(missing_ok=True)
                return DownloadResult(ok=False, size=size, error="too_large")
            os.replace(part, dest)
        except (httpx.HTTPError, TelegramApiError, OSError) as exc:
            part.unlink(missing_ok=True)
            if isinstance(exc, TelegramApiError):
                return DownloadResult(ok=False, error=str(exc))
            cause = _cause(exc) if isinstance(exc, httpx.HTTPError) else type(exc).__name__
            return DownloadResult(ok=False, error=str(_fail("downloadFile", cause)))
        return DownloadResult(ok=True, size=size)
