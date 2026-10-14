"""Contrato y firma (spec 004 §5, §8): subida, devolución, forma especial y envío a firma.

El texto jurídico lo escribe siempre el abogado (VCRM-C13): aquí solo se guarda, se aprueba y se
envía a firmar el archivo que él subió, y solo si su huella coincide con la aprobada (VCRM-C12).
La llamada al proveedor ocurre tras el *commit* (patrón `bot.defer`); nada sale sin ✅."""

import hashlib
import re
import shutil
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

from jerico.crm import closing_repo as crepo
from jerico.crm import leads, permissions, repo
from jerico.crm.bot import (
    CallbackHandler,
    CommandHandler,
    CrmBot,
    DeferredJob,
    FilePendingHandler,
    deny,
)
from jerico.crm.closing_flow import (
    ClosingContext,
    as_lawyer,
    as_lawyer_file,
    contract_route,
    rebuild_package,
)
from jerico.crm.closing_model import Contract, ContractStatus, PackageStatus
from jerico.crm.db import CrmDatabase
from jerico.crm.idempotency import claim, make_key, release
from jerico.crm.leads import Prefetched
from jerico.crm.model import (
    AuditAction,
    AuditOutcome,
    Channel,
    Lead,
    LeadState,
    Outgoing,
    PendingInput,
    Role,
    User,
)
from jerico.crm.outbox import enqueue_critical
from jerico.crm.package import attachment_name, render_markdown
from jerico.crm.parsing import build_callback, parse_short_id
from jerico.crm.permissions import Action, authorize
from jerico.crm.ports import SendResult, TelegramPort, Update
from jerico.crm.render import short_id
from jerico.crm.signature import SignatureError, SignRequest
from jerico.crm.timeutil import from_iso, to_iso

CONTRACT_FILE_KIND = "contract_file"
SIGN_OK = "sigok"
SIGN_NO = "signo"
POLL_META = "contract_poll_last"
POLL_EVERY = timedelta(minutes=5)
MAX_REASON = 300
PDF_MAGIC = b"%PDF-"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
STALE_PACKAGE = "Los datos del paquete cambiaron. Pídele al comercial que lo genere de nuevo."
ZIP_MAGIC = b"PK\x03\x04"  # DOCX

ASK_FILE = "Envíame ahora el contrato como documento adjunto (PDF o DOCX)."
NEED_FILE = "Necesito el contrato como archivo adjunto (PDF o DOCX). Vuelve a usar /subircontrato."
BAD_FILE = "El archivo no parece un PDF ni un DOCX. No lo guardé."
FILE_FAIL = "No pude descargar el archivo. No lo guardé; vuelve a intentarlo."
NO_CONTRACT = "Ese caso no tiene un paquete enviado esperando contrato."
NO_SIGNATURE = "La firma electrónica no está configurada todavía. Avisa al CTO."
WRONG_STATE = "Ese contrato no está en un estado que permita esta acción."
SIGN_UNAVAILABLE = "No se pudo enviar a firma ahora. Inténtalo de nuevo con /firma en unos minutos."
HASH_CHANGED = "El archivo del contrato ya no coincide con el que se subió. No se envía a firma."
LEAD_BLOCKED = "El lead ya no admite envíos: no está aceptado, está suprimido o bloqueado."
CLOSED = "Esa solicitud ya no está pendiente."
NO_EMAIL = "El lead no tiene correo: sin él no hay a quién enviar la firma."


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _audit(
    conn: sqlite3.Connection,
    actor: User,
    action: AuditAction,
    lead_id: int,
    outcome: AuditOutcome,
    now: datetime,
) -> None:
    repo.audit(
        conn, actor=f"user:{actor.id}", action=action, outcome=outcome, at=now, lead_id=lead_id
    )


def contract_filename(lead_id: int, key: str) -> str:
    """Nombre neutro del archivo (sin datos personales); la extensión viene del archivo."""
    return f"contrato-{short_id(lead_id)}{Path(key).suffix}"


def _stakeholders(conn: sqlite3.Connection, lead: Lead) -> list[User]:
    """Comercial del lead (si está activo) y todos los CTO activos, sin repetir."""
    seen: dict[int, User] = {}
    for user in permissions.commercial_recipients(lead, repo.active_users(conn)):
        seen[user.id] = user
    for cto in repo.active_users(conn, Role.CTO):
        seen[cto.id] = cto
    return list(seen.values())


