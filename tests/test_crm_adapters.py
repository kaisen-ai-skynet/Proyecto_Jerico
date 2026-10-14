"""T08 — Adaptadores: Telegram (httpx), correo (SMTP) y archivos locales.

Requisitos: VCRM-105, 140, 008 (límite de descarga), 012 (semántica de «entregado»).
Herméticos: `httpx.MockTransport` y un `smtplib` falso; sin red.
"""

import json
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from crm_support import FakeClock, FakeEmailSender, FakeTelegram, make_settings
from jerico.crm import mail
from jerico.crm.files import MAX_ATTACHMENT_BYTES, AttachmentTooLarge, LocalFileStore
from jerico.crm.mail import SmtpEmailSender, UnconfiguredEmailSender, build_email_sender
from jerico.crm.ports import EmailSender, FileStore, InlineButton, TelegramPort
from jerico.crm.telegram import HttpxTelegramClient, TelegramApiError

TOKEN = "123456:SECRET-TOKEN-xyz"  # noqa: S105 - valor ficticio de prueba
PASSWORD = "pw-ficticia"  # noqa: S105 - valor ficticio de prueba


def _client(handler: Any) -> HttpxTelegramClient:
    return HttpxTelegramClient(TOKEN, transport=httpx.MockTransport(handler))


def _ok(result: Any) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": result})


# ---------------------------------------------------------------- Telegram: getUpdates


@pytest.mark.asyncio
async def test_vcrm012_get_updates_normalizes_message_file_and_callback() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return _ok(
            [
                {
                    "update_id": 10,
                    "message": {
                        "message_id": 1,
                        "from": {"id": 501},
                        "chat": {"id": 501, "type": "private"},
                        "text": "/nuevo Ana",
                    },
                },
                {
                    "update_id": 11,
                    "message": {
                        "message_id": 2,
                        "from": {"id": 501},
                        "chat": {"id": 501, "type": "private"},
                        "caption": "/adjuntar 7",
                        "photo": [
                            {"file_id": "small", "file_size": 10},
                            {"file_id": "big", "file_size": 900},
                        ],
                    },
                },
                {
                    "update_id": 12,
                    "message": {
                        "message_id": 3,
                        "from": {"id": 502},
                        "chat": {"id": -9, "type": "group"},
                        "document": {"file_id": "doc1", "file_size": 2048},
                    },
                },
                {
                    "update_id": 13,
                    "message": {
                        "message_id": 4,
                        "from": {"id": 502},
                        "chat": {"id": 502, "type": "private"},
                        "voice": {"file_id": "v1", "file_size": 77},
                    },
                },
                {
                    "update_id": 14,
                    "callback_query": {
                        "id": "cb-1",
                        "from": {"id": 503},
                        "message": {"message_id": 9, "chat": {"id": 503, "type": "private"}},
                        "data": "acc:7",
                    },
                },
            ]
        )

    updates = await _client(handler).get_updates(offset=10, timeout_s=25)

    assert seen["path"].endswith("/getUpdates")
    assert seen["body"]["offset"] == 10
    assert seen["body"]["timeout"] == 25
    assert seen["body"]["allowed_updates"] == ["message", "callback_query"]
    assert [u.update_id for u in updates] == [10, 11, 12, 13, 14]
    text, photo, doc, voice, cb = updates
    assert (text.user_id, text.chat_id, text.chat_type, text.text) == (
        501,
        501,
        "private",
        "/nuevo Ana",
    )
    assert text.file is None and text.callback_id is None
    assert photo.caption == "/adjuntar 7"
    assert photo.file is not None
    assert (photo.file.file_id, photo.file.size, photo.file.kind) == ("big", 900, "photo")
    assert doc.file is not None and (doc.file.kind, doc.file.size) == ("document", 2048)
    assert doc.chat_type == "group"
    assert voice.file is not None and voice.file.kind == "voice"
    assert (cb.callback_id, cb.callback_data, cb.user_id, cb.chat_id) == (
        "cb-1",
        "acc:7",
        503,
        503,
    )


@pytest.mark.asyncio
async def test_vcrm012_get_updates_failure_raises_without_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})

    with pytest.raises(TelegramApiError) as excinfo:
        await _client(handler).get_updates(offset=None, timeout_s=1)
    assert TOKEN not in str(excinfo.value)
    assert "getUpdates" in str(excinfo.value)


