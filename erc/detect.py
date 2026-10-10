"""Inference-only detectors for the student SDK.

Schools train in Roboflow (or export weights). This module only loads a
model and returns detections. There is no training loop here.

``onnxruntime``, ``ultralytics``, and ``inference-sdk`` are imported inside
``predict``, so ``import erc`` and ``import erc.detect`` do not require them.
Install the ones you use from ``requirements-detect.txt``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Detection:
    """One class the model saw.

    ``box`` is ``(x, y, width, height)`` when the backend provides it.
    """

    label: str
    confidence: float
    box: tuple | None = None


def canonical_class(name: str | None) -> str:
    """``Stop Sign`` and ``stop-sign`` both become ``stop_sign``."""
    if name is None:
        return ""
    text = str(name).strip().lower().replace("-", " ").replace("_", " ")
    text = "_".join(text.split())
    return text


def decode_yolo_onnx(output, class_names, confidence: float) -> list[Detection]:
    """Best box per class from a YOLO-style ONNX tensor.

    Numpy is imported here. ``output`` is squeezed to 2D. If the first axis
    is shorter than the second (Ultralytics export ``(4+nc, N)``), it is
    transposed to ``(N, 4+nc)``. Columns ``0:4`` are xywh. The rest are
    class scores. No NMS: one detection per class, the highest score.
    Missing names become ``class_0``, ``class_1``, ...
    """
    import numpy as np

    array = np.squeeze(np.asarray(output))
    if array.ndim == 1:
        array = array.reshape(1, -1)
    if array.ndim != 2:
        raise ValueError(f"unexpected YOLO output shape {tuple(array.shape)}")
    if array.shape[0] < array.shape[1]:
        array = array.T
    if array.shape[1] < 5:
        return []
    boxes = array[:, :4]
    scores = array[:, 4:]
    best: dict[str, Detection] = {}
    for row_box, score_row in zip(boxes, scores):
        index = int(np.argmax(score_row))
        conf = float(score_row[index])
        if conf < confidence:
            continue
        label = _label_for_index(class_names, index)
        previous = best.get(label)
        if previous is None or conf > previous.confidence:
            xywh = tuple(float(value) for value in row_box[:4])
            best[label] = Detection(label=label, confidence=conf, box=xywh)
    return list(best.values())


def detections_from_roboflow(payload, confidence: float) -> list[Detection]:
    """Read Roboflow infer / workflow JSON. No network.

    Looks for ``predictions`` lists of ``{class, confidence, x, y, width, height}``.
    Nested workflow outputs are walked. Below ``confidence`` is dropped.
    One detection per class name (the highest score).
    """
    found: list = []
    _collect_predictions(payload, found)
    best: dict[str, Detection] = {}
    for item in found:
        if not isinstance(item, dict):
            continue
        label = item.get("class") or item.get("class_name") or item.get("label")
        if not label:
            continue
        raw_conf = item.get("confidence", item.get("confidence_score", 0.0))
        try:
            conf = float(raw_conf)
        except (TypeError, ValueError):
            continue
        if conf < confidence:
            continue
        box = _box_from_mapping(item)
        key = str(label)
        previous = best.get(key)
        if previous is None or conf > previous.confidence:
            best[key] = Detection(label=key, confidence=conf, box=box)
    return list(best.values())


class OnnxDetector:
    """Local ONNX weights. The file must exist. The runtime loads on ``predict``."""

    def __init__(self, path, confidence: float = 0.5):
        self.path = os.fspath(path)
        if not os.path.isfile(self.path):
            raise FileNotFoundError(self.path)
        self.confidence = float(confidence)
        self._session = None
        self._names = _names_from_sidecar(self.path)

    def predict(self, frame) -> list[Detection]:
        import numpy as np

        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise ImportError(
                "onnxruntime is not installed. "
                "pip install -r requirements-detect.txt"
            ) from exc
        if self._session is None:
            self._session = ort.InferenceSession(
                self.path,
                providers=["CPUExecutionProvider"],
            )
            if not self._names:
                self._names = _names_from_onnx_metadata(self._session)
        blob = _frame_to_nchw(frame, self._session, np)
        input_name = self._session.get_inputs()[0].name
        outputs = self._session.run(None, {input_name: blob})
        return decode_yolo_onnx(outputs[0], self._names, self.confidence)


class YoloDetector:
    """Ultralytics ``.pt`` / ``.pth`` weights. The package loads on ``predict``."""

    def __init__(self, path, confidence: float = 0.5):
        self.path = os.fspath(path)
        if not os.path.isfile(self.path):
            raise FileNotFoundError(self.path)
        self.confidence = float(confidence)
        self._model = None

    def predict(self, frame) -> list[Detection]:
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise ImportError(
                "ultralytics is not installed. "
                "pip install -r requirements-detect.txt"
            ) from exc
        if self._model is None:
            self._model = YOLO(self.path)
        results = self._model.predict(source=frame, conf=self.confidence, verbose=False)
        best: dict[str, Detection] = {}
        for result in results:
            names = getattr(result, "names", {}) or {}
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for box in boxes:
                index = _as_int(box.cls)
                label = names.get(index, f"class_{index}")
                if not isinstance(label, str):
                    label = str(label)
                conf = _as_float(box.conf)
                if conf < self.confidence:
                    continue
                previous = best.get(label)
                if previous is None or conf > previous.confidence:
                    best[label] = Detection(label=label, confidence=conf, box=None)
        return list(best.values())


class RoboflowDetector:
    """Hosted Roboflow model id or workflow.

    The API key comes from the ``api_key`` argument or the
    ``ROBOFLOW_API_KEY`` environment variable. It is never hardcoded.
    ``__init__`` does not open a network connection and does not import
    ``inference_sdk``.
    """

    def __init__(
        self,
        model_id=None,
        workflow=None,
        workspace=None,
        api_key=None,
        confidence: float = 0.5,
        api_url=None,
    ):
        self.model_id = model_id
        self.workflow = workflow
        self.workspace = workspace
        self.confidence = float(confidence)
        self.api_url = (
            api_url
            or os.environ.get("ROBOFLOW_API_URL")
            or "https://detect.roboflow.com"
        )
        # Empty string is "not provided" so a blank env entry is not a key.
        if api_key:
            self.api_key = api_key
        else:
            self.api_key = os.environ.get("ROBOFLOW_API_KEY") or None
        if workflow and not workspace:
            raise ValueError(
                "A Roboflow workflow needs workspace= (or workspace_name). "
                "Example: load_model(workflow='detect-signs', workspace='your-workspace')."
            )
        if not model_id and not workflow:
            raise ValueError("Roboflow load needs model_id= or workflow=")
        self._client = None

    def predict(self, frame) -> list[Detection]:
        if not self.api_key:
            raise RuntimeError(
                "Set ROBOFLOW_API_KEY in the environment. "
                "Do not put the key in the script."
            )
        try:
            from inference_sdk import InferenceHTTPClient
        except ImportError as exc:
            raise ImportError(
                "inference-sdk is not installed. "
                "pip install inference-sdk (see requirements-detect.txt)"
            ) from exc
        if self._client is None:
            self._client = InferenceHTTPClient(api_url=self.api_url, api_key=self.api_key)
        client = self._client
        if self.workflow:
            payload = client.run_workflow(
                workspace_name=self.workspace,
                workflow_id=self.workflow,
                images={"image": frame},
            )
        else:
            payload = client.infer(frame, model_id=self.model_id)
        return detections_from_roboflow(payload, self.confidence)


def build_model(
    source=None,
    *,
    model_id=None,
    workflow=None,
    workspace=None,
    confidence: float = 0.5,
    api_key=None,
    api_url=None,
):
    """Pick a detector from a weights path or a Roboflow config.

    Keyword ``model_id`` / ``workflow`` selects Roboflow. A path ending in
    ``.onnx`` selects ONNX. ``.pt`` / ``.pth`` selects Ultralytics YOLO.
    A missing file is ``FileNotFoundError``. A path is never treated as a
    Roboflow id, including strings like ``workspace/project/3``. Pass
    ``model_id=`` for hosted infer.
    """
    model_id, workflow, workspace = _normalize_roboflow_config(
        model_id, workflow, workspace
    )
    if model_id or workflow:
        return RoboflowDetector(
            model_id=model_id,
            workflow=workflow,
            workspace=workspace,
            api_key=api_key,
            confidence=confidence,
            api_url=api_url,
        )
    if source is None:
        raise ValueError(
            "load_model needs a weights path, model_id=, or workflow="
        )
    path = os.fspath(source)
    suffix = os.path.splitext(path)[1].lower()
    if suffix == ".onnx":
        return OnnxDetector(path, confidence=confidence)
    if suffix in (".pt", ".pth"):
        return YoloDetector(path, confidence=confidence)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    raise ValueError(
        f"unsupported model file {path!r}. Use a .onnx or .pt/.pth weights "
        "file, or pass model_id= for a hosted Roboflow model."
    )


def _normalize_roboflow_config(model_id, workflow, workspace):
    """Accept a workflow dict with workspace / workflow_id keys."""
    if isinstance(workflow, dict):
        workspace = (
            workspace
            or workflow.get("workspace")
            or workflow.get("workspace_name")
        )
        workflow = (
            workflow.get("workflow_id")
            or workflow.get("id")
            or workflow.get("workflow")
        )
    if isinstance(model_id, dict):
        workspace = (
            workspace
            or model_id.get("workspace")
            or model_id.get("workspace_name")
        )
        if model_id.get("workflow_id") or model_id.get("workflow"):
            workflow = workflow or (
                model_id.get("workflow_id")
                or model_id.get("workflow")
                or model_id.get("id")
            )
            model_id = model_id.get("model_id") or model_id.get("model")
        else:
            model_id = (
                model_id.get("model_id")
                or model_id.get("model")
                or model_id.get("id")
            )
    return model_id, workflow, workspace


def _label_for_index(names, index: int) -> str:
    if not names:
        return f"class_{index}"
    if isinstance(names, dict):
        if index in names:
            return str(names[index])
        if str(index) in names:
            return str(names[str(index)])
        return f"class_{index}"
    if index < len(names):
        return str(names[index])
    return f"class_{index}"


def _names_from_sidecar(path: str) -> list[str] | None:
    stem, _ext = os.path.splitext(path)
    for candidate in (path + ".names", stem + ".names"):
        if not os.path.isfile(candidate):
            continue
        with open(candidate, encoding="utf-8") as handle:
            names = [line.strip() for line in handle if line.strip()]
        if names:
            return names
    return None


def _names_from_onnx_metadata(session) -> list[str] | dict | None:
    meta = getattr(session, "get_modelmeta", lambda: None)()
    custom = getattr(meta, "custom_metadata_map", None) or {}
    raw = custom.get("names")
    if not raw:
        return None
    text = str(raw).strip()
    if text.startswith("{") or text.startswith("["):
        try:
            import ast

            parsed = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            return None
        if isinstance(parsed, dict):
            return {int(key) if str(key).isdigit() else key: value for key, value in parsed.items()}
        if isinstance(parsed, (list, tuple)):
            return [str(item) for item in parsed]
        return None
    return [part.strip() for part in text.split(",") if part.strip()]


def _frame_to_nchw(frame, session, np):
    """Resize a BGR/RGB frame to the session input and return NCHW float32."""
    height, width = 640, 640
    try:
        shape = session.get_inputs()[0].shape
    except (AttributeError, IndexError):
        shape = None
    if isinstance(shape, (list, tuple)) and len(shape) == 4:
        if isinstance(shape[2], int) and shape[2] > 0:
            height = int(shape[2])
        if isinstance(shape[3], int) and shape[3] > 0:
            width = int(shape[3])
    array = np.asarray(frame)
    if array.ndim == 3 and array.shape[-1] in (1, 3, 4):
        try:
            import cv2

            resized = cv2.resize(array, (width, height))
        except ImportError:
            resized = _resize_nearest(array, width, height, np)
        blob = resized.astype(np.float32)
        if blob.max() > 1.5:
            blob = blob / 255.0
        if blob.shape[-1] == 4:
            blob = blob[..., :3]
        if blob.shape[-1] == 1:
            blob = np.repeat(blob, 3, axis=-1)
        return np.transpose(blob, (2, 0, 1))[None, ...]
    return array


def _resize_nearest(array, width: int, height: int, np):
    source_h, source_w = array.shape[:2]
    y_index = np.linspace(0, source_h - 1, height).astype(int)
    x_index = np.linspace(0, source_w - 1, width).astype(int)
    return array[y_index][:, x_index]


def _collect_predictions(node, found: list) -> None:
    if isinstance(node, dict):
        predictions = node.get("predictions")
        if isinstance(predictions, list):
            found.extend(predictions)
        for key, value in node.items():
            if key == "predictions":
                continue
            _collect_predictions(value, found)
    elif isinstance(node, list):
        for item in node:
            _collect_predictions(item, found)


def _box_from_mapping(item: dict) -> tuple | None:
    if not all(key in item for key in ("x", "y", "width", "height")):
        return None
    try:
        return (
            float(item["x"]),
            float(item["y"]),
            float(item["width"]),
            float(item["height"]),
        )
    except (TypeError, ValueError):
        return None


def _as_float(value) -> float:
    if hasattr(value, "item"):
        return float(value.item())
    return float(value)


def _as_int(value) -> int:
    if hasattr(value, "item"):
        return int(value.item())
    return int(value)
