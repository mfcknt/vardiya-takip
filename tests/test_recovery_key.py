"""Admin recovery key: 20 digits on paper, single use, hashed, locked like the admin code."""
import re

import pytest

from conftest import PASSWORD
from vardiya.security import AppError
from vardiya.storage import inspect_database


def test_setup_creates_a_hashed_key_and_it_resets_the_admin_code(tmp_path):
    from conftest import FakeClock, ts
    from vardiya.service import Service
    from vardiya.storage import Database
    db = Database(tmp_path / "v.sqlite3")
    s = Service(db, FakeClock(ts("2026-10-20T12:00")))
    key = s.setup("7391")
    assert re.fullmatch(r"\d{4}(-\d{4}){4}", key) and s.has_recovery_key and s.admin_notes() == [
        "Henüz hiç yedek yok."]
    stored = db.conn.execute("SELECT secret FROM credentials WHERE subject='recovery'").fetchone()[0]
    assert key.replace("-", "") not in stored
    token = s.login_admin("7391")
    new_key = s.recover_admin(key, "5826")           # dashes and spaces are ignored
    assert token not in s._tokens and new_key != key
    with pytest.raises(AppError):
        s.login_admin("7391")
    s.login_admin("5826")
    with pytest.raises(AppError):                    # single use
        s.recover_admin(key, "6037")
    s.recover_admin(new_key.replace("-", " "), "6037")
    actions = [r[0] for r in db.conn.execute("SELECT action FROM audit ORDER BY id")]
    assert actions.count("ADMIN_RECOVERED") == 2
    assert not inspect_database(db.path)
    db.close()


def test_wrong_keys_lock_like_the_admin_code(system):
    s, c, token, _ = system
    key = s.new_recovery_key(token)
    for _ in range(4):
        with pytest.raises(AppError, match="doğrulanamadı"):
            s.recover_admin("0" * 20, "5826")
    with pytest.raises(AppError, match="kilidi") as locked:
        s.recover_admin("0" * 20, "5826")
    assert "Yönetici kilidi kaldırabilir" not in str(locked.value)
    with pytest.raises(AppError, match="kilidi"):     # even the right key waits
        s.recover_admin(key, "5826")
    c.advance(5 * 60 + 1)
    with pytest.raises(AppError, match="kolay|tekrarlanan"):
        s.recover_admin(key, "1234")                 # weak new code: key not consumed
    s.recover_admin(key, "5826")
    s.login_admin("5826")


def test_new_key_replaces_the_old_one_and_missing_key_is_a_note(system):
    s, c, token, _ = system
    first = s.new_recovery_key(token)
    second = s.new_recovery_key(token)
    with pytest.raises(AppError):
        s.recover_admin(first, "5826")
    s.db.conn.execute("DELETE FROM credentials WHERE subject='recovery'")
    assert s.admin_notes()[0].startswith("Kurtarma anahtarı yok.")
    with pytest.raises(AppError):
        s.recover_admin(second, "5826")
    s.login_admin(PASSWORD)
