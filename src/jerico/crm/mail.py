"""Correo interno por SMTP (plan §6.2; VCRM-105, 140).

Solo destinatarios internos: el llamador resuelve la dirección desde `crm_users`.
"""

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Literal

from pydantic import SecretStr

from jerico.crm.config import CrmSettings
from jerico.crm.ports import EmailSender, SendResult

logger = logging.getLogger(__name__)

SMTP_TIMEOUT_S = 30
Security = Literal["starttls", "ssl"]


class UnconfiguredEmailSender:
    """Buzón o credenciales sin configurar: fallo permanente sin conectar (VCRM-140)."""

    async def send(self, to: str, subject: str, body: str) -> SendResult:
        return SendResult(delivered=False, permanent=True, error="mailbox_not_configured")


class SmtpEmailSender:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        security: Security,
        username: str,
        password: SecretStr,
        sender: str,
        timeout_s: float = SMTP_TIMEOUT_S,
    ) -> None:
        self.host, self.port, self.security = host, port, security
        self.username, self.sender, self.timeout_s = username, sender, timeout_s
        self._password = password

    def __repr__(self) -> str:
        return f"SmtpEmailSender(host={self.host!r}, port={self.port}, security={self.security!r})"

    async def send(self, to: str, subject: str, body: str) -> SendResult:
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = to
        msg["Subject"] = subject
        msg["Message-ID"] = make_msgid(domain=self.sender.rpartition("@")[2] or None)
        msg.set_content(body)
        try:
            refused = await asyncio.to_thread(self._send_sync, msg)
        except smtplib.SMTPRecipientsRefused:
            return self._failed("recipient_refused")
        except smtplib.SMTPAuthenticationError:
            return self._failed("auth_failed")
        except (smtplib.SMTPException, OSError) as exc:
            return self._failed(f"smtp_error:{type(exc).__name__}")
        if refused:
            return self._failed("recipient_refused")
        return SendResult(delivered=True, message_id=msg["Message-ID"])

    def _send_sync(self, msg: EmailMessage) -> dict[str, tuple[int, bytes]]:
        context = ssl.create_default_context()
        smtp: smtplib.SMTP
        if self.security == "ssl":
            smtp = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout_s, context=context)
        else:
            smtp = smtplib.SMTP(self.host, self.port, timeout=self.timeout_s)
        with smtp:
            if self.security == "starttls":
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
            smtp.login(self.username, self._password.get_secret_value())
            return smtp.send_message(msg)

    @staticmethod
    def _failed(error: str) -> SendResult:
        logger.warning("smtp send failed: %s", error)
        return SendResult(delivered=False, error=error)


def build_email_sender(settings: CrmSettings) -> EmailSender:
    """Sin host, puerto, remitente o credenciales → `UnconfiguredEmailSender` (VCRM-140)."""
    if (
        not settings.smtp_host
        or not settings.smtp_port
        or not settings.smtp_from
        or not settings.smtp_username
        or settings.smtp_password is None
        or not settings.smtp_password.get_secret_value()
    ):
        return UnconfiguredEmailSender()
    return SmtpEmailSender(
        host=settings.smtp_host,
        port=settings.smtp_port,
        security=settings.smtp_security or "starttls",
        username=settings.smtp_username,
        password=settings.smtp_password,
        sender=settings.smtp_from,
    )
