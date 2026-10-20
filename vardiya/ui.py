import logging
import sqlite3
import time
import uuid
from datetime import date, datetime
from functools import wraps
from pathlib import Path

from datetime import timedelta

from PySide6.QtCore import QDate, QDateTime, QEvent, QTime, Qt, QTimer
from PySide6.QtGui import QFont, QRegularExpressionValidator
from PySide6.QtCore import QRegularExpression
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateEdit, QDateTimeEdit, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QScroller, QSizePolicy, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .backup import automatic_backup, backup_usage, create_backup, restore_database
from .formatting import cents, tl
from .reports import build_report, duration, export_audit, export_report
from .security import AppError
from .storage import inspect_database

STYLE = """
QWidget { font-family: "Segoe UI", "Arial"; font-size: 16px; color: #183d3c; }
QMainWindow, QDialog { background: #f3f5ef; }
QLabel#title { font-size: 30px; font-weight: 700; }
QLabel#subtitle { color: #5a706b; font-size: 16px; }
QLabel#warning { background: #fff0d5; color: #804311; padding: 14px; border-radius: 10px; }
QLabel#success { background: #dceee2; color: #19543c; padding: 14px; border-radius: 10px; }
QPushButton { min-height: 48px; padding: 5px 16px; border-radius: 9px;
              border: 1px solid #cbd8d1; background: #ffffff; font-weight: 600; }
QPushButton:hover { background: #e3eee5; border-color: #548d76; }
QPushButton:pressed { background: #c8dfd1; }
QPushButton:disabled { color: #899792; background: #e8ece7; }
QPushButton#primary { color: white; background: #176b52; border: none; }
QPushButton#primary:hover { background: #12553f; }
QPushButton#danger { color: #8f362a; background: #f9e8e1; }
QPushButton#person { text-align: left; font-size: 20px; padding: 20px; min-height: 94px; }
QPushButton#personForgotten { text-align: left; font-size: 20px; padding: 20px;
                        min-height: 94px; background: #fde3c4; border-color: #c46a1b; color: #6b3409; }
QPushButton#personOpen { text-align: left; font-size: 20px; padding: 20px;
                        min-height: 94px; background: #dceee2; border-color: #68a180; }
QLineEdit, QComboBox, QDateEdit, QDateTimeEdit { background: white; border: 1px solid #cbd8d1;
    padding: 9px; min-height: 32px; border-radius: 6px; selection-background-color: #176b52; }
QTableWidget { background: white; border: 1px solid #d8e0d8; gridline-color: #e4eae4;
               selection-background-color: #d6eade; selection-color: #173d3c; }
QHeaderView::section { background: #e9eee7; padding: 12px; border: 0; font-weight: 600; }
QTabBar::tab { padding: 14px 18px; background: #e9eee7; }
QTabBar::tab:selected { background: #176b52; color: white; }
QScrollBar:vertical { width: 22px; }
QCheckBox { min-height: 42px; color: #183d3c; background: transparent; }
QTabWidget::pane { background: #f3f5ef; border: 1px solid #d8e0d8; }
QTabWidget > QWidget, QScrollArea, QScrollArea > QWidget > QWidget { background: #f3f5ef; }
QCheckBox::indicator { width: 24px; height: 24px; }
"""


def apply_light_theme(app):
    """Always use the app's own light design, even in macOS/Windows dark mode.

    The stylesheet only colors some widgets; without a fixed light palette the
    rest (tab pages, checkbox labels) followed the OS dark scheme and became
    unreadable (dark text on dark gray).
    """
    from PySide6.QtGui import QColor, QPalette
    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    except AttributeError:
        pass  # Qt < 6.8
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#f3f5ef", QPalette.ColorRole.WindowText: "#183d3c",
        QPalette.ColorRole.Base: "#ffffff", QPalette.ColorRole.AlternateBase: "#f4f7f2",
        QPalette.ColorRole.Text: "#183d3c", QPalette.ColorRole.Button: "#ffffff",
        QPalette.ColorRole.ButtonText: "#183d3c", QPalette.ColorRole.Highlight: "#176b52",
        QPalette.ColorRole.HighlightedText: "#ffffff", QPalette.ColorRole.ToolTipBase: "#ffffff",
        QPalette.ColorRole.ToolTipText: "#183d3c", QPalette.ColorRole.PlaceholderText: "#6f817c",
        QPalette.ColorRole.Link: "#176b52", QPalette.ColorRole.BrightText: "#ffffff",
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#899792"))
    app.setPalette(palette)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)


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


