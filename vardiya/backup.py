import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .security import AppError, verify_secret
from .storage import fsync_file, inspect_database

AUTO_PREFIX, CLOSE_PREFIX = "otomatik-", "kapanis-"
KEEP_DAILY, KEEP_CLOSING = 30, 20


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
        fsync_file(staging)
        os.replace(staging, destination)
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        destination.with_suffix(destination.suffix + ".sha256").write_text(
            digest + "  " + destination.name + "\n", encoding="utf-8"
        )
        return destination
    finally:
        if os.path.exists(staging):
            os.unlink(staging)


def backup_dir(db) -> Path:
    return db.path.parent / "backups"


def automatic_backup(db, zone, verified=None):
    """Take today's first snapshot once; verify an existing one once.

    `verified` is a caller-owned set of paths already checked in this process,
    so the 15-second heartbeat does not re-inspect the whole file every tick.
    """
    day = datetime.now(zone).strftime("%Y-%m-%d")
    path = backup_dir(db) / f"{AUTO_PREFIX}{day}.sqlite3"
    if verified is not None and path in verified:
        return path
    if not path.exists():
        create_backup(db, path)
        prune_backups(backup_dir(db))
    elif inspect_database(path):
        raise AppError("Bugünkü otomatik yedek doğrulanamadı; yeni bir elle yedek alın.")
    if verified is not None:
        verified.add(path)
    return path


def closing_backup(db):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = create_backup(db, backup_dir(db) / f"{CLOSE_PREFIX}{stamp}.sqlite3")
    prune_backups(backup_dir(db))
    return path


def prune_backups(directory: Path, keep_daily=KEEP_DAILY, keep_closing=KEEP_CLOSING):
    """Delete only app-named automatic/closing backups beyond the retention.

    Kept: newest `keep_daily` daily snapshots, the first daily snapshot of every
    month, and the newest `keep_closing` closing snapshots. Manual backups and
    any other files are never touched. Returns the removed paths.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []
    daily = sorted(p for p in directory.glob(AUTO_PREFIX + "????-??-??.sqlite3"))
    closing = sorted(p for p in directory.glob(CLOSE_PREFIX + "*.sqlite3"))
    # Note: list[-0:] is the whole list, so zero counts are handled explicitly.
    keep = set(daily[-keep_daily:] if keep_daily else []) | set(
        closing[-keep_closing:] if keep_closing else [])
    first_of_month = {}
    for p in daily:
        first_of_month.setdefault(p.name[len(AUTO_PREFIX):len(AUTO_PREFIX) + 7], p)
    keep |= set(first_of_month.values())
    removed = []
    for p in daily + closing:
        if p in keep:
            continue
        for target in (p, p.with_suffix(p.suffix + ".sha256")):
            try:
                target.unlink()
            except FileNotFoundError:
                pass
        removed.append(p)
    return removed


def backup_usage(db):
    """(file count, total bytes) of the application backup folder."""
    directory = backup_dir(db)
    files = [p for p in directory.glob("*.sqlite3")] if directory.is_dir() else []
    return len(files), sum(p.stat().st_size for p in files)


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
        fsync_file(temporary)
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
