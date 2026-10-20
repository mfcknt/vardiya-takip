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