def _notify(
    conn: sqlite3.Connection, lead: Lead, kind: str, text: str, tag: str, now: datetime
) -> None:
    for user in _stakeholders(conn, lead):
        enqueue_critical(
            conn,
            kind=kind,
            channel=Channel.TELEGRAM,
            recipient_user_id=user.id,
            lead_id=lead.id,
            subject=None,
            body=text,
            key=make_key(kind, lead.id, tag, user.id),
            now=now,
        )


def _target(
    conn: sqlite3.Connection, actor: User, action: Action, arg: str, now: datetime
) -> tuple[Lead, Contract] | list[Outgoing]:
    """Lead + contrato vivo del caso, o la respuesta de error ya armada."""
    chat = actor.telegram_id
    lead_id = parse_short_id(arg.split(maxsplit=1)[0]) if arg.strip() else None
    lead = None if lead_id is None else repo.get_lead(conn, lead_id)
    if lead is None:
        return [Outgoing(chat, "Indica el caso, por ejemplo: L-0042")]
    decision = authorize(actor, action, lead)
    if not decision.allowed:
        return leads.deny_lead(conn, actor, decision, lead.id, now)
    package = crepo.live_package(conn, lead.id)
    contract = None if package is None else crepo.contract_for_package(conn, package.id)
    if package is None or package.status != PackageStatus.SENT or contract is None:
        return [Outgoing(chat, NO_CONTRACT)]
    return lead, contract


def _args(text: str) -> str:
    return re.sub(r"^/\w+(?:@\w+)?", "", text.strip()).strip()


def _lead_open(lead: Lead) -> bool:
    return (
        lead.state == LeadState.ACCEPTED
        and lead.suppressed_at is None
        and not lead.commercial_block
    )


# --- Abogado ----------------------------------------------------------------------------------


def upload_command(
    conn: sqlite3.Connection, actor: User, text: str, now: datetime
) -> list[Outgoing]:
    found = _target(conn, actor, Action.CONTRACT_UPLOAD, _args(text), now)
    if isinstance(found, list):
        return found
    lead, contract = found
    if contract.status not in (ContractStatus.PACKAGE_SENT, ContractStatus.CONTRACT_UPLOADED):
        return [Outgoing(actor.telegram_id, WRONG_STATE)]
    repo.set_pending_input(
        conn, user_id=actor.id, kind=CONTRACT_FILE_KIND, lead_id=lead.id, now=now
    )
    return [Outgoing(actor.telegram_id, ASK_FILE)]


def file_handler(ctx: ClosingContext, bot: CrmBot, db: CrmDatabase) -> FilePendingHandler:
    def handler(
        conn: sqlite3.Connection,
        actor: User,
        pending: PendingInput,
        update: Update,
        prefetch: Prefetched | None,
        now: datetime,
    ) -> list[Outgoing]:
        chat = actor.telegram_id
        if prefetch is None or update.file is None:
            return [Outgoing(chat, NEED_FILE)]
        if not prefetch.result.ok:
            return [Outgoing(chat, FILE_FAIL)]
        if prefetch.kind != "document":
            return [Outgoing(chat, BAD_FILE)]
        head = prefetch.path.read_bytes()[:8] if prefetch.path.exists() else b""
        if not (head.startswith(PDF_MAGIC) or head.startswith(ZIP_MAGIC)):
            return [Outgoing(chat, BAD_FILE)]
        found = _target(conn, actor, Action.CONTRACT_UPLOAD, short_id(pending.lead_id or 0), now)
        if isinstance(found, list):
            return found
        lead, contract = found
        if contract.status not in (ContractStatus.PACKAGE_SENT, ContractStatus.CONTRACT_UPLOADED):
            return [Outgoing(chat, WRONG_STATE)]
        if ctx.files is None:
            return [Outgoing(chat, FILE_FAIL)]
        digest = hashlib.sha256(prefetch.path.read_bytes()).hexdigest()
        extension = ".pdf" if head.startswith(PDF_MAGIC) else ".docx"
        typed = prefetch.path.with_name(prefetch.path.name + extension)  # la clave conserva el tipo
        prefetch.path.rename(typed)
        key = ctx.files.save_atomic(lead.id, typed)
        if contract.file_path and contract.file_path != key:
            ctx.files.delete(contract.file_path)
        crepo.update_contract(
            conn,
            contract.id,
            status=ContractStatus.CONTRACT_UPLOADED,
            file_path=key,
            sha256=digest,
            uploaded_by=actor.id,
            approved_by=None,
        )
        _audit(conn, actor, AuditAction.CONTRACT_EVENT, lead.id, AuditOutcome.OK, now)
        _notify(
            conn,
            lead,
            "contract_uploaded",
            f"El abogado subió el contrato de {short_id(lead.id)} (huella {digest[:12]}). "
            f"Revísalo con él y, si está bien, envíalo a firma con /firma {short_id(lead.id)}.",
            digest[:12],
            now,
        )
        _queue_delivery(conn, ctx, bot, db, lead, contract.id, key, digest, chat, now)
        return [Outgoing(chat, f"Contrato de {short_id(lead.id)} recibido (huella {digest[:12]}).")]

    return handler


