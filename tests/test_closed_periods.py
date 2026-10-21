"""Closing months: locked records, sequential reopen, and reports that start from closing balances."""
import json
import uuid
from datetime import date

import pytest

from conftest import PASSWORD, PIN, ts
from vardiya.reports import build_report
from vardiya.security import AppError
from vardiya.storage import inspect_database


def uid():
    return str(uuid.uuid4())


def work(s, token, eid, start, end):
    return s.manual_session(token, eid, ts(start), ts(end), 15000, "Kayıt eklendi", uid())


@pytest.fixture
def history(system):
    """August and September work, a session over the 05:00 boundary into 1 October, payments."""
    s, c, token, eid = system
    other = s.add_employee(token, "Can Arslan", "5738", 12000)
    work(s, token, eid, "2026-08-14T09:00", "2026-08-14T17:30")
    work(s, token, other, "2026-09-10T10:00", "2026-09-10T18:00")
    crossing = work(s, token, eid, "2026-09-30T22:00", "2026-10-01T06:15")
    work(s, token, eid, "2026-10-12T09:00", "2026-10-12T15:00")
    s.add_payment(token, eid, ts("2026-09-15T12:00"), 50000, "Avans", "Eylül avansı", uid())
    s.add_payment(token, other, ts("2026-10-05T12:00"), 30000, "Ödeme", "Ekim ödemesi", uid())
    return s, c, token, eid, other, crossing


def summaries(s, token, first, last, **kw):
    report = build_report(s, token, first, last, **kw)
    return [(r["employee_id"], r["seconds"], r["cents"], r["paid_cents"], r["carry_cents"], r["balance_cents"])
            for r in report["summary"]]


def test_only_finished_months_with_records_can_be_closed(history):
    s, c, token, *_ = history
    assert s.closable_months(token) == ["2026-08", "2026-09"]
    with pytest.raises(AppError, match="kapatılamaz"):
        s.close_period(token, "2026-10")             # still running
    s.close_period(token, "2026-08")
    assert s.closable_months(token) == ["2026-09"]
    with pytest.raises(AppError, match="kapatılamaz"):
        s.close_period(token, "2026-08")


def test_open_or_unreviewed_records_block_closing(system):
    s, c, token, eid = system
    c.advance(ts("2026-09-30T20:00") - c.now)
    sid = s.attendance(eid, PIN, "start", None, uid())
    c.advance(ts("2026-10-20T12:00") - c.now)
    s.tick()                                          # flags the forgotten exit
    with pytest.raises(AppError, match="çıkışı yapılmamış 1 kayıt"):
        s.close_period(token, "2026-09")
    row = next(r for r in s.sessions(token) if r["id"] == sid)
    s.correct_session(token, sid, row["revision"], row["start_at"], ts("2026-09-30T23:00"), "Çıkış girildi")
    s.db.conn.execute("UPDATE sessions SET review='kontrol et' WHERE id=?", (sid,))
    with pytest.raises(AppError, match="inceleme bekleyen 1 kayıt"):
        s.close_period(token, "2026-09")


def test_closed_months_cannot_be_changed(history):
    s, c, token, eid, other, crossing = history
    s.close_period(token, "2026-09")
    september = next(r for r in s.sessions(token) if r["employee_id"] == other)
    october = next(r for r in s.sessions(token) if r["start_at"] == ts("2026-10-12T09:00"))
    payment = next(p for p in s.payments(token) if p["paid_at"] == ts("2026-09-15T12:00"))
    attempts = [
        lambda: work(s, token, other, "2026-09-11T10:00", "2026-09-11T12:00"),
        lambda: s.correct_session(token, september["id"], september["revision"], september["start_at"],
                                  september["end_at"] - 600, "Düzeltme"),
        lambda: s.correct_session(token, september["id"], september["revision"], 0, 0, "İptal", void=True),
        lambda: s.correct_session(token, october["id"], october["revision"], ts("2026-09-29T09:00"),
                                  ts("2026-09-29T15:00"), "Eyüle taşı"),
        lambda: s.add_payment(token, eid, ts("2026-09-20T12:00"), 1000, "Avans", "Geç avans", uid()),
        lambda: s.void_payment(token, payment["id"], "İptal"),
    ]
    for attempt in attempts:
        with pytest.raises(AppError, match="eylül 2026 ve öncesi kapalı dönem"):
            attempt()
    s.correct_session(token, october["id"], october["revision"], october["start_at"],
                      october["end_at"] - 600, "Ekim düzeltmesi")
    s.add_payment(token, eid, ts("2026-10-15T12:00"), 1000, "Avans", "Ekim avansı", uid())
    assert not inspect_database(s.db.path)


