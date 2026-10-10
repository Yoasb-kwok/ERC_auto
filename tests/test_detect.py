"""Inference hooks: load a model, map a class to a motion, no training loop."""

import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from ai.wire import format_car_command
from erc.car import Car
from erc.detect import (
    Detection,
    OnnxDetector,
    RoboflowDetector,
    build_model,
    canonical_class,
    decode_yolo_onnx,
    detections_from_roboflow,
)

ROOT = Path(__file__).resolve().parents[1]


class RecordingSender:
    def __init__(self):
        self.sent = []

    def __call__(self, speed, steering, stop_override=0, dry_run=None, debug=False):
        line = format_car_command(speed, steering, stop_override).strip()
        self.sent.append(line)
        return line


def make_car(log=None):
    sender = RecordingSender()
    car = Car(sender=sender, log=log if log is not None else (lambda _message: None), confirm_frames=1)
    return car, sender


class ClassNameTests(unittest.TestCase):
    def test_canonical_class_folds_spaces_and_hyphens(self):
        self.assertEqual(canonical_class("Stop Sign"), "stop_sign")
        self.assertEqual(canonical_class("stop-sign"), "stop_sign")
        self.assertEqual(canonical_class("  go_sign "), "go_sign")


class DetectHandlerTests(unittest.TestCase):
    def test_stop_sign_maps_to_the_brake_datagram(self):
        car, sender = make_car()
        car.on_detect("stop_sign", "stop")
        car.simulate_detect("stop_sign", confidence=0.93)
        self.assertEqual(sender.sent, ["L:0,R:0,B:1,S:90"])

    def test_confidence_below_the_handler_does_not_fire(self):
        car, sender = make_car()
        car.on_detect("stop_sign", "stop", confidence=0.8)
        car.simulate_detect("stop_sign", confidence=0.7)
        self.assertEqual(sender.sent, [])
        car.simulate_detect("stop_sign", confidence=0.81)
        self.assertEqual(sender.sent, ["L:0,R:0,B:1,S:90"])

    def test_same_class_does_not_refire_until_it_leaves_the_frame(self):
        car, sender = make_car()
        fired = []

        def on_stop(label, confidence):
            fired.append(confidence)
            car.stop()

        car.on_detect("stop_sign", on_stop)
        car.simulate_detect("stop_sign", confidence=0.9)
        car.simulate_detect("stop_sign", confidence=0.95)
        self.assertEqual(fired, [0.9])
        self.assertEqual(len(sender.sent), 1)
        car.simulate_detect("road", confidence=0.99)
        time.sleep(0.35)
        car.simulate_detect("stop_sign", confidence=0.91)
        self.assertEqual(fired, [0.9, 0.91])
        self.assertEqual(sender.sent, ["L:0,R:0,B:1,S:90", "L:0,R:0,B:1,S:90"])

    def test_estop_blocks_a_mapped_move_forward(self):
        car, sender = make_car()
        car.on_detect("go_sign", "move_forward")
        car.estop()
        before = len(sender.sent)
        car.simulate_detect("go_sign", confidence=0.99)
        self.assertEqual(len(sender.sent), before)
        self.assertNotIn("L:0,R:100,B:0,S:90", sender.sent)

    def test_callable_receives_the_raw_label(self):
        car, _sender = make_car()
        seen = []
        car.on_detect("Stop Sign", lambda label, confidence: seen.append((label, confidence)))
        car.simulate_detect("stop sign", confidence=0.66)
        self.assertEqual(seen, [("stop sign", 0.66)])

    def test_chinese_stop_and_move_forward_names_bind_to_methods(self):
        car, sender = make_car()
        car.on_detect("go_sign", "move_forward")
        car.on_detect("halt_sign", "停止")
        car.simulate_detect("go_sign", confidence=0.9)
        self.assertEqual(sender.sent[-1], "L:0,R:100,B:0,S:90")
        car.simulate_detect("halt_sign", confidence=0.9)
        self.assertEqual(sender.sent[-1], "L:0,R:0,B:1,S:90")

    def test_unknown_action_and_bad_confidence_are_errors(self):
        car, _sender = make_car()
        with self.assertRaises(ValueError):
            car.on_detect("stop_sign", "dance")
        with self.assertRaises(ValueError):
            car.on_detect("stop_sign", "stop", confidence=1.5)


