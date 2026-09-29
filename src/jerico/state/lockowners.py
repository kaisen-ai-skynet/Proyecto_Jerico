import os
import pwd
from dataclasses import dataclass
from pathlib import Path

PROC_ROOT = Path("/proc")


@dataclass(frozen=True)
class LockHolder:
    pid: int
    username: str
    command: str
    descriptor: str


def scan_database_lockowners(db_path: Path) -> list[LockHolder]:
    """Find processes with an open fd for a SQLite database, WAL, or SHM file."""
    database = db_path.resolve()
    database_files = {
        database,
        Path(f"{database}-wal"),
        Path(f"{database}-shm"),
    }
    holders: dict[int, LockHolder] = {}
    try:
        processes = list(os.scandir(PROC_ROOT))
    except OSError:
        return []

    for process in processes:
        if not process.name.isdigit():
            continue
        pid = int(process.name)
        process_path = PROC_ROOT / process.name
        fd_path = process_path / "fd"
        try:
            descriptors = list(os.scandir(fd_path))
        except OSError:
            continue
        for descriptor in descriptors:
            try:
                target = os.readlink(descriptor.path).removesuffix(" (deleted)")
                resolved = Path(target).resolve()
            except (OSError, RuntimeError):
                continue
            if resolved not in database_files:
                continue
            holders[pid] = LockHolder(
                pid=pid,
                username=_username(process_path),
                command=_command(process_path),
                descriptor=descriptor.path,
            )
            break
    return sorted(holders.values(), key=lambda holder: holder.pid)


def _username(process_path: Path) -> str:
    try:
        status = (process_path / "status").read_text(encoding="utf-8")
        uid_line = next(line for line in status.splitlines() if line.startswith("Uid:"))
        uid = int(uid_line.split()[1])
        try:
            return pwd.getpwuid(uid).pw_name
        except KeyError:
            return str(uid)
    except (OSError, StopIteration, ValueError):
        return "unknown"


def _command(process_path: Path) -> str:
    try:
        raw = (process_path / "cmdline").read_bytes()
    except OSError:
        return "unknown"
    return " ".join(part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part)
