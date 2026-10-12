"""F2-T17 — Adaptador IMAP de solo lectura (VCRM-169, 170). Herméticos: `imaplib` falso, sin red."""

import imaplib
import re
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from crm_support import FakeInbox, make_settings
from jerico.crm import inbox as inbox_mod
from jerico.crm.inbox import ImapInbox, UnconfiguredInbox, build_inbox
from jerico.crm.ports import InboxError

PASSWORD = "contraseña-imap-no-real"
USER = "crm@kaisen.test"


def raw_message(
    *,
    message_id: str | None = "<abc@cliente.test>",
    sender: str = "Ana Pérez <ANA@Cliente.Test>",
    subject: str = "Re: Seguimiento",
    body: str = "Me interesa, hablemos.",
    html: str | None = None,
    in_reply_to: str | None = "<sent1@kaisen.test>",
    references: str | None = "<sent0@kaisen.test> <sent1@kaisen.test>",
) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = USER
    msg["Subject"] = subject
    msg["Date"] = "Mon, 12 Oct 2026 10:00:00 -0500"
    if message_id:
        msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    if html is not None and body:
        msg.set_content(body)
        msg.add_alternative(html, subtype="html")
    elif html is not None:
        msg.set_content(html, subtype="html")
    else:
        msg.set_content(body)
    return msg.as_bytes()


class FakeImap:
    """Doble de `imaplib.IMAP4_SSL`: registra cada comando para probar que solo se lee."""

    uidvalidity: int | None = 7
    messages: dict[int, bytes] = {}
    instances: list["FakeImap"] = []
    connect_error: Exception | None = None
    login_error: Exception | None = None

    def __init__(self, host: str, port: int = 993, **kwargs: Any) -> None:
        if FakeImap.connect_error is not None:
            raise FakeImap.connect_error
        self.host, self.port, self.kwargs = host, port, kwargs
        self.commands: list[tuple[str, tuple[Any, ...]]] = []
        self.selected: tuple[str, bool] | None = None
        FakeImap.instances.append(self)

    def __enter__(self) -> "FakeImap":
        return self

    def __exit__(self, *exc: object) -> None:
        self.commands.append(("logout", ()))

    def login(self, user: str, password: str) -> tuple[str, list[bytes]]:
        if FakeImap.login_error is not None:
            raise FakeImap.login_error
        self.commands.append(("login", (user,)))
        return "OK", [b"logged in"]

    def select(self, mailbox: str = "INBOX", readonly: bool = False) -> tuple[str, list[bytes]]:
        self.selected = (mailbox, readonly)
        self.commands.append(("select", (mailbox, readonly)))
        return "OK", [str(len(FakeImap.messages)).encode()]

    def response(self, code: str) -> tuple[str, list[bytes | None]]:
        if FakeImap.uidvalidity is None:
            return code, [None]
        return code, [str(FakeImap.uidvalidity).encode()]

    def uid(self, command: str, *args: Any) -> tuple[str, list[Any]]:
        self.commands.append((f"uid:{command}", args))
        if command == "SEARCH":
            match = re.search(r"UID (\d+):\*", str(args[-1]))
            assert match is not None
            start = int(match.group(1))
            found = [u for u in sorted(FakeImap.messages) if u >= start]
            if not found and FakeImap.messages:  # peculiaridad real de IMAP: devuelve el último
                found = [max(FakeImap.messages)]
            return "OK", [" ".join(map(str, found)).encode()]
        if command == "FETCH":
            uid = int(args[0])
            spec = str(args[1])
            raw = FakeImap.messages[uid]
            partial = re.search(r"<0\.(\d+)>", spec)
            if partial:
                raw = raw[: int(partial.group(1))]
            return "OK", [(f"{uid} (UID {uid} BODY[] {{{len(raw)}}}".encode(), raw), b")"]
        raise AssertionError(f"comando IMAP no permitido en esta prueba: {command}")


