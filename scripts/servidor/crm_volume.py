"""Empaqueta, restaura y verifica los datos de Jericó CRM (spec 002: SRV-01, 02, 04, 10, 11).

Solo biblioteca estándar (Python con el filtro `data` de tarfile, PEP 706). Se pasa con
`python -c` al intérprete que tenga acceso al volumen, sin copiar nada a la imagen
(stdin queda libre para el tar):

    docker exec jerico-crm python -c "$(cat crm_volume.py)" pack /app/crm-data > crm.tar
    docker run --rm -i -v jerico_crm_data:/data IMG \
        python -c "..." unpack /data < crm.tar
    python3 crm_volume.py verify crm.tar            # en la laptop, tras descifrar

pack   → tar por stdout: instantánea consistente de crm.db (API de backup de SQLite) +
         el resto del volumen, sin heartbeat ni -wal/-shm. Nunca deja copias en disco.
unpack → vacía el directorio y extrae el tar de stdin (filtro "data": sin rutas absolutas ni ..).
verify → integrity_check + tablas básicas + recuento de archivos.
"""

import shutil
import sqlite3
import sys
import tarfile
import tempfile
from pathlib import Path

DB_NAME = "crm.db"
EXCLUDED = {"heartbeat", f"{DB_NAME}-wal", f"{DB_NAME}-shm", f"{DB_NAME}-journal"}
REQUIRED_TABLES = ("crm_meta", "crm_leads")


def _fail(message: str) -> None:
    print(f"[ERROR] {message}", file=sys.stderr)
    sys.exit(1)


def _check_db(path: Path) -> dict[str, int | str]:
    """integrity_check y tablas obligatorias; devuelve el recuento por tabla obligatoria."""
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            _fail(f"integrity_check de {DB_NAME}: {result}")
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in rows}
        missing = [t for t in REQUIRED_TABLES if t not in tables]
        if missing:
            _fail(f"faltan tablas en {DB_NAME}: {', '.join(missing)}")
        counts: dict[str, int | str] = {
            t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]  # noqa: S608 (constantes)
            for t in REQUIRED_TABLES
        }
        counts["tablas"] = len(tables)
        row = conn.execute("SELECT value FROM crm_meta WHERE key = 'schema_version'").fetchone()
        counts["schema_version"] = row[0] if row else "?"
        return counts
    finally:
        conn.close()


def pack(data_dir: Path) -> None:
    source = data_dir / DB_NAME
    if not source.is_file():
        _fail(f"no existe {source}")
    work = Path(tempfile.mkdtemp(prefix="jerico-pack-"))
    try:
        snapshot = work / DB_NAME
        src = sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)
        try:
            dst = sqlite3.connect(snapshot)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        _check_db(snapshot)
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as tar:
            tar.add(snapshot, arcname=DB_NAME)
            for entry in sorted(data_dir.iterdir()):
                if entry.name == DB_NAME or entry.name in EXCLUDED:
                    continue
                tar.add(entry, arcname=entry.name)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def unpack(data_dir: Path) -> None:
    if not data_dir.is_dir():
        _fail(f"no existe el directorio {data_dir}")
    # Dentro del propio volumen (el usuario del contenedor no puede escribir en su padre).
    work = data_dir / ".jerico-unpack"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    try:
        # Primero a un directorio aparte: si el tar es inválido, los datos no se tocan.
        try:
            with tarfile.open(fileobj=sys.stdin.buffer, mode="r|") as tar:
                tar.extractall(work, filter="data")
        except (tarfile.TarError, OSError) as exc:
            _fail(f"archivo inválido, no se tocó {data_dir}: {exc}")
        if not (work / DB_NAME).is_file():
            _fail(f"el archivo no contiene {DB_NAME}; no se tocó {data_dir}")
        for entry in data_dir.iterdir():
            if entry == work:
                continue
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        for entry in work.iterdir():
            shutil.move(str(entry), data_dir / entry.name)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def verify(archive: Path) -> None:
    work = Path(tempfile.mkdtemp(prefix="jerico-verify-"))
    try:
        try:
            with tarfile.open(archive) as tar:
                tar.extractall(work, filter="data")
        except (tarfile.TarError, OSError) as exc:
            _fail(f"no es un tar válido: {exc}")
        if not (work / DB_NAME).is_file():
            _fail(f"el archivo no contiene {DB_NAME}")
        counts = _check_db(work / DB_NAME)
        files = sum(1 for p in work.rglob("*") if p.is_file())
        print("integrity_check: ok")
        print(f"schema_version: {counts.pop('schema_version')}")
        print(f"tablas: {counts.pop('tablas')}")
        for table, count in counts.items():
            print(f"{table}: {count}")
        print(f"archivos: {files}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv: list[str]) -> None:
    if not hasattr(tarfile, "data_filter"):  # PEP 706: 3.12+, y 3.8.17/3.9.17/3.10.12/3.11.4+
        _fail("este Python no tiene el filtro 'data' de tarfile (PEP 706); actualízalo")
    commands = {"pack": pack, "unpack": unpack, "verify": verify}
    if len(argv) != 2 or argv[0] not in commands:
        _fail("uso: crm_volume.py pack|unpack <directorio> | verify <archivo.tar>")
    commands[argv[0]](Path(argv[1]))


if __name__ == "__main__":
    main(sys.argv[1:])
