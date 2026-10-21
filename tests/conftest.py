import os
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from vardiya.service import Service
from vardiya.storage import Database

PASSWORD = "4826"
PIN = "4829"


class FakeClock:
    def __init__(self, now=1792486800):
        self.now = now
        self.mono = 100.0

    def wall(self):
        return self.now

    def monotonic(self):
        return self.mono

    def advance(self, seconds):
        self.now += seconds
        self.mono += seconds


def ts(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=ZoneInfo("Europe/Istanbul")).timestamp())


@pytest.fixture
def system(tmp_path):
    clock = FakeClock(ts("2026-10-20T12:00:00"))
    db = Database(tmp_path / "data" / "vardiya.sqlite3")
    service = Service(db, clock)
    service.setup(PASSWORD)
    token = service.login_admin(PASSWORD)
    eid = service.add_employee(token, "Ayşe Yılmaz", PIN, 15000)
    yield service, clock, token, eid
    db.close()


MODAL_SEEN = []
HANG_SECONDS = 90


@pytest.fixture(autouse=True)
def hang_watchdog(request):
    """If a test blocks (e.g. an unexpected modal exec), write which test and where,
    then stop the run so CI can report it instead of timing out silently."""
    import faulthandler
    import threading
    report = Path(os.environ.get("VARDIYA_HANG_REPORT", "hang-report.txt"))

    def fire():
        with report.open("w", encoding="utf-8") as f:
            f.write(f"Takılan test: {request.node.nodeid}\n")
            faulthandler.dump_traceback(file=f, all_threads=True)
        os._exit(3)
    timer = threading.Timer(HANG_SECONDS, fire)
    timer.daemon = True
    timer.start()
    yield
    timer.cancel()


@pytest.fixture(scope="session")
def qapp():
    """QApplication with a watchdog: an unexpected modal window (e.g. an error
    message box) would block an offscreen test run forever. The watchdog
    closes it and the per-test check below turns it into a readable failure."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox
    from vardiya.ui import apply_theme
    app = QApplication.instance() or QApplication([])
    apply_theme(app)

    def close_modals():
        widget = app.activeModalWidget()
        if isinstance(widget, QMessageBox):   # error/info boxes are never expected in tests
            MODAL_SEEN.append(f"{type(widget).__name__}: {widget.text()}")
            widget.reject()

    watchdog = QTimer()
    watchdog.timeout.connect(close_modals)
    watchdog.start(1500)
    app._vardiya_watchdog = watchdog
    yield app


@pytest.fixture(autouse=True)
def no_unexpected_modals():
    MODAL_SEEN.clear()
    yield
    # Close every window a test left behind so its timers cannot fire later
    # against a database that the `system` fixture has already closed.
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:          # core tests run without Qt installed
        return
    app = QApplication.instance()
    if app is not None:
        for widget in app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        app.processEvents()
    assert not MODAL_SEEN, "Beklenmeyen modal pencere: " + " | ".join(MODAL_SEEN)