def button(text, callback, primary=False, danger=False):
    b = QPushButton(text)
    if primary:
        b.setObjectName("primary")
    elif danger:
        b.setObjectName("danger")
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


ACTION_NAMES = {
    "SETUP": "İlk kurulum", "CLOCK_ALERT": "Saat uyarısı", "CLOCK_NOTICE": "Saat bildirimi",
    "CLOCK_ACK": "Saat kontrol edildi", "AUTH_LOCK": "Giriş kilidi", "AUTH_UNLOCK": "Kilit kaldırıldı",
    "PASSWORD_CHANGE": "Şifre değişti", "EMPLOYEE_ADD": "Personel eklendi",
    "EMPLOYEE_UPDATE": "Personel düzenlendi", "START": "İşe başladı", "END": "İşi bitirdi",
    "SESSION_MANUAL": "Kayıt eklendi", "SESSION_CORRECT": "Kayıt düzeltildi",
    "SESSION_VOID": "Kayıt iptal", "PAYMENT_ADD": "Ödeme eklendi", "PAYMENT_VOID": "Ödeme iptal",
    "RESTORE": "Yedekten kurtarma", "SESSION_FLAG": "Çıkış yapılmamış", "SETTING_CHANGE": "Ayar değişti",
}
AUDIT_SCREEN_LIMIT = 1000


def action_name(code):
    return ACTION_NAMES.get(code, code)


def lock_text(service, locked_until):
    remaining = (locked_until or 0) - service.clock.wall()
    if remaining <= 0:
        return ""
    minutes, seconds = divmod(remaining, 60)
    return f"Kilitli · {minutes} dk {seconds} sn" if minutes else f"Kilitli · {seconds} sn"


def make_table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    t.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(48)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    t.horizontalHeader().setStretchLastSection(True)
    t.setAlternatingRowColors(True)
    QScroller.grabGesture(t.viewport(), QScroller.ScrollerGestureType.TouchGesture)
    return t


def fill_table(table, rows):
    table.setRowCount(len(rows))
    for y, row in enumerate(rows):
        for x, value in enumerate(row):
            table.setItem(y, x, QTableWidgetItem(str(value)))


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
        box.addWidget(label("En az 12 karakter. Bu şifre personel PIN’lerinden ayrıdır."
                            if setup else "Yönetici şifrenizi girin.", "subtitle"))
        self.password = secret_edit()
        box.addWidget(self.password)
        self.repeat = secret_edit() if setup else None
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


