"""Latency-first YOLO26 live bbox stabilizer for the Rokid product path.

DeepStream/YOLO26 can be an excellent detector feed, but raw detector boxes are
not a stable product overlay contract. This module turns live detector frames
into a small, filtered, smoothed perception layer that skills and Ops preview
can consume without binding the product preview to DeepStream OSD drawing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import time
from typing import Any, Callable

from .event_store import InMemoryEventStore


DEFAULT_CLASS_ALLOWLIST = {
    "person",
    "people",
    "car",
    "truck",
    "bus",
    "motorcycle",
    "bicycle",
    "bike",
    "dog",
    "cat",
    "backpack",
    "bag",
    "handbag",
    "suitcase",
    "laptop",
    "cell phone",
    "phone",
    "bottle",
    "chair",
}


@dataclass(frozen=True, slots=True)
class Yolo26LiveStabilizerSettings:
    enabled: bool = True
    min_confidence: float = 0.35
    instant_confidence: float = 0.72
    iou_threshold: float = 0.45
    match_iou_threshold: float = 0.30
    smoothing_alpha: float = 0.45
    hold_ms: int = 500
    min_hits: int = 2
    max_detections: int = 40
    class_allowlist: set[str] = field(default_factory=lambda: set(DEFAULT_CLASS_ALLOWLIST))
    drop_missing_confidence: bool = True
    drop_unclassified: bool = True


@dataclass(slots=True)
class _StableTrack:
    key: str
    label: str
    bbox: list[float]
    confidence: float
    first_seen_s: float
    last_seen_s: float
    hits: int = 0
    missed: int = 0
    track_id: str | None = None
    object_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


class Yolo26LiveStabilizer:
    def __init__(
        self,
        *,
        events: InMemoryEventStore,
        settings_provider: Callable[[], Yolo26LiveStabilizerSettings] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._events = events
        self._settings_provider = settings_provider or load_yolo26_live_stabilizer_settings
        self._clock = clock or time.monotonic
        self._tracks: dict[str, dict[str, _StableTrack]] = {}

    def stabilize(
        self,
        *,
        session_id: str,
        source: str,
        detections: list[dict[str, Any]],
        frame_id: str | None = None,
        width: int | None = None,
        height: int | None = None,
        sequence: int | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        settings = self._settings_provider()
        now_s = self._clock()
        clean_session_id = str(session_id or "").strip()
        raw_count = len([item for item in detections if isinstance(item, dict)])
        if not settings.enabled:
            return [dict(item) for item in detections if isinstance(item, dict)], {
                "enabled": False,
                "raw_count": raw_count,
                "emitted_count": raw_count,
            }

        candidates: list[dict[str, Any]] = []
        rejected_low_confidence = 0
        rejected_missing_confidence = 0
        rejected_unclassified = 0
        rejected_class = 0
        rejected_bbox = 0
        for item in detections:
            if not isinstance(item, dict):
                continue
            normalized = _normalize_detection(item)
            if not normalized:
                rejected_bbox += 1
                continue
            attrs = normalized.setdefault("attributes", {})
            confidence_missing = attrs.get("confidence_source") == "missing" or not _has_confidence(item)
            if settings.drop_missing_confidence and confidence_missing:
                rejected_missing_confidence += 1
                continue
            if settings.drop_unclassified and _is_unclassified(normalized):
                rejected_unclassified += 1
                continue
            if normalized["confidence"] < settings.min_confidence:
                rejected_low_confidence += 1
                continue
            if settings.class_allowlist and normalized["label"] not in settings.class_allowlist:
                rejected_class += 1
                continue
            candidates.append(normalized)

        selected = _nms_by_label(candidates, iou_threshold=settings.iou_threshold, max_detections=settings.max_detections)
        tracks = self._tracks.setdefault(clean_session_id, {})
        seen_keys: set[str] = set()
        jitter_values: list[float] = []
        output: list[dict[str, Any]] = []
        suppressed_min_hits = 0

        for detection in selected:
            track = self._match_track(tracks=tracks, detection=detection, settings=settings, now_s=now_s)
            seen_keys.add(track.key)
            old_bbox = list(track.bbox)
            smoothed_bbox = _smooth_bbox(old_bbox, detection["bbox"], alpha=settings.smoothing_alpha)
            jitter_values.append(_bbox_center_delta(old_bbox, detection["bbox"]))
            track.bbox = smoothed_bbox
            track.confidence = max(track.confidence * 0.65, detection["confidence"])
            track.last_seen_s = now_s
            track.hits += 1
            track.missed = 0
            track.track_id = detection.get("track_id") or track.track_id
            track.object_id = detection.get("object_id") or track.object_id
            track.attributes = dict(detection.get("attributes") or {})
            if track.hits < settings.min_hits and track.confidence < settings.instant_confidence:
                suppressed_min_hits += 1
                continue
            output.append(_track_to_detection(track, stable_state="tracked", now_s=now_s))

        held_count = 0
        expired: list[str] = []
        hold_s = max(0.0, settings.hold_ms / 1000.0)
        for key, track in list(tracks.items()):
            if key in seen_keys:
                continue
            age_s = now_s - track.last_seen_s
            if age_s <= hold_s and track.hits >= settings.min_hits:
                track.missed += 1
                held_count += 1
                output.append(_track_to_detection(track, stable_state="held", now_s=now_s))
            else:
                expired.append(key)
        for key in expired:
            tracks.pop(key, None)

        metrics = {
            "enabled": True,
            "source": source,
            "frame_id": frame_id,
            "sequence": sequence,
            "width": width,
            "height": height,
            "raw_count": raw_count,
            "candidate_count": len(candidates),
            "after_nms_count": len(selected),
            "emitted_count": len(output),
            "held_count": held_count,
            "track_count": len(tracks),
            "rejected_low_confidence": rejected_low_confidence,
            "rejected_missing_confidence": rejected_missing_confidence,
            "rejected_unclassified": rejected_unclassified,
            "rejected_class": rejected_class,
            "rejected_bbox": rejected_bbox,
            "suppressed_min_hits": suppressed_min_hits,
            "bbox_jitter_px": round(sum(jitter_values) / len(jitter_values), 3) if jitter_values else 0.0,
            "min_confidence": settings.min_confidence,
            "instant_confidence": settings.instant_confidence,
            "hold_ms": settings.hold_ms,
            "min_hits": settings.min_hits,
        }
        if sequence is None or sequence % 30 == 0 or raw_count != len(output):
            self._events.add(
                "adapter.yolo26",
                "stream_frame_stabilized",
                metrics,
                session_id=clean_session_id or None,
            )
        return output, metrics

    def clear_session(self, session_id: str, *, reason: str = "session_closed") -> None:
        clean_session_id = str(session_id or "").strip()
        if not clean_session_id:
            return
        removed = len(self._tracks.pop(clean_session_id, {}))
        if removed:
            self._events.add(
                "adapter.yolo26",
                "stable_tracks_cleared",
                {"reason": reason, "removed_track_count": removed},
                session_id=clean_session_id,
            )

    def _match_track(
        self,
        *,
        tracks: dict[str, _StableTrack],
        detection: dict[str, Any],
        settings: Yolo26LiveStabilizerSettings,
        now_s: float,
    ) -> _StableTrack:
        explicit_key = _explicit_track_key(detection)
        if explicit_key and explicit_key in tracks:
            return tracks[explicit_key]
        best_key = ""
        best_iou = 0.0
        for key, track in tracks.items():
            if track.label != detection["label"]:
                continue
            score = _bbox_iou(track.bbox, detection["bbox"])
            if score > best_iou:
                best_iou = score
                best_key = key
        if best_key and best_iou >= settings.match_iou_threshold:
            return tracks[best_key]
        key = explicit_key or f"{detection['label']}:{len(tracks) + 1}:{int(now_s * 1000)}"
        track = _StableTrack(
            key=key,
            label=detection["label"],
            bbox=list(detection["bbox"]),
            confidence=detection["confidence"],
            first_seen_s=now_s,
            last_seen_s=now_s,
            hits=0,
            track_id=detection.get("track_id"),
            object_id=detection.get("object_id"),
            attributes=dict(detection.get("attributes") or {}),
        )
        tracks[key] = track
        return track


def load_yolo26_live_stabilizer_settings() -> Yolo26LiveStabilizerSettings:
    return Yolo26LiveStabilizerSettings(
        enabled=_env_bool("OPENVISION_YOLO26_STABILIZER_ENABLED", True),
        min_confidence=_env_float("OPENVISION_YOLO26_STABLE_MIN_CONFIDENCE", 0.35),
        instant_confidence=_env_float("OPENVISION_YOLO26_STABLE_INSTANT_CONFIDENCE", 0.72),
        iou_threshold=_env_float("OPENVISION_YOLO26_STABLE_NMS_IOU", 0.45),
        match_iou_threshold=_env_float("OPENVISION_YOLO26_STABLE_MATCH_IOU", 0.30),
        smoothing_alpha=_env_float("OPENVISION_YOLO26_STABLE_SMOOTHING_ALPHA", 0.45),
        hold_ms=_env_int("OPENVISION_YOLO26_STABLE_HOLD_MS", 500),
        min_hits=_env_int("OPENVISION_YOLO26_STABLE_MIN_HITS", 2),
        max_detections=_env_int("OPENVISION_YOLO26_STABLE_MAX_DETECTIONS", 40),
        class_allowlist=_env_string_set("OPENVISION_YOLO26_STABLE_CLASS_ALLOWLIST", DEFAULT_CLASS_ALLOWLIST),
        drop_missing_confidence=_env_bool("OPENVISION_YOLO26_STABLE_DROP_MISSING_CONFIDENCE", True),
        drop_unclassified=_env_bool("OPENVISION_YOLO26_STABLE_DROP_UNCLASSIFIED", True),
    )


def _normalize_detection(item: dict[str, Any]) -> dict[str, Any] | None:
    bbox = _coerce_bbox(item.get("bbox", item.get("bbox_xyxy")))
    if bbox is None:
        return None
    label = str(item.get("label") or item.get("class") or item.get("name") or "object").strip().lower()
    confidence = _to_float(item.get("confidence", item.get("score", 0.0)))
    attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
    return {
        **dict(item),
        "label": label or "object",
        "confidence": max(0.0, min(1.0, confidence)),
        "bbox": bbox,
        "track_id": str(item.get("track_id")) if item.get("track_id") is not None else None,
        "object_id": str(item.get("object_id") or item.get("id")) if item.get("object_id") or item.get("id") else None,
        "attributes": dict(attrs),
    }


def _track_to_detection(track: _StableTrack, *, stable_state: str, now_s: float) -> dict[str, Any]:
    attributes = {
        **track.attributes,
        "detector_family": "yolo26",
        "perception_branch": "yolo26_objects",
        "stabilized": True,
        "stable_state": stable_state,
        "stable_hits": track.hits,
        "stable_missed": track.missed,
        "stable_age_ms": max(0, int((now_s - track.first_seen_s) * 1000)),
        "last_seen_age_ms": max(0, int((now_s - track.last_seen_s) * 1000)),
    }
    return {
        "label": track.label,
        "confidence": max(0.0, min(1.0, track.confidence)),
        "bbox": [round(value, 3) for value in track.bbox],
        "track_id": track.track_id,
        "object_id": track.object_id or track.key,
        "attributes": attributes,
    }


def _nms_by_label(candidates: list[dict[str, Any]], *, iou_threshold: float, max_detections: int) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for label in sorted({item["label"] for item in candidates}):
        group = sorted(
            [item for item in candidates if item["label"] == label],
            key=lambda item: item["confidence"],
            reverse=True,
        )
        while group and len(output) < max_detections:
            current = group.pop(0)
            output.append(current)
            group = [item for item in group if _bbox_iou(current["bbox"], item["bbox"]) < iou_threshold]
    return sorted(output, key=lambda item: item["confidence"], reverse=True)[:max_detections]


def _explicit_track_key(detection: dict[str, Any]) -> str | None:
    if detection.get("track_id"):
        return f"track:{detection['track_id']}"
    if detection.get("object_id"):
        return f"object:{detection['object_id']}"
    return None


def _smooth_bbox(previous: list[float], current: list[float], *, alpha: float) -> list[float]:
    clean_alpha = max(0.0, min(1.0, alpha))
    return [
        (old * (1.0 - clean_alpha)) + (new * clean_alpha)
        for old, new in zip(previous, current, strict=False)
    ]


def _bbox_center_delta(first: list[float], second: list[float]) -> float:
    return ((_center_x(first) - _center_x(second)) ** 2 + (_center_y(first) - _center_y(second)) ** 2) ** 0.5


def _center_x(bbox: list[float]) -> float:
    return (bbox[0] + bbox[2]) / 2.0


def _center_y(bbox: list[float]) -> float:
    return (bbox[1] + bbox[3]) / 2.0


def _bbox_iou(first: list[float], second: list[float]) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    inter = max(0.0, right - left) * max(0.0, bottom - top)
    if inter <= 0.0:
        return 0.0
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = first_area + second_area - inter
    return inter / union if union > 0 else 0.0


def _coerce_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) < 4:
        return None
    values = [_to_float(item) for item in value[:4]]
    x1, y1, x2, y2 = values
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    if right <= left or bottom <= top:
        return None
    return [left, top, right, bottom]


def _is_unclassified(item: dict[str, Any]) -> bool:
    attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
    label = str(item.get("label") or "").lower()
    return attrs.get("classification_status") == "unclassified" or label in {"", "object", "unknown", "obj"}


def _has_confidence(item: dict[str, Any]) -> bool:
    return item.get("confidence") is not None or item.get("score") is not None


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_string_set(name: str, default: set[str]) -> set[str]:
    raw = os.getenv(name)
    if raw is None:
        return set(default)
    if raw.strip() in {"", "*", "all"}:
        return set()
    return {item.strip().lower() for item in raw.split(",") if item.strip()}
