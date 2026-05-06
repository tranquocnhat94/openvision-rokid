"""RV101 stream recorder for product-quality review on Jetson SSD."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
from typing import Any
import wave

from .contracts import utc_now
from .event_store import InMemoryEventStore


@dataclass(frozen=True, slots=True)
class Rv101StreamRecorderSettings:
    enabled: bool = False
    root_dir: Path = field(default_factory=lambda: _default_runtime_dir() / "recordings")
    raw_video_enabled: bool = True
    raw_audio_enabled: bool = True
    processed_preview_enabled: bool = True
    playable_video_enabled: bool = True
    ffmpeg_path: str = "ffmpeg"
    ffmpeg_timeout_s: float = 45.0
    max_queue_items: int = 256
    jpeg_quality: int = 82


@dataclass(slots=True)
class _SessionRecording:
    session_id: str
    root_dir: Path
    raw_dir: Path
    processed_dir: Path
    manifest_path: Path
    video_path: Path
    audio_path: Path
    processed_mjpeg_path: Path
    processed_latest_path: Path
    started_at: str
    video_bytes: int = 0
    video_sample_count: int = 0
    audio_bytes: int = 0
    audio_sample_count: int = 0
    processed_frame_count: int = 0
    dropped_item_count: int = 0
    last_error: str | None = None
    video_file: Any | None = None
    audio_file: wave.Wave_write | None = None
    processed_file: Any | None = None
    audio_sample_rate: int = 24000
    audio_channels: int = 1


@dataclass(frozen=True, slots=True)
class _RecordItem:
    kind: str
    session_id: str
    header: dict[str, Any] = field(default_factory=dict)
    payload: bytes = b""
    metadata: dict[str, Any] = field(default_factory=dict)


class Rv101StreamRecorder:
    """Asynchronously writes raw RV101 media and annotated preview evidence.

    The ingest path only enqueues bounded work; disk I/O and JPEG annotation run
    on a single background writer thread so preview/audio/video transport stays
    responsive.
    """

    def __init__(
        self,
        *,
        events: InMemoryEventStore,
        settings_provider: Any = None,
    ) -> None:
        self._events = events
        self._settings_provider = settings_provider or load_rv101_stream_recorder_settings
        self._settings = self._settings_provider()
        self._queue: queue.Queue[_RecordItem | None] = queue.Queue(maxsize=max(1, self._settings.max_queue_items))
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._sessions: dict[str, _SessionRecording] = {}
        self._closing_sessions: set[str] = set()
        self._closed_sessions: dict[str, str] = {}
        self._post_close_media_ignored: set[str] = set()
        self._total_dropped = 0
        self._last_error: str | None = None

    def status(self) -> dict[str, Any]:
        settings = self._settings_provider()
        with self._lock:
            return {
                "enabled": settings.enabled,
                "status": "ready" if settings.enabled else "disabled",
                "root_dir": str(settings.root_dir),
                "raw_video_enabled": settings.raw_video_enabled,
                "raw_audio_enabled": settings.raw_audio_enabled,
                "processed_preview_enabled": settings.processed_preview_enabled,
                "playable_video_enabled": settings.playable_video_enabled,
                "ffmpeg_path": settings.ffmpeg_path,
                "queue_size": settings.max_queue_items,
                "pending_item_count": self._queue.qsize(),
                "active_session_count": len(self._sessions),
                "total_dropped_item_count": self._total_dropped,
                "last_error": self._last_error,
                "sessions": [self._session_status(item) for item in self._sessions.values()],
            }

    def list_recordings(self, *, limit: int = 50) -> list[dict[str, Any]]:
        settings = self._settings_provider()
        root = settings.root_dir
        if not root.is_dir():
            return []
        rows: list[dict[str, Any]] = []
        for session_dir in sorted(root.iterdir(), key=_recording_sort_key, reverse=True):
            if not session_dir.is_dir():
                continue
            manifest = session_dir / "manifest.jsonl"
            raw_video = session_dir / "raw" / "video.h264"
            raw_video_mp4 = session_dir / "raw" / "video.mp4"
            raw_audio = session_dir / "raw" / "audio.wav"
            processed_preview = session_dir / "processed" / "preview_annotated.mjpeg"
            processed_preview_mp4 = session_dir / "processed" / "preview_annotated.mp4"
            latest_annotated = session_dir / "processed" / "latest_annotated.jpg"
            processed_events = session_dir / "processed" / "preview_annotated.jsonl"
            rows.append(
                {
                    "recording_id": session_dir.name,
                    "session_id": _session_id_from_recording_dir(session_dir.name),
                    "recording_dir": str(session_dir),
                    "manifest_path": str(manifest),
                    "raw_video_path": str(raw_video),
                    "raw_video_mp4_path": str(raw_video_mp4),
                    "raw_audio_path": str(raw_audio),
                    "processed_preview_path": str(processed_preview),
                    "processed_preview_mp4_path": str(processed_preview_mp4),
                    "latest_annotated_preview_path": str(latest_annotated),
                    "artifacts": {
                        "manifest": _file_info(manifest),
                        "raw_video": _file_info(raw_video),
                        "raw_video_mp4": _file_info(raw_video_mp4),
                        "raw_audio": _file_info(raw_audio),
                        "processed_preview": _file_info(processed_preview),
                        "processed_preview_mp4": _file_info(processed_preview_mp4),
                        "latest_annotated_preview": _file_info(latest_annotated),
                        "processed_events": _file_info(processed_events),
                    },
                    "summary": _recording_summary(
                        raw_video_samples=session_dir / "raw" / "video_samples.jsonl",
                        raw_audio=raw_audio,
                        processed_events=processed_events,
                        latest_annotated=latest_annotated,
                    ),
                    "updated_at": _mtime_iso(session_dir),
                }
            )
            if len(rows) >= max(1, limit):
                break
        return rows

    def active_processed_preview(self, session_id: str) -> dict[str, Any] | None:
        clean_session_id = str(session_id or "").strip()
        if not clean_session_id:
            return None
        with self._lock:
            session = self._sessions.get(clean_session_id)
            if session is None:
                return None
            payload = self._session_status(session)
            payload["recording_id"] = session.root_dir.name
            payload["latest_annotated_preview"] = _file_info(session.processed_latest_path)
            payload["processed_preview"] = _file_info(session.processed_mjpeg_path)
        if not payload["latest_annotated_preview"].get("exists"):
            return None
        return payload

    def record_video_frame(self, *, session_id: str, header: dict[str, Any], payload: bytes, message_type: int) -> None:
        settings = self._settings_provider()
        if not settings.enabled or not settings.raw_video_enabled:
            return
        kind = "video_hello" if int(message_type or 0) == 1 else "video_sample" if int(message_type or 0) == 2 else ""
        if not kind:
            return
        self._offer(_RecordItem(kind=kind, session_id=session_id, header=dict(header), payload=bytes(payload or b"")))

    def record_audio_frame(self, *, session_id: str, header: dict[str, Any], payload: bytes, message_type: int) -> None:
        settings = self._settings_provider()
        if not settings.enabled or not settings.raw_audio_enabled:
            return
        kind = "audio_hello" if int(message_type or 0) == 3 else "audio_sample" if int(message_type or 0) == 4 else ""
        if not kind:
            return
        self._offer(_RecordItem(kind=kind, session_id=session_id, header=dict(header), payload=bytes(payload or b"")))

    def record_processed_preview(
        self,
        *,
        session_id: str,
        image_bytes: bytes,
        frame_count: int,
        perception: dict[str, Any],
        width: int | None = None,
        height: int | None = None,
    ) -> None:
        settings = self._settings_provider()
        if not settings.enabled or not settings.processed_preview_enabled or not image_bytes:
            return
        metadata = {
            "frame_count": frame_count,
            "width": width,
            "height": height,
            "perception": perception,
        }
        self._offer(_RecordItem(kind="processed_preview", session_id=session_id, payload=bytes(image_bytes), metadata=metadata))

    def close_session(self, session_id: str, *, reason: str = "session_closed") -> None:
        settings = self._settings_provider()
        if not settings.enabled:
            return
        clean_session_id = str(session_id or "").strip()
        if not clean_session_id:
            return
        with self._lock:
            if clean_session_id in self._closing_sessions or clean_session_id in self._closed_sessions:
                return
            self._closing_sessions.add(clean_session_id)
        self._offer(_RecordItem(kind="close_session", session_id=session_id, metadata={"reason": reason}))

    def allow_session_reopen(self, session_id: str) -> None:
        clean_session_id = str(session_id or "").strip()
        if not clean_session_id:
            return
        with self._lock:
            self._closing_sessions.discard(clean_session_id)
            self._closed_sessions.pop(clean_session_id, None)
            self._post_close_media_ignored.discard(clean_session_id)

    def finalize_recording(self, recording_id: str) -> dict[str, Any]:
        settings = self._settings_provider()
        safe_recording_id = _safe_segment(recording_id)
        if safe_recording_id != recording_id:
            raise ValueError("invalid recording id")
        recording_dir = settings.root_dir / safe_recording_id
        if not recording_dir.is_dir():
            raise FileNotFoundError(str(recording_dir))
        return _finalize_playable_videos(
            recording_dir=recording_dir,
            settings=settings,
            events=self._events,
            session_id=_session_id_from_recording_dir(safe_recording_id),
        )

    def close_all(self) -> None:
        with self._lock:
            session_ids = list(self._sessions)
        for session_id in session_ids:
            self.close_session(session_id, reason="shutdown")
        self._offer(None)
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)

    def _offer(self, item: _RecordItem | None) -> None:
        self._settings = self._settings_provider()
        if item is not None:
            session_id = str(item.session_id or "").strip()
            if not session_id:
                return
            with self._lock:
                closing_or_closed = session_id in self._closing_sessions or session_id in self._closed_sessions
                should_ignore = closing_or_closed and item.kind != "close_session"
                should_log_ignore = should_ignore and session_id not in self._post_close_media_ignored
                if should_ignore:
                    self._post_close_media_ignored.add(session_id)
            if should_ignore:
                if should_log_ignore:
                    self._events.add(
                        "rv101_stream_recorder",
                        "post_close_media_ignored",
                        {"kind": item.kind, "reason": self._closed_sessions.get(session_id) or "close_requested"},
                        session_id=session_id,
                        severity="info",
                    )
                return
            item = _RecordItem(
                kind=item.kind,
                session_id=session_id,
                header=item.header,
                payload=item.payload,
                metadata=item.metadata,
            )
        self._ensure_worker()
        try:
            if item is None or item.kind == "close_session":
                self._queue.put(item, timeout=1.0)
            else:
                self._queue.put_nowait(item)
        except queue.Full:
            with self._lock:
                self._total_dropped += 1
                if item is not None and item.session_id in self._sessions:
                    self._sessions[item.session_id].dropped_item_count += 1
            self._events.add(
                "rv101_stream_recorder",
                "queue_full_drop",
                {"kind": item.kind if item else "shutdown", "queue_size": self._settings.max_queue_items},
                session_id=item.session_id if item else None,
                severity="warning",
            )

    def _ensure_worker(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._worker_loop, name="rv101_stream_recorder", daemon=True)
        self._thread.start()

    def _worker_loop(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    self._close_all_open_sessions(reason="shutdown")
                    return
                self._handle_item(item)
            except Exception as exc:
                message = f"{exc.__class__.__name__}: {exc}"
                with self._lock:
                    self._last_error = message
                    if item.session_id in self._sessions:
                        self._sessions[item.session_id].last_error = message
                self._events.add(
                    "rv101_stream_recorder",
                    "write_error",
                    {"kind": item.kind, "error": message},
                    session_id=item.session_id,
                    severity="warning",
                )
            finally:
                self._queue.task_done()

    def _handle_item(self, item: _RecordItem) -> None:
        if item.kind == "close_session":
            self._close_session(item.session_id, reason=str(item.metadata.get("reason") or "session_closed"))
            return
        session = self._ensure_session(item.session_id)
        if item.kind == "video_hello":
            _append_jsonl(session.manifest_path, {"type": "video_hello", "created_at": utc_now(), "header": item.header})
            return
        if item.kind == "video_sample":
            if session.video_file is None:
                session.video_file = (session.raw_dir / "video.h264").open("ab")
            session.video_file.write(item.payload)
            session.video_file.flush()
            session.video_bytes += len(item.payload)
            session.video_sample_count += 1
            _append_jsonl(
                session.raw_dir / "video_samples.jsonl",
                {
                    "created_at": utc_now(),
                    "bytes": len(item.payload),
                    "is_keyframe": bool(item.header.get("isKeyframe") or item.header.get("is_keyframe")),
                    "sequence": item.header.get("sequence"),
                    "width": item.header.get("width"),
                    "height": item.header.get("height"),
                    "sent_fps_estimate": item.header.get("sentFpsEstimate"),
                    "dropped_frames": item.header.get("droppedFrames"),
                },
            )
            return
        if item.kind == "audio_hello":
            session.audio_sample_rate = _to_int(item.header.get("sampleRateHz"), 24000) or 24000
            session.audio_channels = _to_int(item.header.get("channels"), 1) or 1
            _append_jsonl(session.manifest_path, {"type": "audio_hello", "created_at": utc_now(), "header": item.header})
            return
        if item.kind == "audio_sample":
            if session.audio_file is None:
                session.audio_file = wave.open(str(session.audio_path), "wb")
                session.audio_file.setnchannels(max(1, session.audio_channels))
                session.audio_file.setsampwidth(2)
                session.audio_file.setframerate(max(1, session.audio_sample_rate))
            session.audio_file.writeframes(item.payload)
            session.audio_bytes += len(item.payload)
            session.audio_sample_count += 1
            return
        if item.kind == "processed_preview":
            perception = item.metadata.get("perception") if isinstance(item.metadata.get("perception"), dict) else {}
            perception_metadata = perception.get("metadata") if isinstance(perception.get("metadata"), dict) else {}
            annotated = _annotate_preview_jpeg(
                item.payload,
                perception=perception,
                jpeg_quality=self._settings_provider().jpeg_quality,
            )
            if session.processed_file is None:
                session.processed_file = session.processed_mjpeg_path.open("ab")
            session.processed_file.write(annotated)
            session.processed_file.flush()
            session.processed_latest_path.write_bytes(annotated)
            session.processed_frame_count += 1
            _append_jsonl(
                session.processed_dir / "preview_annotated.jsonl",
                {
                    "created_at": utc_now(),
                    "frame_count": item.metadata.get("frame_count"),
                    "width": item.metadata.get("width"),
                    "height": item.metadata.get("height"),
                    "bytes": len(annotated),
                    "object_count": len(perception.get("objects") or []),
                    "snapshot_id": perception.get("snapshot_id"),
                    "source": perception.get("source"),
                    "frame_id": perception.get("frame_id"),
                    "perception_frame_count": perception_metadata.get("perception_frame_count"),
                    "perception_frame_delta": perception_metadata.get("perception_frame_delta"),
                    "perception_bbox_stale": perception_metadata.get("perception_bbox_stale"),
                },
            )
            return
    def _ensure_session(self, session_id: str) -> _SessionRecording:
        with self._lock:
            existing = self._sessions.get(session_id)
            if existing:
                return existing
            now = utc_now()
            root = self._settings_provider().root_dir / f"{_safe_segment(session_id)}-{_timestamp_segment(now)}"
            raw_dir = root / "raw"
            processed_dir = root / "processed"
            raw_dir.mkdir(parents=True, exist_ok=True)
            processed_dir.mkdir(parents=True, exist_ok=True)
            session = _SessionRecording(
                session_id=session_id,
                root_dir=root,
                raw_dir=raw_dir,
                processed_dir=processed_dir,
                manifest_path=root / "manifest.jsonl",
                video_path=raw_dir / "video.h264",
                audio_path=raw_dir / "audio.wav",
                processed_mjpeg_path=processed_dir / "preview_annotated.mjpeg",
                processed_latest_path=processed_dir / "latest_annotated.jpg",
                started_at=now,
            )
            self._sessions[session_id] = session
        _append_jsonl(
            session.manifest_path,
            {
                "type": "recording_started",
                "created_at": now,
                "session_id": session_id,
                "recording_dir": str(root),
                "raw_video_path": str(session.video_path),
                "raw_audio_path": str(session.audio_path),
                "processed_preview_path": str(session.processed_mjpeg_path),
            },
        )
        self._events.add(
            "rv101_stream_recorder",
            "recording_started",
            {"recording_dir": str(root)},
            session_id=session_id,
        )
        return session

    def _close_session(self, session_id: str, *, reason: str) -> None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if not session:
            with self._lock:
                self._closing_sessions.discard(session_id)
                self._closed_sessions[session_id] = reason
            self._events.add(
                "rv101_stream_recorder",
                "recording_closed_empty",
                {"reason": reason},
                session_id=session_id,
            )
            return
        self._close_files(session)
        finalize_result = _finalize_playable_videos(
            recording_dir=session.root_dir,
            settings=self._settings_provider(),
            events=self._events,
            session_id=session.session_id,
        )
        _append_jsonl(
            session.manifest_path,
            {
                "type": "recording_closed",
                "created_at": utc_now(),
                "reason": reason,
                "playable_video": finalize_result,
                **self._session_status(session),
            },
        )
        self._events.add(
            "rv101_stream_recorder",
            "recording_closed",
            self._session_status(session),
            session_id=session_id,
        )
        with self._lock:
            self._closing_sessions.discard(session_id)
            self._closed_sessions[session_id] = reason

    def _close_all_open_sessions(self, *, reason: str) -> None:
        with self._lock:
            session_ids = list(self._sessions)
        for session_id in session_ids:
            self._close_session(session_id, reason=reason)

    @staticmethod
    def _close_files(session: _SessionRecording) -> None:
        for handle_name in ("video_file", "processed_file", "audio_file"):
            handle = getattr(session, handle_name)
            if handle is None:
                continue
            try:
                handle.close()
            finally:
                setattr(session, handle_name, None)

    @staticmethod
    def _session_status(session: _SessionRecording) -> dict[str, Any]:
        return {
            "session_id": session.session_id,
            "recording_dir": str(session.root_dir),
            "raw_video_path": str(session.video_path),
            "raw_audio_path": str(session.audio_path),
            "processed_preview_path": str(session.processed_mjpeg_path),
            "latest_annotated_preview_path": str(session.processed_latest_path),
            "video_sample_count": session.video_sample_count,
            "video_bytes": session.video_bytes,
            "audio_sample_count": session.audio_sample_count,
            "audio_bytes": session.audio_bytes,
            "processed_frame_count": session.processed_frame_count,
            "dropped_item_count": session.dropped_item_count,
            "last_error": session.last_error,
        }


def load_rv101_stream_recorder_settings() -> Rv101StreamRecorderSettings:
    runtime_dir = Path(os.getenv("OPENVISION_RUNTIME_DIR") or _default_runtime_dir()).expanduser()
    root_dir = Path(os.getenv("OPENVISION_RV101_STREAM_RECORDING_DIR") or runtime_dir / "recordings").expanduser()
    return Rv101StreamRecorderSettings(
        enabled=_env_bool("OPENVISION_RV101_STREAM_RECORDING", False),
        root_dir=root_dir,
        raw_video_enabled=_env_bool("OPENVISION_RV101_STREAM_RECORD_RAW_VIDEO", True),
        raw_audio_enabled=_env_bool("OPENVISION_RV101_STREAM_RECORD_RAW_AUDIO", True),
        processed_preview_enabled=_env_bool("OPENVISION_RV101_STREAM_RECORD_PROCESSED_PREVIEW", True),
        playable_video_enabled=_env_bool("OPENVISION_RV101_STREAM_RECORD_PLAYABLE_VIDEO", True),
        ffmpeg_path=os.getenv("OPENVISION_FFMPEG") or "ffmpeg",
        ffmpeg_timeout_s=_env_float("OPENVISION_RV101_STREAM_RECORD_FFMPEG_TIMEOUT_S", 45.0),
        max_queue_items=_env_int("OPENVISION_RV101_STREAM_RECORD_QUEUE_SIZE", 256),
        jpeg_quality=_env_int("OPENVISION_RV101_STREAM_RECORD_JPEG_QUALITY", 82),
    )


def _finalize_playable_videos(
    *,
    recording_dir: Path,
    settings: Rv101StreamRecorderSettings,
    events: InMemoryEventStore,
    session_id: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "enabled": settings.playable_video_enabled,
        "raw_video_mp4": {"status": "disabled"},
        "processed_preview_mp4": {"status": "disabled"},
    }
    if not settings.playable_video_enabled:
        return result

    manifest = recording_dir / "manifest.jsonl"
    raw_video = recording_dir / "raw" / "video.h264"
    raw_video_mp4 = recording_dir / "raw" / "video.mp4"
    processed_mjpeg = recording_dir / "processed" / "preview_annotated.mjpeg"
    processed_mp4 = recording_dir / "processed" / "preview_annotated.mp4"
    processed_events = recording_dir / "processed" / "preview_annotated.jsonl"
    latest_annotated = recording_dir / "processed" / "latest_annotated.jpg"
    summary = _recording_summary(
        raw_video_samples=recording_dir / "raw" / "video_samples.jsonl",
        raw_audio=recording_dir / "raw" / "audio.wav",
        processed_events=processed_events,
        latest_annotated=latest_annotated,
    )
    raw_fps = _safe_fps(summary.get("raw_video_fps_estimate"), default=15.0)
    processed_fps = _safe_fps(summary.get("processed_fps_estimate"), default=min(15.0, raw_fps or 15.0))

    result["raw_video_mp4"] = _finalize_raw_h264_mp4(
        ffmpeg_path=settings.ffmpeg_path,
        input_path=raw_video,
        output_path=raw_video_mp4,
        fps=raw_fps,
        timeout_s=settings.ffmpeg_timeout_s,
    )
    result["processed_preview_mp4"] = _finalize_processed_mjpeg_mp4(
        ffmpeg_path=settings.ffmpeg_path,
        input_path=processed_mjpeg,
        output_path=processed_mp4,
        fps=processed_fps,
        timeout_s=settings.ffmpeg_timeout_s,
    )
    event_payload = {
        "recording_dir": str(recording_dir),
        "raw_video_mp4": result["raw_video_mp4"],
        "processed_preview_mp4": result["processed_preview_mp4"],
    }
    _append_jsonl(
        manifest,
        {
            "type": "playable_video_finalized",
            "created_at": utc_now(),
            **event_payload,
        },
    )
    severity = "info" if all(
        item.get("status") in {"ready", "skipped_missing", "skipped_fresh", "disabled"}
        for item in (result["raw_video_mp4"], result["processed_preview_mp4"])
    ) else "warning"
    events.add(
        "rv101_stream_recorder",
        "playable_video_finalized",
        event_payload,
        session_id=session_id,
        severity=severity,
    )
    return result


def _finalize_raw_h264_mp4(
    *,
    ffmpeg_path: str,
    input_path: Path,
    output_path: Path,
    fps: float,
    timeout_s: float,
) -> dict[str, Any]:
    if not input_path.is_file() or input_path.stat().st_size <= 0:
        return _conversion_result("skipped_missing", output_path)
    if _artifact_is_fresh(output_path, [input_path]):
        return _conversion_result("skipped_fresh", output_path, fps=fps)
    temp_output = _temporary_mp4_path(output_path)
    common = [ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error", "-fflags", "+genpts", "-r", _fps_arg(fps), "-i", str(input_path)]
    attempts = [
        common + ["-c:v", "copy", "-movflags", "+faststart", str(temp_output)],
        common
        + [
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(temp_output),
        ],
    ]
    return _run_ffmpeg_attempts(
        attempts=attempts,
        temp_output=temp_output,
        output_path=output_path,
        fps=fps,
        timeout_s=timeout_s,
    )


def _finalize_processed_mjpeg_mp4(
    *,
    ffmpeg_path: str,
    input_path: Path,
    output_path: Path,
    fps: float,
    timeout_s: float,
) -> dict[str, Any]:
    if not input_path.is_file() or input_path.stat().st_size <= 0:
        return _conversion_result("skipped_missing", output_path)
    if _artifact_is_fresh(output_path, [input_path]):
        return _conversion_result("skipped_fresh", output_path, fps=fps)
    temp_output = _temporary_mp4_path(output_path)
    encode = [
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(temp_output),
    ]
    attempts = [
        [
            ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "mjpeg",
            "-framerate",
            _fps_arg(fps),
            "-i",
            str(input_path),
            *encode,
        ],
        [
            ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "-framerate",
            _fps_arg(fps),
            "-i",
            str(input_path),
            *encode,
        ],
    ]
    return _run_ffmpeg_attempts(
        attempts=attempts,
        temp_output=temp_output,
        output_path=output_path,
        fps=fps,
        timeout_s=timeout_s,
    )


def _run_ffmpeg_attempts(
    *,
    attempts: list[list[str]],
    temp_output: Path,
    output_path: Path,
    fps: float,
    timeout_s: float,
) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for command in attempts:
        try:
            temp_output.unlink(missing_ok=True)
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                timeout=max(1.0, float(timeout_s or 45.0)),
            )
        except FileNotFoundError:
            return _conversion_result("ffmpeg_missing", output_path, fps=fps, error=f"{command[0]} not found")
        except subprocess.TimeoutExpired as exc:
            errors.append(f"timeout after {exc.timeout}s")
            continue
        if completed.returncode == 0 and temp_output.is_file() and temp_output.stat().st_size > 0:
            temp_output.replace(output_path)
            return _conversion_result("ready", output_path, fps=fps)
        stderr = completed.stderr.decode("utf-8", "replace").strip()
        stdout = completed.stdout.decode("utf-8", "replace").strip()
        errors.append(stderr or stdout or f"ffmpeg exited {completed.returncode}")
    temp_output.unlink(missing_ok=True)
    return _conversion_result("failed", output_path, fps=fps, error=" | ".join(errors)[-600:])


def _temporary_mp4_path(output_path: Path) -> Path:
    return output_path.with_name(f".{output_path.stem}.tmp{output_path.suffix}")


def _artifact_is_fresh(output_path: Path, source_paths: list[Path]) -> bool:
    try:
        output_stat = output_path.stat()
    except OSError:
        return False
    if not output_path.is_file() or output_stat.st_size <= 0:
        return False
    source_mtimes = []
    for path in source_paths:
        try:
            source_mtimes.append(path.stat().st_mtime)
        except OSError:
            pass
    return bool(source_mtimes) and output_stat.st_mtime >= max(source_mtimes)


def _conversion_result(status: str, output_path: Path, *, fps: float | None = None, error: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": status, "path": str(output_path)}
    info = _file_info(output_path)
    payload["exists"] = bool(info.get("exists"))
    payload["size_bytes"] = int(info.get("size_bytes") or 0)
    if fps:
        payload["fps"] = round(float(fps), 3)
    if error:
        payload["error"] = error
    return payload


def _safe_fps(value: Any, *, default: float) -> float:
    fps = _to_float(value, default)
    if fps is None or fps <= 0:
        fps = default
    return round(max(1.0, min(60.0, float(fps))), 3)


def _fps_arg(value: float) -> str:
    return f"{_safe_fps(value, default=15.0):.3f}".rstrip("0").rstrip(".")


def _annotate_preview_jpeg(image_bytes: bytes, *, perception: dict[str, Any], jpeg_quality: int) -> bytes:
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return image_bytes
    try:
        image = Image.open(BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return image_bytes
    draw = ImageDraw.Draw(image)
    objects = perception.get("objects") if isinstance(perception.get("objects"), list) else []
    metadata = perception.get("metadata") if isinstance(perception.get("metadata"), dict) else {}
    bbox_stale = metadata.get("perception_bbox_stale") is True
    frame_delta = _to_int(metadata.get("perception_frame_delta"))
    frame_width = _to_int(perception.get("width"), image.width) or image.width
    frame_height = _to_int(perception.get("height"), image.height) or image.height
    scale_x = image.width / max(1, frame_width)
    scale_y = image.height / max(1, frame_height)
    for index, obj in enumerate(objects, start=1):
        if not isinstance(obj, dict):
            continue
        bbox = obj.get("bbox")
        if not isinstance(bbox, list) or len(bbox) < 4:
            continue
        try:
            x1, y1, x2, y2 = [float(value) for value in bbox[:4]]
        except (TypeError, ValueError):
            continue
        xyxy = [x1 * scale_x, y1 * scale_y, x2 * scale_x, y2 * scale_y]
        color = (145, 156, 172) if bbox_stale else _color_for_label(str(obj.get("label") or "object"))
        draw.rectangle(xyxy, outline=color, width=3)
        label = _object_label(obj, index=index)
        if bbox_stale and frame_delta is not None:
            label = f"{label} stale+{frame_delta}f"
        text_xy = (xyxy[0] + 3, max(0, xyxy[1] - 16))
        try:
            text_bbox = draw.textbbox(text_xy, label)
            draw.rectangle(text_bbox, fill=color)
        except Exception:
            pass
        draw.text(text_xy, label, fill=(0, 0, 0))
    out = BytesIO()
    image.save(out, format="JPEG", quality=max(35, min(95, int(jpeg_quality or 82))))
    return out.getvalue()


def _object_label(obj: dict[str, Any], *, index: int) -> str:
    attrs = obj.get("attributes") if isinstance(obj.get("attributes"), dict) else {}
    name = (
        obj.get("display_name")
        or obj.get("name")
        or attrs.get("display_name")
        or attrs.get("identity_name")
        or attrs.get("known_name")
        or attrs.get("contact_name")
    )
    if name:
        return str(name)
    label = str(obj.get("label") or "obj")
    track = obj.get("track_id") or obj.get("object_id") or index
    if attrs.get("classification_status") == "unclassified" or attrs.get("confidence_source") == "missing":
        return f"YOLO track {track}" if str(label).lower() in {"object", "unknown", "obj"} else f"{label} {track}"
    confidence = obj.get("confidence")
    try:
        return f"{label} {track} {float(confidence):.2f}"
    except (TypeError, ValueError):
        return f"{label} {track}"


def _color_for_label(label: str) -> tuple[int, int, int]:
    if "face" in label:
        return (255, 214, 10)
    if "person" in label:
        return (0, 220, 140)
    return (80, 180, 255)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")


def _safe_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return cleaned[:80] or "unknown"


def _timestamp_segment(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "", value)[:15] or "time"


def _session_id_from_recording_dir(name: str) -> str:
    return name.rsplit("-", 1)[0] if "-" in name else name


def _recording_sort_key(path: Path) -> tuple[str, float, str]:
    timestamp = path.name.rsplit("-", 1)[-1] if "-" in path.name else ""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return timestamp, mtime, path.name


def _mtime_iso(path: Path) -> str | None:
    try:
        return utc_now_from_timestamp(path.stat().st_mtime)
    except OSError:
        return None


def _file_info(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
    except OSError:
        return {"path": str(path), "exists": False, "size_bytes": 0}
    info = {"path": str(path), "exists": path.is_file(), "size_bytes": stat.st_size}
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        width, height = _image_size(path)
        if width and height:
            info["width"] = width
            info["height"] = height
    return info


def _recording_summary(
    *,
    raw_video_samples: Path,
    raw_audio: Path,
    processed_events: Path,
    latest_annotated: Path,
) -> dict[str, Any]:
    video_rows = _read_jsonl_rows(raw_video_samples)
    processed_rows = _read_jsonl_rows(processed_events)
    latest_width, latest_height = _image_size(latest_annotated)
    video_width = _last_value(video_rows, "width")
    video_height = _last_value(video_rows, "height")
    sent_fps = _to_float(_last_value(video_rows, "sent_fps_estimate"))
    processed_width = _to_int(_last_value(processed_rows, "width"), latest_width)
    processed_height = _to_int(_last_value(processed_rows, "height"), latest_height)
    processed_duration_s = _jsonl_duration_s(processed_rows)
    processed_count = len(processed_rows)
    return {
        "raw_video_frame_count": len(video_rows),
        "raw_video_width": _to_int(video_width),
        "raw_video_height": _to_int(video_height),
        "raw_video_fps_estimate": sent_fps,
        "raw_video_duration_s": _duration_from_count(count=len(video_rows), fps=sent_fps),
        "raw_audio_duration_s": _wav_duration_s(raw_audio),
        "processed_frame_count": processed_count,
        "processed_preview_width": processed_width,
        "processed_preview_height": processed_height,
        "processed_duration_s": processed_duration_s,
        "processed_fps_estimate": _fps_from_duration(count=processed_count, duration_s=processed_duration_s),
    }


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    rows.append(payload)
    except OSError:
        return rows
    return rows


def _last_value(rows: list[dict[str, Any]], key: str) -> Any:
    for row in reversed(rows):
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _image_size(path: Path) -> tuple[int | None, int | None]:
    if not path.is_file():
        return None, None
    try:
        from PIL import Image
        with Image.open(path) as image:
            return int(image.width), int(image.height)
    except Exception:
        return None, None


def _wav_duration_s(path: Path) -> float | None:
    if not path.is_file():
        return None
    try:
        with wave.open(str(path), "rb") as handle:
            frame_rate = handle.getframerate()
            frame_count = handle.getnframes()
    except Exception:
        return None
    if frame_rate <= 0:
        return None
    return round(frame_count / frame_rate, 3)


def _jsonl_duration_s(rows: list[dict[str, Any]]) -> float | None:
    if len(rows) < 2:
        return None
    start = _parse_iso_time(str(rows[0].get("created_at") or ""))
    end = _parse_iso_time(str(rows[-1].get("created_at") or ""))
    if start is None or end is None:
        return None
    return round(max(0.0, (end - start).total_seconds()), 3)


def _parse_iso_time(value: str) -> datetime | None:
    clean = str(value or "").strip()
    if not clean:
        return None
    try:
        return datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError:
        return None


def _duration_from_count(*, count: int, fps: float | None) -> float | None:
    if count <= 1 or not fps or fps <= 0:
        return None
    return round((count - 1) / fps, 3)


def _fps_from_duration(*, count: int, duration_s: float | None) -> float | None:
    if count <= 1 or not duration_s or duration_s <= 0:
        return None
    return round((count - 1) / duration_s, 3)


def utc_now_from_timestamp(timestamp: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _default_runtime_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "runtime"


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _to_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