@pytest.mark.asyncio
async def test_vcrm012_get_updates_network_error_raises_without_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    with pytest.raises(TelegramApiError) as excinfo:
        await _client(handler).get_updates(offset=None, timeout_s=1)
    assert TOKEN not in str(excinfo.value)


# ---------------------------------------------------------------- Telegram: envíos


@pytest.mark.asyncio
async def test_vcrm012_send_message_with_inline_keyboard_is_delivered() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return _ok({"message_id": 321})

    buttons = [[InlineButton("Aceptar", "acc:7"), InlineButton("Rechazar", "rej:7")]]
    result = await _client(handler).send_message(501, "Hola", buttons)

    assert seen["path"].endswith("/sendMessage")
    assert seen["body"]["chat_id"] == 501
    assert seen["body"]["text"] == "Hola"
    assert seen["body"]["reply_markup"] == {
        "inline_keyboard": [
            [
                {"text": "Aceptar", "callback_data": "acc:7"},
                {"text": "Rechazar", "callback_data": "rej:7"},
            ]
        ]
    }
    assert result.delivered is True
    assert result.message_id == "321"
    assert result.error is None


@pytest.mark.asyncio
async def test_vcrm012_send_message_without_buttons_omits_reply_markup() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _ok({"message_id": 1})

    result = await _client(handler).send_message(501, "Hola")
    assert "reply_markup" not in seen["body"]
    assert result.delivered is True


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"ok": False, "description": "Bad Request"}),
        httpx.Response(403, json={"ok": False, "description": "Forbidden: bot was blocked"}),
        httpx.Response(200, json={"ok": True, "result": {}}),  # sin message_id
        httpx.Response(502, text="Bad Gateway"),
    ],
)
@pytest.mark.asyncio
async def test_vcrm012_send_message_not_ok_is_not_delivered(response: httpx.Response) -> None:
    result = await _client(lambda request: response).send_message(501, "Hola")
    assert result.delivered is False
    assert result.message_id is None
    assert result.error is not None
    assert TOKEN not in result.error


@pytest.mark.asyncio
async def test_vcrm012_send_message_timeout_is_not_delivered_and_hides_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"timeout on {request.url}", request=request)

    result = await _client(handler).send_message(501, "Hola")
    assert result.delivered is False
    assert result.error is not None
    assert "timeout" in result.error
    assert TOKEN not in result.error


@pytest.mark.asyncio
async def test_vcrm012_token_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    caplog.set_level("DEBUG")
    await _client(handler).send_message(501, "Hola")
    await _client(handler).answer_callback("cb-1", "ok")
    assert caplog.records
    assert TOKEN not in caplog.text


@pytest.mark.asyncio
async def test_vcrm012_answer_callback_posts_and_swallows_errors() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(400, json={"ok": False})

    await _client(handler).answer_callback("cb-1", "Listo")
    assert seen == [{"callback_query_id": "cb-1", "text": "Listo"}]


@pytest.mark.asyncio
async def test_vcrm012_send_document_multipart_is_delivered(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}
    doc = tmp_path / "ficha.csv"
    doc.write_bytes(b"a;b\n1;2\n")

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["content_type"] = request.headers["content-type"]
        seen["body"] = request.read()
        return _ok({"message_id": 55})

    result = await _client(handler).send_document(501, doc, "Exportación")
    assert seen["path"].endswith("/sendDocument")
    assert seen["content_type"].startswith("multipart/form-data")
    assert b"a;b\n1;2\n" in seen["body"]
    assert b"Exportaci" in seen["body"]
    assert result.delivered is True and result.message_id == "55"


# ---------------------------------------------------------------- Telegram: descargas (VCRM-008)


def _download_handler(content: bytes, declared: int | None) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getFile"):
            result: dict[str, Any] = {"file_id": "f1", "file_path": "documents/f1.pdf"}
            if declared is not None:
                result["file_size"] = declared
            return _ok(result)
        assert "/file/bot" in request.url.path
        return httpx.Response(200, content=content)

    return handler


