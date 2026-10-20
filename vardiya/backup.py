import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .security import AppError, verify_secret
from .storage import inspect_database


def create_backup(db, destination: Path):
    destination = Path(destination)
    if destination.exists() or destination.resolve() == db.path.resolve():
        raise AppError("Yedek için yeni bir dosya adı seçin.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, staging = tempfile.mkstemp(prefix=".backup-", suffix=".sqlite3", dir=destination.parent)
    os.close(fd)
    try:
        target = sqlite3.connect(staging)
        try:
            db.conn.backup(target)
        finally:
            target.close()
        errors = inspect_database(Path(staging))
        if errors:
            raise AppError("Yedek doğrulanamadı: " + "; ".join(errors))
        with open(staging, "rb") as f:
            os.fsync(f.fileno())
        os.replace(staging, destination)
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        destination.with_suffix(destination.suffix + ".sha256").write_text(
            digest + "  " + destination.name + "\n", encoding="utf-8"
        )
        return destination
    finally:
        if os.path.exists(staging):
            os.unlink(staging)


def automatic_backup(db, zone):
    day = datetime.now(zone).strftime("%Y-%m-%d")
    path = db.path.parent / "backups" / f"otomatik-{day}.sqlite3"
    if not path.exists():
        create_backup(db, path)
    elif inspect_database(path):
        raise AppError("Bugünkü otomatik yedek doğrulanamadı; yeni bir elle yedek alın.")
    return path


def restore_database(source: Path, destination: Path, password: str):
    """Caller must hold FileLock and close Database before entering.

    Verify source, authorize against healthy current DB (or backup if corrupt),
    retain raw old files, stage a verified DB, then atomically replace.
    """
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise AppError("Kaynak yedek ile hedef aynı olamaz.")
    errors = inspect_database(source)
    if errors:
        raise AppError("Yedek geçersiz: " + "; ".join(errors))
    checksum = source.with_suffix(source.suffix + ".sha256")
    if checksum.exists():
        parts = checksum.read_text(encoding="utf-8").split()
        expected = parts[0] if parts else ""
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise AppError("Yedek dosyasının SHA-256 doğrulaması başarısız.")
    authority = destination if destination.exists() and not inspect_database(destination) else source
    auth = sqlite3.connect(authority.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        row = auth.execute("SELECT secret FROM credentials WHERE subject='admin'").fetchone()
        if not row or not verify_secret(password, row[0]):
            raise AppError("Kurtarma için yönetici şifresi doğrulanamadı.")
    finally:
        auth.close()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".restore-", suffix=".sqlite3", dir=destination.parent)
    os.close(fd)
    try:
        src = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
        dst = sqlite3.connect(temporary)
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()
        if inspect_database(Path(temporary)):
            raise AppError("Hazırlanan kurtarma dosyası doğrulanamadı.")
        from .storage import Database
        staged = Database(Path(temporary))
        try:
            with staged.transaction():
                now = int(datetime.now(timezone.utc).timestamp())
                staged.audit(now, "admin", "RESTORE", "system",
                             after={"source": source.name},
                             reason="Yedekten kurtarıldı; saat ve açık kayıtları inceleyin.")
                staged.set_meta("clock_alert", "Yedekten dönüldü; saat ve açık kayıtları inceleyin.")
        finally:
            staged.close()
        with open(temporary, "rb") as f:
            os.fsync(f.fileno())
        archive = destination.parent / "recovery" / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        archive.mkdir(parents=True)
        manifest = {}
        for suffix in ("", "-journal", "-wal", "-shm"):
            old = Path(str(destination) + suffix)
            if old.exists():
                shutil.copy2(old, archive / old.name)
                manifest[old.name] = hashlib.sha256((archive / old.name).read_bytes()).hexdigest()
        (archive / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        # Old sidecars cannot accompany a restored, independent SQLite file.
        # Rename them into the already preserved recovery directory first.
        for suffix in ("-journal", "-wal", "-shm"):
            sidecar = Path(str(destination) + suffix)
            if sidecar.exists():
                os.replace(sidecar, archive / (sidecar.name + ".original"))
        os.replace(temporary, destination)
        return archive
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
