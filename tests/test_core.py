import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from fractions import Fraction

import pytest

from conftest import FakeClock, PASSWORD, PIN, ts
from vardiya.reports import build_report, round_cents, split_days
from vardiya.security import AppError, hash_secret, validate_pin, verify_secret
from vardiya.service import Service
from vardiya.storage import Database, inspect_database


def uid():
    return str(uuid.uuid4())


def admin(s):
    return s.login_admin(PASSWORD)


def test_multiple_entries_and_restart(system):
    s, c, token, eid = system
    first = s.attendance(eid, PIN, "start", None, uid())
    c.advance(3600)
    s.attendance(eid, PIN, "end", first, uid())
    c.advance(600)
    second = s.attendance(eid, PIN, "start", None, uid())
    path = s.db.path
    s.db.close()
    s.db = Database(path)
    assert s.kiosk_employees()[0]["session_id"] == second
    c.advance(1800)
    s.attendance(eid, PIN, "end", second, uid())
    report = build_report(s, admin(s), date(2026, 10, 20), date(2026, 10, 20))
    assert report["summary"][0]["seconds"] == 5400
    assert report["summary"][0]["cents"] == 22500


def test_duplicate_start_finish_and_stale_target(system):
    s, c, _, eid = system
    request = uid()
    sid = s.attendance(eid, PIN, "start", None, request)
    assert s.attendance(eid, PIN, "start", None, request) == sid
    with pytest.raises(AppError):
        s.attendance(eid, PIN, "start", None, uid())
    c.advance(1)
    finish = uid()
    s.attendance(eid, PIN, "end", sid, finish)
    assert s.attendance(eid, PIN, "end", sid, finish) == sid
    new = s.attendance(eid, PIN, "start", None, uid())
    with pytest.raises(AppError):
        s.attendance(eid, PIN, "end", sid, uid())
    assert s.kiosk_employees()[0]["session_id"] == new
    with pytest.raises(AppError):
        s.attendance(eid, PIN, "end", new, request)


def test_same_second_exit_is_rejected(system):
    s, _, _, eid = system
    sid = s.attendance(eid, PIN, "start", None, uid())
    with pytest.raises(AppError):
        s.attendance(eid, PIN, "end", sid, uid())


def test_concurrent_writers_only_one_open(system):
    s, c, _, eid = system
    path, now = s.db.path, c.now

    def write():
        db = Database(path)
        try:
            other = Service(db, FakeClock(now))
            try:
                return other.attendance(eid, PIN, "start", None, uid())
            except AppError:
                return None
        finally:
            db.close()

    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(lambda _: write(), range(2)))
    assert sum(r is not None for r in results) == 1
    assert s.db.conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1


def test_database_unique_open_constraint(system):
    s, c, _, eid = system
    s.attendance(eid, PIN, "start", None, uid())
    with pytest.raises(sqlite3.IntegrityError), s.db.transaction():
        s.db.conn.execute("INSERT INTO sessions(employee_id,start_at,rate_cents) VALUES(?,?,?)",
                          (eid, c.now + 1, 1))


def test_failed_audit_rolls_back_attendance(system, monkeypatch):
    s, _, _, eid = system
    s.tick()
    def fail(*args, **kwargs):
        raise OSError("simulated disk failure")
    monkeypatch.setattr(s.db, "audit", fail)
    with pytest.raises(OSError):
        s.attendance(eid, PIN, "start", None, uid())
    assert s.db.conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
    assert s.db.conn.execute("SELECT count(*) FROM receipts").fetchone()[0] == 0


def test_midnight_month_split_and_rate_snapshot(system):
    s, c, _, eid = system
    c.now = ts("2026-10-31T23:30:00")
    s.acknowledge_clock(admin(s), "Test saati doğrulandı")
    sid = s.attendance(eid, PIN, "start", None, uid())
    s.update_employee(admin(s), eid, "Ayşe Yılmaz", 20000, True, "Yeni ücret belirlendi")
    c.advance(3600)
    s.attendance(eid, PIN, "end", sid, uid())
    october = build_report(s, admin(s), date(2026, 10, 1), date(2026, 10, 31))
    november = build_report(s, admin(s), date(2026, 11, 1), date(2026, 11, 30))
    assert october["summary"][0]["cents"] == 7500
    assert november["summary"][0]["cents"] == 7500
    assert november["summary"][0]["carry_cents"] == 7500
    new = s.attendance(eid, PIN, "start", None, uid())
    rows = s.sessions(admin(s))
    assert {r["id"]: r["rate_cents"] for r in rows} == {sid: 15000, new: 20000}


def test_open_session_is_provisional(system):
    s, c, _, eid = system
    s.attendance(eid, PIN, "start", None, uid())
    c.advance(1800)
    r = build_report(s, admin(s), date(2026, 10, 20), date(2026, 10, 20))["summary"][0]
    assert r["cents"] == r["balance_cents"] == 0
    assert r["open_cents"] == 7500
    assert r["open_seconds"] == 1800


