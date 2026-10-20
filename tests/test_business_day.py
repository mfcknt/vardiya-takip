"""Business-day boundary (default 05:00) and forgotten-exit detection."""
import uuid
from datetime import date

import pytest

from conftest import PASSWORD, PIN, ts
from vardiya.reports import build_report, split_days
from vardiya.security import AppError
from vardiya.service import DEFAULT_DAY_START_HOUR, FORGOTTEN_EXIT
from vardiya.storage import inspect_database


def uid():
    return str(uuid.uuid4())


def admin(s):
    return s.login_admin(PASSWORD)


def move_to(clock, text):
    """Advance wall and monotonic time together (no clock alert)."""
    clock.advance(ts(text) - clock.now)


def day_rows(report):
    return {(r["day"], r["seconds"], r["cents"]) for r in report["days"]}


def test_default_day_start_is_five(system):
    s, _, _, _ = system
    assert s.day_start_hour == DEFAULT_DAY_START_HOUR == 5


def test_half_hour_after_midnight_belongs_to_previous_business_day(system):
    s, c, token, eid = system
    move_to(c, "2026-10-21T12:00")
    token = admin(s)
    s.manual_session(token, eid, ts("2026-10-21T00:30"), ts("2026-10-21T01:00"), 15000,
                     "Gece yarım saat eklendi", uid())
    r20 = build_report(s, token, date(2026, 10, 20), date(2026, 10, 20))
    r21 = build_report(s, token, date(2026, 10, 21), date(2026, 10, 21))
    assert day_rows(r20) == {("2026-10-20", 1800, 7500)}
    assert r21["summary"][0]["cents"] == 0


def test_evening_shift_to_one_am_is_a_single_day(system):
    s, c, token, eid = system
    s.manual_session(token, eid, ts("2026-10-19T17:00"), ts("2026-10-20T01:00"), 15000,
                     "Akşam vardiyası eklendi", uid())
    r = build_report(s, token, date(2026, 10, 19), date(2026, 10, 20))
    assert day_rows(r) == {("2026-10-19", 8 * 3600, 120000)}


def test_shift_crossing_the_boundary_is_split_there():
    from zoneinfo import ZoneInfo
    zone = ZoneInfo("Europe/Istanbul")
    parts = list(split_days(ts("2026-10-21T04:00"), ts("2026-10-21T06:00"), zone, 5))
    assert parts == [("2026-10-20", 3600), ("2026-10-21", 3600)]
    assert list(split_days(ts("2026-10-21T04:00"), ts("2026-10-21T06:00"), zone)) == [("2026-10-21", 7200)]


def test_after_midnight_payment_counts_for_that_night(system):
    s, c, token, eid = system
    move_to(c, "2026-10-21T00:40")
    token = admin(s)
    s.add_payment(token, eid, ts("2026-10-21T00:30"), 2000, "Avans", "Kapanışta verilen avans", uid())
    r20 = build_report(s, token, date(2026, 10, 20), date(2026, 10, 20))
    assert r20["summary"][0]["paid_cents"] == 2000
    assert len(r20["payments"]) == 1


def test_day_bounds_follow_setting(system):
    s, _, token, _ = system
    assert s.day_bounds(date(2026, 10, 20), date(2026, 10, 20)) == (ts("2026-10-20T05:00"), ts("2026-10-21T05:00"))
    s.set_day_start(token, 0, "Takvim günü kullanılacak")
    assert s.day_bounds(date(2026, 10, 20), date(2026, 10, 20)) == (ts("2026-10-20T00:00"), ts("2026-10-21T00:00"))


def test_set_day_start_validation_and_audit(system):
    s, _, token, _ = system
    for bad in (-1, 13, 4.5, "5", True):
        with pytest.raises(AppError):
            s.set_day_start(token, bad, "Geçersiz ayar denemesi")
    with pytest.raises(AppError):
        s.set_day_start("fake", 6, "Yetkisiz ayar denemesi")
    s.set_day_start(token, 6, "Bazı geceler geç kapanıyor")
    assert s.day_start_hour == 6
    entry = next(a for a in s.audit_rows(token) if a["action"] == "SETTING_CHANGE")
    assert '"day_start_hour":5' in entry["before_json"] and '"day_start_hour":6' in entry["after_json"]
    assert not inspect_database(s.db.path)


