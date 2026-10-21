"""Qt-free date periods for the admin filters: presets, day stepping and captions.

`today` is always a business day (see Service.business_day), never a calendar date.
"""
from datetime import date, timedelta

from .theme import MONTHS

# (key, chip text) in the order the chips are shown; "custom" has no fixed range.
PRESETS = [("today", "bugün"), ("yesterday", "dün"), ("this_week", "bu hafta"),
           ("last_week", "geçen hafta"), ("this_month", "bu ay"), ("last_month", "geçen ay"),
           ("custom", "özel")]
DEFAULT_PRESET = "this_month"


def preset_range(key, today: date):
    """(first, last) for a preset; ranges never reach past `today`. Weeks start on Monday."""
    if key == "today":
        return today, today
    if key == "yesterday":
        day = today - timedelta(days=1)
        return day, day
    if key == "this_week":
        return today - timedelta(days=today.weekday()), today
    if key == "last_week":
        monday = today - timedelta(days=today.weekday() + 7)
        return monday, monday + timedelta(days=6)
    if key == "this_month":
        return today.replace(day=1), today
    if key == "last_month":
        last = today.replace(day=1) - timedelta(days=1)
        return last.replace(day=1), last
    raise ValueError(key)


def matching_preset(first: date, last: date, today: date):
    """The preset that produces exactly this range, else None."""
    for key, _ in PRESETS[:-1]:
        if preset_range(key, today) == (first, last):
            return key
    return None


def step_day(last: date, delta: int, today: date):
    """The single day before/after `last`, never later than `today`."""
    return min(last + timedelta(days=delta), today)


def caption(first: date, last: date):
    """Short description of a range: "ekim 2026 · 21 gün", "20.10.2026 · 1 gün"."""
    days = (last - first).days + 1
    if first == last:
        return f"{first:%d.%m.%Y} · 1 gün"
    if first.day == 1 and (first.year, first.month) == (last.year, last.month):
        return f"{MONTHS[first.month - 1]} {first.year} · {days} gün"
    return f"{days} gün"
