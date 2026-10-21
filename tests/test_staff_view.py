"""Staff self-view on the kiosk: own month only, after the PIN, without money."""
import uuid

import pytest

from conftest import PIN, ts
from vardiya.security import AppError


def test_staff_month_shows_days_hours_and_records_but_no_money(system):
    s, c, token, eid = system
    other = s.add_employee(token, "Can Arslan", "5738", 12000)
    for start, end in (("2026-10-05T09:00", "2026-10-05T17:00"), ("2026-10-06T09:00", "2026-10-06T12:30"),
                       ("2026-09-28T09:00", "2026-09-28T17:00")):
        s.manual_session(token, eid, ts(start), ts(end), 15000, "Kayıt", str(uuid.uuid4()))
    voided = s.manual_session(token, eid, ts("2026-10-07T09:00"), ts("2026-10-07T10:00"), 15000, "Yanlış",
                              str(uuid.uuid4()))
    row = next(r for r in s.sessions(token) if r["id"] == voided)
    s.correct_session(token, voided, row["revision"], 0, 0, "İptal", void=True)
    s.manual_session(token, other, ts("2026-10-05T09:00"), ts("2026-10-05T17:00"), 12000, "Kayıt", str(uuid.uuid4()))
    s.attendance(eid, PIN, "start", None, str(uuid.uuid4()))      # open since 12:00, now 13:00
    c.advance(3600)
    month = s.staff_month(eid, PIN)
    assert month["month"] == "2026-10" and month["days"] == 3
    assert month["seconds"] == 8 * 3600 + 3.5 * 3600 + 3600
    assert [r["end_at"] is None for r in month["records"]] == [True, False, False]
    assert not any("cents" in key for key in month) and not any("cents" in k for r in month["records"] for k in r)


def test_wrong_pin_counts_towards_the_lock(system):
    s, c, token, eid = system
    for _ in range(4):
        with pytest.raises(AppError, match="doğrulanamadı"):
            s.staff_month(eid, "0000")
    with pytest.raises(AppError, match="kilidi"):
        s.staff_month(eid, "0000")
