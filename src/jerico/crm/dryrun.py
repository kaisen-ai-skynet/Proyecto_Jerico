"""`JERICO_EXTERNAL_COMMS_DRY_RUN` (Plan Maestro §4): lo externo se redirige al CTO.

Activo por defecto. Mientras lo esté, ningún correo ni envío a firma sale a terceros: llega al
Telegram o correo del CTO con la marca `[DRY_RUN → destino]` para validar el flujo."""

from collections.abc import Mapping

from jerico.crm.config import CrmSettings
from jerico.crm.ports import AttachmentEmailSender, EmailSender, SendResult


def dry_run_active(settings: CrmSettings) -> bool:
    return settings.external_comms_dry_run


class DryRunEmailSender:
    def __init__(self, inner: EmailSender | AttachmentEmailSender, redirect_to: str) -> None:
        self._inner = inner
        self._redirect_to = redirect_to.strip()

    async def send(
        self, to: str, subject: str, body: str, headers: Mapping[str, str] | None = None
    ) -> SendResult:
        if not self._redirect_to:  # sin destino de pruebas no hay forma segura de enviar
            return SendResult(delivered=False, permanent=True, error="dry_run_without_cto_email")
        marked_body = f"[DRY_RUN] Destinatario original: {to}\n\n{body}"
        return await self._inner.send(
            self._redirect_to, f"[DRY_RUN → {to}] {subject}", marked_body, None
        )

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
        if not self._redirect_to or not hasattr(self._inner, "send_with_attachment"):
            return SendResult(delivered=False, permanent=True, error="dry_run_without_cto_email")
        return await self._inner.send_with_attachment(  # type: ignore[union-attr]
            self._redirect_to,
            f"[DRY_RUN → {to}] {subject}",
            f"[DRY_RUN] Destinatario original: {to}\n\n{body}",
            filename=filename,
            content=content,
            mime=mime,
        )
