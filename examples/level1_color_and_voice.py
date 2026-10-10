"""Level 1 student script. No car required.

Run from the repo root::

    ERC_LOG_ONLY=1 python3 examples/level1_color_and_voice.py
"""

import sys
from pathlib import Path

# Running this file puts examples/ on the path. The SDK lives at the repo root.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import erc


@erc.on_color("green")
def see_green(color):
    print("camera saw", color)
    erc.move_forward()


@erc.on_color("red")
def see_red(color):
    print("camera saw", color)
    erc.stop()


@erc.on_voice("前進")
def heard_forward(phrase):
    print("voice heard", phrase)
    erc.move_forward()


@erc.on_voice("stop")
def heard_stop(phrase):
    print("voice heard", phrase)
    erc.stop()


def main():
    # Pretend the camera saw green, then the driver said stop, then e-stop.
    erc.simulate_color("green")
    erc.hear("stop")
    erc.simulate_color("red")
    erc.estop()
    print("last command:", erc.last_command())
    print("e-stop latched; call erc.clear_estop() before driving again")


if __name__ == "__main__":
    main()