async def _send_document(
    telegram: TelegramPort, ctx: ClosingContext, chat_id: int, name: str, data: bytes, caption: str
) -> SendResult:
    """Escribe el archivo con su nombre neutro en una carpeta temporal 600 y lo envía."""
    if ctx.files is None:
        return SendResult(delivered=False, error="no_file_store", permanent=True)
    folder = ctx.files.new_tmp_path()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    try:
        path.write_bytes(data)
        path.chmod(0o600)
        return await telegram.send_document(chat_id, path, caption)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _queue_delivery(
    conn: sqlite3.Connection,
    ctx: ClosingContext,
    bot: CrmBot,
    db: CrmDatabase,
    lead: Lead,
    contract_id: int,
    key: str,
    digest: str,
    lawyer_chat: int,
    now: datetime,
) -> None:
    """Al subir el contrato: archivo al comercial y, si la venta lo pide, al cliente por correo.

    Cada destino reserva una clave idempotente (contrato + huella + destino): resubir el mismo
    archivo no lo reenvía; uno distinto sí. El correo al cliente respeta DRY_RUN (lo redirige el
    remitente) y exige que el lead siga abierto."""
    targets = ["commercial"]
    if (
        contract_route(conn, lead.id) == "cliente"
        and _lead_open(lead)
        and (lead.email or "").strip()
    ):
        targets.append("client")
    claimed = [
        t
        for t in targets
        if claim(conn, make_key("contract_delivery", contract_id, digest[:12], t), now)
    ]
    if not claimed:
        return
    recipients = permissions.commercial_recipients(lead, repo.active_users(conn))
    comercial_chat = recipients[0].telegram_id if recipients else None
    name = contract_filename(lead.id, key)
    client_email = (lead.email or "").strip()

    async def job() -> list[Outgoing]:
        assert ctx.files is not None  # noqa: S101 - el contrato se acaba de guardar ahí
        with ctx.files.open(key) as handle:
            data = handle.read()
        notes: list[str] = []
        if "commercial" in claimed:
            if ctx.telegram is None or comercial_chat is None:
                notes.append("no pude entregarlo al comercial (sin canal)")
                _release(db, contract_id, digest, "commercial")
            else:
                sent = await _send_document(
                    ctx.telegram,
                    ctx,
                    comercial_chat,
                    name,
                    data,
                    f"Contrato de {short_id(lead.id)} para entregar al cliente.",
                )
                if sent.delivered:
                    notes.append("enviado al comercial")
                else:
                    notes.append("el comercial no recibió el archivo")
                    _release(db, contract_id, digest, "commercial")
        if "client" in claimed:
            sent_mail = (
                await ctx.email.send_with_attachment(
                    client_email,
                    f"Contrato {short_id(lead.id)}",
                    "Adjuntamos el contrato para su revisión y firma. "
                    "Responda a este correo si tiene preguntas.",
                    filename=name,
                    content=data,
                    mime="application/pdf" if name.endswith(".pdf") else DOCX_MIME,
                )
                if ctx.email is not None
                else SendResult(delivered=False, error="no_email_channel", permanent=True)
            )
            if sent_mail.delivered:
                notes.append("enviado al cliente por correo")
            else:
                notes.append("no pude enviarlo al cliente por correo; entrégalo tú")
                _release(db, contract_id, digest, "client")
        return [Outgoing(lawyer_chat, f"Entrega de {short_id(lead.id)}: " + "; ".join(notes) + ".")]

    bot.defer(job)


