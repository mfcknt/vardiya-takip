"""Ó'is visual identity: colour tokens, Turkish text helpers and the Qt stylesheet.

Qt-free on purpose so it can be unit-tested anywhere. The palette is derived
from the café logo: bordo #3a0300 and a warm cream; status colours are muted
so they sit with the brand (sage = inside, honey = attention, rose = locked).
"""
from datetime import datetime

DEFAULT_THEME = "dark"

THEMES = {
    "dark": {
        "name": "dark",
        "bg": "#170504", "surface": "#220908", "surface2": "#2c0e0c", "line": "#43201c",
        "line_soft": "#2f110f", "watermark": "#240a08",
        "text": "#f6ece3", "muted": "#b39a90", "faint": "#7d655d",
        "ring": "#f6ece3", "ring_track": "#3a1512", "ring_idle": "#4a2420",
        "brand": "#3a0300", "on_brand": "#f6ece3", "primary": "#f6ece3", "on_primary": "#2a0605",
        "inside": "#9cc7a4", "inside_soft": "#1f3326",
        "warn": "#e2a84b", "warn_text": "#f2c879", "warn_soft": "#3a2a12",
        "lock": "#e58b86", "lock_soft": "#3d1716",
        "done": "#c9a99a", "selection": "#3a1714", "input": "#2a0d0b",
    },
    "night": {
        "name": "night",
        "bg": "#0f0f10", "surface": "#17171a", "surface2": "#1f1f23", "line": "#2e2e34",
        "line_soft": "#222226", "watermark": "#18181b",
        "text": "#f3ede6", "muted": "#a39d97", "faint": "#6f6a66",
        "ring": "#f6ece3", "ring_track": "#2a2a2f", "ring_idle": "#3b3b41",
        "brand": "#3a0300", "on_brand": "#f6ece3", "primary": "#f6ece3", "on_primary": "#3a0300",
        "inside": "#9cc7a4", "inside_soft": "#1b2a20",
        "warn": "#e2a84b", "warn_text": "#f2c879", "warn_soft": "#2d2412",
        "lock": "#e58b86", "lock_soft": "#331a1a",
        "done": "#b5aaa2", "selection": "#2b1715", "input": "#1a1a1e",
    },
    "light": {
        "name": "light",
        "bg": "#f7efe6", "surface": "#fffaf4", "surface2": "#efe3d6", "line": "#cdb8a6",
        "line_soft": "#e4d5c7", "watermark": "#efe3d6",
        "text": "#2a0f0c", "muted": "#6b5850", "faint": "#8f7c73",
        "ring": "#3a0300", "ring_track": "#e0cfbf", "ring_idle": "#b9a190",
        "brand": "#3a0300", "on_brand": "#f6ece3", "primary": "#3a0300", "on_primary": "#f6ece3",
        "inside": "#2e7a4d", "inside_soft": "#e1f0e6",
        "warn": "#a8640c", "warn_text": "#8a520a", "warn_soft": "#fbecd6",
        "lock": "#a3302b", "lock_soft": "#f8e1df",
        "done": "#8a6a5e", "selection": "#efe1d4", "input": "#ffffff",
    },
}

THEME_LABELS = {"dark": "koyu · bordo gece", "night": "gece siyahı", "light": "açık · krem kâğıt"}

SHIFT_GOAL_SECONDS = 8 * 3600     # the ring is full after 8 hours

DAYS = ["pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar"]
SHORT_DAYS = ["pzt", "sal", "çar", "per", "cum", "cmt", "paz"]
MONTHS = ["ocak", "şubat", "mart", "nisan", "mayıs", "haziran", "temmuz", "ağustos", "eylül",
          "ekim", "kasım", "aralık"]


def tokens(name):
    return THEMES.get(name, THEMES[DEFAULT_THEME])


def tr_lower(text):
    """Turkish-aware lowercase (I → ı, İ → i)."""
    return text.replace("I", "ı").replace("İ", "i").lower()


def tr_upper(text):
    return text.replace("i", "İ").replace("ı", "I").upper()


def initials(name):
    parts = [p for p in name.split() if p[:1].isalpha()]
    if not parts:
        return tr_lower(name[:2]) or "?"
    letters = parts[0][0] + (parts[-1][0] if len(parts) > 1 else parts[0][1:2])
    return tr_lower(letters)


