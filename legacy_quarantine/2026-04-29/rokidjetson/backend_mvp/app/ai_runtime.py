from __future__ import annotations

import contextlib
import json
import os
import shlex
import subprocess
import time
import ctypes
import itertools
from pathlib import Path
from typing import Any


SCENE_MODES = {
    "people_count",
    "scene_monitor",
    "object_count",
    "traffic_count",
    "visual_assistant",
    "focus_bubble",
    "ar_radar",
    "alert_burst",
}
MODE_INFER_INTERVAL_MS = {
    "scene_monitor": 140,
    "people_count": 140,
    "object_count": 140,
    "traffic_count": 120,
    "visual_assistant": 150,
    "focus_bubble": 110,
    "ar_radar": 180,
    "alert_burst": 240,
}
MODE_TRACK_HOLD_MS = {
    "traffic_count": 320,
    "focus_bubble": 260,
    "visual_assistant": 360,
    "scene_monitor": 420,
    "people_count": 420,
    "object_count": 420,
    "ar_radar": 520,
    "alert_burst": 620,
}
PRIMARY_COUNT_PRIORITY = (
    "person",
    "people",
    "vehicle",
    "car",
    "motorbike",
    "truck",
    "bag",
    "helmet",
)
SCENE_CATEGORY_ALIASES = {
    "motorcycle": "motorbike",
    "tv": "screen",
    "cell_phone": "phone",
    "potted_plant": "plant",
}
SCENE_GROUP_LABELS = {
    "people": "People",
    "vehicles": "Vehicles",
    "carry": "Carry",
    "animals": "Animals",
    "furniture": "Furniture",
    "electronics": "Electronics",
    "food": "Food",
    "sports": "Sports",
    "signs": "Signs",
    "home": "Home",
}
SCENE_GROUP_BY_LABEL = {
    "person": "people",
    "people": "people",
    "bicycle": "vehicles",
    "car": "vehicles",
    "motorbike": "vehicles",
    "bus": "vehicles",
    "train": "vehicles",
    "truck": "vehicles",
    "boat": "vehicles",
    "airplane": "vehicles",
    "backpack": "carry",
    "umbrella": "carry",
    "handbag": "carry",
    "tie": "carry",
    "suitcase": "carry",
    "bag": "carry",
    "bird": "animals",
    "cat": "animals",
    "dog": "animals",
    "horse": "animals",
    "sheep": "animals",
    "cow": "animals",
    "elephant": "animals",
    "bear": "animals",
    "zebra": "animals",
    "giraffe": "animals",
    "chair": "furniture",
    "couch": "furniture",
    "bed": "furniture",
    "dining_table": "furniture",
    "bench": "furniture",
    "tv": "electronics",
    "screen": "electronics",
    "laptop": "electronics",
    "mouse": "electronics",
    "remote": "electronics",
    "keyboard": "electronics",
    "phone": "electronics",
    "microwave": "electronics",
    "oven": "electronics",
    "toaster": "electronics",
    "refrigerator": "electronics",
    "clock": "electronics",
    "banana": "food",
    "apple": "food",
    "sandwich": "food",
    "orange": "food",
    "broccoli": "food",
    "carrot": "food",
    "hot_dog": "food",
    "pizza": "food",
    "donut": "food",
    "cake": "food",
    "frisbee": "sports",
    "skis": "sports",
    "snowboard": "sports",
    "sports_ball": "sports",
    "kite": "sports",
    "baseball_bat": "sports",
    "baseball_glove": "sports",
    "skateboard": "sports",
    "surfboard": "sports",
    "tennis_racket": "sports",
    "traffic_light": "signs",
    "fire_hydrant": "signs",
    "stop_sign": "signs",
    "parking_meter": "signs",
    "toilet": "home",
    "sink": "home",
    "bottle": "home",
    "wine_glass": "home",
    "cup": "home",
    "fork": "home",
    "knife": "home",
    "spoon": "home",
    "bowl": "home",
    "plant": "home",
    "vase": "home",
    "book": "home",
    "scissors": "home",
    "teddy_bear": "home",
    "hair_drier": "home",
    "toothbrush": "home",
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _normalize_label(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "_")
    return SCENE_CATEGORY_ALIASES.get(normalized, normalized)


def _humanize_label(value: str) -> str:
    normalized = value.replace("_", " ").strip()
    if not normalized:
        return "Object"
    return normalized[:1].upper() + normalized[1:]


def _aggregate_counts(detections: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for detection in detections:
        label = _normalize_label(
            str(
                detection.get("label")
                or detection.get("class")
                or detection.get("name")
                or detection.get("category")
                or "object"
            )
        )
        if not label:
            label = "object"
        counts[label] = counts.get(label, 0) + 1
    return counts


def _coerce_detections(raw_detections: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_detections, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in raw_detections:
        if not isinstance(item, dict):
            continue
        label = str(
            item.get("label")
            or item.get("class")
            or item.get("name")
            or item.get("category")
            or "object"
        ).strip()
        detection: dict[str, Any] = {"label": label or "object"}
        confidence = item.get("confidence", item.get("score"))
        if isinstance(confidence, (int, float)):
            detection["confidence"] = round(float(confidence), 4)
        bbox = item.get("bbox") or item.get("box")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            detection["bbox"] = [float(value) for value in bbox]
        normalized.append(detection)
    return normalized


def _pick_summary(counts: dict[str, int]) -> tuple[str, int]:
    for key in PRIMARY_COUNT_PRIORITY:
        if counts.get(key, 0) > 0:
            return key, int(counts[key])
    if not counts:
        return "watching", 0
    key = max(counts.items(), key=lambda item: item[1])[0]
    return key, int(counts[key])


def _counts_inline(counts: dict[str, int]) -> str:
    ordered_keys = [key for key in PRIMARY_COUNT_PRIORITY if counts.get(key, 0) > 0]
    extras = [key for key in counts if key not in ordered_keys]
    ordered = ordered_keys + sorted(extras)
    return " | ".join(f"{_humanize_label(key)} {counts[key]}" for key in ordered[:4])


def _top_counts_inline(counts: dict[str, int], limit: int = 4) -> str:
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return " | ".join(f"{_humanize_label(key)} {value}" for key, value in ordered[:limit])


def _scene_group_counts(counts: dict[str, int]) -> dict[str, int]:
    group_counts: dict[str, int] = {}
    for label, value in counts.items():
        group = SCENE_GROUP_BY_LABEL.get(label)
        if not group or value <= 0:
            continue
        group_counts[group] = group_counts.get(group, 0) + value
    return group_counts


def _scene_group_inline(counts: dict[str, int], limit: int = 3) -> str:
    group_counts = _scene_group_counts(counts)
    ordered = sorted(group_counts.items(), key=lambda item: (-item[1], item[0]))
    return " | ".join(
        f"{SCENE_GROUP_LABELS.get(group, _humanize_label(group))} {value}"
        for group, value in ordered[:limit]
    )


def _top_labels_line(detections: list[dict[str, Any]], limit: int = 5) -> str:
    labels: list[str] = []
    seen: set[str] = set()
    for detection in detections:
        label = str(detection.get("label") or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        labels.append(_humanize_label(label))
        if len(labels) >= limit:
            break
    return "Top " + " | ".join(labels) if labels else ""


def _scene_headline(counts: dict[str, int]) -> str:
    summary_label, primary_value = _pick_summary(counts)
    if primary_value > 0 and summary_label != "watching":
        suffix = "s" if primary_value > 1 else ""
        return f"{primary_value} {_humanize_label(summary_label)}{suffix} in view"
    total_objects = sum(counts.values())
    if total_objects > 0:
        suffix = "s" if total_objects > 1 else ""
        return f"{total_objects} object{suffix} in view"
    return "Watching live scene"


def _default_alerts(counts: dict[str, int]) -> list[dict[str, str]]:
    people_count = counts.get("person", 0) + counts.get("people", 0)
    vehicle_count = (
        counts.get("vehicle", 0)
        + counts.get("car", 0)
        + counts.get("motorbike", 0)
        + counts.get("truck", 0)
    )
    animal_count = sum(value for label, value in counts.items() if SCENE_GROUP_BY_LABEL.get(label) == "animals")
    carry_count = sum(value for label, value in counts.items() if SCENE_GROUP_BY_LABEL.get(label) == "carry")
    if people_count >= 4:
        return [{"code": "crowd_alert", "label": "entrance crowded"}]
    if vehicle_count >= 3:
        return [{"code": "vehicle_dense", "label": "vehicle traffic rising"}]
    if animal_count > 0:
        return [{"code": "animal_seen", "label": "animal detected"}]
    if carry_count >= 2:
        return [{"code": "carry_items", "label": "multiple carried items"}]
    if counts:
        return [{"code": "scene_live", "label": "scene live"}]
    return [{"code": "watching_scene", "label": "watching scene"}]


class ExternalCliSceneMonitor:
    def __init__(
        self,
        command_template: str,
        work_dir: Path,
        timeout_sec: float,
        model_name: str,
        engine_path: str,
        labels_path: str,
    ) -> None:
        self.command_template = command_template
        self.work_dir = work_dir
        self.timeout_sec = timeout_sec
        self.model_name = model_name
        self.engine_path = engine_path
        self.labels_path = labels_path
        self.pipeline_name = f"scene_monitor:{model_name}"
        self.loaded = False
        self.last_warm_ms = 0
        self.warmup_ms = 900
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def warm(self) -> int:
        if self.loaded:
            return 0
        self.loaded = True
        self.last_warm_ms = _now_ms()
        return self.warmup_ms

    def release(self) -> None:
        self.loaded = False

    def infer(self, frame_payload: dict[str, Any]) -> dict[str, Any]:
        self.warm()
        jpeg_bytes = frame_payload.get("jpeg_bytes")
        if not isinstance(jpeg_bytes, (bytes, bytearray)) or not jpeg_bytes:
            raise RuntimeError("jpeg frame unavailable for external scene monitor")
        image_path = self.work_dir / "scene_latest.jpg"
        image_path.write_bytes(jpeg_bytes)

        environment = os.environ.copy()
        if self.engine_path:
            environment["ROKID_YOLO26_ENGINE_PATH"] = self.engine_path
        if self.labels_path:
            environment["ROKID_YOLO26_LABELS_PATH"] = self.labels_path
        environment["ROKID_SCENE_MODEL_NAME"] = self.model_name

        command = self.command_template.format(
            image_path=shlex.quote(str(image_path)),
            image_path_raw=str(image_path),
        )
        started = time.perf_counter()
        completed = subprocess.run(
            command,
            shell=True,
            cwd=self.work_dir,
            env=environment,
            capture_output=True,
            text=True,
            timeout=self.timeout_sec,
            check=False,
        )
        infer_ms = int((time.perf_counter() - started) * 1000)

        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "scene command failed"
            raise RuntimeError(message)

        output = completed.stdout.strip()
        payload = json.loads(output) if output else {}
        detections = _coerce_detections(payload.get("detections"))
        counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else None
        normalized_counts = {
            _normalize_label(str(key)): int(value)
            for key, value in (counts or {}).items()
            if isinstance(value, (int, float))
        }
        if not normalized_counts:
            normalized_counts = _aggregate_counts(detections)

        summary_label, primary_value = _pick_summary(normalized_counts)
        details = payload.get("details") if isinstance(payload.get("details"), list) else []
        details = [str(item).strip() for item in details if str(item).strip()]
        if not details:
            inline = _counts_inline(normalized_counts)
            if inline:
                details.append(inline)
            details.append(f"Runner {self.model_name}")

        alerts = payload.get("alerts") if isinstance(payload.get("alerts"), list) else []
        normalized_alerts = []
        for alert in alerts:
            if isinstance(alert, dict) and str(alert.get("label", "")).strip():
                normalized_alerts.append(
                    {
                        "code": str(alert.get("code") or "scene_alert"),
                        "label": str(alert["label"]).strip(),
                    }
                )
        if not normalized_alerts:
            normalized_alerts = _default_alerts(normalized_counts)

        latency_payload = payload.get("latency")
        latency_payload = latency_payload if isinstance(latency_payload, dict) else {}

        return {
            "headline": str(payload.get("headline") or "Scene monitor active"),
            "summary_label": summary_label,
            "primary_value": primary_value,
            "counts": normalized_counts,
            "details": details,
            "alerts": normalized_alerts,
            "detections": detections,
            "faces": [],
            "infer_ms": int(
                payload.get("inferMs")
                or payload.get("latencyMs")
                or latency_payload.get("inferMs", infer_ms)
            ),
            "decode_ms": int(payload.get("decodeMs") or 0),
            "publish_ms": int(payload.get("publishMs") or 4),
            "source": self.pipeline_name,
        }


class InlineTensorRTEngine:
    def __init__(self, engine_path: str) -> None:
        import numpy as np  # type: ignore
        import tensorrt as trt  # type: ignore
        from cuda import cudart  # type: ignore

        self.np = np
        self.trt = trt
        self.cudart = cudart
        self.engine_path = str(engine_path)
        self.logger = trt.Logger(trt.Logger.ERROR)
        self.runtime = trt.Runtime(self.logger)
        self.engine = self.runtime.deserialize_cuda_engine(Path(self.engine_path).read_bytes())
        if self.engine is None:
            raise RuntimeError(f"failed to deserialize engine: {self.engine_path}")
        self.context = self.engine.create_execution_context()
        if self.context is None:
            raise RuntimeError(f"failed to create execution context: {self.engine_path}")
        self.stream = self._cuda_check(cudart.cudaStreamCreate())
        self.tensor_names = [self.engine.get_tensor_name(i) for i in range(self.engine.num_io_tensors)]
        self.input_names = [name for name in self.tensor_names if self.engine.get_tensor_mode(name) == trt.TensorIOMode.INPUT]
        self.output_names = [name for name in self.tensor_names if self.engine.get_tensor_mode(name) == trt.TensorIOMode.OUTPUT]
        self.buffers: dict[str, dict[str, Any]] = {}
        self._allocate_buffers()

    def _cuda_check(self, call_result: tuple[Any, ...]) -> Any:
        err = call_result[0]
        if err != self.cudart.cudaError_t.cudaSuccess:
            raise RuntimeError(f"cuda runtime error: {err}")
        if len(call_result) == 2:
            return call_result[1]
        return call_result[1:]

    def _profile_max_shape(self, name: str) -> tuple[int, ...]:
        shape = tuple(int(value) for value in self.engine.get_tensor_shape(name))
        if all(value >= 0 for value in shape):
            return shape
        profile = self.engine.get_tensor_profile_shape(name, 0)
        return tuple(int(value) for value in profile[-1])

    def _allocate_host_device(self, size: int, dtype: Any) -> dict[str, Any]:
        np_dtype = self.np.dtype(dtype)
        nbytes = int(size * np_dtype.itemsize)
        host_ptr = self._cuda_check(self.cudart.cudaMallocHost(nbytes))
        pointer_type = ctypes.POINTER(self.np.ctypeslib.as_ctypes_type(np_dtype))
        host = self.np.ctypeslib.as_array(ctypes.cast(host_ptr, pointer_type), (size,))
        device = self._cuda_check(self.cudart.cudaMalloc(nbytes))
        return {"host": host, "device": device, "size": size, "dtype": np_dtype}

    def _allocate_buffers(self) -> None:
        for name in self.tensor_names:
            dtype = self.np.dtype(self.trt.nptype(self.engine.get_tensor_dtype(name)))
            shape = tuple(int(value) for value in self.engine.get_tensor_shape(name))
            if all(value >= 0 for value in shape):
                size = max(1, int(self.trt.volume(shape)))
            else:
                size = max(1, int(self.trt.volume(self._profile_max_shape(name))))
            self.buffers[name] = self._allocate_host_device(size, dtype)

    def _ensure_buffer(self, name: str, size: int) -> None:
        current = self.buffers[name]
        if current["size"] >= size:
            return
        self.free_buffer(current)
        dtype = self.np.dtype(self.trt.nptype(self.engine.get_tensor_dtype(name)))
        self.buffers[name] = self._allocate_host_device(size, dtype)

    def infer(self, feed_dict: dict[str, Any]) -> dict[str, Any]:
        actual_input_sizes: dict[str, int] = {}
        for name, arr in feed_dict.items():
            data = self.np.ascontiguousarray(arr)
            self.context.set_input_shape(name, data.shape)
            flat = data.reshape(-1)
            actual_input_sizes[name] = int(flat.size)
            self._ensure_buffer(name, actual_input_sizes[name])
            self.np.copyto(self.buffers[name]["host"][: flat.size], flat, casting="same_kind")

        actual_output_sizes: dict[str, int] = {}
        for name in self.output_names:
            shape = tuple(int(value) for value in self.context.get_tensor_shape(name))
            size = max(1, int(self.trt.volume(shape)))
            actual_output_sizes[name] = size
            self._ensure_buffer(name, size)

        for name in self.tensor_names:
            self.context.set_tensor_address(name, int(self.buffers[name]["device"]))

        for name in self.input_names:
            buffer = self.buffers[name]
            nbytes = actual_input_sizes[name] * buffer["dtype"].itemsize
            self._cuda_check(
                self.cudart.cudaMemcpyAsync(
                    buffer["device"],
                    buffer["host"].ctypes.data,
                    nbytes,
                    self.cudart.cudaMemcpyKind.cudaMemcpyHostToDevice,
                    self.stream,
                )
            )

        if not self.context.execute_async_v3(stream_handle=self.stream):
            raise RuntimeError(f"TensorRT execution failed: {self.engine_path}")

        for name in self.output_names:
            buffer = self.buffers[name]
            nbytes = actual_output_sizes[name] * buffer["dtype"].itemsize
            self._cuda_check(
                self.cudart.cudaMemcpyAsync(
                    buffer["host"].ctypes.data,
                    buffer["device"],
                    nbytes,
                    self.cudart.cudaMemcpyKind.cudaMemcpyDeviceToHost,
                    self.stream,
                )
            )
        self._cuda_check(self.cudart.cudaStreamSynchronize(self.stream))

        output: dict[str, Any] = {}
        for name in self.output_names:
            buffer = self.buffers[name]
            shape = tuple(int(value) for value in self.context.get_tensor_shape(name))
            size = actual_output_sizes[name]
            output[name] = self.np.array(buffer["host"][:size], copy=True).reshape(shape)
        return output

    def free_buffer(self, buffer: dict[str, Any]) -> None:
        with contextlib.suppress(Exception):
            self._cuda_check(self.cudart.cudaFree(buffer["device"]))
        with contextlib.suppress(Exception):
            self._cuda_check(self.cudart.cudaFreeHost(buffer["host"].ctypes.data))

    def close(self) -> None:
        for buffer in self.buffers.values():
            self.free_buffer(buffer)
        self.buffers = {}
        with contextlib.suppress(Exception):
            self._cuda_check(self.cudart.cudaStreamDestroy(self.stream))


class InlineTensorRTSceneMonitor:
    def __init__(self, engine_path: str, labels_path: str, model_name: str) -> None:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        self.cv2 = cv2
        self.np = np
        self.engine_path = engine_path
        self.labels_path = labels_path
        self.model_name = model_name
        self.pipeline_name = f"scene_monitor:{model_name}"
        self.engine: InlineTensorRTEngine | None = None
        self.loaded = False
        self.warmup_ms = 1200
        self.input_size = (640, 640)
        self.conf_threshold = float(os.getenv("ROKID_SCENE_CONFIDENCE", "0.30"))
        self.iou_threshold = float(os.getenv("ROKID_SCENE_NMS_IOU", "0.45"))
        self.max_det = int(os.getenv("ROKID_SCENE_MAX_DET", "60"))
        whitelist_raw = os.getenv("ROKID_SCENE_LABEL_WHITELIST", "").strip()
        self.allowed_labels = {
            _normalize_label(item)
            for item in whitelist_raw.split(",")
            if item.strip()
        }
        self.labels = [
            line.strip() for line in Path(labels_path).read_text(encoding="utf-8").splitlines() if line.strip()
        ]

    def warm(self) -> int:
        if self.engine is not None:
            self.loaded = True
            return 0
        started = time.perf_counter()
        self.engine = InlineTensorRTEngine(self.engine_path)
        self.loaded = True
        return max(self.warmup_ms, int((time.perf_counter() - started) * 1000))

    def release(self) -> None:
        if self.engine is not None:
            self.engine.close()
        self.engine = None
        self.loaded = False

    def _letterbox(self, image: Any) -> tuple[Any, float, int, int]:
        ih, iw = image.shape[:2]
        target_w, target_h = self.input_size
        scale = min(target_w / iw, target_h / ih)
        new_w = int(round(iw * scale))
        new_h = int(round(ih * scale))
        resized = self.cv2.resize(image, (new_w, new_h), interpolation=self.cv2.INTER_LINEAR)
        canvas = self.np.full((target_h, target_w, 3), 114, dtype=self.np.uint8)
        pad_x = (target_w - new_w) // 2
        pad_y = (target_h - new_h) // 2
        canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = resized
        return canvas, scale, pad_x, pad_y

    def _iou(self, box: Any, boxes: Any) -> Any:
        xx1 = self.np.maximum(box[0], boxes[:, 0])
        yy1 = self.np.maximum(box[1], boxes[:, 1])
        xx2 = self.np.minimum(box[2], boxes[:, 2])
        yy2 = self.np.minimum(box[3], boxes[:, 3])
        inter_w = self.np.maximum(0.0, xx2 - xx1)
        inter_h = self.np.maximum(0.0, yy2 - yy1)
        inter = inter_w * inter_h
        box_area = max(0.0, (box[2] - box[0]) * (box[3] - box[1]))
        boxes_area = self.np.maximum(0.0, boxes[:, 2] - boxes[:, 0]) * self.np.maximum(0.0, boxes[:, 3] - boxes[:, 1])
        return inter / self.np.maximum(box_area + boxes_area - inter, 1e-6)

    def _nms(self, detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_class: dict[int, list[dict[str, Any]]] = {}
        for item in detections:
            by_class.setdefault(int(item["class_id"]), []).append(item)

        kept: list[dict[str, Any]] = []
        for _, items in by_class.items():
            items = sorted(items, key=lambda item: item["confidence"], reverse=True)
            while items:
                best = items.pop(0)
                kept.append(best)
                if not items:
                    continue
                others = self.np.array([entry["bbox"] for entry in items], dtype=self.np.float32)
                ious = self._iou(self.np.array(best["bbox"], dtype=self.np.float32), others)
                items = [entry for entry, iou in zip(items, ious) if float(iou) < self.iou_threshold]
        kept.sort(key=lambda item: item["confidence"], reverse=True)
        return kept[: self.max_det]

    def infer(self, frame_payload: dict[str, Any]) -> dict[str, Any]:
        self.warm()
        assert self.engine is not None

        width = int(frame_payload.get("width") or 0)
        height = int(frame_payload.get("height") or 0)
        bgr_bytes = frame_payload.get("bgr_bytes")
        if width <= 0 or height <= 0 or not isinstance(bgr_bytes, (bytes, bytearray)):
            raise RuntimeError("raw frame unavailable for inline TensorRT scene monitor")
        image = self.np.frombuffer(bgr_bytes, dtype=self.np.uint8).reshape((height, width, 3))
        original_h, original_w = image.shape[:2]
        letterboxed, scale, pad_x, pad_y = self._letterbox(image)
        blob = self.cv2.dnn.blobFromImage(letterboxed, 1.0 / 255.0, self.input_size, swapRB=True).astype(self.np.float32, copy=False)

        started = time.perf_counter()
        raw_output = self.engine.infer({self.engine.input_names[0]: blob})[self.engine.output_names[0]][0]
        infer_ms = int((time.perf_counter() - started) * 1000)

        detections: list[dict[str, Any]] = []
        for row in raw_output:
            x1, y1, x2, y2, score, class_id = [float(value) for value in row[:6]]
            if score < self.conf_threshold:
                continue
            class_index = int(class_id)
            label = self.labels[class_index] if 0 <= class_index < len(self.labels) else f"class_{class_index}"
            normalized_label = _normalize_label(label)
            if self.allowed_labels and normalized_label not in self.allowed_labels:
                continue

            x1 = max(0.0, min(original_w, (x1 - pad_x) / max(scale, 1e-6)))
            y1 = max(0.0, min(original_h, (y1 - pad_y) / max(scale, 1e-6)))
            x2 = max(0.0, min(original_w, (x2 - pad_x) / max(scale, 1e-6)))
            y2 = max(0.0, min(original_h, (y2 - pad_y) / max(scale, 1e-6)))
            if x2 <= x1 or y2 <= y1:
                continue
            detections.append(
                {
                    "class_id": class_index,
                    "label": normalized_label,
                    "confidence": round(score, 4),
                    "bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                }
            )

        detections = self._nms(detections)

        return {
            "headline": "Scene monitor active",
            "summary_label": "watching",
            "primary_value": 0,
            "counts": {},
            "details": [f"TensorRT {self.model_name}"],
            "alerts": [{"code": "scene_live", "label": "scene live"}],
            "detections": [
                {
                    "label": item["label"],
                    "confidence": item["confidence"],
                    "bbox": item["bbox"],
                }
                for item in detections
            ],
            "faces": [],
            "infer_ms": infer_ms,
            "decode_ms": 0,
            "publish_ms": 4,
            "source": self.pipeline_name,
        }


class SceneTrackState(dict):
    pass


class AiRuntimeManager:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.ai_mode = os.getenv("ROKID_AI_MODE", "debug").strip().lower()
        self.idle_unload_ms = int(os.getenv("ROKID_AI_IDLE_UNLOAD_MS", "45000"))
        self.scene_timeout_sec = float(os.getenv("ROKID_SCENE_TIMEOUT_SEC", "4.0"))
        self.scene_adapter = self._create_scene_adapter()
        self.last_scene_use_ms = 0
        self.session_cache: dict[str, dict[str, Any]] = {}
        self.scene_tracks: dict[str, list[SceneTrackState]] = {}
        self.track_sequence = itertools.count(1)
        self.last_error: str | None = None
        self.track_hold_ms = int(os.getenv("ROKID_SCENE_TRACK_HOLD_MS", "450"))
        self.track_match_iou = float(os.getenv("ROKID_SCENE_TRACK_MATCH_IOU", "0.28"))
        self.track_min_hits = int(os.getenv("ROKID_SCENE_TRACK_MIN_HITS", "2"))
        self.instant_track_confidence = float(os.getenv("ROKID_SCENE_TRACK_INSTANT_CONFIDENCE", "0.58"))

    @property
    def requires_frame_bus(self) -> bool:
        return self.scene_adapter is not None

    def requires_frame_bus_for_mode(self, mode: str, *, target_search_active: bool = False) -> bool:
        if self.scene_adapter is None:
            return False
        return target_search_active or _normalize_label(mode) in SCENE_MODES

    def _create_scene_adapter(self) -> ExternalCliSceneMonitor | None:
        if self.ai_mode == "inline_trt_yolo26":
            engine_path = os.getenv("ROKID_YOLO26_ENGINE_PATH", "").strip()
            labels_path = os.getenv("ROKID_YOLO26_LABELS_PATH", "").strip()
            model_name = os.getenv("ROKID_YOLO26_MODEL_NAME", "yolo26_shared").strip() or "yolo26_shared"
            if not engine_path or not labels_path:
                return None
            return InlineTensorRTSceneMonitor(
                engine_path=engine_path,
                labels_path=labels_path,
                model_name=model_name,
            )

        if self.ai_mode != "external_cli":
            return None

        command_template = os.getenv("ROKID_SCENE_EXTERNAL_CMD", "").strip()
        if not command_template:
            return None

        infer_dir = self.root_dir / "runtime" / "ai_frames" / "scene_monitor"
        model_name = os.getenv("ROKID_YOLO26_MODEL_NAME", "yolo26_shared").strip() or "yolo26_shared"
        engine_path = os.getenv("ROKID_YOLO26_ENGINE_PATH", "").strip()
        labels_path = os.getenv("ROKID_YOLO26_LABELS_PATH", "").strip()
        return ExternalCliSceneMonitor(
            command_template=command_template,
            work_dir=infer_dir,
            timeout_sec=self.scene_timeout_sec,
            model_name=model_name,
            engine_path=engine_path,
            labels_path=labels_path,
        )

    def _reap_idle(self, now_ms: int | None = None) -> None:
        if self.scene_adapter is None or not self.scene_adapter.loaded:
            return
        now_ms = now_ms or _now_ms()
        if self.last_scene_use_ms and now_ms - self.last_scene_use_ms >= self.idle_unload_ms:
            self.scene_adapter.release()

    def mode_state(self, mode: str) -> dict[str, Any]:
        self._reap_idle()
        normalized_mode = _normalize_label(mode)
        if normalized_mode in SCENE_MODES and self.scene_adapter is not None:
            warmup_ms = self.scene_adapter.warm()
            self.last_scene_use_ms = _now_ms()
            return {
                "status": "active",
                "loadedPipelines": [self.scene_adapter.pipeline_name],
                "warmupMs": warmup_ms,
            }
        return {
            "status": "active",
            "loadedPipelines": [f"debug_{normalized_mode}"] if normalized_mode else ["debug_unknown"],
            "warmupMs": 50,
        }

    def loaded_pipelines(self, mode: str) -> list[str]:
        self._reap_idle()
        normalized_mode = _normalize_label(mode)
        if normalized_mode in SCENE_MODES and self.scene_adapter is not None and self.scene_adapter.loaded:
            return [self.scene_adapter.pipeline_name]
        return [f"debug_{normalized_mode}"] if normalized_mode else ["debug_unknown"]

    def infer_scene_monitor(
        self,
        session_id: str,
        mode: str,
        frame_seq: int,
        frame_payload: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        self._reap_idle()
        normalized_mode = _normalize_label(mode)
        if normalized_mode not in SCENE_MODES or self.scene_adapter is None or not frame_payload:
            return None

        cached = self.session_cache.get(session_id)
        if cached and cached.get("frameSeq") == frame_seq:
            return cached["result"]
        min_interval_ms = MODE_INFER_INTERVAL_MS.get(normalized_mode, MODE_INFER_INTERVAL_MS["scene_monitor"])
        if cached and _now_ms() - int(cached.get("timestampMs", 0)) < min_interval_ms:
            return cached["result"]

        self.last_scene_use_ms = _now_ms()
        try:
            result = self.scene_adapter.infer(frame_payload)
            result = self._stabilize_scene(session_id, normalized_mode, result, frame_seq)
            self.session_cache[session_id] = {
                "frameSeq": frame_seq,
                "timestampMs": _now_ms(),
                "result": result,
            }
            self.last_error = None
            return result
        except Exception as error:
            self.last_error = str(error)
            return None

    def drop_session(self, session_id: str) -> None:
        self.session_cache.pop(session_id, None)
        self.scene_tracks.pop(session_id, None)

    def health(self) -> dict[str, Any]:
        self._reap_idle()
        return {
            "mode": self.ai_mode,
            "requiresFrameBus": self.requires_frame_bus,
            "sceneMonitor": {
                "enabled": self.scene_adapter is not None,
                "pipeline": self.scene_adapter.pipeline_name if self.scene_adapter is not None else None,
                "loaded": self.scene_adapter.loaded if self.scene_adapter is not None else False,
            },
            "idleUnloadMs": self.idle_unload_ms,
            "lastError": self.last_error,
        }

    def _bbox_iou(self, box_a: list[float], box_b: list[float]) -> float:
        ax1, ay1, ax2, ay2 = box_a
        bx1, by1, bx2, by2 = box_b
        xx1 = max(ax1, bx1)
        yy1 = max(ay1, by1)
        xx2 = min(ax2, bx2)
        yy2 = min(ay2, by2)
        inter_w = max(0.0, xx2 - xx1)
        inter_h = max(0.0, yy2 - yy1)
        inter = inter_w * inter_h
        area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
        area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
        denom = max(area_a + area_b - inter, 1e-6)
        return inter / denom

    def _merge_scene_details(self, counts: dict[str, int], detections: list[dict[str, Any]], source: str) -> list[str]:
        details: list[str] = []
        top_labels = _top_labels_line(detections)
        if top_labels:
            details.append(top_labels)
        group_inline = _scene_group_inline(counts)
        if group_inline:
            details.append(group_inline)
        counts_inline = _top_counts_inline(counts, limit=5)
        if counts_inline:
            details.append(counts_inline)
        details.append(source.replace("scene_monitor:", "YOLO26 "))
        return details[:4]

    def _stabilize_scene(
        self,
        session_id: str,
        mode: str,
        ai_result: dict[str, Any],
        frame_seq: int,
    ) -> dict[str, Any]:
        now_ms = _now_ms()
        track_hold_ms = MODE_TRACK_HOLD_MS.get(mode, self.track_hold_ms)
        raw_detections = []
        for item in ai_result.get("detections", []):
            if not isinstance(item, dict):
                continue
            label = _normalize_label(str(item.get("label") or "object"))
            bbox = item.get("bbox")
            if not isinstance(bbox, list) or len(bbox) != 4:
                continue
            confidence = float(item.get("confidence") or 0.0)
            raw_detections.append(
                {
                    "label": label,
                    "bbox": [float(value) for value in bbox],
                    "confidence": confidence,
                }
            )

        tracks = self.scene_tracks.get(session_id, [])
        matched_track_ids: set[int] = set()

        for detection in sorted(raw_detections, key=lambda item: item["confidence"], reverse=True):
            best_track: SceneTrackState | None = None
            best_iou = 0.0
            for track in tracks:
                if int(track["id"]) in matched_track_ids:
                    continue
                if track["label"] != detection["label"]:
                    continue
                iou = self._bbox_iou(track["bbox"], detection["bbox"])
                if iou >= self.track_match_iou and iou > best_iou:
                    best_iou = iou
                    best_track = track
            if best_track is not None:
                best_track["bbox"] = detection["bbox"]
                best_track["confidence"] = round(best_track["confidence"] * 0.55 + detection["confidence"] * 0.45, 4)
                best_track["last_seen_ms"] = now_ms
                best_track["hits"] += 1
                best_track["frame_seq"] = frame_seq
                matched_track_ids.add(int(best_track["id"]))
            else:
                track: SceneTrackState = SceneTrackState(
                    id=next(self.track_sequence),
                    label=detection["label"],
                    bbox=detection["bbox"],
                    confidence=round(detection["confidence"], 4),
                    first_seen_ms=now_ms,
                    last_seen_ms=now_ms,
                    hits=1,
                    frame_seq=frame_seq,
                )
                tracks.append(track)
                matched_track_ids.add(int(track["id"]))

        alive_tracks: list[SceneTrackState] = []
        for track in tracks:
            if now_ms - int(track["last_seen_ms"]) <= track_hold_ms:
                alive_tracks.append(track)
        self.scene_tracks[session_id] = alive_tracks

        stable_tracks = [
            track
            for track in alive_tracks
            if (
                int(track["hits"]) >= self.track_min_hits
                or float(track["confidence"]) >= self.instant_track_confidence
                or now_ms - int(track["first_seen_ms"]) >= 350
            )
        ]
        if not stable_tracks and alive_tracks:
            stable_tracks = sorted(alive_tracks, key=lambda item: float(item["confidence"]), reverse=True)[:1]

        detections = [
            {
                "label": str(track["label"]),
                "confidence": round(float(track["confidence"]), 4),
                "bbox": [round(float(value), 1) for value in track["bbox"]],
                "trackId": int(track["id"]),
            }
            for track in sorted(stable_tracks, key=lambda item: (item["label"], -float(item["confidence"])))
        ]
        counts = _aggregate_counts(detections)
        summary_label, primary_value = _pick_summary(counts)
        source = str(ai_result.get("source") or "scene_monitor")

        result = dict(ai_result)
        result["counts"] = counts
        result["summary_label"] = summary_label
        result["primary_value"] = primary_value
        result["detections"] = detections
        result["details"] = self._merge_scene_details(counts, detections, source)
        result["alerts"] = _default_alerts(counts)
        result["headline"] = _scene_headline(counts)
        return result
