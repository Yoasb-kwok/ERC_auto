"""Level 1 vision: webcam color blob, or a simulated label.

Green → forward, red → stop, blue → left, yellow → right, via the shared
intent table. OpenCV is optional. Without it, or without a camera, use
``set_mode`` to inject a label (the UI combo box does this).

TODO(C2): largest contour + centroid, then scale the servo from x-offset
instead of four hard intents. Keep ``latest()`` as ``(timestamp, label, intent)``.
"""

from __future__ import annotations

import os
import threading
import time

from ai.intents import resolve_intent

try:
    import cv2
except ImportError:  # pragma: no cover - environment without OpenCV
    cv2 = None

COLOR_LABELS = ("green", "red", "blue", "yellow")
VALID_MODES = ("camera", "none") + COLOR_LABELS

# Pixel-count fraction of the frame required before a color wins.
MIN_AREA_FRACTION = 0.02
MIN_PIXELS = 20


def camera_index_from_env(default: int = 0) -> int:
    raw = os.environ.get("ERC_CAMERA_INDEX", "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class LabelStabilizer:
    """Require the same label for ``confirm_frames`` updates before it changes.

    ``None`` means no color. A single noisy frame cannot command the car.
    """

    def __init__(self, confirm_frames: int = 2):
        self.confirm_frames = max(1, int(confirm_frames))
        self.stable = None
        self.ready = False
        self._candidate = None
        self._hits = 0

    def reset(self) -> None:
        self.stable = None
        self.ready = False
        self._candidate = None
        self._hits = 0

    def push(self, label: str | None):
        if self.ready and label == self.stable:
            self._candidate = label
            self._hits = 0
            return self.stable
        if label == self._candidate:
            self._hits += 1
        else:
            self._candidate = label
            self._hits = 1
        if self._hits >= self.confirm_frames:
            self.stable = label
            self.ready = True
        if not self.ready:
            return None
        return self.stable


def classify_rgb_samples(samples) -> str | None:
    """Majority saturated color in ``(r, g, b)`` samples, or None.

    Used directly in tests and as the fallback when OpenCV is not installed
    but the caller already has pixels. TODO(C2): contour area, not a vote.
    """
    counts = {name: 0 for name in COLOR_LABELS}
    for pixel in samples:
        if len(pixel) < 3:
            continue
        red, green, blue = int(pixel[0]), int(pixel[1]), int(pixel[2])
        if red > 90 and red > green + 40 and red > blue + 40:
            counts["red"] += 1
        elif green > 90 and green > red + 30 and green > blue + 30:
            counts["green"] += 1
        elif blue > 90 and blue > red + 30 and blue > green + 20:
            counts["blue"] += 1
        elif red > 90 and green > 90 and blue < 80 and abs(red - green) < 60:
            counts["yellow"] += 1
    return _winner(counts, minimum=8)


def classify_frame_bgr(frame) -> str | None:
    """Return ``green`` / ``red`` / ``blue`` / ``yellow`` / None for one frame.

    Numpy frames go through OpenCV HSV masks when ``cv2`` is importable.
    A sequence of RGB triples uses :func:`classify_rgb_samples`.
    """
    if frame is None:
        return None
    if cv2 is not None and hasattr(frame, "shape"):
        return _classify_opencv(frame)
    if isinstance(frame, (list, tuple)):
        return classify_rgb_samples(frame)
    return None


def _winner(counts: dict, minimum: int) -> str | None:
    best = max(counts, key=counts.get)
    best_n = counts[best]
    second = max(count for name, count in counts.items() if name != best)
    if best_n < minimum or best_n <= second:
        return None
    return best


def _classify_opencv(frame) -> str | None:
    if frame.size == 0 or len(getattr(frame, "shape", ())) != 3:
        return None
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    masks = {
        "red": cv2.bitwise_or(
            cv2.inRange(hsv, (0, 80, 80), (10, 255, 255)),
            cv2.inRange(hsv, (170, 80, 80), (180, 255, 255)),
        ),
        "yellow": cv2.inRange(hsv, (18, 80, 80), (34, 255, 255)),
        "green": cv2.inRange(hsv, (36, 80, 80), (85, 255, 255)),
        "blue": cv2.inRange(hsv, (100, 80, 80), (130, 255, 255)),
    }
    counts = {name: int(cv2.countNonZero(mask)) for name, mask in masks.items()}
    area = int(frame.shape[0] * frame.shape[1])
    threshold = max(MIN_PIXELS, int(area * MIN_AREA_FRACTION))
    return _winner(counts, minimum=threshold)


class VisionLevel1:
    """Background sampler. The UI thread only reads :meth:`latest`.

    Modes
    -----
    camera
        ``cv2.VideoCapture``. Missing OpenCV or a closed camera stays in a
        placeholder and reports that on ``status_message`` (no crash).
    green / red / blue / yellow / none
        Dry-run labels. ``none`` is a live non-motion sample.
    """

    def __init__(self, camera_index: int | None = None, confirm_frames: int = 2):
        self.camera_index = (
            camera_index_from_env() if camera_index is None else int(camera_index)
        )
        self._stabilizer = LabelStabilizer(confirm_frames)
        self._mode = "camera"
        self._latest = (None, None, None)  # monotonic ts, label, intent
        self.status_message = "stopped"
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None

    @property
    def mode(self) -> str:
        with self._lock:
            return self._mode

    def set_mode(self, mode: str) -> None:
        if mode not in VALID_MODES:
            mode = "camera"
        with self._lock:
            self._mode = mode
            self._stabilizer.reset()

    def latest(self):
        """``(timestamp_or_None, label_or_None, intent_or_None)``."""
        with self._lock:
            return self._latest

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._loop,
            name="erc-vision-l1",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_s: float = 1.5) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=timeout_s)
        self._thread = None
        with self._lock:
            self.status_message = "stopped"

    def _loop(self) -> None:
        cap = None
        try:
            while not self._stop_event.is_set():
                mode = self.mode
                if mode != "camera" and cap is not None:
                    cap.release()
                    cap = None
                raw_label, status, cap = self._sample(mode, cap)
                with self._lock:
                    if self._mode != mode:
                        # Drop a frame sampled just as the operator switched mode.
                        pass
                    else:
                        stable = self._stabilizer.push(raw_label)
                        if not self._stabilizer.ready:
                            # Warmup is not a "none" sample, so it cannot clear e-stop re-arm.
                            self.status_message = f"{status} (confirming)"
                        else:
                            intent = resolve_intent(stable) if stable else None
                            self._latest = (time.monotonic(), stable, intent)
                            self.status_message = status
                self._stop_event.wait(0.1)
        finally:
            if cap is not None:
                cap.release()

    def _sample(self, mode: str, cap):
        if mode == "none":
            return None, "simulated: none", cap
        if mode in COLOR_LABELS:
            return mode, f"simulated: {mode}", cap
        if cv2 is None:
            return None, "placeholder: install opencv-python (see README)", cap
        if cap is None:
            cap = cv2.VideoCapture(self.camera_index)
            if not cap.isOpened():
                cap.release()
                return None, f"placeholder: camera {self.camera_index} did not open", None
        ok, frame = cap.read()
        if not ok:
            return None, f"camera {self.camera_index} read failed", cap
        label = classify_frame_bgr(frame)
        return label, f"camera {self.camera_index}", cap
