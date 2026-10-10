"""Student SDK for the ERC car.

Start here. You do not build UDP strings. See ``docs/STUDENT_SDK.md``.

.. code-block:: python

    import erc

    @erc.on_color("green")
    def see_green(color):
        erc.move_forward()

    @erc.on_voice("stop")
    def heard_stop(phrase):
        erc.stop()
"""

from __future__ import annotations

from erc.car import Car, get_default_car, reset_default_car

__all__ = [
    "Car",
    "clear_estop",
    "estop",
    "get_default_car",
    "hear",
    "last_command",
    "move_forward",
    "on_color",
    "on_voice",
    "reset_default_car",
    "run",
    "session",
    "set_manual_override",
    "simulate_color",
    "stop",
    "turn_left",
    "turn_right",
    "when",
    "前進",
    "前进",
    "停止",
    "左轉",
    "左转",
    "右轉",
    "右转",
    "緊急停止",
    "紧急停止",
]


def move_forward():
    """Drive forward. Straight wheels."""
    return get_default_car().move_forward()


def stop():
    """Brake. Does not latch. The next ``move_forward`` is allowed."""
    return get_default_car().stop()


def turn_left():
    """Drive forward with the wheels left."""
    return get_default_car().turn_left()


def turn_right():
    """Drive forward with the wheels right."""
    return get_default_car().turn_right()


def estop():
    """Latch the brake. Stays stopped until ``clear_estop``."""
    return get_default_car().estop()


def clear_estop():
    """Drop the e-stop latch. Does not start moving again."""
    return get_default_car().clear_estop()


def on_color(color, handler=None):
    """Run ``handler`` when that color appears.

    Use as ``erc.on_color("red", on_red)`` or as a decorator.
    """
    if handler is None:
        def decorate(fn):
            return get_default_car().on_color(color, fn)
        return decorate
    return get_default_car().on_color(color, handler)


def on_voice(phrase, handler=None):
    """Run ``handler`` when a transcript maps to that phrase's intent.

    ``"stop"`` and ``"停止"`` are the same event.
    """
    if handler is None:
        def decorate(fn):
            return get_default_car().on_voice(phrase, fn)
        return decorate
    return get_default_car().on_voice(phrase, handler)


def when(*, color=None, voice=None):
    """Level 2 stub: remember a compound rule. The Level 1 loop does not run it."""
    return get_default_car().when(color=color, voice=voice)


def simulate_color(color):
    """Pretend the camera just saw ``color``. No webcam required."""
    return get_default_car().simulate_color(color)


def hear(text):
    """Pretend the microphone heard ``text``. No ASR engine required."""
    return get_default_car().hear(text)


def run(seconds=None):
    """Start the camera/voice loop. Blocks until Ctrl+C, or for ``seconds``."""
    return get_default_car().run(seconds=seconds)


def session(simulate=None):
    """Context manager. Optional simulated color, then a safe stop on exit."""
    return get_default_car().session(simulate=simulate)


def set_manual_override(active=True):
    """While true, student motion is dropped. E-stop still sends."""
    return get_default_car().set_manual_override(active)


def last_command():
    """Last ``L:,R:,B:,S:`` line the SDK tried to send, without the newline."""
    return get_default_car().last_command()


# Chinese names for the same five motions.
前進 = move_forward
前进 = move_forward
停止 = stop
左轉 = turn_left
左转 = turn_left
右轉 = turn_right
右转 = turn_right
緊急停止 = estop
紧急停止 = estop