def test_reports_after_the_closed_month_match_a_full_recalculation(history):
    s, c, token, *_ = history
    october = (date(2026, 10, 1), date(2026, 10, 20))
    full = summaries(s, token, *october, use_closed=False)
    s.close_period(token, "2026-09")
    assert summaries(s, token, *october) == full
    assert summaries(s, token, date(2026, 10, 1), date(2026, 10, 1)) == \
        summaries(s, token, date(2026, 10, 1), date(2026, 10, 1), use_closed=False)
    # The 1 October part of the crossing session (05:00–06:15) belongs to October.
    first = build_report(s, token, date(2026, 10, 1), date(2026, 10, 1))
    assert [r["seconds"] for r in first["summary"] if r["seconds"]] == [75 * 60]
    # Ranges that include closed months are still computed from all records.
    assert summaries(s, token, date(2026, 9, 1), date(2026, 10, 20)) == \
        summaries(s, token, date(2026, 9, 1), date(2026, 10, 20), use_closed=False)


def test_reopen_needs_the_admin_code_and_goes_back_one_month(history):
    s, c, token, eid, other, crossing = history
    s.close_period(token, "2026-08")
    s.close_period(token, "2026-09")
    with pytest.raises(AppError):
        s.reopen_period(token, "0000", "Yanlış kod")
    s.reopen_period(token, PASSWORD, "Eylül avansı yanlış girilmiş")
    assert s.closed_month == "2026-08"
    payment = next(p for p in s.payments(token) if p["paid_at"] == ts("2026-09-15T12:00"))
    s.void_payment(token, payment["id"], "Yanlış tutar")
    with pytest.raises(AppError, match="ağustos 2026"):
        work(s, token, eid, "2026-08-20T09:00", "2026-08-20T10:00")
    s.reopen_period(token, PASSWORD, "Tümü açılsın")
    assert s.closed_month is None and s.closed_state() is None
    work(s, token, eid, "2026-08-20T09:00", "2026-08-20T10:00")
    actions = [r[0] for r in s.db.conn.execute("SELECT action FROM audit WHERE entity='period' ORDER BY id")]
    assert actions == ["PERIOD_CLOSE", "PERIOD_CLOSE", "PERIOD_REOPEN", "PERIOD_REOPEN"]
    assert not inspect_database(s.db.path)


def test_day_start_change_recomputes_closing_balances(history):
    s, c, token, *_ = history
    s.close_period(token, "2026-09")
    s.set_day_start(token, 7, "Kapanış saati değişti")
    october = (date(2026, 10, 1), date(2026, 10, 20))
    assert summaries(s, token, *october) == summaries(s, token, *october, use_closed=False)
    assert s.closed_month == "2026-09" and not inspect_database(s.db.path)


def test_tampered_closing_balances_are_detected(history):
    s, c, token, eid, *_ = history
    s.close_period(token, "2026-09")
    state = s.closed_state()
    state["balances"][str(eid)] += 100000
    s.db.conn.execute("UPDATE meta SET value=? WHERE key='closed_period'", (json.dumps(state),))
    assert "Kapalı dönem bilgisi işlem geçmişiyle uyuşmuyor." in inspect_database(s.db.path)
