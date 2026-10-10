"""Level 1 AI skeleton tests. No car, no webcam, no PyQt required."""

import os
import time
import unittest
from pathlib import Path

from ai.command_gateway import CommandGateway
from ai.dry_run import run_demo
from ai.intents import resolve_intent
from ai.vision_l1 import LabelStabilizer, VisionLevel1, classify_frame_bgr, classify_rgb_samples
from ai.voice_l1 import VoiceLevel1, asr_backend
from ai.wire import format_car_command

ROOT = Path(__file__).resolve().parents[1]


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class RecordingSender:
    def __init__(self):
        self.sent = []

    def __call__(self, speed, steering, stop_override=0):
        line = format_car_command(speed, steering, stop_override).strip()
        self.sent.append(line)
        return line


def gateway(sender=None, **kwargs):
    clock = kwargs.pop("clock", None) or _Clock()
    logs = kwargs.pop("logs", [])
    sender = sender or RecordingSender()
    gw = CommandGateway(sender, log=logs.append, clock=clock, stall_timeout_s=1.0, coalesce_s=0.3, **kwargs)
    gw._test_clock = clock
    gw._test_sender = sender
    gw._test_logs = logs
    return gw


class WireTests(unittest.TestCase):
    def test_forward_reverse_and_forced_brake(self):
        self.assertEqual(format_car_command(100, 90, 0), "L:0,R:100,B:0,S:90\n")
        self.assertEqual(format_car_command(-40, 90, 0), "L:40,R:0,B:0,S:90\n")
        self.assertEqual(format_car_command(0, 90, 0), "L:0,R:0,B:1,S:90\n")
        self.assertEqual(format_car_command(0, 90, 1), "L:0,R:0,B:1,S:90\n")

    def test_clamps_match_the_existing_controller(self):
        self.assertEqual(format_car_command(500, 90, 0), "L:0,R:190,B:0,S:90\n")
        self.assertEqual(format_car_command(-999, 90, 0), "L:190,R:0,B:0,S:90\n")
        self.assertEqual(format_car_command(100, 10, 0), "L:0,R:100,B:0,S:50\n")
        self.assertEqual(format_car_command(100, 200, 0), "L:0,R:100,B:0,S:130\n")


class IntentTests(unittest.TestCase):
    def test_shared_table_for_colors_and_speech(self):
        self.assertEqual(resolve_intent("green"), "forward")
        self.assertEqual(resolve_intent("RED"), "stop")
        self.assertEqual(resolve_intent("blue"), "left")
        self.assertEqual(resolve_intent("yellow"), "right")
        self.assertEqual(resolve_intent("  Go   Forward "), "forward")
        self.assertEqual(resolve_intent("please stop now"), "stop")
        self.assertEqual(resolve_intent("turn left"), "left")
        self.assertEqual(resolve_intent("Emergency-Stop"), "estop")
        self.assertEqual(resolve_intent("e-stop"), "estop")
        self.assertIsNone(resolve_intent(""))
        self.assertIsNone(resolve_intent("dance"))
        self.assertIsNone(resolve_intent("none"))

    def test_voice_uses_the_same_table_and_mic_is_a_stub(self):
        voice = VoiceLevel1()
        self.assertEqual(voice.transcript_to_intent("halt"), "stop")
        self.assertIsNone(voice.listen_once())
        self.assertIn(asr_backend(), (None, "speech_recognition", "vosk"))