class LoadModelTests(unittest.TestCase):
    def test_missing_weights_are_not_a_roboflow_id(self):
        with self.assertRaises(FileNotFoundError):
            build_model("your-workspace/erc-signs/1")
        with self.assertRaises(FileNotFoundError):
            build_model("missing-weights.onnx")
        with self.assertRaises(FileNotFoundError):
            build_model("missing-weights.pt")

    def test_unknown_suffix_is_rejected(self):
        with tempfile.NamedTemporaryFile(suffix=".txt") as handle:
            handle.write(b"not a model")
            handle.flush()
            with self.assertRaises(ValueError):
                build_model(handle.name)

    def test_one_byte_onnx_constructs_without_the_runtime(self):
        fd, name = tempfile.mkstemp(suffix=".onnx")
        try:
            os.write(fd, b"x")
            os.close(fd)
            detector = OnnxDetector(name)
            self.assertIsNone(detector._session)
            self.assertTrue(name.endswith(".onnx"))
        finally:
            os.remove(name)

    def test_model_id_returns_roboflow_and_warns_without_a_key(self):
        saved = os.environ.pop("ROBOFLOW_API_KEY", None)
        logs = []
        try:
            car, _sender = make_car(log=logs.append)
            detector = car.load_model(model_id="your-workspace/erc-signs/1")
            self.assertIsInstance(detector, RoboflowDetector)
            self.assertIsNone(detector.api_key)
            self.assertTrue(any("ROBOFLOW_API_KEY" in line for line in logs))
            self.assertNotIn("inference_sdk", sys.modules)
        finally:
            if saved is not None:
                os.environ["ROBOFLOW_API_KEY"] = saved

    def test_predict_without_a_key_names_the_env_var(self):
        saved = os.environ.pop("ROBOFLOW_API_KEY", None)
        try:
            detector = build_model(model_id="ws/erc-signs/1")
            with self.assertRaises(RuntimeError) as ctx:
                detector.predict(None)
            self.assertIn("ROBOFLOW_API_KEY", str(ctx.exception))
        finally:
            if saved is not None:
                os.environ["ROBOFLOW_API_KEY"] = saved

    def test_predict_with_a_key_asks_for_inference_sdk_when_missing(self):
        try:
            import inference_sdk  # noqa: F401
        except ImportError:
            installed = False
        else:
            installed = True
        if installed:
            self.skipTest("inference-sdk is installed; hosted call is not exercised")
        detector = RoboflowDetector(model_id="ws/erc/1", api_key="test-not-a-real-key")
        with self.assertRaises(ImportError) as ctx:
            detector.predict(object())
        self.assertIn("inference-sdk", str(ctx.exception))

    def test_workflow_without_workspace_is_rejected(self):
        with self.assertRaises(ValueError):
            build_model(workflow="detect-signs")
        detector = build_model(workflow={"workspace": "acme", "workflow_id": "signs"})
        self.assertEqual(detector.workspace, "acme")
        self.assertEqual(detector.workflow, "signs")
        self.assertIsNone(detector.model_id)


