"""One car object. Motion, color events, and voice events share the gateway."""

from __future__ import annotations

import inspect
import threading
import time
from contextlib import contextmanager

from ai.command_gateway import CommandGateway
from ai.intents import resolve_intent
from ai.transport import (
    FORWARD_SPEED,
    SERVO_LEFT_MAX,
    SERVO_RIGHT_MAX,
    SERVO_STRAIGHT,
    STOP_SIGNAL,
    TURN_SPEED_FACTOR,
    send_car_command,
)
from ai.vision_l1 import VisionLevel1
from ai.voice_l1 import VoiceLevel1

_COLOR_NAMES = {
    "red": "red",
    "green": "green",
    "blue": "blue",
    "yellow": "yellow",
    "紅": "red",
    "红": "red",
    "綠": "green",
    "绿": "green",
    "藍": "blue",
    "蓝": "blue",
    "黃": "yellow",
    "黄": "yellow",
}

_default_car = None
_default_lock = threading.Lock()


def canonical_color(name: str | None) -> str | None:
    if name is None:
        return None
    key = str(name).strip().lower()
    if key in _COLOR_NAMES:
        return _COLOR_NAMES[key]
    # Chinese keys are not changed by lower().
    raw = str(name).strip()
    return _COLOR_NAMES.get(raw)


def student_log(message: str) -> None:
    """Print safety notes. Successful datagrams are printed by the sender."""
    if "->" in message:
        return
    print(message)


def invoke(handler, *args) -> None:
    """Call ``handler`` with as many of ``args`` as it declares."""
    try:
        parameters = [
            item
            for item in inspect.signature(handler).parameters.values()
            if item.kind in (item.POSITIONAL_ONLY, item.POSITIONAL_OR_KEYWORD)
        ]
    except (TypeError, ValueError):
        handler()
        return
    handler(*args[: len(parameters)])


