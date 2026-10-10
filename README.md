# ERC auto

PC controllers for the ERC WiFi car. The ESP8266 sketch `8266.ino` is the
receiver. It is not part of the Level 1 AI work.

| File | What it is |
| --- | --- |
| `AutoERC_PyQt5.py` | Block-programming UI, plus the Level 1 vision / voice skeleton |
| `123.py` | G27 steering-wheel sender |
| `ps` | Gamepad / wheel dashboard |
| `8266.ino` | Car firmware (UDP listener) |

The car joins its own access point and listens on `192.168.4.1:4210`.
Every controller sends the same datagram: `L:<reverse>,R:<forward>,B:<brake>,S:<servo>`.

## Level 1 AI skeleton

Vision and voice on the PC map to that datagram. They do not define a new
wire protocol. Architecture, the safety rules, and a no-car demo are in
[docs/AI_MVP_L1.md](docs/AI_MVP_L1.md).

```bash
python3 -m pip install -r requirements-ai.txt
ERC_LOG_ONLY=1 python3 -m ai.dry_run
ERC_LOG_ONLY=1 python3 AutoERC_PyQt5.py
```

`ERC_LOG_ONLY=1` prints each `L/R/B/S` line and does not transmit. The same
switch is the **Dry run** checkbox in the UI. OpenCV is only needed for a
real webcam; the vision combo box can simulate green / red / blue / yellow
without a camera.
