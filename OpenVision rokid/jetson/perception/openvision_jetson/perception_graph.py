"""Session-scoped perception graph for OpenVision v2."""

from __future__ import annotations

import asyncio
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
DEFAULT_SOURCE_FUSION_TTL_MS = 2500


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
    metadata: dict[str, Any] = field(default_factory=dict)
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
        source_fusion_ttl_ms: int = DEFAULT_SOURCE_FUSION_TTL_MS,
    ) -> None:
        self._events = events
        self._now_provider = now_provider
        self._history_limit = max(1, history_limit)
        self._source_fusion_ttl_ms = max(0, int(source_fusion_ttl_ms or 0))
        self._latest: dict[str, PerceptionSnapshot] = {}
        self._latest_by_source: dict[str, dict[str, PerceptionSnapshot]] = {}
        self._history: dict[str, list[PerceptionSnapshot]] = {}
        self._tracks: dict[str, dict[str, PerceptionTrack]] = {}
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any] | None]]] = {}

    def update_snapshot(
        self,
        *,
        session_id: str,
        detections: list[dict[str, Any]],
        source: str,
        frame_id: str | None = None,
        width: int | None = None,
        height: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        created_at = self._now_provider()
        clean_metadata = dict(metadata or {})
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
            metadata=clean_metadata,
            created_at=created_at,
        )
        self._latest_by_source.setdefault(session_id, {})[source] = snapshot
        self._latest[session_id] = self._fused_latest(session_id=session_id)
        latest_payload = to_jsonable(self._latest[session_id])
        for queue in tuple(self._subscribers.get(session_id, ())):
            self._offer_latest(queue, latest_payload)
        for queue in tuple(self._subscribers.get("*", ())):
            self._offer_latest(queue, latest_payload)
        self._append_history(session_id=session_id, snapshot=snapshot)
        self._events.add(
            "perception",
            "snapshot",
            {
                "source": source,
                "objects": len(objects),
                "frame_id": frame_id,
                "history_count": len(self._history.get(session_id, [])),
                "source_count": len(self._latest_by_source.get(session_id, {})),
                "track_count": len(self._tracks.get(session_id, {})),
                "metadata": clean_metadata,
            },
            session_id=session_id,
        )
        return to_jsonable(snapshot)

    def latest(self, session_id: str) -> dict[str, Any] | None:
        snapshot = self._latest.get(session_id)
        return to_jsonable(snapshot) if snapshot else None

    def clear_sources(
        self,
        *,
        session_id: str,
        sources: set[str] | None = None,
        source_markers: set[str] | None = None,
        reason: str = "source_stopped",
    ) -> dict[str, Any]:
        """Remove stale latest layers without deleting replay history."""

        layers = self._latest_by_source.get(session_id)
        if not layers:
            return {"status": "noop", "cleared_sources": [], "remaining_source_count": 0}
        clean_sources = {str(item or "").strip() for item in (sources or set()) if str(item or "").strip()}
        clean_markers = {str(item or "").strip().lower() for item in (source_markers or set()) if str(item or "").strip()}
        cleared = [
            source
            for source in list(layers)
            if source in clean_sources or any(marker in source.lower() for marker in clean_markers)
        ]
        if not cleared:
            return {"status": "noop", "cleared_sources": [], "remaining_source_count": len(layers)}
        for source in cleared:
            layers.pop(source, None)
        if layers:
            self._latest[session_id] = self._fused_latest(session_id=session_id)
            latest_payload = to_jsonable(self._latest[session_id])
        else:
            self._latest_by_source.pop(session_id, None)
            self._latest.pop(session_id, None)
            latest_payload = None
        self._events.add(
            "perception",
            "sources_cleared",
            {
                "reason": reason,
                "cleared_sources": cleared,
                "remaining_source_count": len(layers),
            },
            session_id=session_id,
        )
        if latest_payload:
            for queue in tuple(self._subscribers.get(session_id, ())):
                self._offer_latest(queue, latest_payload)
            for queue in tuple(self._subscribers.get("*", ())):
                self._offer_latest(queue, latest_payload)
        return {
            "status": "cleared",
            "cleared_sources": cleared,
            "remaining_source_count": len(layers),
        }

    def clear_session(self, session_id: str, *, reason: str = "session_closed") -> dict[str, Any]:
        layers = self._latest_by_source.pop(session_id, {})
        self._latest.pop(session_id, None)
        if layers:
            self._events.add(
                "perception",
                "session_cleared",
                {"reason": reason, "cleared_sources": sorted(layers)},
                session_id=session_id,
            )
        return {"status": "cleared" if layers else "noop", "cleared_sources": sorted(layers)}

    def list_latest(self) -> list[dict[str, Any]]:
        return [to_jsonable(snapshot) for snapshot in self._latest.values()]

    def recent_snapshots(self, session_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        history = self._history.get(session_id, [])
        clean_limit = max(1, min(limit, self._history_limit))
        return [to_jsonable(snapshot) for snapshot in history[-clean_limit:]]

    def subscribe(self, session_id: str | None = None) -> asyncio.Queue[dict[str, Any] | None]:
        key = str(session_id or "*")
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=1)
        self._subscribers.setdefault(key, set()).add(queue)
        if session_id:
            latest = self.latest(session_id)
            if latest:
                self._offer_latest(queue, latest)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any] | None], session_id: str | None = None) -> None:
        key = str(session_id or "*")
        subscribers = self._subscribers.get(key)
        if not subscribers:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(key, None)

    def _fused_latest(self, *, session_id: str) -> PerceptionSnapshot:
        layers = self._latest_by_source.get(session_id, {})
        if len(layers) == 1:
            return next(iter(layers.values()))
        ordered = sorted(layers.values(), key=lambda item: item.created_at)
        freshest = ordered[-1]
        eligible = _fresh_layers_for_fusion(
            ordered,
            freshest=freshest,
            ttl_ms=self._source_fusion_ttl_ms,
        )
        if len(eligible) == 1:
            return eligible[0]
        objects: list[PerceptionObject] = []
        layer_metadata: dict[str, Any] = {}
        for snapshot in eligible:
            layer_metadata[snapshot.source] = {
                "snapshot_id": snapshot.snapshot_id,
                "frame_id": snapshot.frame_id,
                "object_count": len(snapshot.objects),
                "created_at": snapshot.created_at,
                "age_from_freshest_ms": _snapshot_age_delta_ms(snapshot, freshest),
            }
            objects.extend(_objects_for_fusion(snapshot))
        return PerceptionSnapshot(
            schema_version="perception_snapshot.v1",
            snapshot_id=new_id("perception"),
            session_id=session_id,
            source="fused_perception",
            objects=objects,
            frame_id=freshest.frame_id,
            width=freshest.width,
            height=freshest.height,
            metadata={
                **freshest.metadata,
                "fused": True,
                "source_count": len(eligible),
                "available_source_count": len(ordered),
                "source_fusion_ttl_ms": self._source_fusion_ttl_ms,
                "layers": layer_metadata,
            },
            created_at=freshest.created_at,
        )

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

    @staticmethod
    def _offer_latest(queue: asyncio.Queue[dict[str, Any] | None], snapshot: dict[str, Any] | None) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(snapshot)


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


