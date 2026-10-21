"""System health checks: disk, backup age, daily integrity."""
import os
from collections import namedtuple

from vardiya import health as health_module
from vardiya.backup import create_backup
from vardiya.health import BACKUP_MAX_AGE, INTEGRITY_EVERY, Health

Usage = namedtuple("Usage", "total used free")


def test_healthy_system_has_no_problems(system):
    s, *_ = system
    create_backup(s.db, s.db.path.parent / "backups" / "elle.sqlite3")
    assert s.health.problems() == []


def test_missing_old_backup_low_disk_and_integrity(system, monkeypatch):
    s, *_ = system
    now = [1_800_000_000.0]
    h = Health(s.db.path, now=lambda: now[0])
    assert h.problems() == ["Henüz hiç yedek yok."]
    backup = create_backup(s.db, s.db.path.parent / "backups" / "elle.sqlite3")
    os.utime(backup, (now[0] - BACKUP_MAX_AGE - 86400,) * 2)
    assert h.problems() == ["Son yedek 4 gün önce alındı; otomatik yedek çalışmıyor olabilir."]
    os.utime(backup, (now[0],) * 2)
    monkeypatch.setattr(health_module.shutil, "disk_usage", lambda _: Usage(10, 10, 100 * 1_048_576))
    assert h.problems() == ["Diskte yalnızca 100 MB boş yer kaldı; yedekler alınamayabilir."]
    monkeypatch.setattr(health_module.shutil, "disk_usage", lambda _: Usage(10, 0, 10**12))
    assert not h.integrity_due()
    now[0] += INTEGRITY_EVERY
    assert h.integrity_due()
    monkeypatch.setattr(health_module, "inspect_database", lambda _: ["İşlem geçmişinin doğrulama zinciri bozuk."])
    assert h.check_integrity() and not h.integrity_due()
    assert h.problems()[0].startswith("Bütünlük denetimi sorun buldu: İşlem geçmişinin")
