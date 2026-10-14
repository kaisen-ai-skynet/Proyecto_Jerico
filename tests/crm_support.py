"""Dobles y harness compartidos de los tests del CRM (sin fixtures de pytest).

Esqueleto: crece con cada tarea (FakeTelegram, FakeEmailSender, FakeClock, make_harness).
"""

import sqlite3
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from jerico.crm.config import CrmSettings
from jerico.crm.llm import LlmError, LlmResult
from jerico.crm.model import Lead
from jerico.crm.ports import (
    CommandResult,
    DownloadResult,
    InboundMessage,
    InboxBatch,
    InlineButton,
    SendResult,
    Update,
)
from jerico.crm.telegram import TelegramApiError


class FakeLlm:
    def __init__(self, reply: str | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        text = reply or "Hola [CLIENTE]: seguimos."
        self.reply = LlmResult(text=text, input_tokens=100, output_tokens=40)
        self.error: LlmError | None = None

    async def complete(self, *, system: str, user: str, max_output_tokens: int) -> LlmResult:
        self.calls.append({"system": system, "user": user, "max": max_output_tokens})
        if self.error is not None:
            raise self.error
        return self.reply

    def sent_text(self) -> str:
        return " ".join(f"{c['system']} {c['user']}" for c in self.calls)


def make_settings(**overrides: Any) -> CrmSettings:
    """Configuración hermética: nunca lee un `.env` local."""
    kwargs: dict[str, Any] = {"_env_file": None, **overrides}
    return CrmSettings(**kwargs)


def make_lead(**overrides: Any) -> Lead:
    """Lead en memoria con valores por defecto neutros (sin base de datos)."""
    base: dict[str, Any] = {
        "id": 42,
        "assigned_user_id": 1,
        "state": "accepted",
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
        "auth_status": "unauthorized",
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
        self.my_commands: list[tuple[list[dict[str, str]], dict[str, Any] | None]] = []
        self.deleted_commands: list[dict[str, Any] | None] = []
        self.menu_buttons: list[tuple[int | None, dict[str, Any] | None]] = []
        self._failures: defaultdict[int, int] = defaultdict(int)
        self._failed_documents: set[int] = set()
        self._commands_failure = False
        self._document_attempts = 0
        self._next_id = 1

    def fail_commands(self, fail: bool = True) -> None:
        self._commands_failure = fail

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

    async def set_my_commands(
        self,
        commands: Any,
        scope: Any = None,
    ) -> bool:
        if self._commands_failure:
            raise TelegramApiError("setMyCommands: HTTP 502")
        self.my_commands.append(([dict(c) for c in commands], dict(scope) if scope else None))
        return True

    async def delete_my_commands(
        self,
        scope: Any = None,
    ) -> bool:
        if self._commands_failure:
            raise TelegramApiError("deleteMyCommands: HTTP 502")
        self.deleted_commands.append(dict(scope) if scope else None)
        return True

    async def set_chat_menu_button(
        self,
        chat_id: int | None = None,
        menu_button: Any = None,
    ) -> bool:
        if self._commands_failure:
            raise TelegramApiError("setChatMenuButton: HTTP 502")
        self.menu_buttons.append(
            (chat_id, dict(menu_button) if menu_button else {"type": "commands"})
        )
        return True


@dataclass(frozen=True)
class SentEmail:
    to: str
    subject: str
    body: str
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SentAttachment:
    to: str
    subject: str
    body: str
    filename: str
    content: bytes
    mime: str


class FakeEmailSender:
    """Doble de `EmailSender`; `configured=False` imita `UnconfiguredEmailSender`."""

    def __init__(self, configured: bool = True) -> None:
        self.configured = configured
        self.sent: list[SentEmail] = []
        self.attempts: list[SentEmail] = []
        self.attachments: list[SentAttachment] = []
        self._failures: defaultdict[str, int] = defaultdict(int)

    def fail_next(self, to: str, times: int = 1) -> None:
        self._failures[to] += times

    async def send(
        self, to: str, subject: str, body: str, headers: Mapping[str, str] | None = None
    ) -> SendResult:
        item = SentEmail(to, subject, body, dict(headers or {}))
        if not self.configured:
            return SendResult(delivered=False, permanent=True, error="mailbox_not_configured")
        self.attempts.append(item)
        if self._failures[to] > 0:
            self._failures[to] -= 1
            return SendResult(delivered=False, error="smtp_error:SMTPServerDisconnected")
        self.sent.append(item)
        return SendResult(delivered=True, message_id=f"<{len(self.sent)}@fake.test>")

    async def send_with_attachment(
        self,
        to: str,
        subject: str,
        body: str,
        *,
        filename: str,
        content: bytes,
        mime: str = "application/pdf",
    ) -> SendResult:
        if not self.configured:
            return SendResult(delivered=False, permanent=True, error="mailbox_not_configured")
        if self._failures[to] > 0:
            self._failures[to] -= 1
            return SendResult(delivered=False, error="smtp_error:SMTPServerDisconnected")
        self.attachments.append(SentAttachment(to, subject, body, filename, content, mime))
        return SendResult(delivered=True, message_id=f"<att{len(self.attachments)}@fake>")


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


# --- Esquema v1 congelado (VCRM-171): copia literal del DDL de F1; NO se actualiza con db.py ---
V1_DDL: tuple[str, ...] = (
    "CREATE TABLE IF NOT EXISTS crm_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS crm_users (
  id INTEGER PRIMARY KEY,
  telegram_id BIGINT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('commercial','cto','lawyer')),
  email TEXT NOT NULL,
  active SMALLINT NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, deactivated_at TEXT
)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_users_active_tg ON crm_users (telegram_id) WHERE active = 1",  # noqa: E501
    """CREATE TABLE IF NOT EXISTS crm_leads (
  id INTEGER PRIMARY KEY,
  assigned_user_id INTEGER REFERENCES crm_users(id),
  state TEXT NOT NULL,
  name TEXT, phone_e164 TEXT, email TEXT, company TEXT,
  client_type TEXT, doc_type TEXT, doc_number TEXT, legal_rep TEXT,
  service TEXT, agreed_value TEXT, start_term TEXT,
  reject_reason TEXT, reject_text TEXT, rejection_is_retraction SMALLINT NOT NULL DEFAULT 0,
  auth_status TEXT NOT NULL DEFAULT 'sin_autorizacion',
  ever_accepted SMALLINT NOT NULL DEFAULT 0,
  registered_at TEXT NOT NULL, last_interaction_at TEXT NOT NULL,
  accepted_exit_at TEXT,
  won_at TEXT, final_state_at TEXT,
  legal_hold_basis TEXT, commercial_block SMALLINT NOT NULL DEFAULT 0,
  suppressed_at TEXT, suppression_cause TEXT
)""",
    "CREATE INDEX IF NOT EXISTS ix_leads_phone ON crm_leads (phone_e164)",
    "CREATE INDEX IF NOT EXISTS ix_leads_email ON crm_leads (email)",
    "CREATE INDEX IF NOT EXISTS ix_leads_assigned ON crm_leads (assigned_user_id, last_interaction_at)",  # noqa: E501
    """CREATE TABLE IF NOT EXISTS crm_lead_events (
  id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES crm_leads(id),
  kind TEXT NOT NULL CHECK (kind IN ('state','field','reassign','titular_request')),
  field TEXT, old_value TEXT, new_value TEXT, reason TEXT, reason_text TEXT,
  actor_user_id INTEGER NOT NULL, at TEXT NOT NULL
)""",
    "CREATE TABLE IF NOT EXISTS crm_notes (id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL, author_user_id INTEGER NOT NULL, body TEXT NOT NULL, at TEXT NOT NULL)",  # noqa: E501
    """CREATE TABLE IF NOT EXISTS crm_attachments (
  id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('photo','document','voice','authorization')),
  author_user_id INTEGER NOT NULL, at TEXT NOT NULL,
  storage_key TEXT NOT NULL, size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, deleted_at TEXT
)""",
    """CREATE TABLE IF NOT EXISTS crm_consents (
  id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL, status TEXT NOT NULL, medium TEXT NOT NULL,
  at TEXT NOT NULL, actor_user_id INTEGER NOT NULL, notice_version TEXT, purposes TEXT,
  attachment_id INTEGER
)""",
    "CREATE TABLE IF NOT EXISTS crm_suppression (fingerprint TEXT PRIMARY KEY, at TEXT NOT NULL, medium TEXT NOT NULL)",  # noqa: E501
    """CREATE TABLE IF NOT EXISTS crm_titular_requests (
  id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('consulta','reclamo')),
  medium TEXT NOT NULL, received_on TEXT NOT NULL, due_on TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'abierta' CHECK (status IN ('abierta','vencida','atendida')),
  registered_by INTEGER NOT NULL, registered_at TEXT NOT NULL,
  last_escalation_on TEXT, attended_by INTEGER, attended_at TEXT
)""",
    """CREATE TABLE IF NOT EXISTS crm_outbox (
  id INTEGER PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL, critical SMALLINT NOT NULL,
  channel TEXT NOT NULL CHECK (channel IN ('telegram','email')),
  recipient_user_id INTEGER NOT NULL, lead_id INTEGER, origin_outbox_id INTEGER,
  subject TEXT, body TEXT,
  status TEXT NOT NULL CHECK (status IN ('pendiente','entregada','fallida')),
  attempts SMALLINT NOT NULL DEFAULT 0, first_attempt_at TEXT, next_attempt_at TEXT,
  last_error TEXT, provider_message_id TEXT, created_at TEXT NOT NULL
)""",
    "CREATE INDEX IF NOT EXISTS ix_outbox_due ON crm_outbox (status, next_attempt_at)",
    """CREATE TABLE IF NOT EXISTS crm_alerts (
  id INTEGER PRIMARY KEY, lead_id INTEGER, kind TEXT NOT NULL, outbox_id INTEGER,
  request_id INTEGER, created_at TEXT NOT NULL, resolved_by INTEGER, resolved_at TEXT
)""",
    """CREATE TABLE IF NOT EXISTS crm_audit (
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, actor TEXT NOT NULL,
  action TEXT NOT NULL, lead_id INTEGER, outcome TEXT NOT NULL, detail_code TEXT
)""",
    "CREATE TABLE IF NOT EXISTS crm_processed_updates (update_id BIGINT PRIMARY KEY, processed_at TEXT NOT NULL)",  # noqa: E501
    "CREATE TABLE IF NOT EXISTS crm_pending_inputs (user_id INTEGER PRIMARY KEY, kind TEXT NOT NULL, lead_id INTEGER, data TEXT, expires_at TEXT NOT NULL)",  # noqa: E501
    """CREATE TABLE IF NOT EXISTS crm_confirmations (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('accept','retract','authorization_question')),
  lead_id INTEGER NOT NULL, user_id INTEGER NOT NULL, reason TEXT, reason_text TEXT,
  status TEXT NOT NULL DEFAULT 'pendiente', created_at TEXT NOT NULL, resolved_at TEXT
)""",
    """CREATE TABLE IF NOT EXISTS crm_retention_notices (
  lead_id INTEGER NOT NULL, clock_start TEXT NOT NULL, kind TEXT NOT NULL,
  sent_at TEXT NOT NULL, PRIMARY KEY (lead_id, clock_start, kind)
)""",
    "INSERT INTO crm_meta (key, value) VALUES ('schema_version', '1') ON CONFLICT (key) DO NOTHING",
)


