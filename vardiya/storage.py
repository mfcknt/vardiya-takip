import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .security import AppError

SCHEMA_VERSION = 2
# Upgrade steps: MIGRATIONS[n] turns a version-n database into version n+1.
# On a schema change: change SCHEMA (new databases), bump SCHEMA_VERSION and add
# the step here. Never edit a released step; tests/fixtures holds real old files.
OLDEST_SUPPORTED = 2
MIGRATIONS: dict[int, str] = {}
SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE credentials(
 subject TEXT PRIMARY KEY, secret TEXT NOT NULL,
 failures INTEGER NOT NULL DEFAULT 0, locked_until INTEGER NOT NULL DEFAULT 0);
CREATE TABLE employees(
 id INTEGER PRIMARY KEY, name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 80),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 rate_cents INTEGER NOT NULL CHECK(rate_cents BETWEEN 0 AND 100000000),
 created_at INTEGER NOT NULL);
CREATE TABLE rate_history(
 id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id),
 effective_at INTEGER NOT NULL, rate_cents INTEGER NOT NULL CHECK(rate_cents>=0));
CREATE TABLE sessions(
 id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id),
 start_at INTEGER NOT NULL, end_at INTEGER,
 rate_cents INTEGER NOT NULL CHECK(rate_cents BETWEEN 0 AND 100000000),
 voided INTEGER NOT NULL DEFAULT 0 CHECK(voided IN (0,1)),
 revision INTEGER NOT NULL DEFAULT 1,
 review TEXT NOT NULL DEFAULT '',
 CHECK(end_at IS NULL OR end_at > start_at));
CREATE UNIQUE INDEX one_open_session ON sessions(employee_id)
 WHERE end_at IS NULL AND voided=0;
CREATE INDEX session_dates ON sessions(employee_id,start_at);
CREATE TABLE payments(
 id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id),
 paid_at INTEGER NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
 kind TEXT NOT NULL CHECK(kind IN ('Ödeme','Avans')),
 note TEXT NOT NULL, voided INTEGER NOT NULL DEFAULT 0 CHECK(voided IN (0,1)));
CREATE TABLE receipts(
 request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result_id INTEGER NOT NULL);
CREATE TABLE audit(
 id INTEGER PRIMARY KEY, at INTEGER NOT NULL, actor TEXT NOT NULL,
 action TEXT NOT NULL, entity TEXT NOT NULL, before_json TEXT NOT NULL,
 after_json TEXT NOT NULL, reason TEXT NOT NULL,
 previous_hash TEXT NOT NULL, hash TEXT NOT NULL);
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit BEGIN
 SELECT RAISE(ABORT, 'audit is append-only'); END;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit BEGIN
 SELECT RAISE(ABORT, 'audit is append-only'); END;
