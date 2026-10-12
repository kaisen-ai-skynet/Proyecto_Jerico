"""Buzón de respuestas por IMAP de solo lectura (VCRM-169, 170; plan-f2 D-4, §5.7).

Sondeo SALIENTE: el sistema abre la conexión, lee y cierra; no escucha en ningún puerto ni expone
rutas (P-10). Se usa `EXAMINE` (solo lectura) y `BODY.PEEK`, así que nunca cambia banderas ni
borra nada del buzón. El contenido recibido es no confiable: se normaliza y se acota aquí.
"""

import asyncio
import email
import email.policy
import hashlib
import imaplib
import logging
import re
import ssl
from datetime import UTC, datetime
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser

from pydantic import SecretStr

from jerico.crm.config import CrmSettings
from jerico.crm.ports import InboundMessage, InboxBatch, InboxError

logger = logging.getLogger(__name__)

IMAP_TIMEOUT_S = 30
MAX_MESSAGE_BYTES = 256 * 1024
BATCH_SIZE = 50
MAX_BODY_CHARS = 20_000
_MAX_ID_CHARS = 998
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_BLOCK_TAGS = frozenset({"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"})
_SKIP_TAGS = frozenset({"script", "style", "head"})


class UnconfiguredInbox:
    """Buzón sin configurar: F2 queda deshabilitada y el sondeo avisa en vez de conectar."""

    async def fetch_new(self, uidvalidity: int | None, last_uid: int) -> InboxBatch:
        raise InboxError("inbox_not_configured")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # pragma: no cover - HTMLParser casi nunca lanza; se usa lo extraído
        logger.debug("html to text aborted; using partial text")
    lines = (" ".join(line.replace("\xa0", " ").split()) for line in parser.text().splitlines())
    return "\n".join(line for line in lines if line)


def _clean_line(value: object) -> str:
    return _CONTROL_RE.sub(" ", str(value or "")).strip()


def _fallback_id(raw: bytes) -> str:
    return f"<noid-{hashlib.sha256(raw).hexdigest()[:32]}@crm.invalid>"


def _body_text(msg: Message) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))  # type: ignore[attr-defined]
    if part is None:
        return ""
    try:
        content = part.get_content()
    except Exception:  # charset desconocido o contenido corrupto
        payload = part.get_payload(decode=True)
        content = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else ""
    if part.get_content_type() == "text/html":
        content = _html_to_text(content)
    return str(content).strip()[:MAX_BODY_CHARS]


def _date(msg: Message) -> datetime | None:
    try:
        parsed = parsedate_to_datetime(str(msg["Date"]))
    except (TypeError, ValueError, IndexError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _parse(uid: int, raw: bytes, truncated: bool) -> InboundMessage:
    try:
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        message_id = _clean_line(msg["Message-ID"])
        if not message_id or len(message_id) > _MAX_ID_CHARS:
            message_id = _fallback_id(raw)
        references = tuple(
            token
            for token in _clean_line(msg["References"]).split()
            if token.startswith("<") and token.endswith(">") and len(token) <= _MAX_ID_CHARS
        )
        reply = _clean_line(msg["In-Reply-To"]).split()
        return InboundMessage(
            uid=uid,
            rfc_message_id=message_id,
            in_reply_to=reply[0] if reply else None,
            references=references,
            from_addr=parseaddr(_clean_line(msg["From"]))[1].lower(),
            subject=_clean_line(msg["Subject"]),
            body_text=_body_text(msg),
            date=_date(msg),
            truncated=truncated,
        )
    except Exception:  # un correo ilegible no puede tumbar el lote: va a revisión humana
        return InboundMessage(
            uid=uid,
            rfc_message_id=_fallback_id(raw),
            in_reply_to=None,
            references=(),
            from_addr="",
            subject="",
            body_text="",
            date=None,
            truncated=truncated,
        )


class ImapInbox:
    def __init__(
        self,
        *,
        host: str,
        username: str,
        password: SecretStr,
        port: int = 993,
        mailbox: str = "INBOX",
        timeout_s: float = IMAP_TIMEOUT_S,
        max_bytes: int = MAX_MESSAGE_BYTES,
        batch_size: int = BATCH_SIZE,
    ) -> None:
        self.host, self.port, self.mailbox = host, port, mailbox
        self.username, self.timeout_s = username, timeout_s
        self.max_bytes, self.batch_size = max_bytes, batch_size
        self._password = password

    def __repr__(self) -> str:
        return f"ImapInbox(host={self.host!r}, port={self.port}, mailbox={self.mailbox!r})"

    async def fetch_new(self, uidvalidity: int | None, last_uid: int) -> InboxBatch:
        try:
            return await asyncio.to_thread(self._fetch_sync, uidvalidity, last_uid)
        except InboxError:
            raise
        except (imaplib.IMAP4.error, OSError, EOFError, ssl.SSLError) as exc:
            error = f"imap_error:{type(exc).__name__}"
            logger.warning("imap poll failed: %s", error)
            raise InboxError(error) from None  # sin encadenar: el servidor podría citar el usuario

    def _fetch_sync(self, uidvalidity: int | None, last_uid: int) -> InboxBatch:
        context = ssl.create_default_context()
        with imaplib.IMAP4_SSL(
            self.host, self.port, ssl_context=context, timeout=self.timeout_s
        ) as imap:
            imap.login(self.username, self._password.get_secret_value())
            imap.select(self.mailbox, readonly=True)  # EXAMINE: no cambia banderas
            _, data = imap.response("UIDVALIDITY")
            if not data or not data[0]:
                raise InboxError("imap_error:no_uidvalidity")
            current = int(data[0])
            start = last_uid if uidvalidity == current else 0  # UID viejos ya no valen
            _, found = imap.uid("SEARCH", f"UID {start + 1}:*")
            raw_uids = found[0].split() if found and found[0] else []
            uids = sorted(u for u in (int(x) for x in raw_uids) if u > start)
            chosen = uids[: self.batch_size]
            messages = tuple(self._fetch_one(imap, uid) for uid in chosen)
            return InboxBatch(current, messages, has_more=len(uids) > len(chosen))

    def _fetch_one(self, imap: imaplib.IMAP4_SSL, uid: int) -> InboundMessage:
        _, data = imap.uid("FETCH", str(uid), f"(BODY.PEEK[]<0.{self.max_bytes}>)")
        raw = next((item[1] for item in data if isinstance(item, tuple)), b"")
        raw = raw if isinstance(raw, bytes) else b""
        return _parse(uid, raw, truncated=len(raw) >= self.max_bytes)


def build_inbox(settings: CrmSettings) -> ImapInbox | UnconfiguredInbox:
    """Sin host, usuario o contraseña → `UnconfiguredInbox` (F2 deshabilitada, D-9)."""
    password = settings.imap_password
    if (
        not settings.imap_host
        or not settings.imap_username
        or password is None
        or not password.get_secret_value()
    ):
        return UnconfiguredInbox()
    return ImapInbox(
        host=settings.imap_host,
        port=settings.imap_port,
        username=settings.imap_username,
        password=password,
        mailbox=settings.imap_mailbox,
    )
