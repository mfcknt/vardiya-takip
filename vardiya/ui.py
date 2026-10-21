import logging
import sqlite3
import time
import uuid
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path

from PySide6.QtCore import QDate, QDateTime, QEvent, QRegularExpression, QSize, Qt, QTime, QTimer
from PySide6.QtGui import QColor, QIcon, QPalette, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateEdit, QDateTimeEdit, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QScroller, QStackedWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from . import periods
from . import theme as th
from .backup import automatic_backup, backup_usage, create_backup, restore_database
from .formatting import cents, tl
from .reports import build_report, export_audit, export_report
from .security import PIN_LENGTH, AppError
from .storage import inspect_database
from .widgets import (
    Backdrop, HeatmapWidget, Keypad, PersonRing, PinDots, RingWidget, StatTile, TimelineWidget, WelcomeDialog,
    app_icon, avatar_pixmap, current, font, load_fonts, logo_pixmap, set_current,
)

STYLE = th.stylesheet(th.tokens(th.DEFAULT_THEME))


def apply_theme(app, name=th.DEFAULT_THEME):
    """Apply one Ó'is theme to the whole application, independent of the OS theme."""
    load_fonts()
    t = th.tokens(name)
    set_current(t)
    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Light if t["name"] == "light" else Qt.ColorScheme.Dark)
    except AttributeError:
        pass  # Qt < 6.8
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: t["bg"], QPalette.ColorRole.WindowText: t["text"],
        QPalette.ColorRole.Base: t["input"], QPalette.ColorRole.AlternateBase: t["surface"],
        QPalette.ColorRole.Text: t["text"], QPalette.ColorRole.Button: t["surface"],
        QPalette.ColorRole.ButtonText: t["text"], QPalette.ColorRole.Highlight: t["selection"],
        QPalette.ColorRole.HighlightedText: t["text"], QPalette.ColorRole.ToolTipBase: t["surface"],
        QPalette.ColorRole.ToolTipText: t["text"], QPalette.ColorRole.PlaceholderText: t["faint"],
        QPalette.ColorRole.Link: t["ring"], QPalette.ColorRole.BrightText: t["text"],
    }
    for role, value in roles.items():
        palette.setColor(role, QColor(value))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(t["faint"]))
    app.setPalette(palette)
    app.setStyle("Fusion")
    app.setStyleSheet(th.stylesheet(t))
    app.setFont(font("Quicksand", 15))
    app.setWindowIcon(app_icon())
    for widget in app.topLevelWidgets():
        try:
            if not widget.isVisible():
                continue  # hidden or closing windows re-theme when shown again
            if hasattr(widget, "retheme"):
                widget.retheme()
            widget.update()
        except Exception:  # one broken window must not stop the others
            logging.exception("Tema uygulanamadı: %s", type(widget).__name__)


def apply_light_theme(app):
    """Backwards-compatible name: the light Ó'is theme."""
    apply_theme(app, "light")


