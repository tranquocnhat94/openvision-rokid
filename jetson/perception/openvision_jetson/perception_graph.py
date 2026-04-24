"""Session-scoped perception graph for OpenVision v2."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import new_id, to_jsonable, utc_now
from .event_store import InMemoryEventStore


@dataclass(slots=True)
class PerceptionObject:
    object_id: str
    label: str
    confidence: float
    bbox: list[float] | None = None
    track_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    crop_ref: str | None = None


@dataclass(slots=True)
class PerceptionSnapshot:
    snapshot_id: str
    session_id: str
    source: str
    objects: list[PerceptionObject]
    frame_id: str | None = None
    width: int | None = None
    height: int | None = None
    created_at: str = field(default_factory=utc_now)


class PerceptionGraph:
    def __init__(self, *, events: InMemoryEventStore) -> None:
        self._events = events
        self._latest: dict[str, PerceptionSnapshot] = {}

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
        objects = [self._coerce_detection(item) for item in detections]
        snapshot = PerceptionSnapshot(
            snapshot_id=new_id("perception"),
            session_id=session_id,
            source=source,
            objects=objects,
            frame_id=frame_id,
            width=width,
            height=height,
        )
        self._latest[session_id] = snapshot
        self._events.add(
            "perception",
            "snapshot",
            {"source": source, "objects": len(objects), "frame_id": frame_id},
            session_id=session_id,
        )
        return to_jsonable(snapshot)

    def latest(self, session_id: str) -> dict[str, Any] | None:
        snapshot = self._latest.get(session_id)
        return to_jsonable(snapshot) if snapshot else None

    def list_latest(self) -> list[dict[str, Any]]:
        return [to_jsonable(snapshot) for snapshot in self._latest.values()]

    def _coerce_detection(self, item: dict[str, Any]) -> PerceptionObject:
        label = str(item.get("label") or item.get("class") or item.get("name") or "object").strip().lower()
        confidence = _to_float(item.get("confidence", item.get("score", 0.0)))
        bbox = item.get("bbox")
        return PerceptionObject(
            object_id=str(item.get("object_id") or item.get("id") or new_id("obj")),
            label=label,
            confidence=confidence,
            bbox=[_to_float(value) for value in bbox] if isinstance(bbox, list) else None,
            track_id=str(item.get("track_id")) if item.get("track_id") is not None else None,
            attributes=item.get("attributes") if isinstance(item.get("attributes"), dict) else {},
            crop_ref=str(item.get("crop_ref")) if item.get("crop_ref") else None,
        )


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0