class VisionTests(unittest.TestCase):
    def test_rgb_samples_pick_a_clear_color_and_reject_ties(self):
        self.assertEqual(classify_rgb_samples([(0, 180, 0)] * 20), "green")
        self.assertEqual(classify_rgb_samples([(200, 0, 0)] * 20), "red")
        self.assertEqual(classify_rgb_samples([(0, 0, 220)] * 20), "blue")
        self.assertEqual(classify_rgb_samples([(220, 210, 10)] * 20), "yellow")
        self.assertIsNone(classify_rgb_samples([(200, 0, 0)] * 10 + [(0, 180, 0)] * 10))
        self.assertIsNone(classify_rgb_samples([(12, 12, 12)] * 20))
        self.assertEqual(classify_frame_bgr([(0, 200, 0)] * 20), "green")

    def test_stabilizer_waits_and_does_not_treat_warmup_as_ready(self):
        stabilizer = LabelStabilizer(2)
        self.assertIsNone(stabilizer.push("green"))
        self.assertFalse(stabilizer.ready)
        self.assertEqual(stabilizer.push("green"), "green")
        self.assertTrue(stabilizer.ready)
        self.assertEqual(stabilizer.push("red"), "green")
        self.assertEqual(stabilizer.push("red"), "red")
        self.assertEqual(stabilizer.push(None), "red")
        self.assertIsNone(stabilizer.push(None))
        stabilizer.reset()
        self.assertFalse(stabilizer.ready)
        self.assertIsNone(stabilizer.push(None))
        self.assertFalse(stabilizer.ready)
        self.assertIsNone(stabilizer.push(None))
        self.assertTrue(stabilizer.ready)

    def test_simulated_green_publishes_forward(self):
        vision = VisionLevel1(camera_index=99, confirm_frames=2)
        vision.set_mode("green")
        vision.start()
        try:
            intent = None
            deadline = time.time() + 3
            while time.time() < deadline:
                _ts, _label, intent = vision.latest()
                if intent == "forward":
                    break
                time.sleep(0.02)
            self.assertEqual(intent, "forward")
            self.assertIn("simulated: green", vision.status_message)
        finally:
            vision.stop()

    def test_opencv_solid_frames_when_installed(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy not installed")
        from ai.vision_l1 import cv2
        if cv2 is None:
            self.skipTest("opencv not installed")
        green = np.zeros((40, 40, 3), dtype=np.uint8)
        green[:, :] = (0, 255, 0)  # BGR green
        red = np.zeros((40, 40, 3), dtype=np.uint8)
        red[:, :] = (0, 0, 255)
        self.assertEqual(classify_frame_bgr(green), "green")
        self.assertEqual(classify_frame_bgr(red), "red")


class GatewayTests(unittest.TestCase):
    def test_forward_left_right_stop_reuse_l_r_b_s(self):
        gw = gateway()
        gw.set_source_enabled("vision", True)
        self.assertTrue(gw.submit_intent("green", source="vision", label="green"))
        self.assertEqual(gw._test_sender.sent[-1], "L:0,R:100,B:0,S:90")
        gw._test_clock.t += 0.4
        self.assertTrue(gw.submit_intent("left", source="vision", label="blue"))
        self.assertEqual(gw._test_sender.sent[-1], "L:0,R:50,B:0,S:50")
        gw._test_clock.t += 0.4
        self.assertTrue(gw.submit_intent("right", source="vision", label="yellow"))
        self.assertEqual(gw._test_sender.sent[-1], "L:0,R:50,B:0,S:130")
        gw._test_clock.t += 0.4
        self.assertTrue(gw.submit_intent("stop", source="vision", label="red"))
        self.assertEqual(gw._test_sender.sent[-1], "L:0,R:0,B:1,S:130")

    def test_identical_motion_is_coalesced(self):
        gw = gateway()
        gw.set_source_enabled("vision", True)
        self.assertTrue(gw.submit_intent("forward", source="vision", label="green"))
        gw._test_clock.t += 0.1
        self.assertTrue(gw.submit_intent("forward", source="vision", label="green"))
        self.assertEqual(len(gw._test_sender.sent), 1)
        gw._test_clock.t += 0.4
        self.assertTrue(gw.submit_intent("forward", source="vision", label="green"))
        self.assertEqual(len(gw._test_sender.sent), 2)

    def test_estop_beats_later_vision_and_clear_does_not_resume(self):
        gw = gateway()
        gw.set_source_enabled("vision", True)
        gw.submit_intent("forward", source="vision", label="green")
        self.assertTrue(gw.emergency_stop("ui"))
        self.assertTrue(gw.estop_latched)
        self.assertEqual(gw._test_sender.sent[-1], "L:0,R:0,B:1,S:90")
        before = len(gw._test_sender.sent)
        self.assertFalse(gw.submit_intent("green", source="vision", label="green"))
        self.assertEqual(len(gw._test_sender.sent), before)
        self.assertTrue(gw.clear_estop())
        self.assertFalse(gw.submit_intent("green", source="vision", label="green"))
        self.assertEqual(len(gw._test_sender.sent), before)
        self.assertEqual(gw.safety_status(), "vision held until a non-motion sample")
        gw.heartbeat("vision", label="none")
        self.assertTrue(gw.submit_intent("green", source="vision", label="green"))
        self.assertEqual(gw._test_sender.sent[-1], "L:0,R:100,B:0,S:90")

    def test_voice_forward_is_allowed_while_vision_is_held(self):
        gw = gateway()
        gw.set_source_enabled("vision", True)
        gw.set_source_enabled("voice", True)
        gw.emergency_stop("ui")
        gw.clear_estop()
        self.assertTrue(gw.vision_rearm)
        self.assertTrue(gw.submit_intent("go forward", source="voice", label="go forward"))
        self.assertEqual(gw._test_sender.sent[-1], "L:0,R:100,B:0,S:90")

    def test_manual_override_blocks_ai_but_estop_still_sends(self):
        gw = gateway()
        gw.set_source_enabled("vision", True)
        gw.submit_intent("forward", source="vision", label="green")
        gw.set_manual_override(True)
        self.assertEqual(gw._test_sender.sent[-1], "L:0,R:0,B:1,S:90")
        before = len(gw._test_sender.sent)
        self.assertFalse(gw.submit_intent("right", source="vision", label="yellow"))
        self.assertEqual(len(gw._test_sender.sent), before)
        self.assertEqual(gw.safety_status(), "manual/UI override")
        self.assertTrue(gw.emergency_stop("ui"))
        self.assertEqual(gw._test_sender.sent[-1], "L:0,R:0,B:1,S:90")
        self.assertGreater(len(gw._test_sender.sent), before)

    def test_estop_phrase_works_with_voice_toggle_off(self):
        gw = gateway()
        gw.set_source_enabled("vision", True)
        gw.submit_intent("forward", source="vision", label="green")
        self.assertFalse(gw.sources_enabled["voice"])
        self.assertTrue(gw.submit_intent("emergency stop", source="voice", label="emergency stop"))
        self.assertTrue(gw.estop_latched)

    def test_turning_the_last_source_off_stops_once(self):
        gw = gateway()
        gw.set_source_enabled("vision", True)
        gw.set_source_enabled("voice", True)
        gw.submit_intent("forward", source="vision", label="green")
        gw.set_source_enabled("vision", False)
        self.assertNotEqual(gw._test_sender.sent[-1], "L:0,R:0,B:1,S:90")
        gw.set_source_enabled("voice", False)
        self.assertEqual(gw._test_sender.sent[-1], "L:0,R:0,B:1,S:90")

    def test_stall_sends_one_stop_and_heartbeat_does_not_keep_motion(self):
        gw = gateway()
        gw.set_source_enabled("vision", True)
        gw.tick()
        self.assertEqual(gw._test_sender.sent, [])
        gw.submit_intent("forward", source="vision", label="green")
        gw._test_clock.t += 0.6
        gw.heartbeat("vision", label="none")
        gw._test_clock.t += 0.6
        gw.tick()
        self.assertEqual(gw._test_sender.sent[-1], "L:0,R:0,B:1,S:90")
        stalled = len(gw._test_sender.sent)
        gw._test_clock.t += 5
        gw.tick()
        self.assertEqual(len(gw._test_sender.sent), stalled)

    def test_refreshed_motion_does_not_stall(self):
        gw = gateway()
        gw.set_source_enabled("vision", True)
        gw.submit_intent("forward", source="vision", label="green")
        gw._test_clock.t += 0.6
        gw.submit_intent("forward", source="vision", label="green")
        gw._test_clock.t += 0.6
        gw.tick()
        self.assertEqual(gw._test_sender.sent[-1], "L:0,R:100,B:0,S:90")

    def test_sender_errors_do_not_raise(self):
        def boom(speed, steering, stop_override=0):
            raise OSError("offline")

        logs = []
        clock = _Clock()
        gw = CommandGateway(boom, log=logs.append, clock=clock)
        gw.set_source_enabled("vision", True)
        self.assertFalse(gw.submit_intent("forward", source="vision", label="green"))
        self.assertTrue(any("sender error" in line for line in logs))
        self.assertTrue(gw.emergency_stop("ui"))
        self.assertTrue(gw.estop_latched)

    def test_unknown_intent_sends_nothing(self):
        gw = gateway()
        gw.set_source_enabled("voice", True)
        self.assertFalse(gw.submit_intent("dance", source="voice", label="dance"))
        self.assertEqual(gw._test_sender.sent, [])

    def test_external_stop_updates_the_displayed_command(self):
        gw = gateway()
        gw.set_source_enabled("vision", True)
        gw.submit_intent("forward", source="vision", label="green")
        gw.acknowledge_external_stop()
        self.assertEqual(gw.last_command, "L:0,R:0,B:1,S:90")
        self.assertFalse(gw._motion_active)


class ControllerSourceTests(unittest.TestCase):
    def test_pyqt_app_wires_the_gateway_and_keeps_the_servo_constant_order(self):
        text = (ROOT / "AutoERC_PyQt5.py").read_text()
        transport = (ROOT / "ai" / "transport.py").read_text()
        self.assertLess(text.index("from ai.transport import"), text.index("current_steering_angle = SERVO_STRAIGHT"))
        self.assertIn("SERVO_STRAIGHT = 90", transport)
        self.assertIn("format_car_command(", transport)
        self.assertIn("forward_speed=FORWARD_SPEED", text)
        self.assertIn("turn_speed=int(FORWARD_SPEED * TURN_SPEED_FACTOR)", text)
        self.assertIn("stop_signal=STOP_SIGNAL", text)
        self.assertIn("Vision AI", text)
        self.assertIn("Voice AI", text)
        self.assertIn("emergency_stop", text)
        self.assertIn("set_manual_override(True)", text)
        self.assertNotIn("ai/", (ROOT / "8266.ino").read_text())


class DryRunTests(unittest.TestCase):
    def test_scripted_demo(self):
        sent = run_demo(log=lambda _message: None)
        self.assertIn("L:0,R:100,B:0,S:90", sent)
        self.assertEqual(sent[-1], "L:0,R:0,B:1,S:90")


class OffscreenUiTests(unittest.TestCase):
    def test_toggles_estop_and_voice_without_a_car(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["ERC_LOG_ONLY"] = "1"
        try:
            from PyQt5.QtWidgets import QApplication
        except ImportError:
            self.skipTest("PyQt5 is not installed")
        try:
            app = QApplication.instance() or QApplication([])
        except Exception as exc:
            self.skipTest(f"Qt offscreen unavailable: {exc}")
        import AutoERC_PyQt5 as ui

        window = ui.MainWindow()
        try:
            self.assertTrue(window.dry_run_box.isChecked() or ui.LOG_ONLY)
            window.dry_run_box.setChecked(True)
            green = window.sim_combo.findData("green")
            window.sim_combo.setCurrentIndex(green)
            window.vision_button.click()
            self.assertTrue(window.vision_button.isChecked())

            deadline = time.time() + 3
            while time.time() < deadline and not window.gateway._motion_active:
                app.processEvents()
                window._on_ai_tick()
                time.sleep(0.02)
            self.assertEqual(window.gateway.last_command, "L:0,R:100,B:0,S:90")
            self.assertEqual(window.gateway.last_label, "green")

            window.stop_program()
            self.assertTrue(window.gateway.estop_latched)
            self.assertIn("B:1", window.gateway.last_command)
            window.run_program()
            self.assertFalse(window.is_executing)

            window._clear_estop()
            self.assertTrue(window.gateway.vision_rearm)
            window._on_ai_tick()
            self.assertFalse(window.gateway._motion_active)

            window.sim_combo.setCurrentIndex(window.sim_combo.findData("none"))
            deadline = time.time() + 3
            while time.time() < deadline and window.gateway.vision_rearm:
                app.processEvents()
                window._on_ai_tick()
                time.sleep(0.02)
            self.assertFalse(window.gateway.vision_rearm)

            window.voice_button.click()
            window.voice_entry.setText("turn left")
            window._submit_voice()
            self.assertEqual(window.gateway.last_intent, "left")
            self.assertEqual(window.gateway.last_command, "L:0,R:50,B:0,S:50")

            window.voice_entry.setText("not a command")
            window._submit_voice()
            self.assertEqual(window.gateway.last_intent, "—")

            window._mic_once()

            # Existing block runner still sends L/R/B/S and takes manual override.
            window.add_block(block_data={
                "name": "Moving Forward",
                "block_type": "Motion",
                "param_type": "duration",
                "default_value": 1,
            })
            block, _func, param_type = window.program_blocks[0]
            self.assertEqual(param_type, "duration")
            block.param_entry.setText("0.05")
            window.run_program()
            self.assertTrue(window.gateway.manual_override)
            deadline = time.time() + 3
            while time.time() < deadline and window.is_executing:
                app.processEvents()
                time.sleep(0.02)
            self.assertFalse(window.is_executing)
            self.assertFalse(window.gateway.manual_override)
            self.assertIn("Move Forward", window.log_text.toPlainText())
            self.assertIn("manual/UI override", window.log_text.toPlainText())
            self.assertEqual(window.gateway.last_command, "L:0,R:0,B:1,S:90")
            window.close()
        finally:
            window.vision.stop()
            if window._ai_timer.isActive():
                window._ai_timer.stop()


if __name__ == "__main__":
    unittest.main()