def _release(db: CrmDatabase, contract_id: int, digest: str, target: str) -> None:
    with db.tx() as tx:
        release(tx, make_key("contract_delivery", contract_id, digest[:12], target))


def download_command(ctx: ClosingContext, bot: CrmBot, telegram: TelegramPort) -> CommandHandler:
    """`/descargar L-n`: el paquete como archivo Markdown para leerlo o editarlo (VCRM-R02)."""

    def command(conn: sqlite3.Connection, actor: User, text: str, now: datetime) -> list[Outgoing]:
        chat = actor.telegram_id
        lead_id = parse_short_id(_args(text))
        lead = None if lead_id is None else repo.get_lead(conn, lead_id)
        if lead is None:
            return [Outgoing(chat, "Indica el caso, por ejemplo: /descargar L-0042")]
        decision = authorize(actor, Action.PACKAGE_VIEW, lead)
        if not decision.allowed:
            return leads.deny_lead(conn, actor, decision, lead.id, now)
        package = crepo.live_package(conn, lead.id)
        if package is None or package.status != PackageStatus.SENT:
            return [Outgoing(chat, "Ese caso no tiene un paquete enviado.")]
        built = rebuild_package(conn, lead, package, now)
        if built is None:  # pragma: no cover - la oferta existe por clave foránea
            return [Outgoing(chat, STALE_PACKAGE)]
        data = render_markdown(built).encode("utf-8")
        name = attachment_name(lead.id, package.version)

        async def job() -> list[Outgoing]:
            sent = await _send_document(
                telegram,
                ctx,
                chat,
                name,
                data,
                f"Paquete de {short_id(lead.id)} (v{package.version}).",
            )
            return [] if sent.delivered else [Outgoing(chat, "No pude enviarte el archivo ahora.")]

        bot.defer(job)
        return [Outgoing(chat, "Preparando el archivo…")]

    return command


def return_command(
    conn: sqlite3.Connection, actor: User, text: str, now: datetime
) -> list[Outgoing]:
    arg = _args(text)
    found = _target(conn, actor, Action.CONTRACT_UPLOAD, arg, now)
    if isinstance(found, list):
        return found
    lead, contract = found
    reason = arg.split(maxsplit=1)[1].strip() if len(arg.split(maxsplit=1)) > 1 else ""
    if not reason:
        return [
            Outgoing(actor.telegram_id, "Indica el motivo: /devolver L-0042 falta la cláusula X")
        ]
    if contract.status not in (ContractStatus.PACKAGE_SENT, ContractStatus.CONTRACT_UPLOADED):
        return [Outgoing(actor.telegram_id, WRONG_STATE)]
    reason = reason[:MAX_REASON]
    crepo.update_contract(conn, contract.id, status=ContractStatus.CANCELLED, return_reason=reason)
    crepo.set_package_status(conn, contract.package_id, PackageStatus.SUPERSEDED)
    _audit(conn, actor, AuditAction.CONTRACT_EVENT, lead.id, AuditOutcome.OK, now)
    _notify(
        conn,
        lead,
        "contract_returned",
        f"El abogado devolvió el paquete de {short_id(lead.id)}: {reason}. "
        "Corrige y vuelve a generarlo con /oferta.",
        str(contract.id),
        now,
    )
    return [Outgoing(actor.telegram_id, f"Devolución de {short_id(lead.id)} registrada y avisada.")]


def special_form_command(
    conn: sqlite3.Connection, actor: User, text: str, now: datetime
) -> list[Outgoing]:
    found = _target(conn, actor, Action.CONTRACT_UPLOAD, _args(text), now)
    if isinstance(found, list):
        return found
    lead, contract = found
    if contract.status not in (ContractStatus.PACKAGE_SENT, ContractStatus.CONTRACT_UPLOADED):
        return [Outgoing(actor.telegram_id, WRONG_STATE)]
    crepo.update_contract(conn, contract.id, status=ContractStatus.SPECIAL_FORM)
    _audit(conn, actor, AuditAction.CONTRACT_EVENT, lead.id, AuditOutcome.OK, now)
    _notify(
        conn,
        lead,
        "contract_special_form",
        f"El abogado indica que el contrato de {short_id(lead.id)} requiere firma certificada o "
        "presencial. No se enviará a firma electrónica.",
        str(contract.id),
        now,
    )
    return [Outgoing(actor.telegram_id, "Marcado como firma certificada o presencial.")]


