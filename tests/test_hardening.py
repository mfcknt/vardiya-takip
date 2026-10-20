"""Tests for the hardening round: performance, clock review, locks, retention, filters."""
import csv
import random
import sqlite3
import uuid
from datetime import date

import pytest

from conftest import PASSWORD, PIN, ts
from vardiya import backup as backup_module
from vardiya.backup import automatic_backup, backup_usage, prune_backups
from vardiya.reports import build_report, export_audit
from vardiya.security import AppError
from vardiya.service import STAFF_LOCK_STEPS, staff_lock_seconds
from vardiya.storage import OVERLAP_SQL, fsync_file, inspect_database

WRONG = "192837"


def uid():
    return str(uuid.uuid4())


# --- overlap check -----------------------------------------------------------

OLD_SELF_JOIN = """SELECT 1 FROM sessions a JOIN sessions b
    ON a.employee_id=b.employee_id AND a.id<b.id
    WHERE a.voided=0 AND b.voided=0
    AND a.start_at<COALESCE(b.end_at,9223372036854775807)
    AND b.start_at<COALESCE(a.end_at,9223372036854775807) LIMIT 1"""


def _sessions_db(rows):
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE sessions(id INTEGER PRIMARY KEY, employee_id INTEGER,
                    start_at INTEGER, end_at INTEGER, voided INTEGER)""")
    conn.executemany("INSERT INTO sessions(employee_id,start_at,end_at,voided) VALUES(?,?,?,?)", rows)
    return conn


def test_overlap_sweep_matches_self_join_on_random_data():
    rng = random.Random(20261020)
    for _ in range(400):
        rows = []
        for _ in range(rng.randint(0, 8)):
            start = rng.randint(0, 50)
            end = None if rng.random() < 0.15 else start + rng.randint(1, 12)
            rows.append((rng.randint(1, 3), start, end, int(rng.random() < 0.2)))
        conn = _sessions_db(rows)
        assert bool(conn.execute(OVERLAP_SQL).fetchone()) == bool(conn.execute(OLD_SELF_JOIN).fetchone()), rows
        conn.close()


def test_overlap_edge_cases():
    touching = _sessions_db([(1, 0, 10, 0), (1, 10, 20, 0)])
    assert not touching.execute(OVERLAP_SQL).fetchone()
    same_start = _sessions_db([(1, 5, 6, 0), (1, 5, 9, 0)])
    assert same_start.execute(OVERLAP_SQL).fetchone()
    nested_after_long = _sessions_db([(1, 0, 100, 0), (1, 10, 20, 0), (1, 30, 40, 0)])
    assert nested_after_long.execute(OVERLAP_SQL).fetchone()
    other_employee = _sessions_db([(1, 0, 10, 0), (2, 5, 15, 0)])
    assert not other_employee.execute(OVERLAP_SQL).fetchone()
    voided = _sessions_db([(1, 0, 10, 0), (1, 5, 15, 1)])
    assert not voided.execute(OVERLAP_SQL).fetchone()
    open_then_later = _sessions_db([(1, 0, None, 0), (1, 50, 60, 0)])
    assert open_then_later.execute(OVERLAP_SQL).fetchone()


def test_inspection_scales_linearly(system):
    """3 years x 30 staff must stay well under the old ~1.7 s heartbeat cost."""
    import time
    s, c, token, _ = system
    ids = [s.add_employee(token, f"P{i}", "%06d" % (271828 + i * 7919), 15000) for i in range(29)]
    ids.append(1)
    base = c.now - 3 * 365 * 86400
    with s.db.transaction():
        for d in range(3 * 365):
            for eid in ids:
                start = base + d * 86400
                sid = s.db.conn.execute(
                    "INSERT INTO sessions(employee_id,start_at,end_at,rate_cents) VALUES(?,?,?,?)",
                    (eid, start, start + 8 * 3600, 15000)).lastrowid
                row = dict(s.db.conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone())
                s.db.audit(start, f"staff:{eid}", "START", f"session:{sid}", after=row)
    began = time.perf_counter()
    found = s.db.conn.execute(OVERLAP_SQL).fetchone()
    elapsed = time.perf_counter() - began
    assert found is None
    assert elapsed < 0.5, elapsed
    assert not inspect_database(s.db.path)


# --- heartbeat backup --------------------------------------------------------

def test_automatic_backup_is_verified_once_per_process(system, monkeypatch):
    s, _, _, _ = system
    from zoneinfo import ZoneInfo
    zone = ZoneInfo("Europe/Istanbul")
    verified = set()
    path = automatic_backup(s.db, zone, verified)
    assert path.exists() and path in verified
    calls = []
    real = backup_module.inspect_database
    monkeypatch.setattr(backup_module, "inspect_database", lambda p: calls.append(p) or real(p))
    for _ in range(10):
        automatic_backup(s.db, zone, verified)
    assert calls == []
    # A fresh process (new set) verifies the existing file exactly once.
    fresh = set()
    automatic_backup(s.db, zone, fresh)
    automatic_backup(s.db, zone, fresh)
    assert calls == [path]


def test_corrupt_daily_backup_is_reported_and_not_cached(system):
    s, _, _, _ = system
    from zoneinfo import ZoneInfo
    zone = ZoneInfo("Europe/Istanbul")
    path = automatic_backup(s.db, zone, set())
    path.write_bytes(b"damaged")
    verified = set()
    with pytest.raises(AppError):
        automatic_backup(s.db, zone, verified)
    assert path not in verified


def test_fsync_file_uses_writable_handle(tmp_path):
    target = tmp_path / "x.bin"
    target.write_bytes(b"data")
    fsync_file(target)
    assert target.read_bytes() == b"data"


# --- retention ---------------------------------------------------------------

def _touch(path):
    path.write_bytes(b"x")
    path.with_suffix(path.suffix + ".sha256").write_text("x")
    return path


def test_prune_keeps_recent_monthly_and_manual(tmp_path):
    days = [date(2026, 1, 1).toordinal() + i for i in range(120)]
    daily = [_touch(tmp_path / f"otomatik-{date.fromordinal(d).isoformat()}.sqlite3") for d in days]
    closing = [_touch(tmp_path / f"kapanis-202604{i:02d}-120000-000000.sqlite3") for i in range(1, 26)]
    manual = _touch(tmp_path / "vardiya-20260301-101010.sqlite3")
    other = tmp_path / "notlar.txt"
    other.write_text("dokunma")
    removed = prune_backups(tmp_path)
    kept = {p.name for p in tmp_path.glob("*.sqlite3")}
    assert {p.name for p in daily[-30:]} <= kept
    for month in ("01", "02", "03", "04"):
        assert f"otomatik-2026-{month}-01.sqlite3" in kept
    assert {p.name for p in closing[-20:]} <= kept
    assert not ({p.name for p in closing[:5]} & kept)
    assert manual.exists() and other.exists()
    assert len(removed) == (120 - 30 - 3) + 5  # Jan/Feb/Mar firsts are outside the last 30.
    for p in removed:
        assert not p.with_suffix(p.suffix + ".sha256").exists()


def test_prune_zero_retention_keeps_nothing_but_monthly(tmp_path):
    _touch(tmp_path / "otomatik-2026-05-01.sqlite3")
    _touch(tmp_path / "otomatik-2026-05-02.sqlite3")
    _touch(tmp_path / "kapanis-20260502-120000-000000.sqlite3")
    prune_backups(tmp_path, keep_daily=0, keep_closing=0)
    assert {p.name for p in tmp_path.glob("*.sqlite3")} == {"otomatik-2026-05-01.sqlite3"}


def test_backup_usage_counts_backup_folder(system):
    s, _, _, _ = system
    from zoneinfo import ZoneInfo
    automatic_backup(s.db, ZoneInfo("Europe/Istanbul"), set())
    count, size = backup_usage(s.db)
    assert count == 1 and size > 0


# --- PIN locks ---------------------------------------------------------------

def test_staff_lock_escalates_and_admin_unlocks(system):
    s, c, token, eid = system
    assert [staff_lock_seconds(n) for n in range(4, 11)] == [0, *STAFF_LOCK_STEPS, STAFF_LOCK_STEPS[-1]]
    for _ in range(4):
        with pytest.raises(AppError, match="doğrulanamadı"):
            s.attendance(eid, WRONG, "start", None, uid())
    with pytest.raises(AppError, match="kilid"):
        s.attendance(eid, WRONG, "start", None, uid())  # 5th wrong: 30 s lock
    with pytest.raises(AppError, match="kilid"):
        s.attendance(eid, PIN, "start", None, uid())     # correct PIN still waits
    c.advance(31)
    with pytest.raises(AppError, match="kilid"):
        s.attendance(eid, WRONG, "start", None, uid())  # 6th wrong: 60 s lock
    c.advance(31)
    with pytest.raises(AppError, match="kilid"):
        s.attendance(eid, PIN, "start", None, uid())
    token = s.login_admin(PASSWORD)
    locked = next(e for e in s.employees(token) if e["id"] == eid)
    assert locked["locked_until"] > c.now and locked["failures"] == 6
    assert s.kiosk_employees()[0]["locked_until"] > c.now
    s.unlock_employee(token, eid, "Personel kimliği görülerek açıldı")
    assert s.attendance(eid, PIN, "start", None, uid())
    assert any(a["action"] == "AUTH_UNLOCK" for a in s.audit_rows(token))
    assert not inspect_database(s.db.path)


def test_correct_pin_resets_staff_counter(system):
    s, c, token, eid = system
    for _ in range(4):
        with pytest.raises(AppError):
            s.attendance(eid, WRONG, "start", None, uid())
    s.attendance(eid, PIN, "start", None, uid())
    assert next(e for e in s.employees(token) if e["id"] == eid)["failures"] == 0


def test_unlock_requires_admin_and_reason(system):
    s, _, token, eid = system
    with pytest.raises(AppError):
        s.unlock_employee("fake", eid, "Yetkisiz kilit açma")
    with pytest.raises(AppError):
        s.unlock_employee(token, eid, "x")
    with pytest.raises(AppError):
        s.unlock_employee(token, 999, "Olmayan personel")


# --- clock review ------------------------------------------------------------

def test_finish_under_alert_flags_existing_record(system):
    s, c, token, eid = system
    s.tick()
    sid = s.attendance(eid, PIN, "start", None, uid())
    c.advance(3600)
    c.now += 600  # wall clock jumps ahead of monotonic time
    s.attendance(eid, PIN, "end", sid, uid())
    token = s.login_admin(PASSWORD)
    row = next(r for r in s.sessions(token) if r["id"] == sid)
    assert row["review"] and row["end_at"]
    r = build_report(s, token, date(2026, 10, 20), date(2026, 10, 20))
    assert r["review_count"] == 1
    assert r["sessions"][0]["review"]


def test_clock_set_back_before_start_tells_staff_to_ask_admin(system):
    s, c, token, eid = system
    s.tick()
    sid = s.attendance(eid, PIN, "start", None, uid())
    c.now -= 3600
    with pytest.raises(AppError, match="yönetici"):
        s.attendance(eid, PIN, "end", sid, uid())


# --- filters -----------------------------------------------------------------

def test_session_payment_and_audit_filters(system):
    s, c, token, eid = system
    other = s.add_employee(token, "Can Arslan", "573819", 12000)
    old = s.manual_session(token, eid, ts("2026-09-01T09:00"), ts("2026-09-01T17:00"), 15000,
                           "Eylül kaydı eklendi", uid())
    new = s.manual_session(token, other, ts("2026-10-19T09:00"), ts("2026-10-19T17:00"), 12000,
                           "Ekim kaydı eklendi", uid())
    open_ = s.attendance(eid, PIN, "start", None, uid())
    since = ts("2026-10-01T00:00")
    assert {r["id"] for r in s.sessions(token, since=since)} == {new, open_}
    assert {r["id"] for r in s.sessions(token, eid=eid)} == {old, open_}
    assert {r["id"] for r in s.sessions(token, since=ts("2026-09-01T12:00"),
                                        until=ts("2026-09-01T13:00"))} == {old}
    p1 = s.add_payment(token, eid, ts("2026-09-02T12:00"), 1000, "Avans", "Eylül avansı", uid())
    p2 = s.add_payment(token, other, ts("2026-10-19T12:00"), 2000, "Ödeme", "Ekim ödemesi", uid())
    assert [p["id"] for p in s.payments(token, since=since)] == [p2]
    assert [p["id"] for p in s.payments(token, eid=eid)] == [p1]
    assert len(s.audit_rows(token, limit=3)) == 3
    assert len(s.audit_rows(token)) > 3


def test_report_hides_idle_archived_staff_but_keeps_balances(system):
    s, c, token, eid = system
    idle = s.add_employee(token, "Eski Personel", "573819", 10000)
    owed = s.add_employee(token, "Alacaklı Eski", "684920", 10000)
    s.manual_session(token, owed, ts("2026-09-10T09:00"), ts("2026-09-10T10:00"), 10000,
                     "Eylül kaydı eklendi", uid())
    for person in (idle, owed):
        s.update_employee(token, person, "Arşiv " + str(person), 10000, False, "İşten ayrıldı")
    names = {r["employee_id"] for r in build_report(s, token, date(2026, 10, 1), date(2026, 10, 20))["summary"]}
    assert eid in names and owed in names and idle not in names


def test_audit_export_is_atomic_with_fixed_columns(system, tmp_path, monkeypatch):
    s, _, token, _ = system
    out = tmp_path / "exports"
    out.mkdir()
    path = out / "audit.csv"
    export_audit(s, token, path)
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter=";"))
    assert rows[0][:4] == ["id", "at", "actor", "action"] and rows[0][-1] == "Tarih (yerel)"
    assert len(rows) == len(s.audit_rows(token)) + 1
    path.write_text("eski", encoding="utf-8")
    import vardiya.reports as reports
    monkeypatch.setattr(reports, "safe_text", lambda v: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        export_audit(s, token, path)
    assert path.read_text(encoding="utf-8") == "eski"
    assert [p.name for p in out.iterdir()] == ["audit.csv"]


# --- money format ------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("150", 15000), ("150,50", 15050), ("150.50", 15050), ("1.500", 150000),
    ("1.500,50", 150050), ("12.345.678,90", 1234567890), (" 1.440,00 TL", 144000),
    ("₺75", 7500), ("1.5", 150), ("0", 0),
])
def test_amount_parsing_accepts_turkish_input(text, expected):
    from vardiya.formatting import cents
    assert cents(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "-5", "1,234", "12.345,678", "1,2,3", "NaN", "inf"])
def test_amount_parsing_rejects_invalid(text):
    from vardiya.formatting import cents
    with pytest.raises(AppError):
        cents(text)


def test_turkish_money_display():
    from vardiya.formatting import tl
    assert tl(144000) == "1.440,00"
    assert tl(5) == "0,05"
    assert tl(-3000) == "-30,00"
    assert tl(123456789) == "1.234.567,89"