def test_forgotten_exit_is_flagged_at_boundary_and_reviewed(system):
    s, c, _, eid = system
    move_to(c, "2026-10-20T17:00")
    sid = s.attendance(eid, PIN, "start", None, uid())
    move_to(c, "2026-10-21T04:59")
    s.tick()
    assert not s.past_day_boundary(ts("2026-10-20T17:00"))
    token = admin(s)
    assert s.pending_reviews(token) == 0
    move_to(c, "2026-10-21T05:00")
    s.tick()
    s.tick()  # flagged once, not on every heartbeat
    token = admin(s)
    row = next(r for r in s.sessions(token) if r["id"] == sid)
    assert row["review"] == FORGOTTEN_EXIT and row["revision"] == 2 and row["end_at"] is None
    assert [a["action"] for a in s.audit_rows(token)].count("SESSION_FLAG") == 1
    assert s.past_day_boundary(row["start_at"])
    assert not inspect_database(s.db.path)
    # Next morning the staff member closes it; the record stays flagged.
    move_to(c, "2026-10-21T09:00")
    s.attendance(eid, PIN, "end", sid, uid())
    token = admin(s)
    row = next(r for r in s.sessions(token) if r["id"] == sid)
    assert row["review"] == FORGOTTEN_EXIT and row["end_at"] == ts("2026-10-21T09:00")
    r = build_report(s, token, date(2026, 10, 20), date(2026, 10, 21))
    assert r["review_count"] == 1 and r["summary"][0]["review_count"] == 1
    # And can start a new shift right away.
    c.advance(60)
    new = s.attendance(eid, PIN, "start", None, uid())
    assert new != sid
    # Admin enters the real exit time; the flag clears and pay is correct.
    token = admin(s)
    s.correct_session(token, sid, row["revision"], row["start_at"], ts("2026-10-21T01:00"),
                      "Gerçek çıkış 01:00, personelle doğrulandı")
    assert s.pending_reviews(token) == 0
    r = build_report(s, token, date(2026, 10, 20), date(2026, 10, 20))
    assert r["summary"][0]["seconds"] == 8 * 3600
    assert not inspect_database(s.db.path)


def test_stale_editor_cannot_overwrite_a_flagged_record(system):
    s, c, _, eid = system
    move_to(c, "2026-10-20T17:00")
    sid = s.attendance(eid, PIN, "start", None, uid())
    token = admin(s)
    stale = next(r for r in s.sessions(token) if r["id"] == sid)
    move_to(c, "2026-10-21T06:00")
    s.tick()
    token = admin(s)
    with pytest.raises(AppError, match="değişmiş"):
        s.correct_session(token, sid, stale["revision"], stale["start_at"], ts("2026-10-21T01:00"),
                          "Eski ekrandan düzeltme")


def test_after_midnight_start_still_open_at_boundary_is_flagged(system):
    s, c, _, eid = system
    move_to(c, "2026-10-21T00:30")
    sid = s.attendance(eid, PIN, "start", None, uid())
    move_to(c, "2026-10-21T04:00")
    s.tick()
    token = admin(s)
    assert next(r for r in s.sessions(token) if r["id"] == sid)["review"] == ""
    move_to(c, "2026-10-21T05:30")
    s.tick()
    token = admin(s)
    assert next(r for r in s.sessions(token) if r["id"] == sid)["review"] == FORGOTTEN_EXIT


def test_normal_shift_is_never_flagged(system):
    s, c, _, eid = system
    move_to(c, "2026-10-20T17:00")
    sid = s.attendance(eid, PIN, "start", None, uid())
    move_to(c, "2026-10-21T01:00")
    s.attendance(eid, PIN, "end", sid, uid())
    move_to(c, "2026-10-21T10:00")
    s.tick()
    token = admin(s)
    assert s.pending_reviews(token) == 0
