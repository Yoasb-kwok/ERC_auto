# ERC Level 1 AI (PC skeleton)

Course demo: one vision command and one voice command both drive the car
through the UDP path that already exists. Emergency stop and the block
program win over those commands.

The ESP8266 sketch is unchanged. If the AI loop on the computer stops
refreshing a motion command, the **PC** sends brake. The firmware still
holds the last packet forever if the whole process dies; a firmware
watchdog is Level 2 and is intentionally not in this change.

## Architecture

```
webcam or simulated color          mic stub or typed phrase
        |                                    |
        v                                    v
  ai/vision_l1.py                    ai/voice_l1.py
  label: green/red/blue/yellow/none  transcript
        \                                  /
         v                                v
              ai/intents.py  resolve_intent
                         |
                         v
              ai/command_gateway.py
              e-stop > manual override > AI
                         |
                         v
              send_car_command() in AutoERC_PyQt5.py
                         |
                         v
              ai/wire.py  →  "L:..,R:..,B:..,S:..\n"
                         |
                         v
              UDP 192.168.4.1:4210     (skipped in dry-run)
                         |
                         v
                    8266.ino parseCommand
```

Block programs do **not** go through the gateway. They keep calling
`send_car_command` directly. While a program is running the gateway is in
manual override, so vision and voice packets are dropped. Pressing **STOP**
or **E-STOP** also latches the brake until **Clear e-stop**.

## UDP contract

One ASCII datagram per packet, newline-terminated. Fields are integers.

| Field | Meaning | PC range |
| --- | --- | --- |
| `L` | Reverse channel (not "left motor") | 0–190 |
| `R` | Forward channel | 0–190 |
| `B` | Brake / stop override. `1` means stop | 0 or 1 |
| `S` | Steering servo degrees | 50–130 (90 straight) |

`L` and `R` are the names the firmware already uses: `R > 0` is forward,
`L > 0` is reverse. Steering is only `S`.

Examples (same strings the dry-run prints):

| Intent | Datagram |
| --- | --- |
| forward | `L:0,R:100,B:0,S:90` |
| left | `L:0,R:50,B:0,S:50` |
| right | `L:0,R:50,B:0,S:130` |
| stop | `L:0,R:0,B:1,S:<held>` |
| e-stop | `L:0,R:0,B:1,S:90` |

Speeds come from the existing constants `FORWARD_SPEED` (100) and
`TURN_SPEED_FACTOR` (0.5). A resting command (`speed == 0` and no explicit
brake) is promoted to `B:1`, which is what `send_car_command` already did.

## Shared intent table

`ai/intents.py` is the only label → intent map. Vision colors and voice
phrases both use it.

| Label or phrase | Intent |
| --- | --- |
| green, go, forward, "go forward" | `forward` |
| red, stop, halt, brake | `stop` |
| blue, left, "turn left" | `left` |
| yellow, right, "turn right" | `right` |
| emergency, "emergency stop", "e-stop" | `estop` |

`estop` is accepted even when the Voice AI toggle is off, so the text box
can still brake. Other voice phrases require the toggle.

## Safety

Highest priority first:

1. **E-stop latch.** UI **STOP**, **E-STOP**, window close, or the phrase
   "emergency stop". Sends `B:1` and ignores later AI motion until
   **Clear e-stop**. Clearing the latch does not replay the last motion.
2. **Manual / block program.** `run_program` sets manual override (and
   refuses to start while e-stop is latched). AI intents are logged and
   dropped. The blocks keep sending their own datagrams. Override turns
   off when the program thread finishes. Starting a program also stops AI
   motion if the car was moving under AI.
3. **AI**, only from a source whose toggle is on.

Extra vision hold: after e-stop, after **Clear e-stop**, or after a block
program, a **held** color (the camera still sees green) does not resume.
Vision motion waits until a non-motion sample: simulated **none**, a red
stop, or a real frame with no blob. A typed or spoken command is an
explicit edge and is allowed immediately. The two-frame color stabilizer
does not count its warmup as that "none" sample.

**Stall timeout** (`ERC_AI_STALL_S`, default 1.0 s). While an AI toggle is
on and the gateway last sent motion, `tick()` (10 Hz from the Qt timer)
sends one brake if either:

- no fresh sample arrives (the vision thread died), or
- no new motion intent arrives (the blob went away; heartbeats of "none"
  do not keep the car rolling).

Turning the last AI toggle off also sends one brake. Identical motion
datagrams are coalesced to about 3 Hz so a solid green blob does not flood
UDP; the refresh timestamp still updates, so coalesce does not look like a
stall.

What this does **not** do: if Python is killed, no further UDP is sent and
the current firmware keeps the last motor command. Do not "fix" that inside
`8266.ino` for Level 1.

## Level 1 pieces

| Module | Level 1 behavior | Left for later |
| --- | --- | --- |
| `ai/wire.py` | Formats `L,R,B,S` | — |
| `ai/intents.py` | Color and phrase table | More phrases, confidence |
| `ai/command_gateway.py` | Map intent → speed/servo, e-stop, override, stall | Closed-loop servo from a centroid |
| `ai/vision_l1.py` | HSV blob if OpenCV is installed; otherwise simulate a label. Two matching frames before the label changes | `TODO(C2)`: largest contour, centroid → steering, hysteresis |
| `ai/voice_l1.py` | Text box uses the intent table. `listen_once()` returns None | `TODO(C3)`: one-shot `speech_recognition` or Vosk, honor `timeout_s`, return a transcript only |
| `AutoERC_PyQt5.py` | Toggles, last label, last command, dry-run | Don't rewrite the block widgets |

`VisionLevel1.latest()` is `(timestamp, label, intent)`. `listen_once()`
should stay "return a string or None". The UI already feeds that string to
`transcript_to_intent`.

## Demo with no car

From the repo root:

```bash
python3 -m pip install -r requirements-ai.txt
python3 -m unittest discover -s tests -v
ERC_LOG_ONLY=1 python3 -m ai.dry_run
```

`ai.dry_run` never opens a socket. It prints the scripted course path:
green → forward, a voice "stop", e-stop rejecting the next green, manual
override, then a stall brake.

UI, still with no car:

```bash
ERC_LOG_ONLY=1 python3 AutoERC_PyQt5.py
```

1. **Dry run** is checked (because of the env var). The race log and the
   terminal show `[log-only] L:...` instead of UDP.
2. Turn **Vision AI** on. Set **Vision input** to **Simulate green**.
   Last command becomes `L:0,R:100,B:0,S:90`.
3. Switch the combo to **Simulate red**, or enable **Voice AI** and send
   `stop`. Last command becomes a brake.
4. Press **E-STOP**. Switch back to green: the label may still read green,
   and Safety stays **e-stop latched**. **START RACE** will not run.
5. **Clear e-stop**. Green still does not drive. Choose **Simulate none**,
   then green again (or send `forward` on the voice line).
6. Drag a block and press **START RACE**. Safety shows manual override;
   simulated green does not move the wire until the program finishes.
   After the program, vision stays held until a non-motion sample.

Webcam (optional): install the requirements, set **Vision input** to
**Camera**. `ERC_CAMERA_INDEX` picks the device (default `0`). If OpenCV
or the camera is missing, the source line says so and the car is not
commanded. Use the simulate entries in class.

Useful env vars:

| Variable | Default | Role |
| --- | --- | --- |
| `ERC_LOG_ONLY` | off | `1` / `true` / `yes` / `on` skips UDP. The checkbox can turn it back off. |
| `ERC_AI_STALL_S` | `1.0` | Seconds without a refreshed motion intent before brake |
| `ERC_CAMERA_INDEX` | `0` | OpenCV camera index |

## Level 2 roadmap

- Replace the full-frame color vote with the largest contour. Drive `S`
  from the blob's x-position instead of only left/right intents. Keep
  publishing a label into `resolve_intent` so the gateway stays the safety
  layer.
- Real push-to-talk inside `VoiceLevel1.listen_once`. Do not send UDP from
  the recognizer.
- Debounce flicker (the two-frame stabilizer is only a start).
- Firmware deadman: if UDP is silent for a few hundred milliseconds, brake.
  That is an `8266.ino` change, separate from this PC skeleton.