# --- Comercial / CTO: aprobar el envío a firma ---------------------------------------------


def sign_command(ctx: ClosingContext) -> CommandHandler:
    def command(conn: sqlite3.Connection, actor: User, text: str, now: datetime) -> list[Outgoing]:
        chat = actor.telegram_id
        found = _target(conn, actor, Action.CONTRACT_APPROVE, _args(text), now)
        if isinstance(found, list):
            return found
        lead, contract = found
        if ctx.signature is None:
            return [Outgoing(chat, NO_SIGNATURE)]
        if contract.status != ContractStatus.CONTRACT_UPLOADED or not contract.sha256:
            return [Outgoing(chat, WRONG_STATE)]
        if not _lead_open(lead):
            return [Outgoing(chat, LEAD_BLOCKED)]
        if not (lead.email or "").strip():
            return [
                Outgoing(chat, "El lead no tiene correo: sin él no hay a quién enviar la firma.")
            ]
        shown = contract_filename(lead.id, contract.file_path or "")
        suffix = " (DRY_RUN: no saldrá del sistema)" if ctx.dry_run else ""
        return [
            Outgoing(
                chat,
                f"¿Enviar a firma electrónica {shown} (huella {contract.sha256[:12]}) de "
                f"{short_id(lead.id)} al cliente? Vigencia: {ctx.validity_days} días.{suffix}",
                (
                    (
                        ("✅ Enviar a firma", build_callback(SIGN_OK, str(contract.id))),
                        ("❌ Cancelar", build_callback(SIGN_NO, str(contract.id))),
                    ),
                ),
            )
        ]

    return command


def _contract_for_callback(
    conn: sqlite3.Connection, args: tuple[str, ...]
) -> tuple[Contract | None, Lead | None]:
    if len(args) != 1 or not args[0].isdigit():
        return None, None
    contract = crepo.get_contract(conn, int(args[0]))
    package = None if contract is None else crepo.get_package(conn, contract.package_id)
    lead = None if package is None else repo.get_lead(conn, package.lead_id)
    return contract, lead


def cancel_sign_callback(
    conn: sqlite3.Connection, actor: User, args: tuple[str, ...], now: datetime
) -> list[Outgoing]:
    contract, lead = _contract_for_callback(conn, args)
    if contract is None or lead is None:
        return [Outgoing(actor.telegram_id, CLOSED)]
    decision = authorize(actor, Action.CONTRACT_APPROVE, lead)
    if not decision.allowed:
        return leads.deny_lead(conn, actor, decision, lead.id, now)
    return [Outgoing(actor.telegram_id, "Envío a firma cancelado; el contrato sigue sin firmar.")]


def send_sign_callback(ctx: ClosingContext, bot: CrmBot, db: CrmDatabase) -> CallbackHandler:
    def handler(
        conn: sqlite3.Connection, actor: User, args: tuple[str, ...], now: datetime
    ) -> list[Outgoing]:
        chat = actor.telegram_id
        contract, lead = _contract_for_callback(conn, args)
        if contract is None or lead is None or contract.status != ContractStatus.CONTRACT_UPLOADED:
            return [Outgoing(chat, CLOSED)]
        decision = authorize(actor, Action.CONTRACT_APPROVE, lead)
        if not decision.allowed:
            return leads.deny_lead(conn, actor, decision, lead.id, now)
        port = ctx.signature
        if port is None or ctx.files is None or not contract.file_path or not contract.sha256:
            return [Outgoing(chat, NO_SIGNATURE)]
        if not _lead_open(lead) or not (lead.email or "").strip():
            return [Outgoing(chat, LEAD_BLOCKED)]
        with ctx.files.open(contract.file_path) as handle:
            document = handle.read()
        if _sha256_bytes(document) != contract.sha256:  # VCRM-C12
            _audit(conn, actor, AuditAction.SIGNATURE_EVENT, lead.id, AuditOutcome.DENIED, now)
            return [Outgoing(chat, HASH_CHANGED)]
        idem = make_key("signature_send", contract.id)
        if not claim(conn, idem, now):
            return [Outgoing(chat, CLOSED)]
        crepo.update_contract(
            conn, contract.id, status=ContractStatus.APPROVED_FOR_SIGNATURE, approved_by=actor.id
        )
        request = SignRequest(
            contract_id=contract.id,
            document_name=contract_filename(lead.id, contract.file_path),
            document=document,
            signer_email=(lead.email or "").strip(),
            signer_name=(lead.legal_rep or lead.name or lead.company or "").strip(),
            idempotency_key=idem,
        )
        bot.defer(_send_job(ctx, db, port_send=port.send, request=request, chat=chat, lead=lead))
        return [Outgoing(chat, "Enviando a firma…")]

    return handler