@pytest.mark.asyncio
async def test_vcrm008_download_within_limit_writes_dest(tmp_path: Path) -> None:
    dest = tmp_path / "in" / "f1.pdf"
    client = _client(_download_handler(b"x" * 100, declared=100))
    result = await client.download_file("f1", dest, max_bytes=1000)
    assert result.ok is True and result.size == 100 and result.error is None
    assert dest.read_bytes() == b"x" * 100
    assert [p.name for p in dest.parent.iterdir()] == ["f1.pdf"]


@pytest.mark.asyncio
async def test_vcrm008_download_declared_too_large_is_rejected_without_file(
    tmp_path: Path,
) -> None:
    dest = tmp_path / "f1.pdf"
    client = _client(_download_handler(b"x" * 10, declared=MAX_ATTACHMENT_BYTES + 1))
    result = await client.download_file("f1", dest, max_bytes=MAX_ATTACHMENT_BYTES)
    assert result.ok is False and result.error == "too_large"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_vcrm008_download_stream_over_limit_is_cut_without_file(tmp_path: Path) -> None:
    dest = tmp_path / "f1.pdf"
    # Tamaño declarado ausente o falso: el corte lo hace el conteo en streaming.
    client = _client(_download_handler(b"x" * 5000, declared=None))
    result = await client.download_file("f1", dest, max_bytes=1000)
    assert result.ok is False and result.error == "too_large"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_vcrm008_download_failure_leaves_no_file_and_hides_token(tmp_path: Path) -> None:
    dest = tmp_path / "f1.pdf"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getFile"):
            return _ok({"file_id": "f1", "file_path": "documents/f1.pdf", "file_size": 10})
        return httpx.Response(500)

    result = await _client(handler).download_file("f1", dest, max_bytes=1000)
    assert result.ok is False and result.error is not None
    assert TOKEN not in result.error
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_vcrm008_download_getfile_failure_is_reported(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "file is too big"})

    result = await _client(handler).download_file("f1", tmp_path / "x", max_bytes=1000)
    assert result.ok is False and result.error is not None
    assert TOKEN not in result.error
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------- Correo (VCRM-105, 140)


class _FakeSMTP:
    instances: list["_FakeSMTP"] = []
    refuse: dict[str, tuple[int, bytes]] = {}
    raise_on_send: Exception | None = None

    def __init__(self, host: str, port: int, **kwargs: Any) -> None:
        self.host, self.port, self.kwargs = host, port, kwargs
        self.calls: list[str] = []
        self.sent: list[EmailMessage] = []
        _FakeSMTP.instances.append(self)

    def __enter__(self) -> "_FakeSMTP":
        return self

    def __exit__(self, *exc: object) -> None:
        self.calls.append("quit")

    def ehlo(self) -> None:
        self.calls.append("ehlo")

    def starttls(self, **kwargs: Any) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(f"login:{user}")

    def send_message(self, msg: EmailMessage) -> dict[str, tuple[int, bytes]]:
        if _FakeSMTP.raise_on_send is not None:
            raise _FakeSMTP.raise_on_send
        self.sent.append(msg)
        return dict(_FakeSMTP.refuse)


class _FakeSMTPSSL(_FakeSMTP):
    pass


@pytest.fixture
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> type[_FakeSMTP]:
    _FakeSMTP.instances = []
    _FakeSMTP.refuse = {}
    _FakeSMTP.raise_on_send = None
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTPSSL)
    return _FakeSMTP


def _sender(security: str) -> SmtpEmailSender:
    return SmtpEmailSender(
        host="smtp.kaisen.test",
        port=587 if security == "starttls" else 465,
        security=security,  # type: ignore[arg-type]
        username="crm@kaisen.test",
        password=SecretStr(PASSWORD),
        sender="crm@kaisen.test",
    )


