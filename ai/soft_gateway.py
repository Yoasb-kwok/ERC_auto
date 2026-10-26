"""Rewrite outgoing ``L/R/B/S`` for Boss demo1. The ESP8266 sketch is unchanged.

Power-ups live only on the PC. ``SoftGateway`` formats a command the same way
``send_car_command`` does, applies one active effect, then hands the line to
``ai.transport.transmit_datagram`` (the socket ``send_car_command`` already
uses). Log-only mode still prints and does not transmit.

Effects, one at a time (a new one refreshes or replaces the old one):

- boost: ``R × 1.5``, capped at 255, for 2s
- slow: ``R × 0.4`` for 2s
- freeze: force ``B:1`` and drop drive channels for 1.5s
- steer: ``S`` offset by ±30 for 2s (key 4 uses +30)

While e-stop is latched every power-up is a no-op and the wire is the brake
line. ``clear_estop`` does not bring the power-up back. A human brake
(``B:1`` or zero ``R``) is not turned into motion by boost or slow.
"""

from __future__ import annotations

import time

from ai.transport import (
    MAX_SPEED,
    SERVO_LEFT_MAX,
    SERVO_RIGHT_MAX,
    SERVO_STRAIGHT,
    STOP_SIGNAL,
    transmit_datagram,
)
from ai.wire import format_car_command

BOOST_FACTOR = 1.5
BOOST_CAP = 255
SLOW_FACTOR = 0.4
STEER_BIAS = 30
CHANNEL_CAP = 255
SERVO_ABS_MIN = 0
SERVO_ABS_MAX = 180

POWERUPS = {
    "boost": 2.0,
    "slow": 2.0,
    "freeze": 1.5,
    "steer": 2.0,
}

POWER_NAMES = {
    "boost": "Boost",
    "slow": "Slow",
    "freeze": "Freeze",
    "steer": "Steer",
}

_BRAKE_LINE = f"L:0,R:0,B:{STOP_SIGNAL},S:{SERVO_STRAIGHT}\n"


def parse_car_command(command: str) -> dict | None:
    """Pull ``L`` ``R`` ``B`` ``S`` integers out of one datagram."""
    found = {}
    for part in str(command).replace("\n", "").split(","):
        piece = part.strip()
        if ":" not in piece:
            continue
        key, raw = piece.split(":", 1)
        key = key.strip()
        if key not in {"L", "R", "B", "S"}:
            continue
        try:
            found[key] = int(raw.strip())
        except ValueError:
            return None
    if set(found) != {"L", "R", "B", "S"}:
        return None
    return found


def format_fields(left, right, brake, servo) -> str:
    """One newline-terminated datagram. Channels are already scaled."""
    return f"L:{int(left)},R:{int(right)},B:{int(brake)},S:{int(servo)}\n"


def _scale(value: int, factor: float, cap: int = CHANNEL_CAP) -> int:
    scaled = int(round(float(value) * factor))
    if scaled < 0:
        return 0
    if scaled > cap:
        return cap
    return scaled