@pytest.fixture
def fake_imap(monkeypatch: pytest.MonkeyPatch) -> type[FakeImap]:
    FakeImap.instances = []
    FakeImap.messages = {}
    FakeImap.uidvalidity = 7
    FakeImap.connect_error = None
    FakeImap.login_error = None
    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeImap)
    return FakeImap


def _inbox(**overrides: Any) -> ImapInbox:
    kwargs: dict[str, Any] = {
        "host": "imap.kaisen.test",
        "port": 993,
        "username": USER,
        "password": SecretStr(PASSWORD),
    }
    return ImapInbox(**{**kwargs, **overrides})


@pytest.mark.asyncio
async def test_vcrm169_lectura_solo_lectura_peek(fake_imap: type[FakeImap]) -> None:
    fake_imap.messages = {6: raw_message(), 7: raw_message(message_id="<def@cliente.test>")}

    batch = await _inbox().fetch_new(None, 0)

    (conn,) = fake_imap.instances
    assert conn.selected == ("INBOX", True)  # EXAMINE: no cambia banderas
    assert ("login", (USER,)) in conn.commands
    fetches = [args for name, args in conn.commands if name == "uid:FETCH"]
    assert fetches and all("BODY.PEEK[]" in str(a[1]) for a in fetches)
    names = {name for name, _ in conn.commands}
    assert names <= {
        "login",
        "select",
        "uid:SEARCH",
        "uid:FETCH",
        "logout",
    }  # nada de STORE/EXPUNGE
    assert conn.kwargs["timeout"] == 30
    assert batch.uidvalidity == 7 and batch.has_more is False
    first = batch.messages[0]
    assert (first.uid, first.rfc_message_id) == (6, "<abc@cliente.test>")
    assert first.from_addr == "ana@cliente.test"
    assert first.subject == "Re: Seguimiento"
    assert first.body_text == "Me interesa, hablemos."
    assert first.in_reply_to == "<sent1@kaisen.test>"
    assert first.references == ("<sent0@kaisen.test>", "<sent1@kaisen.test>")
    assert first.date is not None and first.date.utcoffset() is not None
    assert first.truncated is False


@pytest.mark.asyncio
async def test_vcrm169_uidvalidity_distinto_reinicia(fake_imap: type[FakeImap]) -> None:
    fake_imap.messages = {3: raw_message(message_id="<a@x>"), 4: raw_message(message_id="<b@x>")}
    # Mismo UIDVALIDITY: solo lo posterior al último UID procesado.
    batch = await _inbox().fetch_new(7, 3)
    assert [m.uid for m in batch.messages] == [4]
    # Sin mensajes nuevos: IMAP devuelve igualmente el último; el adaptador lo descarta.
    assert (await _inbox().fetch_new(7, 4)).messages == ()
    # UIDVALIDITY distinto: los UID viejos ya no valen y se relee desde el principio.
    reset = await _inbox().fetch_new(5, 100)
    assert reset.uidvalidity == 7
    assert [m.uid for m in reset.messages] == [3, 4]
    # Primera vez (sin UIDVALIDITY guardado) también lee desde el principio.
    assert [m.uid for m in (await _inbox().fetch_new(None, 0)).messages] == [3, 4]
    fake_imap.messages = {}
    assert (await _inbox().fetch_new(7, 0)).messages == ()


@pytest.mark.asyncio
async def test_vcrm169_tope_256kb_y_lote_50(fake_imap: type[FakeImap]) -> None:
    fake_imap.messages = {i: raw_message(message_id=f"<m{i}@x>") for i in range(1, 61)}

    first = await _inbox().fetch_new(None, 0)
    assert [m.uid for m in first.messages] == list(range(1, 51))
    assert first.has_more is True
    second = await _inbox().fetch_new(first.uidvalidity, 50)
    assert [m.uid for m in second.messages] == list(range(51, 61))
    assert second.has_more is False

    big = raw_message(message_id="<big@x>", body="x" * 300_000)
    assert len(big) > 256 * 1024
    fake_imap.messages = {1: big}
    fake_imap.instances = []
    (message,) = (await _inbox().fetch_new(None, 0)).messages
    assert message.truncated is True
    fetch = next(a for n, a in fake_imap.instances[0].commands if n == "uid:FETCH")
    assert "<0.262144>" in str(fetch[1])  # el servidor solo entrega los primeros 256 KB
    assert len(message.body_text) <= 20_000


