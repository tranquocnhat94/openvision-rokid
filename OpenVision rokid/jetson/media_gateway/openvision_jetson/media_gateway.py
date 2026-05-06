"""Media and audio state model for RV101 and simulator sessions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import time
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
    estimated_fps: float | None = None
    first_frame_at: str | None = None
    last_frame_at: str | None = None
    last_frame_age_ms: int | None = None
    last_heartbeat_at: str | None = None
    last_heartbeat_age_ms: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
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
    avg_abs: float | None = None
    peak_abs: int | None = None
    non_silent_ratio: float | None = None
    max_avg_abs: float | None = None
    max_peak_abs: int | None = None
    max_non_silent_ratio: float | None = None
    byte_count: int = 0
    last_payload_bytes: int = 0
    rms: float | None = None
    track_count: int = 0
    gate_state: str = "idle"
    gate_decision_count: int = 0
    gate_open_count: int = 0
    gate_close_count: int = 0
    gate_forwarded_chunk_count: int = 0
    gate_buffered_chunks: int = 0
    last_gate_transition: str | None = None
    last_gate_at: str | None = None
    updated_at: str | None = None


@dataclass(slots=True)
class MediaSessionStatus:
    session_id: str
    video: VideoStatus
    audio: AudioStatus
    updated_at: str


@dataclass(slots=True)
class _VideoTiming:
    first_frame_monotonic_s: float | None = None
    last_frame_monotonic_s: float | None = None
    last_heartbeat_monotonic_s: float | None = None


class MediaGateway:
    def __init__(self, *, events: InMemoryEventStore, clock: Callable[[], float] | None = None) -> None:
        self._events = events
        self._clock = clock or time.monotonic
        self._sessions: dict[str, MediaSessionStatus] = {}
        self._video_timing: dict[str, _VideoTiming] = {}

    def statuses(self) -> list[dict[str, Any]]:
        return [self._status_payload(status) for status in self._sessions.values()]

    def status(self, session_id: str) -> dict[str, Any]:
        return self._status_payload(self._ensure(session_id))

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
        return self._status_payload(status)

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
        return self._status_payload(status)

    def stop_video_stream(self, *, session_id: str, reason: str) -> dict[str, Any] | None:
        status = self._sessions.get(session_id)
        if not status:
            return None
        if status.video.state != "receiving":
            return self._status_payload(status)
        now = utc_now()
        status.video.state = "idle"
        status.video.updated_at = now
        status.updated_at = now
        self._events.add(
            "media",
            "video_stream_stopped",
            {"reason": reason, "transport": status.video.transport, "frame_count": status.video.frame_count},
            session_id=session_id,
        )
        return self._status_payload(status)

    def stop_audio_stream(self, *, session_id: str, reason: str) -> dict[str, Any] | None:
        status = self._sessions.get(session_id)
        if not status:
            return None
        if status.audio.state != "receiving":
            return self._status_payload(status)
        now = utc_now()
        status.audio.state = "closed"
        status.audio.updated_at = now
        status.updated_at = now
        self._events.add(
            "media",
            "audio_stream_closed",
            {"reason": reason, "transport": status.audio.transport, "chunk_count": status.audio.chunk_count},
            session_id=session_id,
        )
        return self._status_payload(status)

    def record_video_heartbeat(
        self,
        *,
        session_id: str,
        transport: str,
        codec: str,
        width: int | None = None,
        height: int | None = None,
        fps: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        status = self._ensure(session_id)
        video = self._ensure_video_window(
            status=status,
            transport=transport,
            codec=codec,
            reason="heartbeat",
        )
        video.state = "receiving"
        video.transport = transport
        video.codec = codec
        video.width = width
        video.height = height
        video.fps = fps
        if metadata:
            video.metadata = {**video.metadata, **metadata}
        video.updated_at = utc_now()
        video.last_heartbeat_at = video.updated_at
        self._ensure_video_timing(session_id).last_heartbeat_monotonic_s = self._clock()
        status.updated_at = video.updated_at
        self._events.add(
            "media",
            "video_heartbeat",
            {
                "transport": transport,
                "codec": codec,
                "width": width,
                "height": height,
                "fps": fps,
                "metadata": video.metadata,
            },
            session_id=session_id,
        )
        return self._status_payload(status)

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
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        status = self._ensure(session_id)
        video = self._ensure_video_window(
            status=status,
            transport=transport,
            codec=codec,
            reason="sample",
        )
        video.state = "receiving"
        video.transport = transport
        video.codec = codec
        video.width = width or video.width
        video.height = height or video.height
        if fps is not None:
            video.fps = fps
        if metadata:
            video.metadata = {**video.metadata, **metadata}
        video.frame_count += 1
        video.byte_count += max(0, payload_bytes)
        video.last_payload_bytes = max(0, payload_bytes)
        if is_keyframe:
            video.keyframe_count += 1
        now = utc_now()
        video.updated_at = now
        video.first_frame_at = video.first_frame_at or now
        video.last_frame_at = now
        self._record_video_timing(session_id=session_id, video=video)
        status.updated_at = video.updated_at
        if is_keyframe or video.frame_count % 30 == 1:
            self._events.add(
                "media",
                "video_sample",
                {
                    "transport": transport,
                    "codec": codec,
                    "payload_bytes": payload_bytes,
                    "is_keyframe": is_keyframe,
                    "frame_count": video.frame_count,
                    "estimated_fps": video.estimated_fps,
                    "width": video.width,
                    "height": video.height,
                    "metadata": video.metadata,
                },
                session_id=session_id,
            )
        return self._status_payload(status)

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
        avg_abs: float | None = None,
        peak_abs: int | None = None,
        non_silent_ratio: float | None = None,
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
        self._record_audio_signal(
            status.audio,
            avg_abs=avg_abs if avg_abs is not None else rms,
            peak_abs=peak_abs,
            non_silent_ratio=non_silent_ratio,
        )
        status.audio.rms = status.audio.avg_abs if status.audio.avg_abs is not None else rms
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
                "avg_abs": status.audio.avg_abs,
                "peak_abs": status.audio.peak_abs,
                "non_silent_ratio": status.audio.non_silent_ratio,
                "source": source,
            },
            session_id=session_id,
        )
        return self._status_payload(status)

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
        avg_abs: float | None = None,
        peak_abs: int | None = None,
        non_silent_ratio: float | None = None,
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
        self._record_audio_signal(
            status.audio,
            avg_abs=avg_abs if avg_abs is not None else rms,
            peak_abs=peak_abs,
            non_silent_ratio=non_silent_ratio,
        )
        status.audio.rms = status.audio.avg_abs if status.audio.avg_abs is not None else rms
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
                    "avg_abs": status.audio.avg_abs,
                    "peak_abs": status.audio.peak_abs,
                    "non_silent_ratio": status.audio.non_silent_ratio,
                    "source": source,
                },
                session_id=session_id,
            )
        return self._status_payload(status)

    def record_audio_gate_decision(
        self,
        *,
        session_id: str,
        source: str,
        state: str,
        transition: str | None,
        strong: bool,
        forwarded_chunks: int,
        buffered_chunks: int,
        avg_abs: float | None = None,
        peak_abs: int | None = None,
        non_silent_ratio: float | None = None,
        mode: str | None = None,
    ) -> dict[str, Any]:
        status = self._ensure(session_id)
        status.audio.state = "receiving"
        status.audio.source = source or status.audio.source
        status.audio.gate_state = state
        status.audio.gate_decision_count += 1
        status.audio.gate_forwarded_chunk_count += max(0, forwarded_chunks)
        status.audio.gate_buffered_chunks = max(0, buffered_chunks)
        if transition == "opened":
            status.audio.gate_open_count += 1
        elif transition == "closed":
            status.audio.gate_close_count += 1
        if transition:
            status.audio.last_gate_transition = transition
            status.audio.last_gate_at = utc_now()
        self._record_audio_signal(
            status.audio,
            avg_abs=avg_abs,
            peak_abs=peak_abs,
            non_silent_ratio=non_silent_ratio,
        )
        status.audio.updated_at = utc_now()
        status.updated_at = status.audio.updated_at
        if transition or status.audio.gate_decision_count % 50 == 1:
            self._events.add(
                "media",
                "audio_gate_decision",
                {
                    "source": source,
                    "mode": mode,
                    "state": state,
                    "transition": transition,
                    "strong": strong,
                    "forwarded_chunks": forwarded_chunks,
                    "buffered_chunks": buffered_chunks,
                    "gate_open_count": status.audio.gate_open_count,
                    "gate_close_count": status.audio.gate_close_count,
                    "avg_abs": status.audio.avg_abs,
                    "peak_abs": status.audio.peak_abs,
                    "non_silent_ratio": status.audio.non_silent_ratio,
                },
                session_id=session_id,
            )
        return self._status_payload(status)

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

    def _ensure_video_timing(self, session_id: str) -> _VideoTiming:
        timing = self._video_timing.get(session_id)
        if timing:
            return timing
        timing = _VideoTiming()
        self._video_timing[session_id] = timing
        return timing

    def _ensure_video_window(
        self,
        *,
        status: MediaSessionStatus,
        transport: str,
        codec: str,
        reason: str,
    ) -> VideoStatus:
        video = status.video
        should_reset = video.state != "receiving"
        if not should_reset and video.transport and video.transport != transport:
            should_reset = True
        if not should_reset and video.codec and video.codec != codec:
            should_reset = True
        if not should_reset:
            return video
        previous = {
            "state": video.state,
            "transport": video.transport,
            "codec": video.codec,
            "frame_count": video.frame_count,
            "byte_count": video.byte_count,
            "estimated_fps": video.estimated_fps,
        }
        track_count = video.track_count
        status.video = VideoStatus(track_count=track_count)
        self._video_timing[status.session_id] = _VideoTiming()
        self._events.add(
            "media",
            "video_window_started",
            {"reason": reason, "transport": transport, "codec": codec, "previous": previous},
            session_id=status.session_id,
        )
        return status.video

    def _record_video_timing(self, *, session_id: str, video: VideoStatus) -> None:
        now = self._clock()
        timing = self._ensure_video_timing(session_id)
        if timing.first_frame_monotonic_s is None:
            timing.first_frame_monotonic_s = now
        timing.last_frame_monotonic_s = now
        elapsed_s = now - timing.first_frame_monotonic_s
        if elapsed_s > 0 and video.frame_count > 1:
            video.estimated_fps = round((video.frame_count - 1) / elapsed_s, 2)
        video.last_frame_age_ms = 0

    def _refresh_video_liveness(self, session_id: str, video: VideoStatus) -> None:
        timing = self._video_timing.get(session_id)
        if not timing:
            return
        now = self._clock()
        if timing.last_frame_monotonic_s is not None:
            video.last_frame_age_ms = max(0, int((now - timing.last_frame_monotonic_s) * 1000))
        if timing.last_heartbeat_monotonic_s is not None:
            video.last_heartbeat_age_ms = max(0, int((now - timing.last_heartbeat_monotonic_s) * 1000))

    def _status_payload(self, status: MediaSessionStatus) -> dict[str, Any]:
        self._refresh_video_liveness(status.session_id, status.video)
        return to_jsonable(status)

    def _record_audio_signal(
        self,
        audio: AudioStatus,
        *,
        avg_abs: float | None,
        peak_abs: int | None,
        non_silent_ratio: float | None,
    ) -> None:
        if avg_abs is not None:
            audio.avg_abs = float(max(0.0, avg_abs))
            audio.max_avg_abs = max(audio.max_avg_abs or 0.0, audio.avg_abs)
        if peak_abs is not None:
            audio.peak_abs = max(0, int(peak_abs))
            audio.max_peak_abs = max(audio.max_peak_abs or 0, audio.peak_abs)
        if non_silent_ratio is not None:
            audio.non_silent_ratio = min(1.0, max(0.0, float(non_silent_ratio)))
            audio.max_non_silent_ratio = max(audio.max_non_silent_ratio or 0.0, audio.non_silent_ratio)
