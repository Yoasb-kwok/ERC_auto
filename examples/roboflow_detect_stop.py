"""School C2: Roboflow trains the model. This script only runs inference.

Students do not write a training loop. This file is log-only: no API key,
no weights, no network. It pretends the model saw a go sign, then a stop sign.

Run from the repo root::

    ERC_LOG_ONLY=1 python3 examples/roboflow_detect_stop.py

A downloaded ONNX file::

    erc.load_model("erc-signs.onnx", confidence=0.5)
    erc.run(seconds=20)

Hosted Roboflow infer (set ROBOFLOW_API_KEY in the environment, never in
this file)::

    erc.load_model(model_id="your-workspace/erc-signs/1")
    erc.run(seconds=20)
"""

import sys
from pathlib import Path

# Running this file puts examples/ on the path. The SDK lives at the repo root.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import erc

erc.load_model(model_id="your-workspace/erc-signs/1")
erc.on_detect("stop_sign", "stop")
erc.on_detect("go_sign", "move_forward")
erc.simulate_detect("go_sign", confidence=0.88)
erc.simulate_detect("stop_sign", confidence=0.93)
print("last command:", erc.last_command())