class Car:
    """Level 1 student car.

    Direct calls (``move_forward``, ``stop``, ``turn_left``, ``turn_right``,
    ``estop``) go through ``CommandGateway`` as operator commands. Color and
    voice handlers are yours: the car does not move until a handler, or you,
    asks it to. E-stop and manual override still win.
    """

    def __init__(self, sender=None, log=None, confirm_frames: int = 2, gateway=None):
        self._log = log if log is not None else student_log
        self._sender = sender or send_car_command
        self.gateway = gateway or CommandGateway(
            self._sender,
            forward_speed=FORWARD_SPEED,
            turn_speed=int(FORWARD_SPEED * TURN_SPEED_FACTOR),
            servo_straight=SERVO_STRAIGHT,
            servo_left=SERVO_LEFT_MAX,
            servo_right=SERVO_RIGHT_MAX,
            stop_signal=STOP_SIGNAL,
            log=self._log,
        )
        self.vision = VisionLevel1(confirm_frames=confirm_frames)
        self.voice = VoiceLevel1()
        self._color_handlers: dict[str, list] = {}
        self._voice_handlers: dict[str, list] = {}
        self.level2_rules: list[dict] = []
        self._last_color = None
        self._handler_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None
        self._running = False

    def move_forward(self) -> bool:
        return self._drive("forward")

    def stop(self) -> bool:
        return self._drive("stop")

    def turn_left(self) -> bool:
        return self._drive("left")

    def turn_right(self) -> bool:
        return self._drive("right")

    def estop(self) -> bool:
        return self.gateway.emergency_stop("student")

    def clear_estop(self) -> bool:
        return self.gateway.clear_estop()

    def set_manual_override(self, active: bool = True) -> None:
        """Block-program stand-in. Student motion is ignored while this is on."""
        self.gateway.set_manual_override(active)

    def last_command(self) -> str:
        return self.gateway.last_command

    def on_color(self, color, handler):
        name = canonical_color(color)
        if name is None:
            raise ValueError(
                f"unknown color {color!r}. Use red, green, blue, yellow "
                "(or 紅/红, 綠/绿, 藍/蓝, 黃/黄)."
            )
        with self._handler_lock:
            self._color_handlers.setdefault(name, []).append(handler)
        return handler

    def on_voice(self, phrase, handler):
        intent = resolve_intent(phrase)
        if intent is None:
            raise ValueError(
                f"unknown voice phrase {phrase!r}. "
                "Try forward, stop, left, right, 前進, 停止, or emergency stop."
            )
        with self._handler_lock:
            self._voice_handlers.setdefault(intent, []).append(handler)
        return handler

    def when(self, *, color=None, voice=None):
        """Remember a Level 2 compound rule. Level 1 does not run it.

        TODO(L2): evaluate these when both the color and the voice intent
        have been seen, then call the handler. Until then, use ``on_color``
        and ``on_voice`` separately.
        """
        color_name = canonical_color(color) if color else None
        if color and color_name is None:
            raise ValueError(f"unknown color {color!r} in Level 2 rule")
        voice_intent = resolve_intent(voice) if voice else None
        if voice and voice_intent is None:
            raise ValueError(f"unknown voice phrase {voice!r} in Level 2 rule")

        def decorate(handler):
            self.level2_rules.append(
                {
                    "color": color_name,
                    "voice": voice_intent,
                    "handler": handler,
                }
            )
            return handler

        return decorate

    def simulate_color(self, color):
        """Inject one color edge. Also selects that color for a later ``run``."""
        if color in (None, "", "none"):
            self.vision.set_mode("none")
            self._on_color_sample(None)
            return None
        name = canonical_color(color)
        if name is None:
            raise ValueError(f"unknown color {color!r}")
        self.vision.set_mode(name)
        self._on_color_sample(name)
        return name

    def hear(self, text):
        """Inject one transcript. Handlers run; this does not move the car itself."""
        intent = self.voice.transcript_to_intent(text)
        if intent is None:
            self._log(f"no Level 1 phrase in {text!r}")
            return None
        with self._handler_lock:
            handlers = list(self._voice_handlers.get(intent, ()))
        for handler in handlers:
            invoke(handler, text)
        return intent

    def run(self, seconds: float | None = None) -> None:
        """Block on the vision loop. ``seconds=None`` runs until Ctrl+C."""
        self.start()
        try:
            if seconds is None:
                while not self._stop_event.is_set():
                    time.sleep(0.2)
            else:
                time.sleep(max(0.0, float(seconds)))
        except KeyboardInterrupt:
            pass
        finally:
            self.close()

    @contextmanager
    def session(self, simulate=None):
        """Start the loop, run the ``with`` block, then brake.

        ``simulate`` picks a color for the camera stand-in (``\"green\"``)
        without firing handlers before the loop is up. Call
        ``simulate_color`` if you want the handler immediately.
        """
        if simulate is not None:
            if simulate in ("", "none"):
                self.vision.set_mode("none")
            else:
                name = canonical_color(simulate)
                if name is None:
                    raise ValueError(f"unknown color {simulate!r}")
                self.vision.set_mode(name)
        self.start()
        try:
            yield self
        finally:
            self.close()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self.vision.start()
        self._thread = threading.Thread(target=self._loop, name="erc-student", daemon=True)
        self._thread.start()

    def close(self) -> None:
        was_running = self._running
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.5)
        self._thread = None
        self._running = False
        self.vision.stop()
        if was_running and not self.gateway.estop_latched:
            self.stop()

    def _drive(self, intent: str) -> bool:
        return self.gateway.submit_intent(intent, source="student", label=intent, operator=True)

    def _on_color_sample(self, label) -> None:
        with self._handler_lock:
            if label == self._last_color:
                return
            self._last_color = label
            handlers = list(self._color_handlers.get(label, ())) if label else []
        for handler in handlers:
            invoke(handler, label)

    def _loop(self) -> None:
        seen = None
        while not self._stop_event.is_set():
            timestamp, label, _intent = self.vision.latest()
            if timestamp is not None and timestamp != seen:
                seen = timestamp
                self._on_color_sample(label)
            self.gateway.tick()
            self._stop_event.wait(0.1)


def get_default_car() -> Car:
    global _default_car
    with _default_lock:
        if _default_car is None:
            _default_car = Car()
        return _default_car


def reset_default_car(car: Car | None = None) -> None:
    """Tests and notebooks use this to swap the process-wide car."""
    global _default_car
    with _default_lock:
        if _default_car is not None and car is not _default_car:
            try:
                _default_car.close()
            except Exception:
                pass
        _default_car = car
