"""Session-scoped perception graph for OpenVision v2."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from typing import Any, Callable

from .contracts import new_id, to_jsonable, utc_now
from .event_store import InMemoryEventStore


ALLOWED_ZONES = {
    "left",
    "left_front",
    "front",
    "right_front",
    "right",
    "near",
    "far",
    "unknown",
}

NEAR_AREA_RATIO = 0.35
NEAR_HEIGHT_RATIO = 0.78
FAR_AREA_RATIO = 0.015
FAR_HEIGHT_RATIO = 0.16


@dataclass(slots=True)
class PerceptionObject:
    object_id: str
    label: str
    confidence: float
    bbox: list[float] | None = None
    track_id: str | None = None
    zone: str | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    age_ms: int = 0
    frame_width: int | None = None
    frame_height: int | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    crop_ref: str | None = None


@dataclass(slots=True)
class PerceptionSnapshot:
    schema_version: str
    snapshot_id: str
    session_id: str
    source: str
    objects: list[PerceptionObject]
    frame_id: str | None = None
    width: int | None = None
    height: int | None = None
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class PerceptionTrack:
    object_id: str
    first_seen_at: str
    last_seen_at: str
    label: str
    seen_count: int = 0


class PerceptionGraph:
    def __init__(
        self,
        *,
        events: InMemoryEventStore,
        now_provider: Callable[[], str] = utc_now,
        history_limit: int = 30,
    ) -> None:
        self._events = events
        self._now_provider = now_provider
        self._history_limit = max(1, history_limit)
        self._latest: dict[str, PerceptionSnapshot] = {}
        self._history: dict[str, list[PerceptionSnapshot]] = {}
        self._tracks: dict[str, dict[str, PerceptionTrack]] = {}

    def update_snapshot(
        self,
        *,
        session_id: str,
        detections: list[dict[str, Any]],
        source: str,
        frame_id: str | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> dict[str, Any]:
        created_at = self._now_provider()
        objects = [
            self._apply_temporal_state(
                session_id=session_id,
                obj=self._coerce_detection(
                    item,
                    timestamp=created_at,
                    frame_width=width,
                    frame_height=height,
                ),
                timestamp=created_at,
            )
            for item in detections
        ]
        snapshot = PerceptionSnapshot(
            schema_version="perception_snapshot.v1",
            snapshot_id=new_id("perception"),
            session_id=session_id,
            source=source,
            objects=objects,
            frame_id=frame_id,
            width=width,
            height=height,
            created_at=created_at,
        )
        self._latest[session_id] = snapshot
        self._append_history(session_id=session_id, snapshot=snapshot)
        self._events.add(
            "perception",
            "snapshot",
            {
                "source": source,
                "objects": len(objects),
                "frame_id": frame_id,
                "history_count": len(self._history.get(session_id, [])),
                "track_count": len(self._tracks.get(session_id, {})),
            },
            session_id=session_id,
        )
        return to_jsonable(snapshot)

    def latest(self, session_id: str) -> dict[str, Any] | None:
        snapshot = self._latest.get(session_id)
        return to_jsonable(snapshot) if snapshot else None

    def list_latest(self) -> list[dict[str, Any]]:
        return [to_jsonable(snapshot) for snapshot in self._latest.values()]

    def recent_snapshots(self, session_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        history = self._history.get(session_id, [])
        clean_limit = max(1, min(limit, self._history_limit))
        return [to_jsonable(snapshot) for snapshot in history[-clean_limit:]]

    def _coerce_detection(
        self,
        item: dict[str, Any],
        *,
        timestamp: str,
        frame_width: int | None,
        frame_height: int | None,
    ) -> PerceptionObject:
        label = str(item.get("label") or item.get("class") or item.get("name") or "object").strip().lower()
        label = label or "object"
        confidence = _clamp(_to_float(item.get("confidence", item.get("score", 0.0))), minimum=0.0, maximum=1.0)
        bbox = _coerce_bbox(item.get("bbox", item.get("bbox_xyxy")))
        attributes = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
        first_seen_at = str(item.get("first_seen_at") or item.get("created_at") or timestamp)
        last_seen_at = str(item.get("last_seen_at") or item.get("updated_at") or timestamp)
        clean_frame_width = max(1, _to_int(frame_width)) if frame_width else None
        clean_frame_height = max(1, _to_int(frame_height)) if frame_height else None
        explicit_zone = _coerce_zone(item.get("zone") or attributes.get("zone"))
        computed_zone = compute_bbox_zone(
            bbox,
            frame_width=clean_frame_width,
            frame_height=clean_frame_height,
        )
        return PerceptionObject(
            object_id=str(item.get("object_id") or item.get("id") or new_id("obj")),
            label=label,
            confidence=confidence,
            bbox=bbox,
            track_id=str(item.get("track_id")) if item.get("track_id") is not None else None,
            zone=explicit_zone or computed_zone,
            first_seen_at=first_seen_at,
            last_seen_at=last_seen_at,
            age_ms=max(0, _to_int(item.get("age_ms"))),
            frame_width=clean_frame_width,
            frame_height=clean_frame_height,
            attributes=attributes,
            crop_ref=str(item.get("crop_ref")) if item.get("crop_ref") else None,
        )

    def _apply_temporal_state(self, *, session_id: str, obj: PerceptionObject, timestamp: str) -> PerceptionObject:
        key = _track_key(obj)
        tracks = self._tracks.setdefault(session_id, {})
        track = tracks.get(key)
        if track is None:
            track = PerceptionTrack(
                object_id=obj.object_id,
                first_seen_at=obj.first_seen_at or timestamp,
                last_seen_at=timestamp,
                label=obj.label,
                seen_count=0,
            )
            tracks[key] = track
        track.seen_count += 1
        track.last_seen_at = timestamp
        track.label = obj.label
        obj.object_id = track.object_id
        obj.first_seen_at = track.first_seen_at
        obj.last_seen_at = timestamp
        obj.age_ms = _age_ms(track.first_seen_at, timestamp)
        return obj

    def _append_history(self, *, session_id: str, snapshot: PerceptionSnapshot) -> None:
        history = self._history.setdefault(session_id, [])
        history.append(snapshot)
        del history[:-self._history_limit]


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _clamp(value: float, *, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def _coerce_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) < 4:
        return None
    return [_to_float(item) for item in value[:4]]


def _coerce_zone(value: Any) -> str | None:
    if value is None:
        return None
    zone = str(value).strip().lower()
    return zone if zone in ALLOWED_ZONES else None


def _track_key(obj: PerceptionObject) -> str:
    if obj.track_id:
        return f"track:{obj.track_id}"
    return f"object:{obj.object_id}"


def compute_bbox_zone(
    bbox: list[float] | None,
    *,
    frame_width: int | None = None,
    frame_height: int | None = None,
) -> str:
    """Compute a coarse wearable-facing zone from a bbox.

    This intentionally stays 2D and cheap. True AR/world coordinates belong in
    a later graph layer once detector/tracker calibration is stable.
    """

    normalized = _normalize_bbox(bbox, frame_width=frame_width, frame_height=frame_height)
    if normalized is None:
        return "unknown"
    x1, y1, x2, y2 = normalized
    box_width = max(0.0, x2 - x1)
    box_height = max(0.0, y2 - y1)
    if box_width <= 0.0 or box_height <= 0.0:
        return "unknown"
    area_ratio = box_width * box_height
    if area_ratio >= NEAR_AREA_RATIO or box_height >= NEAR_HEIGHT_RATIO:
        return "near"
    if area_ratio <= FAR_AREA_RATIO and box_height <= FAR_HEIGHT_RATIO:
        return "far"
    center_x = (x1 + x2) / 2.0
    if center_x < 1.0 / 3.0:
        return "left_front"
    if center_x > 2.0 / 3.0:
        return "right_front"
    return "front"


def _normalize_bbox(
    bbox: list[float] | None,
    *,
    frame_width: int | None,
    frame_height: int | None,
) -> tuple[float, float, float, float] | None:
    if not bbox or len(bbox) < 4:
        return None
    x1, y1, x2, y2 = bbox[:4]
    if not all(_is_finite_number(value) for value in (x1, y1, x2, y2)):
        return None
    left, right = sorted((float(x1), float(x2)))
    top, bottom = sorted((float(y1), float(y2)))
    if right <= left or bottom <= top:
        return None
    if max(abs(left), abs(top), abs(right), abs(bottom)) <= 1.5:
        return (
            _clamp(left, minimum=0.0, maximum=1.0),
            _clamp(top, minimum=0.0, maximum=1.0),
            _clamp(right, minimum=0.0, maximum=1.0),
            _clamp(bottom, minimum=0.0, maximum=1.0),
        )
    if not frame_width or not frame_height:
        return None
    return (
        _clamp(left / frame_width, minimum=0.0, maximum=1.0),
        _clamp(top / frame_height, minimum=0.0, maximum=1.0),
        _clamp(right / frame_width, minimum=0.0, maximum=1.0),
        _clamp(bottom / frame_height, minimum=0.0, maximum=1.0),
    )


def _is_finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _age_ms(first_seen_at: str | None, last_seen_at: str | None) -> int:
    first = _parse_timestamp(first_seen_at)
    last = _parse_timestamp(last_seen_at)
    if not first or not last:
        return 0
    return max(0, int((last - first).total_seconds() * 1000))


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
