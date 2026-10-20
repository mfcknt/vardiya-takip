"""Create a small, valid sample database for packaging smoke tests.

Usage: python scripts/make_sample_db.py <data-dir>
Never point this at a real data folder; it refuses non-empty targets.
"""
import sys
import uuid
from pathlib import Path

from vardiya.backup import create_backup
from vardiya.service import Service
from vardiya.storage import Database


class StepClock:
    def __init__(self, now=1792486800):
        self.now, self.mono = now, 100.0

    def wall(self):
        return self.now

    def monotonic(self):
        return self.mono

    def advance(self, seconds):
        self.now += seconds
        self.mono += seconds


def main(directory):
    directory = Path(directory)
    if directory.exists() and any(directory.iterdir()):
        print("Hedef klasör boş değil; gerçek veri korunmak için durduruldu.", file=sys.stderr)
        return 2
    clock = StepClock()
    db = Database(directory / "vardiya.sqlite3")
    try:
        service = Service(db, clock)
        service.setup("Ornek!Yonetici2026")
        token = service.login_admin("Ornek!Yonetici2026")
        eid = service.add_employee(token, "Örnek Personel", "482957", 15000)
        sid = service.attendance(eid, "482957", "start", None, str(uuid.uuid4()))
        clock.advance(3600)
        service.attendance(eid, "482957", "end", sid, str(uuid.uuid4()))
        token = service.login_admin("Ornek!Yonetici2026")
        service.add_payment(token, eid, clock.wall(), 5000, "Avans", "Örnek avans kaydı", str(uuid.uuid4()))
        create_backup(db, directory / "backups" / "ornek.sqlite3")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