class SoftGateway:
    """One active power-up in front of the existing UDP sender.

    ``send(speed, steering, stop_override)`` matches ``send_car_command``
    so this object can sit where that function sits. ``rewrite`` is the
    pure line transform tests and the window both use.
    """

    def __init__(self, transmit=None, *, clock=None, log=None):
        self.transmit = transmit or transmit_datagram
        self._clock = clock or time.monotonic
        self._log_callback = log
        self.estop_latched = False
        self.power = None
        self.expires_at = None
        self.steer_sign = 1
        self.last_sent = None
        self.last_command = "—"
        self._last_log = None

    def activate(self, name: str, *, bias_sign: int = 1, now: float | None = None) -> bool:
        """Start or refresh one power-up. No-op while e-stop is latched."""
        if name not in POWERUPS:
            self._log(f"unknown power-up {name!r}")
            return False
        if self.estop_latched:
            self._log(f"ignored {name}: e-stop latched")
            return False
        now = self._now() if now is None else now
        self.power = name
        self.expires_at = now + POWERUPS[name]
        if name == "steer":
            self.steer_sign = 1 if bias_sign >= 0 else -1
        self._log(f"{self.power_label()} for {POWERUPS[name]:.1f}s")
        return True

    def emergency_stop(self, *, dry_run=None) -> str:
        """Latch brake and drop any power-up. The next clear does not restore it."""
        self.estop_latched = True
        self._drop_power()
        self._log("e-stop latched; power-ups cleared")
        return self._send(_BRAKE_LINE, dry_run=dry_run, force=True)

    def clear_estop(self) -> bool:
        """Drop the latch. Does not resume a power-up or a drive command."""
        if not self.estop_latched:
            self._log("Clear e-stop: nothing was latched")
            return False
        self.estop_latched = False
        self._drop_power()
        self._log("e-stop cleared; power-up was not restored")
        return True

    def expire(self, now: float | None = None) -> None:
        if self.power is None or self.expires_at is None:
            return
        now = self._now() if now is None else now
        if now >= self.expires_at:
            name = self.power_label()
            self._drop_power()
            self._log(f"{name} ended")

    def power_label(self) -> str:
        if self.power is None:
            return "none"
        if self.power == "steer":
            sign = "+" if self.steer_sign >= 0 else "-"
            return f"Steer {sign}{STEER_BIAS}"
        return POWER_NAMES.get(self.power, self.power)

    def remaining_s(self, now: float | None = None) -> float:
        self.expire(now)
        if self.estop_latched or self.power is None or self.expires_at is None:
            return 0.0
        now = self._now() if now is None else now
        return max(0.0, self.expires_at - now)

    def rewrite(self, command: str, now: float | None = None) -> str:
        """Apply the active effect. E-stop always becomes the brake line.

        The firmware keeps the last packet, so freeze sends ``B:1`` with the
        drive channels cleared instead of swallowing the datagram.
        """
        if self.estop_latched:
            self._drop_power()
            return _BRAKE_LINE
        self.expire(now)
        parsed = parse_car_command(command)
        if parsed is None or self.power is None:
            text = str(command)
            return text if text.endswith("\n") else f"{text}\n"
        left = parsed["L"]
        right = parsed["R"]
        brake = parsed["B"]
        servo = parsed["S"]
        if self.power == "boost":
            right = _scale(right, BOOST_FACTOR, BOOST_CAP)
        elif self.power == "slow":
            right = _scale(right, SLOW_FACTOR, CHANNEL_CAP)
        elif self.power == "freeze":
            left = 0
            right = 0
            brake = STOP_SIGNAL
        elif self.power == "steer":
            servo = int(servo) + self.steer_sign * STEER_BIAS
            servo = max(SERVO_ABS_MIN, min(SERVO_ABS_MAX, servo))
        return format_fields(left, right, brake, servo)

    def send(self, speed, steering_angle, stop_override=0, dry_run=None, debug=False) -> str:
        """Format, rewrite, and transmit. Same call shape as ``send_car_command``."""
        del debug
        raw = format_car_command(
            speed,
            steering_angle,
            stop_override,
            max_speed=MAX_SPEED,
            servo_min=SERVO_LEFT_MAX,
            servo_max=SERVO_RIGHT_MAX,
            stop_signal=STOP_SIGNAL,
        )
        return self._send(self.rewrite(raw), dry_run=dry_run, force=False)

    def _drop_power(self) -> None:
        self.power = None
        self.expires_at = None

    def _send(self, line: str, *, dry_run=None, force: bool) -> str:
        if not line.endswith("\n"):
            line = f"{line}\n"
        if not force and line == self.last_sent:
            self.last_command = line.strip()
            return line
        self.last_sent = line
        sent = self.transmit(line, dry_run=dry_run)
        text = line if sent is None else str(sent)
        if not text.endswith("\n"):
            text = f"{text}\n"
        self.last_command = text.strip()
        return text

    def _now(self) -> float:
        return self._clock()

    def _log(self, message: str) -> None:
        if message == self._last_log:
            return
        self._last_log = message
        if self._log_callback is not None:
            self._log_callback(message)


def run_self_check(log=print) -> list[str]:
    """Script the soft rules with no Qt and no socket."""
    sent: list[str] = []

    class _Clock:
        def __init__(self):
            self.t = 1_000.0

        def __call__(self):
            return self.t

    def transmit(command_str, dry_run=None, debug=False):
        del dry_run, debug
        sent.append(str(command_str).strip())
        return command_str

    clock = _Clock()
    soft = SoftGateway(transmit=transmit, clock=clock, log=log)

    log("--- boost scales R and caps at 255 ---")
    assert soft.activate("boost")
    assert soft.rewrite("L:0,R:100,B:0,S:90").strip() == "L:0,R:150,B:0,S:90"
    assert soft.rewrite("L:0,R:190,B:0,S:90").strip() == "L:0,R:255,B:0,S:90"

    log("--- slow replaces boost ---")
    assert soft.activate("slow")
    assert soft.rewrite("L:0,R:100,B:0,S:90").strip() == "L:0,R:40,B:0,S:90"

    log("--- freeze forces brake and drops drive ---")
    assert soft.activate("freeze")
    assert soft.rewrite("L:20,R:100,B:0,S:50").strip() == "L:0,R:0,B:1,S:50"

    log("--- steer bias +30, and a negative bias ---")
    assert soft.activate("steer")
    assert soft.rewrite("L:0,R:100,B:0,S:90").strip() == "L:0,R:100,B:0,S:120"
    assert soft.activate("steer", bias_sign=-1)
    assert soft.rewrite("L:0,R:100,B:0,S:90").strip() == "L:0,R:100,B:0,S:60"

    log("--- duration ends the effect ---")
    clock.t = 1_000.0
    assert soft.activate("boost")
    clock.t = 1_001.9
    assert soft.rewrite("L:0,R:100,B:0,S:90").strip() == "L:0,R:150,B:0,S:90"
    clock.t = 1_002.0
    assert soft.rewrite("L:0,R:100,B:0,S:90").strip() == "L:0,R:100,B:0,S:90"

    log("--- e-stop blocks power-ups; clear does not restore ---")
    clock.t = 2_000.0
    assert soft.activate("boost")
    assert soft.send(100, 90, 0).strip() == "L:0,R:150,B:0,S:90"
    assert soft.emergency_stop().strip() == "L:0,R:0,B:1,S:90"
    assert not soft.activate("boost")
    assert soft.send(100, 90, 0).strip() == "L:0,R:0,B:1,S:90"
    assert soft.clear_estop()
    assert soft.power is None
    assert soft.send(100, 90, 0).strip() == "L:0,R:100,B:0,S:90"

    log("Soft gateway self-check complete. No UDP was sent.")
    return sent


def main(argv=None) -> int:
    del argv
    print("ERC demo1 soft gateway (log only, no car, no window)")
    try:
        run_self_check()
    except AssertionError as exc:
        print(f"Soft gateway self-check failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