def test_rounding_once_per_day_not_per_session(system):
    s, c, token, eid = system
    for offset in (10, 20):
        s.manual_session(token, eid, c.now - offset, c.now - offset + 1, 100,
                         "Eksik kayıt tamamlandı", uid())
    report = build_report(s, token, date(2026, 10, 20), date(2026, 10, 20))
    assert report["summary"][0]["cents"] == 0
    assert round_cents(Fraction(1, 2)) == 1
    assert round_cents(Fraction(149, 100)) == 1


def test_timezone_dst_elapsed_seconds():
    from zoneinfo import ZoneInfo
    zone = ZoneInfo("Europe/Berlin")
    from datetime import datetime
    first = int(datetime(2026, 10, 25, tzinfo=zone).timestamp())
    last = int(datetime(2026, 10, 26, tzinfo=zone).timestamp())
    assert list(split_days(first, last, zone)) == [("2026-10-25", 25 * 3600)]


def test_payments_balance_void_and_idempotency(system):
    s, c, token, eid = system
    s.manual_session(token, eid, c.now - 3600, c.now, 15000, "Eksik giriş eklendi", uid())
    key = uid()
    pid = s.add_payment(token, eid, c.now, 5000, "Avans", "Nakit avans verildi", key)
    assert s.add_payment(token, eid, c.now, 5000, "Avans", "Nakit avans verildi", key) == pid
    with pytest.raises(AppError):
        s.add_payment(token, eid, c.now, 5000, "Avans", "Nakit avans verildi", uid())
    report = build_report(s, token, date(2026, 10, 20), date(2026, 10, 20))
    assert report["summary"][0]["balance_cents"] == 10000
    s.void_payment(token, pid, "Yanlış ödeme iptal edildi")
    report = build_report(s, token, date(2026, 10, 20), date(2026, 10, 20))
    assert report["summary"][0]["balance_cents"] == 15000
    with pytest.raises(AppError):
        s.void_payment(token, pid, "İkinci iptal denemesi")


def test_prior_payment_carries_negative_balance(system):
    s, c, token, eid = system
    s.add_payment(token, eid, ts("2026-09-30T12:00"), 40000, "Avans", "Önceki ay avansı", uid())
    r = build_report(s, token, date(2026, 10, 1), date(2026, 10, 31))["summary"][0]
    assert r["carry_cents"] == r["balance_cents"] == -40000
    assert r["paid_cents"] == r["period_net_cents"] == 0


def test_correction_overlap_revision_and_history(system):
    s, c, token, eid = system
    first = s.manual_session(token, eid, c.now - 7200, c.now - 3600, 15000, "Eksik kayıt eklendi", uid())
    s.manual_session(token, eid, c.now - 1800, c.now, 15000, "Eksik kayıt eklendi", uid())
    with pytest.raises(AppError):
        s.correct_session(token, first, 1, c.now - 7200, c.now, "Çakışan düzeltme")
    s.correct_session(token, first, 1, c.now - 7000, c.now - 3600, "Giriş saati düzeltildi")
    with pytest.raises(AppError):
        s.correct_session(token, first, 1, c.now - 7000, c.now - 3600, "Eski sürüm denemesi")
    audit = next(a for a in s.audit_rows(token) if a["action"] == "SESSION_CORRECT")
    assert '"revision":1' in audit["before_json"]
    assert '"revision":2' in audit["after_json"]
    assert not inspect_database(s.db.path)


def test_void_old_open_record_and_archive_protection(system):
    s, c, token, eid = system
    sid = s.attendance(eid, PIN, "start", None, uid())
    with pytest.raises(AppError):
        s.update_employee(token, eid, "Ayşe", 15000, False, "Arşive taşıma")
    c.advance(8 * 86400)
    token = admin(s)
    s.correct_session(token, sid, 1, c.now - 8 * 86400, None, "Unutulan kayıt iptal", void=True)
    s.update_employee(token, eid, "Ayşe", 15000, False, "Arşive taşıma")
    assert not s.kiosk_employees()
    with pytest.raises(AppError):
        s.manual_session(token, eid, c.now - 60, None, 15000, "Arşiv açık kayıt", uid())


@pytest.mark.parametrize("pin", ["123456", "111111", "543210", "12345", "1234567", "１２３４５６", "abc123"])
def test_reject_weak_or_invalid_pins(pin):
    with pytest.raises(AppError):
        validate_pin(pin)


def test_salted_passwords_and_no_plaintext(system):
    s, _, _, _ = system
    first, second = hash_secret(PIN), hash_secret(PIN)
    assert first != second
    assert verify_secret(PIN, first)
    assert not verify_secret("000000", first)
    content = s.db.path.read_bytes()
    assert PIN.encode() not in content
    assert PASSWORD.encode() not in content