"""


def default_data_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "VardiyaTakip"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "VardiyaTakip"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "vardiya-takip"


def fsync_file(path) -> None:
    """Flush a closed file to disk.

    Windows FlushFileBuffers needs a writable handle; fsync on a read-only
    descriptor fails there with EBADF, so always open for update.
    """
    with open(path, "r+b") as f:
        os.fsync(f.fileno())


# Sorted sweep per employee: a record overlaps an earlier one exactly when it
# starts before the latest end seen so far. O(n log n) instead of a self-join.
OVERLAP_SQL = """SELECT 1 FROM (
    SELECT start_at, MAX(COALESCE(end_at, 9223372036854775807)) OVER (
        PARTITION BY employee_id ORDER BY start_at, id
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS previous_end
    FROM sessions WHERE voided=0)
  WHERE previous_end > start_at LIMIT 1"""


def schema_version(path: Path) -> int:
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def check_upgradable(version: int) -> None:
    if version > SCHEMA_VERSION:
        raise AppError("Bu veri dosyası programın daha yeni bir sürümüyle kaydedilmiş. "
                       "Programın güncel sürümünü kurun; veri değiştirilmedi.")
    if version < OLDEST_SUPPORTED or any(v not in MIGRATIONS for v in range(version, SCHEMA_VERSION)):
        raise AppError(f"Veri şeması (sürüm {version}) bu programla güncellenemiyor; veri değiştirilmedi.")


def upgraded_copy(source: Path, target: Path) -> int:
    """Copy `source` into the empty file `target` and bring the copy to SCHEMA_VERSION.

    All steps and their audit entry commit together; `source` is never written.
    Returns the source's version. The caller verifies `target` before using it.
    """
    version = schema_version(source)
    check_upgradable(version)
    src = sqlite3.connect(Path(source).resolve().as_uri() + "?mode=ro", uri=True)
    dst = sqlite3.connect(target, isolation_level=None)
    try:
        src.backup(dst)
        if version < SCHEMA_VERSION:
            steps = "\n".join(MIGRATIONS[step] for step in range(version, SCHEMA_VERSION))
            try:
                # executescript leaves the transaction it began open for the audit entry.
                dst.executescript(f"BEGIN IMMEDIATE;\n{steps}\nPRAGMA user_version={SCHEMA_VERSION};")
                append_audit(dst, int(datetime.now(timezone.utc).timestamp()), "system", "SCHEMA_UPGRADE",
                             "schema", {"version": version}, {"version": SCHEMA_VERSION},
                             "Program güncellendi; veri şeması yükseltildi.")
                dst.execute("COMMIT")
            except BaseException:
                if dst.in_transaction:
                    dst.execute("ROLLBACK")
                raise
    except sqlite3.Error as exc:
        raise AppError(f"Veri şeması güncellenemedi ({type(exc).__name__}); veri değiştirilmedi.") from exc
    finally:
        src.close()
        dst.close()
    fsync_file(target)
    return version


def upgrade_database(path: Path):
    """Upgrade an older database file in place; no-op when current.

    The upgrade is built and verified in a staging copy, the original is kept
    in backups/ as "guncelleme-oncesi-v<n>-…", and only then replaces the file.
    Returns the kept copy (or None when nothing was upgraded).
    """
    path = Path(path)
    version = schema_version(path)
    if version == SCHEMA_VERSION:
        return None
    check_upgradable(version)
    fd, staging = tempfile.mkstemp(prefix=".upgrade-", suffix=".sqlite3", dir=path.parent)
    os.close(fd)
    try:
        upgraded_copy(path, Path(staging))
        errors = inspect_database(Path(staging))
        if errors:
            raise AppError("Güncellenen veri doğrulanamadı; veri değiştirilmedi: " + "; ".join(errors))
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        kept = path.parent / "backups" / f"guncelleme-oncesi-v{version}-{stamp}.sqlite3"
        kept.parent.mkdir(parents=True, exist_ok=True)
        # Byte-for-byte: the caller holds FileLock and the journal is already recovered.
        shutil.copyfile(path, kept)
        fsync_file(kept)
        kept.with_suffix(kept.suffix + ".sha256").write_text(
            hashlib.sha256(kept.read_bytes()).hexdigest() + "  " + kept.name + "\n", encoding="utf-8")
        os.replace(staging, path)
        return kept
    finally:
        if os.path.exists(staging):
            os.unlink(staging)


def append_audit(conn, at, actor, action, entity, before=None, after=None, reason=""):
    """Append one entry to the hashed audit chain (inside the caller's transaction)."""
    previous = conn.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
    previous = previous[0] if previous else "0" * 64
    values = [at, actor, action, entity, canonical(before), canonical(after), reason]
    conn.execute(
        """INSERT INTO audit(at,actor,action,entity,before_json,after_json,reason,
           previous_hash,hash) VALUES(?,?,?,?,?,?,?,?,?)""",
        (*values, previous, audit_hash(previous, values)),
    )


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def audit_hash(previous: str, values: list) -> str:
    return hashlib.sha256((previous + canonical(values)).encode()).hexdigest()


class FileLock:
    """OS-held lock; released by the OS on crash. Never unlink the lock file."""
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.handle = (directory / "application.lock").open("a+b")
        try:
            # On Windows, reading a byte another process has locked raises
            # PermissionError, so every step of acquiring belongs in the try.
            self.handle.seek(0)
            if self.handle.read(1) == b"":
                self.handle.write(b"0")
                self.handle.flush()
            self.handle.seek(0)
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            raise AppError("Bu veri klasörü başka bir uygulamada açık.") from exc

    def close(self):
        self.handle.close()


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.upgraded_from = None
        exists = self.path.exists()
        if not exists:
            # Publish only a committed schema, so an interrupted first launch
            # cannot leave an empty production database that blocks setup.
            fd, staging = tempfile.mkstemp(prefix=".init-", suffix=".sqlite3", dir=self.path.parent)
            os.close(fd)
            try:
                initial = sqlite3.connect(staging, isolation_level=None)
                try:
                    initial.execute("PRAGMA synchronous=FULL")
                    initial.executescript("BEGIN IMMEDIATE;\n" + SCHEMA +
                                          f"\nPRAGMA user_version={SCHEMA_VERSION};\nCOMMIT;")
                finally:
                    initial.close()
                fsync_file(staging)
                os.replace(staging, self.path)
            finally:
                if os.path.exists(staging):
                    os.unlink(staging)
        if exists:
            # SQLite needs write access to recover a hot rollback journal after
            # a power/process failure. Perform that recovery before read-only QA.
            probe = sqlite3.connect(self.path, timeout=10)
            try:
                probe.execute("PRAGMA user_version").fetchone()
            finally:
                probe.close()
            self.upgraded_from = upgrade_database(self.path)
            errors = inspect_database(self.path)
            if errors:
                raise AppError("Veritabanı açılamadı: " + "; ".join(errors))
        self.conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=10000")
        # A single workstation does not need WAL concurrency. DELETE + FULL
        # also avoids copying a live WAL and permits broadly supported SQLite.
        self.conn.execute("PRAGMA journal_mode=DELETE")
        self.conn.execute("PRAGMA synchronous=FULL")

    @contextmanager
    def transaction(self):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def close(self):
        self.conn.close()

    def meta(self, key, default=None):
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key, value):
        self.conn.execute(
            "INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )

    def audit(self, at, actor, action, entity, before=None, after=None, reason=""):
        append_audit(self.conn, at, actor, action, entity, before, after, reason)


SNAPSHOT_DEFAULTS = {"active": 1, "voided": 0, "review": ""}


def inspect_database(path: Path) -> list[str]:
    """Read-only structural, relational, business and audit-chain checks."""
    errors = []
    try:
        conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            conn.execute("BEGIN")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if OLDEST_SUPPORTED <= version < SCHEMA_VERSION:
                return [f"Veri şeması eski (sürüm {version}); program açıldığında güncellenir."]
            if version != SCHEMA_VERSION:
                return ["Desteklenmeyen veya eksik veri şeması."]
            result = conn.execute("PRAGMA integrity_check").fetchall()
            if result != [("ok",)]:
                errors.extend(str(row[0]) for row in result)
            if conn.execute("PRAGMA foreign_key_check").fetchall():
                errors.append("İlişkili kayıt bütünlüğü bozuk.")
            expected = {"meta", "credentials", "employees", "rate_history", "sessions",
                        "payments", "receipts", "audit"}
            actual = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not expected <= actual:
                return ["Gerekli tablolar eksik."]
            if conn.execute(OVERLAP_SQL).fetchone():
                errors.append("Çakışan çalışma kayıtları var.")
            if conn.execute("""SELECT 1 FROM employees e LEFT JOIN credentials c
                ON c.subject='staff:'||e.id WHERE c.subject IS NULL LIMIT 1""").fetchone():
                errors.append("Personel kimlik bilgisi eksik.")
            previous = "0" * 64
            snapshots = {}
            for row in conn.execute("""SELECT at,actor,action,entity,before_json,after_json,
                                      reason,previous_hash,hash FROM audit ORDER BY id"""):
                if row[7] != previous or row[8] != audit_hash(previous, list(row[:7])):
                    errors.append("İşlem geçmişinin doğrulama zinciri bozuk.")
                    break
                previous = row[8]
                after = json.loads(row[5])
                if isinstance(after, dict) and row[3].startswith(("session:", "employee:", "payment:")):
                    snapshots.setdefault(row[3], {}).update(after)
            for table, entity, fields in [
                ("sessions", "session", ("employee_id", "start_at", "end_at", "rate_cents", "voided",
                                         "revision", "review")),
                ("employees", "employee", ("name", "rate_cents", "active")),
                ("payments", "payment", ("employee_id", "paid_at", "amount_cents", "kind", "note", "voided")),
            ]:
                records = conn.execute(f"SELECT id,{','.join(fields)} FROM {table}").fetchall()
                record_ids = {r[0] for r in records}
                for record in records:
                    snapshot = snapshots.get(f"{entity}:{record[0]}", {})
                    expected_values = [snapshot.get(field, SNAPSHOT_DEFAULTS.get(field)) for field in fields]
                    if not snapshot or list(record[1:]) != expected_values:
                        errors.append(f"İşlem geçmişi ile {table} kaydı uyuşmuyor: {record[0]}.")
                        break
                for key in snapshots:
                    if key.startswith(entity + ":") and int(key.split(":")[1]) not in record_ids:
                        errors.append(f"Geçmişte bulunan {table} kaydı eksik.")
                        break
        finally:
            conn.close()
    except (sqlite3.Error, OSError, ValueError) as exc:
        errors.append(f"Veri dosyası okunamadı ({type(exc).__name__}).")
    return errors