def short_names(employees):
    """{id: label}: lowercase first name, plus surname initial when first names clash."""
    first = {}
    for e in employees:
        first.setdefault(tr_lower(e["name"].split()[0]) if e["name"].split() else "?", []).append(e)
    labels = {}
    for key, group in first.items():
        for e in group:
            parts = e["name"].split()
            if len(group) > 1 and len(parts) > 1:
                labels[e["id"]] = f"{key} {tr_lower(parts[-1][0])}."
            else:
                labels[e["id"]] = key
    return labels


def clock_text(seconds):
    """4:12 style elapsed time (hours:minutes)."""
    seconds = max(0, int(seconds))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}"


def hours_text(seconds):
    """"92 sa 30 dk", "8 sa", "45 dk" (no seconds; "s" would read as saniye)."""
    hours, minutes = divmod(max(0, int(seconds)) // 60, 60)
    if hours and minutes:
        return f"{hours} sa {minutes} dk"
    return f"{hours} sa" if hours else f"{minutes} dk"


def greeting(local: datetime, business_day):
    """Plain date line: 'salı, 20 ekim' (the business day, so 00:30 still shows the night's day)."""
    return f"{DAYS[business_day.weekday()]}, {business_day.day} {MONTHS[business_day.month - 1]}"


def stylesheet(t):
    """Global Qt stylesheet for one token set."""
    return f"""
* {{ font-family: "Quicksand", "Segoe UI", "Helvetica Neue", Arial; }}
QWidget {{ font-size: 15px; color: {t['text']}; }}
QMainWindow, QDialog, QStackedWidget, QStackedWidget > QWidget, QScrollArea, QScrollArea > QWidget > QWidget
    {{ background: {t['bg']}; }}
QToolTip {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['line']}; padding: 6px; }}
QLabel {{ background: transparent; }}
QLabel#display {{ font-family: "Jost"; font-weight: 200; font-size: 68px; letter-spacing: 3px; }}
QLabel#title {{ font-family: "Jost"; font-weight: 300; font-size: 30px; letter-spacing: 1px; }}
QLabel#h2 {{ font-family: "Jost"; font-weight: 400; font-size: 20px; }}
QLabel#subtitle {{ color: {t['muted']}; font-size: 14px; }}
QLabel#faint {{ color: {t['faint']}; font-size: 13px; }}
QLabel#eyebrow {{ color: {t['muted']}; font-size: 12px; letter-spacing: 2px; }}
QLabel#warning {{ background: {t['warn_soft']}; color: {t['warn_text']}; padding: 12px 16px;
                  border-radius: 14px; }}
QLabel#success {{ background: {t['inside_soft']}; color: {t['inside']}; padding: 12px 16px;
                  border-radius: 14px; }}
QLabel#status {{ color: {t['muted']}; font-size: 14px; }}
QLabel#insideCount {{ color: {t['inside']}; font-family: "Jost"; font-size: 22px; font-weight: 400; }}
QLabel#note {{ background: {t['surface2']}; color: {t['muted']}; padding: 12px 16px; border-radius: 14px; }}
QLabel#tileValue {{ font-family: "Jost"; font-weight: 300; font-size: 34px; }}
QLabel#tileValueWarn {{ font-family: "Jost"; font-weight: 300; font-size: 34px; color: {t['warn_text']}; }}
QLabel#welcomeTitle {{ font-family: "Jost"; font-weight: 200; font-size: 42px; }}
QLabel#welcomeSub {{ color: {t['muted']}; font-size: 17px; }}
QPushButton {{ min-height: 44px; padding: 4px 18px; border-radius: 22px; background: transparent;
               border: 1px solid {t['line']}; color: {t['text']}; font-weight: 500; }}
QPushButton:hover {{ border-color: {t['muted']}; }}
QPushButton:pressed {{ background: {t['selection']}; }}
QPushButton:disabled {{ color: {t['faint']}; border-color: {t['line_soft']}; }}
QPushButton#primary {{ background: {t['primary']}; color: {t['on_primary']}; border: none; }}
QPushButton#primary:hover {{ background: {t['muted']}; }}
QPushButton#danger {{ color: {t['lock']}; border-color: {t['lock']}; }}
QPushButton#ghost {{ border: none; color: {t['muted']}; min-height: 36px; padding: 2px 10px; }}
QPushButton#ghost:hover {{ color: {t['text']}; }}
QPushButton#key {{ min-width: 74px; min-height: 74px; max-width: 74px; max-height: 74px; padding: 0;
                   border-radius: 38px; font-family: "Jost"; font-size: 28px; font-weight: 300; }}
QPushButton#keyText {{ min-width: 74px; min-height: 74px; max-width: 74px; max-height: 74px; padding: 0;
                       border-radius: 38px; border: none; color: {t['muted']}; font-size: 13px; }}
QPushButton#chip {{ min-height: 34px; padding: 2px 16px; border-radius: 17px; }}
QPushButton#chip:checked {{ background: {t['primary']}; color: {t['on_primary']}; border: none; }}
QLineEdit, QComboBox, QDateEdit, QDateTimeEdit {{ background: {t['input']}; color: {t['text']};
    border: 1px solid {t['line']}; padding: 8px 12px; min-height: 28px; border-radius: 12px;
    selection-background-color: {t['selection']}; selection-color: {t['text']}; }}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QDateTimeEdit:focus {{ border-color: {t['muted']}; }}
QLineEdit#search {{ border-radius: 20px; padding-left: 16px; background: {t['surface']}; }}
QLineEdit#pin {{ border: none; background: transparent; color: transparent; min-height: 2px;
                 max-height: 2px; padding: 0; selection-background-color: transparent; }}
QComboBox::drop-down, QDateEdit::drop-down, QDateTimeEdit::drop-down {{ border: none; width: 28px;
    background: transparent; }}
QComboBox QAbstractItemView {{ background: {t['surface']}; color: {t['text']};
                               selection-background-color: {t['selection']}; border: 1px solid {t['line']}; }}
QCalendarWidget QWidget {{ background: {t['surface']}; color: {t['text']}; }}
QCheckBox {{ min-height: 36px; color: {t['text']}; background: transparent; spacing: 10px; }}
QCheckBox::indicator {{ width: 22px; height: 22px; border-radius: 7px; border: 1px solid {t['line']};
                        background: {t['input']}; }}
QCheckBox::indicator:checked {{ background: {t['primary']}; border-color: {t['primary']}; }}
QListWidget#nav {{ background: transparent; border: none; padding: 0; outline: 0; }}
QListWidget#nav::item {{ padding: 12px 14px; margin: 2px 0; border-radius: 12px; color: {t['muted']}; }}
QListWidget#nav::item:selected {{ background: {t['selection']}; color: {t['text']}; }}
QListWidget#nav::item:hover {{ color: {t['text']}; }}
QFrame#navPane {{ background: {t['surface']}; border-right: 1px solid {t['line_soft']}; }}
QFrame#tile {{ background: {t['surface']}; border: 1px solid {t['line_soft']}; border-radius: 16px; }}
QFrame#tileWarn {{ background: {t['surface']}; border: 1px solid {t['warn']}; border-radius: 16px; }}
QFrame#panel {{ background: {t['surface']}; border: 1px solid {t['line_soft']}; border-radius: 18px; }}
QTableWidget {{ background: {t['surface']}; alternate-background-color: {t['surface']};
                border: 1px solid {t['line_soft']}; border-radius: 16px; gridline-color: transparent;
                selection-background-color: {t['selection']}; selection-color: {t['text']}; outline: 0; }}
QTableWidget::item {{ border-bottom: 1px solid {t['line_soft']}; padding: 6px 10px; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: {t['surface']}; color: {t['faint']}; padding: 12px 10px; border: none;
                        border-bottom: 1px solid {t['line']}; font-size: 12px; font-weight: 500; }}
QTableCornerButton::section {{ background: {t['surface']}; border: none; }}
QScrollBar:vertical {{ width: 12px; background: transparent; margin: 4px; }}
QScrollBar::handle:vertical {{ background: {t['line']}; border-radius: 4px; min-height: 40px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ height: 12px; background: transparent; margin: 4px; }}
QScrollBar::handle:horizontal {{ background: {t['line']}; border-radius: 4px; min-width: 40px; }}
QMessageBox {{ background: {t['bg']}; }}
QDialogButtonBox QPushButton {{ min-width: 110px; }}
"""