@pytest.mark.parametrize(
    ("security", "cls", "steps"),
    [
        ("starttls", _FakeSMTP, ["ehlo", "starttls", "ehlo", "login:crm@kaisen.test", "quit"]),
        ("ssl", _FakeSMTPSSL, ["login:crm@kaisen.test", "quit"]),
    ],
)
@pytest.mark.asyncio
async def test_vcrm105_smtp_delivers_with_message_id(
    fake_smtp: type[_FakeSMTP], security: str, cls: type, steps: list[str]
) -> None:
    result = await _sender(security).send("cto@kaisen.test", "Lead aceptado", "Cuerpo")

    (conn,) = fake_smtp.instances
    assert type(conn) is cls
    assert conn.calls == steps
    assert conn.kwargs["timeout"] == 30
    (msg,) = conn.sent
    assert msg["To"] == "cto@kaisen.test"
    assert msg["From"] == "crm@kaisen.test"
    assert msg["Subject"] == "Lead aceptado"
    assert result.delivered is True
    assert result.message_id == msg["Message-ID"]
    assert result.message_id is not None and result.message_id.startswith("<")


@pytest.mark.asyncio
async def test_vcrm105_smtp_refused_recipient_is_not_delivered(
    fake_smtp: type[_FakeSMTP],
) -> None:
    fake_smtp.refuse = {"cto@kaisen.test": (550, b"no such user")}
    result = await _sender("starttls").send("cto@kaisen.test", "S", "B")
    assert result.delivered is False and result.message_id is None
    assert result.error == "recipient_refused"


@pytest.mark.parametrize(
    ("exc", "error"),
    [
        (smtplib.SMTPRecipientsRefused({"cto@kaisen.test": (550, b"no")}), "recipient_refused"),
        (smtplib.SMTPAuthenticationError(535, b"bad credentials"), "auth_failed"),
        (TimeoutError("timed out"), "smtp_error:TimeoutError"),
        (smtplib.SMTPServerDisconnected("bye"), "smtp_error:SMTPServerDisconnected"),
    ],
)
@pytest.mark.asyncio
async def test_vcrm105_smtp_errors_are_not_delivered(
    fake_smtp: type[_FakeSMTP], exc: Exception, error: str
) -> None:
    fake_smtp.raise_on_send = exc
    result = await _sender("ssl").send("cto@kaisen.test", "S", "B")
    assert result.delivered is False
    assert result.error == error
    assert PASSWORD not in (result.error or "")


@pytest.mark.asyncio
async def test_vcrm140_unconfigured_sender_fails_permanently_without_connecting(
    fake_smtp: type[_FakeSMTP],
) -> None:
    result = await UnconfiguredEmailSender().send("cto@kaisen.test", "S", "B")
    assert result.delivered is False
    assert result.permanent is True
    assert result.error == "mailbox_not_configured"
    assert fake_smtp.instances == []


_FULL_SMTP: dict[str, Any] = {
    "smtp_host": "smtp.kaisen.test",
    "smtp_port": 587,
    "smtp_security": "starttls",
    "smtp_username": "crm@kaisen.test",
    "smtp_password": PASSWORD,
    "smtp_from": "crm@kaisen.test",
}


@pytest.mark.parametrize(
    "missing", ["smtp_host", "smtp_port", "smtp_username", "smtp_password", "smtp_from"]
)
def test_vcrm140_build_without_mailbox_or_credentials_is_unconfigured(missing: str) -> None:
    settings = make_settings(**{k: v for k, v in _FULL_SMTP.items() if k != missing})
    assert isinstance(build_email_sender(settings), UnconfiguredEmailSender)


def test_vcrm140_build_defaults_are_unconfigured() -> None:
    assert isinstance(build_email_sender(make_settings()), UnconfiguredEmailSender)


def test_vcrm105_build_with_full_config_is_smtp() -> None:
    sender = build_email_sender(make_settings(**_FULL_SMTP))
    assert isinstance(sender, SmtpEmailSender)
    assert sender.security == "starttls"
    ssl_sender = build_email_sender(make_settings(**{**_FULL_SMTP, "smtp_security": "ssl"}))
    assert isinstance(ssl_sender, SmtpEmailSender) and ssl_sender.security == "ssl"


def test_vcrm105_build_without_security_defaults_to_starttls() -> None:
    sender = build_email_sender(make_settings(**{**_FULL_SMTP, "smtp_security": None}))
    assert isinstance(sender, SmtpEmailSender) and sender.security == "starttls"


def test_vcrm105_password_not_in_repr() -> None:
    assert PASSWORD not in repr(_sender("ssl"))
    assert mail.SMTP_TIMEOUT_S == 30


# ---------------------------------------------------------------- Archivos (VCRM-008)


