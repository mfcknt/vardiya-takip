"""Qt-free identity helpers: Turkish casing, names, greetings, stylesheet."""
from datetime import date, datetime

from vardiya import theme as th


def test_turkish_lowercase_and_initials():
    assert th.tr_lower("IŞIK İnci") == "ışık inci"
    assert th.tr_upper("ışık inci") == "IŞIK İNCİ"
    assert th.initials("Ayşe Yılmaz") == "ay"
    assert th.initials("İlker Işık") == "iı"
    assert th.initials("Can") == "ca"
    assert th.initials("") == "?"


def test_short_names_disambiguate_same_first_name():
    people = [{"id": 1, "name": "Ayşe Yılmaz"}, {"id": 2, "name": "Ayşe Demir"}, {"id": 3, "name": "Can Arslan"}]
    assert th.short_names(people) == {1: "ayşe y.", 2: "ayşe d.", 3: "can"}


def test_time_texts():
    assert th.clock_text(4 * 3600 + 12 * 60 + 59) == "4:12"
    assert th.clock_text(-5) == "0:00"
    assert th.hours_text(6 * 3600) == "6 sa"
    assert th.hours_text(7 * 3600 + 30 * 60) == "7 sa 30 dk"
    assert th.hours_text(92 * 3600 + 30 * 60 + 59) == "92 sa 30 dk"
    assert th.hours_text(45 * 60) == "45 dk"


def test_greeting_uses_business_day_and_phase():
    tuesday = date(2026, 10, 20)
    assert th.greeting(datetime(2026, 10, 20, 21, 42), tuesday) == "salı, 20 ekim"
    assert th.greeting(datetime(2026, 10, 21, 0, 30), tuesday) == "salı, 20 ekim"   # still that night


def test_themes_share_keys_and_stylesheet_builds():
    dark, night, light = th.THEMES["dark"], th.THEMES["night"], th.THEMES["light"]
    assert dark.keys() == light.keys() == night.keys()
    assert dark["brand"] == light["brand"] == night["brand"] == "#3a0300"   # the logo colour
    assert set(th.THEME_LABELS) == set(th.THEMES)
    for t in (dark, night, light):
        css = th.stylesheet(t)
        assert t["bg"] in css and "Jost" in css and "Quicksand" in css
    assert th.tokens("nope") is th.THEMES[th.DEFAULT_THEME]
