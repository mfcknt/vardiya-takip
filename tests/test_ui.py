import time

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog

from conftest import PIN
from vardiya.ui import AdminDialog, EmployeeDialog, MainWindow, PaymentDialog, PinDialog, SessionDialog


def test_kiosk_touch_pin_start_finish_and_cancel(qapp, system):
    s, c, _, _ = system
    window = MainWindow(s)
    window.show()
    qapp.processEvents()
    assert window.grid.count() == 1
    employee = s.kiosk_employees()[0]
    dialog = PinDialog(s, employee, window)
    dialog.show()
    for digit in PIN:
        dialog.press(digit)
    QTest.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.pin.text() == ""
    c.advance(60)
    dialog = PinDialog(s, s.kiosk_employees()[0], window)
    dialog.pin.setText(PIN)
    dialog.confirm()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert s.kiosk_employees()[0]["session_id"] is None
    cancelled = PinDialog(s, s.kiosk_employees()[0], window)
    cancelled.pin.setText(PIN)
    cancelled.reject()
    assert cancelled.pin.text() == ""
    window.close()


def test_wrong_pin_stays_in_dialog(qapp, system):
    s, _, _, _ = system
    dialog = PinDialog(s, s.kiosk_employees()[0])
    dialog.pin.setText("019283")
    dialog.confirm()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.error.text()
    assert s.kiosk_employees()[0]["session_id"] is None
    dialog.reject()


def test_admin_tabs_forms_and_inactivity(qapp, system):
    s, _, token, _ = system
    panel = AdminDialog(s, token)
    panel.show()
    qapp.processEvents()
    assert panel.tabs.count() == 5
    assert panel.people_table.rowCount() == 1
    assert panel.report_table.rowCount() == 1
    for form in (EmployeeDialog(s, token), SessionDialog(s, token), PaymentDialog(s, token)):
        form.show()
        qapp.processEvents()
        form.reject()
    panel.last_input = time.monotonic() - 301
    panel.check_timeout()
    assert not panel.isVisible()
    assert token not in s._tokens


def test_search_filters_employee_cards(qapp, system):
    s, _, _, _ = system
    window = MainWindow(s)
    window.search.setText("bulunamaz")
    qapp.processEvents()
    assert "bulunamadı" in window.grid.itemAt(0).widget().text()
    window.search.clear()
    qapp.processEvents()
    assert "Ayşe" in window.grid.itemAt(0).widget().text()
    window.close()


def test_clock_alert_keeps_kiosk_usable_and_flags(qapp, system):
    s, c, token, _ = system
    window = MainWindow(s)
    window.show()
    s.tick()
    c.now -= 600
    window.heartbeat()
    assert window.cards.isEnabled()
    assert "işaretleniyor" in window.warning.text()
    dialog = PinDialog(s, s.kiosk_employees()[0], window)
    dialog.pin.setText(PIN)
    dialog.confirm()
    assert dialog.result() == QDialog.DialogCode.Accepted
    token = s.login_admin("Restoran!Guvenli2026")
    assert s.pending_reviews(token) == 1
    panel = AdminDialog(s, token)
    assert panel.review_note.text()
    panel.session_filter.review.setChecked(True)
    panel.refresh()
    assert panel.session_table.rowCount() == 1
    assert panel.session_table.item(0, 6).text()
    panel.reject()
    window.close()


def test_locked_staff_card_and_admin_status(qapp, system):
    s, c, token, eid = system
    import uuid
    from vardiya.security import AppError
    for _ in range(5):
        try:
            s.attendance(eid, "192837", "start", None, str(uuid.uuid4()))
        except AppError:
            pass
    window = MainWindow(s)
    window.refresh()
    assert "Kilitli" in window.grid.itemAt(0).widget().text()
    panel = AdminDialog(s, token)
    assert "Kilitli" in panel.people_table.item(0, 3).text()
    s.unlock_employee(token, eid, "Test için kilit kaldırıldı")
    panel.refresh()
    assert "Kilitli" not in panel.people_table.item(0, 3).text()
    window.heartbeat()
    assert "Kilitli" not in window.grid.itemAt(0).widget().text()
    panel.reject()
    window.close()


def test_admin_shows_turkish_money_actions_and_filters(qapp, system):
    s, c, token, eid = system
    import uuid
    s.manual_session(token, eid, c.now - 40 * 86400, c.now - 40 * 86400 + 3600, 15000,
                     "Eski kayıt eklendi", str(uuid.uuid4()))
    s.manual_session(token, eid, c.now - 3600, c.now, 15000, "Yeni kayıt eklendi", str(uuid.uuid4()))
    panel = AdminDialog(s, token)
    assert panel.people_table.item(0, 2).text() == "150,00"
    assert panel.session_table.rowCount() == 1  # default: last 30 days
    assert panel.audit_table.item(0, 3).text() == "Kayıt eklendi"
    assert "MB" in panel.backup_note.text()
    new = s.add_employee(token, "Can Arslan", "573819", 12000)
    panel.refresh()
    assert panel.session_filter.employee.findData(new) > 0
    panel.reject()


def test_forgotten_exit_card_pin_warning_and_report(qapp, system):
    import uuid
    from conftest import ts
    s, c, _, eid = system
    c.advance(ts("2026-10-20T17:00") - c.now)
    sid = s.attendance(eid, PIN, "start", None, str(uuid.uuid4()))
    window = MainWindow(s)
    window.show()
    window.refresh()
    assert "Çalışıyor" in window.grid.itemAt(0).widget().text()
    c.advance(ts("2026-10-21T05:10") - c.now)
    window.heartbeat()
    card = window.grid.itemAt(0).widget()
    assert "Çıkış yapılmamış" in card.text() and card.objectName() == "personForgotten"
    assert "Çıkışı yapılmamış 1 kayıt" in window.warning.text()
    dialog = PinDialog(s, s.kiosk_employees()[0], window)
    assert dialog.forgotten
    assert any("önceki iş gününden" in w.text() for w in dialog.findChildren(type(window.status)))
    dialog.pin.setText(PIN)
    dialog.confirm()
    assert dialog.result() == QDialog.DialogCode.Accepted
    token = s.login_admin("Restoran!Guvenli2026")
    panel = AdminDialog(s, token)
    # Business "today" at 05:10 is 21 Oct; the 20 Oct shift shows in the 30-day filter.
    assert panel.last.date().toPython().isoformat() == "2026-10-21"
    assert any(panel.session_table.item(r, 0).text() == str(sid) and panel.session_table.item(r, 6).text()
               for r in range(panel.session_table.rowCount()))
    assert "05:00" in panel.day_note.text()
    panel.reject()
    window.close()


def test_report_today_uses_business_day(qapp, system):
    from conftest import ts
    s, c, token, _ = system
    c.advance(ts("2026-10-21T00:30") - c.now)
    token = s.login_admin("Restoran!Guvenli2026")
    panel = AdminDialog(s, token)
    panel.today()
    assert panel.first.date().toPython().isoformat() == "2026-10-20"
    assert panel.report_table.columnCount() == 8
    panel.reject()


def test_light_theme_is_forced_even_in_dark_mode(qapp):
    from PySide6.QtGui import QPalette
    from vardiya.ui import apply_light_theme
    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Window, Qt.GlobalColor.black)
    qapp.setPalette(dark)
    apply_light_theme(qapp)
    palette = qapp.palette()
    assert palette.color(QPalette.ColorRole.Window).lightness() > 200
    assert palette.color(QPalette.ColorRole.Base).lightness() > 200
    assert palette.color(QPalette.ColorRole.WindowText).lightness() < 100
