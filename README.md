# ERC auto

Students start with the Python SDK. You call `erc.move_forward()` and
`erc.on_color` / `erc.on_voice`. You do not write UDP strings.
Booklet: [docs/STUDENT_SDK.md](docs/STUDENT_SDK.md).

```bash
python3 -m pip install -r requirements-ai.txt
ERC_LOG_ONLY=1 python3 examples/level1_color_and_voice.py
```

The ESP8266 sketch `8266.ino` is the receiver. It is not part of the Level 1 AI work.

| File | What it is |
| --- | --- |
| `erc/` | Student SDK (`import erc`) |
| `AutoERC_PyQt5.py` | Block-programming UI, plus the Level 1 vision / voice skeleton |
| `123.py` | G27 steering-wheel sender |
| `ps` | Gamepad / wheel dashboard |
| `8266.ino` | Car firmware (UDP listener) |

The car joins its own access point and listens on `192.168.4.1:4210`.
The SDK and the block UI both end in the same datagram:
`L:<reverse>,R:<forward>,B:<brake>,S:<servo>`.

## Level 1

Use [docs/STUDENT_SDK.md](docs/STUDENT_SDK.md) in class. The page behind the
SDK (intent table, e-stop, stall timer, block window) is
[docs/AI_MVP_L1.md](docs/AI_MVP_L1.md).

School C2 trains in Roboflow, then calls `erc.load_model` and `erc.on_detect`.
Students do not write a training loop. Optional detect packages live in
`requirements-detect.txt` and are not imported by `import erc`.

## Boss demo1 (soft)

One window, no camera, no change to `8266.ino`. Coins and power-ups stay on
the PC. The soft gateway rewrites the outgoing `L/R/B/S` line, then uses the
same sender as the block UI. If `ERC_LOG_ONLY` is unset, the demo sets it to
`1` and only prints datagrams.

```bash
python3 -m pip install -r requirements-ai.txt
ERC_LOG_ONLY=1 python3 examples/demo1_mario_soft.py
```

Arrows or WASD drive the virtual car. Space, a click on a coin, or
`simulate_detect("coin")` scores +1. Keys `1`–`4` are Boost (`R × 1.5`, cap
255, 2s), Slow (`R × 0.4`, 2s), Freeze (`B:1`, 1.5s), and steer bias
(`S + 30`, 2s). The oil patch is Slow. Esc or **E-STOP** cancels power-ups;
**Clear e-stop** does not restore them. The HUD shows score, remaining coins,
the current power-up and countdown, e-stop, and the UDP log-only switch.

## Advanced: the datagram

Only read this if you are changing the PC sender or the firmware. Level 1
students should stay on the SDK.

`L` is reverse, `R` is forward, `B` is the brake (1 = stop), `S` is the
steering servo. `ai/transport.py` is the only place that sends those bytes.
`ERC_LOG_ONLY=1` prints them and does not transmit.

```bash
python3 -m pip install -r requirements-ai.txt
ERC_LOG_ONLY=1 python3 -m ai.dry_run
ERC_LOG_ONLY=1 python3 AutoERC_PyQt5.py
```

`ERC_LOG_ONLY=1` prints each `L/R/B/S` line and does not transmit. The same
switch is the **Dry run** checkbox in the UI. OpenCV is only needed for a
real webcam; the vision combo box can simulate green / red / blue / yellow
without a camera.
