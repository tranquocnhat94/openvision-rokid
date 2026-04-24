"""Session-scoped decoded preview frames for Jetson Ops."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from .contracts import to_jsonable, utc_now
from .event_store import InMemoryEventStore


@dataclass(slots=True)
class PreviewFrame:
    session_id: str
    source: str
    image_bytes: bytes
    content_type: str = "image/jpeg"
    width: int | None = None
    height: int | None = None
    frame_count: int = 0
    updated_at: str = field(default_factory=utc_now)


class PreviewStore:
    def __init__(self, *, events: InMemoryEventStore) -> None:
        self._events = events
        self._latest: dict[str, PreviewFrame] = {}
        self._subscribers: dict[str, set[asyncio.Queue[PreviewFrame | None]]] = {}

    def record_frame(
        self,
        *,
        session_id: str,
        source: str,
        image_bytes: bytes,
        width: int | None = None,
        height: int | None = None,
        frame_count: int = 0,
        content_type: str = "image/jpeg",
    ) -> dict[str, Any]:
        frame = PreviewFrame(
            session_id=session_id,
            source=source,
            image_bytes=image_bytes,
            content_type=content_type,
            width=width,
            height=height,
            frame_count=frame_count,
        )
        self._latest[session_id] = frame
        for queue in tuple(self._subscribers.get(session_id, ())):
            self._offer_latest(queue, frame)
        if frame_count <= 1 or frame_count % 30 == 1:
            self._events.add(
                "preview",
                "frame_updated",
                {
                    "source": source,
                    "width": width,
                    "height": height,
                    "frame_count": frame_count,
                    "bytes": len(image_bytes),
                },
                session_id=session_id,
            )
        return self._status(frame)

    def list_statuses(self) -> list[dict[str, Any]]:
        return [self._status(frame) for frame in self._latest.values()]

    def status(self, session_id: str) -> dict[str, Any] | None:
        frame = self._latest.get(session_id)
        return self._status(frame) if frame else None

    def latest_image(self, session_id: str) -> tuple[bytes, str] | None:
        frame = self._latest.get(session_id)
        if not frame:
            return None
        return frame.image_bytes, frame.content_type

    def remove_session(self, session_id: str) -> bool:
        removed = self._latest.pop(session_id, None)
        subscribers = self._subscribers.pop(session_id, set())
        for queue in tuple(subscribers):
            self._offer_latest(queue, None)
        if removed:
            self._events.add("preview", "session_removed", {}, session_id=session_id)
        return removed is not None

    def subscribe(self, session_id: str) -> asyncio.Queue[PreviewFrame | None]:
        queue: asyncio.Queue[PreviewFrame | None] = asyncio.Queue(maxsize=1)
        self._subscribers.setdefault(session_id, set()).add(queue)
        frame = self._latest.get(session_id)
        if frame:
            self._offer_latest(queue, frame)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[PreviewFrame | None]) -> None:
        subscribers = self._subscribers.get(session_id)
        if not subscribers:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(session_id, None)

    def _status(self, frame: PreviewFrame) -> dict[str, Any]:
        payload = to_jsonable(frame)
        payload.pop("image_bytes", None)
        payload["has_frame"] = True
        payload["image_url"] = f"/api/preview/{frame.session_id}/frame.jpg"
        payload["mjpeg_url"] = f"/api/preview/{frame.session_id}/stream.mjpeg"
        return payload

    @staticmethod
    def _offer_latest(queue: asyncio.Queue[PreviewFrame | None], frame: PreviewFrame | None) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(frame)
