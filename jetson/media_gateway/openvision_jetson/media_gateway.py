"""Media and audio state model for RV101 and simulator sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import to_jsonable, utc_now
from .event_store import InMemoryEventStore


@dataclass(slots=True)
class VideoStatus:
    state: str = "idle"
    transport: str | None = None
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    track_count: int = 0
    frame_count: int = 0
    byte_count: int = 0
    keyframe_count: int = 0
    last_payload_bytes: int = 0
    updated_at: str | None = None


@dataclass(slots=True)
class AudioStatus:
    state: str = "idle"
    transport: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    source: str | None = None
    chunk_count: int = 0
    strong_chunk_count: int = 0
    strong_chunk_ratio: float = 0.0
    byte_count: int = 0
    last_payload_bytes: int = 0
    rms: float | None = None
    track_count: int = 0
    updated_at: str | None = None


@dataclass(slots=True)
class MediaSessionStatus:
    session_id: str
    video: VideoStatus
    audio: AudioStatus
    updated_at: str


class MediaGateway:
    def __init__(self, *, events: InMemoryEventStore) -> None:
        self._events = events
        self._sessions: dict[str, MediaSessionStatus] = {}

    def statuses(self) -> list[dict[str, Any]]:
        return [to_jsonable(status) for status in self._sessions.values()]

    def status(self, session_id: str) -> dict[str, Any]:
        return to_jsonable(self._ensure(session_id))

    def record_webrtc_track(self, *, session_id: str, kind: str) -> dict[str, Any]:
        status = self._ensure(session_id)
        if kind == "video":
            status.video.state = "receiving"
            status.video.transport = "webrtc"
            status.video.track_count += 1
            status.video.updated_at = utc_now()
        elif kind == "audio":
            status.audio.state = "receiving"
            status.audio.transport = "webrtc"
            status.audio.track_count += 1
            status.audio.updated_at = utc_now()
        status.updated_at = utc_now()
        self._events.add("media", "webrtc_track", {"kind": kind}, session_id=session_id)
        return to_jsonable(status)

    def close_session(self, session_id: str) -> dict[str, Any] | None:
        status = self._sessions.get(session_id)
        if not status:
            return None
        now = utc_now()
        if status.video.state == "receiving":
            status.video.state = "closed"
            status.video.updated_at = now
        if status.audio.state == "receiving":
            status.audio.state = "closed"
            status.audio.updated_at = now
        status.updated_at = now
        self._events.add("media", "session_closed", {}, session_id=session_id)
        return to_jsonable(status)

    def record_video_heartbeat(
        self,
        *,
        session_id: str,
        transport: str,
        codec: str,
        width: int | None = None,
        height: int | None = None,
        fps: float | None = None,
    ) -> dict[str, Any]:
        status = self._ensure(session_id)
        status.video.state = "receiving"
        status.video.transport = transport
        status.video.codec = codec
        status.video.width = width
        status.video.height = height
        status.video.fps = fps
        status.video.updated_at = utc_now()
        status.updated_at = status.video.updated_at
        self._events.add(
            "media",
            "video_heartbeat",
            {"transport": transport, "codec": codec, "width": width, "height": height, "fps": fps},
            session_id=session_id,
        )
        return to_jsonable(status)

    def record_video_sample(
        self,
        *,
        session_id: str,
        transport: str,
        codec: str,
        payload_bytes: int,
        is_keyframe: bool = False,
        width: int | None = None,
        height: int | None = None,
        fps: float | None = None,
    ) -> dict[str, Any]:
        status = self._ensure(session_id)
        status.video.state = "receiving"
        status.video.transport = transport
        status.video.codec = codec
        status.video.width = width or status.video.width
        status.video.height = height or status.video.height
        status.video.fps = fps or status.video.fps
        status.video.frame_count += 1
        status.video.byte_count += max(0, payload_bytes)
        status.video.last_payload_bytes = max(0, payload_bytes)
        if is_keyframe:
            status.video.keyframe_count += 1
        status.video.updated_at = utc_now()
        status.updated_at = status.video.updated_at
        if is_keyframe or status.video.frame_count % 30 == 1:
            self._events.add(
                "media",
                "video_sample",
                {
                    "transport": transport,
                    "codec": codec,
                    "payload_bytes": payload_bytes,
                    "is_keyframe": is_keyframe,
                    "frame_count": status.video.frame_count,
                },
                session_id=session_id,
            )
        return to_jsonable(status)

    def record_audio_metrics(
        self,
        *,
        session_id: str,
        transport: str,
        sample_rate: int,
        channels: int,
        chunk_count: int,
        strong_chunk_count: int,
        rms: float | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        status = self._ensure(session_id)
        status.audio.state = "receiving"
        status.audio.transport = transport
        status.audio.sample_rate = sample_rate
        status.audio.channels = channels
        status.audio.source = source
        status.audio.chunk_count += max(0, chunk_count)
        status.audio.strong_chunk_count += max(0, strong_chunk_count)
        status.audio.strong_chunk_ratio = (
            status.audio.strong_chunk_count / status.audio.chunk_count
            if status.audio.chunk_count
            else 0.0
        )
        status.audio.rms = rms
        status.audio.updated_at = utc_now()
        status.updated_at = status.audio.updated_at
        self._events.add(
            "media",
            "audio_metrics",
            {
                "transport": transport,
                "sample_rate": sample_rate,
                "channels": channels,
                "chunk_count": chunk_count,
                "strong_chunk_count": strong_chunk_count,
                "strong_chunk_ratio": status.audio.strong_chunk_ratio,
                "source": source,
            },
            session_id=session_id,
        )
        return to_jsonable(status)

    def record_audio_sample(
        self,
        *,
        session_id: str,
        transport: str,
        sample_rate: int,
        channels: int,
        payload_bytes: int,
        strong: bool,
        rms: float | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        status = self._ensure(session_id)
        status.audio.state = "receiving"
        status.audio.transport = transport
        status.audio.sample_rate = sample_rate
        status.audio.channels = channels
        status.audio.source = source
        status.audio.chunk_count += 1
        if strong:
            status.audio.strong_chunk_count += 1
        status.audio.strong_chunk_ratio = (
            status.audio.strong_chunk_count / status.audio.chunk_count
            if status.audio.chunk_count
            else 0.0
        )
        status.audio.byte_count += max(0, payload_bytes)
        status.audio.last_payload_bytes = max(0, payload_bytes)
        status.audio.rms = rms
        status.audio.updated_at = utc_now()
        status.updated_at = status.audio.updated_at
        if status.audio.chunk_count % 50 == 1:
            self._events.add(
                "media",
                "audio_sample",
                {
                    "transport": transport,
                    "sample_rate": sample_rate,
                    "channels": channels,
                    "payload_bytes": payload_bytes,
                    "strong_chunk_ratio": status.audio.strong_chunk_ratio,
                    "source": source,
                },
                session_id=session_id,
            )
        return to_jsonable(status)

    def _ensure(self, session_id: str) -> MediaSessionStatus:
        status = self._sessions.get(session_id)
        if status:
            return status
        status = MediaSessionStatus(
            session_id=session_id,
            video=VideoStatus(),
            audio=AudioStatus(),
            updated_at=utc_now(),
        )
        self._sessions[session_id] = status
        return status
