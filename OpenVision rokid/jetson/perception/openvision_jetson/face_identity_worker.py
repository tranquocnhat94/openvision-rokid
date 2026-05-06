"""OpenVision local face identity stream worker.

This worker is separate from YOLO26 and from the protected Ring/security runtime.
It runs only for approved active OpenVision live-video skills, extracts
face boxes plus local embedding vectors, writes face crops under the OpenVision
runtime directory, and posts typed frames back to the Jetson adapter.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO
import json
import math
import os
from pathlib import Path
import time
from typing import Any, Protocol
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


FORBIDDEN_RUNTIME_MARKERS = ("ring", "security", "surveillance")
DEFAULT_BASE_URL = "http://127.0.0.1:8765"
YUNET_MODEL_NAME = "face_detection_yunet_2023mar.onnx"
SFACE_MODEL_NAME = "face_recognition_sface_2021dec.onnx"
MIN_IDENTITY_FACE_BRIGHTNESS = 35.0
MIN_IDENTITY_FACE_CONTRAST = 10.0
MIN_IDENTITY_FACE_SHARPNESS = 2.0


@dataclass(frozen=True, slots=True)
class FaceIdentityWorkerSettings:
    enabled: bool = False
    jetson_base_url: str = DEFAULT_BASE_URL
    source: str = "openvision_rokid_face_identity"
    backend: str = "opencv_sface"
    detector_model_path: str | None = None
    recognizer_model_path: str | None = None
    min_face_confidence: float = 0.75
    poll_interval_s: float = 0.35
    idle_poll_interval_s: float = 2.0
    request_timeout_s: float = 2.0
    max_fps: float = 2.0
    target_skill_id: str = "target_finder,person_info"
    runtime_dir: Path = field(default_factory=lambda: _default_runtime_dir())
    crop_enabled: bool = True
    crop_quality: int = 88
    detection_target_size: int = 1280
    orientation_fallback_enabled: bool = True
    min_identity_face_side_px: int = 56
    status_path: Path | None = None


class FaceBackend(Protocol):
    def detect_and_embed(self, image: Any) -> list[dict[str, Any]]:
        ...

    def status(self) -> dict[str, Any]:
        ...


class JetsonApiClient:
    def __init__(self, *, base_url: str, timeout_s: float) -> None:
        self._base_url = _normalize_base_url(base_url)
        self._timeout_s = max(0.1, timeout_s)

    def list_active_live(self) -> list[dict[str, Any]]:
        payload = self._get_json("/api/media/commands")
        media_commands = payload.get("media_commands") if isinstance(payload, dict) else {}
        active = media_commands.get("active_live") if isinstance(media_commands, dict) else []
        return [item for item in active if isinstance(item, dict)]

    def list_preview(self) -> list[dict[str, Any]]:
        payload = self._get_json("/api/preview")
        previews = payload.get("preview") if isinstance(payload, dict) else []
        return [item for item in previews if isinstance(item, dict)]

    def fetch_image(self, image_url: str) -> Any:
        from PIL import Image  # type: ignore

        data = self._get_bytes(_absolute_url(self._base_url, image_url))
        image = Image.open(BytesIO(data))
        return image.convert("RGB")

    def post_face_detections(self, *, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_json(f"/api/adapters/face-identity/{session_id}/stream", payload)

    def _get_json(self, path_or_url: str) -> dict[str, Any]:
        data = self._get_bytes(_absolute_url(self._base_url, path_or_url))
        return json.loads(data.decode("utf-8"))

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = Request(
            _absolute_url(self._base_url, path),
            data=data,
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self._timeout_s) as response:  # noqa: S310 - local Jetson API URL from config.
            return json.loads(response.read().decode("utf-8"))

    def _get_bytes(self, url: str) -> bytes:
        with urlopen(url, timeout=self._timeout_s) as response:  # noqa: S310 - local Jetson API URL from config.
            return response.read()


class UnavailableFaceBackend:
    def __init__(self, *, reason: str, message: str) -> None:
        self._reason = reason
        self._message = message

    def detect_and_embed(self, image: Any) -> list[dict[str, Any]]:
        _ = image
        return []

    def status(self) -> dict[str, Any]:
        return {
            "status": "blocked",
            "reason": self._reason,
            "message": self._message,
        }


class OpenCvSFaceBackend:
    def __init__(self, settings: FaceIdentityWorkerSettings) -> None:
        if not settings.detector_model_path:
            raise RuntimeError("OPENVISION_FACE_WORKER_DETECTOR_MODEL is required for opencv_sface backend.")
        if not settings.recognizer_model_path:
            raise RuntimeError("OPENVISION_FACE_WORKER_RECOGNIZER_MODEL is required for opencv_sface backend.")
        for value in (settings.detector_model_path, settings.recognizer_model_path):
            if marker := _forbidden_marker(value):
                raise RuntimeError(f"Model path contains protected marker: {marker}")
        detector_path = Path(settings.detector_model_path).expanduser()
        recognizer_path = Path(settings.recognizer_model_path).expanduser()
        if not detector_path.exists():
            raise RuntimeError(f"Face detector model does not exist: {detector_path}")
        if not recognizer_path.exists():
            raise RuntimeError(f"Face recognizer model does not exist: {recognizer_path}")
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore
        except Exception as exc:  # pragma: no cover - optional Jetson dependency.
            raise RuntimeError("Python packages 'opencv-python-headless' and 'numpy' are required for face identity worker.") from exc
        if not hasattr(cv2, "FaceDetectorYN") or not hasattr(cv2, "FaceRecognizerSF"):
            raise RuntimeError("Installed OpenCV lacks FaceDetectorYN/FaceRecognizerSF support.")
        self._cv2 = cv2
        self._np = np
        self._detector = cv2.FaceDetectorYN.create(str(detector_path), "", (320, 320), settings.min_face_confidence, 0.3, 5000)
        self._recognizer = cv2.FaceRecognizerSF.create(str(recognizer_path), "")
        self._detector_path = str(detector_path)
        self._recognizer_path = str(recognizer_path)
        self._min_face_confidence = settings.min_face_confidence
        self._detection_target_size = max(0, int(settings.detection_target_size or 0))
        self._orientation_fallback_enabled = bool(settings.orientation_fallback_enabled)
        self._min_identity_face_side_px = max(1, int(settings.min_identity_face_side_px or 1))

    def detect_and_embed(self, image: Any) -> list[dict[str, Any]]:
        bgr = self._pil_to_bgr(image)
        original_height, original_width = bgr.shape[:2]
        for orientation in _orientation_candidates(self._orientation_fallback_enabled):
            oriented = _rotate_bgr(self._cv2, bgr, orientation)
            detections = self._detect_oriented_bgr(
                oriented,
                orientation=orientation,
                original_width=original_width,
                original_height=original_height,
            )
            if detections:
                return detections
        return []

    def _detect_oriented_bgr(
        self,
        bgr: Any,
        *,
        orientation: int,
        original_width: int,
        original_height: int,
    ) -> list[dict[str, Any]]:
        detection_bgr, detection_scale = self._resize_for_detection(bgr)
        height, width = detection_bgr.shape[:2]
        self._detector.setInputSize((width, height))
        _, faces = self._detector.detect(detection_bgr)
        if faces is None:
            return []
        output: list[dict[str, Any]] = []
        for index, face in enumerate(faces):
            row = [float(value) for value in face.tolist()]
            if len(row) < 15:
                continue
            x, y, box_w, box_h = row[:4]
            score = float(row[-1])
            if score < self._min_face_confidence:
                continue
            bbox_detection = [max(0.0, x), max(0.0, y), min(float(width), x + box_w), min(float(height), y + box_h)]
            bbox_oriented = _scale_bbox(bbox_detection, 1.0 / detection_scale)
            bbox = _map_bbox_to_original(
                bbox_oriented,
                orientation=orientation,
                original_width=original_width,
                original_height=original_height,
            )
            face_width_px = max(0.0, bbox[2] - bbox[0])
            face_height_px = max(0.0, bbox[3] - bbox[1])
            face_min_side_px = min(face_width_px, face_height_px)
            try:
                aligned = self._recognizer.alignCrop(detection_bgr, face)
                feature = self._recognizer.feature(aligned)
            except Exception:
                continue
            vector = _normalize_vector([float(value) for value in self._np.asarray(feature).reshape(-1).tolist()])
            if not vector:
                continue
            quality_metrics = _face_quality_metrics(self._cv2, aligned)
            quality_reasons = [
                str(reason)
                for reason in quality_metrics.pop("identity_quality_reasons", [])
                if str(reason).strip()
            ]
            if face_min_side_px < self._min_identity_face_side_px:
                quality_reasons = _append_quality_reason(quality_reasons, "too_small_for_identity")
            identity_quality = quality_reasons[0] if quality_reasons else "ok"
            output.append(
                {
                    "label": "person",
                    "confidence": score,
                    "bbox": bbox,
                    "attributes": {
                        "detector": "opencv_yunet_sface",
                        "detector_index": index,
                        "face_bbox": bbox,
                        "face_confidence": score,
                        "identity_vector": vector,
                        "embedding_model": "sface",
                        "primary_region": "face",
                        "detection_orientation_deg": orientation,
                        "detection_scale": round(detection_scale, 4),
                        "face_width_px": round(face_width_px, 2),
                        "face_height_px": round(face_height_px, 2),
                        "face_min_side_px": round(face_min_side_px, 2),
                        **quality_metrics,
                        "identity_quality": identity_quality,
                        "identity_quality_reasons": quality_reasons,
                        "face_quality_flags": quality_reasons,
                        "min_identity_face_side_px": self._min_identity_face_side_px,
                    },
                }
            )
        return output

    def _resize_for_detection(self, bgr: Any) -> tuple[Any, float]:
        height, width = bgr.shape[:2]
        largest_side = max(width, height)
        target_size = self._detection_target_size
        if target_size <= 0 or largest_side >= target_size:
            return bgr, 1.0
        scale = target_size / float(largest_side)
        resized = self._cv2.resize(
            bgr,
            (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
            interpolation=self._cv2.INTER_LINEAR,
        )
        return resized, scale

    def best_embedding_from_image(self, image: Any) -> list[float]:
        detections = self.detect_and_embed(image)
        if not detections:
            return []
        best = max(detections, key=lambda item: float(item.get("confidence") or 0.0))
        attributes = best.get("attributes") if isinstance(best.get("attributes"), dict) else {}
        vector = attributes.get("identity_vector")
        return [float(value) for value in vector] if isinstance(vector, list) else []

    def status(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "backend": "opencv_sface",
            "detector_model_configured": True,
            "detector_model_path": self._detector_path,
            "recognizer_model_configured": True,
            "recognizer_model_path": self._recognizer_path,
            "detection_target_size": self._detection_target_size,
            "orientation_fallback_enabled": self._orientation_fallback_enabled,
            "min_identity_face_side_px": self._min_identity_face_side_px,
        }

    def _pil_to_bgr(self, image: Any) -> Any:
        rgb = self._np.asarray(image.convert("RGB"))
        return self._cv2.cvtColor(rgb, self._cv2.COLOR_RGB2BGR)


class SimpleFaceTracker:
    def __init__(self, *, iou_threshold: float = 0.25, max_age_frames: int = 12) -> None:
        self._iou_threshold = iou_threshold
        self._max_age_frames = max(1, max_age_frames)
        self._next_id = 0
        self._tracks: dict[str, list[dict[str, Any]]] = {}

    def update(self, *, session_id: str, detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tracks = self._tracks.setdefault(session_id, [])
        for track in tracks:
            track["missed"] = int(track.get("missed") or 0) + 1
        output: list[dict[str, Any]] = []
        for detection in detections:
            bbox = detection.get("bbox") if isinstance(detection.get("bbox"), list) else None
            match = self._best_match(tracks=tracks, bbox=bbox)
            if match is None:
                self._next_id += 1
                match = {"track_id": f"f{self._next_id}", "bbox": bbox, "missed": 0}
                tracks.append(match)
            else:
                match["bbox"] = bbox
                match["missed"] = 0
            attributes = detection.get("attributes") if isinstance(detection.get("attributes"), dict) else {}
            output.append(
                {
                    **detection,
                    "track_id": match["track_id"],
                    "attributes": {**attributes, "face_track_id": match["track_id"]},
                }
            )
        self._tracks[session_id] = [track for track in tracks if int(track.get("missed") or 0) <= self._max_age_frames]
        return output

    def prune_sessions(self, active_session_ids: set[str]) -> None:
        self._tracks = {
            session_id: tracks
            for session_id, tracks in self._tracks.items()
            if session_id in active_session_ids
        }

    def _best_match(self, *, tracks: list[dict[str, Any]], bbox: list[float] | None) -> dict[str, Any] | None:
        if not bbox:
            return None
        best_track: dict[str, Any] | None = None
        best_iou = 0.0
        for track in tracks:
            track_bbox = track.get("bbox") if isinstance(track.get("bbox"), list) else None
            iou = _bbox_iou(bbox, track_bbox)
            if iou > best_iou:
                best_iou = iou
                best_track = track
        return best_track if best_iou >= self._iou_threshold else None


class JsonStatusWriter:
    def __init__(self, path: Path) -> None:
        self._path = path

    def write(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp_path.replace(self._path)


class FaceIdentityWorker:
    def __init__(
        self,
        *,
        settings: FaceIdentityWorkerSettings,
        api: JetsonApiClient | None = None,
        backend: FaceBackend | None = None,
        tracker: SimpleFaceTracker | None = None,
        status_writer: JsonStatusWriter | None = None,
        clock: Any = time.monotonic,
    ) -> None:
        self._settings = settings
        self._api = api or JetsonApiClient(base_url=settings.jetson_base_url, timeout_s=settings.request_timeout_s)
        self._backend = backend or build_face_backend(settings)
        self._tracker = tracker or SimpleFaceTracker()
        self._status_writer = status_writer or JsonStatusWriter(_status_path(settings))
        self._clock = clock
        self._last_frame_count: dict[str, int] = {}
        self._last_post_s: dict[str, float] = {}
        self._total_posted_frame_count = 0
        self._total_skipped_frame_count = 0
        self._last_posted_frame: dict[str, Any] | None = None

    def run_forever(self) -> None:
        if not self._settings.enabled:
            self._write_status(status="disabled", message="OPENVISION_FACE_WORKER_ENABLED is not set.")
            return
        while True:
            status: dict[str, Any] = {}
            try:
                status = self.run_once()
            except KeyboardInterrupt:
                self._write_status(status="stopped", message="Worker interrupted.")
                raise
            except Exception as exc:
                self._write_status(status="error", message=f"{exc.__class__.__name__}: {exc}")
            time.sleep(self._sleep_interval_s(status))

    def run_once(self) -> dict[str, Any]:
        if not self._settings.enabled:
            status = self._status_payload(status="disabled", message="OPENVISION_FACE_WORKER_ENABLED is not set.")
            self._status_writer.write(status)
            return status
        backend_status = self._backend.status()
        if backend_status.get("status") != "ready":
            status = self._status_payload(
                status="blocked",
                message=str(backend_status.get("message") or backend_status.get("reason") or "Face backend unavailable."),
                backend_status=backend_status,
            )
            self._status_writer.write(status)
            return status

        active_live = self._target_live_sessions(self._api.list_active_live())
        self._prune_inactive_sessions(active_live)
        posted = 0
        skipped = 0
        errors: list[str] = []
        if not active_live:
            status = self._status_payload(
                status="running",
                message="Face identity worker poll completed.",
                backend_status=backend_status,
                active_live_count=0,
                posted_frame_count=posted,
                skipped_frame_count=skipped,
                errors=errors,
            )
            self._status_writer.write(status)
            return status
        previews = {str(item.get("session_id")): item for item in self._api.list_preview()}
        for live in active_live:
            session_id = str(live.get("session_id") or "")
            preview = previews.get(session_id)
            if not preview or not preview.get("has_frame"):
                skipped += 1
                continue
            frame_count = _to_int(preview.get("frame_count"))
            if frame_count and self._last_frame_count.get(session_id) == frame_count:
                skipped += 1
                continue
            now_s = self._clock()
            last_post = self._last_post_s.get(session_id)
            if last_post is not None and now_s - last_post < 1.0 / max(0.1, self._settings.max_fps):
                skipped += 1
                continue
            try:
                post_result = self._process_preview(session_id=session_id, preview=preview, frame_count=frame_count)
            except Exception as exc:
                errors.append(f"{session_id}:{exc.__class__.__name__}:{exc}")
                continue
            if post_result:
                posted += 1
                self._total_posted_frame_count += 1
                self._last_posted_frame = {
                    "session_id": session_id,
                    "frame_id": post_result.get("posted_frame_id"),
                    "sequence": post_result.get("posted_sequence"),
                    "detection_count": post_result.get("posted_detection_count"),
                    "posted_at": _utc_now(),
                }
                self._last_frame_count[session_id] = frame_count
                self._last_post_s[session_id] = now_s
        self._total_skipped_frame_count += skipped
        status = self._status_payload(
            status="running",
            message="Face identity worker poll completed.",
            backend_status=backend_status,
            active_live_count=len(active_live),
            posted_frame_count=posted,
            skipped_frame_count=skipped,
            errors=errors,
        )
        self._status_writer.write(status)
        return status

    def _process_preview(self, *, session_id: str, preview: dict[str, Any], frame_count: int) -> dict[str, Any] | None:
        image_url = _preview_image_url(preview, frame_count=frame_count)
        if not image_url:
            return None
        image = self._api.fetch_image(image_url)
        detections = self._backend.detect_and_embed(image)
        detections = self._tracker.update(session_id=session_id, detections=detections)
        if self._settings.crop_enabled:
            detections = self._attach_crops(session_id=session_id, image=image, detections=detections)
        payload = {
            "source": self._settings.source,
            "frame_id": str(preview.get("frame_id") or f"preview_{frame_count}"),
            "sequence": frame_count,
            "width": int(image.width),
            "height": int(image.height),
            "metadata": preview.get("metadata") if isinstance(preview.get("metadata"), dict) else {},
            "detections": detections,
        }
        post_result = self._api.post_face_detections(session_id=session_id, payload=payload)
        return {
            **post_result,
            "posted_frame_id": payload["frame_id"],
            "posted_sequence": frame_count,
            "posted_detection_count": len(detections),
        }

    def _attach_crops(self, *, session_id: str, image: Any, detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        crop_dir = self._settings.runtime_dir / "crops" / _safe_segment(session_id)
        crop_dir.mkdir(parents=True, exist_ok=True)
        output: list[dict[str, Any]] = []
        for detection in detections:
            bbox = detection.get("bbox") if isinstance(detection.get("bbox"), list) else None
            track_id = _safe_segment(str(detection.get("track_id") or "face"))
            crop = _crop_image(image, bbox)
            if crop is None:
                output.append(detection)
                continue
            file_name = f"face_{track_id}_latest.jpg"
            crop.save(crop_dir / file_name, format="JPEG", quality=self._settings.crop_quality)
            output.append({**detection, "crop_ref": f"/api/crops/{_safe_segment(session_id)}/{file_name}"})
        return output

    def _target_live_sessions(self, active_live: list[dict[str, Any]]) -> list[dict[str, Any]]:
        target_skill_ids = _target_skill_ids(self._settings.target_skill_id)
        return [item for item in active_live if str(item.get("skill_id") or "") in target_skill_ids][:16]

    def _sleep_interval_s(self, status: dict[str, Any]) -> float:
        if status.get("active_live_count"):
            return max(0.05, float(self._settings.poll_interval_s or 0.35))
        return max(0.1, float(self._settings.idle_poll_interval_s or self._settings.poll_interval_s or 2.0))

    def _prune_inactive_sessions(self, active_live: list[dict[str, Any]]) -> None:
        active_session_ids = {
            str(item.get("session_id") or "")
            for item in active_live
            if str(item.get("session_id") or "").strip()
        }
        self._last_frame_count = {
            session_id: value
            for session_id, value in self._last_frame_count.items()
            if session_id in active_session_ids
        }
        self._last_post_s = {
            session_id: value
            for session_id, value in self._last_post_s.items()
            if session_id in active_session_ids
        }
        prune = getattr(self._tracker, "prune_sessions", None)
        if callable(prune):
            prune(active_session_ids)

    def _status_payload(self, *, status: str, message: str, **extra: Any) -> dict[str, Any]:
        detector = self._settings.detector_model_path or ""
        recognizer = self._settings.recognizer_model_path or ""
        return {
            "schema_version": "openvision.face_identity_worker_status.v1",
            "status": status,
            "enabled": self._settings.enabled,
            "backend": self._settings.backend,
            "source": self._settings.source,
            "jetson_base_url": self._settings.jetson_base_url,
            "target_skill_id": self._settings.target_skill_id,
            "target_skill_ids": sorted(_target_skill_ids(self._settings.target_skill_id)),
            "detector_model_configured": bool(detector),
            "detector_model_exists": bool(detector and Path(detector).expanduser().exists()),
            "recognizer_model_configured": bool(recognizer),
            "recognizer_model_exists": bool(recognizer and Path(recognizer).expanduser().exists()),
            "min_face_confidence": self._settings.min_face_confidence,
            "max_fps": self._settings.max_fps,
            "total_posted_frame_count": self._total_posted_frame_count,
            "total_skipped_frame_count": self._total_skipped_frame_count,
            "last_posted_frame": self._last_posted_frame,
            "ring_safety": "separate_openvision_runtime_only",
            "message": message,
            "updated_at": _utc_now(),
            **extra,
        }

    def _write_status(self, *, status: str, message: str) -> None:
        self._status_writer.write(self._status_payload(status=status, message=message))


def load_face_identity_worker_settings() -> FaceIdentityWorkerSettings:
    runtime_dir = Path(os.getenv("OPENVISION_RUNTIME_DIR") or _default_runtime_dir()).expanduser()
    default_face_dir = runtime_dir / "face"
    return FaceIdentityWorkerSettings(
        enabled=_env_bool("OPENVISION_FACE_WORKER_ENABLED", False),
        jetson_base_url=os.getenv("OPENVISION_FACE_WORKER_JETSON_URL", DEFAULT_BASE_URL),
        source=_clean_source(os.getenv("OPENVISION_FACE_WORKER_SOURCE", "openvision_rokid_face_identity")),
        backend=os.getenv("OPENVISION_FACE_WORKER_BACKEND", "opencv_sface").strip().lower() or "opencv_sface",
        detector_model_path=_clean_path(os.getenv("OPENVISION_FACE_WORKER_DETECTOR_MODEL")) or str(default_face_dir / YUNET_MODEL_NAME),
        recognizer_model_path=_clean_path(os.getenv("OPENVISION_FACE_WORKER_RECOGNIZER_MODEL")) or str(default_face_dir / SFACE_MODEL_NAME),
        min_face_confidence=_env_float("OPENVISION_FACE_WORKER_MIN_FACE_CONFIDENCE", 0.75),
        poll_interval_s=_env_float("OPENVISION_FACE_WORKER_POLL_INTERVAL_S", 0.35),
        idle_poll_interval_s=_env_float("OPENVISION_FACE_WORKER_IDLE_POLL_INTERVAL_S", 2.0),
        request_timeout_s=_env_float("OPENVISION_FACE_WORKER_REQUEST_TIMEOUT_S", 2.0),
        max_fps=_env_float("OPENVISION_FACE_WORKER_MAX_FPS", 2.0),
        target_skill_id=os.getenv("OPENVISION_FACE_WORKER_TARGET_SKILL_ID", "target_finder,person_info"),
        runtime_dir=runtime_dir,
        crop_enabled=_env_bool("OPENVISION_FACE_WORKER_CROP_ENABLED", True),
        crop_quality=_env_int("OPENVISION_FACE_WORKER_CROP_QUALITY", 88),
        detection_target_size=_env_int("OPENVISION_FACE_WORKER_DETECTION_TARGET_SIZE", 1280),
        orientation_fallback_enabled=_env_bool("OPENVISION_FACE_WORKER_ORIENTATION_FALLBACK", True),
        min_identity_face_side_px=_env_int("OPENVISION_FACE_WORKER_MIN_IDENTITY_FACE_SIDE_PX", 56),
        status_path=_clean_status_path(os.getenv("OPENVISION_FACE_WORKER_STATUS_PATH"), runtime_dir),
    )


def build_face_backend(settings: FaceIdentityWorkerSettings) -> FaceBackend:
    if settings.backend == "disabled":
        return UnavailableFaceBackend(reason="backend_disabled", message="Face identity worker backend is disabled.")
    if settings.backend != "opencv_sface":
        return UnavailableFaceBackend(
            reason="unsupported_backend",
            message=f"Unsupported face identity worker backend: {settings.backend}",
        )
    try:
        return OpenCvSFaceBackend(settings)
    except RuntimeError as exc:
        return UnavailableFaceBackend(reason="backend_unavailable", message=str(exc))


def extract_identity_vector_from_image_path(settings: FaceIdentityWorkerSettings, image_path: str | Path) -> list[float]:
    from PIL import Image  # type: ignore

    backend = build_face_backend(settings)
    if backend.status().get("status") != "ready":
        raise RuntimeError(str(backend.status().get("message") or "Face identity backend is not ready."))
    if not isinstance(backend, OpenCvSFaceBackend):
        raise RuntimeError("Configured face identity backend cannot extract enrollment embeddings.")
    image = Image.open(Path(image_path).expanduser()).convert("RGB")
    vector = backend.best_embedding_from_image(image)
    if not vector:
        raise RuntimeError("No face embedding could be extracted from the image.")
    return vector


def _crop_image(image: Any, bbox: list[float] | None) -> Any | None:
    if not bbox or len(bbox) < 4:
        return None
    x1, y1, x2, y2 = [float(value) for value in bbox[:4]]
    if max(x1, y1, x2, y2) <= 1.5:
        x1 *= image.width
        x2 *= image.width
        y1 *= image.height
        y2 *= image.height
    padding_x = max(8, int((x2 - x1) * 0.45))
    padding_y = max(8, int((y2 - y1) * 0.65))
    left = max(0, int(x1) - padding_x)
    top = max(0, int(y1) - padding_y)
    right = min(image.width, int(x2) + padding_x)
    bottom = min(image.height, int(y2) + padding_y)
    if right <= left or bottom <= top:
        return None
    return image.crop((left, top, right, bottom))


def _orientation_candidates(enabled: bool) -> list[int]:
    return [0, 90, -90, 180] if enabled else [0]


def _rotate_bgr(cv2: Any, bgr: Any, orientation: int) -> Any:
    if orientation == 90:
        return cv2.rotate(bgr, cv2.ROTATE_90_CLOCKWISE)
    if orientation == -90:
        return cv2.rotate(bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if orientation == 180:
        return cv2.rotate(bgr, cv2.ROTATE_180)
    return bgr


def _scale_bbox(bbox: list[float], scale: float) -> list[float]:
    return [float(value) * scale for value in bbox[:4]]


def _map_bbox_to_original(
    bbox: list[float],
    *,
    orientation: int,
    original_width: int,
    original_height: int,
) -> list[float]:
    x1, y1, x2, y2 = [float(value) for value in bbox[:4]]
    corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    mapped = [
        _map_point_to_original(
            x,
            y,
            orientation=orientation,
            original_width=original_width,
            original_height=original_height,
        )
        for x, y in corners
    ]
    xs = [point[0] for point in mapped]
    ys = [point[1] for point in mapped]
    return [
        max(0.0, min(float(original_width), min(xs))),
        max(0.0, min(float(original_height), min(ys))),
        max(0.0, min(float(original_width), max(xs))),
        max(0.0, min(float(original_height), max(ys))),
    ]


def _map_point_to_original(
    x: float,
    y: float,
    *,
    orientation: int,
    original_width: int,
    original_height: int,
) -> tuple[float, float]:
    if orientation == 90:
        return y, float(original_height) - x
    if orientation == -90:
        return float(original_width) - y, x
    if orientation == 180:
        return float(original_width) - x, float(original_height) - y
    return x, y


def _bbox_iou(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) < 4 or len(b) < 4:
        return 0.0
    ax1, ay1, ax2, ay2 = [float(value) for value in a[:4]]
    bx1, by1, bx2, by2 = [float(value) for value in b[:4]]
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_area = max(0.0, inter_x2 - inter_x1) * max(0.0, inter_y2 - inter_y1)
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter_area
    return inter_area / union if union > 0 else 0.0


def _normalize_vector(values: list[float]) -> list[float]:
    total = math.sqrt(sum(value * value for value in values if math.isfinite(value)))
    if total <= 0:
        return []
    return [round(value / total, 6) for value in values if math.isfinite(value)]


def _face_quality_metrics(cv2: Any, bgr: Any) -> dict[str, Any]:
    try:
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        brightness = float(gray.mean())
        contrast = float(gray.std())
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    except Exception:
        return {
            "face_quality_status": "unknown",
            "identity_quality_reasons": [],
        }
    reasons: list[str] = []
    if brightness < MIN_IDENTITY_FACE_BRIGHTNESS:
        reasons.append("too_dark_for_identity")
    if contrast < MIN_IDENTITY_FACE_CONTRAST:
        reasons.append("low_contrast_for_identity")
    if sharpness < MIN_IDENTITY_FACE_SHARPNESS:
        reasons.append("too_soft_for_identity")
    return {
        "face_quality_status": "low_quality" if reasons else "ok",
        "face_brightness": round(brightness, 2),
        "face_contrast": round(contrast, 2),
        "face_sharpness": round(sharpness, 2),
        "identity_quality_reasons": reasons,
    }


def _append_quality_reason(reasons: list[str], reason: str) -> list[str]:
    cleaned = str(reason or "").strip()
    if cleaned and cleaned not in reasons:
        return [*reasons, cleaned]
    return reasons


def _status_path(settings: FaceIdentityWorkerSettings) -> Path:
    return settings.status_path or settings.runtime_dir / "status" / "face_identity_worker.json"


def _clean_status_path(value: str | None, runtime_dir: Path) -> Path:
    if value:
        return Path(value).expanduser()
    return runtime_dir / "status" / "face_identity_worker.json"


def _default_runtime_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "runtime"


def _normalize_base_url(value: str) -> str:
    cleaned = value.strip() or DEFAULT_BASE_URL
    return cleaned if cleaned.endswith("/") else f"{cleaned}/"


def _absolute_url(base_url: str, path_or_url: str) -> str:
    if path_or_url.startswith(("http://", "https://")):
        if not _same_origin(base_url, path_or_url):
            raise ValueError("Preview URL must stay on the configured Jetson API origin.")
        return path_or_url
    return urljoin(base_url, path_or_url.lstrip("/"))


def _preview_image_url(preview: dict[str, Any], *, frame_count: int | None) -> str:
    image_url = str(preview.get("image_url") or "")
    if not image_url:
        return str(preview.get("mjpeg_url") or "")
    if not frame_count:
        return image_url
    joiner = "&" if "?" in image_url else "?"
    return f"{image_url}{joiner}frame_count={int(frame_count)}"


def _same_origin(base_url: str, candidate_url: str) -> bool:
    base = urlparse(_normalize_base_url(base_url))
    candidate = urlparse(candidate_url)
    return (
        candidate.scheme in {"http", "https"}
        and candidate.scheme == base.scheme
        and candidate.hostname == base.hostname
        and (candidate.port or _default_port(candidate.scheme)) == (base.port or _default_port(base.scheme))
    )


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def _clean_source(value: str) -> str:
    source = value.strip().lower().replace(" ", "_")
    if _forbidden_marker(source):
        return "openvision_rokid_face_identity"
    return source or "openvision_rokid_face_identity"


def _target_skill_ids(value: str) -> set[str]:
    ids = {item.strip() for item in str(value or "").split(",") if item.strip()}
    return ids or {"target_finder"}


def _clean_path(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    return cleaned or None


def _forbidden_marker(value: str | None) -> str | None:
    if not value:
        return None
    lowered = value.lower()
    for marker in FORBIDDEN_RUNTIME_MARKERS:
        if marker in lowered:
            return marker
    return None


def _safe_segment(value: str) -> str:
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in {"_", "-"})
    return cleaned or "unknown"


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenVision local face identity stream worker")
    parser.add_argument("--once", action="store_true", help="Run one poll cycle and exit.")
    args = parser.parse_args(argv)
    settings = load_face_identity_worker_settings()
    worker = FaceIdentityWorker(settings=settings)
    if args.once:
        print(json.dumps(worker.run_once(), ensure_ascii=False))
        return 0
    worker.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