def test_vcrm008_file_store_save_atomic_moves_tmp(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path / "files")
    tmp = store.new_tmp_path(".pdf")
    tmp.write_bytes(b"pdf-bytes")

    key = store.save_atomic(7, tmp)

    assert not tmp.exists()
    assert key.startswith("7/") and key.endswith(".pdf")
    with store.open(key) as fh:
        assert fh.read() == b"pdf-bytes"


def test_vcrm008_file_store_rejects_over_limit_without_leaving_file(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path / "files", max_bytes=10)
    tmp = store.new_tmp_path()
    tmp.write_bytes(b"x" * 11)

    with pytest.raises(AttachmentTooLarge):
        store.save_atomic(7, tmp)
    assert not tmp.exists()
    assert not (tmp_path / "files" / "7").exists() or not any((tmp_path / "files" / "7").iterdir())


def test_vcrm008_file_store_default_limit_is_20_mb(tmp_path: Path) -> None:
    assert MAX_ATTACHMENT_BYTES == 20 * 1024 * 1024
    assert LocalFileStore(tmp_path).max_bytes == MAX_ATTACHMENT_BYTES


def test_vcrm008_file_store_delete_is_idempotent(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path)
    tmp = store.new_tmp_path()
    tmp.write_bytes(b"a")
    key = store.save_atomic(1, tmp)

    store.delete(key)
    store.delete(key)  # archivo ausente = éxito
    with pytest.raises(FileNotFoundError):
        store.open(key)


@pytest.mark.parametrize("key", ["../evil", "/etc/passwd", "1/../../x"])
def test_vcrm008_file_store_rejects_keys_outside_base(tmp_path: Path, key: str) -> None:
    store = LocalFileStore(tmp_path / "files")
    with pytest.raises(ValueError):
        store.delete(key)


# ---------------------------------------------------------------- Dobles de prueba


@pytest.mark.asyncio
async def test_fakes_satisfy_ports_and_script_failures(tmp_path: Path) -> None:
    tg: TelegramPort = FakeTelegram()
    fake_tg = FakeTelegram()
    fake_tg.fail_next(501, times=1)
    first = await fake_tg.send_message(501, "a", [[InlineButton("x", "y")]])
    second = await fake_tg.send_message(501, "b")
    assert first.delivered is False and second.delivered is True
    assert [s.text for s in fake_tg.attempts] == ["a", "b"]
    assert [s.text for s in fake_tg.sent] == ["b"]
    assert await tg.get_updates(None, 0) == []

    fake_tg.files["f1"] = b"abc"
    ok = await fake_tg.download_file("f1", tmp_path / "f1", max_bytes=10)
    big = await fake_tg.download_file("f1", tmp_path / "f2", max_bytes=1)
    assert ok.ok and (tmp_path / "f1").read_bytes() == b"abc"
    assert big.error == "too_large" and not (tmp_path / "f2").exists()

    email: EmailSender = FakeEmailSender()
    fake_mail = FakeEmailSender()
    fake_mail.fail_next("cto@kaisen.test", times=1)
    assert (await fake_mail.send("cto@kaisen.test", "s", "b")).delivered is False
    assert (await fake_mail.send("cto@kaisen.test", "s", "b")).delivered is True
    assert (await email.send("x@kaisen.test", "s", "b")).delivered is True
    assert [m.to for m in fake_mail.attempts] == ["cto@kaisen.test", "cto@kaisen.test"]
    assert len(fake_mail.sent) == 1

    unconfigured = FakeEmailSender(configured=False)
    res = await unconfigured.send("cto@kaisen.test", "s", "b")
    assert res.permanent is True and res.error == "mailbox_not_configured"

    store: FileStore = LocalFileStore(tmp_path / "store")
    assert store is not None

    clock = FakeClock()
    start = clock.now()
    clock.advance(minutes=5)
    assert (clock.now() - start).total_seconds() == 300
    assert clock.now().tzinfo is not None


# --- Cabeceras de correo opcionales (F2-T16, VCRM-123, 069) ----------------------------------

UNSUB = "<mailto:crm@kaisen.test?subject=BAJA%2042.abcdef>"