# (id, state, auth_status) de los 10 leads de ejemplo: un lead por estado v1.
V1_LEAD_ROWS: tuple[tuple[int, str, str], ...] = (
    (1, "nuevo", "sin_autorizacion"),
    (2, "contactado", "autorizada"),
    (3, "aceptado", "autorizada"),
    (4, "rechazado", "revocada"),
    (5, "en_nutricion", "autorizada"),
    (6, "pausado", "sin_autorizacion"),
    (7, "reactivado", "autorizada"),
    (8, "ganado", "autorizada"),
    (9, "perdido", "revocada"),
    (10, "baja", "revocada"),
)
V1_TS = "2026-10-01T12:00:00+00:00"


def build_v1_database(path: Path) -> None:
    """Crea una base con el esquema v1 literal y filas en todos los estados de F1.

    Inventario de `crm_confirmations.status` en F1 (repo.resolve_confirmation, bot.py):
    `pendiente`, `confirmada`, `cancelada`.
    """
    conn = sqlite3.connect(str(path), isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        for statement in V1_DDL:
            conn.execute(statement)
        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO crm_users (id, telegram_id, role, email, active, created_at) "
            "VALUES (1, 1001, 'cto', 'cto@example.invalid', 1, ?), "
            "(2, 1002, 'commercial', 'com@example.invalid', 1, ?)",
            (V1_TS, V1_TS),
        )
        for lead_id, state, auth in V1_LEAD_ROWS:
            conn.execute(
                "INSERT INTO crm_leads (id, assigned_user_id, state, name, phone_e164, email, "
                "reject_reason, auth_status, registered_at, last_interaction_at) "
                "VALUES (?, 2, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    lead_id,
                    state,
                    f"Cliente {lead_id}",
                    f"+57300000{lead_id:04d}",
                    f"c{lead_id}@example.invalid",
                    "precio" if state == "rechazado" else None,
                    auth,
                    V1_TS,
                    V1_TS,
                ),
            )
            conn.execute(
                "INSERT INTO crm_lead_events (lead_id, kind, old_value, new_value, "
                "actor_user_id, at) VALUES (?, 'state', 'nuevo', ?, 2, ?)",
                (lead_id, state, V1_TS),
            )
        # Un evento de campo cuyo texto coincide con un estado: NO debe migrarse.
        conn.execute(
            "INSERT INTO crm_lead_events (lead_id, kind, field, old_value, new_value, "
            "actor_user_id, at) VALUES (2, 'field', 'company', 'contactado', 'aceptado', 2, ?)",
            (V1_TS,),
        )
        conn.execute(
            "INSERT INTO crm_consents (lead_id, status, medium, at, actor_user_id) "
            "VALUES (2, 'autorizada', 'email', ?, 2), (4, 'revocada', 'telegram', ?, 2)",
            (V1_TS, V1_TS),
        )
        for key, status in (("k1", "pendiente"), ("k2", "entregada"), ("k3", "fallida")):
            conn.execute(
                "INSERT INTO crm_outbox (idempotency_key, kind, critical, channel, "
                "recipient_user_id, status, created_at) VALUES (?, 'handoff', 1, 'email', 1, ?, ?)",
                (key, status, V1_TS),
            )
        for req_type, status in (
            ("consulta", "abierta"),
            ("reclamo", "vencida"),
            ("consulta", "atendida"),
        ):
            conn.execute(
                "INSERT INTO crm_titular_requests (lead_id, type, medium, received_on, due_on, "
                "status, registered_by, registered_at) VALUES (2, ?, 'email', '2026-10-01', "
                "'2026-10-15', ?, 1, ?)",
                (req_type, status, V1_TS),
            )
        for kind, status in (
            ("accept", "pendiente"),
            ("retract", "confirmada"),
            ("authorization_question", "cancelada"),
        ):
            conn.execute(
                "INSERT INTO crm_confirmations (kind, lead_id, user_id, status, created_at) "
                "VALUES (?, 2, 2, ?, ?)",
                (kind, status, V1_TS),
            )
        conn.execute(
            "INSERT INTO crm_notes (lead_id, author_user_id, body, at) VALUES (2, 2, 'nota', ?)",
            (V1_TS,),
        )
        conn.execute(
            "INSERT INTO crm_suppression (fingerprint, at, medium) VALUES ('fp', ?, 'email')",
            (V1_TS,),
        )
        conn.execute(
            "INSERT INTO crm_audit (at, actor, action, outcome) VALUES (?, 'u2', 'lead_created', 'ok')",  # noqa: E501
            (V1_TS,),
        )
        conn.execute("COMMIT")
    finally:
        conn.close()


class FakeInbox:
    """Doble de `InboxPort`: lotes de hasta 50, `UIDVALIDITY` y fallos programables."""

    def __init__(self, messages: Sequence[InboundMessage] = (), uidvalidity: int = 1) -> None:
        self.messages = list(messages)
        self.uidvalidity = uidvalidity
        self.fetches: list[tuple[int | None, int]] = []
        self._failures: list[Exception] = []

    def add(self, *messages: InboundMessage) -> None:
        self.messages.extend(messages)

    def fail_next(self, error: Exception) -> None:
        self._failures.append(error)

    async def fetch_new(self, uidvalidity: int | None, last_uid: int) -> InboxBatch:
        self.fetches.append((uidvalidity, last_uid))
        if self._failures:
            raise self._failures.pop(0)
        start = last_uid if uidvalidity == self.uidvalidity else 0
        pending = sorted((m for m in self.messages if m.uid > start), key=lambda m: m.uid)
        return InboxBatch(self.uidvalidity, tuple(pending[:50]), has_more=len(pending) > 50)
