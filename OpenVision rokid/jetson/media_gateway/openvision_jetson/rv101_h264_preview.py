"""Optional RV101 H.264 live-video preview decoder."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import BytesIO
import os
import time
from typing import Any, Callable, Protocol

from .event_store import InMemoryEventStore
from .preview_store import PreviewStore
from .rv101_video_metadata import merge_video_metadata, video_metadata_from_header


class H264FrameDecoder(Protocol):
    def decode(self, payload: bytes) -> list[Any]:
        ...

    def close(self) -> None:
        ...


PreviewFrameRecorder = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class Rv101H264PreviewSettings:
    enabled: bool = False
    every_n_frames: int = 1
    min_interval_ms: int = 66
    max_width: int = 720
    jpeg_quality: int = 82
    queue_size: int = 4
    decode_every_sample: bool = True


@dataclass(frozen=True, slots=True)
class _QueuedPreviewSample:
    session_id: str
    header: dict[str, Any]
    payload: bytes
    media_status: dict[str, Any]


@dataclass(slots=True)
class _SessionPreviewDecoder:
    decoder: H264FrameDecoder | None = None
    queue: asyncio.Queue[_QueuedPreviewSample | None] | None = None
    worker: asyncio.Task[None] | None = None
    closed: bool = False
    has_key_or_config_sample: bool = False
    decoded_frame_count: int = 0
    preview_frame_count: int = 0
    last_preview_frame_count: int = 0
    last_preview_monotonic_s: float | None = None
    last_enqueued_frame_count: int = 0
    last_enqueued_monotonic_s: float | None = None
    enqueued_sample_count: int = 0
    processed_sample_count: int = 0
    throttled_sample_count: int = 0
    queue_drop_count: int = 0
    queue_resync_count: int = 0
    error_count: int = 0
    last_error: str | None = None
    needs_keyframe_after_gap: bool = True


@dataclass(frozen=True, slots=True)
class _PreparedPreviewFrame:
    session_id: str
    image_bytes: bytes
    width: int | None
    height: int | None
    frame_count: int
    metadata: dict[str, Any]


class Rv101H264PreviewDecoder:
    """Decode a throttled JPEG preview stream from RV101 tcp_h264 samples."""

    def __init__(
        self,
        *,
        preview: PreviewStore,
        events: InMemoryEventStore,
        settings_provider: Callable[[], Rv101H264PreviewSettings] = None,
        decoder_factory: Callable[[], H264FrameDecoder] | None = None,
        preview_frame_recorder: PreviewFrameRecorder | None = None,
        clock: Callable[[], float] | None = None,
        start_workers: bool = True,
    ) -> None:
        self._preview = preview
        self._events = events
        self._settings_provider = settings_provider or load_rv101_h264_preview_settings
        self._decoder_factory = decoder_factory or PyAvH264FrameDecoder
        self._preview_frame_recorder = preview_frame_recorder
        self._clock = clock or time.monotonic
        self._start_workers = start_workers
        self._sessions: dict[str, _SessionPreviewDecoder] = {}
        self._decoded_frame_count = 0
        self._preview_frame_count = 0
        self._decoder_init_error: str | None = None
        self._decoder_init_error_logged = False

    def status(self) -> dict[str, Any]:
        settings = self._settings_provider()
        if not settings.enabled:
            status = "disabled"
        elif self._decoder_init_error:
            status = "unavailable"
        else:
            status = "ready"
        return {
            "enabled": settings.enabled,
            "status": status,
            "backend": "pyav",
            "session_count": len(self._sessions),
            "decoded_frame_count": self._decoded_frame_count,
            "preview_frame_count": self._preview_frame_count,
            "every_n_frames": settings.every_n_frames,
            "min_interval_ms": settings.min_interval_ms,
            "max_publish_fps": _max_publish_fps(settings.min_interval_ms),
            "max_width": settings.max_width,
            "jpeg_quality": settings.jpeg_quality,
            "queue_size": settings.queue_size,
            "decode_every_sample": settings.decode_every_sample,
            "queued_sample_count": sum(state.enqueued_sample_count for state in self._sessions.values()),
            "processed_sample_count": sum(state.processed_sample_count for state in self._sessions.values()),
            "pending_sample_count": sum(
                state.queue.qsize() for state in self._sessions.values() if state.queue is not None
            ),
            "throttled_sample_count": sum(state.throttled_sample_count for state in self._sessions.values()),
            "queue_drop_count": sum(state.queue_drop_count for state in self._sessions.values()),
            "queue_resync_count": sum(state.queue_resync_count for state in self._sessions.values()),
            "worker_count": sum(
                1
                for state in self._sessions.values()
                if state.worker is not None and not state.worker.done()
            ),
            "last_error": self._decoder_init_error,
        }

    def enqueue_sample(
        self,
        *,
        session_id: str,
        header: dict[str, Any],
        payload: bytes,
        media_status: dict[str, Any],
    ) -> dict[str, Any]:
        """Queue a compressed sample for background preview decoding.

        This method is intentionally cheap enough for the RV101 TCP ingest loop:
        it only applies pre-decode throttling and a bounded queue offer.
        """

        settings = self._settings_provider()
        if not settings.enabled or not payload:
            return {"queued": False, "reason": "disabled" if not settings.enabled else "empty_payload"}
        state = self._ensure_session(session_id, settings=settings)
        frame_count = _frame_count_for(header=header, media_status=media_status)
        is_keyframe = bool(header.get("isKeyframe") or header.get("is_keyframe"))
        if not self._should_attempt_decode(
            state=state,
            frame_count=frame_count,
            is_keyframe=is_keyframe,
            settings=settings,
        ):
            self._record_throttled_sample(state=state, session_id=session_id, frame_count=frame_count)
            return {"queued": False, "reason": "throttled"}

        queue = self._ensure_queue(session_id=session_id, state=state, settings=settings)
        sample = _QueuedPreviewSample(
            session_id=session_id,
            header=dict(header),
            payload=payload,
            media_status=_copy_media_status(media_status),
        )
        try:
            queue.put_nowait(sample)
        except asyncio.QueueFull:
            if is_keyframe:
                dropped_pending_count = _drain_preview_queue(queue)
                try:
                    queue.put_nowait(sample)
                except asyncio.QueueFull:
                    pass
                else:
                    state.enqueued_sample_count += 1
                    state.queue_resync_count += 1
                    state.has_key_or_config_sample = True
                    state.needs_keyframe_after_gap = False
                    state.last_enqueued_frame_count = frame_count
                    state.last_enqueued_monotonic_s = self._clock()
                    self._events.add(
                        "rv101_h264_preview",
                        "queue_resynced_for_keyframe",
                        {
                            "frame_count": frame_count,
                            "queue_size": settings.queue_size,
                            "dropped_pending_count": dropped_pending_count,
                            "queue_resync_count": state.queue_resync_count,
                        },
                        session_id=session_id,
                    )
                    return {"queued": True, "reason": "queued_keyframe_resynced", "pending_sample_count": queue.qsize()}
            state.queue_drop_count += 1
            if not is_keyframe:
                state.needs_keyframe_after_gap = True
            self._events.add(
                "rv101_h264_preview",
                "queue_full_drop",
                {
                    "frame_count": frame_count,
                    "queue_size": settings.queue_size,
                    "queue_drop_count": state.queue_drop_count,
                    "needs_keyframe_after_gap": state.needs_keyframe_after_gap,
                    "backpressure_policy": "wait_for_next_keyframe",
                },
                session_id=session_id,
                severity="info",
            )
            return {"queued": False, "reason": "backpressure_delta_drop"}
        state.enqueued_sample_count += 1
        if is_keyframe:
            state.has_key_or_config_sample = True
            state.needs_keyframe_after_gap = False
        state.last_enqueued_frame_count = frame_count
        state.last_enqueued_monotonic_s = self._clock()
        return {"queued": True, "reason": "queued", "pending_sample_count": queue.qsize()}

    def handle_sample(
        self,
        *,
        session_id: str,
        header: dict[str, Any],
        payload: bytes,
        media_status: dict[str, Any],
    ) -> None:
        settings = self._settings_provider()
        if not settings.enabled or not payload:
            return
        state = self._ensure_session(session_id, settings=settings)
        frame_count = _frame_count_for(header=header, media_status=media_status)
        is_keyframe = bool(header.get("isKeyframe") or header.get("is_keyframe"))
        if not self._should_attempt_decode(
            state=state,
            frame_count=frame_count,
            is_keyframe=is_keyframe,
            settings=settings,
        ):
            self._record_throttled_sample(state=state, session_id=session_id, frame_count=frame_count)
            return
        state.enqueued_sample_count += 1
        if is_keyframe:
            state.has_key_or_config_sample = True
            state.needs_keyframe_after_gap = False
        state.last_enqueued_frame_count = frame_count
        state.last_enqueued_monotonic_s = self._clock()
        for frame in self._process_sample(state=state, session_id=session_id, header=header, payload=payload, media_status=media_status):
            self._record_prepared_preview(frame)

    async def _worker_loop(self, *, session_id: str, state: _SessionPreviewDecoder) -> None:
        queue = state.queue
        if queue is None:
            return
        try:
            while True:
                sample = await queue.get()
                try:
                    if sample is None:
                        return
                    frames = await asyncio.to_thread(
                        self._process_sample,
                        state=state,
                        session_id=sample.session_id,
                        header=sample.header,
                        payload=sample.payload,
                        media_status=sample.media_status,
                    )
                    if state.closed:
                        continue
                    for frame in frames:
                        self._record_prepared_preview(frame)
                finally:
                    queue.task_done()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state.error_count += 1
            state.last_error = f"{exc.__class__.__name__}: {exc}"
            self._events.add(
                "rv101_h264_preview",
                "worker_error",
                {"error": state.last_error, "error_count": state.error_count},
                session_id=session_id,
                severity="warning",
            )
        finally:
            if state.decoder:
                state.decoder.close()
                state.decoder = None

    def _process_sample(
        self,
        *,
        state: _SessionPreviewDecoder,
        session_id: str,
        header: dict[str, Any],
        payload: bytes,
        media_status: dict[str, Any],
    ) -> list[_PreparedPreviewFrame]:
        settings = self._settings_provider()
        decoder = self._ensure_decoder(session_id=session_id, state=state)
        if not decoder:
            return []
        frame_count = _frame_count_for(header=header, media_status=media_status)
        metadata = merge_video_metadata(_media_status_metadata(media_status), video_metadata_from_header(header))
        try:
            images = decoder.decode(payload)
        except Exception as exc:
            state.error_count += 1
            state.last_error = f"{exc.__class__.__name__}: {exc}"
            state.has_key_or_config_sample = False
            state.needs_keyframe_after_gap = True
            self._events.add(
                "rv101_h264_preview",
                "decode_error",
                {"error": state.last_error, "error_count": state.error_count},
                session_id=session_id,
                severity="warning",
            )
            decoder.close()
            state.decoder = None
            return []
        state.processed_sample_count += 1
        prepared: list[_PreparedPreviewFrame] = []
        for image in images:
            state.decoded_frame_count += 1
            self._decoded_frame_count += 1
            if self._should_publish(state, frame_count, settings):
                prepared.append(
                    self._prepare_preview(
                        session_id=session_id,
                        image=image,
                        frame_count=frame_count,
                        settings=settings,
                        metadata=metadata,
                    )
                )
                state.preview_frame_count += 1
                state.last_preview_frame_count = frame_count
                state.last_preview_monotonic_s = self._clock()
                self._preview_frame_count += 1
        return prepared

    def close_session(self, session_id: str) -> None:
        state = self._sessions.pop(session_id, None)
        if not state:
            return
        state.closed = True
        if state.queue is not None:
            if state.queue.full():
                try:
                    state.queue.get_nowait()
                    state.queue.task_done()
                except asyncio.QueueEmpty:
                    pass
            try:
                state.queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
        if state.worker is not None and not state.worker.done():
            return
        if state.decoder:
            state.decoder.close()
            state.decoder = None

    def close_all(self) -> None:
        for session_id in list(self._sessions):
            self.close_session(session_id)

    def _ensure_session(self, session_id: str, *, settings: Rv101H264PreviewSettings) -> _SessionPreviewDecoder:
        state = self._sessions.get(session_id)
        if state:
            return state
        state = _SessionPreviewDecoder()
        if self._start_workers:
            self._ensure_queue(session_id=session_id, state=state, settings=settings)
        self._sessions[session_id] = state
        return state

    def _ensure_queue(
        self,
        *,
        session_id: str,
        state: _SessionPreviewDecoder,
        settings: Rv101H264PreviewSettings,
    ) -> asyncio.Queue[_QueuedPreviewSample | None]:
        if state.queue is None:
            state.queue = asyncio.Queue(maxsize=settings.queue_size)
        if self._start_workers and (state.worker is None or state.worker.done()):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # Unit tests may use enqueue_sample outside an event loop; in that
                # case the bounded queue behavior is still testable but no worker runs.
                pass
            else:
                state.worker = loop.create_task(
                    self._worker_loop(session_id=session_id, state=state),
                    name=f"rv101_h264_preview:{session_id}",
                )
        return state.queue

    def _ensure_decoder(self, *, session_id: str, state: _SessionPreviewDecoder) -> H264FrameDecoder | None:
        if state.decoder:
            return state.decoder
        try:
            decoder = self._decoder_factory()
        except Exception as exc:
            self._decoder_init_error = f"{exc.__class__.__name__}: {exc}"
            if not self._decoder_init_error_logged:
                self._events.add(
                    "rv101_h264_preview",
                    "decoder_unavailable",
                    {"error": self._decoder_init_error},
                    session_id=session_id,
                    severity="warning",
                )
                self._decoder_init_error_logged = True
            return None
        state.decoder = decoder
        return decoder

    def _should_attempt_decode(
        self,
        *,
        state: _SessionPreviewDecoder,
        frame_count: int,
        is_keyframe: bool,
        settings: Rv101H264PreviewSettings,
    ) -> bool:
        # H.264 P/B frames depend on prior compressed frames. Dropping deltas
        # before PyAV creates blocky/corrupt previews, so the default path
        # decodes the full dependency chain and throttles only JPEG publishing.
        if state.needs_keyframe_after_gap and not is_keyframe:
            return False
        if state.enqueued_sample_count <= 0 and state.processed_sample_count <= 0 and state.preview_frame_count <= 0:
            return is_keyframe
        if not state.has_key_or_config_sample and not is_keyframe:
            return False
        if settings.decode_every_sample:
            return True
        if is_keyframe and state.preview_frame_count <= 0:
            return True
        if settings.every_n_frames > 1 and state.last_enqueued_frame_count:
            if frame_count - state.last_enqueued_frame_count < settings.every_n_frames:
                return False
        if settings.min_interval_ms > 0 and state.last_enqueued_monotonic_s is not None:
            elapsed_ms = (self._clock() - state.last_enqueued_monotonic_s) * 1000
            if elapsed_ms < settings.min_interval_ms:
                return False
        return True

    def _record_throttled_sample(self, *, state: _SessionPreviewDecoder, session_id: str, frame_count: int) -> None:
        state.throttled_sample_count += 1
        if state.throttled_sample_count <= 3 or state.throttled_sample_count % 120 == 0:
            self._events.add(
                "rv101_h264_preview",
                "sample_throttled",
                {
                    "frame_count": frame_count,
                    "throttled_sample_count": state.throttled_sample_count,
                },
                session_id=session_id,
            )

    def _should_publish(
        self,
        state: _SessionPreviewDecoder,
        frame_count: int,
        settings: Rv101H264PreviewSettings,
    ) -> bool:
        if state.preview_frame_count <= 0:
            return True
        if frame_count - state.last_preview_frame_count < settings.every_n_frames:
            return False
        if state.last_preview_monotonic_s is None:
            return True
        return (self._clock() - state.last_preview_monotonic_s) * 1000 >= settings.min_interval_ms

    def _prepare_preview(
        self,
        *,
        session_id: str,
        image: Any,
        frame_count: int,
        settings: Rv101H264PreviewSettings,
        metadata: dict[str, Any] | None = None,
    ) -> _PreparedPreviewFrame:
        source_width = _to_int(getattr(image, "width", None))
        source_height = _to_int(getattr(image, "height", None))
        preview_metadata = merge_video_metadata(metadata)
        image, rotation = _apply_rotation(image, preview_metadata)
        oriented_width = _to_int(getattr(image, "width", None))
        oriented_height = _to_int(getattr(image, "height", None))
        image = _resize_for_preview(image, max_width=settings.max_width)
        if image.mode != "RGB":
            image = image.convert("RGB")
        preview_width = _to_int(getattr(image, "width", None))
        preview_height = _to_int(getattr(image, "height", None))
        downscaled = bool(
            oriented_width
            and oriented_height
            and preview_width
            and preview_height
            and (preview_width != oriented_width or preview_height != oriented_height)
        )
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=settings.jpeg_quality)
        preview_metadata.setdefault("profile", "rv101_live_h264")
        preview_metadata["source"] = "rv101_live_h264"
        preview_metadata["preview_profile"] = "downscaled" if downscaled else "full_res"
        preview_metadata["preview_downscaled"] = downscaled
        preview_metadata["source_width"] = source_width
        preview_metadata["source_height"] = source_height
        preview_metadata["sourceWidth"] = source_width
        preview_metadata["sourceHeight"] = source_height
        preview_metadata["oriented_width"] = oriented_width
        preview_metadata["oriented_height"] = oriented_height
        preview_metadata["preview_width"] = preview_width
        preview_metadata["preview_height"] = preview_height
        preview_metadata["previewWidth"] = preview_width
        preview_metadata["previewHeight"] = preview_height
        preview_metadata["rotation_applied"] = rotation["applied"]
        preview_metadata["rotation_applied_degrees"] = rotation["degrees"] if rotation["applied"] else 0
        preview_metadata["rotation_metadata_source"] = rotation["source"]
        preview_metadata["downscaled_to"] = f"{preview_width}x{preview_height}" if preview_width and preview_height else None
        preview_metadata["downscaled_from"] = f"{oriented_width}x{oriented_height}" if downscaled else None
        return _PreparedPreviewFrame(
            session_id=session_id,
            image_bytes=buffer.getvalue(),
            width=preview_width,
            height=preview_height,
            frame_count=frame_count,
            metadata=preview_metadata,
        )

    def _record_prepared_preview(self, frame: _PreparedPreviewFrame) -> None:
        self._preview.record_frame(
            session_id=frame.session_id,
            source="rv101_live_h264",
            image_bytes=frame.image_bytes,
            width=frame.width,
            height=frame.height,
            frame_count=frame.frame_count,
            content_type="image/jpeg",
            metadata=frame.metadata,
        )
        if self._preview_frame_recorder:
            self._preview_frame_recorder(
                session_id=frame.session_id,
                image_bytes=frame.image_bytes,
                frame_count=frame.frame_count,
                metadata=frame.metadata,
                width=frame.width,
                height=frame.height,
            )


class PyAvH264FrameDecoder:
    def __init__(self) -> None:
        import av  # type: ignore

        self._codec = av.CodecContext.create("h264", "r")

    def decode(self, payload: bytes) -> list[Any]:
        images: list[Any] = []
        for packet in self._codec.parse(payload):
            for frame in self._codec.decode(packet):
                images.append(frame.to_image())
        return images

    def close(self) -> None:
        try:
            self._codec.close()
        except Exception:
            pass


def load_rv101_h264_preview_settings() -> Rv101H264PreviewSettings:
    return Rv101H264PreviewSettings(
        enabled=_env_bool("OPENVISION_RV101_H264_PREVIEW", False),
        every_n_frames=_clamp_int(_env_int("OPENVISION_RV101_H264_PREVIEW_EVERY_N_FRAMES", 1), 1, 300),
        min_interval_ms=_clamp_int(_env_int("OPENVISION_RV101_H264_PREVIEW_MIN_INTERVAL_MS", 66), 0, 60000),
        max_width=_clamp_int(_env_int("OPENVISION_RV101_H264_PREVIEW_MAX_WIDTH", 720), 160, 1920),
        jpeg_quality=_clamp_int(_env_int("OPENVISION_RV101_H264_PREVIEW_JPEG_QUALITY", 82), 30, 95),
        queue_size=_clamp_int(_env_int("OPENVISION_RV101_H264_PREVIEW_QUEUE_SIZE", 4), 1, 30),
        decode_every_sample=_env_bool("OPENVISION_RV101_H264_PREVIEW_DECODE_EVERY_SAMPLE", True),
    )


def _drain_preview_queue(queue: asyncio.Queue[_QueuedPreviewSample | None]) -> int:
    dropped = 0
    while True:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            return dropped
        queue.task_done()
        dropped += 1


def _max_publish_fps(min_interval_ms: int) -> float | None:
    if min_interval_ms <= 0:
        return None
    return round(1000.0 / min_interval_ms, 2)


def _resize_for_preview(image: Any, *, max_width: int) -> Any:
    if max_width <= 0 or image.width <= max_width:
        return image
    height = max(1, round(image.height * (max_width / image.width)))
    try:
        from PIL import Image  # type: ignore

        return image.resize((max_width, height), Image.Resampling.LANCZOS)
    except Exception:
        return image.resize((max_width, height))


def _apply_rotation(image: Any, metadata: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    degrees, source = _rotation_degrees_for(metadata)
    rotation = {"degrees": degrees, "source": source, "applied": False}
    if degrees not in {90, 180, 270}:
        return image, rotation
    # Metadata degrees describe the clockwise display correction. PIL's rotate()
    # uses counter-clockwise degrees, so apply the inverse.
    rotated = image.rotate(-degrees, expand=True)
    rotation["applied"] = True
    return rotated, rotation


def _rotation_degrees_for(metadata: dict[str, Any]) -> tuple[int, str | None]:
    for key in ("rotation_degrees", "sensor_orientation_degrees"):
        value = _to_int(metadata.get(key))
        if value is None:
            continue
        normalized = value % 360
        if normalized in {0, 90, 180, 270}:
            return normalized, key
    return 0, None


def _frame_count_for(*, header: dict[str, Any], media_status: dict[str, Any]) -> int:
    video = media_status.get("video") if isinstance(media_status, dict) else None
    if isinstance(video, dict):
        count = _to_int(video.get("frame_count"))
        if count:
            return count
    return _to_int(header.get("sequence")) or 0


def _media_status_metadata(media_status: dict[str, Any]) -> dict[str, Any]:
    video = media_status.get("video") if isinstance(media_status, dict) else None
    metadata = video.get("metadata") if isinstance(video, dict) else None
    return metadata if isinstance(metadata, dict) else {}


def _copy_media_status(media_status: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(media_status, dict):
        return {}
    output: dict[str, Any] = {}
    video = media_status.get("video")
    if isinstance(video, dict):
        copied_video = dict(video)
        metadata = copied_video.get("metadata")
        if isinstance(metadata, dict):
            copied_video["metadata"] = dict(metadata)
        output["video"] = copied_video
    return output


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
