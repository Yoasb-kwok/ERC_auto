"""Student SDK: intents become L/R/B/S, and e-stop still wins."""

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

from ai.wire import format_car_command
from erc.car import Car

ROOT = Path(__file__).resolve().parents[1]


class RecordingSender:
    def __init__(self):
        self.sent = []

    def __call__(self, speed, steering, stop_override=0, dry_run=None, debug=False):
        line = format_car_command(speed, steering, stop_override).strip()
        self.sent.append(line)
        return line


def make_car():
    sender = RecordingSender()
    car = Car(sender=sender, log=lambda _message: None, confirm_frames=1)
    return car, sender


class MotionTests(unittest.TestCase):
    def test_motions_use_the_existing_datagram(self):
        car, sender = make_car()
        self.assertTrue(car.move_forward())
        self.assertEqual(sender.sent[-1], "L:0,R:100,B:0,S:90")
        self.assertTrue(car.turn_left())
        self.assertEqual(sender.sent[-1], "L:0,R:50,B:0,S:50")
        self.assertTrue(car.turn_right())
        self.assertEqual(sender.sent[-1], "L:0,R:50,B:0,S:130")
        self.assertTrue(car.stop())
        self.assertEqual(sender.sent[-1], "L:0,R:0,B:1,S:130")
        self.assertEqual(car.last_command(), "L:0,R:0,B:1,S:130")

    def test_estop_blocks_motion_until_clear_and_does_not_resume(self):
        car, sender = make_car()
        car.move_forward()
        self.assertTrue(car.estop())
        self.assertEqual(sender.sent[-1], "L:0,R:0,B:1,S:90")
        before = len(sender.sent)
        self.assertFalse(car.move_forward())
        self.assertFalse(car.turn_left())
        self.assertEqual(len(sender.sent), before)
        self.assertTrue(car.clear_estop())
        self.assertEqual(len(sender.sent), before)
        self.assertTrue(car.move_forward())
        self.assertEqual(sender.sent[-1], "L:0,R:100,B:0,S:90")

    def test_manual_override_blocks_student_motion_but_estop_sends(self):
        car, sender = make_car()
        car.move_forward()
        car.set_manual_override(True)
        self.assertEqual(sender.sent[-1], "L:0,R:0,B:1,S:90")
        before = len(sender.sent)
        self.assertFalse(car.move_forward())
        self.assertEqual(len(sender.sent), before)
        self.assertTrue(car.estop())
        self.assertGreater(len(sender.sent), before)
        self.assertTrue(car.gateway.estop_latched)


class HandlerTests(unittest.TestCase):
    def test_color_edge_drives_once(self):
        car, sender = make_car()
        seen = []

        def on_green(color):
            seen.append(color)
            car.move_forward()

        def on_red(color):
            seen.append(color)
            car.stop()

        car.on_color("green", on_green)
        car.on_color("紅", on_red)
        self.assertEqual(car.simulate_color("green"), "green")
        car.simulate_color("green")
        self.assertEqual(seen, ["green"])
        self.assertEqual(sender.sent, ["L:0,R:100,B:0,S:90"])
        car.simulate_color("紅")
        self.assertEqual(seen, ["green", "red"])
        self.assertEqual(sender.sent[-1], "L:0,R:0,B:1,S:90")

    def test_voice_aliases_call_the_stop_and_forward_handlers(self):
        car, sender = make_car()
        heard = []
        car.on_voice("前進", lambda phrase: heard.append(("go", phrase)) or car.move_forward())
        car.on_voice("stop", lambda phrase: heard.append(("stop", phrase)) or car.stop())
        self.assertEqual(car.hear("前進"), "forward")
        self.assertEqual(sender.sent[-1], "L:0,R:100,B:0,S:90")
        self.assertEqual(car.hear("please stop now"), "stop")
        self.assertEqual(sender.sent[-1], "L:0,R:0,B:1,S:90")
        self.assertEqual(heard, [("go", "前進"), ("stop", "please stop now")])
        self.assertIsNone(car.hear("dance"))

    def test_unknown_registration_is_an_error(self):
        car, _sender = make_car()
        with self.assertRaises(ValueError):
            car.on_voice("dance", lambda: None)
        with self.assertRaises(ValueError):
            car.on_color("purple", lambda: None)

    def test_handler_with_no_arguments_is_called(self):
        car, sender = make_car()
        car.on_voice("停止", car.stop)
        self.assertEqual(car.hear("停止"), "stop")
        self.assertEqual(sender.sent[-1], "L:0,R:0,B:1,S:90")

    def test_level2_rule_is_stored_and_not_run(self):
        car, _sender = make_car()
        called = []

        @car.when(color="red", voice="stop")
        def both():
            called.append("both")

        car.on_color("red", lambda _color: car.stop())
        car.simulate_color("red")
        car.hear("stop")
        self.assertEqual(called, [])
        self.assertEqual(car.level2_rules[0]["color"], "red")
        self.assertEqual(car.level2_rules[0]["voice"], "stop")

    def test_vision_loop_reports_a_simulated_color(self):
        car, _sender = make_car()
        seen = []
        car.on_color("blue", seen.append)
        car.vision.set_mode("blue")
        car.start()
        try:
            deadline = time.time() + 3
            while time.time() < deadline and seen != ["blue"]:
                time.sleep(0.02)
            self.assertEqual(seen, ["blue"])
        finally:
            car.close()


class ModuleApiTests(unittest.TestCase):
    def test_import_erc_functions_share_one_car(self):
        import erc

        sender = RecordingSender()
        erc.reset_default_car(Car(sender=sender, log=lambda _message: None))
        try:
            self.assertTrue(erc.move_forward())
            self.assertEqual(sender.sent[-1], "L:0,R:100,B:0,S:90")
            self.assertTrue(erc.前進())
            erc.on_voice("stop", erc.stop)
            self.assertEqual(erc.hear("stop"), "stop")
            self.assertEqual(sender.sent[-1], "L:0,R:0,B:1,S:90")
            erc.estop()
            self.assertFalse(erc.turn_right())
            self.assertTrue(erc.get_default_car().gateway.estop_latched)
        finally:
            erc.reset_default_car(None)

    def test_example_script_is_log_only(self):
        env = os.environ.copy()
        env["ERC_LOG_ONLY"] = "1"
        result = subprocess.run(
            [sys.executable, str(ROOT / "examples" / "level1_color_and_voice.py")],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = result.stdout
        self.assertIn("[log-only] L:0,R:100,B:0,S:90", output)
        self.assertIn("[log-only] L:0,R:0,B:1,S:90", output)
        self.assertIn("camera saw green", output)
        self.assertIn("voice heard stop", output)
        self.assertNotIn("UDP Send Error", output + result.stderr)


if __name__ == "__main__":
    unittest.main()
