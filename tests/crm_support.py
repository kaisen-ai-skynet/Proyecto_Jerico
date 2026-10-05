"""Dobles y harness compartidos de los tests del CRM (sin fixtures de pytest).

Esqueleto: crece con cada tarea (FakeTelegram, FakeEmailSender, FakeClock, make_harness).
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from jerico.crm.config import CrmSettings
from jerico.crm.model import Lead
from jerico.crm.ports import CommandResult, DownloadResult, InlineButton, SendResult, Update


def make_settings(**overrides: Any) -> CrmSettings:
    """Configuración hermética: nunca lee un `.env` local."""
    kwargs: dict[str, Any] = {"_env_file": None, **overrides}
    return CrmSettings(**kwargs)


def make_lead(**overrides: Any) -> Lead:
    """Lead en memoria con valores por defecto neutros (sin base de datos)."""
    base: dict[str, Any] = {
        "id": 42,
        "assigned_user_id": 1,
        "state": "aceptado",
        "name": "Ana Pérez",
        "phone_e164": "+573001234567",
        "email": "ana@empresa.co",
        "company": None,
        "client_type": None,
        "doc_type": None,
        "doc_number": None,
        "legal_rep": None,
        "service": None,
        "agreed_value": None,
        "start_term": None,
        "reject_reason": None,
        "reject_text": None,
        "rejection_is_retraction": 0,
        "auth_status": "sin_autorizacion",
        "ever_accepted": 1,
        "registered_at": "2026-01-01T00:00:00Z",
        "last_interaction_at": "2026-01-01T00:00:00Z",
        "accepted_exit_at": None,
        "won_at": None,
        "final_state_at": None,
        "legal_hold_basis": None,
        "commercial_block": 0,
        "suppressed_at": None,
        "suppression_cause": None,
    }
    base.update(overrides)
    return Lead(**base)


@dataclass(frozen=True)
class SentTelegram:
    chat_id: int
    text: str
    buttons: list[list[InlineButton]] | None = None
    document: Path | None = None
    content: bytes | None = None  # bytes del documento al enviarlo (el temporal se borra después)


class FakeTelegram:
    """Doble de `TelegramPort`: registra envíos y aplica un guion de fallos por destinatario."""

    def __init__(self) -> None:
        self.sent: list[SentTelegram] = []
        self.attempts: list[SentTelegram] = []
        self.updates: list[Update] = []
        self.answered: list[tuple[str, str | None]] = []
        self.files: dict[str, bytes] = {}
        self._failures: defaultdict[int, int] = defaultdict(int)
        self._failed_documents: set[int] = set()
        self._document_attempts = 0
        self._next_id = 1

    def fail_next(self, chat_id: int, times: int = 1) -> None:
        self._failures[chat_id] += times

    def fail_document(self, attempt: int) -> None:
        """Hace fallar el envío del documento número `attempt` (1, 2, …)."""
        self._failed_documents.add(attempt)

    def _deliver(self, item: SentTelegram) -> SendResult:
        self.attempts.append(item)
        if self._failures[item.chat_id] > 0:
            self._failures[item.chat_id] -= 1
            return SendResult(delivered=False, error="sendMessage: HTTP 502")
        self.sent.append(item)
        self._next_id += 1
        return SendResult(delivered=True, message_id=str(self._next_id))

    async def get_updates(self, offset: int | None, timeout_s: int) -> list[Update]:
        pending = [u for u in self.updates if offset is None or u.update_id >= offset]
        self.updates = []
        return pending

    async def send_message(
        self, chat_id: int, text: str, buttons: list[list[InlineButton]] | None = None
    ) -> SendResult:
        return self._deliver(SentTelegram(chat_id, text, buttons))

    async def answer_callback(self, callback_id: str, text: str | None = None) -> None:
        self.answered.append((callback_id, text))

    async def download_file(self, file_id: str, dest: Path, max_bytes: int) -> DownloadResult:
        content = self.files.get(file_id)
        if content is None:
            return DownloadResult(ok=False, error="getFile: HTTP 400")
        if len(content) > max_bytes:
            return DownloadResult(ok=False, size=len(content), error="too_large")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        return DownloadResult(ok=True, size=len(content))

    async def send_document(self, chat_id: int, path: Path, caption: str) -> SendResult:
        self._document_attempts += 1
        content = path.read_bytes() if path.exists() else None
        item = SentTelegram(chat_id, caption, document=path, content=content)
        if self._document_attempts in self._failed_documents:
            self.attempts.append(item)
            return SendResult(delivered=False, error="sendDocument: HTTP 502")
        return self._deliver(item)


@dataclass(frozen=True)
class SentEmail:
    to: str
    subject: str
    body: str


class FakeEmailSender:
    """Doble de `EmailSender`; `configured=False` imita `UnconfiguredEmailSender`."""

    def __init__(self, configured: bool = True) -> None:
        self.configured = configured
        self.sent: list[SentEmail] = []
        self.attempts: list[SentEmail] = []
        self._failures: defaultdict[str, int] = defaultdict(int)

    def fail_next(self, to: str, times: int = 1) -> None:
        self._failures[to] += times

    async def send(self, to: str, subject: str, body: str) -> SendResult:
        item = SentEmail(to, subject, body)
        if not self.configured:
            return SendResult(delivered=False, permanent=True, error="mailbox_not_configured")
        self.attempts.append(item)
        if self._failures[to] > 0:
            self._failures[to] -= 1
            return SendResult(delivered=False, error="smtp_error:SMTPServerDisconnected")
        self.sent.append(item)
        return SendResult(delivered=True, message_id=f"<{len(self.sent)}@fake.test>")


class FakeClock:
    """Reloj UTC simulado y avanzable."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 5, 14, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, **delta: float) -> datetime:
        self._now += timedelta(**delta)
        return self._now


class FakeRunner:
    """Doble de `CommandRunner`: registra `argv` y aplica un guion de códigos por programa.

    `fail(prog, sub, rc)` hace fallar la siguiente invocación de `prog sub`; `age` crea su
    `--output` y copia la entrada en `inputs` (contenido real del `tar.gz`); `rclone lsf`
    devuelve `listing`.
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.inputs: dict[str, bytes] = {}
        self.listing: list[str] = []
        self._script: defaultdict[tuple[str, str], list[int]] = defaultdict(list)

    def fail(self, prog: str, sub: str, returncode: int = 1) -> None:
        self._script[(prog, sub)].append(returncode)

    async def run(self, argv: list[str], timeout_s: float) -> CommandResult:
        self.calls.append(list(argv))
        script = self._script[(argv[0], argv[1])]
        if script:
            return CommandResult(returncode=script.pop(0), stderr_tail="error simulado")
        if argv[0] == "age":
            source = Path(argv[-1])
            self.inputs["age"] = source.read_bytes()
            Path(argv[argv.index("--output") + 1]).write_bytes(b"cifrado")
        stdout = "\n".join(self.listing) + "\n" if argv[:2] == ["rclone", "lsf"] else ""
        return CommandResult(returncode=0, stderr_tail="", stdout=stdout)