def guarded(fn):
    @wraps(fn)
    def run(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except AppError as exc:
            QMessageBox.warning(self, "İşlem yapılamadı", str(exc))
        except (sqlite3.Error, OSError) as exc:
            logging.exception("Yerel veri işlemi başarısız")
            QMessageBox.critical(
                self, "Veri işlemi tamamlanamadı",
                "İşlemin sonucu doğrulanamadı. Tekrar denemeden önce kayıtları kontrol edin. "
                "Disk alanını ve veri klasörü erişimini inceleyin.\n\n" + str(exc),
            )
    return run


def button(text, callback, primary=False, danger=False, name=None):
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    elif primary:
        b.setObjectName("primary")
    elif danger:
        b.setObjectName("danger")
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.clicked.connect(callback)
    return b


def label(text, style=None):
    w = QLabel(text)
    w.setTextFormat(Qt.TextFormat.PlainText)
    w.setWordWrap(True)
    if style:
        w.setObjectName(style)
    return w


def secret_edit(max_length=128):
    field = QLineEdit()
    field.setEchoMode(QLineEdit.EchoMode.Password)
    field.setMaxLength(max_length)
    return field


def code_edit(placeholder="4 rakam"):
    """A masked field that accepts exactly the 4-digit codes used for staff and admin."""
    field = secret_edit(PIN_LENGTH)
    field.setValidator(QRegularExpressionValidator(QRegularExpression("[0-9]{0,%d}" % PIN_LENGTH)))
    field.setPlaceholderText(placeholder)
    return field


ACTION_NAMES = {
    "SETUP": "İlk kurulum", "CLOCK_ALERT": "Saat uyarısı", "CLOCK_NOTICE": "Saat bildirimi",
    "CLOCK_ACK": "Saat kontrol edildi", "AUTH_LOCK": "Giriş kilidi", "AUTH_UNLOCK": "Kilit kaldırıldı",
    "PASSWORD_CHANGE": "Şifre değişti", "EMPLOYEE_ADD": "Personel eklendi",
    "EMPLOYEE_UPDATE": "Personel düzenlendi", "START": "İşe başladı", "END": "İşi bitirdi",
    "SESSION_MANUAL": "Kayıt eklendi", "SESSION_CORRECT": "Kayıt düzeltildi",
    "SESSION_VOID": "Kayıt iptal", "PAYMENT_ADD": "Ödeme eklendi", "PAYMENT_VOID": "Ödeme iptal",
    "RESTORE": "Yedekten kurtarma", "SESSION_FLAG": "Çıkış unutuldu", "SETTING_CHANGE": "Ayar değişti",
    "SCHEMA_UPGRADE": "Veri şeması güncellendi",
}
AUDIT_SCREEN_LIMIT = 1000


# Audit actors/entities are stored as "admin", "staff:5", "session:32"...; screens show words.
AUDIT_NAMES = {"admin": "Yönetici", "system": "Sistem", "clock": "Saat", "theme": "Tema",
               "day_start_hour": "İş günü saati", "session": "Kayıt", "payment": "Ödeme",
               "schema": "Veri şeması"}


def action_name(code):
    return ACTION_NAMES.get(code, code)


def audit_party(value, names):
    """"staff:5"/"employee:5" → the person's name, "session:32" → "Kayıt 32", "system" → "Sistem"."""
    kind, _, number = value.partition(":")
    if kind in ("staff", "employee") and number.isdigit():
        return names.get(int(number), f"Personel {number}")
    word = AUDIT_NAMES.get(kind, kind)
    return f"{word} {number}" if number else word


def lock_seconds(service, locked_until):
    return max(0, (locked_until or 0) - service.clock.wall())


def lock_text(service, locked_until):
    remaining = lock_seconds(service, locked_until)
    if remaining <= 0:
        return ""
    minutes, seconds = divmod(remaining, 60)
    return f"Kilitli · {minutes} dk {seconds} sn" if minutes else f"Kilitli · {seconds} sn"


def make_table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels([th.tr_lower(h) for h in headers])
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    t.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setShowGrid(False)
    t.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    t.setIconSize(QSize(30, 30))
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(54)
    t.setMinimumHeight(260)
    header = t.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setStretchLastSection(True)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header.setHighlightSections(False)
    t.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
    QScroller.grabGesture(t.viewport(), QScroller.ScrollerGestureType.TouchGesture)
    return t


def fill_table(table, rows, avatars=None, avatar_col=1):
    """rows: list of cell values; avatars: optional [(letters, state)] per row for `avatar_col`."""
    table.setRowCount(len(rows))
    ratio = table.devicePixelRatioF() if hasattr(table, "devicePixelRatioF") else 1.0
    for y, row in enumerate(rows):
        for x, value in enumerate(row):
            item = QTableWidgetItem(str(value))
            if avatars and x == avatar_col:
                letters, state = avatars[y]
                item.setIcon(QIcon(avatar_pixmap(letters, state, 30, ratio)))
            table.setItem(y, x, item)


def page_header(title, subtitle=""):
    box = QVBoxLayout()
    box.setSpacing(2)
    head = label(title, "title")
    box.addWidget(head)
    sub = label(subtitle, "subtitle")
    box.addWidget(sub)
    return box, head, sub


def panel(title=None):
    frame = QFrame()
    frame.setObjectName("panel")
    box = QVBoxLayout(frame)
    box.setContentsMargins(20, 16, 20, 18)
    box.setSpacing(10)
    if title:
        box.addWidget(label(title, "eyebrow"))
    return frame, box


class FormDialog(QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(540)
        self.layout = QVBoxLayout(self)
        self.layout.addWidget(label(title, "title"))
        self.form = QFormLayout()
        self.form.setSpacing(12)
        self.layout.addLayout(self.form)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("Kaydet")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Vazgeç")
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)


class PasswordDialog(QDialog):
    def __init__(self, title, parent=None, setup=False, submit=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(500)
        self.result_value = None
        self.submit = submit
        box = QVBoxLayout(self)
        box.addWidget(label(title, "title"))
        box.addWidget(label("4 haneli bir yönetici şifresi seçin. Personel PIN’lerinden farklı olmalı; "
                            "1111 ya da 1234 gibi kolay şifreler kabul edilmez."
                            if setup else "Yönetici şifrenizi girin.", "subtitle"))
        # Login also accepts a longer legacy password so older installs can still sign in.
        self.password = code_edit("4 haneli şifre") if setup else secret_edit()
        if not setup:
            self.password.setPlaceholderText("4 haneli şifre")
        box.addWidget(self.password)
        self.repeat = code_edit() if setup else None
        if self.repeat:
            self.repeat.setPlaceholderText("Şifreyi tekrar girin")
            box.addWidget(self.repeat)
        self.error = label("", "warning")
        self.error.hide()
        box.addWidget(self.error)
        box.addWidget(button("Kurulumu tamamla" if setup else "Giriş yap", self.confirm, True))
        box.addWidget(button("Vazgeç", self.reject))
        self.password.returnPressed.connect(self.confirm)

    def confirm(self):
        try:
            if self.repeat and self.password.text() != self.repeat.text():
                raise AppError("Şifreler aynı değil.")
            self.result_value = self.submit(self.password.text()) if self.submit else self.password.text()
            self.password.clear()
            if self.repeat:
                self.repeat.clear()
            self.accept()
        except AppError as exc:
            self.error.setText(str(exc))
            self.error.show()
            self.password.clear()

    def done(self, result):
        self.password.clear()
        if self.repeat:
            self.repeat.clear()
        super().done(result)


def fit_to_screen(widget, width, height, center=True):
    """Size a window to fit the screen it is on (small laptops, 125–150 % scaling)."""
    screen = widget.screen() or QApplication.primaryScreen()
    if screen is None:
        widget.resize(width, height)
        return
    area = screen.availableGeometry()
    w, h = min(width, int(area.width() * 0.96)), min(height, int(area.height() * 0.92))
    widget.resize(w, h)
    if center:
        widget.move(area.x() + (area.width() - w) // 2, area.y() + (area.height() - h) // 2)


class KeypadInput:
    """Shared behaviour: an on-screen keypad feeding a hidden, never-focused field.

    The field never takes focus, so Windows does not pop up its touch keyboard;
    physical keyboards still work through keyPressEvent.
    """
    def _build_input(self, box, key_size):
        self.pin = secret_edit(128)
        self.pin.setObjectName("pin")
        self.pin.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pin.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, False)
        self.pin.setAccessibleName("Dört haneli şifre")
        self.dots = PinDots(PIN_LENGTH)
        self.pin.textChanged.connect(lambda text: self.dots.set_filled(min(len(text), PIN_LENGTH)))
        box.addWidget(self.dots, 0, Qt.AlignmentFlag.AlignHCenter)
        box.addWidget(self.pin)
        self.keypad = Keypad(key_size)
        self.keypad.digit.connect(self.press)
        self.keypad.clear.connect(lambda: self.press("Temizle"))
        self.keypad.backspace.connect(lambda: self.press("Sil"))
        box.addWidget(self.keypad, 0, Qt.AlignmentFlag.AlignHCenter)
        self._submit_pending = False

    def press(self, text):
        if text == "Temizle":
            self.pin.clear()
        elif text == "Sil":
            self.pin.backspace()
        else:
            if len(self.pin.text()) >= PIN_LENGTH and self.pin.text().isdigit():
                return
            self.pin.insert(text)
            if len(self.pin.text()) == PIN_LENGTH and self.pin.text().isdigit() and not self._submit_pending:
                # Submit on the last digit; the short pause lets the last dot appear.
                self._submit_pending = True
                QTimer.singleShot(180, self, self.confirm)

    def keyPressEvent(self, event):
        key, text = event.key(), event.text()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.confirm()
        elif key == Qt.Key.Key_Backspace:
            self.press("Sil")
        elif key == Qt.Key.Key_Escape:
            self.reject()
        elif text and text.isprintable() and not text.isspace():
            if text.isdigit():
                self.press(text)
            else:
                self.pin.insert(text)          # legacy long admin password typed on a keyboard
        else:
            super().keyPressEvent(event)


class PinDialog(KeypadInput, QDialog):
    def __init__(self, service, employee, parent=None):
        QDialog.__init__(self, parent)
        self.service, self.employee = service, employee
        self.action = "end" if employee["session_id"] else "start"
        self.request_id = str(uuid.uuid4())
        self.result_sid = None
        self.setWindowTitle("Personel doğrulama")
        self.forgotten = bool(employee["session_id"]) and service.past_day_boundary(employee["start_at"])
        screen = self.screen() or QApplication.primaryScreen()
        short = screen is not None and screen.availableGeometry().height() < 760
        key = 54 if short else 62
        box = QVBoxLayout(self)
        box.setContentsMargins(28, 18, 28, 18)
        box.setSpacing(8)
        head = QHBoxLayout()
        ring = RingWidget(26)
        if self.forgotten:
            state, progress = "forgotten", 0.0
        elif employee["session_id"]:
            state = "in"
            progress = (service.clock.wall() - employee["start_at"]) / th.SHIFT_GOAL_SECONDS
        else:
            state, progress = "out", 0.0
        ring.set_ring(state, progress, th.initials(employee["name"]))
        head.addWidget(ring)
        names = QVBoxLayout()
        names.setSpacing(0)
        name = label(employee["name"], "h2")
        names.addWidget(name)
        if self.forgotten:
            hint = "giriş " + service.display_time(employee["start_at"], seconds=False)
        elif employee["session_id"]:
            local = datetime.fromtimestamp(employee["start_at"], service.zone)
            hint = f"{local:%H:%M}'dan beri içeride"
        else:
            hint = "işe başlamak için pin'ini gir"
        names.addWidget(label(hint, "subtitle"))
        head.addLayout(names, 1)
        box.addLayout(head)
        if self.forgotten:
            box.addWidget(label("Bu kayıt önceki iş gününden açık kalmış; çıkış yapılmamış. "
                                "Şimdi kapatabilirsin, kayıt yöneticiye işaretlenir ve gerçek çıkış "
                                "saatini yönetici girer. Ardından yeni giriş yapabilirsin.", "warning"))
        box.addSpacing(4)
        self._build_input(box, key)
        self.error = label("", "warning")
        self.error.hide()
        box.addWidget(self.error)
        self.confirm_button = button("işi bitir" if self.action == "end" else "işe başla",
                                     self.confirm, True)
        self.confirm_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        box.addWidget(self.confirm_button)
        cancel = button("vazgeç", self.reject, name="ghost")
        cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        box.addWidget(cancel, 0, Qt.AlignmentFlag.AlignHCenter)
        self.setFixedWidth(max(340, key * 3 + int(key * 0.32) * 2 + 56))
        # Short-lived PIN screen, even if nobody presses a button.
        QTimer.singleShot(60_000, self, self.reject)

    def confirm(self):
        self._submit_pending = False
        if self.result_sid is not None:
            return
        self.confirm_button.setEnabled(False)
        try:
            self.result_sid = self.service.attendance(self.employee["id"], self.pin.text(), self.action,
                                                      self.employee["session_id"], self.request_id)
            self.pin.clear()
            self.accept()
        except (AppError, sqlite3.Error, OSError) as exc:
            self.error.setText(str(exc) if isinstance(exc, AppError) else
                               "İşlem doğrulanamadı. Yönetici kayıtları kontrol etmeli.")
            self.error.show()
            self.pin.clear()
            self.dots.set_filled(0, error=True)
        finally:
            self.confirm_button.setEnabled(True)

    def done(self, result):
        self.pin.clear()
        super().done(result)


class CodeDialog(KeypadInput, QDialog):
    """Admin code entry with the same compact keypad (no OS touch keyboard).

    `steps` are the prompts shown one after another (e.g. new code, repeat);
    `submit` receives the list of entered codes and returns the result value.
    """
    def __init__(self, title, steps, submit, parent=None, note=""):
        QDialog.__init__(self, parent)
        self.setWindowTitle(title)
        self.steps, self.submit, self.codes = steps, submit, []
        self.result_value = None
        self.result_sid = None
        box = QVBoxLayout(self)
        box.setContentsMargins(28, 22, 28, 20)
        box.setSpacing(8)
        box.addWidget(label(title, "h2"))
        self.prompt = label(steps[0], "subtitle")
        box.addWidget(self.prompt)
        if note:
            box.addWidget(label(note, "faint"))
        box.addSpacing(4)
        self._build_input(box, 58)
        self.error = label("", "warning")
        self.error.hide()
        box.addWidget(self.error)
        cancel = button("vazgeç", self.reject, name="ghost")
        cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        box.addWidget(cancel, 0, Qt.AlignmentFlag.AlignHCenter)
        self.setFixedWidth(360)

    def confirm(self):
        self._submit_pending = False
        code = self.pin.text()
        if not code:
            return
        self.codes.append(code)
        self.pin.clear()
        if len(self.codes) < len(self.steps):
            self.prompt.setText(self.steps[len(self.codes)])
            self.error.hide()
            return
        try:
            self.result_value = self.submit(self.codes)
            self.accept()
        except AppError as exc:
            self.codes = []
            self.prompt.setText(self.steps[0])
            self.error.setText(str(exc))
            self.error.show()
            self.dots.set_filled(0, error=True)

    def done(self, result):
        self.pin.clear()
        self.codes = []
        super().done(result)


def admin_login_dialog(service, parent=None):
    return CodeDialog("Yönetici girişi", ["yönetici şifresini gir"],
                      lambda codes: service.login_admin(codes[0]), parent)


def setup_dialog(service, parent=None):
    def submit(codes):
        if codes[0] != codes[1]:
            raise AppError("Şifreler aynı değil. Baştan girin.")
        service.setup(codes[0])
        return True
    return CodeDialog("İlk kurulum", ["4 haneli yönetici şifresi belirle", "aynı şifreyi tekrar gir"],
                      submit, parent, "1111 ya da 1234 gibi kolay şifreler kabul edilmez.")


class EmployeeDialog(FormDialog):
    def __init__(self, service, token, employee=None, parent=None):
        super().__init__("Personel düzenle" if employee else "Yeni personel", parent)
        self.service, self.token, self.employee = service, token, employee
        self.name = QLineEdit(employee["name"] if employee else "")
        self.name.setMaxLength(80)
        self.pin = code_edit("Değiştirmemek için boş bırakın" if employee else "4 rakam")
        self.rate = QLineEdit(tl(employee["rate_cents"]) if employee else "")
        self.active = QCheckBox("Aktif personel")
        self.active.setChecked(bool(employee["active"]) if employee else True)
        self.reason = QLineEdit()
        self.form.addRow("Ad soyad", self.name)
        self.form.addRow("PIN", self.pin)
        self.form.addRow("Saatlik ücret (TL)", self.rate)
        if employee:
            self.form.addRow(self.active)
            self.form.addRow("Değişiklik gerekçesi", self.reason)
        self.form.addRow(label("Ücret değişikliği sonraki işe girişlerde geçerlidir. "
                              "Açık ve geçmiş kayıtların ücreti korunur.", "subtitle"))
        self.buttons.accepted.connect(self.save)

    @guarded
    def save(self):
        if self.employee:
            self.service.update_employee(self.token, self.employee["id"], self.name.text(),
                                         cents(self.rate.text()), self.active.isChecked(),
                                         self.reason.text(), self.pin.text() or None)
        else:
            self.service.add_employee(self.token, self.name.text(), self.pin.text(), cents(self.rate.text()))
        self.pin.clear()
        self.accept()

    def done(self, result):
        self.pin.clear()
        super().done(result)


def datetime_field(service, timestamp):
    # Widgets show business local wall time, independent of OS timezone.
    local = datetime.fromtimestamp(timestamp, service.zone)
    field = QDateTimeEdit(QDateTime(QDate(local.year, local.month, local.day),
                                   QTime(local.hour, local.minute, local.second)))
    field.setDisplayFormat("dd.MM.yyyy HH:mm:ss")
    field.setCalendarPopup(True)
    return field


def field_timestamp(service, field):
    dt = field.dateTime()
    local = datetime(dt.date().year(), dt.date().month(), dt.date().day(),
                     dt.time().hour(), dt.time().minute(), dt.time().second(), tzinfo=service.zone)
    # Reject ambiguous / nonexistent wall times instead of silently shifting.
    if local.replace(fold=0).utcoffset() != local.replace(fold=1).utcoffset():
        raise AppError("Bu saat saat dilimi geçişinde belirsiz. Farklı bir saat seçin.")
    return int(local.timestamp())


class SessionDialog(FormDialog):
    def __init__(self, service, token, session=None, parent=None):
        super().__init__("Çalışma kaydını düzelt" if session else "Eksik çalışma kaydı ekle", parent)
        self.service, self.token, self.session = service, token, session
        self.request_id = str(uuid.uuid4())
        self.employee = QComboBox()
        self.employee_rows = service.employees(token)
        for e in self.employee_rows:
            self.employee.addItem(f"{e['name']} · No {e['id']}", e["id"])
        now = service.clock.wall()
        self.start = datetime_field(service, session["start_at"] if session else now - 3600)
        self.end = datetime_field(service, (session["end_at"] or now) if session else now)
        self.open = QCheckBox("Açık kayıt olarak bırak")
        self.open.setChecked(bool(session and session["end_at"] is None))
        self.end.setEnabled(not self.open.isChecked())
        self.open.toggled.connect(lambda checked: self.end.setEnabled(not checked))
        self.rate = QLineEdit(tl(session["rate_cents"]) if session else "0,00")
        self.void = QCheckBox("Kaydı iptal et (geçmişte saklanır)")
        self.reason = QLineEdit()
        self.reason.setMaxLength(500)
        if session:
            self.form.addRow("Personel", label(session["name"]))
            self.rate.setReadOnly(True)
            if session.get("review"):
                self.form.addRow(label("İnceleme bekliyor: " + session["review"] +
                                       " Saatleri kontrol edip kaydetmek kaydı incelenmiş sayar.",
                                       "warning"))
        else:
            self.form.addRow("Personel", self.employee)
            self.employee.currentIndexChanged.connect(self.set_rate)
            self.set_rate()
        self.form.addRow("Giriş", self.start)
        self.form.addRow("Çıkış", self.end)
        self.form.addRow(self.open)
        self.form.addRow("Bu kaydın saatlik TL ücreti", self.rate)
        if session:
            self.form.addRow(self.void)
        self.form.addRow("Gerekçe", self.reason)
        self.form.addRow(label("Saat dilimi: " + str(service.zone) +
                              ". Geçmiş kayıt eklerken o tarihteki ücreti doğrulayın.", "subtitle"))
        self.buttons.accepted.connect(self.save)

    def set_rate(self):
        if self.employee.currentIndex() >= 0:
            self.rate.setText(tl(self.employee_rows[self.employee.currentIndex()]["rate_cents"]))

    @guarded
    def save(self):
        start = field_timestamp(self.service, self.start)
        end = None if self.open.isChecked() else field_timestamp(self.service, self.end)
        if self.session:
            self.service.correct_session(self.token, self.session["id"], self.session["revision"],
                                         start, end, self.reason.text(), self.void.isChecked())
        else:
            self.service.manual_session(self.token, self.employee.currentData(), start, end,
                                        cents(self.rate.text()), self.reason.text(), self.request_id)
        self.accept()


class PaymentDialog(FormDialog):
    def __init__(self, service, token, parent=None):
        super().__init__("Ödeme / avans ekle", parent)
        self.service, self.token = service, token
        self.request_id = str(uuid.uuid4())
        self.employee = QComboBox()
        for e in service.employees(token):
            self.employee.addItem(f"{e['name']} · No {e['id']}", e["id"])
        self.kind = QComboBox()
        self.kind.addItems(["Ödeme", "Avans"])
        self.amount = QLineEdit()
        self.paid_at = datetime_field(service, service.clock.wall())
        self.note = QLineEdit()
        self.note.setMaxLength(500)
        for name, widget in [("Personel", self.employee), ("Tür", self.kind), ("Tutar (TL)", self.amount),
                             ("Tarih", self.paid_at), ("Açıklama", self.note)]:
            self.form.addRow(name, widget)
        self.buttons.accepted.connect(self.save)

    @guarded
    def save(self):
        self.service.add_payment(self.token, self.employee.currentData(),
                                 field_timestamp(self.service, self.paid_at), cents(self.amount.text()),
                                 self.kind.currentText(), self.note.text(), self.request_id)
        self.accept()


class ReasonDialog(FormDialog):
    def __init__(self, title, action, parent):
        super().__init__(title, parent)
        self.action = action
        self.reason = QLineEdit()
        self.reason.setMaxLength(500)
        self.form.addRow("Gerekçe", self.reason)
        self.buttons.accepted.connect(self.save)

    @guarded
    def save(self):
        self.action(self.reason.text())
        self.accept()


def qdate(day):
    return QDate(day.year, day.month, day.day)


class FilterBar(QWidget):
    """Period + employee filter shared by sessions, earnings and payments; default is this month.

    Preset chips and the ‹ › day arrows apply at once. Dates typed into the fields form a
    custom range that waits for "filtrele", so half-entered dates never run a query.
    `on_apply(bar)` runs after every applied change.
    """
    def __init__(self, service, token, on_apply, review_toggle=False, parent=None):
        super().__init__(parent)
        self.service, self.on_apply = service, on_apply
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)
        chips = QHBoxLayout()
        chips.setSpacing(8)
        self.chips = {}
        for key, text in periods.PRESETS:
            chip = button(text, lambda checked=False, k=key: self.choose(k), name="chip")
            chip.setCheckable(True)
            self.chips[key] = chip
            chips.addWidget(chip)
        chips.addStretch()
        outer.addLayout(chips)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.prev = button("‹", lambda: self.step(-1), name="chip")
        self.next = button("›", lambda: self.step(1), name="chip")
        self.prev.setToolTip("önceki gün")
        self.next.setToolTip("sonraki gün")
        self.first, self.last = QDateEdit(), QDateEdit()
        row.addWidget(self.prev)
        for w in (self.first, self.last):
            w.setCalendarPopup(True)
            w.setDisplayFormat("dd.MM.yyyy")
            row.addWidget(w)
        row.addWidget(self.next)
        for b in (self.prev, self.next):
            b.setFixedWidth(44)
        self.apply_button = button("filtrele", self.apply_custom, True)
        row.addWidget(self.apply_button)
        self.caption = label("", "subtitle")
        self.caption.setWordWrap(False)
        row.addWidget(self.caption)
        row.addStretch()
        self.employee = QComboBox()
        self.employee.addItem("Tüm personel", None)
        for e in service.employees(token):
            self.employee.addItem(f"{e['name']} · No {e['id']}", e["id"])
        row.addWidget(self.employee)
        self.review = QCheckBox("inceleme bekleyenler") if review_toggle else None
        if self.review:
            row.addWidget(self.review)
        outer.addLayout(row)
        self.first.dateChanged.connect(lambda: self.edited(self.first))
        self.last.dateChanged.connect(lambda: self.edited(self.last))
        self.show_range(*periods.preset_range(periods.DEFAULT_PRESET, self.today()), periods.DEFAULT_PRESET)
        # Employee/review changes apply by themselves (short debounce).
        self._apply = QTimer(self)
        self._apply.setSingleShot(True)
        self._apply.setInterval(200)
        self._apply.timeout.connect(lambda: self.on_apply(self) if self.window().isVisible() else None)
        self.employee.currentIndexChanged.connect(self._apply.start)
        if self.review:
            self.review.toggled.connect(self._apply.start)

    def today(self):
        return self.service.business_day(self.service.clock.wall())

    def show_range(self, first, last, preset):
        """Make (first, last) the applied range without running the query."""
        today = self.today()
        self.range, self.preset = (first, last), preset
        for edit, day in ((self.first, first), (self.last, last)):
            edit.blockSignals(True)
            edit.setMaximumDate(qdate(today))
            edit.setDate(qdate(day))
            edit.blockSignals(False)
        self.mark(preset)
        self.next.setEnabled(last < today)
        self.caption.setText(periods.caption(first, last))
        self.caption.show()

    def mark(self, preset):
        for key, chip in self.chips.items():
            chip.setChecked(key == preset)
        self.apply_button.setVisible(preset == "custom")

    def follow(self, other):
        """Take another bar's applied period (the period is shared between pages)."""
        self.show_range(*other.range, other.preset)

    def changed(self):
        self._apply.stop()
        self.on_apply(self)

    def choose(self, key):
        if key == "custom":
            self.mark("custom")
            self.caption.hide()   # until applied; the "filtrele" button says what to do
            return
        self.show_range(*periods.preset_range(key, self.today()), key)
        self.changed()

    def step(self, delta):
        today = self.today()
        day = periods.step_day(self.range[1], delta, today)
        self.show_range(day, day, periods.matching_preset(day, day, today))
        self.changed()

    def edited(self, which):
        """A date was typed or picked: keep the range ordered and wait for "filtrele"."""
        first, last = self.first.date(), self.last.date()
        if first > last:
            other = self.last if which is self.first else self.first
            other.blockSignals(True)
            other.setDate(which.date())
            other.blockSignals(False)
        self.mark("custom")
        self.caption.hide()

    def apply_custom(self):
        first, last = self.first.date().toPython(), self.last.date().toPython()
        self.show_range(first, last, periods.matching_preset(first, last, self.today()) or "custom")
        self.changed()

    def sync_employees(self, rows):
        """Keep the employee list current without losing the selection."""
        current = self.employee.currentData()
        wanted = [(f"{e['name']} · No {e['id']}", e["id"]) for e in rows]
        existing = [(self.employee.itemText(i), self.employee.itemData(i))
                    for i in range(1, self.employee.count())]
        if wanted == existing:
            return
        self.employee.blockSignals(True)
        while self.employee.count() > 1:
            self.employee.removeItem(1)
        for text, eid in wanted:
            self.employee.addItem(text, eid)
        index = self.employee.findData(current)
        self.employee.setCurrentIndex(index if index >= 0 else 0)
        self.employee.blockSignals(False)

    def values(self):
        """The applied filter; dates still waiting for "filtrele" are not included."""
        first, last = self.range
        since, until = self.service.day_bounds(first, last)
        return {"eid": self.employee.currentData(), "first": first, "last": last,
                "since": since, "until": until}

    def review_only(self):
        return bool(self.review and self.review.isChecked())


class AdminDialog(QDialog):
    PAGES = ["bugün", "personel", "giriş / çıkış", "hak ediş", "ödemeler", "ayarlar"]

    def __init__(self, service, token, parent=None):
        super().__init__(parent)
        self.service, self.token = service, token
        self.last_input = time.monotonic()
        self.setWindowTitle("Yönetici paneli")
        self.setMinimumSize(760, 520)
        fit_to_screen(self, 1240, 820)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        nav_pane = QFrame()
        nav_pane.setObjectName("navPane")
        nav_pane.setFixedWidth(232)
        nav_box = QVBoxLayout(nav_pane)
        nav_box.setContentsMargins(18, 26, 18, 20)
        nav_box.setSpacing(6)
        self.logo = QLabel()
        nav_box.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignLeft)
        nav_box.addWidget(label("yönetici", "eyebrow"))
        nav_box.addSpacing(14)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.addItems(self.PAGES)
        self.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        nav_box.addWidget(self.nav, 1)
        nav_box.addWidget(button("oturumu kapat", self.accept))
        nav_box.addWidget(label("5 dakika hareketsizlikte kapanır · ön hak ediş, resmî bordro değildir",
                                "faint"))
        outer.addWidget(nav_pane)

        self.pages = QStackedWidget()
        self.tabs = self.pages  # older name kept for callers/tests
        outer.addWidget(self.pages, 1)
        self.today_page()
        self.people_tab()
        self.sessions_tab()
        self.reports_tab()
        self.payments_tab()
        self.security_tab()
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self.retheme()
        self.refresh()
        QApplication.instance().installEventFilter(self)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_timeout)
        self.timer.start(1000)

    def retheme(self):
        t = current()
        self.logo.setPixmap(logo_pixmap(t["text"], 58, self.devicePixelRatioF()))
        for chip, name in getattr(self, "theme_chips", []):
            chip.setChecked(self.service.theme == name)
        self.update()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress,
                            QEvent.Type.TouchBegin, QEvent.Type.Wheel):
            if isinstance(watched, QWidget) and (watched is self or self.isAncestorOf(watched)):
                self.last_input = time.monotonic()
        return False

    def check_timeout(self):
        if time.monotonic() - self.last_input > 300:
            self.service.logout(self.token)
            # Close nested forms so an inactive panel cannot remain visible.
            for child in self.findChildren(QDialog):
                child.reject()
            self.reject()

    def done(self, result):
        self.timer.stop()
        # A filter change made just before closing must not refresh a closed panel.
        for bar in getattr(self, "filters", ()):
            bar._apply.stop()
        QApplication.instance().removeEventFilter(self)
        self.service.logout(self.token)
        super().done(result)

    def tab(self, title, subtitle="", scroll=True):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 28, 34, 24)
        layout.setSpacing(14)
        head, _, sub = page_header(title, subtitle)
        layout.addLayout(head)
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setWidget(page)
            self.pages.addWidget(area)
        else:
            self.pages.addWidget(page)
        layout.subtitle_label = sub
        return layout

    def toolbar(self, layout, actions):
        row = QHBoxLayout()
        row.setSpacing(10)
        for title, callback in actions:
            row.addWidget(button(title, callback))
        row.addStretch()
        layout.addLayout(row)

    # --- pages ---------------------------------------------------------------

    def today_page(self):
        box = self.tab("bugün", scroll=True)
        self.today_subtitle = box.subtitle_label
        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.tile_inside = StatTile("şu an içeride")
        self.tile_hours = StatTile("bugünkü toplam")
        self.tile_month = StatTile("bu ay ön hak ediş")
        self.tile_review = StatTile("inceleme bekleyen")
        for tile in (self.tile_inside, self.tile_hours, self.tile_month, self.tile_review):
            tiles.addWidget(tile, 1)
        box.addLayout(tiles)
        frame, inner = panel("vardiya çizelgesi")
        self.timeline = TimelineWidget()
        inner.addWidget(self.timeline)
        box.addWidget(frame)
        frame, inner = panel("son 7 gün · saat")
        self.heatmap = HeatmapWidget()
        inner.addWidget(self.heatmap)
        box.addWidget(frame)
        box.addStretch()

    def people_tab(self):
        box = self.tab("personel", "ekip, ücretler ve pin kilitleri")
        self.toolbar(box, [("Personel ekle", self.add_employee), ("Seçileni düzenle", self.edit_employee),
                           ("Kilidi kaldır", self.unlock_employee)])
        self.people_table = make_table(["No", "Ad Soyad", "Saatlik TL", "Durum"])
        self.people_table.cellDoubleClicked.connect(lambda *_: self.edit_employee())
        box.addWidget(self.people_table)

    def sessions_tab(self):
        box = self.tab("giriş / çıkış", "kayıtlar, düzeltmeler ve incelemeler")
        self.session_filter = FilterBar(self.service, self.token, self.filters_changed, review_toggle=True)
        self.filters = [self.session_filter]
        box.addWidget(self.session_filter)
        self.review_note = label("", "warning")
        self.review_note.hide()
        box.addWidget(self.review_note)
        self.toolbar(box, [("Eksik kayıt ekle", self.add_session), ("Seçileni düzelt", self.edit_session)])
        self.session_table = make_table(["Kayıt", "Personel", "Giriş", "Çıkış", "Saatlik TL", "Durum",
                                         "İnceleme"])
        self.session_table.cellDoubleClicked.connect(lambda *_: self.edit_session())
        box.addWidget(self.session_table)

    def reports_tab(self):
        box = self.tab("hak ediş", "ön hak ediş · resmî bordro değildir")
        self.report_filter = FilterBar(self.service, self.token, self.filters_changed)
        self.filters.append(self.report_filter)
        box.addWidget(self.report_filter)
        self.report_note = label("Açık kayıtlar geçici tahmindir ve bakiyeye eklenmez.", "warning")
        box.addWidget(self.report_note)
        self.report_table = make_table(["Personel", "Kapalı süre", "Ön hak ediş TL", "Açık tahmini TL",
                                       "Ödeme/avans TL", "Devreden TL", "Bakiye TL", "İnceleme"])
        box.addWidget(self.report_table)
        self.toolbar(box, [("CSV indir", lambda: self.export(".csv")),
                           ("Excel indir", lambda: self.export(".xlsx"))])
        self.report = None

    def payments_tab(self):
        box = self.tab("ödemeler", "ödeme ve avanslar")
        self.payment_filter = FilterBar(self.service, self.token, self.filters_changed)
        self.filters.append(self.payment_filter)
        box.addWidget(self.payment_filter)
        self.toolbar(box, [("Ödeme / avans ekle", self.add_payment), ("Seçileni iptal et", self.void_payment)])
        self.payment_table = make_table(["Kayıt", "Personel", "Tarih", "Tür", "Tutar TL", "Açıklama", "Durum"])
        box.addWidget(self.payment_table)

    def security_tab(self):
        box = self.tab("ayarlar", "görünüm, saat, iş günü, güvenlik ve yedekler", scroll=True)
        frame, inner = panel("görünüm")
        row = QHBoxLayout()
        self.theme_chips = []
        for name, caption in th.THEME_LABELS.items():
            chip = button(caption, lambda checked=False, n=name: self.change_theme(n), name="chip")
            chip.setCheckable(True)
            self.theme_chips.append((chip, name))
            row.addWidget(chip)
        row.addStretch()
        inner.addLayout(row)
        box.addWidget(frame)

        frame, inner = panel("saat ve iş günü")
        self.clock_note = label("", "warning")
        inner.addWidget(self.clock_note)
        self.toolbar(inner, [("Saati kontrol ettim", self.ack_clock),
                             ("İş günü başlangıcını değiştir", self.change_day_start)])
        self.day_note = label("", "subtitle")
        inner.addWidget(self.day_note)
        box.addWidget(frame)

        frame, inner = panel("güvenlik ve yedek")
        self.toolbar(inner, [("Şifre değiştir", self.change_password), ("Bütünlüğü denetle", self.check_integrity),
                             ("Yedek al", self.backup), ("Yedekten kurtar", self.restore)])
        inner.addWidget(label("Veri klasörü: " + str(self.service.db.path.parent), "faint"))
        self.backup_note = label("", "subtitle")
        inner.addWidget(self.backup_note)
        box.addWidget(frame)

        frame, inner = panel("işlem geçmişi")
        self.audit_note = label("", "faint")
        inner.addWidget(self.audit_note)
        self.audit_table = make_table(["No", "Tarih", "Yapan", "İşlem", "Kayıt", "Gerekçe"])
        self.audit_table.setMinimumHeight(360)
        inner.addWidget(self.audit_table)
        self.toolbar(inner, [("Geçmiş ayrıntısı", self.audit_detail), ("Geçmişi CSV indir", self.audit_export)])
        box.addWidget(frame)

    # --- data ----------------------------------------------------------------

    @guarded
    def change_theme(self, name):
        self.service.set_theme(self.token, name)
        apply_theme(QApplication.instance(), name)
        self.retheme()

    @guarded
    def refresh(self):
        self.people = self.service.employees(self.token)
        for bar in self.filters:
            bar.sync_employees(self.people)
        fill_table(self.people_table, [[e["id"], e["name"], tl(e["rate_cents"]),
                                       " · ".join(x for x in ("Aktif" if e["active"] else "Arşiv",
                                                              lock_text(self.service, e["locked_until"])) if x)]
                                      for e in self.people],
                   [(th.initials(e["name"]), "locked" if lock_seconds(self.service, e["locked_until"])
                     else "out") for e in self.people])
        f = self.session_filter.values()
        self.session_rows = self.service.sessions(self.token, f["eid"], f["since"], f["until"],
                                                  self.session_filter.review_only())
        fill_table(self.session_table, [[s["id"], s["name"], self.service.display_time(s["start_at"], False),
                                        self.service.display_time(s["end_at"], False), tl(s["rate_cents"]),
                                        "İptal" if s["voided"] else "Açık" if s["end_at"] is None else "Kapalı",
                                        "" if s["voided"] else s["review"]]
                                       for s in self.session_rows],
                   [(th.initials(s["name"]), "forgotten" if s["review"] and not s["voided"]
                     else "in" if s["end_at"] is None and not s["voided"] else "out")
                    for s in self.session_rows])
        pending = self.service.pending_reviews(self.token)
        self.review_note.setText(f"İnceleme bekleyen {pending} kayıt var. “inceleme bekleyenler” kutusuyla "
                                 "listeleyip saatleri kontrol ederek kaydedin.")
        self.review_note.setVisible(bool(pending))
        f = self.payment_filter.values()
        self.payment_rows = self.service.payments(self.token, f["eid"], f["since"], f["until"])
        fill_table(self.payment_table, [[p["id"], p["name"], self.service.display_time(p["paid_at"], False),
                                        p["kind"], tl(p["amount_cents"]), p["note"],
                                        "İptal" if p["voided"] else "Geçerli"] for p in self.payment_rows],
                   [(th.initials(p["name"]), "out") for p in self.payment_rows])
        self.audit = self.service.audit_rows(self.token, AUDIT_SCREEN_LIMIT)
        names = {e["id"]: e["name"] for e in self.people}
        fill_table(self.audit_table, [[a["id"], self.service.display_time(a["at"], False),
                                      audit_party(a["actor"], names), action_name(a["action"]),
                                      audit_party(a["entity"], names), a["reason"]] for a in self.audit])
        self.audit_note.setText(f"Ekranda son {AUDIT_SCREEN_LIMIT} işlem gösterilir; "
                                "tamamı için “Geçmişi CSV indir”.")
        alert, notice = self.service.clock_status()
        self.clock_note.setText("\n".join(x for x in (alert, notice) if x) or "Saat şüphesi bulunmuyor.")
        self.clock_note.setObjectName("warning" if alert or notice else "note")
        self.clock_note.style().unpolish(self.clock_note)
        self.clock_note.style().polish(self.clock_note)
        self.day_note.setText(f"İş günü her gün {self.service.day_start_hour:02d}:00’da başlar. "
                              "Bu saatten önceki çalışma ve ödemeler önceki güne yazılır; "
                              "bu saati geçen açık kayıtlar “çıkış yapılmamış” olarak işaretlenir.")
        count, size = backup_usage(self.service.db)
        self.backup_note.setText(f"Otomatik yedekler: {count} dosya, {size / 1_048_576:.1f} MB. "
                                 "Son 30 gün, her ayın ilk yedeği ve son 20 kapanış yedeği saklanır; "
                                 "elle alınan yedekler silinmez.")
        self.calculate()
        self.refresh_today(pending)

    def refresh_today(self, pending):
        s, now = self.service, self.service.clock.wall()
        day = s.business_day(now)
        since, until = s.day_bounds(day, day)
        self.today_subtitle.setText(f"{th.DAYS[day.weekday()]}, {day.day} {th.MONTHS[day.month - 1]} · "
                                    f"iş günü {s.day_start_hour:02d}:00’da başlar")
        kiosk = {e["id"]: e for e in s.kiosk_employees()}
        inside = [e for e in kiosk.values() if e["session_id"]]
        today_report = build_report(s, self.token, day, day)
        month_report = build_report(s, self.token, day.replace(day=1), day)
        self.tile_inside.set_value(str(len(inside)))
        self.tile_hours.set_value(th.hours_text(sum(r["seconds"] + r["open_seconds"]
                                                    for r in today_report["summary"])))
        self.tile_month.set_value(tl(sum(r["cents"] for r in month_report["summary"])) + " TL")
        self.tile_review.set_value(str(pending), warn=bool(pending))

        labels = th.short_names(self.people)
        sessions = [r for r in s.sessions(self.token, since=since, until=until) if not r["voided"]]
        by_person = {}
        for r in sessions:
            by_person.setdefault(r["employee_id"], []).append(r)
        rows, lo, hi = [], since + 4 * 3600, since + 12 * 3600
        for eid, items in sorted(by_person.items(), key=lambda kv: min(x["start_at"] for x in kv[1])):
            segments = []
            for r in items:
                end = r["end_at"] if r["end_at"] is not None else now
                kind = "review" if r["review"] else "now" if r["end_at"] is None else "done"
                segments.append((max(r["start_at"], since), min(end, until), kind))
                lo, hi = min(lo, max(r["start_at"], since)), max(hi, min(end, until))
            k = kiosk.get(eid)
            if k and k["session_id"] and s.past_day_boundary(k["start_at"]):
                state = "forgotten"
            elif k and k["session_id"]:
                state = "in"
            else:
                state = "out"
            name = labels.get(eid) or th.tr_lower(items[0]["name"])
            rows.append((name, th.initials(items[0]["name"]), state, segments))
        hi = max(hi, min(now, until))
        lo -= lo % 3600
        hi += (-hi) % 3600
        ticks = []
        tick = lo
        step = 3600 if hi - lo <= 12 * 3600 else 7200
        while tick <= hi:
            ticks.append((tick, f"{datetime.fromtimestamp(tick, s.zone):%H}"))
            tick += step
        self.timeline.set_data(rows, lo, hi, ticks, now)

        first = day - timedelta(days=6)
        week = build_report(s, self.token, first, day)
        values, flags = {}, set()
        for r in week["days"]:
            col = (date.fromisoformat(r["day"]) - first).days
            values[(r["employee_id"], col)] = values.get((r["employee_id"], col), 0) + \
                (r["seconds"] + r["open_seconds"]) / 3600
        for r in week["sessions"]:
            if r.get("review"):
                col = (s.business_day(r["start_at"]) - first).days
                if 0 <= col < 7:
                    flags.add((r["employee_id"], col))
        names = [(e["id"], labels.get(e["id"], th.tr_lower(e["name"]))) for e in self.people
                 if e["active"] or any(key[0] == e["id"] for key in values)]
        days = [th.SHORT_DAYS[(first + timedelta(days=i)).weekday()] for i in range(7)]
        self.heatmap.set_data(names, days, values, flags)

    def selected(self, table, rows):
        index = table.currentRow()
        if not 0 <= index < len(rows):
            raise AppError("Önce bir satır seçin.")
        return rows[index]

    @guarded
    def add_employee(self):
        if EmployeeDialog(self.service, self.token, parent=self).exec():
            self.refresh()

    @guarded
    def edit_employee(self):
        row = self.selected(self.people_table, self.people)
        if EmployeeDialog(self.service, self.token, row, self).exec():
            self.refresh()

    @guarded
    def unlock_employee(self):
        row = self.selected(self.people_table, self.people)
        if ReasonDialog(f"{row['name']} · PIN kilidini kaldır",
                        lambda reason: self.service.unlock_employee(self.token, row["id"], reason),
                        self).exec():
            self.refresh()

    @guarded
    def add_session(self):
        if SessionDialog(self.service, self.token, parent=self).exec():
            self.refresh()

    @guarded
    def edit_session(self):
        row = self.selected(self.session_table, self.session_rows)
        if SessionDialog(self.service, self.token, row, self).exec():
            self.refresh()

    @guarded
    def add_payment(self):
        if PaymentDialog(self.service, self.token, self).exec():
            self.refresh()

    @guarded
    def void_payment(self):
        row = self.selected(self.payment_table, self.payment_rows)
        if ReasonDialog("Ödemeyi iptal et",
                        lambda reason: self.service.void_payment(self.token, row["id"], reason), self).exec():
            self.refresh()

    def filters_changed(self, source):
        """The period is shared: every page follows the bar that changed, then all refresh."""
        for bar in self.filters:
            if bar is not source:
                bar.follow(source)
        self.refresh()

    def build_report(self):
        f = self.report_filter.values()
        return build_report(self.service, self.token, f["first"], f["last"], f["eid"])

    @guarded
    def calculate(self):
        self.report = self.build_report()
        fill_table(self.report_table, [[r["name"], th.hours_text(r["seconds"]), tl(r["cents"]),
                                       tl(r["open_cents"]), tl(r["paid_cents"]),
                                       tl(r["carry_cents"]), tl(r["balance_cents"]),
                                       f"{r['review_count']} kayıt" if r["review_count"] else ""]
                                      for r in self.report["summary"]])
        first = date.fromisoformat(self.report["first"]).strftime("%d.%m.%Y")
        last = date.fromisoformat(self.report["last"]).strftime("%d.%m.%Y")
        self.report_note.setText(
            f"{first} — {last} · Açık tahminler bakiyeye dahil değil."
            + (f" İNCELEME BEKLEYEN {self.report['review_count']} KAYIT." if self.report["review_count"] else "")
            + (" SAAT UYARISI: " + self.report["clock_alert"] if self.report["clock_alert"] else ""))

    @guarded
    def export(self, suffix):
        report = self.build_report()   # the applied filter: the period shown on screen
        path, _ = QFileDialog.getSaveFileName(self, "Rapor kaydet",
                                              f"on-hak-edis-{report['first']}{suffix}",
                                              "Excel (*.xlsx)" if suffix == ".xlsx" else "CSV (*.csv)")
        if path:
            if not Path(path).suffix:
                path += suffix
            export_report(self.service, self.token, report, Path(path))
            QMessageBox.information(self, "Rapor hazır", "Rapor kaydedildi:\n" + path)

    @guarded
    def ack_clock(self):
        if ReasonDialog("Bilgisayar saati ve açık kayıtlar kontrol edildi",
                        lambda reason: self.service.acknowledge_clock(self.token, reason), self).exec():
            self.refresh()

    @guarded
    def check_integrity(self):
        self.service.require_admin(self.token)
        errors = inspect_database(self.service.db.path)
        QMessageBox.information(self, "Bütünlük sonucu", "\n".join(errors) if errors else
                                "SQLite, ilişkili kayıtlar, saat çakışmaları ve işlem zinciri: sağlam.")

    @guarded
    def backup(self):
        self.service.require_admin(self.token)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path, _ = QFileDialog.getSaveFileName(self, "Yeni yedek dosyası", f"vardiya-{stamp}.sqlite3",
                                              "SQLite (*.sqlite3)")
        if path:
            self.service.require_admin(self.token)
            create_backup(self.service.db, Path(path))
            QMessageBox.information(self, "Yedek hazır", "Doğrulanan yedek ve SHA-256 dosyası kaydedildi.")

    @guarded
    def restore(self):
        self.service.require_admin(self.token)
        path, _ = QFileDialog.getOpenFileName(self, "Kurtarılacak yedeği seç", "", "SQLite (*.sqlite3)")
        if not path:
            return
        choice = QMessageBox.question(
            self, "Yedekten kurtar",
            "Seçilen yedekten sonraki işlemler etkin kayıtlardan kalkacak. Mevcut veri recovery "
            "klasöründe korunacak. Kurtarma sonrası uygulama kapanacak. Devam edilsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if choice != QMessageBox.StandardButton.Yes:
            return
        dialog = CodeDialog("Kurtarma için yönetici doğrulaması", ["yönetici şifresini gir"],
                            lambda codes: (self.service._authenticate("admin", codes[0]), codes[0])[1], self)
        if not dialog.exec():
            return
        self.service.require_admin(self.token)
        db_path = self.service.db.path
        if isinstance(self.parent(), MainWindow):
            self.parent().restoring = True
            self.parent().timer.stop()
            self.parent().clock_timer.stop()
        self.service.db.close()
        try:
            archive = restore_database(Path(path), db_path, dialog.result_value)
            QMessageBox.information(self, "Kurtarma tamamlandı",
                                    "Uygulamayı yeniden açın. Önceki veriler:\n" + str(archive))
        finally:
            dialog.result_value = None
            QApplication.instance().quit()

    @guarded
    def change_day_start(self):
        dlg = FormDialog("İş günü başlangıcı", self)
        hours = QComboBox()
        for h in range(0, 13):
            hours.addItem(f"{h:02d}:00", h)
        hours.setCurrentIndex(self.service.day_start_hour)
        reason = QLineEdit()
        reason.setMaxLength(500)
        dlg.form.addRow("Başlangıç saati", hours)
        dlg.form.addRow("Gerekçe", reason)
        dlg.form.addRow(label("İşletmenin kapalı olduğu bir saat seçin. Değişiklik geçmiş raporların "
                              "gün dağılımını da yeniden hesaplar; toplam tutar değişmez.", "subtitle"))

        @guarded
        def save(_dialog):
            self.service.set_day_start(self.token, hours.currentData(), reason.text())
            dlg.accept()
        dlg.buttons.accepted.connect(lambda: save(dlg))
        if dlg.exec():
            self.refresh()

    @guarded
    def change_password(self):
        def submit(codes):
            old, new, repeat = codes
            if new != repeat:
                raise AppError("Yeni şifreler aynı değil. Baştan girin.")
            self.service.change_password(self.token, old, new)
            return True
        dlg = CodeDialog("Yönetici şifresini değiştir",
                         ["mevcut şifreni gir", "yeni 4 haneli şifreyi gir", "yeni şifreyi tekrar gir"],
                         submit, self, "Değişiklikten sonra yeniden giriş yapmanız gerekir.")
        if dlg.exec():
            self.accept()

    @guarded
    def audit_detail(self):
        self.service.require_admin(self.token)
        row = self.selected(self.audit_table, self.audit)
        box = QMessageBox(self)
        box.setWindowTitle("İşlem geçmişi")
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(f"{action_name(row['action'])} ({row['action']}) · {row['entity']}\n{row['reason']}")
        box.setDetailedText("ÖNCE\n" + row["before_json"] + "\n\nSONRA\n" + row["after_json"] +
                           "\n\nSHA-256\n" + row["hash"])
        box.exec()

    @guarded
    def audit_export(self):
        self.service.require_admin(self.token)
        path, _ = QFileDialog.getSaveFileName(self, "İşlem geçmişini kaydet", "islem-gecmisi.csv", "CSV (*.csv)")
        if path:
            export_audit(self.service, self.token, path)


class MainWindow(QMainWindow):
    TILE_W = 168

    def __init__(self, service):
        super().__init__()
        self.service = service
        self.restoring = False
        self.verified_backups = set()
        self.card_signature = None
        self.columns = 0
        self.today_seconds = {}
        self.setWindowTitle("Ó'is · Vardiya")
        self.resize(1180, 800)
        self.setMinimumSize(640, 480)
        root = Backdrop()
        self.setCentralWidget(root)
        box = QVBoxLayout(root)
        box.setContentsMargins(44, 30, 44, 22)
        box.setSpacing(12)

        top = QHBoxLayout()
        left = QVBoxLayout()
        left.setSpacing(0)
        self.greeting = label("", "subtitle")
        self.clock_label = QLabel("")
        self.clock_label.setObjectName("display")
        self.inside_label = label("", "insideCount")
        left.addWidget(self.greeting)
        left.addWidget(self.clock_label)
        left.addWidget(self.inside_label)
        top.addLayout(left)
        top.addStretch()
        right = QVBoxLayout()
        right.setSpacing(4)
        self.logo = QLabel()
        self.logo.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        right.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignRight)
        right.addWidget(button("yönetici", self.admin, name="ghost"), 0, Qt.AlignmentFlag.AlignRight)
        right.addStretch()
        top.addLayout(right)
        box.addLayout(top)

        self.warning = label("", "warning")
        self.warning.hide()
        box.addWidget(self.warning)

        row = QHBoxLayout()
        self.prompt = label("adına dokun", "subtitle")
        row.addWidget(self.prompt)
        row.addStretch()
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("ara")
        self.search.setFixedWidth(240)
        self.search.setClearButtonEnabled(True)
        self.search.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.search.textChanged.connect(self.render_people)
        row.addWidget(self.search)
        box.addLayout(row)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        self.cards = QWidget()
        self.cards.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.grid = QGridLayout(self.cards)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(14)
        self.grid.setContentsMargins(0, 8, 0, 8)
        self.scroll.setWidget(self.cards)
        self.scroll.viewport().installEventFilter(self)
        QScroller.grabGesture(self.scroll.viewport(), QScroller.ScrollerGestureType.TouchGesture)
        box.addWidget(self.scroll, 1)

        bottom = QHBoxLayout()
        self.status = label("çevrimdışı · tüm kayıtlar bu bilgisayarda", "status")
        bottom.addWidget(self.status, 1)
        bottom.addWidget(label("4 haneli pin ile", "faint"))
        box.addLayout(bottom)

        self.retheme()
        self.refresh()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.heartbeat)
        self.timer.start(15_000)
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_clock)
        self.clock_timer.start(1000)

    # --- appearance ----------------------------------------------------------

    def showEvent(self, event):
        super().showEvent(event)
        if current()["name"] != getattr(self, "_themed", None):
            self.retheme()
        if hasattr(self, "clock_timer") and not self.restoring:
            self.clock_timer.start(1000)     # restart after a close/show cycle
            self.timer.start(15_000)
        self.update_clock()

    def retheme(self):
        apply = QApplication.instance()
        if apply is not None and current()["name"] != self.service.theme:
            apply_theme(apply, self.service.theme)
            return  # apply_theme calls retheme again
        t = current()
        self._themed = t["name"]
        self.logo.setPixmap(logo_pixmap(t["text"], 92, self.devicePixelRatioF()))
        self.card_signature = None
        if hasattr(self, "people"):
            self.render_people()
        self.centralWidget().update()

    def closeEvent(self, event):
        # A closed window must not keep polling the database in the background.
        for timer in (getattr(self, "timer", None), getattr(self, "clock_timer", None)):
            if timer is not None:
                timer.stop()
        super().closeEvent(event)

    def update_clock(self):
        if self.restoring:
            return
        now = self.service.clock.wall()
        local = datetime.fromtimestamp(now, self.service.zone)
        self.clock_label.setText(f"{local:%H:%M}")
        self.greeting.setText(th.greeting(local, self.service.business_day(now)))
        inside = sum(1 for e in getattr(self, "people", []) if e["session_id"])
        self.inside_label.setText(f"içeride {inside} kişi" if inside else "şu an içeride kimse yok")

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.Resize and watched is self.scroll.viewport() and self.isVisible()
                and hasattr(self, "people") and self.column_count() != self.columns):
            # Queued: by the time it runs the window may be closed and the database shut.
            QTimer.singleShot(0, lambda: self.isVisible() and self.render_people())
        return False

    def column_count(self):
        width = self.scroll.viewport().width() if hasattr(self, "scroll") else self.width()
        return max(2, width // self.TILE_W)

    # --- people --------------------------------------------------------------

    @guarded
    def refresh(self):
        self.people = self.service.kiosk_employees()
        self.today_seconds = self.service.kiosk_today_seconds()
        self.render_people()
        self.heartbeat()

    def render_people(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        query = th.tr_lower(self.search.text())
        people = [e for e in getattr(self, "people", []) if query in th.tr_lower(e["name"])]
        names = th.short_names(getattr(self, "people", []))
        self.card_signature = self.cards_state()
        self.columns = self.column_count()
        for i, employee in enumerate(people):
            state, progress, subtitle, description = self.card_state(employee)
            ring = PersonRing()
            ring.set_person(state, progress, th.initials(employee["name"]),
                            names.get(employee["id"], th.tr_lower(employee["name"])), subtitle, description)
            ring.setToolTip(employee["name"] + f" · personel no {employee['id']}")
            ring.clicked.connect(lambda checked=False, e=employee: QTimer.singleShot(
                170, self, lambda: self.attendance(e)))
            self.grid.addWidget(ring, i // self.columns, i % self.columns)
        if not people:
            self.grid.addWidget(label("Personel bulunamadı. İlk personeli yönetici panelinden ekleyin."
                                      if not query else "Personel bulunamadı.", "subtitle"), 0, 0, 1, 4)

    def card_state(self, employee):
        """(ring state, progress 0..1, subtitle, accessible description) for one person."""
        now = self.service.clock.wall()
        opened = employee["session_id"] is not None
        locked = lock_seconds(self.service, employee.get("locked_until"))
        progress = 0.0
        if opened and self.service.past_day_boundary(employee["start_at"]):
            state, subtitle, words = "forgotten", "çıkış unutuldu", "Çıkış unutuldu"
        elif opened:
            elapsed = now - employee["start_at"]
            progress = elapsed / th.SHIFT_GOAL_SECONDS
            state, subtitle = "in", f"içeride · {th.clock_text(elapsed)}"
            words = f"İçeride {th.clock_text(elapsed)}"
        else:
            worked = self.today_seconds.get(employee["id"], 0)
            state = "out"
            subtitle = f"bugün {th.hours_text(worked)}" if worked >= 60 else "dışarıda"
            words = "Dışarıda"
        if locked:
            minutes, seconds = divmod(locked, 60)
            wait = f"{minutes} dk {seconds} sn" if minutes else f"{seconds} sn"
            state, subtitle = "locked", f"kilitli · {wait}"
            words = f"Kilitli · {wait} · {words}"
        description = f"{employee['name']} · {employee['id']} — {words}"
        return state, progress, subtitle, description

    def cards_state(self):
        return tuple((e["id"], *self.card_state(e)[:1], self.card_state(e)[2])
                     for e in getattr(self, "people", []))

    @guarded
    def heartbeat(self):
        if self.restoring:
            return
        alert = self.service.tick()
        notice = self.service.clock_status()[1]
        self.update_clock()
        people = getattr(self, "people", [])
        now = self.service.clock.wall()
        lines = []
        if alert:
            # Staff keep working; records are flagged for the admin.
            lines.append(alert + " Giriş/çıkışlar yönetici incelemesi için işaretleniyor.")
        # Anything only the admin can fix is a short count; details live in the admin panel.
        # Forgotten exits and open records older than 24 h, each person counted once.
        stuck = sum(1 for e in people if e["session_id"] and (self.service.past_day_boundary(e["start_at"])
                                                               or now - e["start_at"] > 86400))
        notes = stuck + bool(notice and not alert)
        if notes:
            lines.append(f"Yönetici için {notes} not var.")
        message = "\n".join(lines)
        self.warning.setText(message)
        self.warning.setVisible(bool(message))
        # Reload cheaply; re-render only when a ring would look different
        # (minute counters, lock countdown, admin unlock, day boundary).
        self.people = self.service.kiosk_employees()
        self.today_seconds = self.service.kiosk_today_seconds()
        if self.cards_state() != self.card_signature:
            self.render_people()
        try:
            automatic_backup(self.service.db, self.service.zone, self.verified_backups)
        except (AppError, sqlite3.Error, OSError):
            self.warning.setText((message + "\n" if message else "") +
                                 "Otomatik yedek alınamadı. Yönetici yedekleri kontrol etmeli.")
            self.warning.show()

    @guarded
    def attendance(self, employee):
        dialog = PinDialog(self.service, employee, self)
        if dialog.exec():
            self.welcome(employee, dialog)
        self.refresh()

    def welcome(self, employee, dialog):
        first = th.short_names(self.people).get(employee["id"], th.tr_lower(employee["name"]))
        summary = self.service.staff_summary(employee["id"], dialog.result_sid) if dialog.result_sid else {}
        month = th.hours_text(summary.get("month_seconds", 0))
        now = datetime.fromtimestamp(self.service.clock.wall(), self.service.zone)
        note = ""
        if dialog.action == "start":
            state, title = "in", f"hoş geldin, {first}"
            subtitle = f"giriş {now:%H:%M} · bu ay {month}"
            status = f"{first} giriş yaptı · {now:%H:%M}"
        else:
            state, title = "out", f"görüşürüz, {first}"
            subtitle = (f"çıkış {now:%H:%M} · bugün {th.hours_text(summary.get('session_seconds', 0))}"
                        f" · bu ay {month}")
            status = f"{first} çıkış yaptı · {now:%H:%M}"
        if dialog.forgotten:
            note = "gerçek çıkış saatini yönetici girecek"
        elif self.service.clock_status()[0]:
            note = "kayıt yönetici incelemesine işaretlendi"
        self.status.setText(status)
        WelcomeDialog(th.initials(employee["name"]), state, title, subtitle, note, self).exec()

    @guarded
    def admin(self):
        dialog = admin_login_dialog(self.service, self)
        if dialog.exec():
            AdminDialog(self.service, dialog.result_value, self).exec()
            if not self.restoring:
                self.refresh()
