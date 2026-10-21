"""Qt-free system health: things nobody looks at for months unless the program says so.

Shown on the admin "bugün" page and counted in the kiosk's "Yönetici için N not var."
Uses real time (file ages), not the service clock, which may be under review.
"""
import shutil
import time
from pathlib import Path

from .storage import inspect_database

DISK_MIN_BYTES = 500 * 1024 * 1024
BACKUP_MAX_AGE = 3 * 86400
INTEGRITY_EVERY = 86400


class Health:
    def __init__(self, db_path: Path, now=time.time):
        self.db_path = Path(db_path)
        self.now = now
        # Database() verified the file when it was opened.
        self.integrity_at = now()
        self.integrity_errors = []

    def integrity_due(self):
        return self.now() - self.integrity_at >= INTEGRITY_EVERY

    def record_integrity(self, errors):
        self.integrity_at, self.integrity_errors = self.now(), list(errors)

    def check_integrity(self):
        self.record_integrity(inspect_database(self.db_path))
        return self.integrity_errors

    def problems(self):
        """Plain Turkish sentences, most serious first; empty when all is well."""
        found = []
        if self.integrity_errors:
            found.append("Bütünlük denetimi sorun buldu: " + "; ".join(self.integrity_errors[:3]) +
                         " Ayarlar → Bütünlüğü denetle; gerekirse yedekten kurtarın.")
        try:
            free = shutil.disk_usage(self.db_path.parent).free
        except OSError:
            free = None
        if free is not None and free < DISK_MIN_BYTES:
            found.append(f"Diskte yalnızca {free // 1_048_576} MB boş yer kaldı; yedekler alınamayabilir.")
        backups = [p for p in (self.db_path.parent / "backups").glob("*.sqlite3")]
        newest = max((p.stat().st_mtime for p in backups), default=None)
        if newest is None:
            found.append("Henüz hiç yedek yok.")
        elif self.now() - newest > BACKUP_MAX_AGE:
            found.append(f"Son yedek {int((self.now() - newest) // 86400)} gün önce alındı; "
                         "otomatik yedek çalışmıyor olabilir.")
        return found
