"""Schema upgrades: old data files must open with every later program version."""
import hashlib
import shutil
import sqlite3
from pathlib import Path

import pytest

from vardiya import storage
from vardiya.backup import restore_database
from vardiya.security import AppError
from vardiya.service import Service
from vardiya.storage import Database, inspect_database, schema_version

FIXTURES = Path(__file__).parent / "fixtures"
ADMIN, PIN = "3917", "4829"


def copy_fixture(tmp_path, name="sema-v2.sqlite3"):
    path = tmp_path / "data" / "vardiya.sqlite3"
    path.parent.mkdir()
    shutil.copy(FIXTURES / name, path)
    return path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def counts(conn):
    return [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("employees", "sessions", "payments")]


@pytest.fixture
def version_3(monkeypatch):
    """A pretend next schema version that adds a column with a default."""
    monkeypatch.setattr(storage, "SCHEMA_VERSION", 3)
    monkeypatch.setattr(storage, "MIGRATIONS", {
        2: "ALTER TABLE employees ADD COLUMN phone TEXT NOT NULL DEFAULT '';"})


@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURES.glob("sema-v*.sqlite3")))
def test_every_old_data_file_opens_with_this_program(tmp_path, name):
    path = copy_fixture(tmp_path, name)
    db = Database(path)
    try:
        assert schema_version(path) == storage.SCHEMA_VERSION
        assert not inspect_database(path)
        service = Service(db)
        token = service.login_admin(ADMIN)
        assert [e["name"] for e in service.employees(token)] == ["Örnek Personel"]
        assert len(service.sessions(token)) == 1 and len(service.payments(token)) == 1
    finally:
        db.close()


def test_upgrade_keeps_data_and_a_copy_of_the_old_file(tmp_path, version_3):
    path = copy_fixture(tmp_path)
    original = digest(path)
    db = Database(path)
    try:
        assert schema_version(path) == 3
        assert counts(db.conn) == [1, 1, 1]
        assert db.conn.execute("SELECT phone FROM employees").fetchone()[0] == ""
        last = db.conn.execute("SELECT action, before_json, after_json FROM audit ORDER BY id DESC").fetchone()
        assert tuple(last) == ("SCHEMA_UPGRADE", '{"version":2}', '{"version":3}')
        assert not inspect_database(path)
        kept = db.upgraded_from
        assert kept.parent.name == "backups" and kept.name.startswith("guncelleme-oncesi-v2-")
        assert digest(kept) == original
        assert kept.with_suffix(".sqlite3.sha256").read_text().split()[0] == original
    finally:
        db.close()
    reopened = Database(path)          # already current: no second upgrade or copy
    assert reopened.upgraded_from is None
    reopened.close()
    assert len(list((path.parent / "backups").glob("guncelleme-oncesi-*.sqlite3"))) == 1
    assert not list(path.parent.glob(".upgrade-*"))


def test_failed_upgrade_changes_nothing(tmp_path, monkeypatch, version_3):
    monkeypatch.setattr(storage, "MIGRATIONS", {2: "ALTER TABLE missing ADD COLUMN x TEXT;"})
    path = copy_fixture(tmp_path)
    original = digest(path)
    with pytest.raises(AppError, match="güncellenemedi"):
        Database(path)
    assert digest(path) == original
    assert not list(path.parent.glob(".upgrade-*")) and not (path.parent / "backups").exists()


def test_newer_or_unsupported_files_are_refused_untouched(tmp_path, monkeypatch):
    path = copy_fixture(tmp_path)
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version={storage.SCHEMA_VERSION + 1}")
    conn.close()
    newer = digest(path)
    with pytest.raises(AppError, match="daha yeni bir sürümüyle"):
        Database(path)
    assert digest(path) == newer
    monkeypatch.setattr(storage, "OLDEST_SUPPORTED", storage.SCHEMA_VERSION + 2)
    monkeypatch.setattr(storage, "SCHEMA_VERSION", storage.SCHEMA_VERSION + 3)
    with pytest.raises(AppError, match="güncellenemiyor"):
        Database(path)
    assert digest(path) == newer


def test_check_reports_old_schema_without_changing_it(tmp_path, version_3):
    path = copy_fixture(tmp_path)
    assert inspect_database(path) == ["Veri şeması eski (sürüm 2); program açıldığında güncellenir."]


def test_restoring_an_old_backup_upgrades_it(tmp_path, version_3):
    backup = FIXTURES / "sema-v2.sqlite3"
    original = digest(backup)
    target = tmp_path / "data" / "vardiya.sqlite3"
    restore_database(backup, target, ADMIN)
    assert digest(backup) == original
    assert schema_version(target) == 3 and not inspect_database(target)
    conn = sqlite3.connect(target)
    try:
        assert counts(conn) == [1, 1, 1]
        actions = [r[0] for r in conn.execute("SELECT action FROM audit ORDER BY id DESC LIMIT 2")]
        assert actions == ["RESTORE", "SCHEMA_UPGRADE"]
    finally:
        conn.close()
    assert not list(target.parent.glob(".upgrade-*"))


def test_maintenance_tool_check_and_upgrade(tmp_path, monkeypatch, capsys, version_3):
    from vardiya.__main__ import main
    path = copy_fixture(tmp_path)
    run = lambda *flags: monkeypatch.setattr("sys.argv", ["VardiyaBakim", "--data-dir", str(path.parent),
                                                          *flags]) or main()
    assert run("--check") == 1 and "eski (sürüm 2)" in capsys.readouterr().out
    assert run("--upgrade") == 0 and "güncellendi" in capsys.readouterr().out
    assert run("--upgrade") == 0 and "zaten güncel" in capsys.readouterr().out
    assert run("--check") == 0 and "sağlam" in capsys.readouterr().out
    assert schema_version(path) == 3
