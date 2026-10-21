"""Daily automatic backup and integrity check, off the kiosk's UI thread.

The worker opens its own read-only SQLite connection (connections are thread-bound).
Results are collected by `poll()` on the UI thread, so no Qt signals cross threads.
"""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .backup import automatic_backup
from .security import AppError
from .storage import inspect_database


class ReadOnlySource:
    """Just enough of Database for backup.create_backup: `path` and a read-only `conn`."""
    def __init__(self, path: Path):
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)

    def close(self):
        self.conn.close()


def maintenance_job(db_path, zone, verified, check_integrity):
    """Returns {"backup_failed": bool, "integrity": errors list or None (not checked)}."""
    result = {"backup_failed": False, "integrity": None}
    source = None
    try:
        source = ReadOnlySource(db_path)
        automatic_backup(source, zone, verified)
    except (AppError, sqlite3.Error, OSError):
        result["backup_failed"] = True
    finally:
        if source:
            source.close()
    if check_integrity:
        result["integrity"] = inspect_database(db_path)
    return result


class Maintenance:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.verified = set()           # backups already verified in this process
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vardiya-bakim")
        self._future = None

    @property
    def running(self):
        return self._future is not None and not self._future.done()

    def start(self, zone, check_integrity):
        if self._future is None:
            self._future = self._pool.submit(maintenance_job, self.db_path, zone, self.verified, check_integrity)

    def poll(self):
        """The finished job's result once (None while running or idle)."""
        if self._future is None or not self._future.done():
            return None
        future, self._future = self._future, None
        try:
            return future.result()
        except Exception:               # never let a maintenance bug stop the kiosk
            return {"backup_failed": True, "integrity": None}

    def wait(self, timeout=60):
        if self._future is not None:
            self._future.exception(timeout)

    def shutdown(self):
        self._pool.shutdown(wait=True)
