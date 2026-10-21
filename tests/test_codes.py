"""Four-digit staff PINs and admin code: weak-code rules and escalating admin lock."""
import uuid

import pytest

from conftest import PASSWORD, PIN
from vardiya.security import AppError, hash_secret, validate_password, validate_pin, weak_pin
from vardiya.service import ADMIN_LOCK_STEPS, admin_lock_seconds


@pytest.mark.parametrize("code", ["1111", "1234", "4321", "0123", "9876", "1212", "1122", "0000"])
def test_weak_codes(code):
    assert weak_pin(code)
    with pytest.raises(AppError):
        validate_pin(code)
    with pytest.raises(AppError):
        validate_password(code)


@pytest.mark.parametrize("code", ["4829", "1928", "0192", "7391", "2580"])
def test_acceptable_codes(code):
    assert not weak_pin(code)
    validate_pin(code)
    validate_password(code)


def test_admin_code_must_be_four_digits():
    for bad in ("123", "12345", "abcd", "Restoran!Guvenli2026"):
        with pytest.raises(AppError, match="4 rakam"):
            validate_password(bad)


def test_admin_lock_escalates_to_an_hour(system):
    s, c, _, _ = system
    assert [admin_lock_seconds(n) for n in range(4, 11)] == [0, *ADMIN_LOCK_STEPS, 3600, 3600]
    for _ in range(4):
        with pytest.raises(AppError, match="doğrulanamadı"):
            s.login_admin("9990")
    with pytest.raises(AppError, match="kilid"):
        s.login_admin("9990")                 # 5th: 5 minutes
    c.advance(301)
    with pytest.raises(AppError, match="kilid"):
        s.login_admin("9991")                 # 6th: 15 minutes
    c.advance(301)
    with pytest.raises(AppError, match="kilid"):
        s.login_admin(PASSWORD)               # still locked, right code waits too
    c.advance(900)
    assert s.login_admin(PASSWORD)            # success resets the counter
    row = s.db.conn.execute("SELECT failures FROM credentials WHERE subject='admin'").fetchone()
    assert row["failures"] == 0


def test_staff_pin_cannot_equal_admin_code(system):
    s, _, token, eid = system
    with pytest.raises(AppError, match="yönetici"):
        s.add_employee(token, "Can Arslan", PASSWORD, 12000)
    with pytest.raises(AppError, match="yönetici"):
        s.update_employee(token, eid, "Ayşe Yılmaz", 15000, True, "PIN yenilendi", pin=PASSWORD)
    s.update_employee(token, eid, "Ayşe Yılmaz", 15000, True, "PIN yenilendi", pin="7391")
    assert s.attendance(eid, "7391", "start", None, str(uuid.uuid4()))


def test_legacy_long_admin_password_still_signs_in(system):
    s, _, _, _ = system
    s.db.conn.execute("UPDATE credentials SET secret=? WHERE subject='admin'",
                      (hash_secret("Restoran!Guvenli2026"),))
    token = s.login_admin("Restoran!Guvenli2026")
    s.change_password(token, "Restoran!Guvenli2026", "7391")
    assert s.login_admin("7391")
    assert PIN != "7391"
