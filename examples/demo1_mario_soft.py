"""Boss demo1 Soft — virtual coins, power-ups, and score.

No camera. Does not modify ``8266.ino``. Power-ups rewrite outgoing
``L/R/B/S`` in ``ai.soft_gateway`` before ``ai.transport`` sends them.

Run from the repo root::

    ERC_LOG_ONLY=1 python3 examples/demo1_mario_soft.py

If ``ERC_LOG_ONLY`` is unset, the demo sets it to 1 and only prints datagrams.

Keys: arrows or WASD drive, Space collects a coin, 1 Boost, 2 Slow,
3 Freeze, 4 Steer bias, Esc e-stop. Click a coin on the map.
The oil patch applies Slow. ``simulate_detect("coin")`` is the same pickup
as Space (about 30% of pickups also start Boost).
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ai.demo1_window import ensure_demo1_log_only, run


def main(argv=None) -> int:
    ensure_demo1_log_only()
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
