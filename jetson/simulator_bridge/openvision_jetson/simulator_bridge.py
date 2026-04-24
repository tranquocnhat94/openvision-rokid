"""iPhone/browser simulator WebRTC bridge."""

from __future__ import annotations

import asyncio
from io import BytesIO
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError
from av.audio.resampler import AudioResampler

from .audio_signal import pcm16_metrics
from .contracts import to_jsonable, utc_now
from .event_store import InMemoryEventStore


@dataclass(slots=True)
class SimulatorPeerStatus:
    session_id: str
    state: str = "new"
    tracks: list[str] = field(default_factory=list)
    audio_chunks: int = 0
    audio_bytes: int = 0
    video_frames: int = 0
    video_width: int | None = None
    video_height: int | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


TrackCallback = Callable[[str, str], None]
AudioPcmCallback = Callable[[str, bytes, dict[str, Any]], Awaitable[None] | None]
VideoFrameCallback = Callable[[str, dict[str, Any]], None]
PreviewFrameCallback = Callable[[str, bytes, dict[str, Any]], None]
CloseCallback = Callable[[str], None]


class SimulatorBridge:
    def __init__(
        self,
        *,
        events: InMemoryEventStore,
        on_track: TrackCallback | None = None,
        on_audio_pcm: AudioPcmCallback | None = None,
        on_video_frame: VideoFrameCallback | None = None,
        on_preview_frame: PreviewFrameCallback | None = None,
        on_close: CloseCallback | None = None,
        preview_every_frames: int = 3,
    ) -> None:
        self._events = events
        self._on_track = on_track
        self._on_audio_pcm = on_audio_pcm
        self._on_video_frame = on_video_frame
        self._on_preview_frame = on_preview_frame
        self._on_close = on_close
        self._preview_every_frames = max(1, preview_every_frames)
        self._peers: dict[str, RTCPeerConnection] = {}
        self._statuses: dict[str, SimulatorPeerStatus] = {}
        self._track_tasks: dict[str, list[asyncio.Task[None]]] = {}
        self._close_notified: set[str] = set()

    def statuses(self) -> list[dict[str, Any]]:
        return [to_jsonable(status) for status in self._statuses.values()]

    async def handle_offer(self, *, session_id: str, sdp: str, offer_type: str) -> dict[str, Any]:
        if offer_type != "offer":
            raise ValueError(f"Unsupported WebRTC description type: {offer_type}")

        await self.close(session_id)
        self._close_notified.discard(session_id)
        pc = RTCPeerConnection()
        status = SimulatorPeerStatus(session_id=session_id)
        self._peers[session_id] = pc
        self._statuses[session_id] = status

        @pc.on("connectionstatechange")
        async def on_connectionstatechange() -> None:
            status.state = pc.connectionState
            status.updated_at = utc_now()
            self._events.add(
                "simulator",
                "webrtc_state",
                {"state": pc.connectionState},
                session_id=session_id,
            )
            if pc.connectionState in {"failed", "closed", "disconnected"}:
                await self.close(session_id)

        @pc.on("track")
        def on_track(track: Any) -> None:
            status.tracks.append(str(track.kind))
            status.updated_at = utc_now()
            if self._on_track:
                self._on_track(session_id, str(track.kind))
            self._events.add(
                "simulator",
                "track",
                {"kind": track.kind},
                session_id=session_id,
            )
            if track.kind == "audio":
                self._track_tasks.setdefault(session_id, []).append(
                    asyncio.create_task(self._consume_audio_track(session_id, track))
                )
            elif track.kind == "video":
                self._track_tasks.setdefault(session_id, []).append(
                    asyncio.create_task(self._consume_video_track(session_id, track))
                )

            @track.on("ended")
            async def on_ended() -> None:
                self._events.add(
                    "simulator",
                    "track_ended",
                    {"kind": track.kind},
                    session_id=session_id,
                )

        await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=offer_type))
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        status.state = pc.connectionState
        status.updated_at = utc_now()
        self._events.add(
            "simulator",
            "webrtc_answer",
            {"tracks": status.tracks},
            session_id=session_id,
        )
        return {
            "type": pc.localDescription.type,
            "sdp": pc.localDescription.sdp,
            "session_id": session_id,
        }

    async def close(self, session_id: str) -> dict[str, Any]:
        tasks = self._track_tasks.pop(session_id, [])
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        pc = self._peers.pop(session_id, None)
        if pc:
            await pc.close()
        status = self._statuses.get(session_id)
        if status:
            status.state = "closed"
            status.updated_at = utc_now()
        if self._on_close and (pc or status) and session_id not in self._close_notified:
            self._close_notified.add(session_id)
            self._on_close(session_id)
        return {"session_id": session_id, "closed": bool(pc)}

    async def _consume_audio_track(self, session_id: str, track: Any) -> None:
        resampler = AudioResampler(format="s16", layout="mono", rate=24000)
        try:
            while True:
                frame = await track.recv()
                for pcm in audio_frame_to_pcm24_mono(frame, resampler):
                    if not pcm:
                        continue
                    metrics = pcm16_metrics(pcm)
                    status = self._statuses.get(session_id)
                    if status:
                        status.audio_chunks += 1
                        status.audio_bytes += len(pcm)
                        status.updated_at = utc_now()
                    if self._on_audio_pcm:
                        maybe_awaitable = self._on_audio_pcm(session_id, pcm, metrics)
                        if maybe_awaitable:
                            await maybe_awaitable
                    if status and status.audio_chunks % 50 == 1:
                        self._events.add(
                            "simulator",
                            "audio_pcm",
                            {
                                "chunks": status.audio_chunks,
                                "bytes": status.audio_bytes,
                                "avg_abs": metrics["avg_abs"],
                                "peak_abs": metrics["peak_abs"],
                                "non_silent_ratio": metrics["non_silent_ratio"],
                            },
                            session_id=session_id,
                        )
        except (asyncio.CancelledError, MediaStreamError):
            return
        except Exception as exc:
            self._events.add(
                "simulator",
                "audio_consumer_error",
                {"error": f"{exc.__class__.__name__}: {exc}"},
                session_id=session_id,
                severity="error",
            )

    async def _consume_video_track(self, session_id: str, track: Any) -> None:
        try:
            while True:
                frame = await track.recv()
                status = self._statuses.get(session_id)
                width = int(getattr(frame, "width", 0) or 0) or None
                height = int(getattr(frame, "height", 0) or 0) or None
                if status:
                    status.video_frames += 1
                    status.video_width = width or status.video_width
                    status.video_height = height or status.video_height
                    status.updated_at = utc_now()
                if self._on_video_frame:
                    self._on_video_frame(
                        session_id,
                        {
                            "width": width,
                            "height": height,
                            "frame_count": status.video_frames if status else 0,
                        },
                    )
                frame_count = status.video_frames if status else 0
                if self._on_preview_frame and frame_count % self._preview_every_frames == 1:
                    try:
                        jpeg = video_frame_to_jpeg(frame)
                    except Exception as exc:
                        self._events.add(
                            "preview",
                            "encode_error",
                            {"error": f"{exc.__class__.__name__}: {exc}"},
                            session_id=session_id,
                            severity="warning",
                        )
                    else:
                        self._on_preview_frame(
                            session_id,
                            jpeg,
                            {
                                "source": "iphone_webrtc",
                                "width": width,
                                "height": height,
                                "frame_count": frame_count,
                            },
                        )
                if status and status.video_frames % 30 == 1:
                    self._events.add(
                        "simulator",
                        "video_frame",
                        {"frames": status.video_frames, "width": width, "height": height},
                        session_id=session_id,
                    )
        except (asyncio.CancelledError, MediaStreamError):
            return
        except Exception as exc:
            self._events.add(
                "simulator",
                "video_consumer_error",
                {"error": f"{exc.__class__.__name__}: {exc}"},
                session_id=session_id,
                severity="error",
            )


def audio_frame_to_pcm24_mono(frame: Any, resampler: AudioResampler) -> list[bytes]:
    out_frames = resampler.resample(frame)
    pcm_chunks: list[bytes] = []
    for out_frame in out_frames:
        if not out_frame.planes:
            continue
        exact_bytes = int(out_frame.samples) * 2
        pcm_chunks.append(bytes(out_frame.planes[0])[:exact_bytes])
    return pcm_chunks


def video_frame_to_jpeg(frame: Any, *, max_width: int = 480, quality: int = 68) -> bytes:
    image = frame.to_image()
    if image.width > max_width:
        height = max(1, round(image.height * (max_width / image.width)))
        image = image.resize((max_width, height))
    output = BytesIO()
    image.save(output, format="JPEG", quality=quality, optimize=True)
    return output.getvalue()