@pytest.mark.asyncio
async def test_vcrm123_cabecera_list_unsubscribe_mailto(fake_smtp: type[_FakeSMTP]) -> None:
    result = await _sender("ssl").send(
        "cliente@example.test", "Seguimiento", "Cuerpo", headers={"List-Unsubscribe": UNSUB}
    )

    assert result.delivered is True
    (msg,) = fake_smtp.instances[0].sent
    assert msg["List-Unsubscribe"] == UNSUB
    assert msg["To"] == "cliente@example.test"
    assert msg["Subject"] == "Seguimiento"


@pytest.mark.parametrize(
    ("to", "subject", "headers"),
    [
        ("cliente@example.test\r\nBcc: otro@example.test", "Asunto", None),
        ("cliente@example.test", "Asunto\nBcc: otro@example.test", None),
        ("cliente@example.test", "Asunto", {"List-Unsubscribe": f"{UNSUB}\r\nBcc: x@example.test"}),
        ("cliente@example.test", "Asunto", {"List-Unsubscribe": f"{UNSUB}\nX: y"}),
        ("cliente@example.test", "Asunto", {"X-Extra\nBcc": "valor"}),
        ("cliente@example.test", "Asunto", {"List-Unsubscribe": "valor\x00nulo"}),
        ("cliente@example.test", "Asunto", {"Bcc": "otro@example.test"}),  # nombre prohibido
        ("cliente@example.test", "Asunto", {"subject": "Otro"}),  # sin importar mayúsculas
        ("cliente@example.test", "Asunto", {"Message-ID": "<x@y>"}),
        ("cliente@example.test", "Asunto", {"Nombre Con Espacio": "valor"}),
        ("cliente@example.test", "Asunto", {"": "valor"}),
    ],
)
@pytest.mark.asyncio
async def test_vcrm123_rechaza_crlf_en_cabeceras(
    fake_smtp: type[_FakeSMTP], to: str, subject: str, headers: dict[str, str] | None
) -> None:
    result = await _sender("ssl").send(to, subject, "Cuerpo", headers=headers)

    assert result.delivered is False
    assert result.permanent is True  # reintentar no lo arregla
    assert result.error == "invalid_header"
    assert fake_smtp.instances == []  # ni siquiera se conecta


@pytest.mark.asyncio
async def test_vcrm069_llamadas_f1_sin_cabeceras_siguen_igual(fake_smtp: type[_FakeSMTP]) -> None:
    sender = _sender("ssl")
    positional = await sender.send("cto@kaisen.test", "Lead aceptado", "Cuerpo")
    explicit_none = await sender.send("cto@kaisen.test", "Lead aceptado", "Cuerpo", headers=None)
    empty = await sender.send("cto@kaisen.test", "Lead aceptado", "Cuerpo", headers={})

    assert positional.delivered and explicit_none.delivered and empty.delivered
    for conn in fake_smtp.instances:
        (msg,) = conn.sent
        assert msg["List-Unsubscribe"] is None
        assert set(msg.keys()) <= {
            "From",
            "To",
            "Subject",
            "Message-ID",
            "Content-Type",
            "Content-Transfer-Encoding",
            "MIME-Version",
        }


@pytest.mark.asyncio
async def test_vcrm069_sin_configurar_acepta_cabeceras_y_sigue_fallando() -> None:
    result = await UnconfiguredEmailSender().send(
        "a@b.test", "s", "b", headers={"List-Unsubscribe": UNSUB}
    )
    assert result.delivered is False and result.permanent is True
    assert result.error == "mailbox_not_configured"


@pytest.mark.asyncio
async def test_vcrm123_doble_de_prueba_captura_cabeceras() -> None:
    from crm_support import FakeEmailSender

    fake = FakeEmailSender()
    await fake.send("a@b.test", "s", "b")
    await fake.send("a@b.test", "s", "b", headers={"List-Unsubscribe": UNSUB})

    assert fake.sent[0].headers == {}
    assert fake.sent[1].headers == {"List-Unsubscribe": UNSUB}


@pytest.mark.asyncio
async def test_telegram_repr_y_aclose() -> None:
    client = _client(lambda r: _ok({}))
    assert repr(client) == "HttpxTelegramClient(token=***)"
    await client.aclose()


