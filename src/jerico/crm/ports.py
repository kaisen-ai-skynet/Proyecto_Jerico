"""Puertos (`Protocol`s) y tipos de intercambio de los adaptadores del CRM (plan §6)."""

from dataclasses import dataclass
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
    async def send(self, to: str, subject: str, body: str) -> SendResult: ...


class CommandRunner(Protocol):
    async def run(self, argv: list[str], timeout_s: float) -> CommandResult: ...


class FileStore(Protocol):
    def new_tmp_path(self, suffix: str = "") -> Path: ...

    def save_atomic(self, lead_id: int, tmp_path: Path) -> str: ...

    def delete(self, storage_key: str) -> None: ...

    def open(self, storage_key: str) -> BinaryIO: ...
