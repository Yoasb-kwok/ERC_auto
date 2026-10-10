"""Level 1 demo with no car and no UDP.

Run from the repo root::

    python3 -m ai.dry_run
"""

from __future__ import annotations

import sys

from ai.command_gateway import CommandGateway
from ai.intents import resolve_intent
from ai.voice_l1 import VoiceLevel1
from ai.wire import format_car_command


class _Clock:
    def __init__(self):
        self.t = 1_000.0

    def __call__(self):
        return self.t


def run_demo(log=print) -> list[str]:
    """Script the course demo. Returns the datagrams that would have been sent."""
    sent: list[str] = []
    clock = _Clock()

    def sender(speed, steering, stop_override=0):
        line = format_car_command(speed, steering, stop_override).strip()
        sent.append(line)
        return line

    gateway = CommandGateway(
        sender,
        forward_speed=100,
        turn_speed=50,
        servo_straight=90,
        servo_left=50,
        servo_right=130,
        stop_signal=1,
        stall_timeout_s=1.0,
        coalesce_s=0.3,
        log=log,
        clock=clock,
    )
    voice = VoiceLevel1()

    log("--- vision green → forward ---")
    gateway.set_source_enabled("vision", True)
    assert resolve_intent("green") == "forward"
    assert gateway.submit_intent("green", source="vision", label="green")
    assert sent[-1] == "L:0,R:100,B:0,S:90"

    log("--- voice stop on the same path ---")
    gateway.set_source_enabled("voice", True)
    phrase = "please stop now"
    intent = voice.transcript_to_intent(phrase)
    assert intent == "stop"
    assert gateway.submit_intent(intent, source="voice", label=phrase)
    assert sent[-1] == "L:0,R:0,B:1,S:90"

    log("--- e-stop beats a later vision forward ---")
    assert gateway.submit_intent("forward", source="vision", label="green")
    before = len(sent)
    assert gateway.submit_intent("emergency stop", source="voice", label="emergency stop")
    assert sent[-1] == "L:0,R:0,B:1,S:90"
    assert gateway.estop_latched
    assert not gateway.submit_intent("green", source="vision", label="green")
    assert len(sent) == before + 1

    log("--- clear e-stop; held green does not resume; a none sample re-arms ---")
    assert gateway.clear_estop()
    assert not gateway.submit_intent("green", source="vision", label="green")
    gateway.heartbeat("vision", label="none")
    assert gateway.submit_intent("green", source="vision", label="green")
    assert sent[-1] == "L:0,R:100,B:0,S:90"

    log("--- manual override wins over vision; e-stop still sends ---")
    gateway.set_manual_override(True)
    assert not gateway.submit_intent("right", source="vision", label="yellow")
    assert gateway.emergency_stop("ui")
    assert sent[-1] == "L:0,R:0,B:1,S:90"
    gateway.clear_estop()
    gateway.set_manual_override(False)

    log("--- explicit voice forward is allowed after clear ---")
    assert voice.transcript_to_intent("go forward") == "forward"
    assert gateway.submit_intent("go forward", source="voice", label="go forward")
    assert sent[-1] == "L:0,R:100,B:0,S:90"

    log("--- stall timeout sends one stop ---")
    clock.t += 1.1
    gateway.tick()
    assert sent[-1] == "L:0,R:0,B:1,S:90"
    stall_count = len(sent)
    clock.t += 1.1
    gateway.tick()
    assert len(sent) == stall_count

    log("--- ASR listen_once is a stub (no microphone) ---")
    assert voice.listen_once() is None

    log("Dry run complete. No UDP was sent.")
    return sent


def main(argv=None) -> int:
    del argv
    print("ERC Level 1 dry run (log only, no car, no UDP)")
    print("Wire contract: L:<reverse>,R:<forward>,B:<brake>,S:<servo>")
    try:
        run_demo()
    except AssertionError as exc:
        print(f"Dry run failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