def _send_job(
    ctx: ClosingContext,
    db: CrmDatabase,
    *,
    port_send: Callable[[SignRequest], Awaitable[str]],
    request: SignRequest,
    chat: int,
    lead: Lead,
) -> DeferredJob:
    async def job() -> list[Outgoing]:
        idem = request.idempotency_key
        try:
            external_id = await port_send(request)
        except SignatureError as exc:
            now = ctx.clock()
            logger.warning("firma: envío fallido ({})", exc.code)
            with db.tx() as tx:
                release(tx, idem)
                crepo.update_contract(
                    tx, request.contract_id, status=ContractStatus.CONTRACT_UPLOADED
                )
                repo.audit(
                    tx,
                    actor="system",
                    action=AuditAction.SIGNATURE_EVENT,
                    outcome=AuditOutcome.ERROR,
                    at=now,
                    lead_id=lead.id,
                )
            return [Outgoing(chat, SIGN_UNAVAILABLE)]
        now = ctx.clock()
        with db.tx() as tx:
            crepo.insert_signature(
                tx,
                contract_id=request.contract_id,
                provider="dryrun" if ctx.dry_run else "docuseal",
                external_id=external_id,
                status="sent",
                now=now,
            )
            crepo.update_contract(
                tx,
                request.contract_id,
                status=ContractStatus.SENT_FOR_SIGNATURE,
                expires_at=now + timedelta(days=ctx.validity_days),
            )
            repo.audit(
                tx,
                actor="system",
                action=AuditAction.SIGNATURE_EVENT,
                outcome=AuditOutcome.OK,
                at=now,
                lead_id=lead.id,
            )
        extra = (
            " [DRY_RUN] No salió a terceros; el CTO puede simularla con /firmaprueba "
            f"{short_id(lead.id)}."
            if ctx.dry_run
            else ""
        )
        return [Outgoing(chat, f"Contrato de {short_id(lead.id)} enviado a firma.{extra}")]

    return job


# --- Resultado de la firma (sondeo saliente, sin ruta pública) ----------------------------------


def _store_evidence(
    ctx: ClosingContext, lead_id: int, signed: bytes, audit: bytes
) -> tuple[str, str]:
    """Guarda copia firmada y registro de auditoría; devuelve (clave de la copia, huella)."""
    assert ctx.files is not None  # noqa: S101 - el llamador lo comprobó
    keys: list[str] = []
    for blob in (signed, audit):
        tmp = ctx.files.new_tmp_path(".pdf")
        tmp.write_bytes(blob)
        tmp.chmod(0o600)
        keys.append(ctx.files.save_atomic(lead_id, tmp))
    return keys[0], _sha256_bytes(signed)


def _complete(
    conn: sqlite3.Connection,
    ctx: ClosingContext,
    contract: Contract,
    lead: Lead,
    signature_id: int,
    signed: bytes,
    audit: bytes,
    now: datetime,
) -> None:
    key, digest = _store_evidence(ctx, lead.id, signed, audit)
    crepo.update_signature(
        conn, signature_id, status="completed", now=now, evidence_path=key, evidence_sha256=digest
    )
    crepo.update_contract(conn, contract.id, status=ContractStatus.SIGNED, signed_at=now)
    repo.audit(
        conn,
        actor="system",
        action=AuditAction.SIGNATURE_EVENT,
        outcome=AuditOutcome.OK,
        at=now,
        lead_id=lead.id,
    )
    _notify(
        conn,
        lead,
        "contract_signed",
        f"El contrato de {short_id(lead.id)} quedó firmado (huella {digest[:12]}). "
        "Cuando confirmes, márcalo como ganado desde la ficha del lead.",
        str(contract.id),
        now,
    )