class ParserTests(unittest.TestCase):
    def test_roboflow_payload_keeps_the_best_box_above_the_threshold(self):
        payload = {
            "outputs": [
                {
                    "predictions": [
                        {
                            "class": "stop_sign",
                            "confidence": 0.93,
                            "x": 1,
                            "y": 2,
                            "width": 3,
                            "height": 4,
                        },
                        {
                            "class": "go_sign",
                            "confidence": 0.2,
                            "x": 0,
                            "y": 0,
                            "width": 1,
                            "height": 1,
                        },
                        {
                            "class": "stop_sign",
                            "confidence": 0.4,
                            "x": 5,
                            "y": 5,
                            "width": 1,
                            "height": 1,
                        },
                    ]
                }
            ]
        }
        found = detections_from_roboflow(payload, 0.5)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].label, "stop_sign")
        self.assertAlmostEqual(found[0].confidence, 0.93)
        self.assertEqual(found[0].box, (1.0, 2.0, 3.0, 4.0))

    def test_decode_yolo_onnx_transposes_and_names_classes(self):
        numpy = _numpy_or_skip()
        output = numpy.zeros((1, 6, 10), dtype=numpy.float32)
        output[0, 0, 0] = 10
        output[0, 1, 0] = 11
        output[0, 2, 0] = 12
        output[0, 3, 0] = 13
        output[0, 4, 0] = 0.2
        output[0, 5, 0] = 0.9
        output[0, 4, 1] = 0.1
        found = decode_yolo_onnx(output, ["go_sign", "stop_sign"], 0.5)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].label, "stop_sign")
        self.assertAlmostEqual(found[0].confidence, 0.9)
        self.assertEqual(found[0].box, (10.0, 11.0, 12.0, 13.0))
        unnamed = decode_yolo_onnx(output, None, 0.5)
        self.assertEqual(unnamed[0].label, "class_1")


class LoopTests(unittest.TestCase):
    def test_loaded_model_predicts_on_a_new_camera_frame(self):
        car, sender = make_car()
        car.vision.set_mode("none")
        seen = []

        class FakeModel:
            def predict(self, frame):
                seen.append(frame)
                return [Detection("stop_sign", 0.91)]

        car._model = FakeModel()
        car.on_detect("stop_sign", "stop")
        car.vision.latest_frame = lambda: (42.0, "frame-bytes")
        car.start()
        try:
            deadline = time.time() + 3
            while time.time() < deadline and not sender.sent:
                time.sleep(0.02)
            self.assertEqual(sender.sent, ["L:0,R:0,B:1,S:90"])
            self.assertEqual(seen, ["frame-bytes"])
        finally:
            car.close()

    def test_predict_errors_are_logged_once_and_the_loop_stays_up(self):
        logs = []
        car, _sender = make_car(log=logs.append)
        car.vision.set_mode("none")

        class Boom:
            def predict(self, frame):
                raise RuntimeError("nope")

        car._model = Boom()
        car.vision.latest_frame = lambda: (7.0, object())
        car.start()
        try:
            deadline = time.time() + 1.0
            while time.time() < deadline and not any("nope" in line for line in logs):
                time.sleep(0.02)
            self.assertTrue(car._running)
            self.assertEqual(sum("detect predict failed" in line for line in logs), 1)
        finally:
            car.close()


class ImportAndExampleTests(unittest.TestCase):
    def test_import_does_not_load_optional_detectors(self):
        script = textwrap.dedent(
            f"""
            import sys
            sys.path.insert(0, {str(ROOT)!r})
            import erc
            import erc.detect
            banned = ("onnxruntime", "ultralytics", "inference_sdk", "roboflow")
            hit = [name for name in banned if name in sys.modules]
            print(",".join(hit))
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_example_is_log_only_without_a_key(self):
        env = os.environ.copy()
        env["ERC_LOG_ONLY"] = "1"
        env.pop("ROBOFLOW_API_KEY", None)
        result = subprocess.run(
            [sys.executable, str(ROOT / "examples" / "roboflow_detect_stop.py")],
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
        self.assertIn("ROBOFLOW_API_KEY", output)
        self.assertNotIn("UDP Send Error", output + result.stderr)


def _numpy_or_skip():
    try:
        import numpy
    except ImportError:
        raise unittest.SkipTest("numpy is not installed")
    return numpy


if __name__ == "__main__":
    unittest.main()
