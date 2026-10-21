"""Render the main screens with sample data to PNG files (for review and docs).

Usage: python scripts/screenshots.py <output-dir>
Uses a temporary data folder and a fixed clock (Tuesday 20 Oct 2026, 21:42).
Sample names and amounts are fictional.
"""
import os
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VARDIYA_ANIMATIONS", "0")   # capture final frames, not mid-animation

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from vardiya.security import AppError  # noqa: E402
from vardiya.service import Service  # noqa: E402
from vardiya.storage import Database  # noqa: E402
from vardiya.ui import AdminDialog, MainWindow, PinDialog, apply_theme  # noqa: E402
from vardiya.widgets import WelcomeDialog  # noqa: E402

ZONE = ZoneInfo("Europe/Istanbul")
PASSWORD = "3917"


def ts(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=ZONE).timestamp())


class Clock:
    def __init__(self, now):
        self.now, self.mono = now, 1000.0

    def wall(self):
        return self.now

    def monotonic(self):
        return self.mono


def seed(service, clock):
    service.setup(PASSWORD)
    token = service.login_admin(PASSWORD)
    staff = {}
    for name, pin, rate in [("Ayşe Yılmaz", "4829", 15000), ("Can Arslan", "5738", 14000),
                            ("Zeynep Aydın", "6849", 15000), ("Elif Demir", "7950", 13500),
                            ("Mehmet Kaya", "8061", 14000), ("Ece Çelik", "9172", 13000),
                            ("Burak Şahin", "1283", 14500)]:
        staff[name.split()[0]] = service.add_employee(token, name, pin, rate)

    def shift(who, start, end, note="Örnek vardiya"):
        service.manual_session(token, staff[who], ts(start), ts(end) if end else None, 15000, note,
                               str(uuid.uuid4()))

    for day in range(14, 20):
        d = f"2026-10-{day:02d}"
        shift("Ayşe", f"{d}T16:30", f"2026-10-{day + 1:02d}T01:00" if day % 2 else f"{d}T23:30")
        shift("Can", f"{d}T09:00", f"{d}T15:00" if day % 3 else f"{d}T17:30")
        if day != 16:
            shift("Zeynep", f"{d}T12:00", f"{d}T20:00")
        if day % 2 == 0:
            shift("Mehmet", f"{d}T09:00", f"{d}T13:00")
            shift("Ece", f"{d}T18:00", f"2026-10-{day + 1:02d}T00:30")
        if day in (15, 17, 18):
            shift("Burak", f"{d}T10:00", f"{d}T18:00")
        if day in (14, 17, 18):
            shift("Elif", f"{d}T17:00", f"{d}T23:00")
    shift("Can", "2026-10-20T09:00", "2026-10-20T15:00")
    shift("Mehmet", "2026-10-20T09:30", "2026-10-20T13:30")
    shift("Elif", "2026-10-19T17:00", None, "Açık kalan kayıt")       # forgotten exit
    shift("Ayşe", "2026-10-20T17:30", None, "Akşam vardiyası")
    shift("Zeynep", "2026-10-20T20:12", None, "Akşam vardiyası")
    service.add_payment(token, staff["Ayşe"], ts("2026-10-15T23:00"), 200000, "Avans", "Haftalık avans",
                        str(uuid.uuid4()))
    service.tick()                                   # flags Elif's open record
    for _ in range(5):                               # Mehmet mistyped his PIN
        try:
            service.attendance(staff["Mehmet"], "1112", "start", None, str(uuid.uuid4()))
        except AppError:
            pass
    clock.now += 20
    return staff


def grab(widget, path, size=None):
    if size:
        widget.resize(*size)
    widget.show()
    for _ in range(5):
        QApplication.processEvents()
    widget.grab().save(str(path))
    print("saved", path)


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv[:1])
    apply_theme(app, "dark")

    def fail_on_modal():
        widget = app.activeModalWidget()
        if widget is not None:
            text = widget.text() if hasattr(widget, "text") else widget.windowTitle()
            print("Beklenmeyen modal pencere:", text, flush=True)
            os._exit(3)
    watchdog = QTimer()
    watchdog.timeout.connect(fail_on_modal)
    watchdog.start(1000)
    data = Path(tempfile.mkdtemp())
    clock = Clock(ts("2026-10-20T21:42"))
    db = Database(data / "vardiya.sqlite3")
    service = Service(db, clock)
    seed(service, clock)
    for theme in ("dark", "night", "light"):
        token = service.login_admin(PASSWORD)
        service.set_theme(token, theme)
        apply_theme(app, theme)
        window = MainWindow(service)
        grab(window, out / f"kiosk-{theme}.png", (1280, 800))
        person = next(e for e in service.kiosk_employees() if e["name"].startswith("Ayşe"))
        pin = PinDialog(service, person, window)
        for digit in "48":
            pin.press(digit)
        grab(pin, out / f"pin-{theme}.png")
        pin.reject()
        welcome = WelcomeDialog("ca", "in", "hoş geldin, can", "giriş 21:42 · bu ay 92s 30dk",
                                "şapka yandı, iyi servisler", window, timeout_ms=60_000)
        grab(welcome, out / f"welcome-{theme}.png")
        welcome.reject()
        token = service.login_admin(PASSWORD)
        panel = AdminDialog(service, token, window)
        pages = ["today", "people", "sessions", "report", "payments", "settings"]
        for index, page in enumerate(pages):
            if theme != "dark" and page not in ("today", "sessions"):
                continue
            panel.nav.setCurrentRow(index)
            grab(panel, out / f"admin-{page}-{theme}.png", (1280, 860))
        panel.reject()
        window.close()
    db.close()
    QTimer.singleShot(0, app.quit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "screenshots"))