def simulate_signature_command(ctx: ClosingContext) -> CommandHandler:
    """`/firmaprueba L-n` (solo CTO, solo con DRY_RUN): completa la firma con evidencia simulada."""

    def command(conn: sqlite3.Connection, actor: User, text: str, now: datetime) -> list[Outgoing]:
        if actor.role != Role.CTO or not ctx.dry_run or ctx.files is None:
            return deny(conn, actor, now)
        found = _target(conn, actor, Action.CONTRACT_APPROVE, _args(text), now)
        if isinstance(found, list):
            return found
        lead, contract = found
        signature = crepo.signature_for_contract(conn, contract.id)
        if contract.status != ContractStatus.SENT_FOR_SIGNATURE or signature is None:
            return [Outgoing(actor.telegram_id, WRONG_STATE)]
        _complete(
            conn, ctx, contract, lead, signature.id, b"%PDF-DRY_RUN firmado", b"%PDF-DRY_RUN", now
        )
        return [Outgoing(actor.telegram_id, "[DRY_RUN] Firma simulada y archivada.")]

    return command


async def contract_sweep(db: CrmDatabase, ctx: ClosingContext, now: datetime) -> None:
    """Vence contratos sin firmar y consulta al proveedor el estado de los enviados."""
    with db.tx() as tx:
        for contract in crepo.expired_contracts(tx, now):
            package = crepo.get_package(tx, contract.package_id)
            lead = None if package is None else repo.get_lead(tx, package.lead_id)
            crepo.update_contract(tx, contract.id, status=ContractStatus.EXPIRED)
            if lead is not None:
                _notify(
                    tx,
                    lead,
                    "contract_expired",
                    f"El contrato de {short_id(lead.id)} venció sin firma. "
                    "No se reenvía sin un nuevo ✅.",
                    str(contract.id),
                    now,
                )
        last = repo.get_meta(tx, POLL_META)
        due = last is None or now - from_iso(last) >= POLL_EVERY
        pending = crepo.contracts_with_status(tx, ContractStatus.SENT_FOR_SIGNATURE) if due else []
        if due:
            repo.set_meta(tx, POLL_META, to_iso(now))
        snapshot = []
        for contract in pending:
            signature = crepo.signature_for_contract(tx, contract.id)
            package = crepo.get_package(tx, contract.package_id)
            lead = None if package is None else repo.get_lead(tx, package.lead_id)
            if signature is not None and signature.external_id and lead is not None:
                snapshot.append((contract, signature, lead))
    port = ctx.signature
    if port is None:
        return
    for contract, signature, lead in snapshot:
        try:
            status = await port.status(signature.external_id or "")
        except SignatureError as exc:
            logger.warning("firma: consulta fallida ({})", exc.code)
            continue
        if status.state == "pending":
            continue
        with db.tx() as tx:
            if status.state == "completed" and status.signed_document is not None:
                _complete(
                    tx,
                    ctx,
                    contract,
                    lead,
                    signature.id,
                    status.signed_document,
                    status.audit_document or b"",
                    now,
                )
            else:
                new_status = (
                    ContractStatus.DECLINED
                    if status.state == "declined"
                    else ContractStatus.EXPIRED
                )
                crepo.update_signature(tx, signature.id, status=status.state, now=now)
                crepo.update_contract(tx, contract.id, status=new_status)
                _notify(
                    tx,
                    lead,
                    f"contract_{status.state}",
                    f"El cliente no completó la firma de {short_id(lead.id)} ({status.state}).",
                    str(contract.id),
                    now,
                )


def register_contract(bot: CrmBot, db: CrmDatabase, ctx: ClosingContext) -> None:
    bot.register_command("subircontrato", as_lawyer(ctx, upload_command))
    bot.register_file_pending(CONTRACT_FILE_KIND, as_lawyer_file(ctx, file_handler(ctx, bot, db)))
    bot.register_command("devolver", as_lawyer(ctx, return_command))
    bot.register_command("formaespecial", as_lawyer(ctx, special_form_command))
    bot.register_command("firma", sign_command(ctx))
    bot.register_callback(SIGN_OK, send_sign_callback(ctx, bot, db))
    bot.register_callback(SIGN_NO, cancel_sign_callback)
    bot.register_command("firmaprueba", simulate_signature_command(ctx))
