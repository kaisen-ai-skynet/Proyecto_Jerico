"""Puertos (`Protocol`s) y tipos de intercambio de los adaptadores del CRM (plan §6)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Literal, Protocol

FileKind = Literal["photo", "document", "voice"]


@dataclass(frozen=True)
class InlineButton:
    text: str
    callback_data: str


@dataclass(frozen=True)
class FileRef:
    file_id: str
    size: int | None
    kind: FileKind


@dataclass(frozen=True)
class Update:
    update_id: int
    user_id: int | None = None
    chat_id: int | None = None
    chat_type: str | None = None
    text: str | None = None
    caption: str | None = None
    file: FileRef | None = None
    callback_id: str | None = None
    callback_data: str | None = None


@dataclass(frozen=True)
class SendResult:
    """Entregado solo si el canal lo confirma con un identificador (spec §4.5)."""

    delivered: bool
    message_id: str | None = None
    error: str | None = None
    permanent: bool = False


@dataclass(frozen=True)
class DownloadResult:
    ok: bool
    size: int = 0
    error: str | None = None  # "too_large" o causa saneada (sin token)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stderr_tail: str
    stdout: str = ""  # salida estándar (p. ej. `rclone lsf`)


class TelegramPort(Protocol):
    async def get_updates(self, offset: int | None, timeout_s: int) -> list[Update]: ...

    async def send_message(
        self, chat_id: int, text: str, buttons: list[list[InlineButton]] | None = None
    ) -> SendResult: ...

    async def answer_callback(self, callback_id: str, text: str | None = None) -> None: ...

    async def download_file(self, file_id: str, dest: Path, max_bytes: int) -> DownloadResult: ...

    async def send_document(self, chat_id: int, path: Path, caption: str) -> SendResult: ...


class EmailSender(Protocol):
    async def send(
        self, to: str, subject: str, body: str, headers: Mapping[str, str] | None = None
    ) -> SendResult: ...


class AttachmentEmailSender(EmailSender, Protocol):
    """Correo con un adjunto (el contrato al cliente, spec 004)."""

    async def send_with_attachment(
        self,
        to: str,
        subject: str,
        body: str,
        *,
        filename: str,
        content: bytes,
        mime: str = "application/pdf",
    ) -> SendResult: ...


class InboxError(Exception):
    """Fallo de conexión o credenciales del buzón (VCRM-170).

    El texto lleva solo el tipo de error: nunca el mensaje del servidor ni credenciales.
    """


@dataclass(frozen=True)
class InboundMessage:
    """Correo entrante ya normalizado; el contenido es NO confiable (viene de terceros)."""

    uid: int
    rfc_message_id: str
    in_reply_to: str | None
    references: tuple[str, ...]
    from_addr: str  # minúsculas; vacío si no hay un remitente fiable
    subject: str
    body_text: str  # texto plano, acotado; el HTML ya viene reducido a texto
    date: datetime | None  # con zona; None si la cabecera falta o es ilegible
    truncated: bool  # el mensaje superó el tope de bytes y se leyó solo el principio


@dataclass(frozen=True)
class InboxBatch:
    uidvalidity: int
    messages: tuple[InboundMessage, ...]
    has_more: bool  # quedan mensajes nuevos para el siguiente sondeo


class InboxPort(Protocol):
    async def fetch_new(self, uidvalidity: int | None, last_uid: int) -> InboxBatch:
        """Mensajes con UID > `last_uid` (o todos si `uidvalidity` cambió). Solo lectura."""
        ...


class CommandRunner(Protocol):
    async def run(self, argv: list[str], timeout_s: float) -> CommandResult: ...


class FileStore(Protocol):
    def new_tmp_path(self, suffix: str = "") -> Path: ...

    def save_atomic(self, lead_id: int, tmp_path: Path) -> str: ...

    def delete(self, storage_key: str) -> None: ...

    def open(self, storage_key: str) -> BinaryIO: ...
