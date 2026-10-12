"""VCRM-171: migración de valores de dominio v1 → v2 (español → inglés), plan-f2 §2."""

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from loguru import logger

from crm_support import (
    V1_LEAD_ROWS,
    FakeClock,
    FakeEmailSender,
    FakeRunner,
    FakeTelegram,
    build_v1_database,
    make_settings,
)
from jerico.crm import app as app_mod
from jerico.crm import leads, migrate, repo
from jerico.crm.app import CrmApp
from jerico.crm.backup import _snapshot
from jerico.crm.migrate import (
    MigrationError,
    current_version,
    migrate_if_needed,
    migrate_v1_to_v2,
)
from jerico.crm.parsing import parse_callback

STATE_MAP = {
    "nuevo": "new",
    "contactado": "contacted",
    "aceptado": "accepted",
    "rechazado": "rejected",
    "en_nutricion": "nurturing",
    "pausado": "paused",
    "reactivado": "reactivated",
    "ganado": "won",
    "perdido": "lost",
    "baja": "opted_out",
}
AUTH_MAP = {"sin_autorizacion": "unauthorized", "autorizada": "authorized", "revocada": "revoked"}
OUTBOX_MAP = {"pendiente": "pending", "entregada": "delivered", "fallida": "failed"}
REQ_TYPE_MAP = {"consulta": "inquiry", "reclamo": "claim"}
REQ_STATUS_MAP = {"abierta": "open", "vencida": "overdue", "atendida": "attended"}
CONFIRMATION_MAP = {"pendiente": "pending", "confirmada": "confirmed", "cancelada": "cancelled"}


def _query(path: Path, sql: str) -> list[tuple]:
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        return [tuple(r) for r in conn.execute(sql).fetchall()]
    finally:
        conn.close()


def _version(path: Path) -> str:
    return str(_query(path, "SELECT value FROM crm_meta WHERE key = 'schema_version'")[0][0])


def _counts(path: Path) -> dict[str, int]:
    names = [
        r[0]
        for r in _query(
            path, "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'crm_%'"
        )
    ]
    return {n: _query(path, f"SELECT COUNT(*) FROM {n}")[0][0] for n in names}  # noqa: S608


def _dump(path: Path) -> dict[str, list[tuple]]:
    return {n: _query(path, f"SELECT * FROM {n} ORDER BY 1") for n in sorted(_counts(path))}  # noqa: S608


def _v1_db(tmp_path: Path) -> Path:
    path = tmp_path / "crm.db"
    build_v1_database(path)
    return path


