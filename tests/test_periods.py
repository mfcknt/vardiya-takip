"""Admin filter periods: presets, day stepping and captions (Qt-free)."""
import uuid
from datetime import date

import pytest

from vardiya.periods import PRESETS, caption, matching_preset, preset_range, step_day
from vardiya.reports import build_report

TODAY = date(2026, 10, 21)            # a Wednesday


@pytest.mark.parametrize("key, first, last", [
    ("today", "2026-10-21", "2026-10-21"),
    ("yesterday", "2026-10-20", "2026-10-20"),
    ("this_week", "2026-10-19", "2026-10-21"),
    ("last_week", "2026-10-12", "2026-10-18"),
    ("this_month", "2026-10-01", "2026-10-21"),
    ("last_month", "2026-09-01", "2026-09-30"),
])
def test_presets(key, first, last):
    assert preset_range(key, TODAY) == (date.fromisoformat(first), date.fromisoformat(last))


def test_presets_across_year_and_month_edges():
    assert preset_range("last_month", date(2026, 1, 15)) == (date(2025, 12, 1), date(2025, 12, 31))
    assert preset_range("last_month", date(2028, 3, 1)) == (date(2028, 2, 1), date(2028, 2, 29))
    assert preset_range("yesterday", date(2027, 1, 1)) == (date(2026, 12, 31),) * 2
    monday = date(2026, 10, 19)
    assert preset_range("this_week", monday) == (monday, monday)
    assert preset_range("last_week", date(2027, 1, 3)) == (date(2026, 12, 21), date(2026, 12, 27))
    with pytest.raises(ValueError):
        preset_range("custom", TODAY)
    assert [key for key, _ in PRESETS][-1] == "custom"


def test_day_steps_go_back_one_day_at_a_time_and_stop_at_today():
    assert step_day(TODAY, -1, TODAY) == date(2026, 10, 20)
    assert step_day(date(2026, 10, 1), -1, TODAY) == date(2026, 9, 30)
    assert step_day(date(2026, 10, 20), 1, TODAY) == TODAY
    assert step_day(TODAY, 1, TODAY) == TODAY


def test_matching_preset_and_caption():
    assert matching_preset(TODAY, TODAY, TODAY) == "today"
    assert matching_preset(date(2026, 10, 20), date(2026, 10, 20), TODAY) == "yesterday"
    assert matching_preset(date(2026, 9, 1), date(2026, 9, 30), TODAY) == "last_month"
    assert matching_preset(date(2026, 10, 19), TODAY, TODAY) == "this_week"
    assert matching_preset(date(2026, 10, 5), date(2026, 10, 9), TODAY) is None
    assert caption(date(2026, 10, 1), TODAY) == "ekim 2026 · 21 gün"
    assert caption(TODAY, TODAY) == "21.10.2026 · 1 gün"
    assert caption(date(2026, 10, 5), date(2026, 10, 9)) == "5 gün"


def test_report_for_one_employee(system):
    s, c, token, eid = system
    other = s.add_employee(token, "Can Arslan", "5738", 12000)
    for person in (eid, other):
        s.manual_session(token, person, c.now - 3600, c.now, 15000, "Kayıt eklendi", str(uuid.uuid4()))
    day = date.fromisoformat("2026-10-20")
    everyone = build_report(s, token, day, day)
    one = build_report(s, token, day, day, other)
    assert len(everyone["summary"]) == 2
    assert [r["employee_id"] for r in one["summary"]] == [other]
    assert {r["employee_id"] for r in one["days"] + one["sessions"]} == {other}
    assert one["summary"][0] == next(r for r in everyone["summary"] if r["employee_id"] == other)
