"""Custom-painted Ó'is widgets: the Ó ring, backdrop watermark, timeline, heatmap.

Touch feedback uses short QVariantAnimations (≤ 0.7 s) that repaint only the
widget being touched; nothing runs while the screen is idle. Set the
environment variable VARDIYA_ANIMATIONS=0 to switch them off on weak hardware.
"""
import math
import os
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontDatabase, QIcon, QImage, QPainter, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractButton, QDialog, QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from . import theme as th

ASSETS = Path(__file__).resolve().parent / "assets"
_state = {"tokens": th.tokens(th.DEFAULT_THEME), "fonts": False}


def current():
    return _state["tokens"]


def set_current(tokens):
    _state["tokens"] = tokens


def load_fonts():
    """Register the bundled Jost and Quicksand fonts once (OFL, see assets/fonts)."""
    if _state["fonts"]:
        return
    for name in ("Jost.ttf", "Quicksand.ttf"):
        path = ASSETS / "fonts" / name
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))
    _state["fonts"] = True


def font(family="Quicksand", size=14, weight=QFont.Weight.Normal):
    f = QFont(family)
    f.setPixelSize(int(size))
    f.setWeight(weight)
    return f


ANIMATIONS = os.environ.get("VARDIYA_ANIMATIONS", "1") != "0"


def animate(owner, name, start, end, ms, setter, easing=QEasingCurve.Type.OutCubic, delay=0):
    """Run one short value animation owned by `owner` (replaces a running one of the same name)."""
    running = getattr(owner, "_anim_" + name, None)
    if running is not None:
        running.stop()
    if not ANIMATIONS or ms <= 0:
        setter(end)
        return None
    anim = QVariantAnimation(owner)
    anim.setStartValue(float(start))
    anim.setEndValue(float(end))
    anim.setDuration(ms)
    anim.setEasingCurve(easing)
    anim.valueChanged.connect(lambda value: setter(float(value)))
    setattr(owner, "_anim_" + name, anim)
    if delay:
        setter(float(start))
        QTimer.singleShot(delay, owner, anim.start)
    else:
        anim.start()
    return anim