def test_vcrm171_migracion_conserva_datos(tmp_path: Path) -> None:
    path = _v1_db(tmp_path)
    before = _counts(path)
    migrate_v1_to_v2(path)

    after = _counts(path)
    assert all(after[table] == count for table, count in before.items())  # F2 solo añade tablas
    assert _version(path) == "2"
    assert dict(_query(path, "SELECT id, state FROM crm_leads")) == {
        i: STATE_MAP[state] for i, state, _ in V1_LEAD_ROWS
    }
    assert dict(_query(path, "SELECT id, auth_status FROM crm_leads")) == {
        i: AUTH_MAP[auth] for i, _, auth in V1_LEAD_ROWS
    }
    # Datos no mapeados intactos (códigos de motivo, nombre, medio).
    assert _query(path, "SELECT reject_reason FROM crm_leads WHERE id = 4") == [("precio",)]
    assert _query(path, "SELECT name FROM crm_leads WHERE id = 1") == [("Cliente 1",)]
    assert sorted(r[0] for r in _query(path, "SELECT medium FROM crm_consents")) == [
        "email",
        "telegram",
    ]
    # Eventos de estado se migran; los de campo (texto coincidente) NO.
    assert {
        r[0] for r in _query(path, "SELECT new_value FROM crm_lead_events WHERE kind = 'state'")
    } == set(STATE_MAP.values())
    assert {
        r[0] for r in _query(path, "SELECT old_value FROM crm_lead_events WHERE kind = 'state'")
    } == {"new"}
    assert _query(
        path, "SELECT old_value, new_value FROM crm_lead_events WHERE kind = 'field'"
    ) == [("contactado", "aceptado")]
    assert sorted(r[0] for r in _query(path, "SELECT status FROM crm_consents")) == [
        "authorized",
        "revoked",
    ]
    assert sorted(r[0] for r in _query(path, "SELECT status FROM crm_outbox")) == sorted(
        OUTBOX_MAP.values()
    )
    assert sorted(_query(path, "SELECT type, status FROM crm_titular_requests")) == sorted(
        [("inquiry", "open"), ("claim", "overdue"), ("inquiry", "attended")]
    )
    assert sorted(r[0] for r in _query(path, "SELECT status FROM crm_confirmations")) == sorted(
        CONFIRMATION_MAP.values()
    )
    assert _query(path, "PRAGMA foreign_key_check") == []
    # Los índices de las tablas reconstruidas se recrean con las mismas columnas que en v1.
    indexes = {
        name: [r[2] for r in _query(path, f"PRAGMA index_info({name})")]  # noqa: S608
        for (name,) in _query(
            path, "SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'ix_%'"
        )
    }
    assert indexes["ix_leads_phone"] == ["phone_e164"]
    assert indexes["ix_leads_email"] == ["email"]
    assert indexes["ix_leads_assigned"] == ["assigned_user_id", "last_interaction_at"]
    assert indexes["ix_outbox_due"] == ["status", "next_attempt_at"]

    # CHECK v2: el valor antiguo se rechaza, el nuevo y `unclassified` (VCRM-153) se aceptan.
    conn = sqlite3.connect(path)
    try:
        insert_outbox = (
            "INSERT INTO crm_outbox (idempotency_key, kind, critical, channel, recipient_user_id, "
            "status, created_at) VALUES (?, 'x', 0, 'email', 1, ?, 't')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert_outbox, ("old", "pendiente"))
        conn.execute(insert_outbox, ("new", "pending"))
        conn.execute(
            "INSERT INTO crm_titular_requests (lead_id, type, medium, received_on, due_on, status, "
            "registered_by, registered_at) "
            "VALUES (2, 'unclassified', 'email', 'a', 'b', 'open', 1, 't')"
        )
    finally:
        conn.close()


def test_vcrm171_migracion_valor_desconocido_aborta(tmp_path: Path) -> None:
    path = _v1_db(tmp_path)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE crm_leads SET state = 'zombi' WHERE id = 3")
    conn.commit()
    conn.close()
    original = _dump(path)

    with pytest.raises(MigrationError) as err:
        migrate_v1_to_v2(path)

    assert "zombi" in str(err.value)
    assert "Cliente" not in str(err.value)  # sin datos personales
    assert _version(path) == "1"
    assert _dump(path) == original


def test_vcrm171_migracion_idempotente(tmp_path: Path) -> None:
    path = _v1_db(tmp_path)
    migrate_v1_to_v2(path)
    bak = path.with_name(path.name + ".pre-v2.bak")
    migrated = _dump(path)
    bak_hash = hashlib.sha256(bak.read_bytes()).hexdigest()

    migrate_v1_to_v2(path)  # con schema_version = 2 no hace nada

    assert _dump(path) == migrated
    assert hashlib.sha256(bak.read_bytes()).hexdigest() == bak_hash
    assert _version(path) == "2"


def test_vcrm171_migracion_copia_previa(tmp_path: Path) -> None:
    path = _v1_db(tmp_path)
    original = _dump(path)
    migrate_v1_to_v2(path)

    bak = path.with_name(path.name + ".pre-v2.bak")
    assert bak.exists()
    assert _query(bak, "PRAGMA integrity_check") == [("ok",)]
    assert _version(bak) == "1"
    assert _dump(bak) == original  # la copia conserva los valores v1


def test_vcrm171_migracion_transaccion_unica_rollback(tmp_path: Path) -> None:
    path = _v1_db(tmp_path)
    conn = sqlite3.connect(path)
    # Falla a mitad de la migración, después de actualizar `crm_leads`.
    conn.execute(
        "CREATE TRIGGER boom BEFORE UPDATE ON crm_consents BEGIN SELECT RAISE(ABORT, 'boom'); END"
    )
    conn.commit()
    conn.close()
    original = _dump(path)
    tables = sorted(_counts(path))

    with pytest.raises(MigrationError):
        migrate_v1_to_v2(path)

    assert _version(path) == "1"
    assert _dump(path) == original
    assert sorted(_counts(path)) == tables  # sin tablas F2 ni temporales a medias
    assert (
        "'pendiente'"
        in _query(path, "SELECT sql FROM sqlite_master WHERE name = 'crm_outbox'")[0][0]
    )


def test_vcrm171_callbacks_v1_emitidos_siguen_vigentes() -> None:
    """Los botones de F1 ya enviados llevan operaciones y códigos, no valores de enum."""
    sample = {
        "v1:abrir:7": ("abrir", ("7",)),
        "v1:conf:12:si": ("conf", ("12", "si")),
        "v1:conf:12:no": ("conf", ("12", "no")),
        "v1:estado:contacto:7": ("estado", ("contacto", "7")),
        "v1:estado:aceptar:7": ("estado", ("aceptar", "7")),
        "v1:estado:rechazo:7": ("estado", ("rechazo", "7")),
        "v1:estado:ganado:7": ("estado", ("ganado", "7")),
        "v1:estado:perdido:7": ("estado", ("perdido", "7")),
        "v1:motivo:7:precio": ("motivo", ("7", "precio")),
        "v1:rmotivo:7:otro": ("rmotivo", ("7", "otro")),
        "v1:lista:2": ("lista", ("2",)),
        "v1:atendida:5": ("atendida", ("5",)),
        "v1:reasignar:7:3": ("reasignar", ("7", "3")),
        "v1:retractar:7": ("retractar", ("7",)),
        "v1:baja_leads:3": ("baja_leads", ("3",)),
        "v1:cancelar:9": ("cancelar", ("9",)),
    }
    for data, (action, args) in sample.items():
        parsed = parse_callback(data)
        assert parsed is not None, data
        assert (parsed.action, parsed.args) == (action, args)
    # Guarda contra un renombrado mecánico: operaciones y motivos NO cambian (plan-f2 §2).
    assert set(leads.STATE_OPS) == {"contacto", "aceptar", "rechazo", "ganado", "perdido"}
    assert set(leads.REJECT_REASONS) == {"precio", "momento", "proveedor", "no_interesado", "otro"}


def test_vcrm171_migracion_respaldo_f1_restaurado(tmp_path: Path) -> None:
    """R-M3: una base v1 restaurada desde un respaldo de F1 se migra igual."""
    source = _v1_db(tmp_path)
    restored_dir = tmp_path / "restored"
    restored_dir.mkdir()
    restored = restored_dir / "crm.db"
    _snapshot(source, restored)  # misma instantánea que el respaldo nocturno (VCRM-097)
    assert _version(restored) == "1"

    migrate_v1_to_v2(restored)

    assert _version(restored) == "2"
    assert dict(_query(restored, "SELECT id, state FROM crm_leads")) == {
        i: STATE_MAP[state] for i, state, _ in V1_LEAD_ROWS
    }


def test_vcrm171_migracion_rechaza_bases_que_no_son_v1(tmp_path: Path) -> None:
    vacia = tmp_path / "vacia.db"
    sqlite3.connect(vacia).close()
    with pytest.raises(MigrationError, match="crm_meta"):
        migrate_v1_to_v2(vacia)

    sin_version = tmp_path / "sin_version.db"
    conn = sqlite3.connect(sin_version)
    conn.execute("CREATE TABLE crm_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.commit()
    conn.close()
    with pytest.raises(MigrationError, match="schema_version"):
        migrate_v1_to_v2(sin_version)

    (tmp_path / "x").mkdir()
    futura = _v1_db(tmp_path / "x")
    conn = sqlite3.connect(futura)
    conn.execute("UPDATE crm_meta SET value = '3' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()
    with pytest.raises(MigrationError, match="no migrable"):
        migrate_v1_to_v2(futura)
    assert _version(futura) == "3"


def test_vcrm171_copia_previa_corrupta_aborta_sin_tocar_la_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _v1_db(tmp_path)
    original = _dump(path)
    monkeypatch.setattr(migrate, "_integrity_ok", lambda _path: False)

    with pytest.raises(MigrationError, match="integrity_check"):
        migrate_v1_to_v2(path)

    assert _dump(path) == original
    assert _version(path) == "1"
    assert not path.with_name(path.name + ".pre-v2.bak").exists()


def test_vcrm171_clave_foranea_huerfana_deshace_la_migracion(tmp_path: Path) -> None:
    path = _v1_db(tmp_path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(
        "INSERT INTO crm_lead_events (lead_id, kind, actor_user_id, at) "
        "VALUES (999, 'field', 1, 't')"
    )
    conn.commit()
    conn.close()
    original = _dump(path)

    with pytest.raises(MigrationError, match="foreign_key_check"):
        migrate_v1_to_v2(path)

    assert _version(path) == "1"
    assert _dump(path) == original


def test_vcrm171_error_no_sqlite_tambien_deshace_y_se_propaga(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _v1_db(tmp_path)
    original = _dump(path)

    def boom(conn: sqlite3.Connection) -> None:
        conn.execute("UPDATE crm_leads SET state = 'new'")  # cambio a medias
        raise ValueError("interrupción")

    monkeypatch.setattr(migrate, "_apply", boom)
    with pytest.raises(ValueError, match="interrupción"):
        migrate_v1_to_v2(path)

    assert _dump(path) == original
    assert _version(path) == "1"


def _crm_settings(data_dir: Path):  # noqa: ANN202 - helper de prueba
    return make_settings(
        telegram_bot_token="123:token-ficticio",
        fingerprint_key="clave-ficticia",
        seed_cto_telegram_id="1000",
        seed_cto_email="cto@example.invalid",
        data_dir=data_dir,
    )


def test_vcrm171_main_migra_la_base_v1_antes_de_arrancar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "crm-data"
    data_dir.mkdir()
    build_v1_database(data_dir / "crm.db")
    started: list[object] = []

    async def fake_service(settings: object) -> None:
        # Al llegar aquí la base ya debe estar en v2.
        started.append(_version(data_dir / "crm.db"))

    monkeypatch.setattr(app_mod, "run_service", fake_service)
    app_mod.main(_crm_settings(data_dir))

    assert started == ["2"]


def test_vcrm171_main_sale_con_codigo_3_si_falla_la_migracion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "crm-data"
    data_dir.mkdir()
    path = data_dir / "crm.db"
    build_v1_database(path)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE crm_leads SET state = 'zombi' WHERE id = 3")
    conn.commit()
    conn.close()
    called: list[object] = []

    async def fake_service(settings: object) -> None:
        called.append(settings)

    monkeypatch.setattr(app_mod, "run_service", fake_service)
    lines: list[str] = []
    sink = logger.add(lines.append, level="DEBUG")
    try:
        with pytest.raises(SystemExit) as exc:
            app_mod.main(_crm_settings(data_dir))
    finally:
        logger.remove(sink)

    assert exc.value.code == app_mod.EXIT_MIGRATION == 3
    assert called == []
    assert _version(path) == "1"  # la base queda en v1 intacta
    log = "".join(lines)
    assert "zombi" in log and "Cliente" not in log and "123:token-ficticio" not in log


def test_vcrm171_la_app_abre_una_base_v1_y_opera(tmp_path: Path) -> None:
    """`CrmApp` por sí sola (sin pasar por `main`) también migra y puede consultar los leads."""

    data_dir = tmp_path / "crm-data"
    data_dir.mkdir()
    build_v1_database(data_dir / "crm.db")
    app = CrmApp(
        _crm_settings(data_dir),
        telegram=FakeTelegram(),
        email=FakeEmailSender(),
        runner=FakeRunner(),
        clock=FakeClock(datetime(2026, 10, 12, 15, 0, tzinfo=UTC)).now,
    )
    try:
        with app.db.read() as conn:
            assert repo.get_meta(conn, "schema_version") == "2"
            assert (
                conn.execute("SELECT state FROM crm_leads WHERE id = 3").fetchone()[0] == "accepted"
            )
    finally:
        app.db.close()


def test_vcrm171_version_actual_y_migrar_solo_si_hace_falta(tmp_path: Path) -> None:
    assert current_version(tmp_path / "no-existe.db") is None
    assert migrate_if_needed(tmp_path / "no-existe.db") is False

    vacia = tmp_path / "vacia.db"
    vacia.write_bytes(b"")
    assert current_version(vacia) is None  # archivo de 0 bytes: una base nueva

    ajena = tmp_path / "ajena.db"
    conn = sqlite3.connect(ajena)
    conn.execute("CREATE TABLE otra (x INTEGER)")
    conn.commit()
    conn.close()
    assert current_version(ajena) is None
    assert migrate_if_needed(ajena) is False

    (tmp_path / "v1").mkdir()
    v1 = _v1_db(tmp_path / "v1")
    assert current_version(v1) == "1"
    assert migrate_if_needed(v1) is True
    assert current_version(v1) == "2"
    assert migrate_if_needed(v1) is False  # ya migrada