def _objects_for_fusion(snapshot: PerceptionSnapshot) -> list[PerceptionObject]:
    output: list[PerceptionObject] = []
    source = snapshot.source.lower()
    for obj in snapshot.objects:
        attributes = dict(obj.attributes)
        attributes.setdefault("perception_source", snapshot.source)
        label = obj.label
        if source.startswith("face_identity") or attributes.get("detector_family") == "face_identity":
            label = "face"
        output.append(
            PerceptionObject(
                object_id=obj.object_id,
                label=label,
                confidence=obj.confidence,
                bbox=list(obj.bbox) if obj.bbox else None,
                track_id=obj.track_id,
                zone=obj.zone,
                first_seen_at=obj.first_seen_at,
                last_seen_at=obj.last_seen_at,
                age_ms=obj.age_ms,
                frame_width=obj.frame_width,
                frame_height=obj.frame_height,
                attributes=attributes,
                crop_ref=obj.crop_ref,
            )
        )
    return output


def _fresh_layers_for_fusion(
    snapshots: list[PerceptionSnapshot],
    *,
    freshest: PerceptionSnapshot,
    ttl_ms: int,
) -> list[PerceptionSnapshot]:
    if ttl_ms <= 0:
        return list(snapshots)
    eligible = [
        snapshot
        for snapshot in snapshots
        if _snapshot_age_delta_ms(snapshot, freshest) <= ttl_ms
    ]
    return eligible or [freshest]


def _snapshot_age_delta_ms(snapshot: PerceptionSnapshot, freshest: PerceptionSnapshot) -> int:
    snapshot_time = _parse_timestamp(snapshot.created_at)
    freshest_time = _parse_timestamp(freshest.created_at)
    if not snapshot_time or not freshest_time:
        return 0
    return max(0, int((freshest_time - snapshot_time).total_seconds() * 1000))


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
