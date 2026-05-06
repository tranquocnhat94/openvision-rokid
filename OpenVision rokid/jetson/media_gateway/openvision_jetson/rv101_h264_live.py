"""Live RV101 H.264 sample fanout for Jetson Ops video preview."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from .contracts import to_jsonable, utc_now
from .event_store import InMemoryEventStore
from .rv101_video_metadata import merge_video_metadata, video_metadata_from_header


@dataclass(slots=True)
class Rv101H264LiveSample:
    session_id: str
    header: dict[str, Any]
    payload: bytes
    media_status: dict[str, Any]
    sequence: int
    is_keyframe: bool = False
    is_codec_config: bool = False
    width: int | None = None
    height: int | None = None
    presentation_time_us: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=utc_now)

    def ws_metadata(self) -> dict[str, Any]:
        return {
            "type": "sample",
            "session_id": self.session_id,
            "codec": "video/avc",
            "container": "annexb_h264",
            "sequence": self.sequence,
            "is_keyframe": self.is_keyframe,
            "is_codec_config": self.is_codec_config,
            "presentation_time_us": self.presentation_time_us,
            "width": self.width,
            "height": self.height,
            "payload_bytes": len(self.payload),
            "metadata": to_jsonable(self.metadata),
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class _Rv101H264LiveStatus:
    session_id: str
    state: str = "receiving"
    transport: str = "rv101_tcp"
    codec: str = "video/avc"
    container: str = "annexb_h264"
    sample_count: int = 0
    keyframe_count: int = 0
    codec_config_count: int = 0
    byte_count: int = 0
    last_payload_bytes: int = 0
    width: int | None = None
    height: int | None = None
    sequence: int | None = None
    presentation_time_us: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    subscriber_count: int = 0
    updated_at: str = field(default_factory=utc_now)


class Rv101H264LiveStore:
    """Bounded live fanout of raw RV101 H.264 samples.

    This stays deliberately separate from the JPEG/MJPEG preview decoder:
    AI/perception still consume decoded images, while the Ops Console can
    render the real compressed camera stream without forcing JPEG polling.
    """

    def __init__(self, *, events: InMemoryEventStore, queue_size: int = 8) -> None:
        self._events = events
        self._queue_size = max(1, int(queue_size or 8))
        self._latest: dict[str, Rv101H264LiveSample] = {}
        self._statuses: dict[str, _Rv101H264LiveStatus] = {}
        self._subscribers: dict[str, set[asyncio.Queue[Rv101H264LiveSample | None]]] = {}
        self._drop_count: dict[str, int] = {}

    def publish_sample(
        self,
        *,
        session_id: str,
        header: dict[str, Any],
        payload: bytes,
        media_status: dict[str, Any],
    ) -> dict[str, Any]:
        if not payload:
            return {"published": False, "reason": "empty_payload"}
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return {"published": False, "reason": "missing_session_id"}
        video = media_status.get("video") if isinstance(media_status.get("video"), dict) else {}
        metadata = merge_video_metadata(
            video.get("metadata") if isinstance(video, dict) else {},
            video_metadata_from_header(header),
        )
        status = self._statuses.get(normalized_session_id)
        if status is None:
            status = _Rv101H264LiveStatus(session_id=normalized_session_id)
            self._statuses[normalized_session_id] = status
        is_keyframe = bool(header.get("isKeyframe") or header.get("is_keyframe"))
        is_codec_config = bool(header.get("isCodecConfig") or header.get("is_codec_config"))
        sequence = _to_int(header.get("sequence")) or status.sample_count + 1
        width = _to_int(header.get("width")) or _to_int(video.get("width"))
        height = _to_int(header.get("height")) or _to_int(video.get("height"))
        presentation_time_us = _to_int(header.get("presentationTimeUs")) or _to_int(header.get("presentation_time_us"))
        now = utc_now()
        sample = Rv101H264LiveSample(
            session_id=normalized_session_id,
            header=dict(header),
            payload=payload,
            media_status=dict(media_status),
            sequence=sequence,
            is_keyframe=is_keyframe,
            is_codec_config=is_codec_config,
            width=width,
            height=height,
            presentation_time_us=presentation_time_us,
            metadata=metadata,
            updated_at=now,
        )
        status.state = "receiving"
        status.sample_count += 1
        status.keyframe_count += 1 if is_keyframe else 0
        status.codec_config_count += 1 if is_codec_config else 0
        status.byte_count += len(payload)
        status.last_payload_bytes = len(payload)
        status.width = width or status.width
        status.height = height or status.height
        status.sequence = sequence
        status.presentation_time_us = presentation_time_us
        status.metadata = metadata
        status.updated_at = now
        status.subscriber_count = len(self._subscribers.get(normalized_session_id, ()))
        self._latest[normalized_session_id] = sample
        for queue in tuple(self._subscribers.get(normalized_session_id, ())):
            self._offer_latest(normalized_session_id, queue, sample)
        if is_keyframe or status.sample_count == 1 or status.sample_count % 30 == 1:
            self._events.add(
                "rv101_h264_live",
                "sample_published",
                {
                    "sequence": sequence,
                    "is_keyframe": is_keyframe,
                    "is_codec_config": is_codec_config,
                    "width": status.width,
                    "height": status.height,
                    "payload_bytes": len(payload),
                    "subscriber_count": status.subscriber_count,
                },
                session_id=normalized_session_id,
            )
        return self._status_payload(status)

    def list_statuses(self) -> list[dict[str, Any]]:
        return [self._status_payload(status) for status in self._statuses.values()]

    def status(self, session_id: str) -> dict[str, Any] | None:
        status = self._statuses.get(session_id)
        return self._status_payload(status) if status else None

    def subscribe(self, session_id: str) -> asyncio.Queue[Rv101H264LiveSample | None]:
        queue: asyncio.Queue[Rv101H264LiveSample | None] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.setdefault(session_id, set()).add(queue)
        status = self._statuses.get(session_id)
        if status:
            status.subscriber_count = len(self._subscribers.get(session_id, ()))
        sample = self._latest.get(session_id)
        if sample:
            self._offer_latest(session_id, queue, sample)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[Rv101H264LiveSample | None]) -> None:
        subscribers = self._subscribers.get(session_id)
        if not subscribers:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(session_id, None)
        status = self._statuses.get(session_id)
        if status:
            status.subscriber_count = len(self._subscribers.get(session_id, ()))

    def close_session(self, session_id: str) -> None:
        status = self._statuses.pop(session_id, None)
        self._latest.pop(session_id, None)
        subscribers = self._subscribers.pop(session_id, set())
        for queue in tuple(subscribers):
            self._offer_latest(session_id, queue, None)
        if status:
            self._events.add(
                "rv101_h264_live",
                "session_closed",
                {"sample_count": status.sample_count, "keyframe_count": status.keyframe_count},
                session_id=session_id,
            )

    def close_all(self) -> None:
        for session_id in list(self._statuses):
            self.close_session(session_id)

    def _status_payload(self, status: _Rv101H264LiveStatus) -> dict[str, Any]:
        payload = to_jsonable(status)
        payload["has_h264_live"] = True
        payload["h264_ws_url"] = f"/ws/preview/{status.session_id}/h264"
        payload["drop_count"] = self._drop_count.get(status.session_id, 0)
        return payload

    def _offer_latest(
        self,
        session_id: str,
        queue: asyncio.Queue[Rv101H264LiveSample | None],
        sample: Rv101H264LiveSample | None,
    ) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            else:
                self._drop_count[session_id] = self._drop_count.get(session_id, 0) + 1
        queue.put_nowait(sample)


def _to_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
