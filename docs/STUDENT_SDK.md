# ERC student SDK

You drive the car with a few Python functions. You do not write `L:,R:,B:,S:`
strings. The SDK turns your calls into that message for you.

Connect the computer to the car's Wi-Fi access point first (the one started
by `8266.ino`). The car is at `192.168.4.1`, port `4210`.

## Install

From the repo root:

```bash
python3 -m pip install -r requirements-ai.txt
```

PyQt5 is only for the block-programming window. This SDK does not import it.
OpenCV is only for a real webcam. The examples below do not need a camera.

## Dry run (no car)

```bash
ERC_LOG_ONLY=1 python3 examples/level1_color_and_voice.py
```

You should see lines like:

```text
camera saw green
[log-only] L:0,R:100,B:0,S:90
voice heard stop
[log-only] L:0,R:0,B:1,S:90
```

`L:0,R:100,B:0,S:90` is forward. `B:1` is the brake.

`ERC_LOG_ONLY=1` prints the message and does not send it. Take the variable
off only when the car is on the desk and you are ready for it to move.

## Level 1 functions

```python
import erc

erc.move_forward()   # straight ahead
erc.stop()           # brake, not latched
erc.turn_left()
erc.turn_right()
erc.estop()          # brake stays on
erc.clear_estop()    # allow driving again; the car stays still
```

Same functions with Chinese names: `erc.前進()`, `erc.停止()`, `erc.左轉()`,
`erc.右轉()`, `erc.緊急停止()`. Simplified characters work too
(`前进`, `停止`, `左转`, `右转`, `紧急停止`).

`move_forward()` returns `False` when the car refused the command (e-stop
is latched, or manual override is on). It does not raise.

## Color → move

The handler runs once each time the color **changes** to that color.
Seeing green again does not call it a second time until another color
(or no color) happens first.

```python
import erc

@erc.on_color("green")
def see_green(color):
    erc.move_forward()

@erc.on_color("red")
def see_red(color):
    erc.stop()

# Classroom, no webcam:
erc.simulate_color("green")
erc.simulate_color("red")
```

Colors: `green` forward, `red` stop, `blue` left, `yellow` right — but only
if **your handler** says so. `紅`/`红`, `綠`/`绿`, `藍`/`蓝`, `黃`/`黄`
are the same four colors.

A real camera:

```python
erc.run(seconds=30)          # blocks for 30 seconds, then brakes
# or:
with erc.session():          # brakes when the block ends
    input("press Enter to stop")
```

## Voice → stop

```python
@erc.on_voice("stop")
def heard_stop(phrase):
    erc.stop()

@erc.on_voice("前進")
def heard_go(phrase):
    erc.move_forward()

erc.hear("請不要管這句")   # no Level 1 phrase; nothing happens
erc.hear("stop")         # calls heard_stop
erc.hear("前進")         # calls heard_go
```

`stop`, `halt`, `停止`, and `停` are one intent. `前進` and `forward` are
one intent. The handler is called with the text you passed; it does not
have to use that argument (`def heard_stop():` is fine).

`hear` is the Level 1 microphone. A real speech engine is later work. The
loop inside `run()` does not listen to the mic yet; call `hear` yourself,
or type the phrase.

## School model (C2): train in Roboflow, then 4 lines

`on_color` and `on_voice` stay the zero-ML path. Use them when the class
has no trained model. School C2 is the other path: Roboflow train, then
`load_model` + `on_detect`. Students do **not** write a training loop.
This SDK only runs inference and maps a class name to a motion.

1. In Roboflow, create a project, upload photos, and draw boxes. Name the
   classes `stop_sign` and `go_sign` (any names are fine; the SDK uses the
   same strings you typed).
2. Press **Train** on the Roboflow website. That is the whole training
   step. There is no `for epoch in ...` in this repository.
3. Download the ONNX file, or copy the model id (`workspace/project/version`).
   A `.pt` YOLO weights file works the same way as ONNX.
4. Hosted infer needs an API key in the environment. Do not paste it into
   the script:

   ```bash
   export ROBOFLOW_API_KEY="your key from Roboflow"
   ```

5. The student program is these lines:

```python
import erc

erc.load_model("erc-signs.onnx", confidence=0.5)
# hosted, instead of a file:
# erc.load_model(model_id="your-workspace/erc-signs/1")

erc.on_detect("stop_sign", "stop")
erc.on_detect("go_sign", "move_forward")

erc.run(seconds=20)
```

Classroom with no weights file and no key (nothing is trained, nothing is
downloaded):

```python
import erc

erc.load_model(model_id="your-workspace/erc-signs/1")
erc.on_detect("stop_sign", "stop")
erc.on_detect("go_sign", "move_forward")
erc.simulate_detect("go_sign", confidence=0.88)
erc.simulate_detect("stop_sign", confidence=0.93)
```

```bash
ERC_LOG_ONLY=1 python3 examples/roboflow_detect_stop.py
```

`on_detect` uses the same gateway as `move_forward`. E-stop and manual
override still win. A detection cannot clear an e-stop.

The handler runs when that class is at or above the confidence. The default
is `0.5`, or the `confidence=` you passed to `load_model` if you call
`load_model` first. Override one class with
`erc.on_detect("stop_sign", "stop", confidence=0.8)`. The same class does
not fire again until a later frame leaves it out.

YOLO weights and a hosted workflow:

```python
erc.load_model("best.pt", confidence=0.5)
erc.load_model(workflow="detect-signs", workspace="your-workspace")
```

Pass `model_id=` for a hosted model. A typo in a file path is a missing
file, not a Roboflow id.

Optional packages are **not** imported by `import erc`. Install only what
that lesson uses:

```bash
python3 -m pip install -r requirements-detect.txt
```

`requirements-detect.txt` lists `onnxruntime` (ONNX), `ultralytics`
(`.pt` weights), and `inference-sdk` (hosted Roboflow).

## Safety

1. `erc.estop()` latches the brake. `move_forward` and the color, voice,
   and detection handlers' drive calls do nothing until `erc.clear_estop()`.
   Clearing does **not** resume the old speed.
2. Manual / block-program override wins the same way. From a script:
   `erc.set_manual_override(True)`. Turn it off with `False`. E-stop still
   sends while override is on.
3. The PyQt **STOP** / **E-STOP** buttons latch that window's own gateway.
   They are the same rule, in the block UI.

## Level 2 (not running yet)

Compound rules are stored and ignored by Level 1:

```python
@erc.when(color="red", voice="stop")
def both(phrase):
    erc.estop()
```

TODO(L2): run `when` only after both events have happened. Until then, call
`stop` from `on_color("red", ...)` and from `on_voice("stop", ...)`.

## Copy-paste file

`examples/level1_color_and_voice.py` is the Level 1 booklet example.
`examples/roboflow_detect_stop.py` is the school-model example in log-only
mode (no API key, no weights, no network).

## Where the bytes go (you can skip this)

`move_forward` asks `CommandGateway` for the `forward` intent. The gateway
calls the same sender as the block UI. The sender writes one line,
`L:<reverse>,R:<forward>,B:<brake>,S:<steering>`, and ships it to
`192.168.4.1:4210`. Full picture, stall timer, and the block window:
[AI_MVP_L1.md](AI_MVP_L1.md).