@pytest.mark.asyncio
async def test_vcrm169_mensaje_sin_message_id_usa_hash(fake_imap: type[FakeImap]) -> None:
    fake_imap.messages = {
        1: raw_message(message_id=None, body="uno"),
        2: raw_message(message_id=None, body="dos"),
    }
    a = (await _inbox().fetch_new(None, 0)).messages
    b = (await _inbox().fetch_new(None, 0)).messages

    assert a[0].rfc_message_id.startswith("<noid-") and a[0].rfc_message_id.endswith(
        "@crm.invalid>"
    )
    assert a[0].rfc_message_id != a[1].rfc_message_id
    assert [m.rfc_message_id for m in a] == [m.rfc_message_id for m in b]  # estable entre sondeos


def test_vcrm169_sin_ruta_publica() -> None:
    source = Path(inbox_mod.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "import socket",
        "socketserver",
        "http.server",
        ".bind(",
        ".listen(",
        "aiohttp",
    ):
        assert forbidden not in source, forbidden


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        OSError("[Errno 111] Connection refused"),
        TimeoutError("timed out"),
        imaplib.IMAP4.error(f"LOGIN failed for {USER} with {PASSWORD}"),
    ],
)
async def test_vcrm170_fallo_de_conexion_sin_secreto_en_error(
    fake_imap: type[FakeImap], error: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    if isinstance(error, imaplib.IMAP4.error):
        fake_imap.login_error = error
    else:
        fake_imap.connect_error = error

    with pytest.raises(InboxError) as exc:
        await _inbox().fetch_new(None, 0)

    text = f"{exc.value} {exc.value!r} {caplog.text}"
    assert PASSWORD not in text and USER not in text
    assert type(error).__name__ in str(exc.value)  # solo el tipo de error, útil para diagnóstico
    assert PASSWORD not in repr(_inbox())


@pytest.mark.asyncio
async def test_vcrm169_html_se_reduce_a_texto(fake_imap: type[FakeImap]) -> None:
    html = (
        "<html><head><style>p{color:red}</style><script>alert('x')</script></head>"
        "<body><p>Hola&nbsp;equipo &amp; amigos</p><p>Segunda l&iacute;nea</p>"
        "<div>Tercera<br>cuarta</div></body></html>"
    )
    fake_imap.messages = {
        1: raw_message(message_id="<h1@x>", body="", html=html),  # solo HTML
        2: raw_message(message_id="<h2@x>", body="Texto plano", html="<p>Versión HTML</p>"),
    }

    only_html, alternative = (await _inbox().fetch_new(None, 0)).messages

    assert "alert" not in only_html.body_text and "color" not in only_html.body_text
    assert "<" not in only_html.body_text and "&amp;" not in only_html.body_text
    assert only_html.body_text.splitlines() == [
        "Hola equipo & amigos",
        "Segunda línea",
        "Tercera",
        "cuarta",
    ]
    assert alternative.body_text == "Texto plano"  # prefiere la parte de texto plano


@pytest.mark.asyncio
async def test_vcrm169_mensaje_ilegible_no_rompe_el_lote(fake_imap: type[FakeImap]) -> None:
    fake_imap.messages = {
        1: b"\xff\xfe\x00 esto no es un correo",
        2: raw_message(message_id="<ok@x>"),
        3: raw_message(subject="=?utf-8?q?Asunto_con_tilde_=C3=B3?=", message_id="<enc@x>"),
    }

    broken, fine, encoded = (await _inbox().fetch_new(None, 0)).messages

    assert broken.rfc_message_id.startswith("<noid-")
    assert broken.from_addr == ""  # sin remitente fiable: la clasificación lo mandará a revisión
    assert fine.rfc_message_id == "<ok@x>"
    assert encoded.subject == "Asunto con tilde ó"


@pytest.mark.asyncio
async def test_vcrm169_unconfigured_y_build_inbox() -> None:
    with pytest.raises(InboxError, match="inbox_not_configured"):
        await UnconfiguredInbox().fetch_new(None, 0)

    assert isinstance(build_inbox(make_settings()), UnconfiguredInbox)
    partial = make_settings(imap_host="imap.kaisen.test", imap_username=USER)
    assert isinstance(build_inbox(partial), UnconfiguredInbox)  # falta la contraseña
    full = make_settings(
        imap_host="imap.kaisen.test",
        imap_username=USER,
        imap_password=PASSWORD,
        imap_mailbox="Clientes",
    )
    built = build_inbox(full)
    assert isinstance(built, ImapInbox) and built.mailbox == "Clientes" and built.port == 993


@pytest.mark.asyncio
async def test_vcrm169_doble_de_prueba_fake_inbox() -> None:
    from jerico.crm.ports import InboundMessage

    msg = InboundMessage(
        uid=1,
        rfc_message_id="<a@x>",
        in_reply_to=None,
        references=(),
        from_addr="a@x",
        subject="s",
        body_text="b",
        date=None,
        truncated=False,
    )
    fake = FakeInbox([msg])
    batch = await fake.fetch_new(None, 0)
    assert batch.messages == (msg,) and batch.uidvalidity == 1
    assert (await fake.fetch_new(1, 1)).messages == ()
    fake.fail_next(InboxError("imap_error:OSError"))
    with pytest.raises(InboxError):
        await fake.fetch_new(1, 1)
    assert (await fake.fetch_new(1, 1)).messages == ()  # se recupera tras el fallo


@pytest.mark.asyncio
async def test_vcrm169_cabeceras_y_cuerpos_atipicos(fake_imap: type[FakeImap]) -> None:
    sin_fecha_valida = raw_message(message_id="<d@x>").replace(
        b"Mon, 12 Oct 2026 10:00:00 -0500", b"no es una fecha"
    )
    solo_adjunto = EmailMessage()
    solo_adjunto["From"] = "Ana <ana@cliente.test>"
    solo_adjunto["Message-ID"] = "<adj@x>"
    solo_adjunto.set_content("x")
    solo_adjunto.clear_content()
    solo_adjunto.add_attachment(
        b"%PDF-1.4", maintype="application", subtype="pdf", filename="a.pdf"
    )
    charset_raro = (
        b"From: ana@cliente.test\r\nMessage-ID: <cs@x>\r\n"
        b"Content-Type: text/plain; charset=charset-que-no-existe\r\n\r\nhola \xe1"
    )
    fake_imap.messages = {1: sin_fecha_valida, 2: solo_adjunto.as_bytes(), 3: charset_raro}

    fecha, adjunto, charset = (await _inbox().fetch_new(None, 0)).messages

    assert fecha.date is None and fecha.body_text == "Me interesa, hablemos."
    assert adjunto.body_text == ""  # un adjunto no es texto del titular
    assert charset.rfc_message_id == "<cs@x>" and charset.body_text.startswith("hola")


@pytest.mark.asyncio
async def test_vcrm170_servidor_sin_uidvalidity_es_un_fallo_del_buzon(
    fake_imap: type[FakeImap],
) -> None:
    fake_imap.uidvalidity = None
    with pytest.raises(InboxError, match="no_uidvalidity"):
        await _inbox().fetch_new(None, 0)


@pytest.mark.asyncio
async def test_vcrm169_si_el_analizador_falla_queda_un_registro_para_revision(
    fake_imap: type[FakeImap], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise ValueError("correo imposible")

    monkeypatch.setattr(inbox_mod.email, "message_from_bytes", boom)
    fake_imap.messages = {1: raw_message()}

    (message,) = (await _inbox().fetch_new(None, 0)).messages

    assert message.rfc_message_id.startswith("<noid-") and message.from_addr == ""
    assert message.body_text == "" and message.uid == 1