@pytest.mark.asyncio
async def test_telegram_send_document_api_error_retorna_no_entregado(tmp_path: Path) -> None:
    doc = tmp_path / "ficha.csv"
    doc.write_bytes(b"data")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"ok": False, "description": "internal server error"})

    result = await _client(handler).send_document(501, doc, "Caption")
    assert result.delivered is False
    assert "sendDocument: HTTP 500" in (result.error or "")


@pytest.mark.asyncio
async def test_telegram_download_file_sin_file_path(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ok({"file_id": "f1", "file_size": 10})

    dest = tmp_path / "f1.pdf"
    result = await _client(handler).download_file("f1", dest, max_bytes=1000)
    assert result.ok is False
    assert "missing file_path" in (result.error or "")


@pytest.mark.asyncio
async def test_telegram_download_file_error_de_red(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getFile"):
            return _ok({"file_id": "f1", "file_path": "documents/f1.pdf"})
        raise httpx.ConnectError("conection failed")

    dest = tmp_path / "f1.pdf"
    result = await _client(handler).download_file("f1", dest, max_bytes=1000)
    assert result.ok is False
    assert "downloadFile: ConnectError" in (result.error or "")


@pytest.mark.asyncio
async def test_mail_send_cuerpo_invalido_retorna_error_permanente() -> None:
    sender = _sender("ssl")
    result = await sender.send(
        "dest@k.test",
        "Asunto",
        "\ud800",
    )
    assert result.delivered is False
    assert result.permanent is True
    assert result.error == "invalid_header"


# ---------------------------------------- Correo con adjunto (spec 004: contrato al cliente)


@pytest.mark.asyncio
async def test_smtp_sends_the_attachment_intact(fake_smtp: type[_FakeSMTP]) -> None:
    result = await _sender("starttls").send_with_attachment(
        "cliente@empresa.co",
        "Contrato L-0042",
        "Adjunto el contrato.",
        filename="contrato-L-0042.pdf",
        content=b"%PDF-1.7 datos",
        mime="application/pdf",
    )
    (msg,) = fake_smtp.instances[0].sent
    assert result.delivered is True and msg["To"] == "cliente@empresa.co"
    (attachment,) = list(msg.iter_attachments())
    assert attachment.get_filename() == "contrato-L-0042.pdf"
    assert attachment.get_content_type() == "application/pdf"
    assert attachment.get_payload(decode=True) == b"%PDF-1.7 datos"
    assert msg.get_body(preferencelist=("plain",)).get_content().strip() == "Adjunto el contrato."  # type: ignore[union-attr]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("to", "subject", "filename"),
    [
        ("a@b.co\nBcc: x@y.co", "s", "f.pdf"),
        ("a@b.co", "s\r\nBcc: x@y.co", "f.pdf"),
        ("a@b.co", "s", "f.pdf\r\nX: y"),
        ("a@b.co", "s", ""),
    ],
)
async def test_smtp_attachment_rejects_header_injection(
    fake_smtp: type[_FakeSMTP], to: str, subject: str, filename: str
) -> None:
    result = await _sender("ssl").send_with_attachment(
        to, subject, "cuerpo", filename=filename, content=b"x", mime="application/pdf"
    )
    assert result.delivered is False and result.permanent is True
    assert not fake_smtp.instances or not fake_smtp.instances[0].sent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "error"),
    [
        (smtplib.SMTPAuthenticationError(535, b"no"), "auth_failed"),
        (OSError("down"), "smtp_error:OSError"),
    ],
)
async def test_smtp_attachment_errors_are_not_delivered(
    fake_smtp: type[_FakeSMTP], failure: Exception, error: str
) -> None:
    fake_smtp.raise_on_send = failure
    result = await _sender("ssl").send_with_attachment(
        "a@b.co", "s", "c", filename="f.pdf", content=b"x", mime="application/pdf"
    )
    assert result.delivered is False and result.error == error


@pytest.mark.asyncio
async def test_unconfigured_sender_refuses_attachments_without_connecting() -> None:
    from jerico.crm.mail import UnconfiguredEmailSender

    result = await UnconfiguredEmailSender().send_with_attachment(
        "a@b.co", "s", "c", filename="f.pdf", content=b"x", mime="application/pdf"
    )
    assert result.delivered is False and result.permanent is True