def test_pin_lock_persists_restart(system):
    s, c, _, eid = system
    for _ in range(5):
        with pytest.raises(AppError):
            s.attendance(eid, "192837", "start", None, uid())
    s.db.close()
    s.db = Database(s.db.path)
    with pytest.raises(AppError, match="kilid"):
        s.attendance(eid, PIN, "start", None, uid())
    c.advance(301)
    s.attendance(eid, PIN, "start", None, uid())


def test_admin_authorization_expiry_and_change(system):
    s, c, token, eid = system
    with pytest.raises(AppError):
        s.employees("fake")
    with pytest.raises(AppError):
        s.add_payment(None, eid, c.now, 100, "Avans", "Yetkisiz deneme", uid())
    c.advance(301)
    with pytest.raises(AppError):
        s.employees(token)
    token = admin(s)
    s.change_password(token, PASSWORD, "YeniGuvenliSifre2026!")
    with pytest.raises(AppError):
        s.employees(token)
    with pytest.raises(AppError):
        s.login_admin(PASSWORD)
    assert s.login_admin("YeniGuvenliSifre2026!")


def test_admin_lock_and_setup_cannot_be_overwritten(system):
    s, c, _, _ = system
    with pytest.raises(AppError):
        s.setup("FarkliSifre!2026")
    for _ in range(5):
        with pytest.raises(AppError):
            s.login_admin("YanlisSifre123")
    with pytest.raises(AppError, match="kilid"):
        s.login_admin(PASSWORD)
    c.advance(301)
    assert s.login_admin(PASSWORD)


def test_sql_injection_stored_as_text(system):
    s, _, token, _ = system
    eid = s.add_employee(token, "'); DROP TABLE employees;--", "573819", 100)
    assert any(r["id"] == eid for r in s.employees(token))
    assert len(s.employees(token)) == 2


@pytest.mark.parametrize("jump", [-600, 3600])
def test_clock_manipulation_flags_records_until_admin_review(system, jump):
    s, c, token, eid = system
    s.tick()
    c.now += jump
    assert s.tick()
    # Staff can still work; the record is flagged instead of refused.
    sid = s.attendance(eid, PIN, "start", None, uid())
    row = next(r for r in s.sessions(token) if r["id"] == sid)
    assert "saat" in row["review"].lower()
    assert s.pending_reviews(token) == 1
    s.acknowledge_clock(token, "Bilgisayar saati kontrol edildi")
    assert not s.tick()
    assert s.pending_reviews(token) == 1  # Acknowledging the clock is not reviewing records.
    c.advance(60)
    s.correct_session(token, sid, row["revision"], row["start_at"], None, "Saat kontrol edildi, kayıt doğru")
    assert s.pending_reviews(token) == 0
    assert not inspect_database(s.db.path)


def test_restart_backwards_and_long_gap(system):
    s, c, token, eid = system
    s.tick()
    restarted = Service(s.db, FakeClock(c.now - 600))
    assert restarted.tick()
    restarted.acknowledge_clock(admin(restarted), "Saat düzeltildi kontrol edildi")
    long_gap = Service(s.db, FakeClock(c.now + 3 * 86400))
    # A closed day or holiday is only a notice: no alert, attendance unflagged.
    assert not long_gap.tick()
    alert, notice = long_gap.clock_status()
    assert not alert and "uzun süre" in notice
    sid = long_gap.attendance(eid, PIN, "start", None, uid())
    token = admin(long_gap)
    assert next(r for r in long_gap.sessions(token) if r["id"] == sid)["review"] == ""
    long_gap.acknowledge_clock(token, "Uzun ara sonrası saat doğru")
    assert long_gap.clock_status() == ("", "")


def test_long_session_requires_manager(system):
    s, c, _, eid = system
    sid = s.attendance(eid, PIN, "start", None, uid())
    c.advance(25 * 3600)
    with pytest.raises(AppError, match="24"):
        s.attendance(eid, PIN, "end", sid, uid())
    assert s.kiosk_employees()[0]["session_id"] == sid


def test_audit_append_only_and_tamper_detection(system):
    s, _, _, _ = system
    with pytest.raises(sqlite3.IntegrityError):
        s.db.conn.execute("DELETE FROM audit")
    s.db.conn.execute("DROP TRIGGER audit_no_update")
    s.db.conn.execute("UPDATE audit SET reason='tampered' WHERE id=1")
    assert any("zinciri" in e for e in inspect_database(s.db.path))


@pytest.mark.parametrize("amount", [-1, 100000001, 1.5, True])
def test_invalid_money_rejected(system, amount):
    s, _, token, _ = system
    with pytest.raises(AppError):
        s.add_employee(token, "Test", "573819", amount)


def test_report_range_validation(system):
    s, _, token, _ = system
    with pytest.raises(AppError):
        build_report(s, token, date(2026, 10, 20), date(2026, 10, 19))
    with pytest.raises(AppError):
        build_report(s, token, date(2020, 1, 1), date(2026, 10, 20))
