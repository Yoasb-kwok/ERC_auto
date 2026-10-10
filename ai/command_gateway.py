"""Map Level 1 intents onto the existing car sender, with safety first.

Priority, highest first:

1. E-stop (latched ``B`` / stop override) — voice, vision, or the UI.
2. Manual / block-program override — AI motion is not transmitted.
3. AI intents from an enabled source.

A stalled AI stream, or a motion intent that is not refreshed, sends one
stop. The ESP8266 firmware is unchanged and does not itself time out; this
watchdog lives on the PC.
"""

from __future__ import annotations

import os
import time

from ai.intents import KNOWN_INTENTS, MOTION_INTENTS, resolve_intent
from ai.wire import format_car_command


def stall_timeout_from_env(default: float = 1.0) -> float:
    """Read ``ERC_AI_STALL_S`` (seconds). Non-positive or junk → ``default``."""
    raw = os.environ.get("ERC_AI_STALL_S", "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if value <= 0:
        return default
    return value


class CommandGateway:
    """Single AI exit onto ``send_car_command(speed, steering, stop_override)``.

    ``sender`` is injected so this module does not import the Qt UI. The
    callable is ``sender(speed, steering_angle, stop_override)`` and should
    return the ``L:,R:,B:,S:`` string (the real sender does).
    """

    def __init__(
        self,
        sender,
        *,
        forward_speed=100,
        turn_speed=50,
        servo_straight=90,
        servo_left=50,
        servo_right=130,
        stop_signal=1,
        stall_timeout_s=1.0,
        coalesce_s=0.3,
        log=None,
        clock=None,
    ):
        self.sender = sender
        self.forward_speed = forward_speed
        self.turn_speed = turn_speed
        self.servo_straight = servo_straight
        self.servo_left = servo_left
        self.servo_right = servo_right
        self.stop_signal = stop_signal
        self.stall_timeout_s = stall_timeout_s
        self.coalesce_s = coalesce_s
        self._log_callback = log
        self._clock = clock or time.monotonic

        self.manual_override = False
        self.estop_latched = False
        # After e-stop or a block program, a held vision color must not resume
        # until a non-motion sample is seen. Voice is an explicit edge.
        self.vision_rearm = False
        self.sources_enabled = {"vision": False, "voice": False}

        self.last_label = "—"
        self.last_intent = "—"
        self.last_command = "—"
        self.last_reason = ""

        self._steering = servo_straight
        self._motion_active = False
        self._last_motion_at = None
        self._last_sample_at = None
        self._last_emit_key = None
        self._last_emit_at = 0.0
        self._logged_command = None
        self._last_log = None

    def set_source_enabled(self, source: str, enabled: bool) -> None:
        """Enable or disable one AI source. The last source off stops motion."""
        if source not in self.sources_enabled:
            self._log(f"unknown AI source {source!r}")
            return
        enabled = bool(enabled)
        self.sources_enabled[source] = enabled
        if enabled:
            self._last_sample_at = self._now()
            self._log(f"{source} AI on")
            return
        self._log(f"{source} AI off")
        if not any(self.sources_enabled.values()):
            self._stop_if_ai_driving(f"{source} disabled")

    def set_manual_override(self, active: bool) -> None:
        """Block programs and other manual paths call this around their run.

        While active, AI intents are logged and dropped. The block runner
        keeps calling ``send_car_command`` itself.
        """
        active = bool(active)
        if active and not self.manual_override:
            self.vision_rearm = True
            self._stop_if_ai_driving("manual override")
            self._log("manual/UI override on; AI will not drive")
        elif not active and self.manual_override:
            self._log("manual/UI override off")
        self.manual_override = active

    def emergency_stop(self, source: str = "ui") -> bool:
        """Latch brake. Beats AI and is still sent during manual override."""
        self.estop_latched = True
        self.vision_rearm = True
        self.last_intent = "estop"
        self._last_sample_at = self._now()
        self._emit(
            0,
            self.servo_straight,
            self.stop_signal,
            reason=f"e-stop:{source}",
            force=True,
        )
        return True

    def clear_estop(self) -> bool:
        """Drop the latch. Does not resume the previous motion command."""
        if not self.estop_latched:
            self._log("Clear e-stop: nothing was latched")
            return False
        self.estop_latched = False
        self.vision_rearm = True
        self._motion_active = False
        self._last_motion_at = None
        self._log(
            "e-stop cleared; car stays stopped. "
            "Vision motion waits for a non-motion sample. Voice commands work now."
        )
        return True

    def acknowledge_external_stop(self) -> None:
        """The block runner already put ``B:1`` on the wire itself."""
        self._motion_active = False
        self._last_motion_at = None
        self._steering = self.servo_straight
        self.last_reason = "block program stop"
        self.last_command = format_car_command(
            0,
            self.servo_straight,
            self.stop_signal,
            servo_min=self.servo_left,
            servo_max=self.servo_right,
            stop_signal=self.stop_signal,
        ).strip()

    def heartbeat(self, source: str, label: str | None = None) -> None:
        """A live sample with no driving intent (no blob, silence, \"none\")."""
        if not self.sources_enabled.get(source, False):
            return
        self._last_sample_at = self._now()
        if label is not None:
            self.last_label = str(label)
        # A non-motion vision sample (no blob, red/stop, "none") re-arms driving.
        if source == "vision" and resolve_intent(label) not in MOTION_INTENTS:
            self.vision_rearm = False

    def submit_intent(self, intent, source: str = "ai", label: str | None = None) -> bool:
        """Accept a canonical intent or any shared-table label (``green``).

        Returns True only when the intent was allowed onto the sender.
        E-stop is accepted even if that source's toggle is off.
        """
        if label is not None:
            self.last_label = str(label)
        resolved = resolve_intent(None if intent is None else str(intent))
        if resolved not in KNOWN_INTENTS:
            self._log(f"no Level 1 intent for {intent!r} from {source}")
            return False
        self.last_intent = resolved

        if resolved == "estop":
            return self.emergency_stop(source)
        if self.estop_latched:
            self._log(f"ignored {resolved} from {source}: e-stop latched")
            return False
        if self.manual_override:
            self._log(f"ignored {resolved} from {source}: manual/UI override")
            return False
        if not self.sources_enabled.get(source, False):
            self._log(f"ignored {resolved} from {source}: {source} AI is off")
            return False
        if source == "vision" and self.vision_rearm and resolved in MOTION_INTENTS:
            self._log(
                f"ignored {resolved} from vision: held until a non-motion sample"
            )
            return False

        if source == "vision" and resolved not in MOTION_INTENTS:
            self.vision_rearm = False
        if source != "vision":
            self.vision_rearm = False

        now = self._now()
        self._last_sample_at = now
        if resolved in MOTION_INTENTS:
            self._last_motion_at = now
        else:
            self._last_motion_at = None
        return self._dispatch(resolved, source)

    def tick(self, now: float | None = None) -> None:
        """Call on a UI timer. One stop if AI motion is not being refreshed."""
        if self.estop_latched or self.manual_override:
            return
        if not any(self.sources_enabled.values()):
            return
        if not self._motion_active:
            return
        now = self._now() if now is None else now
        sample_age = None if self._last_sample_at is None else now - self._last_sample_at
        motion_age = None if self._last_motion_at is None else now - self._last_motion_at
        stalled = (
            sample_age is None
            or sample_age > self.stall_timeout_s
            or motion_age is None
            or motion_age > self.stall_timeout_s
        )
        if stalled:
            self._emit(
                0,
                self._steering,
                self.stop_signal,
                reason="ai stall timeout",
                force=True,
            )

    def safety_status(self) -> str:
        if self.estop_latched:
            return "e-stop latched"
        if self.manual_override:
            return "manual/UI override"
        if self.vision_rearm and self.sources_enabled.get("vision"):
            return "vision held until a non-motion sample"
        if not any(self.sources_enabled.values()):
            return "AI off"
        if self._motion_active:
            return "AI driving"
        return "AI idle"

    def _dispatch(self, intent: str, source: str) -> bool:
        if intent == "forward":
            speed, steering, brake = self.forward_speed, self.servo_straight, 0
        elif intent == "left":
            speed, steering, brake = self.turn_speed, self.servo_left, 0
        elif intent == "right":
            speed, steering, brake = self.turn_speed, self.servo_right, 0
        elif intent == "stop":
            speed, steering, brake = 0, self._steering, self.stop_signal
        else:
            self._log(f"unhandled intent {intent}")
            return False
        return self._emit(speed, steering, brake, reason=f"{source}:{intent}")

    def _stop_if_ai_driving(self, reason: str) -> None:
        if self._motion_active and not self.estop_latched:
            self._emit(
                0,
                self._steering,
                self.stop_signal,
                reason=reason,
                force=True,
            )
        else:
            self._motion_active = False

    def _emit(self, speed, steering, stop_override, reason: str, force: bool = False) -> bool:
        steering = int(max(self.servo_left, min(self.servo_right, steering)))
        self._steering = steering
        now = self._now()
        key = (speed, steering, int(stop_override))
        if (
            not force
            and key == self._last_emit_key
            and (now - self._last_emit_at) < self.coalesce_s
        ):
            # Accepted, but identical to the datagram just sent.
            return True
        try:
            command = self.sender(speed, steering, stop_override)
        except Exception as exc:
            self._log(f"sender error during {reason}: {exc}")
            if force or int(stop_override) != 0:
                self._motion_active = False
                self._last_motion_at = None
            return False
        text = (command or "").strip() or f"L/R/B/S speed={speed} S={steering} B={stop_override}"
        self.last_command = text
        self.last_reason = reason
        self._last_emit_key = key
        self._last_emit_at = now
        moving = int(stop_override) == 0 and speed != 0
        self._motion_active = bool(moving)
        if not moving:
            self._last_motion_at = None
        if force or text != self._logged_command:
            self._logged_command = text
            self._log(f"{reason} -> {text}")
        return True

    def _now(self) -> float:
        return self._clock()

    def _log(self, message: str) -> None:
        if message == self._last_log:
            return
        self._last_log = message
        if self._log_callback is not None:
            self._log_callback(message)