def with_alpha(hex_color, alpha):
    c = QColor(hex_color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def color(key):
    return QColor(current()[key])


def logo_pixmap(color_hex, height, ratio=1.0):
    """The café logo recoloured to `color_hex` (the asset is a white alpha mask)."""
    image = QImage(str(ASSETS / "logo.png"))
    if image.isNull():
        return QPixmap()
    target_h = max(1, int(height * ratio))
    image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied).scaledToHeight(
        target_h, Qt.TransformationMode.SmoothTransformation)
    out = QImage(image.size(), QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(QColor(color_hex))
    painter = QPainter(out)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.drawImage(0, 0, image)
    painter.end()
    pixmap = QPixmap.fromImage(out)
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def app_icon():
    path = ASSETS / "icon.png"
    return QIcon(str(path)) if path.exists() else QIcon()


# --- the Ó ring ---------------------------------------------------------------

def paint_ring(p, cx, cy, r, state, progress, letters, t=None, hover=0.0, reveal=1.0):
    """Draw one person as a thin 'Ó'.

    state: in (accent lit, ring fills with the shift), out (dim ring),
    forgotten (dashed honey ring, tilted accent), locked (rose ring).
    hover: 0..1 strength of the soft touch disc; reveal: 0..1 draw-in progress
    (the ring sweeps in first, the accent appears in the last 40%).
    """
    hover, reveal = float(hover), max(0.0, min(1.0, float(reveal)))
    t = t or current()
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setBrush(Qt.BrushStyle.NoBrush)
    box = QRectF(cx - r, cy - r, 2 * r, 2 * r)
    s = r / 42.0
    if hover > 0.01:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(with_alpha(t["surface2"], hover))
        grow = 4 + 6 * hover
        p.drawEllipse(box.adjusted(-grow * s, -grow * s, grow * s, grow * s))
        p.setBrush(Qt.BrushStyle.NoBrush)
    accent_alpha = max(0.0, (reveal - 0.6) / 0.4)

    def pen(key, width, style=Qt.PenStyle.SolidLine, alpha=1.0):
        q = QPen(with_alpha(t[key], alpha), width * s)
        q.setCapStyle(Qt.PenCapStyle.RoundCap)
        q.setStyle(style)
        return q

    def accent(key, tilted=False):
        if accent_alpha <= 0:
            return
        if tilted:
            a, b = QPointF(cx + 0.14 * r, cy - 1.05 * r), QPointF(cx + 0.29 * r, cy - 1.29 * r)
        else:
            a, b = QPointF(cx + 0.19 * r, cy - 1.14 * r), QPointF(cx + 0.43 * r, cy - 1.33 * r)
        lift = (1 - accent_alpha) * 0.12 * r       # the accent drops into place
        p.setPen(pen(key, 3.2, alpha=accent_alpha))
        p.drawLine(QPointF(a.x(), a.y() - lift), QPointF(b.x(), b.y() - lift))

    text_key = "muted"
    if state == "in":
        p.setPen(pen("ring_track", 2))
        p.drawEllipse(box)
        sweep = max(0.02, min(1.0, progress)) * min(1.0, reveal / 0.8)
        p.setPen(pen("ring", 2.6))
        p.drawArc(box, 90 * 16, -int(360 * 16 * sweep))
        accent("ring")
        text_key = "ring"
    elif state == "forgotten":
        q = pen("warn", 2)
        q.setDashPattern([2.0, 3.0])
        p.setPen(q)
        p.drawEllipse(box)
        accent("warn", tilted=True)
        text_key = "warn_text"
    elif state == "locked":
        p.setPen(pen("lock", 2))
        p.drawEllipse(box)
        text_key = "lock"
    else:
        p.setPen(pen("ring_idle", 1.5, alpha=0.4 + 0.6 * reveal))
        p.drawEllipse(box)
    p.setPen(with_alpha(t[text_key], 0.3 + 0.7 * reveal))
    size = 24 * s if r > 20 else max(24 * s, r * 0.95)   # tiny avatars stay legible
    p.setFont(font("Jost", size, QFont.Weight.Light if r > 20 else QFont.Weight.Normal))
    p.drawText(box.adjusted(-r, 0, r, 0), Qt.AlignmentFlag.AlignCenter, letters)
    if state == "locked":
        # small padlock under the letters
        w, h = 10 * s, 8 * s
        x, y = cx - w / 2, cy + 0.42 * r
        p.setPen(pen("lock", 1.4))
        p.drawRoundedRect(QRectF(x, y, w, h), 2 * s, 2 * s)
        p.drawArc(QRectF(x + 2 * s, y - 5 * s, w - 4 * s, 9 * s), 0, 180 * 16)
    p.restore()


class PersonRing(QAbstractButton):
    """A kiosk tile: the ring plus lowercase name and a short status line."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.state, self.progress, self.letters = "out", 0.0, ""
        self.title, self.subtitle = "", ""
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(160, 186)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.press_level = 0.0    # 0 = rest, 1 = fully pressed
        self.hover_level = 0.0
        self.pressed.connect(self._on_press)
        self.released.connect(self._on_release)

    def _set_press(self, value):
        self.press_level = value
        self.update()

    def _set_hover(self, value):
        self.hover_level = value
        self.update()

    def _on_press(self):
        animate(self, "press", self.press_level, 1.0, 90, self._set_press)
        animate(self, "hover", self.hover_level, 1.0, 90, self._set_hover)

    def _on_release(self):
        # spring back slightly past rest, like a soft button
        animate(self, "press", self.press_level, 0.0, 280, self._set_press, QEasingCurve.Type.OutBack)
        animate(self, "hover", self.hover_level, 0.0 if not self.underMouse() else 0.5, 320, self._set_hover)

    def enterEvent(self, event):
        animate(self, "hover", self.hover_level, 0.5, 140, self._set_hover)
        super().enterEvent(event)

    def leaveEvent(self, event):
        animate(self, "hover", self.hover_level, 0.0, 200, self._set_hover)
        super().leaveEvent(event)

    def set_person(self, state, progress, letters, title, subtitle, description):
        self.state, self.progress, self.letters = state, progress, letters
        self.title, self.subtitle = title, subtitle
        self.setText(description)          # accessible text; tests read it too
        self.setAccessibleName(description)
        self.setObjectName("ring_" + state)
        self.update()

    def sizeHint(self):
        return QSize(160, 186)

    def paintEvent(self, _event):
        t = current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        scale = 1.0 - 0.07 * self.press_level
        if scale != 1.0:
            p.translate(self.width() / 2, 80)
            p.scale(scale, scale)
            p.translate(-self.width() / 2, -80)
        paint_ring(p, self.width() / 2, 80, 46, self.state, self.progress, self.letters, t,
                   self.hover_level)
        p.resetTransform()
        name_key = {"in": "text", "forgotten": "warn_text", "locked": "lock"}.get(self.state, "muted")
        p.setPen(QColor(t[name_key] if self.state != "out" else t["text"]))
        p.setFont(font("Quicksand", 16, QFont.Weight.Medium))
        metrics = p.fontMetrics()
        title = metrics.elidedText(self.title, Qt.TextElideMode.ElideRight, self.width() - 12)
        p.drawText(QRectF(0, 140, self.width(), 22), Qt.AlignmentFlag.AlignHCenter, title)
        sub_key = {"forgotten": "warn", "locked": "lock"}.get(self.state, "muted")
        p.setPen(QColor(t[sub_key]))
        p.setFont(font("Quicksand", 13))
        p.drawText(QRectF(0, 162, self.width(), 20), Qt.AlignmentFlag.AlignHCenter, self.subtitle)
        if self.hasFocus():
            q = QPen(QColor(t["muted"]), 1, Qt.PenStyle.DotLine)
            p.setPen(q)
            p.drawRoundedRect(QRectF(4, 4, self.width() - 8, self.height() - 8), 18, 18)
        p.end()


class PinDots(QWidget):
    """Six small rings that fill as digits are typed (no font glyph needed)."""
    def __init__(self, count=4, parent=None):
        super().__init__(parent)
        self.count, self.filled, self.error = count, 0, False
        self.pop, self.shake = 1.0, 0.0
        self.setFixedSize(count * 34 + 24, 34)

    def _set_pop(self, value):
        self.pop = value
        self.update()

    def _set_shake(self, value):
        self.shake = value
        self.update()

    def set_filled(self, n, error=False):
        grew = n > self.filled
        self.filled, self.error = n, error
        if grew:
            animate(self, "pop", 0.0, 1.0, 160, self._set_pop, QEasingCurve.Type.OutBack)
        if error:
            animate(self, "shake", 0.0, 1.0, 360, self._set_shake, QEasingCurve.Type.Linear)
        self.update()

    def paintEvent(self, _event):
        t = current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        key = "lock" if self.error else "ring"
        offset = 0.0
        if self.error and 0.0 < self.shake < 1.0:
            offset = math.sin(self.shake * math.pi * 6) * (1 - self.shake) * 9
        for i in range(self.count):
            center = QPointF(29 + i * 34 + offset, 17)
            if i < self.filled:
                radius = 7 * (self.pop if i == self.filled - 1 else 1.0)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(t[key]))
                p.drawEllipse(center, max(0.5, radius), max(0.5, radius))
            else:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor(t["ring_idle"] if not self.error else t["lock"]), 1.5))
                p.drawEllipse(center, 7, 7)
        p.end()


class RingWidget(QWidget):
    """A standalone ring (PIN screen, welcome screen, table avatars)."""
    def __init__(self, radius=46, parent=None):
        super().__init__(parent)
        self.radius = radius
        self.state, self.progress, self.letters = "out", 0.0, ""
        self.reveal = 1.0
        size = int(radius * 2 + radius * 0.9)
        self.setFixedSize(int(radius * 2.6), size)

    def set_ring(self, state, progress, letters):
        self.state, self.progress, self.letters = state, progress, letters
        self.update()

    def _set_reveal(self, value):
        self.reveal = value
        self.update()

    def draw_in(self, ms=700, delay=80):
        """Sweep the ring in, then drop the accent into place."""
        animate(self, "reveal", 0.0, 1.0, ms, self._set_reveal, QEasingCurve.Type.OutCubic, delay)

    def paintEvent(self, _event):
        p = QPainter(self)
        paint_ring(p, self.width() / 2, self.height() - self.radius - 4, self.radius,
                   self.state, self.progress, self.letters, reveal=self.reveal)
        p.end()


def avatar_pixmap(letters, state="out", size=30, ratio=1.0):
    pm = QPixmap(int(size * ratio), int(size * ratio))
    pm.fill(Qt.GlobalColor.transparent)
    pm.setDevicePixelRatio(ratio)
    p = QPainter(pm)
    r = size * 0.36
    paint_ring(p, size / 2, size / 2 + r * 0.25, r, state, 1.0 if state == "in" else 0.0, letters)
    p.end()
    return pm


# --- backdrop -----------------------------------------------------------------

class Backdrop(QWidget):
    """Page background with a large, faint Ó watermark in the top-right corner."""
    def paintEvent(self, _event):
        t = current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(t["bg"]))
        r = max(220.0, min(self.width(), self.height()) * 0.42)
        cx, cy = self.width() - r * 0.45, r * 0.55
        q = QPen(QColor(t["watermark"]), max(8.0, r / 22))
        q.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(q)
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.drawLine(QPointF(cx + 0.19 * r, cy - 1.14 * r), QPointF(cx + 0.43 * r, cy - 1.33 * r))
        p.end()


# --- admin: tiles, timeline, heatmap -----------------------------------------

class StatTile(QFrame):
    def __init__(self, caption, parent=None):
        super().__init__(parent)
        self.setObjectName("tile")
        box = QVBoxLayout(self)
        box.setContentsMargins(18, 14, 18, 14)
        box.setSpacing(2)
        self.caption = QLabel(caption)
        self.caption.setObjectName("subtitle")
        self.value = QLabel("—")
        self.value.setObjectName("tileValue")
        box.addWidget(self.caption)
        box.addWidget(self.value)

    def set_value(self, text, warn=False):
        self.value.setText(text)
        name = "tileWarn" if warn else "tile"
        if self.objectName() != name:
            self.setObjectName(name)
            self.style().unpolish(self)
            self.style().polish(self)
        self.value.setObjectName("tileValueWarn" if warn else "tileValue")
        self.value.style().unpolish(self.value)
        self.value.style().polish(self.value)


class TimelineWidget(QWidget):
    """Today's shifts as horizontal bars across the service hours."""
    ROW, GUTTER = 38, 132

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows, self.lo, self.hi, self.now = [], 0, 1, 0
        self.ticks = []
        self.setMinimumHeight(120)

    def set_data(self, rows, lo, hi, ticks, now):
        """rows: [(name, letters, state, [(start, end, kind)])]; kind: now|done|review."""
        self.rows, self.lo, self.hi, self.ticks, self.now = rows, lo, max(hi, lo + 1), ticks, now
        self.setMinimumHeight(40 + max(1, len(rows)) * self.ROW)
        self.updateGeometry()
        self.update()

    def _x(self, ts):
        width = max(1, self.width() - self.GUTTER - 12)
        return self.GUTTER + (min(max(ts, self.lo), self.hi) - self.lo) / (self.hi - self.lo) * width

    def paintEvent(self, _event):
        t = current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setFont(font("Quicksand", 12))
        for ts, text in self.ticks:
            x = self._x(ts)
            p.setPen(QColor(t["faint"]))
            p.drawText(QRectF(x - 20, 0, 40, 18), Qt.AlignmentFlag.AlignCenter, text)
            p.setPen(QPen(QColor(t["line_soft"]), 1))
            p.drawLine(QPointF(x, 22), QPointF(x, self.height() - 4))
        if not self.rows:
            p.setPen(QColor(t["muted"]))
            p.setFont(font("Quicksand", 14))
            p.drawText(QRectF(0, 30, self.width(), 40), Qt.AlignmentFlag.AlignCenter,
                       "bugün henüz kayıt yok")
        for i, (name, letters, state, segments) in enumerate(self.rows):
            y = 30 + i * self.ROW
            paint_ring(p, 16, y + 16, 11, state, 1.0 if state == "in" else 0.0, letters, t)
            p.setPen(QColor(t["text"]))
            p.setFont(font("Quicksand", 14, QFont.Weight.Medium))
            p.drawText(QRectF(36, y + 6, self.GUTTER - 44, 22),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       p.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, self.GUTTER - 44))
            track = QRectF(self.GUTTER, y + 10, self.width() - self.GUTTER - 12, 12)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t["line_soft"]))
            p.drawRoundedRect(track, 6, 6)
            for start, end, kind in segments:
                x1, x2 = self._x(start), self._x(end)
                bar = QRectF(x1, y + 9, max(6.0, x2 - x1), 14)
                key = {"now": "inside", "review": "warn"}.get(kind, "done")
                p.setBrush(QColor(t[key]))
                p.drawRoundedRect(bar, 7, 7)
                if kind == "review":
                    p.setBrush(QBrush(QColor(t["bg"]), Qt.BrushStyle.BDiagPattern))
                    p.drawRoundedRect(bar, 7, 7)
        if self.lo <= self.now <= self.hi:
            x = self._x(self.now)
            p.setPen(QPen(QColor(t["ring"]), 1.4, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(x, 20), QPointF(x, self.height() - 4))
        p.end()


class HeatmapWidget(QWidget):
    """Hours per person per business day for the last seven days."""
    CELL_H, GUTTER = 30, 110

    def __init__(self, parent=None):
        super().__init__(parent)
        self.names, self.days, self.values, self.flags = [], [], {}, set()
        self.setMinimumHeight(80)

    def set_data(self, names, days, values, flags):
        """names: [(id, label)]; days: [label]; values: {(id, col): hours}; flags: {(id, col)}."""
        self.names, self.days, self.values, self.flags = names, days, values, flags
        self.setMinimumHeight(30 + max(1, len(names)) * (self.CELL_H + 6))
        self.updateGeometry()
        self.update()

    def paintEvent(self, _event):
        t = current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cols = max(1, len(self.days))
        cw = (self.width() - self.GUTTER) / cols
        p.setFont(font("Quicksand", 12))
        p.setPen(QColor(t["faint"]))
        for c, label in enumerate(self.days):
            p.drawText(QRectF(self.GUTTER + c * cw, 0, cw, 20), Qt.AlignmentFlag.AlignCenter, label)
        low, high = QColor(t["surface2"]), QColor(t["inside"])
        for r, (eid, name) in enumerate(self.names):
            y = 26 + r * (self.CELL_H + 6)
            p.setPen(QColor(t["text"]))
            p.setFont(font("Quicksand", 13, QFont.Weight.Medium))
            p.drawText(QRectF(0, y, self.GUTTER - 10, self.CELL_H),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
            for c in range(cols):
                cell = QRectF(self.GUTTER + c * cw + 3, y, cw - 6, self.CELL_H)
                hours = self.values.get((eid, c), 0.0)
                flagged = (eid, c) in self.flags
                if flagged:
                    fill, text_color = QColor(t["warn_soft"]), QColor(t["warn_text"])
                elif hours > 0:
                    k = min(1.0, 0.25 + hours / 12.0)
                    fill = QColor(int(low.red() + (high.red() - low.red()) * k),
                                  int(low.green() + (high.green() - low.green()) * k),
                                  int(low.blue() + (high.blue() - low.blue()) * k))
                    text_color = QColor(t["bg"]) if k > 0.6 else QColor(t["text"])
                else:
                    fill, text_color = QColor(t["surface2"]), QColor(t["faint"])
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(fill)
                p.drawRoundedRect(cell, 8, 8)
                label = "?" if flagged else (f"{hours:.0f}" if hours >= 0.5 else "")
                if label:
                    p.setPen(text_color)
                    p.setFont(font("Jost", 13, QFont.Weight.Normal))
                    p.drawText(cell, Qt.AlignmentFlag.AlignCenter, label)
        p.end()


# --- welcome ------------------------------------------------------------------

class WelcomeDialog(QDialog):
    """A two-second confirmation after a successful start/finish."""
    closed = Signal()

    def __init__(self, letters, state, title, subtitle, note, parent=None, timeout_ms=2400):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setModal(True)
        self.setObjectName("welcome")
        t = current()
        self.setStyleSheet(f"QDialog#welcome {{ background: {t['surface']}; border: 1px solid {t['line']};"
                           f" border-radius: 24px; }}")
        row = QHBoxLayout(self)
        row.setContentsMargins(34, 30, 40, 30)
        row.setSpacing(28)
        self.ring = RingWidget(62)
        self.ring.set_ring(state, 1.0 if state == "in" else 0.0, letters)
        self.ring.draw_in()
        row.addWidget(self.ring)
        texts = QVBoxLayout()
        texts.addStretch()
        self.title = QLabel(title)
        self.title.setObjectName("welcomeTitle")
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("welcomeSub")
        self.note = QLabel(note)
        self.note.setObjectName("faint")
        for w in (self.title, self.subtitle, self.note):
            texts.addWidget(w)
        texts.addStretch()
        row.addLayout(texts, 1)
        self.setMinimumWidth(620)
        self.setWindowOpacity(0.0 if ANIMATIONS else 1.0)
        QTimer.singleShot(timeout_ms, self, self.accept)

    def showEvent(self, event):
        super().showEvent(event)
        animate(self, "fade", 0.0, 1.0, 180, self.setWindowOpacity)

    def mousePressEvent(self, _event):
        self.accept()