class PinDialog(QDialog):
    def __init__(self, service, employee, parent=None):
        super().__init__(parent)
        self.service, self.employee = service, employee
        self.action = "end" if employee["session_id"] else "start"
        self.request_id = str(uuid.uuid4())
        self.setWindowTitle("Personel doğrulama")
        self.setFixedWidth(430)
        box = QVBoxLayout(self)
        box.addWidget(label(employee["name"], "title"))
        box.addWidget(label(f"Personel no: {employee['id']} · 6 haneli PIN’inizi girin", "subtitle"))
        self.forgotten = bool(employee["session_id"]) and service.past_day_boundary(employee["start_at"])
        if self.forgotten:
            box.addWidget(label("Giriş: " + service.display_time(employee["start_at"]) +
                                "\nBu kayıt önceki iş gününden açık kalmış; çıkış yapılmamış. "
                                "Şimdi kapatabilirsin, kayıt yöneticiye işaretlenir ve gerçek çıkış "
                                "saatini yönetici girer. Ardından yeni giriş yapabilirsin.", "warning"))
        elif employee["session_id"]:
            box.addWidget(label("Giriş: " + service.display_time(employee["start_at"]), "success"))
        self.pin = secret_edit(6)
        self.pin.setValidator(QRegularExpressionValidator(QRegularExpression("[0-9]{0,6}")))
        self.pin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pin.setFont(QFont("Segoe UI", 28))
        self.pin.setAccessibleName("Altı haneli personel PIN")
        box.addWidget(self.pin)
        grid = QGridLayout()
        for i, text in enumerate(["1", "2", "3", "4", "5", "6", "7", "8", "9", "Temizle", "0", "Sil"]):
            b = button(text, lambda checked=False, t=text: self.press(t))
            b.setMinimumHeight(62)
            grid.addWidget(b, i // 3, i % 3)
        box.addLayout(grid)
        self.error = label("", "warning")
        self.error.hide()
        box.addWidget(self.error)
        self.confirm_button = button("İŞİ BİTİR" if self.action == "end" else "İŞE BAŞLA",
                                     self.confirm, True)
        box.addWidget(self.confirm_button)
        box.addWidget(button("Vazgeç", self.reject))
        self.pin.returnPressed.connect(self.confirm)
        # Short-lived PIN screen, even if nobody presses a button.
        QTimer.singleShot(60_000, self, self.reject)

    def press(self, text):
        if text == "Temizle":
            self.pin.clear()
        elif text == "Sil":
            self.pin.backspace()
        else:
            self.pin.insert(text)

    def confirm(self):
        self.confirm_button.setEnabled(False)
        try:
            self.service.attendance(self.employee["id"], self.pin.text(), self.action,
                                    self.employee["session_id"], self.request_id)
            self.pin.clear()
            self.accept()
        except (AppError, sqlite3.Error, OSError) as exc:
            self.error.setText(str(exc) if isinstance(exc, AppError) else
                               "İşlem doğrulanamadı. Yönetici kayıtları kontrol etmeli.")
            self.error.show()
            self.pin.clear()
        finally:
            self.confirm_button.setEnabled(True)

    def done(self, result):
        self.pin.clear()
        super().done(result)


class EmployeeDialog(FormDialog):
    def __init__(self, service, token, employee=None, parent=None):
        super().__init__("Personel düzenle" if employee else "Yeni personel", parent)
        self.service, self.token, self.employee = service, token, employee
        self.name = QLineEdit(employee["name"] if employee else "")
        self.name.setMaxLength(80)
        self.pin = secret_edit(6)
        self.pin.setPlaceholderText("Değiştirmemek için boş bırakın" if employee else "6 rakam")
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


class FilterBar(QWidget):
    """Date range + employee filter; default is the last 30 days."""
    def __init__(self, service, token, on_apply, review_toggle=False, parent=None):
        super().__init__(parent)
        self.service = service
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        today = service.business_day(service.clock.wall())
        start = today - timedelta(days=29)
        self.first = QDateEdit(QDate(start.year, start.month, start.day))
        self.last = QDateEdit(QDate(today.year, today.month, today.day))
        for w in (self.first, self.last):
            w.setCalendarPopup(True)
            w.setDisplayFormat("dd.MM.yyyy")
            row.addWidget(w)
        self.employee = QComboBox()
        self.employee.addItem("Tüm personel", None)
        for e in service.employees(token):
            self.employee.addItem(f"{e['name']} · No {e['id']}", e["id"])
        row.addWidget(self.employee)
        self.review = QCheckBox("Yalnızca inceleme bekleyenler") if review_toggle else None
        if self.review:
            row.addWidget(self.review)
        row.addWidget(button("Filtrele", on_apply))
        row.addStretch()

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
        first, last = self.first.date().toPython(), self.last.date().toPython()
        if last < first:
            raise AppError("Bitiş tarihi başlangıçtan önce olamaz.")
        since, until = self.service.day_bounds(first, last)
        return {"eid": self.employee.currentData(), "since": since, "until": until}

    def review_only(self):
        return bool(self.review and self.review.isChecked())


class AdminDialog(QDialog):
    def __init__(self, service, token, parent=None):
        super().__init__(parent)
        self.service, self.token = service, token
        self.last_input = time.monotonic()
        self.setWindowTitle("Yönetici paneli")
        self.resize(1160, 780)
        self.setMinimumSize(880, 620)
        box = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(label("Yönetici paneli", "title"))
        top.addStretch()
        top.addWidget(button("Oturumu kapat", self.accept))
        box.addLayout(top)
        box.addWidget(label("Ön hak ediş • Resmî bordro değildir • 5 dakika hareketsizlikte kilitlenir",
                            "subtitle"))
        self.tabs = QTabWidget()
        box.addWidget(self.tabs)
        self.people_tab()
        self.sessions_tab()
        self.reports_tab()
        self.payments_tab()
        self.security_tab()
        self.refresh()
        QApplication.instance().installEventFilter(self)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_timeout)
        self.timer.start(1000)

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
        QApplication.instance().removeEventFilter(self)
        self.service.logout(self.token)
        super().done(result)

    def tab(self, title):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.tabs.addTab(page, title)
        return layout

    def toolbar(self, layout, actions):
        row = QHBoxLayout()
        for title, callback in actions:
            row.addWidget(button(title, callback))
        row.addStretch()
        layout.addLayout(row)

    def people_tab(self):
        box = self.tab("Personel")
        self.toolbar(box, [("Personel ekle", self.add_employee), ("Seçileni düzenle", self.edit_employee),
                           ("Kilidi kaldır", self.unlock_employee)])
        self.people_table = make_table(["No", "Ad Soyad", "Saatlik TL", "Durum"])
        box.addWidget(self.people_table)

    def sessions_tab(self):
        box = self.tab("Giriş / çıkış")
        self.session_filter = FilterBar(self.service, self.token, self.refresh, review_toggle=True)
        box.addWidget(self.session_filter)
        self.review_note = label("", "warning")
        self.review_note.hide()
        box.addWidget(self.review_note)
        self.toolbar(box, [("Eksik kayıt ekle", self.add_session), ("Seçileni düzelt", self.edit_session)])
        self.session_table = make_table(["Kayıt", "Personel", "Giriş", "Çıkış", "Saatlik TL", "Durum",
                                         "İnceleme"])
        box.addWidget(self.session_table)

    def reports_tab(self):
        box = self.tab("Hak ediş")
        dates = QHBoxLayout()
        today = self.service.business_day(self.service.clock.wall())
        self.first = QDateEdit(QDate(today.year, today.month, 1))
        self.last = QDateEdit(QDate(today.year, today.month, today.day))
        for w in (self.first, self.last):
            w.setCalendarPopup(True)
            w.setDisplayFormat("dd.MM.yyyy")
        dates.addWidget(self.first)
        dates.addWidget(self.last)
        dates.addWidget(button("Bugün", self.today))
        dates.addWidget(button("Bu ay", self.this_month))
        dates.addWidget(button("Hesapla", self.calculate, True))
        box.addLayout(dates)
        self.report_note = label("Açık kayıtlar geçici tahmindir ve bakiyeye eklenmez.", "warning")
        box.addWidget(self.report_note)
        self.report_table = make_table(["Personel", "Kapalı süre", "Ön hak ediş TL", "Açık tahmini TL",
                                       "Ödeme/avans TL", "Devreden TL", "Bakiye TL", "İnceleme"])
        box.addWidget(self.report_table)
        self.toolbar(box, [("CSV indir", lambda: self.export(".csv")),
                           ("Excel indir", lambda: self.export(".xlsx"))])
        self.report = None

    def payments_tab(self):
        box = self.tab("Ödeme / avans")
        self.payment_filter = FilterBar(self.service, self.token, self.refresh)
        box.addWidget(self.payment_filter)
        self.toolbar(box, [("Ödeme / avans ekle", self.add_payment), ("Seçileni iptal et", self.void_payment)])
        self.payment_table = make_table(["Kayıt", "Personel", "Tarih", "Tür", "Tutar TL", "Açıklama", "Durum"])
        box.addWidget(self.payment_table)

    def security_tab(self):
        box = self.tab("Güvenlik / yedek")
        self.clock_note = label("", "warning")
        box.addWidget(self.clock_note)
        self.toolbar(box, [("Saati kontrol ettim", self.ack_clock), ("Şifre değiştir", self.change_password)])
        self.day_note = label("", "subtitle")
        box.addWidget(self.day_note)
        self.toolbar(box, [("İş günü başlangıcını değiştir", self.change_day_start)])
        self.toolbar(box, [("Bütünlüğü denetle", self.check_integrity), ("Yedek al", self.backup),
                           ("Yedekten kurtar", self.restore)])
        box.addWidget(label("Veri klasörü: " + str(self.service.db.path.parent), "subtitle"))
        self.backup_note = label("", "subtitle")
        box.addWidget(self.backup_note)
        self.audit_note = label("", "subtitle")
        box.addWidget(self.audit_note)
        self.audit_table = make_table(["No", "Tarih", "Yapan", "İşlem", "Kayıt", "Gerekçe"])
        box.addWidget(self.audit_table)
        self.toolbar(box, [("Geçmiş ayrıntısı", self.audit_detail), ("Geçmişi CSV indir", self.audit_export)])

    @guarded
    def refresh(self):
        self.people = self.service.employees(self.token)
        for bar in (self.session_filter, self.payment_filter):
            bar.sync_employees(self.people)
        fill_table(self.people_table, [[e["id"], e["name"], tl(e["rate_cents"]),
                                       " · ".join(x for x in ("Aktif" if e["active"] else "Arşiv",
                                                              lock_text(self.service, e["locked_until"])) if x)]
                                      for e in self.people])
        f = self.session_filter.values()
        self.session_rows = self.service.sessions(self.token, f["eid"], f["since"], f["until"],
                                                  self.session_filter.review_only())
        fill_table(self.session_table, [[s["id"], s["name"], self.service.display_time(s["start_at"]),
                                        self.service.display_time(s["end_at"]), tl(s["rate_cents"]),
                                        "İptal" if s["voided"] else "Açık" if s["end_at"] is None else "Kapalı",
                                        "" if s["voided"] else s["review"]]
                                       for s in self.session_rows])
        pending = self.service.pending_reviews(self.token)
        self.review_note.setText(f"İnceleme bekleyen {pending} kayıt var. “Yalnızca inceleme bekleyenler” "
                                 "ile listeleyip saatleri kontrol ederek kaydedin.")
        self.review_note.setVisible(bool(pending))
        f = self.payment_filter.values()
        self.payment_rows = self.service.payments(self.token, f["eid"], f["since"], f["until"])
        fill_table(self.payment_table, [[p["id"], p["name"], self.service.display_time(p["paid_at"]),
                                        p["kind"], tl(p["amount_cents"]), p["note"],
                                        "İptal" if p["voided"] else "Geçerli"] for p in self.payment_rows])
        self.audit = self.service.audit_rows(self.token, AUDIT_SCREEN_LIMIT)
        fill_table(self.audit_table, [[a["id"], self.service.display_time(a["at"]), a["actor"],
                                      action_name(a["action"]), a["entity"], a["reason"]] for a in self.audit])
        self.audit_note.setText(f"Ekranda son {AUDIT_SCREEN_LIMIT} işlem gösterilir; "
                                "tamamı için “Geçmişi CSV indir”.")
        alert, notice = self.service.clock_status()
        self.clock_note.setText("\n".join(x for x in (alert, notice) if x) or "Saat şüphesi bulunmuyor.")
        self.day_note.setText(f"İş günü her gün {self.service.day_start_hour:02d}:00’da başlar. "
                              "Bu saatten önceki çalışma ve ödemeler önceki güne yazılır; "
                              "bu saati geçen açık kayıtlar “çıkış yapılmamış” olarak işaretlenir.")
        count, size = backup_usage(self.service.db)
        self.backup_note.setText(f"Otomatik yedekler: {count} dosya, {size / 1_048_576:.1f} MB. "
                                 "Son 30 gün, her ayın ilk yedeği ve son 20 kapanış yedeği saklanır; "
                                 "elle alınan yedekler silinmez.")
        self.calculate()

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

    def today(self):
        day = self.service.business_day(self.service.clock.wall())
        q = QDate(day.year, day.month, day.day)
        self.first.setDate(q)
        self.last.setDate(q)
        self.calculate()

    def this_month(self):
        day = self.service.business_day(self.service.clock.wall())
        self.first.setDate(QDate(day.year, day.month, 1))
        self.last.setDate(QDate(day.year, day.month, day.day))
        self.calculate()

    @guarded
    def calculate(self):
        self.report = build_report(self.service, self.token, self.first.date().toPython(),
                                   self.last.date().toPython())
        fill_table(self.report_table, [[r["name"], duration(r["seconds"]), tl(r["cents"]),
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
        report = build_report(self.service, self.token, self.first.date().toPython(),
                              self.last.date().toPython())
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
        dialog = PasswordDialog("Kurtarma için yönetici doğrulaması", self,
                                submit=lambda pw: (self.service._authenticate("admin", pw), pw)[1])
        if not dialog.exec():
            return
        self.service.require_admin(self.token)
        db_path = self.service.db.path
        if isinstance(self.parent(), MainWindow):
            self.parent().restoring = True
            self.parent().timer.stop()
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
        dlg = FormDialog("Yönetici şifresini değiştir", self)
        old, new, repeat = secret_edit(), secret_edit(), secret_edit()
        dlg.form.addRow("Mevcut şifre", old)
        dlg.form.addRow("Yeni şifre", new)
        dlg.form.addRow("Yeni şifre tekrar", repeat)

        @guarded
        def save(_dialog):
            if new.text() != repeat.text():
                raise AppError("Yeni şifreler aynı değil.")
            self.service.change_password(self.token, old.text(), new.text())
            old.clear()
            new.clear()
            repeat.clear()
            dlg.accept()
            self.accept()
        dlg.buttons.accepted.connect(lambda: save(dlg))
        dlg.finished.connect(lambda _: [field.clear() for field in (old, new, repeat)])
        dlg.exec()

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
    def __init__(self, service):
        super().__init__()
        self.service = service
        self.restoring = False
        self.verified_backups = set()
        self.card_signature = None
        self.setWindowTitle("Vardiya Takip")
        self.resize(1120, 780)
        self.setMinimumSize(760, 580)
        root = QWidget()
        self.setCentralWidget(root)
        box = QVBoxLayout(root)
        box.setContentsMargins(30, 24, 30, 20)
        box.setSpacing(18)
        top = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(label("Vardiya Takip", "title"))
        titles.addWidget(label("İşe başlamak veya işi bitirmek için adınızı seçin.", "subtitle"))
        top.addLayout(titles)
        top.addStretch()
        top.addWidget(button("Yönetici", self.admin))
        box.addLayout(top)
        self.clock_label = label("", "subtitle")
        box.addWidget(self.clock_label)
        self.warning = label("", "warning")
        box.addWidget(self.warning)
        self.status = label("Hazır • Tüm kayıtlar bu bilgisayarda tutulur.", "success")
        box.addWidget(self.status)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Personel ara…")
        self.search.textChanged.connect(self.render_people)
        box.addWidget(self.search)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.cards = QWidget()
        self.grid = QGridLayout(self.cards)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.grid.setSpacing(16)
        scroll.setWidget(self.cards)
        QScroller.grabGesture(scroll.viewport(), QScroller.ScrollerGestureType.TouchGesture)
        box.addWidget(scroll, 1)
        box.addWidget(label("ÇEVRİMDIŞI  •  Personel işlemleri için 6 haneli PIN",
                            "subtitle"))
        self.refresh()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.heartbeat)
        self.timer.start(15_000)

    @guarded
    def refresh(self):
        self.people = self.service.kiosk_employees()
        self.render_people()
        self.heartbeat()

    def render_people(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        query = self.search.text().casefold()
        people = [e for e in getattr(self, "people", []) if query in e["name"].casefold()]
        self.card_signature = self.cards_state()
        for i, employee in enumerate(people):
            state, style = self.card_state(employee)
            text = employee["name"] + f"  ·  {employee['id']}\n" + state
            b = button(text, lambda checked=False, e=employee: self.attendance(e))
            b.setObjectName(style)
            b.setAccessibleName(text.replace("\n", ". "))
            b.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            b.ensurePolished()
            short_name = b.fontMetrics().elidedText(
                employee["name"] + f" · {employee['id']}", Qt.TextElideMode.ElideRight,
                max(180, (self.width() - 108) // 2 - 45))
            b.setText(short_name + "\n" + state)
            b.setToolTip(employee["name"] + f" · Personel no: {employee['id']}")
            self.grid.addWidget(b, i // 2, i % 2)
        if not people:
            self.grid.addWidget(label("Personel bulunamadı. İlk personeli Yönetici panelinden ekleyin.",
                                      "subtitle"), 0, 0)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)

    def card_state(self, employee):
        """(second line of the card, style name) for one kiosk card."""
        opened = employee["session_id"] is not None
        if opened and self.service.past_day_boundary(employee["start_at"]):
            state, style = "Çıkış yapılmamış  →  İşi bitir", "personForgotten"
        elif opened:
            state, style = "Çalışıyor  →  İşi bitir", "personOpen"
        else:
            state, style = "Hazır  →  İşe başla", "person"
        locked = lock_text(self.service, employee.get("locked_until"))
        return (locked + "  ·  " + state if locked else state), style

    def cards_state(self):
        return tuple((e["id"], *self.card_state(e)) for e in getattr(self, "people", []))

    @guarded
    def heartbeat(self):
        if self.restoring:
            return
        alert = self.service.tick()
        notice = self.service.clock_status()[1]
        self.clock_label.setText(self.service.display_time(self.service.clock.wall()) +
                                 "  ·  " + str(self.service.zone))
        long_open = any(e["start_at"] is not None and self.service.clock.wall() - e["start_at"] > 86400
                        for e in getattr(self, "people", []))
        lines = []
        if alert:
            # Staff keep working; records are flagged for the admin.
            lines.append(alert + " Giriş/çıkışlar yönetici incelemesi için işaretleniyor.")
        elif notice:
            lines.append("Yönetici: " + notice)
        forgotten = sum(1 for e in getattr(self, "people", [])
                        if e["session_id"] and self.service.past_day_boundary(e["start_at"]))
        if forgotten:
            lines.append(f"Çıkışı yapılmamış {forgotten} kayıt var. Yönetici gerçek çıkış saatini girmeli.")
        if long_open:
            lines.append("24 saati aşan açık kayıt var. Yönetici kontrol etmeli.")
        message = "\n".join(lines)
        self.warning.setText(message)
        self.warning.setVisible(bool(message))
        # Reload cheaply; re-render only when a card would look different
        # (lock countdown, admin unlock, crossing the business-day boundary).
        self.people = self.service.kiosk_employees()
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
            text = "Çıkış kaydedildi." if employee["session_id"] else "Giriş kaydedildi."
            if dialog.forgotten:
                text += " Gerçek çıkış saatini yönetici girecek."
            elif self.service.clock_status()[0]:
                text += " Kayıt yönetici incelemesine işaretlendi."
            self.status.setText(text)
        self.refresh()

    @guarded
    def admin(self):
        dialog = PasswordDialog("Yönetici girişi", self, submit=self.service.login_admin)
        if dialog.exec():
            AdminDialog(self.service, dialog.result_value, self).exec()
            if not self.restoring:
                self.refresh()
