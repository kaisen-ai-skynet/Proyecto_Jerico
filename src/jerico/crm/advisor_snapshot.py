"""Corrida diaria de la instantánea del CRM-consejero (spec 007, VJC-003 a 010, VJC-021 a 024)."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from jerico.crm.advisor_queries import load_context
from jerico.crm.advisor_state import (
    InvalidVector,
    build_vector,
    is_eligible,
    lead_ref,
    validate_vector,
)
from jerico.crm.db import CrmDatabase
from jerico.shadowlog.jsonl import BOGOTA_TZ, DailyJsonlWriter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SnapshotReport:
    """Informe consolidado de la corrida de instantánea sin exponer datos de leads."""

    capture_day: str
    eligible_count: int
    written_count: int
    omitted_count: int
    purged_files: int
    withdrawals_count: int
    success: bool


def run_snapshot(
    db: CrmDatabase,
    writer: DailyJsonlWriter,
    *,
    key: str,
    clock: Callable[[], float] | None = None,
    retention_days: int = 90,
    withdrawals_retention_days: int = 30,
    withdrawals_writer: DailyJsonlWriter | None = None,
) -> SnapshotReport:
    """Ejecuta la captura de instantáneas con purga de retención y reconciliación de retiros."""
    clock_fn = clock if clock is not None else time.time
    now_epoch = clock_fn()
    now_dt = datetime.fromtimestamp(now_epoch, tz=BOGOTA_TZ)
    capture_day = now_dt.strftime("%Y-%m-%d")

    w_writer = (
        withdrawals_writer
        if withdrawals_writer is not None
        else DailyJsonlWriter(
            writer.dir_path,
            prefix="retiros-",
            tz=BOGOTA_TZ,
            clock=clock_fn,
            retention_days=withdrawals_retention_days,
        )
    )

    # 1. Purgar archivos antiguos de instantáneas y retiros (VJC-021)
    purged_snapshots = writer.purge(retention_days)
    purged_withdrawals = w_writer.purge(withdrawals_retention_days)
    total_purged = purged_snapshots + purged_withdrawals

    # 2. Cargar contexto de la base de datos dentro de una sola sección de lectura (VJC-005)
    try:
        with db.read() as conn:
            context = load_context(conn, now_dt)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Fallo al leer datos para instantánea: %s", exc)
        return SnapshotReport(
            capture_day=capture_day,
            eligible_count=0,
            written_count=0,
            omitted_count=0,
            purged_files=total_purged,
            withdrawals_count=0,
            success=False,
        )

    # 3. Reconciliación previa: supresión, bajas y retiros (VJC-022, VJC-024)
    eligible_leads = [lead for lead in context if is_eligible(lead)]
    eligible_refs = {lead_ref(int(lead["id"]), key) for lead in eligible_leads}

    removed_records = writer.rewrite_without(lambda r: r.get("lead_ref") not in eligible_refs)
    withdrawals_seen: set[str] = set()
    withdrawals_count = 0

    for rec in removed_records:
        r_ref = rec.get("lead_ref")
        if r_ref and r_ref not in withdrawals_seen:
            withdrawals_seen.add(r_ref)
            withdrawals_count += 1
            w_writer.append({"lead_ref": r_ref, "withdrawal_day": capture_day})

    # 4. Escritura de leads elegibles si existen (VJC-003, VJC-004, VJC-010)
    eligible_count = len(eligible_leads)
    if eligible_count == 0:
        return SnapshotReport(
            capture_day=capture_day,
            eligible_count=0,
            written_count=0,
            omitted_count=0,
            purged_files=total_purged,
            withdrawals_count=withdrawals_count,
            success=True,
        )

    existing_today = {r.get("lead_ref") for r in writer.read_day(capture_day)}
    written_count = 0
    omitted_count = 0
    weekday = now_dt.weekday()

    for lead in eligible_leads:
        ref = lead_ref(int(lead["id"]), key)
        if ref in existing_today:
            continue
        try:
            vec = build_vector(lead, key=key, capture_day=capture_day, weekday=weekday)
            validate_vector(vec)
            writer.append(vec, date_str=capture_day)
            written_count += 1
            existing_today.add(ref)
        except (InvalidVector, Exception) as exc:  # noqa: BLE001
            omitted_count += 1
            logger.warning("Lead omitido por vector inválido (VJC-007): %s", exc)

    return SnapshotReport(
        capture_day=capture_day,
        eligible_count=eligible_count,
        written_count=written_count,
        omitted_count=omitted_count,
        purged_files=total_purged,
        withdrawals_count=withdrawals_count,
        success=True,
    )
