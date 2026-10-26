"""Boss demo1 window: one map, coins, power-ups, and the soft gateway.

No camera. Run from the repo root::

    ERC_LOG_ONLY=1 python3 examples/demo1_mario_soft.py

If ``ERC_LOG_ONLY`` is unset, this demo sets it to 1 so the car is not
commanded. Uncheck **UDP log-only** only when a car should actually move.
``8266.ino`` is not involved.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    _ROOT = Path(__file__).resolve().parents[1]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from PyQt5.QtCore import QEvent, QPointF, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ai.demo1_course import (
    CAR_RADIUS,
    COIN_RADIUS,
    MAP_H,
    MAP_W,
    OIL_RECT,
    Demo1Course,
)
from ai.soft_gateway import SoftGateway
from ai.transport import (
    BACKWARD_SPEED,
    FORWARD_SPEED,
    SERVO_LEFT_MAX,
    SERVO_RIGHT_MAX,
    SERVO_STRAIGHT,
    STOP_SIGNAL,
    log_only_from_env,
    transmit_datagram,
)

_HOLD_KEYS = {
    Qt.Key_Up: "up",
    Qt.Key_W: "up",
    Qt.Key_Down: "down",
    Qt.Key_S: "down",
    Qt.Key_Left: "left",
    Qt.Key_A: "left",
    Qt.Key_Right: "right",
    Qt.Key_D: "right",
}

_POWER_KEYS = {
    Qt.Key_1: "boost",
    Qt.Key_2: "slow",
    Qt.Key_3: "freeze",
    Qt.Key_4: "steer",
}


def ensure_demo1_log_only() -> bool:
    """Turn on log-only when the variable is unset. Return whether it is on.

    An explicit ``ERC_LOG_ONLY=0`` stays off so a later real-car run can opt in.
    """
    raw = os.environ.get("ERC_LOG_ONLY")
    if raw is None or raw.strip() == "":
        os.environ["ERC_LOG_ONLY"] = "1"
    return log_only_from_env()


class CourseMap(QWidget):
    """Top-down map. Clicks are reported in course coordinates."""

    def __init__(self, course: Demo1Course, soft: SoftGateway, parent=None):
        super().__init__(parent)
        self.course = course
        self.soft = soft
        self.setMinimumSize(640, 400)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.NoFocus)
        self._click = None

    def set_click_handler(self, handler) -> None:
        self._click = handler

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        point = self._to_course(event.pos())
        if point is not None and self._click is not None:
            self._click(point[0], point[1])

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#121417"))
        scale, ox, oy = self._geom()
        painter.translate(ox, oy)
        painter.scale(scale, scale)
        self._paint_course(painter)
        painter.end()

    def _geom(self):
        scale = min(self.width() / MAP_W, self.height() / MAP_H)
        if scale <= 0:
            scale = 1.0
        ox = (self.width() - MAP_W * scale) / 2
        oy = (self.height() - MAP_H * scale) / 2
        return scale, ox, oy

    def _to_course(self, pos):
        scale, ox, oy = self._geom()
        x = (pos.x() - ox) / scale
        y = (pos.y() - oy) / scale
        if x < 0 or y < 0 or x > MAP_W or y > MAP_H:
            return None
        return x, y

    def _paint_course(self, painter: QPainter) -> None:
        painter.fillRect(0, 0, MAP_W, MAP_H, QColor("#1f5a32"))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#2f7a43"))
        painter.drawRoundedRect(16, 16, MAP_W - 32, MAP_H - 32, 18, 18)
        painter.setPen(QPen(QColor("#d7e26a"), 2, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(28, 28, MAP_W - 56, MAP_H - 56, 14, 14)

        x, y, w, h = OIL_RECT
        painter.setPen(QPen(QColor("#6e628c"), 2))
        painter.setBrush(QColor(28, 26, 36, 230))
        painter.drawRoundedRect(int(x), int(y), int(w), int(h), 22, 22)
        painter.setPen(QColor("#e4dcf8"))
        painter.setFont(QFont("Sans Serif", 12))
        painter.drawText(int(x), int(y), int(w), int(h), Qt.AlignCenter, "oil")

        for coin in self.course.coins:
            if not coin.alive:
                continue
            painter.setPen(QPen(QColor("#8a6410"), 2))
            painter.setBrush(QColor("#f0c419"))
            painter.drawEllipse(QPointF(coin.x, coin.y), COIN_RADIUS, COIN_RADIUS)
            painter.setPen(QPen(QColor("#6d4e0c"), 2))
            painter.drawLine(int(coin.x), int(coin.y - 8), int(coin.x), int(coin.y + 8))

        self._paint_car(painter)

    def _paint_car(self, painter: QPainter) -> None:
        course = self.course
        color = QColor("#3c7dff")
        power = None if self.soft.estop_latched else self.soft.power
        if power == "boost":
            color = QColor("#e23d3d")
        elif power == "slow":
            color = QColor("#8b6ad8")
        elif power == "freeze":
            color = QColor("#7fd3e8")
        elif power == "steer":
            color = QColor("#e0a030")
        painter.save()
        painter.translate(course.car_x, course.car_y)
        painter.rotate(course.heading)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#1a1a1a"))
        painter.drawRoundedRect(-14, -12, 6, 10, 2, 2)
        painter.drawRoundedRect(8, -12, 6, 10, 2, 2)
        painter.drawRoundedRect(-14, 4, 6, 10, 2, 2)
        painter.drawRoundedRect(8, 4, 6, 10, 2, 2)
        painter.setBrush(color)
        painter.drawRoundedRect(-10, -16, 20, 32, 5, 5)
        painter.setBrush(QColor("#e8f1ff"))
        painter.drawRoundedRect(-6, -12, 12, 8, 2, 2)
        painter.setBrush(QColor("#111111"))
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(0, -22),
                    QPointF(7, -12),
                    QPointF(-7, -12),
                ]
            )
        )
        painter.restore()
        if self.soft.estop_latched:
            painter.setPen(QColor("#ffb4b4"))
            painter.setFont(QFont("Sans Serif", 11))
            painter.drawText(
                int(course.car_x - 28),
                int(course.car_y + CAR_RADIUS + 16),
                "e-stop",
            )


class Demo1Window(QMainWindow):
    """Playable demo1. Keyboard, clicks, and ``simulate_detect`` share one course."""

    def __init__(self, *, course: Demo1Course | None = None, soft: SoftGateway | None = None):
        super().__init__()
        ensure_demo1_log_only()
        self.log_only = log_only_from_env()
        self.course = course or Demo1Course(clock=self._clock)
        self.soft = soft or SoftGateway(transmit=self._transmit, clock=self._clock, log=self._note)
        self.held: set[str] = set()
        self._last_tick = self._clock()
        self._last_panel_line = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer)

        self.setWindowTitle("ERC Boss demo1 Soft")
        self.resize(980, 720)
        self.setFocusPolicy(Qt.StrongFocus)
        self._build()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self._refresh_hud()
        self._note(
            "Log-only is on. Datagrams are printed and not sent."
            if self.log_only
            else "UDP transmit is on."
        )

    def _clock(self) -> float:
        import time

        return time.monotonic()

    def _build(self) -> None:
        root = QWidget()
        root.setStyleSheet("background: #121417; color: #f4f1ea;")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)

        title = QLabel("ERC Boss demo1 — Soft")
        title.setStyleSheet("font-size: 22px; font-weight: 700; color: #f7f3ea;")
        outer.addWidget(title)

        subtitle = QLabel("Virtual coins and power-ups. The car firmware is not modified.")
        subtitle.setStyleSheet("color: #b7b1a6; font-size: 13px;")
        outer.addWidget(subtitle)

        hud = QHBoxLayout()
        hud.setSpacing(8)
        self.score_label = self._pill("Score: 0")
        self.coins_label = self._pill("Remaining coins: 5")
        self.power_label = self._pill("Power-up: none")
        self.estop_label = self._pill("E-stop: clear")
        for label in (self.score_label, self.coins_label, self.power_label, self.estop_label):
            hud.addWidget(label)
        hud.addStretch()
        outer.addLayout(hud)

        controls = QHBoxLayout()
        self.estop_button = QPushButton("E-STOP")
        self.estop_button.setAutoDefault(False)
        self.estop_button.setStyleSheet(
            "QPushButton { background: #c1121f; color: white; font-weight: 700;"
            " padding: 8px 16px; border-radius: 6px; }"
            "QPushButton:pressed { background: #8d0e17; }"
        )
        self.estop_button.clicked.connect(self.emergency_stop)
        self.clear_button = QPushButton("Clear e-stop")
        self.clear_button.setAutoDefault(False)
        self.clear_button.setStyleSheet(
            "QPushButton { background: #343a40; color: white; padding: 8px 14px;"
            " border-radius: 6px; }"
            "QPushButton:pressed { background: #23272b; }"
        )
        self.clear_button.clicked.connect(self.clear_estop)
        self.log_only_box = QCheckBox("UDP log-only")
        self.log_only_box.setChecked(self.log_only)
        self.log_only_box.setStyleSheet("color: #f4f1ea; font-size: 14px;")
        self.log_only_box.toggled.connect(self._on_log_only)
        controls.addWidget(self.estop_button)
        controls.addWidget(self.clear_button)
        controls.addStretch()
        controls.addWidget(self.log_only_box)
        outer.addLayout(controls)

        body = QHBoxLayout()
        body.setSpacing(12)
        self.map = CourseMap(self.course, self.soft)
        self.map.set_click_handler(self._on_map_click)
        body.addWidget(self.map, 3)

        help_box = QLabel(self._help_text())
        help_box.setWordWrap(True)
        help_box.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        help_box.setStyleSheet(
            "background: #1c2128; color: #e7e2d8; border-radius: 10px; padding: 12px;"
            " font-size: 13px;"
        )
        help_box.setMinimumWidth(230)
        help_box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        body.addWidget(help_box, 1)
        outer.addLayout(body, 1)

        self.wire_label = QLabel("Wire: —")
        self.wire_label.setFont(QFont("Monospace", 12))
        self.wire_label.setStyleSheet("color: #f0d78c;")
        outer.addWidget(self.wire_label)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFocusPolicy(Qt.NoFocus)
        self.log.setFixedHeight(120)
        self.log.setStyleSheet(
            "background: #0e1114; color: #d9d4ca; border-radius: 8px; padding: 6px;"
            " font-family: Monospace; font-size: 12px;"
        )
        outer.addWidget(self.log)

    @staticmethod
    def _help_text() -> str:
        return (
            "Drive with the arrow keys or WASD.\n\n"
            "Coin: Space, click a coin, or simulate_detect(\"coin\"). "
            "Score +1. About 30% of pickups are a Boost mushroom.\n\n"
            "1  Boost    R × 1.5, cap 255, 2s\n"
            "2  Slow     R × 0.4, 2s\n"
            "3  Freeze   force B:1, 1.5s\n"
            "4  Steer    S + 30, 2s\n\n"
            "The oil patch is Slow. A new power-up replaces the old one.\n\n"
            "Esc or E-STOP latches the brake and cancels power-ups. "
            "Clear e-stop does not bring them back.\n\n"
            "Default is UDP log-only, so this window is safe with no car."
        )

    @staticmethod
    def _pill(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            "background: #1b2026; color: #f4f1ea; border-radius: 8px;"
            " padding: 6px 10px; font-size: 14px;"
        )
        return label

    def showEvent(self, event):
        super().showEvent(event)
        self.setFocus()
        self._last_tick = self._clock()
        if not self._timer.isActive():
            self._timer.start(50)

    def closeEvent(self, event):
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().closeEvent(event)

    def eventFilter(self, obj, event):
        if not self.isVisible():
            return False
        kind = event.type()
        if kind not in (QEvent.KeyPress, QEvent.KeyRelease):
            return False
        if event.isAutoRepeat():
            return True
        handled = self.handle_key(event.key(), pressed=(kind == QEvent.KeyPress))
        return bool(handled)

    def handle_key(self, key: int, *, pressed: bool = True) -> bool:
        """Apply one key. Tests call this without a Qt key event."""
        name = _HOLD_KEYS.get(key)
        if name is not None:
            if pressed:
                self.held.add(name)
            else:
                self.held.discard(name)
            self._emit_motion()
            self.map.update()
            return True
        if not pressed:
            return False
        if key == Qt.Key_Space:
            self.simulate_detect("coin")
            return True
        power = _POWER_KEYS.get(key)
        if power is not None:
            self.activate_power(power)
            return True
        if key == Qt.Key_Escape:
            self.emergency_stop()
            return True
        return False

    def simulate_detect(self, label, confidence: float = 1.0) -> bool:
        """Score a coin. A later camera can call this with the same label."""
        ok = self.course.simulate_detect(label, confidence, soft=self.soft)
        if ok:
            self._emit_motion()
            self._refresh_hud()
            self.map.update()
        return ok

    def activate_power(self, name: str) -> bool:
        ok = self.soft.activate(name)
        self._emit_motion()
        self._refresh_hud()
        self.map.update()
        return ok

    def emergency_stop(self) -> str:
        line = self.soft.emergency_stop(dry_run=self.log_only)
        self._refresh_hud()
        self.map.update()
        return line

    def clear_estop(self) -> bool:
        ok = self.soft.clear_estop()
        self._refresh_hud()
        self.map.update()
        return ok

    def tick_once(self, dt: float = 0.05) -> None:
        """Advance the map once. The on-screen timer calls this too."""
        self.course.step(dt, self.held, self.soft)
        self._emit_motion()
        self._refresh_hud()
        self.map.update()

    def _on_timer(self) -> None:
        now = self._clock()
        dt = min(0.1, max(0.0, now - self._last_tick))
        self._last_tick = now
        self.tick_once(dt)

    def _on_map_click(self, x: float, y: float) -> None:
        if self.course.collect_at(x, y, self.soft):
            self._emit_motion()
            self._refresh_hud()
            self.map.update()

    def _on_log_only(self, checked: bool) -> None:
        self.log_only = bool(checked)
        os.environ["ERC_LOG_ONLY"] = "1" if self.log_only else "0"
        self._note("UDP log-only on." if self.log_only else "UDP log-only off. Datagrams will be sent.")

    def _motion_tuple(self):
        if self.soft.estop_latched:
            return 0, SERVO_STRAIGHT, STOP_SIGNAL
        speed = 0
        steering = SERVO_STRAIGHT
        if "up" in self.held and "down" not in self.held:
            speed = FORWARD_SPEED
        elif "down" in self.held and "up" not in self.held:
            speed = -BACKWARD_SPEED
        if "left" in self.held and "right" not in self.held:
            steering = SERVO_LEFT_MAX
        elif "right" in self.held and "left" not in self.held:
            steering = SERVO_RIGHT_MAX
        stop = STOP_SIGNAL if speed == 0 else 0
        return speed, steering, stop

    def _emit_motion(self) -> str:
        # Opening the window does not transmit. The first datagram waits for
        # a key, a power-up, or e-stop. Later repeats are coalesced in the gateway.
        if (
            self.soft.last_sent is None
            and not self.held
            and self.soft.power is None
            and not self.soft.estop_latched
        ):
            return self.soft.last_command
        speed, steering, stop = self._motion_tuple()
        return self.soft.send(speed, steering, stop, dry_run=self.log_only)

    def _refresh_hud(self) -> None:
        self.score_label.setText(f"Score: {self.course.score}")
        self.coins_label.setText(f"Remaining coins: {self.course.remaining()}")
        remaining = self.soft.remaining_s()
        if self.soft.estop_latched or self.soft.power is None:
            self.power_label.setText("Power-up: none")
        else:
            self.power_label.setText(f"Power-up: {self.soft.power_label()} {remaining:.1f}s")
        if self.soft.estop_latched:
            self.estop_label.setText("E-stop: latched")
            self.estop_label.setStyleSheet(
                "background: #6e1218; color: #ffd7d7; border-radius: 8px;"
                " padding: 6px 10px; font-size: 14px; font-weight: 700;"
            )
        else:
            self.estop_label.setText("E-stop: clear")
            self.estop_label.setStyleSheet(
                "background: #1b2026; color: #f4f1ea; border-radius: 8px;"
                " padding: 6px 10px; font-size: 14px;"
            )
        wire = self.soft.last_command
        self.wire_label.setText(f"Wire: {wire}")

    def _transmit(self, command_str, dry_run=None, debug=False):
        if dry_run is None:
            dry_run = self.log_only
        line = transmit_datagram(command_str, dry_run=dry_run, debug=debug)
        self._note(str(line).strip())
        return line

    def _note(self, message: str) -> None:
        if not hasattr(self, "log"):
            return
        text = str(message).strip()
        if not text or text == self._last_panel_line:
            return
        self._last_panel_line = text
        self.log.appendPlainText(text)


def run(argv=None) -> int:
    del argv
    ensure_demo1_log_only()
    app = QApplication.instance() or QApplication(sys.argv)
    window = Demo1Window()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(run())
