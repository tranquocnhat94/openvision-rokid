import asyncio
import base64
import json
import os
import queue
import re
import struct
import subprocess
import threading
import time
import uuid
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .admin_page_templates import (
    build_dashboard_page,
    build_preview_live_page,
    build_simulator_page,
    simulator_page_headers,
)
from .admin_session_runtime import (
    latest_session_id,
    serialize_live_voice_session,
    serialize_session,
    sort_sessions_by_connected_at,
    tail_session_log_lines,
)
from .ai_runtime import AiRuntimeManager, _humanize_label, _normalize_label
from .browser_media_runtime import BrowserMediaRuntime, LatestFrame
from .browser_webrtc_runtime import BrowserWebRTCRuntime
from .control_protocol_runtime import (
    build_browser_client_hello_log,
    build_browser_client_trace_log,
    build_browser_media_state_log,
    build_error_payload,
    build_session_accept_payload,
)
from .hud_scene_runtime import (
    build_hud_scene_payload,
    build_target_search_hud_scene_payload,
)
from .preview_runtime import PreviewProcess, PreviewRuntime
from .session_retention_runtime import (
    SessionRetentionSnapshot,
    session_last_activity_ts,
    session_prune_eligible,
)
from .target_hud_runtime import (
    TargetHudState,
    evaluate_target_hud_scene,
    reset_target_hud_positive_state,
)
from .voice_runtime import VoiceOrchestrator
from .websocket_control_runtime import SessionControlRuntime, send_json

try:
    from aiortc import RTCPeerConnection, RTCSessionDescription  # type: ignore
    from av.audio.resampler import AudioResampler  # type: ignore
    AIORTC_AVAILABLE = True
    AIORTC_IMPORT_ERROR = ""
except Exception as error:  # pragma: no cover - optional dependency
    RTCPeerConnection = None  # type: ignore[assignment]
    RTCSessionDescription = None  # type: ignore[assignment]
    AudioResampler = None  # type: ignore[assignment]
    AIORTC_AVAILABLE = False
    AIORTC_IMPORT_ERROR = str(error)


HOST = os.getenv("ROKID_BACKEND_HOST", "0.0.0.0")
PUBLIC_HOST = os.getenv("ROKID_PUBLIC_HOST", "127.0.0.1")
PORT = int(os.getenv("ROKID_BACKEND_PORT", "9080"))
MEDIA_PORT = int(os.getenv("ROKID_MEDIA_PORT", os.getenv("ROKID_VIDEO_PORT", "9082")))
VIDEO_PORT = MEDIA_PORT
AUDIO_PORT = MEDIA_PORT
RESULT_INTERVAL_MS = int(os.getenv("ROKID_RESULT_INTERVAL_MS", "120"))
DEFAULT_MODE = os.getenv("ROKID_DEFAULT_MODE", "standby")
ROOT_DIR = Path(os.getenv("ROKID_ROOT_DIR", str(Path.home() / ".openvision-glass")))
APP_DIR = Path(__file__).parent
LOG_DIR = ROOT_DIR / "logs"
STREAM_DIR = ROOT_DIR / "runtime" / "streams"
PREVIEW_DIR = ROOT_DIR / "runtime" / "preview"
ADMIN_STATIC_DIR = APP_DIR / "static"
ENABLE_HLS_PREVIEW = os.getenv("ROKID_ENABLE_HLS", "0") == "1"
ENABLE_MJPEG_PREVIEW = os.getenv("ROKID_ENABLE_MJPEG", "0") == "1"
ENABLE_LOCAL_PREVIEW = os.getenv("ROKID_ENABLE_LOCAL_PREVIEW", "0") == "1"
ENABLE_FRAME_BUS = os.getenv("ROKID_ENABLE_FRAME_BUS", "0") == "1"
RAW_FRAME_TARGET_FPS = int(os.getenv("ROKID_RAW_FRAME_FPS", "10"))
PREVIEW_JPEG_QUALITY = int(os.getenv("ROKID_PREVIEW_JPEG_QUALITY", "82"))
AUDIO_RING_MAX_BYTES = int(os.getenv("ROKID_AUDIO_RING_MAX_BYTES", str(16_000 * 2 * 12)))
AUDIO_SAMPLE_LOG_INTERVAL = max(1, int(os.getenv("ROKID_AUDIO_SAMPLE_LOG_INTERVAL", "10")))
VIDEO_SAMPLE_LOG_INTERVAL = max(1, int(os.getenv("ROKID_VIDEO_SAMPLE_LOG_INTERVAL", "15")))
PREVIEW_PIPE_QUEUE_MAX = max(2, int(os.getenv("ROKID_PREVIEW_PIPE_QUEUE_MAX", "4")))
SESSION_RETENTION_SEC = max(15.0, float(os.getenv("ROKID_SESSION_RETENTION_SEC", "60")))
SESSION_PRUNE_INTERVAL_SEC = max(5.0, float(os.getenv("ROKID_SESSION_PRUNE_INTERVAL_SEC", "15")))
BROWSER_AUDIO_SAMPLE_RATE = int(os.getenv("ROKID_BROWSER_AUDIO_SAMPLE_RATE", "16000"))
BROWSER_AUDIO_CHANNELS = int(os.getenv("ROKID_BROWSER_AUDIO_CHANNELS", "1"))
BROWSER_AUDIO_BYTES_PER_SAMPLE = int(os.getenv("ROKID_BROWSER_AUDIO_BYTES_PER_SAMPLE", "2"))
HUD_THUMB_SIZE_PX = max(36, int(os.getenv("ROKID_HUD_THUMB_SIZE_PX", "72")))
HUD_THUMB_JPEG_QUALITY = max(35, min(90, int(os.getenv("ROKID_HUD_THUMB_JPEG_QUALITY", "55"))))
HUD_THUMB_PNG_COMPRESSION = max(0, min(9, int(os.getenv("ROKID_HUD_THUMB_PNG_COMPRESSION", "4"))))
HUD_MAX_CANDIDATES = max(1, min(4, int(os.getenv("ROKID_HUD_MAX_CANDIDATES", "2"))))
HUD_TARGET_SCENE_INTERVAL_MS = max(250, int(os.getenv("ROKID_HUD_TARGET_SCENE_INTERVAL_MS", "850")))
HUD_TARGET_CANDIDATE_GRACE_MS = max(500, int(os.getenv("ROKID_HUD_TARGET_CANDIDATE_GRACE_MS", "2200")))
ARCHIVE_AUDIO_STREAMS = os.getenv("ROKID_ARCHIVE_AUDIO_STREAMS", "0") == "1"
ARCHIVE_VIDEO_STREAMS = os.getenv("ROKID_ARCHIVE_VIDEO_STREAMS", "0") == "1"
ARCHIVE_QUEUE_MAX = max(1, int(os.getenv("ROKID_ARCHIVE_QUEUE_MAX", "256")))
LOCAL_PREVIEW_DISPLAY = os.getenv("ROKID_LOCAL_PREVIEW_DISPLAY", ":0")
LOCAL_PREVIEW_XAUTHORITY = os.getenv(
    "ROKID_LOCAL_PREVIEW_XAUTHORITY",
    "/run/user/1000/gdm/Xauthority",
)
LOCAL_PREVIEW_MODE = os.getenv("ROKID_LOCAL_PREVIEW_MODE", "ffplay")
LOCAL_PREVIEW_SINK = os.getenv("ROKID_LOCAL_PREVIEW_SINK", "xvimagesink")

def frame_bus_required_for_session(session: "SessionState") -> bool:
    return AI_RUNTIME.requires_frame_bus_for_mode(
        session.mode,
        target_search_active=bool((session.active_target_query or "").strip()),
    )


def frame_bus_runtime_enabled() -> bool:
    if ENABLE_FRAME_BUS:
        return True
    return any(frame_bus_required_for_session(session) for session in sessions.values() if session.active)


def sensor_debug_mjpeg_enabled() -> bool:
    return sensor_debug_mjpeg_enabled_for_session(None)


def sensor_debug_mjpeg_enabled_for_session(session_id: str | None = None) -> bool:
    if ENABLE_MJPEG_PREVIEW or frame_bus_runtime_enabled():
        return True
    if session_id:
        session = sessions.get(session_id)
        return bool(session is not None and session.active and latest_frames.get(session_id) is not None)
    return any(
        session.active and latest_frames.get(active_session_id) is not None
        for active_session_id, session in sessions.items()
    )


FRAME_HEADER = struct.Struct("!4sHHII")
FRAME_MAGIC = b"RVS1"
FRAME_VERSION = 1
TYPE_HELLO = 1
TYPE_VIDEO_SAMPLE = 2
TYPE_AUDIO_HELLO = 3
TYPE_AUDIO_SAMPLE = 4
SMART_SCENE_MODES = {
    "scene_monitor",
    "people_count",
    "object_count",
    "visual_assistant",
    "focus_bubble",
    "ar_radar",
    "alert_burst",
    "traffic_count",
}
VEHICLE_LABELS = {"car", "truck", "bus", "motorbike", "motorcycle", "bicycle"}
CARRY_LABELS = {"bag", "backpack", "handbag", "suitcase", "umbrella"}
PRIORITY_LABELS = (
    "person",
    "bag",
    "backpack",
    "car",
    "motorbike",
    "truck",
    "bus",
    "bicycle",
)


@dataclass
class SessionState:
    session_id: str
    device_id: str
    app_version: str
    mode: str = DEFAULT_MODE
    connected_at: float = field(default_factory=time.time)
    last_ping_at: float = field(default_factory=time.time)
    last_message_at: float = field(default_factory=time.time)
    result_count: int = 0
    control_connected: bool = True
    video_connected: bool = False
    audio_connected: bool = False
    video_peer: str | None = None
    audio_peer: str | None = None
    video_frames: int = 0
    video_bytes: int = 0
    video_keyframes: int = 0
    audio_packets: int = 0
    audio_bytes: int = 0
    last_audio_timestamp_ms: int | None = None
    rotation_degrees: int = 0
    last_video_seq: int = 0
    last_video_timestamp_ms: int | None = None
    latest_video_width: int = 0
    latest_video_height: int = 0
    latest_video_target_fps: int = 0
    latest_video_target_bitrate: int = 0
    latest_video_profile_label: str = ""
    rx_fps: float = 0.0
    last_video_monotonic: float | None = None
    latest_device_telemetry: dict[str, Any] = field(default_factory=dict)
    latest_encoder_stats: dict[str, Any] = field(default_factory=dict)
    latest_audio_stats: dict[str, Any] = field(default_factory=dict)
    latest_speech_state: dict[str, Any] = field(default_factory=dict)
    latest_hud_scene: dict[str, Any] = field(default_factory=dict)
    latest_voice_command: dict[str, Any] = field(default_factory=dict)
    latest_skill_trace: list[dict[str, Any]] = field(default_factory=list)
    active_target_query: str | None = None
    selected_target_track_id: str = ""
    selected_target_label: str = ""
    selected_target_summary: str = ""
    selected_target_query: str = ""
    selected_target_updated_ms: int = 0
    selected_target_visible: bool = False
    last_target_hud_signature: str = ""
    last_target_hud_sent_ms: int = 0
    last_target_positive_scene: dict[str, Any] = field(default_factory=dict)
    last_target_positive_ms: int = 0
    last_target_positive_query: str = ""
    last_error: str | None = None
    log_path: str = ""
    h264_path: str = ""
    audio_path: str = ""
    preview_path: str = ""
    preview_url: str = ""

    def __post_init__(self) -> None:
        self._audio_buffer_lock = threading.Lock()
        self._audio_buffer = bytearray()
        self._audio_buffer_start_offset = 0

    def append_audio_payload(self, payload: bytes, *, max_buffer_bytes: int) -> None:
        if not payload:
            return
        with self._audio_buffer_lock:
            self._audio_buffer.extend(payload)
            overflow = len(self._audio_buffer) - max(1, max_buffer_bytes)
            if overflow > 0:
                del self._audio_buffer[:overflow]
                self._audio_buffer_start_offset += overflow

    def read_audio_window(self, start_offset: int, max_bytes: int | None = None) -> tuple[int, int, bytes]:
        with self._audio_buffer_lock:
            buffer_start = self._audio_buffer_start_offset
            buffer_end = buffer_start + len(self._audio_buffer)
            normalized_start = max(start_offset, buffer_start)
            normalized_end = buffer_end if max_bytes is None else min(buffer_end, normalized_start + max_bytes)
            relative_start = max(0, normalized_start - buffer_start)
            relative_end = max(relative_start, normalized_end - buffer_start)
            payload = bytes(self._audio_buffer[relative_start:relative_end])
        return normalized_start, normalized_end, payload

    @property
    def active(self) -> bool:
        return self.control_connected or self.video_connected or self.audio_connected

    def summary(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("latest_hud_scene", None)
        data["active"] = self.active
        data["uptime_sec"] = round(time.time() - self.connected_at, 1)
        return data


class BinaryArchiveWriter:
    def __init__(self, *, thread_name: str, max_items: int) -> None:
        self._queue: queue.Queue[tuple[str, bytes] | None] = queue.Queue(maxsize=max_items)
        self._max_items = max_items
        self._dropped_items = 0
        self._dropped_bytes = 0
        self._lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name=thread_name,
        )
        self._thread.start()

    def append(self, path: str, payload: bytes) -> None:
        if not path or not payload:
            return
        try:
            self._queue.put_nowait((path, payload))
        except queue.Full:
            with self._lock:
                self._dropped_items += 1
                self._dropped_bytes += len(payload)

    def close(self) -> None:
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            with suppress(queue.Empty):
                self._queue.get_nowait()
            self._queue.put_nowait(None)
        self._thread.join(timeout=2.0)

    def health(self) -> dict[str, Any]:
        with self._lock:
            dropped_items = self._dropped_items
            dropped_bytes = self._dropped_bytes
        return {
            "queueDepth": self._queue.qsize(),
            "queueMax": self._max_items,
            "droppedItems": dropped_items,
            "droppedBytes": dropped_bytes,
        }

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            path, payload = item
            try:
                archive_path = Path(path)
                archive_path.parent.mkdir(parents=True, exist_ok=True)
                with open(archive_path, "ab") as sink:
                    sink.write(payload)
            except Exception:
                continue


class AudioArchiveWriter(BinaryArchiveWriter):
    def __init__(self, *, max_items: int) -> None:
        super().__init__(thread_name="rokid-audio-archive", max_items=max_items)


class VideoArchiveWriter(BinaryArchiveWriter):
    def __init__(self, *, max_items: int) -> None:
        super().__init__(thread_name="rokid-video-archive", max_items=max_items)


class SessionLogWriter:
    def __init__(self) -> None:
        self._queue: queue.SimpleQueue[tuple[str, dict[str, Any]] | None] = queue.SimpleQueue()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="rokid-session-log",
        )
        self._thread.start()

    def append(self, path: str, record: dict[str, Any]) -> None:
        if not path:
            return
        self._queue.put((path, record))

    def close(self) -> None:
        self._queue.put(None)
        self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            path, record = item
            try:
                log_path = Path(path)
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(log_path, "a", encoding="utf-8") as sink:
                    sink.write(json.dumps(record, ensure_ascii=False) + "\n")
            except Exception:
                continue


app = FastAPI(title="Rokid Backend MVP", version="0.5.0")
sessions: dict[str, SessionState] = {}
preview_processes: dict[str, PreviewProcess] = {}
latest_preview_session_id: str | None = None
latest_frames: dict[str, LatestFrame] = {}
latest_codec_config_frames: dict[str, bytes] = {}
latest_ai_results: dict[str, dict[str, Any]] = {}
pending_control_events: dict[str, list[dict[str, Any]]] = {}
PENDING_EVENTS_LOCK = threading.Lock()
AI_RUNTIME = AiRuntimeManager(ROOT_DIR)
VOICE_RUNTIME: VoiceOrchestrator | None = None


def now_ms() -> int:
    return int(time.time() * 1000)


def _get_latest_preview_session_id() -> str | None:
    return latest_preview_session_id


def _set_latest_preview_session_id(value: str | None) -> None:
    global latest_preview_session_id
    latest_preview_session_id = value


def ensure_runtime_dirs() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    STREAM_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)


def create_session(device_id: str, app_version: str, mode: str) -> SessionState:
    ensure_runtime_dirs()
    session_id = f"sess_{uuid.uuid4().hex[:8]}"
    session = SessionState(
        session_id=session_id,
        device_id=device_id,
        app_version=app_version,
        mode=mode or DEFAULT_MODE,
        log_path=str(LOG_DIR / f"{session_id}.jsonl"),
        h264_path=str(STREAM_DIR / f"{session_id}.h264"),
        audio_path=str(STREAM_DIR / f"{session_id}.pcm"),
        preview_path=str(PREVIEW_DIR / session_id / "index.m3u8"),
        preview_url=f"http://{PUBLIC_HOST}:{PORT}/preview/sessions/{session_id}/index.m3u8",
    )
    sessions[session_id] = session
    append_session_log(
        session,
        "session_created",
        {
            "deviceId": device_id,
            "appVersion": app_version,
            "mode": session.mode,
        },
    )
    return session


def queue_control_event(session: SessionState, payload: dict[str, Any]) -> None:
    with PENDING_EVENTS_LOCK:
        pending_control_events.setdefault(session.session_id, []).append(payload)

    message_type = payload.get("type")
    if message_type == "speech_state":
        session.latest_speech_state = payload
    elif message_type == "hud_scene":
        session.latest_hud_scene = payload


def drain_control_events(session_id: str) -> list[dict[str, Any]]:
    with PENDING_EVENTS_LOCK:
        return pending_control_events.pop(session_id, [])


def session_preview_dir(session: SessionState) -> Path:
    return PREVIEW_DIR / session.session_id


def session_retention_snapshot(session: SessionState) -> SessionRetentionSnapshot:
    return SessionRetentionSnapshot(
        connected_at=session.connected_at,
        last_ping_at=session.last_ping_at,
        last_message_at=session.last_message_at,
        control_connected=session.control_connected,
        video_connected=session.video_connected,
        audio_connected=session.audio_connected,
    )


async def prune_session(session_id: str, *, reason: str) -> None:
    global latest_preview_session_id
    session = sessions.get(session_id)
    if session is None:
        with PENDING_EVENTS_LOCK:
            pending_control_events.pop(session_id, None)
        latest_frames.pop(session_id, None)
        latest_codec_config_frames.pop(session_id, None)
        latest_ai_results.pop(session_id, None)
        if latest_preview_session_id == session_id:
            latest_preview_session_id = None
        if VOICE_RUNTIME is not None:
            VOICE_RUNTIME.drop_session(session_id, reason=reason)
        AI_RUNTIME.drop_session(session_id)
        return

    await close_browser_webrtc_peer(session_id, reason=reason)
    PREVIEW_RUNTIME.stop_preview_process(session, reason=reason)
    with PENDING_EVENTS_LOCK:
        pending_control_events.pop(session_id, None)
    latest_frames.pop(session_id, None)
    latest_codec_config_frames.pop(session_id, None)
    latest_ai_results.pop(session_id, None)
    if latest_preview_session_id == session_id:
        latest_preview_session_id = None

    inactivity_sec = max(0.0, time.time() - session_last_activity_ts(session_retention_snapshot(session)))
    append_session_log(
        session,
        "session_pruned",
        {
            "reason": reason,
            "inactiveAgeSec": round(inactivity_sec, 1),
        },
    )
    sessions.pop(session_id, None)
    if VOICE_RUNTIME is not None:
        VOICE_RUNTIME.drop_session(session_id, reason=reason)
    AI_RUNTIME.drop_session(session_id)


async def prune_stale_sessions(*, reason: str = "inactive_retention_expired") -> None:
    now_ts = time.time()
    stale_ids = [
        session.session_id
        for session in list(sessions.values())
        if session_prune_eligible(
            session_retention_snapshot(session),
            now_ts=now_ts,
            retention_sec=SESSION_RETENTION_SEC,
        )
    ]
    for session_id in stale_ids:
        await prune_session(session_id, reason=reason)


async def session_prune_loop() -> None:
    while True:
        await asyncio.sleep(SESSION_PRUNE_INTERVAL_SEC)
        await prune_stale_sessions()


def get_or_create_video_session(header: dict[str, Any]) -> SessionState:
    session_id = str(header.get("sessionId") or "").strip()
    if session_id and session_id in sessions:
        return sessions[session_id]
    return create_session(
        device_id=str(header.get("deviceId") or "video-only-device"),
        app_version=str(header.get("appVersion") or "0.0.0"),
        mode=str(header.get("mode") or DEFAULT_MODE),
    )


def append_session_log(session: SessionState, event: str, payload: dict[str, Any]) -> None:
    record = {
        "timestampMs": now_ms(),
        "sessionId": session.session_id,
        "event": event,
        **payload,
    }
    _maybe_append_skill_trace(session, event, record)
    log_writer = getattr(app.state, "session_log_writer", None)
    if log_writer is not None:
        log_writer.append(session.log_path, record)
        return
    log_path = Path(session.log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as sink:
        sink.write(json.dumps(record, ensure_ascii=False) + "\n")


PREVIEW_RUNTIME = PreviewRuntime(
    append_session_log=append_session_log,
    session_lookup=lambda session_id: sessions.get(session_id),
    session_preview_dir_provider=session_preview_dir,
    preview_processes=preview_processes,
    latest_frames=latest_frames,
    latest_ai_results=latest_ai_results,
    latest_codec_config_frames=latest_codec_config_frames,
    latest_preview_session_id_getter=_get_latest_preview_session_id,
    latest_preview_session_id_setter=_set_latest_preview_session_id,
    now_ms_provider=now_ms,
    enable_hls_preview=ENABLE_HLS_PREVIEW,
    enable_frame_bus=ENABLE_FRAME_BUS,
    ai_requires_frame_bus_provider=frame_bus_required_for_session,
    enable_local_preview=ENABLE_LOCAL_PREVIEW,
    raw_frame_target_fps=RAW_FRAME_TARGET_FPS,
    preview_jpeg_quality=PREVIEW_JPEG_QUALITY,
    preview_pipe_queue_max=PREVIEW_PIPE_QUEUE_MAX,
    local_preview_display=LOCAL_PREVIEW_DISPLAY,
    local_preview_xauthority=LOCAL_PREVIEW_XAUTHORITY,
    local_preview_mode=LOCAL_PREVIEW_MODE,
    local_preview_sink=LOCAL_PREVIEW_SINK,
    local_preview_port=PORT,
)


def remember_session_video_profile(
    session: SessionState,
    *,
    width: int,
    height: int,
    target_fps: int,
    target_bitrate: int,
    profile_label: str,
) -> None:
    if width > 0:
        session.latest_video_width = width
    if height > 0:
        session.latest_video_height = height
    if target_fps > 0:
        session.latest_video_target_fps = target_fps
    if target_bitrate > 0:
        session.latest_video_target_bitrate = target_bitrate
    if profile_label:
        session.latest_video_profile_label = profile_label


def refresh_preview_for_session(session: SessionState, *, reason: str) -> bool:
    current_preview = preview_processes.get(session.session_id)
    if not PREVIEW_RUNTIME.preview_required_for_session(session):
        if current_preview is not None:
            PREVIEW_RUNTIME.stop_preview_process(session, reason=f"{reason}_not_required")
        return False
    width = session.latest_video_width
    height = session.latest_video_height
    if width <= 0 or height <= 0:
        return False
    frame_bus_enabled = PREVIEW_RUNTIME.frame_bus_enabled_for_session(session)
    should_restart = current_preview is None or PREVIEW_RUNTIME.needs_preview_restart(
        current_preview,
        width=width,
        height=height,
        target_fps=session.latest_video_target_fps,
        target_bitrate=session.latest_video_target_bitrate,
        profile_label=session.latest_video_profile_label,
        frame_bus_enabled=frame_bus_enabled,
    )
    if should_restart:
        PREVIEW_RUNTIME.start_preview_process(
            session=session,
            width=width,
            height=height,
            target_fps=session.latest_video_target_fps,
            target_bitrate=session.latest_video_target_bitrate,
            profile_label=session.latest_video_profile_label,
        )
    return should_restart


BROWSER_MEDIA_RUNTIME = BrowserMediaRuntime(
    append_session_log=append_session_log,
    latest_frames=latest_frames,
    latest_ai_results=latest_ai_results,
    latest_preview_session_id_getter=_get_latest_preview_session_id,
    latest_preview_session_id_setter=_set_latest_preview_session_id,
    now_ms_provider=now_ms,
    preview_jpeg_quality=PREVIEW_JPEG_QUALITY,
    video_sample_log_interval=VIDEO_SAMPLE_LOG_INTERVAL,
    audio_sample_log_interval=AUDIO_SAMPLE_LOG_INTERVAL,
    browser_audio_sample_rate=BROWSER_AUDIO_SAMPLE_RATE,
    browser_audio_channels=BROWSER_AUDIO_CHANNELS,
    audio_ring_max_bytes=AUDIO_RING_MAX_BYTES,
    audio_archive_writer_provider=lambda: getattr(app.state, "audio_archive_writer", None),
)


BROWSER_WEBRTC_RUNTIME = BrowserWebRTCRuntime(
    peer_connection_factory=lambda: RTCPeerConnection(),  # type: ignore[misc]
    session_description_factory=RTCSessionDescription,  # type: ignore[arg-type]
    audio_resampler_factory=AudioResampler,
    media_runtime=BROWSER_MEDIA_RUNTIME,
    sessions=sessions,
    append_session_log=append_session_log,
    now_ms_provider=now_ms,
    browser_audio_sample_rate=BROWSER_AUDIO_SAMPLE_RATE,
    browser_audio_channels=BROWSER_AUDIO_CHANNELS,
)


async def close_browser_webrtc_peer(session_id: str, *, reason: str) -> None:
    await BROWSER_WEBRTC_RUNTIME.close_peer(session_id, reason=reason)


def _trace_summary(value: Any, *, limit: int = 160) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except Exception:
            text = str(value)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)].rstrip()}…"


def _append_skill_trace_entry(session: SessionState, entry: dict[str, Any]) -> None:
    session.latest_skill_trace.append(entry)
    if len(session.latest_skill_trace) > 40:
        session.latest_skill_trace = session.latest_skill_trace[-40:]


def _maybe_append_skill_trace(session: SessionState, event: str, record: dict[str, Any]) -> None:
    entry: dict[str, Any] | None = None
    if event == "voice_realtime_skill_call":
        entry = {
            "timestampMs": record.get("timestampMs"),
            "kind": "tool_call",
            "title": f"AI -> {record.get('tool') or 'tool'}",
            "summary": _trace_summary(record.get("arguments")),
            "payload": {
                "tool": record.get("tool"),
                "arguments": record.get("arguments"),
                "callId": record.get("callId"),
            },
        }
    elif event == "voice_realtime_skill_tool_output":
        entry = {
            "timestampMs": record.get("timestampMs"),
            "kind": "tool_output",
            "title": f"Jetson -> {record.get('tool') or 'tool'}",
            "summary": _trace_summary(record.get("output")),
            "payload": {
                "tool": record.get("tool"),
                "output": record.get("output"),
                "callId": record.get("callId"),
            },
        }
    elif event == "voice_realtime_skill_message":
        entry = {
            "timestampMs": record.get("timestampMs"),
            "kind": "model_message",
            "title": "AI status",
            "summary": _trace_summary(record.get("text")),
            "payload": {"text": record.get("text")},
        }
    elif event == "voice_skill_dispatched":
        entry = {
            "timestampMs": record.get("timestampMs"),
            "kind": "jetson_action",
            "title": f"Jetson action -> {record.get('intent') or 'unknown'}",
            "summary": _trace_summary(
                {
                    "mode": record.get("mode"),
                    "targetQuery": record.get("targetQuery"),
                    "statusText": record.get("statusText"),
                    "selectedTrackId": record.get("selectedTrackId"),
                }
            ),
            "payload": {
                "intent": record.get("intent"),
                "mode": record.get("mode"),
                "targetQuery": record.get("targetQuery"),
                "statusText": record.get("statusText"),
                "selectedTrackId": record.get("selectedTrackId"),
                "selectedTargetLabel": record.get("selectedTargetLabel"),
            },
        }
    elif event == "voice_realtime_skill_error":
        entry = {
            "timestampMs": record.get("timestampMs"),
            "kind": "error",
            "title": "Skill error",
            "summary": _trace_summary(record.get("error")),
            "payload": {
                "error": record.get("error"),
                "phase": record.get("phase"),
            },
        }
    elif event == "vision_skill_resolve_started":
        entry = {
            "timestampMs": record.get("timestampMs"),
            "kind": "vision_call",
            "title": "Jetson -> vision resolve",
            "summary": _trace_summary(
                {
                    "query": record.get("query"),
                    "candidateCount": record.get("candidateCount"),
                    "model": record.get("model"),
                }
            ),
            "payload": {
                "query": record.get("query"),
                "candidateCount": record.get("candidateCount"),
                "model": record.get("model"),
            },
        }
    elif event == "vision_skill_resolve_result":
        entry = {
            "timestampMs": record.get("timestampMs"),
            "kind": "vision_result",
            "title": "Vision resolution",
            "summary": _trace_summary(
                {
                    "selectedTrackId": record.get("selectedTrackId"),
                    "selectedTargetSummary": record.get("selectedTargetSummary"),
                    "resolutionSource": record.get("resolutionSource"),
                }
            ),
            "payload": record,
        }
    elif event == "vision_skill_analyze_started":
        entry = {
            "timestampMs": record.get("timestampMs"),
            "kind": "vision_call",
            "title": "Jetson -> target analyze",
            "summary": _trace_summary(record.get("question")),
            "payload": record,
        }
    elif event == "vision_skill_analyze_result":
        entry = {
            "timestampMs": record.get("timestampMs"),
            "kind": "vision_result",
            "title": "Vision answer",
            "summary": _trace_summary(record.get("answer")),
            "payload": record,
        }
    elif event == "vision_skill_openai_response":
        entry = {
            "timestampMs": record.get("timestampMs"),
            "kind": "vision_result",
            "title": "Vision model output",
            "summary": _trace_summary(record.get("text")),
            "payload": record,
        }
    elif event == "selected_target_updated":
        entry = {
            "timestampMs": record.get("timestampMs"),
            "kind": "jetson_action",
            "title": "Selected target",
            "summary": _trace_summary(
                {
                    "trackId": record.get("trackId"),
                    "label": record.get("label"),
                    "summary": record.get("summary"),
                }
            ),
            "payload": record,
        }
    elif event == "voice_command":
        transcript = str(record.get("transcript") or "").strip()
        if transcript:
            entry = {
                "timestampMs": record.get("timestampMs"),
                "kind": "final_command",
                "title": "Command committed",
                "summary": transcript,
                "payload": {
                    "intent": record.get("intent"),
                    "mode": record.get("mode"),
                    "targetQuery": record.get("targetQuery"),
                    "statusText": record.get("statusText"),
                    "transcript": transcript,
                },
            }
    if entry is not None:
        _append_skill_trace_entry(session, entry)


def estimate_capture_to_receive_ms(session: SessionState) -> int:
    capture_timestamp_ms = session.last_video_timestamp_ms
    if not capture_timestamp_ms:
        return 0
    delta_ms = now_ms() - capture_timestamp_ms
    if delta_ms < 0 or delta_ms > 10_000:
        return 0
    return int(delta_ms)


def _sorted_detections(ai_result: dict[str, Any]) -> list[dict[str, Any]]:
    detections = ai_result.get("detections")
    if not isinstance(detections, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in detections:
        if not isinstance(item, dict):
            continue
        bbox = item.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        normalized.append(
            {
                "label": _normalize_label(str(item.get("label") or "object")),
                "confidence": float(item.get("confidence") or 0.0),
                "bbox": [float(value) for value in bbox],
                "trackId": item.get("trackId"),
            }
        )
    normalized.sort(key=lambda entry: (-entry["confidence"], entry["label"]))
    return normalized


def _counts_for_detections(detections: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in detections:
        label = _normalize_label(str(item.get("label") or "object"))
        counts[label] = counts.get(label, 0) + 1
    return counts


def _zone_index(center_x: float, width: int) -> int:
    if width <= 0:
        return 1
    ratio = center_x / max(float(width), 1.0)
    if ratio < 0.33:
        return 0
    if ratio > 0.66:
        return 2
    return 1


def _zone_name(index: int) -> str:
    return ("left", "ahead", "right")[max(0, min(index, 2))]


def _directional_counts(detections: list[dict[str, Any]], width: int) -> dict[str, int]:
    counts = {"left": 0, "ahead": 0, "right": 0}
    for item in detections:
        x1, _, x2, _ = item["bbox"]
        counts[_zone_name(_zone_index((x1 + x2) * 0.5, width))] += 1
    return counts


def _top_by_zone(detections: list[dict[str, Any]], width: int) -> dict[str, dict[str, Any]]:
    picks: dict[str, dict[str, Any]] = {}
    for item in detections:
        x1, _, x2, _ = item["bbox"]
        zone = _zone_name(_zone_index((x1 + x2) * 0.5, width))
        current = picks.get(zone)
        if current is None or float(item["confidence"]) > float(current["confidence"]):
            picks[zone] = item
    return picks


def _pick_priority_detection(detections: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not detections:
        return None
    order = {label: index for index, label in enumerate(PRIORITY_LABELS)}
    return min(
        detections,
        key=lambda item: (
            order.get(str(item["label"]), 999),
            -float(item["confidence"]),
        ),
    )


def _vehicle_detections(detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in detections if _normalize_label(str(item["label"])) in VEHICLE_LABELS]


def _important_alert_detection(detections: list[dict[str, Any]], width: int) -> dict[str, Any] | None:
    vehicles = _vehicle_detections(detections)
    priority = vehicles or detections
    pick = _pick_priority_detection(priority)
    if pick is None:
        return None
    x1, _, x2, _ = pick["bbox"]
    pick = dict(pick)
    pick["zone"] = _zone_name(_zone_index((x1 + x2) * 0.5, width))
    return pick


def _inline_counts(counts: dict[str, int], preferred: tuple[str, ...], limit: int = 4) -> str:
    ordered = [(label, counts[label]) for label in preferred if counts.get(label, 0) > 0]
    if not ordered:
        ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return " | ".join(f"{_humanize_label(label)} {value}" for label, value in ordered[:limit])


def _person_candidates(detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    people = [item for item in detections if _normalize_label(str(item.get("label") or "")) == "person"]
    people.sort(
        key=lambda item: (
            -float(item.get("confidence") or 0.0),
            str(item.get("trackId") or ""),
        )
    )
    return people


def _target_query_normalized(value: str | None) -> str:
    return _normalize_label(str(value or ""))


def _query_is_person_like(query: str | None) -> bool:
    normalized = _target_query_normalized(query)
    return any(
        token in normalized
        for token in (
            "nguoi",
            "ao",
            "quan",
            "deo",
            "kinh",
            "mu",
            "nam",
            "nu",
            "mat",
            "balo",
            "tui",
        )
    )


def _query_zone_hint(query: str | None) -> str | None:
    normalized = _target_query_normalized(query)
    if any(token in normalized for token in ("ben trai", "phia trai", "trai", "left")):
        return "left"
    if any(token in normalized for token in ("ben phai", "phia phai", "phai", "right")):
        return "right"
    if any(token in normalized for token in ("phia truoc", "o giua", "giua", "ahead", "center")):
        return "ahead"
    return None


def _query_label_matches(item: dict[str, Any], query: str | None) -> bool:
    normalized = _target_query_normalized(query)
    if not normalized:
        return False
    label = _normalize_label(str(item.get("label") or ""))
    if not label:
        return False
    if label in normalized:
        return True
    humanized = _normalize_label(_humanize_label(label))
    return bool(humanized and humanized in normalized)


def _selected_track_first(
    candidates: list[dict[str, Any]],
    selected_track_id: str | None,
) -> list[dict[str, Any]]:
    selected = str(selected_track_id or "").strip()
    if not selected:
        return list(candidates)
    preferred: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []
    for item in candidates:
        if str(item.get("trackId") or "") == selected:
            preferred.append(item)
        else:
            remaining.append(item)
    return preferred + remaining


def _target_candidates_for_query(
    session: SessionState,
    detections: list[dict[str, Any]],
    query: str | None,
    frame_width: int = 0,
) -> list[dict[str, Any]]:
    base = list(detections)
    if not base:
        return []
    normalized_query = _target_query_normalized(query)
    if _query_is_person_like(normalized_query):
        people = _person_candidates(base)
        if people:
            base = people
    else:
        label_matches = [item for item in base if _query_label_matches(item, normalized_query)]
        if label_matches:
            base = label_matches
        elif _person_candidates(base):
            base = _person_candidates(base)
    zone_hint = _query_zone_hint(normalized_query)
    if zone_hint:
        zoned = [
            item
            for item in base
            if _candidate_zone(item, max(frame_width, 1)) == zone_hint
        ]
        if zoned:
            base = zoned
    base.sort(
        key=lambda item: (
            -float(item.get("confidence") or 0.0),
            _normalize_label(str(item.get("label") or "")),
            str(item.get("trackId") or ""),
        )
    )
    return _selected_track_first(base, session.selected_target_track_id)


def _candidate_zone(item: dict[str, Any], width: int) -> str:
    bbox = item.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return "ahead"
    x1, _, x2, _ = [float(value) for value in bbox]
    return _zone_name(_zone_index((x1 + x2) * 0.5, width))


def _candidate_label(index: int, item: dict[str, Any]) -> str:
    label = _normalize_label(str(item.get("label") or ""))
    track_id = item.get("trackId")
    if label and label != "person":
        base = _humanize_label(label)
        if isinstance(track_id, (int, float)) and int(track_id) > 0:
            return f"{base} {int(track_id)}"
        return base
    if isinstance(track_id, (int, float)) and int(track_id) > 0:
        return f"Nguoi {int(track_id)}"
    return f"Nguoi {index + 1}"


def _encode_candidate_thumb(frame_payload: dict[str, Any] | None, bbox: list[float] | None) -> str | None:
    if not frame_payload or not isinstance(bbox, list) or len(bbox) != 4:
        return None
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return None

    width = int(frame_payload.get("width") or 0)
    height = int(frame_payload.get("height") or 0)
    bgr_bytes = frame_payload.get("bgr_bytes")
    if width <= 0 or height <= 0 or not isinstance(bgr_bytes, (bytes, bytearray)):
        return None

    try:
        frame = np.frombuffer(bgr_bytes, dtype=np.uint8).reshape((height, width, 3))
    except Exception:
        return None

    x1, y1, x2, y2 = [int(float(value)) for value in bbox]
    if x2 <= x1 or y2 <= y1:
        return None

    pad_x = max(4, int((x2 - x1) * 0.18))
    pad_y = max(4, int((y2 - y1) * 0.12))
    x1 = max(0, x1 - pad_x)
    y1 = max(0, y1 - pad_y)
    x2 = min(width, x2 + pad_x)
    y2 = min(height, y2 + pad_y)
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return None

    crop_h, crop_w = crop.shape[:2]
    side = max(crop_h, crop_w)
    canvas = np.zeros((side, side, 3), dtype=np.uint8)
    y_offset = (side - crop_h) // 2
    x_offset = (side - crop_w) // 2
    canvas[y_offset:y_offset + crop_h, x_offset:x_offset + crop_w] = crop
    thumb = cv2.resize(canvas, (HUD_THUMB_SIZE_PX, HUD_THUMB_SIZE_PX), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(thumb, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    softened = cv2.GaussianBlur(gray, (0, 0), 0.9)
    enhanced = cv2.addWeighted(gray, 1.35, softened, -0.35, 0)
    enhanced = cv2.normalize(enhanced, None, 0, 255, cv2.NORM_MINMAX)
    _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    evidence = cv2.max(enhanced, binary)
    green_thumb = np.zeros((HUD_THUMB_SIZE_PX, HUD_THUMB_SIZE_PX, 3), dtype=np.uint8)
    green_thumb[:, :, 1] = evidence
    ok, encoded = cv2.imencode(
        ".png",
        green_thumb,
        [int(cv2.IMWRITE_PNG_COMPRESSION), HUD_THUMB_PNG_COMPRESSION],
    )
    if not ok:
        return None
    return base64.b64encode(encoded.tobytes()).decode("ascii")


def _candidate_thumb_bbox(item: dict[str, Any]) -> list[float] | None:
    bbox = item.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    x1, y1, x2, y2 = [float(value) for value in bbox]
    width = x2 - x1
    height = y2 - y1
    if width <= 0.0 or height <= 0.0:
        return bbox

    # For person search, bias the tile toward the head/upper torso so the
    # gallery reads more like an identity cue than a full-body evidence crop.
    if _normalize_label(str(item.get("label") or "")) == "person" and height >= width * 1.05:
        inset_x = width * 0.18
        head_bottom = min(y2, y1 + max(height * 0.42, width * 0.7))
        candidate = [x1 + inset_x, y1, x2 - inset_x, head_bottom]
        cx1, cy1, cx2, cy2 = candidate
        if cx2 > cx1 and cy2 > cy1:
            return candidate
    return bbox


def _crop_bbox_with_padding(
    bbox: list[float] | None,
    *,
    width: int,
    height: int,
    pad_x_ratio: float,
    pad_y_ratio: float,
) -> list[int] | None:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    x1, y1, x2, y2 = [int(float(value)) for value in bbox]
    if x2 <= x1 or y2 <= y1:
        return None
    pad_x = max(4, int((x2 - x1) * pad_x_ratio))
    pad_y = max(4, int((y2 - y1) * pad_y_ratio))
    return [
        max(0, x1 - pad_x),
        max(0, y1 - pad_y),
        min(width, x2 + pad_x),
        min(height, y2 + pad_y),
    ]


def _encode_vision_crop_jpeg(
    frame_payload: dict[str, Any] | None,
    bbox: list[float] | None,
    *,
    pad_x_ratio: float,
    pad_y_ratio: float,
    max_side: int,
    quality: int,
) -> str | None:
    if not frame_payload or not isinstance(bbox, list) or len(bbox) != 4:
        return None
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return None

    width = int(frame_payload.get("width") or 0)
    height = int(frame_payload.get("height") or 0)
    bgr_bytes = frame_payload.get("bgr_bytes")
    if width <= 0 or height <= 0 or not isinstance(bgr_bytes, (bytes, bytearray)):
        return None
    try:
        frame = np.frombuffer(bgr_bytes, dtype=np.uint8).reshape((height, width, 3))
    except Exception:
        return None
    crop_bbox = _crop_bbox_with_padding(
        bbox,
        width=width,
        height=height,
        pad_x_ratio=pad_x_ratio,
        pad_y_ratio=pad_y_ratio,
    )
    if not crop_bbox:
        return None
    x1, y1, x2, y2 = crop_bbox
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    crop_h, crop_w = crop.shape[:2]
    scale = min(1.0, float(max_side) / max(float(max(crop_h, crop_w)), 1.0))
    if scale < 0.999:
        resized = cv2.resize(
            crop,
            (max(1, int(crop_w * scale)), max(1, int(crop_h * scale))),
            interpolation=cv2.INTER_AREA,
        )
    else:
        resized = crop
    ok, encoded = cv2.imencode(
        ".jpg",
        resized,
        [int(cv2.IMWRITE_JPEG_QUALITY), max(40, min(95, quality))],
    )
    if not ok:
        return None
    return base64.b64encode(encoded.tobytes()).decode("ascii")


def _encode_full_frame_jpeg(
    frame_payload: dict[str, Any] | None,
    *,
    max_side: int,
    quality: int,
) -> str | None:
    if not frame_payload:
        return None
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return None
    width = int(frame_payload.get("width") or 0)
    height = int(frame_payload.get("height") or 0)
    bgr_bytes = frame_payload.get("bgr_bytes")
    if width <= 0 or height <= 0 or not isinstance(bgr_bytes, (bytes, bytearray)):
        return None
    try:
        frame = np.frombuffer(bgr_bytes, dtype=np.uint8).reshape((height, width, 3))
    except Exception:
        return None
    scale = min(1.0, float(max_side) / max(float(max(height, width)), 1.0))
    if scale < 0.999:
        frame = cv2.resize(
            frame,
            (max(1, int(width * scale)), max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    ok, encoded = cv2.imencode(
        ".jpg",
        frame,
        [int(cv2.IMWRITE_JPEG_QUALITY), max(40, min(95, quality))],
    )
    if not ok:
        return None
    return base64.b64encode(encoded.tobytes()).decode("ascii")


def _voice_config_value(key: str, default: Any) -> Any:
    voice_runtime = VOICE_RUNTIME
    if voice_runtime is None:
        return default
    try:
        config = voice_runtime.get_config(mask_secrets=False)
    except Exception:
        return default
    return config.get(key, default)


def _build_target_gallery_items(
    session: SessionState,
    detections: list[dict[str, Any]],
    frame_payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    width = int(frame_payload.get("width") or 0) if frame_payload else 0
    items: list[dict[str, Any]] = []
    query = session.active_target_query or session.selected_target_query or ""
    candidates = _target_candidates_for_query(session, detections, query, frame_width=width)
    for index, item in enumerate(candidates[:HUD_MAX_CANDIDATES]):
        confidence = float(item.get("confidence") or 0.0)
        zone = _candidate_zone(item, width)
        track_id = item.get("trackId")
        label = _candidate_label(index, item)
        secondary = f"{zone.title()} | {confidence:.2f}"
        gallery_item = {
            "label": label,
            "secondary": secondary,
            "trackId": str(track_id) if track_id not in (None, "") else "",
            "selected": str(track_id or "") == session.selected_target_track_id or (
                not session.selected_target_track_id and index == 0
            ),
        }
        thumb_b64 = _encode_candidate_thumb(frame_payload, _candidate_thumb_bbox(item))
        if thumb_b64:
            gallery_item["thumbB64"] = thumb_b64
        items.append(gallery_item)
    return items


def _build_target_marker_component(
    session: SessionState,
    detections: list[dict[str, Any]],
    frame_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    width = int(frame_payload.get("width") or 0) if frame_payload else 0
    query = session.active_target_query or session.selected_target_query or ""
    candidates = _target_candidates_for_query(session, detections, query, frame_width=width)
    if not candidates:
        return None
    selected_track = session.selected_target_track_id
    primary = next(
        (item for item in candidates if str(item.get("trackId") or "") == selected_track),
        candidates[0],
    )
    bbox = primary.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    height = int(frame_payload.get("height") or 0) if frame_payload else 0
    x1, y1, x2, y2 = [float(value) for value in bbox]
    center_x = ((x1 + x2) * 0.5) / max(float(width), 1.0) if width > 0 else 0.5
    center_y = ((y1 + y2) * 0.5) / max(float(height), 1.0) if height > 0 else 0.5
    return {
        "kind": "target_marker",
        "id": "primary_target",
        "zone": "center_overlay",
        "label": _candidate_label(candidates.index(primary), primary),
        "trackId": str(primary.get("trackId") or ""),
        "direction": _candidate_zone(primary, width),
        "selected": str(primary.get("trackId") or "") == selected_track or not selected_track,
        "normalizedX": round(max(0.0, min(1.0, center_x)), 3),
        "normalizedY": round(max(0.0, min(1.0, center_y)), 3),
    }


def _build_target_direction_hint(
    session: SessionState,
    detections: list[dict[str, Any]],
    frame_payload: dict[str, Any] | None,
) -> str | None:
    width = int(frame_payload.get("width") or 0) if frame_payload else 0
    query = session.active_target_query or session.selected_target_query or ""
    candidates = _target_candidates_for_query(session, detections, query, frame_width=width)
    if not candidates:
        return None
    primary_zone = _candidate_zone(candidates[0], width)
    if len(candidates) == 1:
        return f"{primary_zone.title()} 1 ung vien"
    return f"{primary_zone.title()} {len(candidates)} ung vien"


def _make_mode_payload(
    *,
    headline: str,
    summary_label: str,
    primary_value: int,
    counts: dict[str, int],
    details: list[str],
    alerts: list[dict[str, str]],
    detections: list[dict[str, Any]],
    infer_ms: int,
    decode_ms: int,
    publish_ms: int,
) -> dict[str, Any]:
    return {
        "headline": headline,
        "summary_label": summary_label,
        "primary_value": primary_value,
        "counts": counts,
        "details": [line for line in details if line],
        "alerts": alerts,
        "detections": detections,
        "faces": [],
        "infer_ms": infer_ms,
        "decode_ms": decode_ms,
        "publish_ms": publish_ms,
    }


def format_ai_result_for_mode(
    mode: str,
    ai_result: dict[str, Any],
    frame_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized_mode = _normalize_label(mode)
    detections = _sorted_detections(ai_result)
    width = int(frame_payload.get("width") or 0) if frame_payload else 0
    counts = _counts_for_detections(detections)
    infer_ms = int(ai_result.get("infer_ms", 0))
    decode_ms = int(ai_result.get("decode_ms", 0))
    publish_ms = int(ai_result.get("publish_ms", 4))
    source = str(ai_result.get("source") or "YOLO26")

    if normalized_mode == "traffic_count":
        vehicles = _vehicle_detections(detections)
        vehicle_counts = _counts_for_detections(vehicles)
        directional = _directional_counts(vehicles, width)
        total = sum(vehicle_counts.values())
        headline = f"{total} vehicles in lane view" if total else "Traffic lane clear"
        details = [
            _inline_counts(vehicle_counts, ("car", "motorbike", "truck", "bus", "bicycle")),
            f"Left {directional['left']} | Ahead {directional['ahead']} | Right {directional['right']}",
            "YOLO26 vehicle watch",
            source.replace("scene_monitor:", "YOLO26 "),
        ]
        alerts = [
            {
                "code": "traffic_live" if total else "traffic_clear",
                "label": "vehicle flow active" if total else "lane looks clear",
            }
        ]
        counts_payload = dict(vehicle_counts)
        counts_payload.update(
            {
                "left": directional["left"],
                "ahead": directional["ahead"],
                "right": directional["right"],
                "vehicle_total": total,
            }
        )
        return _make_mode_payload(
            headline=headline,
            summary_label="vehicle",
            primary_value=total,
            counts=counts_payload,
            details=details,
            alerts=alerts,
            detections=vehicles,
            infer_ms=infer_ms,
            decode_ms=decode_ms,
            publish_ms=publish_ms,
        )

    if normalized_mode == "focus_bubble":
        focus = _pick_priority_detection(detections)
        if focus is None:
            return _make_mode_payload(
                headline="Focus bubble waiting",
                summary_label="focus",
                primary_value=0,
                counts={"focus": 0},
                details=["No strong object locked", "Bubble wakes when something stands out", source.replace("scene_monitor:", "YOLO26 ")],
                alerts=[{"code": "focus_waiting", "label": "quiet focus"}],
                detections=[],
                infer_ms=infer_ms,
                decode_ms=decode_ms,
                publish_ms=publish_ms,
            )
        x1, _, x2, _ = focus["bbox"]
        zone = _zone_name(_zone_index((x1 + x2) * 0.5, width))
        same_label_count = counts.get(str(focus["label"]), 1)
        return _make_mode_payload(
            headline=f"{_humanize_label(str(focus['label']))} {zone}",
            summary_label=str(focus["label"]),
            primary_value=same_label_count,
            counts={
                str(focus["label"]): same_label_count,
                "focus": 1,
                zone: 1,
            },
            details=[
                f"Focused {_humanize_label(str(focus['label']))} on {zone}",
                _inline_counts(counts, ("person", "bag", "car", "motorbike", "truck")),
                source.replace("scene_monitor:", "YOLO26 "),
            ],
            alerts=[{"code": "focus_lock", "label": f"{_humanize_label(str(focus['label']))} locked"}],
            detections=[focus],
            infer_ms=infer_ms,
            decode_ms=decode_ms,
            publish_ms=publish_ms,
        )

    if normalized_mode == "ar_radar":
        by_zone = _top_by_zone(detections, width)
        directional = _directional_counts(detections, width)
        details = []
        for zone in ("left", "ahead", "right"):
            pick = by_zone.get(zone)
            if pick is None:
                details.append(f"{zone.title()}: Clear")
            else:
                details.append(f"{zone.title()}: {_humanize_label(str(pick['label']))}")
        details.append(source.replace("scene_monitor:", "YOLO26 "))
        counts_payload = dict(counts)
        counts_payload.update(directional)
        return _make_mode_payload(
            headline="AR radar live",
            summary_label="objects",
            primary_value=sum(directional.values()),
            counts=counts_payload,
            details=details,
            alerts=[{"code": "radar_live", "label": "peripheral scan active"}],
            detections=list(by_zone.values()) if by_zone else detections[:3],
            infer_ms=infer_ms,
            decode_ms=decode_ms,
            publish_ms=publish_ms,
        )

    if normalized_mode == "alert_burst":
        alert_pick = _important_alert_detection(detections, width)
        if alert_pick is None:
            return _make_mode_payload(
                headline="Quiet scene",
                summary_label="quiet",
                primary_value=0,
                counts={"quiet": 1},
                details=["Monitoring quietly", "", source.replace("scene_monitor:", "YOLO26 ")],
                alerts=[{"code": "quiet_scene", "label": "nothing urgent"}],
                detections=[],
                infer_ms=infer_ms,
                decode_ms=decode_ms,
                publish_ms=publish_ms,
            )
        zone = str(alert_pick["zone"])
        label = _humanize_label(str(alert_pick["label"]))
        return _make_mode_payload(
            headline=f"{label} {zone}",
            summary_label=str(alert_pick["label"]),
            primary_value=1,
            counts={str(alert_pick["label"]): 1, zone: 1},
            details=[f"Alert burst: {label} on {zone}", _inline_counts(counts, ("person", "car", "motorbike", "truck", "bag")), source.replace("scene_monitor:", "YOLO26 ")],
            alerts=[{"code": "burst_alert", "label": f"{label} {zone}"}],
            detections=[alert_pick],
            infer_ms=infer_ms,
            decode_ms=decode_ms,
            publish_ms=publish_ms,
        )

    if normalized_mode == "visual_assistant":
        lead = _important_alert_detection(detections, width)
        directional = _directional_counts(detections, width)
        tags = []
        for zone in ("left", "ahead", "right"):
            zone_pick = _top_by_zone(detections, width).get(zone)
            if zone_pick is not None:
                tags.append(f"{zone.title()} {_humanize_label(str(zone_pick['label']))}")
        if lead is None:
            headline = "Scene looks clear"
        else:
            headline = f"{_humanize_label(str(lead['label']))} {lead['zone']}"
        counts_payload = dict(counts)
        counts_payload.update(directional)
        return _make_mode_payload(
            headline=headline,
            summary_label=str(lead["label"]) if lead is not None else "watching",
            primary_value=sum(counts.values()),
            counts=counts_payload,
            details=[
                _inline_counts(counts, ("person", "bag", "car", "motorbike", "truck", "bus")),
                " | ".join(tags[:3]) if tags else "No priority object yet",
                source.replace("scene_monitor:", "YOLO26 "),
            ],
            alerts=[{"code": "assistant_live", "label": headline.lower()}],
            detections=detections[:4],
            infer_ms=infer_ms,
            decode_ms=decode_ms,
            publish_ms=publish_ms,
        )

    scene_counts = dict(counts)
    scene_counts.update(_directional_counts(detections, width))
    return _make_mode_payload(
        headline=str(ai_result.get("headline") or "Scene monitor active"),
        summary_label=str(ai_result.get("summary_label") or "watching"),
        primary_value=int(ai_result.get("primary_value", 0)),
        counts=scene_counts,
        details=[str(line) for line in ai_result.get("details", []) if str(line).strip()],
        alerts=[
            {"code": str(alert.get("code") or "scene_alert"), "label": str(alert.get("label") or "scene active")}
            for alert in ai_result.get("alerts", [])
            if isinstance(alert, dict)
        ] or [{"code": "scene_live", "label": "scene live"}],
        detections=detections,
        infer_ms=infer_ms,
        decode_ms=decode_ms,
        publish_ms=publish_ms,
    )


def _rotation_normalized(rotation_degrees: int) -> int:
    return ((rotation_degrees % 360) + 360) % 360


def _rotate_bgr_frame(frame_bytes: bytes, width: int, height: int, rotation_degrees: int) -> tuple[bytes, int, int]:
    rotation = _rotation_normalized(rotation_degrees)
    if rotation == 0:
        return frame_bytes, width, height

    import cv2  # type: ignore
    import numpy as np  # type: ignore

    frame = np.frombuffer(frame_bytes, dtype=np.uint8).reshape((height, width, 3))
    if rotation == 90:
        rotated = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    elif rotation == 180:
        rotated = cv2.rotate(frame, cv2.ROTATE_180)
    elif rotation == 270:
        rotated = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    else:
        return frame_bytes, width, height
    return rotated.tobytes(), int(rotated.shape[1]), int(rotated.shape[0])


def _frame_payload_for_ai(session_id: str) -> dict[str, Any] | None:
    latest_frame = latest_frames.get(session_id)
    if latest_frame is None:
        return None
    session = sessions.get(session_id)
    rotation_degrees = session.rotation_degrees if session is not None else 0
    bgr_bytes, width, height = _rotate_bgr_frame(
        latest_frame.bgr_bytes,
        latest_frame.width,
        latest_frame.height,
        rotation_degrees,
    )
    if bgr_bytes is latest_frame.bgr_bytes:
        jpeg_bytes = latest_frame.jpeg_bytes
    else:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        frame = np.frombuffer(bgr_bytes, dtype=np.uint8).reshape((height, width, 3))
        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), PREVIEW_JPEG_QUALITY],
        )
        jpeg_bytes = encoded.tobytes() if ok else latest_frame.jpeg_bytes
    return {
        "width": width,
        "height": height,
        "bgr_bytes": bgr_bytes,
        "jpeg_bytes": jpeg_bytes,
        "sequence": latest_frame.sequence,
        "timestampMs": latest_frame.timestamp_ms,
        "rotationDegrees": rotation_degrees,
    }


def make_debug_result(session: SessionState) -> dict[str, Any]:
    session.result_count += 1
    step = session.result_count % 12
    capture_to_receive_ms = estimate_capture_to_receive_ms(session)
    decode_ms = 6 + (step % 3)
    infer_ms = 18 + (step % 4) * 4
    publish_ms = 4 + (step % 2)
    end_to_end_ms = capture_to_receive_ms + decode_ms + infer_ms + publish_ms

    people_cycle = [1, 1, 2, 2, 3, 4, 4, 3, 3, 2, 2, 1]
    vehicle_cycle = [0, 0, 1, 1, 1, 2, 2, 2, 1, 1, 0, 0]
    bag_cycle = [0, 0, 1, 1, 0, 1, 2, 1, 1, 0, 0, 0]
    confidence_cycle = [0.82, 0.86, 0.88, 0.91, 0.93, 0.89]
    people_count = people_cycle[step]
    vehicle_count = vehicle_cycle[step]
    bag_count = bag_cycle[step]
    face_name = ["", "", "Nguyen Nhat", "Nguyen Nhat", "", "", "Tran Lan", "Tran Lan", "", "", "", ""][step]
    face_confidence = confidence_cycle[step % len(confidence_cycle)]

    headline = "Jetson AI waiting for video"
    summary_label = "frames_ingested"
    primary_value = session.video_frames
    counts: dict[str, Any] = {
        "videoFrames": session.video_frames,
        "keyframes": session.video_keyframes,
    }
    details = ["Select a mode on the glasses to wake Jetson AI."]
    alerts = [
        {
            "code": "stream_waiting",
            "label": "waiting for video ingest",
        }
    ]
    faces: list[dict[str, Any]] = []

    if session.mode == "standby":
        headline = "Jetson ready"
        summary_label = "mode_ready"
        primary_value = 0
        counts = {"videoFrames": session.video_frames}
        details = [
            "Chon tac vu de bat dau.",
            "Model nang dang cho kich hoat.",
        ]
        alerts = [
            {
                "code": "mode_idle",
                "label": "waiting for mode selection",
            }
        ]
    elif session.video_connected:
        if session.mode in ("face_mode", "face_memory"):
            matched_faces = 1 if face_name else 0
            headline = "Face memory active"
            summary_label = "matched_faces"
            primary_value = matched_faces
            counts = {
                "trackedFace": 1 if people_count > 0 else 0,
                "matchedFace": matched_faces,
                "watchlist": 2,
            }
            if face_name:
                details = [
                    "34 • kien truc su",
                    "anh ho | gap tuan truoc",
                    "thich noi ve smart home va camera AI",
                ]
                alerts = [
                    {
                        "code": "face_match",
                        "label": f"matched {face_name}",
                    }
                ]
                faces = [
                    {
                        "trackId": f"face_{step}",
                        "matchLabel": face_name,
                        "matchScore": round(face_confidence, 2),
                        "confidence": round(face_confidence + 0.03, 2),
                        "age": 34,
                        "job": "kien truc su",
                        "relationship": "anh ho",
                        "lastSeen": "tuan truoc",
                        "note": "thich noi ve smart home va camera AI",
                    }
                ]
            else:
                details = [
                    "Dang quet nguoi quen trong camera feed.",
                    "Thong tin ngan se hien o day khi co match.",
                ]
                alerts = [
                    {
                        "code": "face_scan",
                        "label": "scanning faces",
                    }
                ]
        elif session.mode in ("vehicle_count", "traffic_count"):
            headline = "Traffic count active"
            summary_label = "vehicle"
            total_count = vehicle_count + (1 if step >= 6 else 0)
            primary_value = total_count
            counts = {
                "total": total_count,
                "car": vehicle_count,
                "motorbike": max(0, vehicle_count - 1),
                "truck": 1 if vehicle_count >= 2 else 0,
                "line": 1,
            }
            details = [
                "Northbound line active",
                f"Car {vehicle_count} | Bike {max(0, vehicle_count - 1)} | Truck {1 if vehicle_count >= 2 else 0}",
            ]
            alerts = [
                {
                    "code": "loading_zone_busy" if vehicle_count >= 2 else "lane_clear",
                    "label": "loading zone busy" if vehicle_count >= 2 else "lane clear",
                }
            ]
        elif session.mode in ("visual_assistant",):
            headline = "Person ahead"
            summary_label = "person"
            primary_value = people_count
            counts = {
                "person": people_count,
                "bag": bag_count,
                "vehicle": vehicle_count,
                "left": 1 if bag_count else 0,
                "ahead": people_count,
                "right": vehicle_count,
            }
            details = [
                f"People {people_count} | Bag {bag_count} | Vehicle {vehicle_count}",
                "Left Bag | Ahead Person | Right Vehicle",
                "YOLO26 assistant shell",
            ]
            alerts = [{"code": "assistant_live", "label": "person ahead"}]
        elif session.mode in ("focus_bubble",):
            headline = "Person ahead"
            summary_label = "person"
            primary_value = people_count
            counts = {"person": people_count, "focus": 1, "ahead": 1}
            details = [
                "Focused Person on ahead",
                "Bubble waits for strongest object",
                "YOLO26 focus shell",
            ]
            alerts = [{"code": "focus_lock", "label": "person locked"}]
        elif session.mode in ("ar_radar",):
            headline = "AR radar live"
            summary_label = "objects"
            primary_value = people_count + vehicle_count + bag_count
            counts = {
                "left": bag_count,
                "ahead": people_count,
                "right": vehicle_count,
                "person": people_count,
                "vehicle": vehicle_count,
                "bag": bag_count,
            }
            details = [
                "Left: Bag",
                "Ahead: Person",
                "Right: Vehicle",
                "YOLO26 radar shell",
            ]
            alerts = [{"code": "radar_live", "label": "peripheral scan active"}]
        elif session.mode in ("alert_burst",):
            headline = "Vehicle right" if vehicle_count > 0 else "Quiet scene"
            summary_label = "alert"
            primary_value = 1 if vehicle_count > 0 else 0
            counts = {"quiet": 0 if vehicle_count > 0 else 1, "vehicle": vehicle_count}
            details = [
                "Monitoring quietly",
                "Burst only when something matters",
                "YOLO26 alert shell",
            ]
            alerts = [{"code": "burst_alert" if vehicle_count > 0 else "quiet_scene", "label": "vehicle right" if vehicle_count > 0 else "nothing urgent"}]
        elif session.mode in ("people_count", "scene_monitor", "object_count"):
            headline = "Scene monitor active"
            summary_label = "people"
            primary_value = people_count
            counts = {
                "person": people_count,
                "bag": bag_count,
                "helmet": max(0, people_count - 1),
                "vehicle": vehicle_count,
            }
            details = [
                f"People {people_count} | Bag {bag_count} | Helmet {max(0, people_count - 1)}",
                "Jetson can swap this fake mode to YOLO object mode later.",
            ]
            alerts = [
                {
                    "code": "crowd_alert" if people_count >= 4 else "zone_clear",
                    "label": "entrance crowded" if people_count >= 4 else "scene normal",
                }
            ]
        else:
            headline = "Scene monitor active"
            summary_label = "people"
            primary_value = people_count
            counts = {
                "person": people_count,
                "vehicle": vehicle_count,
                "bag": bag_count,
                "helmet": max(0, people_count - 1),
            }
            details = [
                f"People {people_count} | Vehicle {vehicle_count} | Bag {bag_count}",
                "Mode fallback is using the scene monitor shell.",
            ]
            alerts = [
                {
                    "code": "object_left" if bag_count >= 2 else "scene_stable",
                    "label": "possible unattended object" if bag_count >= 2 else "scene stable",
                }
            ]

    return {
        "type": "vision_result",
        "version": 1,
        "sessionId": session.session_id,
        "mode": session.mode,
        "headline": headline,
        "timestampMs": now_ms(),
        "frameSeq": session.last_video_seq,
        "latency": {
            "captureToReceiveMs": capture_to_receive_ms,
            "decodeMs": decode_ms,
            "inferMs": infer_ms,
            "publishMs": publish_ms,
            "endToEndMs": end_to_end_ms,
        },
        "summary": {
            "primaryValue": primary_value,
            "label": summary_label,
        },
        "counts": counts,
        "details": details,
        "alerts": alerts,
        "detections": [],
        "faces": faces,
    }


def make_node_telemetry(session: SessionState) -> dict[str, Any]:
    return {
        "type": "node_telemetry",
        "version": 1,
        "sessionId": session.session_id,
        "timestampMs": now_ms(),
        "rxFps": round(session.rx_fps, 2),
        "decodeMs": 0,
        "gpuPercent": 0,
        "cpuPercent": 0,
        "ramMb": 0,
        "videoFrames": session.video_frames,
        "videoBytes": session.video_bytes,
        "audioPackets": session.audio_packets,
        "audioBytes": session.audio_bytes,
        "activePipelines": AI_RUNTIME.loaded_pipelines(session.mode),
    }


def make_speech_state(
    session: SessionState,
    *,
    listening: bool,
    state_label: str,
    task_label: str | None = None,
    transcript_hint: str | None = None,
) -> dict[str, Any]:
    return {
        "type": "speech_state",
        "version": 1,
        "sessionId": session.session_id,
        "timestampMs": now_ms(),
        "listening": listening,
        "stateLabel": state_label,
        "taskLabel": task_label,
        "transcriptHint": transcript_hint,
    }


def _next_scene_id(session: SessionState) -> str:
    return f"scene_{session.result_count}_{now_ms()}"


def _read_target_hud_state(session: SessionState) -> TargetHudState:
    return TargetHudState(
        last_signature=session.last_target_hud_signature,
        last_sent_ms=session.last_target_hud_sent_ms,
        last_positive_scene=session.last_target_positive_scene,
        last_positive_ms=session.last_target_positive_ms,
        last_positive_query=session.last_target_positive_query,
    )


def _write_target_hud_state(session: SessionState, state: TargetHudState) -> None:
    session.last_target_hud_signature = state.last_signature
    session.last_target_hud_sent_ms = state.last_sent_ms
    session.last_target_positive_scene = state.last_positive_scene
    session.last_target_positive_ms = state.last_positive_ms
    session.last_target_positive_query = state.last_positive_query


def make_hud_scene(
    session: SessionState,
    *,
    task_chip: str | None = None,
    mic_chip: str | None = None,
    answer_text: str | None = None,
    status_text: str | None = None,
    gallery_labels: list[str] | None = None,
    gallery_items: list[dict[str, Any]] | None = None,
    direction_hint: str | None = None,
    target_marker: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_hud_scene_payload(
        session_id=session.session_id,
        scene_id=_next_scene_id(session),
        task_chip=task_chip,
        mic_chip=mic_chip,
        answer_text=answer_text,
        status_text=status_text,
        gallery_labels=gallery_labels,
        gallery_items=gallery_items,
        direction_hint=direction_hint,
        target_marker=target_marker,
    )


def make_target_search_hud_scene(
    session: SessionState,
    *,
    detections: list[dict[str, Any]],
    frame_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    query = (session.active_target_query or "").strip()
    if not query:
        return None
    gallery_items = _build_target_gallery_items(session, detections, frame_payload)
    direction_hint = None
    if gallery_items:
        direction_hint = _build_target_direction_hint(session, detections, frame_payload)
    return build_target_search_hud_scene_payload(
        session_id=session.session_id,
        scene_id=_next_scene_id(session),
        query=query,
        selected_target_track_id=session.selected_target_track_id,
        selected_target_visible=session.selected_target_visible,
        selected_target_label=session.selected_target_label,
        gallery_items=gallery_items,
        direction_hint=direction_hint,
        target_marker=_build_target_marker_component(session, detections, frame_payload),
    )


def queue_target_search_hud_scene(
    session: SessionState,
    *,
    detections: list[dict[str, Any]],
    frame_payload: dict[str, Any] | None,
) -> None:
    payload = make_target_search_hud_scene(session, detections=detections, frame_payload=frame_payload)
    evaluation = evaluate_target_hud_scene(
        state=_read_target_hud_state(session),
        query=session.active_target_query,
        payload=payload,
        session_id=session.session_id,
        hold_scene_id=_next_scene_id(session),
        now_ms=now_ms(),
        candidate_grace_ms=HUD_TARGET_CANDIDATE_GRACE_MS,
        scene_interval_ms=HUD_TARGET_SCENE_INTERVAL_MS,
    )
    _write_target_hud_state(session, evaluation.next_state)
    if evaluation.emit_payload is None:
        return
    queue_control_event(session, evaluation.emit_payload)
    if evaluation.emit_log_payload is not None:
        append_session_log(session, "target_search_hud_queued", evaluation.emit_log_payload)


def _candidate_display_label(item: dict[str, Any]) -> str:
    label = _normalize_label(str(item.get("label") or "object"))
    track_id = str(item.get("trackId") or "").strip()
    if label == "person":
        return f"Nguoi {track_id}" if track_id else "Nguoi"
    humanized = _humanize_label(label)
    return f"{humanized} {track_id}".strip() if track_id else humanized


def _candidate_summary_text(item: dict[str, Any], width: int) -> str:
    zone = _candidate_zone(item, width)
    confidence = float(item.get("confidence") or 0.0)
    return f"{_candidate_display_label(item)} | {zone} | {confidence:.2f}"


def _candidate_image_bundle(item: dict[str, Any], frame_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    config_max_side = int(_voice_config_value("openaiVisionCropMaxSidePx", 512) or 512)
    quality = max(55, min(90, PREVIEW_JPEG_QUALITY))
    bbox = item.get("bbox") if isinstance(item.get("bbox"), list) else None
    if not isinstance(bbox, list) or len(bbox) != 4:
        return []
    images: list[dict[str, Any]] = []
    tight = _encode_vision_crop_jpeg(
        frame_payload,
        bbox,
        pad_x_ratio=0.06,
        pad_y_ratio=0.06,
        max_side=config_max_side,
        quality=quality,
    )
    if tight:
        images.append({"label": "tight_crop", "mimeType": "image/jpeg", "imageB64": tight})
    context = _encode_vision_crop_jpeg(
        frame_payload,
        bbox,
        pad_x_ratio=0.22,
        pad_y_ratio=0.18,
        max_side=config_max_side,
        quality=quality,
    )
    if context:
        images.append({"label": "context_crop", "mimeType": "image/jpeg", "imageB64": context})
    return images


def _selected_target_for_session(
    session: SessionState,
    detections: list[dict[str, Any]],
    frame_payload: dict[str, Any] | None,
    *,
    query: str | None = None,
    selected_track_id: str | None = None,
) -> dict[str, Any] | None:
    width = int(frame_payload.get("width") or 0) if frame_payload else 0
    candidates = _target_candidates_for_query(session, detections, query, frame_width=width)
    wanted_track_id = str(selected_track_id or session.selected_target_track_id or "").strip()
    if wanted_track_id:
        selected = next(
            (item for item in candidates if str(item.get("trackId") or "") == wanted_track_id),
            None,
        )
    else:
        selected = candidates[0] if candidates else None
    if selected is None:
        return None
    evidence_images = _candidate_image_bundle(selected, frame_payload)
    full_frame = _encode_full_frame_jpeg(
        frame_payload,
        max_side=max(640, int(_voice_config_value("openaiVisionCropMaxSidePx", 512) or 512)),
        quality=max(55, min(90, PREVIEW_JPEG_QUALITY)),
    )
    if full_frame:
        evidence_images.append({"label": "full_frame", "mimeType": "image/jpeg", "imageB64": full_frame})
    return {
        "trackId": str(selected.get("trackId") or ""),
        "label": _candidate_display_label(selected),
        "summary": _candidate_summary_text(selected, width),
        "zone": _candidate_zone(selected, width),
        "confidence": round(float(selected.get("confidence") or 0.0), 3),
        "bbox": selected.get("bbox") or [],
        "evidenceImages": evidence_images,
    }


def _shadow_session(session_id: str) -> SessionState:
    return SessionState(session_id=session_id, device_id="", app_version="")


def vision_skill_context_for_session(
    session_id: str,
    target_query: str | None = None,
    selected_track_id: str | None = None,
) -> dict[str, Any]:
    session = sessions.get(session_id)
    ai_result = latest_ai_results.get(session_id) or {}
    detections = _sorted_detections(ai_result)
    frame_payload = _frame_payload_for_ai(session_id)
    frame_width = int(frame_payload.get("width") or 0) if frame_payload else 0
    owner = session if session is not None else _shadow_session(session_id)
    effective_query = str(
        target_query
        or (session.active_target_query if session is not None else "")
        or (session.selected_target_query if session is not None else "")
        or ""
    ).strip()
    candidates = _target_candidates_for_query(
        owner,
        detections,
        effective_query,
        frame_width=frame_width,
    )
    candidate_payload: list[dict[str, Any]] = []
    max_candidates = max(1, int(_voice_config_value("openaiVisionMaxCandidates", 3) or 3))
    for item in candidates[:max_candidates]:
        candidate_payload.append(
            {
                "trackId": str(item.get("trackId") or ""),
                "label": _normalize_label(str(item.get("label") or "object")),
                "displayLabel": _candidate_display_label(item),
                "summary": _candidate_summary_text(item, frame_width),
                "zone": _candidate_zone(item, frame_width),
                "confidence": round(float(item.get("confidence") or 0.0), 3),
                "bbox": item.get("bbox") or [],
                "candidateImages": _candidate_image_bundle(item, frame_payload),
            }
        )
    selected_target = None
    if session is not None:
        selected_target = _selected_target_for_session(
            session,
            detections,
            frame_payload,
            query=effective_query,
            selected_track_id=selected_track_id,
        )
    return {
        "sessionId": session_id,
        "summary": str(ai_result.get("headline") or "Scene live"),
        "headline": str(ai_result.get("headline") or "Scene live"),
        "mode": session.mode if session is not None else DEFAULT_MODE,
        "targetQuery": effective_query or None,
        "candidates": candidate_payload,
        "selectedTarget": selected_target,
    }


def scene_context_for_session(session_id: str) -> dict[str, Any]:
    session = sessions.get(session_id)
    ai_result = latest_ai_results.get(session_id) or {}
    counts = ai_result.get("counts") if isinstance(ai_result.get("counts"), dict) else {}
    detections = ai_result.get("detections") if isinstance(ai_result.get("detections"), list) else []
    counts_inline = " | ".join(
        f"{_humanize_label(str(key))} {int(value)}"
        for key, value in list(counts.items())[:5]
        if isinstance(value, (int, float))
    )
    top_labels: list[str] = []
    for detection in detections[:6]:
        if not isinstance(detection, dict):
            continue
        label = str(detection.get("label") or "").strip()
        if not label or label in top_labels:
            continue
        top_labels.append(label)
    summary_parts = [
        str(ai_result.get("headline") or "Scene live"),
        counts_inline,
    ]
    summary = ". ".join(part for part in summary_parts if part)
    frame_payload = _frame_payload_for_ai(session_id)
    frame_width = int(frame_payload.get("width") or 0) if frame_payload else 0
    owner = session if session is not None else _shadow_session(session_id)
    candidate_preview = [
        {
            "trackId": str(item.get("trackId") or ""),
            "label": _normalize_label(str(item.get("label") or "object")),
            "zone": _candidate_zone(item, frame_width),
            "confidence": round(float(item.get("confidence") or 0.0), 3),
        }
        for item in _target_candidates_for_query(
            owner,
            _sorted_detections(ai_result),
            session.active_target_query if session is not None else None,
            frame_width=frame_width,
        )[:4]
    ]
    return {
        "sessionId": session_id,
        "mode": session.mode if session is not None else DEFAULT_MODE,
        "summary": summary or "Scene live",
        "headline": str(ai_result.get("headline") or "Scene live"),
        "countsInline": counts_inline,
        "counts": counts,
        "detections": detections,
        "topLabels": top_labels,
        "targetQuery": session.active_target_query if session is not None else None,
        "selectedTarget": (
            {
                "trackId": session.selected_target_track_id,
                "label": session.selected_target_label,
                "summary": session.selected_target_summary,
                "query": session.selected_target_query,
                "visible": session.selected_target_visible,
                "updatedMs": session.selected_target_updated_ms,
            }
            if session is not None and (session.selected_target_track_id or session.selected_target_label)
            else None
        ),
        "targetCandidates": candidate_preview,
    }


def apply_voice_action(payload: dict[str, Any]) -> None:
    session_id = str(payload.get("session_id") or payload.get("sessionId") or "")
    session = sessions.get(session_id)
    if session is None:
        return

    transcript = str(payload.get("transcript") or "").strip()
    intent = str(payload.get("intent") or "assistant_query")
    answer = str(payload.get("answer") or "").strip()
    status_text = str(payload.get("status_text") or payload.get("statusText") or "").strip()
    target_query = str(payload.get("target_query") or payload.get("targetQuery") or "").strip() or None
    requested_mode = str(payload.get("mode") or "").strip() or None
    confidence = float(payload.get("confidence") or 0.0)
    selected_track_key_present = "selectedTrackId" in payload or "selected_track_id" in payload
    selected_track_id = str(payload.get("selected_track_id") or payload.get("selectedTrackId") or "").strip()
    selected_target_label = str(payload.get("selected_target_label") or payload.get("selectedTargetLabel") or "").strip()
    selected_target_summary = str(
        payload.get("selected_target_summary") or payload.get("selectedTargetSummary") or ""
    ).strip()
    previous_selected_track_id = session.selected_target_track_id

    session.latest_voice_command = {
        "timestampMs": int(payload.get("timestamp_ms") or payload.get("timestampMs") or now_ms()),
        "transcript": transcript,
        "intent": intent,
        "answer": answer,
        "statusText": status_text,
        "targetQuery": target_query,
        "mode": requested_mode,
        "confidence": confidence,
        "selectedTrackId": selected_track_id,
        "selectedTargetLabel": selected_target_label,
        "selectedTargetSummary": selected_target_summary,
    }
    previous_target_query = session.active_target_query
    session.active_target_query = target_query
    if target_query != previous_target_query:
        _write_target_hud_state(
            session,
            reset_target_hud_positive_state(_read_target_hud_state(session)),
        )
        if target_query:
            session.selected_target_query = target_query
    if selected_track_key_present:
        session.selected_target_track_id = selected_track_id
        session.selected_target_label = selected_target_label
        session.selected_target_summary = selected_target_summary
        session.selected_target_query = target_query or session.selected_target_query
        session.selected_target_updated_ms = now_ms()
    elif intent == "target_search" and target_query and target_query != previous_target_query:
        session.selected_target_track_id = ""
        session.selected_target_label = ""
        session.selected_target_summary = ""
        session.selected_target_query = target_query
        session.selected_target_updated_ms = 0
    if not target_query and selected_track_key_present and not selected_track_id:
        session.selected_target_query = ""
        session.selected_target_visible = False
    if selected_track_key_present and previous_selected_track_id != session.selected_target_track_id:
        append_session_log(
            session,
            "selected_target_updated",
            {
                "trackId": session.selected_target_track_id,
                "label": session.selected_target_label,
                "summary": session.selected_target_summary,
                "query": session.selected_target_query,
            },
        )

    if requested_mode and requested_mode != session.mode:
        session.mode = requested_mode
        append_session_log(
            session,
            "voice_mode_change",
            {"mode": requested_mode, "intent": intent, "targetQuery": target_query},
        )
        queue_control_event(
            session,
            {
                "type": "mode_state",
                "version": 1,
                "sessionId": session.session_id,
                "mode": session.mode,
                **AI_RUNTIME.mode_state(session.mode),
            },
        )

    refresh_preview_for_session(session, reason="voice_action")

    if target_query:
        task_chip = f"Tim: {target_query[:22]}"
    elif requested_mode:
        task_chip = requested_mode.replace("_", " ")
    elif intent == "scene_query":
        task_chip = "scene command"
    elif intent == "transcript_only":
        task_chip = "voice command"
    else:
        task_chip = intent.replace("_", " ")
    listening = bool(session.audio_connected)
    speech_payload = make_speech_state(
        session,
        listening=listening,
        state_label="routed" if (requested_mode or target_query or status_text or answer) else "heard",
        task_label=task_chip,
        transcript_hint=None,
    )
    queue_control_event(session, speech_payload)
    if intent == "target_search" and target_query:
        placeholder_scene = make_hud_scene(
            session,
            task_chip=f"Tim: {target_query[:22]}",
            mic_chip="target search",
            answer_text=answer or None,
            status_text=status_text or f"Dang quet {target_query[:20]}",
            direction_hint="Dang quet khung hinh",
        )
        queue_control_event(session, placeholder_scene)
        append_session_log(
            session,
            "target_search_placeholder_queued",
            {
                "query": target_query,
                "sceneId": placeholder_scene.get("sceneId"),
            },
        )
        return

    if requested_mode or status_text or answer:
        queue_control_event(
            session,
            make_hud_scene(
                session,
                task_chip=task_chip,
                mic_chip="always on" if session.audio_connected else "audio idle",
                answer_text=answer or None,
                status_text=status_text or ("Lenh da duoc chuyen toi Jetson." if not answer else None),
            ),
        )


def apply_voice_speech_update(payload: dict[str, Any]) -> None:
    session_id = str(payload.get("sessionId") or payload.get("session_id") or "")
    session = sessions.get(session_id)
    if session is None:
        return

    speech_payload = make_speech_state(
        session,
        listening=bool(payload.get("listening", True)),
        state_label=str(payload.get("stateLabel") or "listening"),
        task_label=str(payload.get("taskLabel") or "voice live").strip() or "voice live",
        transcript_hint=str(payload.get("transcriptHint") or "").strip() or None,
    )
    queue_control_event(session, speech_payload)


def make_ai_scene_result(session: SessionState, ai_result: dict[str, Any]) -> dict[str, Any]:
    session.result_count += 1
    capture_to_receive_ms = estimate_capture_to_receive_ms(session)
    decode_ms = int(ai_result.get("decode_ms", 0))
    infer_ms = int(ai_result.get("infer_ms", 0))
    publish_ms = int(ai_result.get("publish_ms", 4))
    end_to_end_ms = capture_to_receive_ms + decode_ms + infer_ms + publish_ms
    return {
        "type": "vision_result",
        "version": 1,
        "sessionId": session.session_id,
        "mode": session.mode,
        "headline": ai_result.get("headline", "Scene monitor active"),
        "timestampMs": now_ms(),
        "frameSeq": session.last_video_seq,
        "latency": {
            "captureToReceiveMs": capture_to_receive_ms,
            "decodeMs": decode_ms,
            "inferMs": infer_ms,
            "publishMs": publish_ms,
            "endToEndMs": end_to_end_ms,
        },
        "summary": {
            "primaryValue": int(ai_result.get("primary_value", 0)),
            "label": str(ai_result.get("summary_label", "watching")),
        },
        "counts": ai_result.get("counts", {}),
        "details": ai_result.get("details", []),
        "alerts": ai_result.get("alerts", []),
        "detections": ai_result.get("detections", []),
        "faces": ai_result.get("faces", []),
    }


def make_result(session: SessionState) -> dict[str, Any]:
    frame_payload = _frame_payload_for_ai(session.session_id)
    effective_mode = session.mode
    if session.active_target_query and _normalize_label(effective_mode) not in SMART_SCENE_MODES:
        effective_mode = "scene_monitor"
    ai_result = AI_RUNTIME.infer_scene_monitor(
        session_id=session.session_id,
        mode=effective_mode,
        frame_seq=session.last_video_seq,
        frame_payload=frame_payload,
    )
    if ai_result is not None:
        formatted = format_ai_result_for_mode(effective_mode, ai_result, frame_payload)
        latest_ai_results[session.session_id] = {
            "mode": effective_mode,
            "headline": formatted.get("headline", ""),
            "detections": formatted.get("detections", []),
            "counts": formatted.get("counts", {}),
            "frameSeq": session.last_video_seq,
        }
        selected_track_id = str(session.selected_target_track_id or "").strip()
        if selected_track_id:
            width = int(frame_payload.get("width") or 0) if frame_payload else 0
            selected_detection = next(
                (
                    item
                    for item in formatted.get("detections", [])
                    if isinstance(item, dict) and str(item.get("trackId") or "") == selected_track_id
                ),
                None,
            )
            session.selected_target_visible = selected_detection is not None
            if isinstance(selected_detection, dict):
                session.selected_target_label = _candidate_display_label(selected_detection)
                session.selected_target_summary = _candidate_summary_text(selected_detection, width)
                session.selected_target_updated_ms = now_ms()
        else:
            session.selected_target_visible = False
        if session.active_target_query:
            queue_target_search_hud_scene(
                session,
                detections=formatted.get("detections", []),
                frame_payload=frame_payload,
            )
        return make_ai_scene_result(session, formatted)
    latest_ai_results.pop(session.session_id, None)
    return make_debug_result(session)


def mode_result_interval_ms(mode: str) -> int:
    normalized_mode = _normalize_label(mode)
    if normalized_mode == "focus_bubble":
        return max(90, RESULT_INTERVAL_MS)
    if normalized_mode == "traffic_count":
        return max(110, RESULT_INTERVAL_MS)
    if normalized_mode == "visual_assistant":
        return max(130, RESULT_INTERVAL_MS)
    if normalized_mode == "ar_radar":
        return max(180, RESULT_INTERVAL_MS)
    if normalized_mode == "alert_burst":
        return max(220, RESULT_INTERVAL_MS)
    return RESULT_INTERVAL_MS


def session_accept_payload(session: SessionState, *, media_transport: str) -> dict[str, Any]:
    return build_session_accept_payload(
        session_id=session.session_id,
        result_interval_ms=RESULT_INTERVAL_MS,
        media_transport=media_transport,
        public_host=PUBLIC_HOST,
        media_port=MEDIA_PORT,
        aiortc_available=AIORTC_AVAILABLE,
        browser_audio_sample_rate=BROWSER_AUDIO_SAMPLE_RATE,
        browser_audio_channels=BROWSER_AUDIO_CHANNELS,
    )


CONTROL_WS_RUNTIME = SessionControlRuntime(
    session_accept_payload_provider=session_accept_payload,
    mode_state_provider=AI_RUNTIME.mode_state,
    make_hud_scene=make_hud_scene,
    make_speech_state=make_speech_state,
    make_result=make_result,
    make_node_telemetry=make_node_telemetry,
    drain_control_events=drain_control_events,
    append_session_log=append_session_log,
    result_interval_provider=mode_result_interval_ms,
    now_ms_provider=now_ms,
)


async def _handle_glasses_control_disconnect(session: SessionState) -> None:
    AI_RUNTIME.drop_session(session.session_id)
    append_session_log(session, "control_disconnected", {})


async def _handle_browser_client_hello(
    session: SessionState,
    payload: dict[str, Any],
    *,
    peer_label: str,
) -> None:
    session.preview_url = f"http://{PUBLIC_HOST}:{PORT}/preview/sessions/{session.session_id}/live.mjpg"
    append_session_log(
        session,
        "browser_client_hello",
        build_browser_client_hello_log(peer_label=peer_label, payload=payload),
    )


async def _handle_browser_extra_message(
    session: SessionState,
    websocket: WebSocket,
    message_type: str,
    payload: dict[str, Any],
    *,
    peer_label: str,
) -> bool:
    del websocket
    if message_type == "browser_media_state":
        video_active = payload.get("videoActive")
        audio_active = payload.get("audioActive")
        BROWSER_MEDIA_RUNTIME.set_browser_media_state(
            session,
            video_active=bool(video_active) if video_active is not None else None,
            audio_active=bool(audio_active) if audio_active is not None else None,
            peer_label=peer_label,
        )
        append_session_log(
            session,
            "browser_media_state",
            build_browser_media_state_log(
                peer_label=peer_label,
                video_active=session.video_connected,
                audio_active=session.audio_connected,
            ),
        )
        return True
    if message_type == "browser_client_trace":
        append_session_log(
            session,
            "browser_client_trace",
            build_browser_client_trace_log(peer_label=peer_label, payload=payload),
        )
        return True
    return False


async def _handle_browser_control_disconnect(session: SessionState, *, peer_label: str) -> None:
    await close_browser_webrtc_peer(session.session_id, reason="browser_control_disconnected")
    BROWSER_MEDIA_RUNTIME.set_browser_media_state(
        session,
        video_active=False,
        audio_active=False,
        peer_label=peer_label,
    )
    AI_RUNTIME.drop_session(session.session_id)
    append_session_log(session, "browser_control_disconnected", {"peer": peer_label})


async def ingest_video_sample(
    session: SessionState,
    header: dict[str, Any],
    payload: bytes,
) -> None:
    sequence = int(header.get("sequence") or 0)
    is_keyframe = bool(header.get("isKeyframe"))
    is_codec_config = bool(header.get("isCodecConfig"))
    capture_timestamp_ms = int(header.get("captureTimestampMs") or 0)
    presentation_time_us = int(header.get("presentationTimeUs") or 0)
    width = int(header.get("width") or 0)
    height = int(header.get("height") or 0)
    session.rotation_degrees = int(header.get("rotationDegrees") or session.rotation_degrees or 0)

    now_monotonic = time.perf_counter()
    if session.last_video_monotonic is not None:
        delta = max(0.001, now_monotonic - session.last_video_monotonic)
        instant_fps = 1.0 / delta
        session.rx_fps = instant_fps if session.rx_fps == 0 else session.rx_fps * 0.85 + instant_fps * 0.15
    session.last_video_monotonic = now_monotonic

    session.video_frames += 1
    session.video_bytes += len(payload)
    if is_keyframe:
        session.video_keyframes += 1
    session.last_video_seq = sequence
    session.last_video_timestamp_ms = capture_timestamp_ms

    if is_codec_config and payload:
        latest_codec_config_frames[session.session_id] = payload

    current_preview = preview_processes.get(session.session_id)
    if (
        current_preview is not None
        and width > 0
        and height > 0
        and (current_preview.width != width or current_preview.height != height)
    ):
        append_session_log(
            session,
            "preview_dimensions_mismatch",
            {
                "helloWidth": current_preview.width,
                "helloHeight": current_preview.height,
                "sampleWidth": width,
                "sampleHeight": height,
                "sequence": sequence,
            },
        )
        remember_session_video_profile(
            session=session,
            width=width,
            height=height,
            target_fps=current_preview.target_fps,
            target_bitrate=current_preview.target_bitrate,
            profile_label=current_preview.profile_label,
        )
        refresh_preview_for_session(session, reason="dimensions_changed")

    if payload:
        video_archive_writer = getattr(app.state, "video_archive_writer", None)
        if video_archive_writer is not None:
            video_archive_writer.append(session.h264_path, payload)

    if payload:
        PREVIEW_RUNTIME.write_preview_payload(session, payload)

    if sequence <= 2 or is_keyframe or sequence % VIDEO_SAMPLE_LOG_INTERVAL == 0:
        append_session_log(
            session,
            "video_sample",
            {
                "sequence": sequence,
                "captureTimestampMs": capture_timestamp_ms,
                "presentationTimeUs": presentation_time_us,
                "width": width,
                "height": height,
                "payloadBytes": len(payload),
                "isKeyframe": is_keyframe,
                "isCodecConfig": is_codec_config,
                "videoFrames": session.video_frames,
                "videoBytes": session.video_bytes,
            },
        )


async def handle_media_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer = writer.get_extra_info("peername")
    peer_label = f"{peer[0]}:{peer[1]}" if peer else "unknown"
    session: SessionState | None = None
    saw_video = False
    saw_audio = False

    try:
        while True:
            prelude = await reader.readexactly(FRAME_HEADER.size)
            magic, version, message_type, header_len, payload_len = FRAME_HEADER.unpack(prelude)
            if magic != FRAME_MAGIC:
                raise ValueError("invalid frame magic")
            if version != FRAME_VERSION:
                raise ValueError(f"unsupported frame version {version}")

            header_bytes = await reader.readexactly(header_len)
            header = json.loads(header_bytes.decode("utf-8")) if header_len else {}
            payload = await reader.readexactly(payload_len) if payload_len else b""

            if message_type == TYPE_HELLO:
                session = get_or_create_video_session(header)
                saw_video = True
                session.video_connected = True
                session.video_peer = peer_label
                session.last_message_at = time.time()
                width = int(header.get("width") or 0)
                height = int(header.get("height") or 0)
                target_fps = int(header.get("targetFps") or 0)
                target_bitrate = int(header.get("targetBitrate") or 0)
                profile_label = str(header.get("profileLabel") or "")
                session.rotation_degrees = int(header.get("rotationDegrees") or 0)
                remember_session_video_profile(
                    session=session,
                    width=width,
                    height=height,
                    target_fps=target_fps,
                    target_bitrate=target_bitrate,
                    profile_label=profile_label,
                )
                should_restart_preview = refresh_preview_for_session(session, reason="video_hello")
                append_session_log(
                    session,
                    "video_hello",
                    {
                        "peer": peer_label,
                        "codec": header.get("codec"),
                        "width": width,
                        "height": height,
                        "targetFps": target_fps,
                        "targetBitrate": target_bitrate,
                        "profileLabel": profile_label,
                        "rotationDegrees": session.rotation_degrees,
                        "previewRestarted": should_restart_preview,
                    },
                )
            elif message_type == TYPE_AUDIO_HELLO:
                session = session or get_or_create_video_session(header)
                saw_audio = True
                session.audio_connected = True
                session.audio_peer = peer_label
                session.last_message_at = time.time()
                append_session_log(
                    session,
                    "audio_hello",
                    {
                        "peer": peer_label,
                        "codec": header.get("codec"),
                        "sampleRateHz": header.get("sampleRateHz"),
                        "channels": header.get("channels"),
                        "bytesPerSample": header.get("bytesPerSample"),
                    },
                )
            elif message_type == TYPE_VIDEO_SAMPLE:
                session = session or get_or_create_video_session(header)
                saw_video = True
                session.video_connected = True
                session.video_peer = peer_label
                session.last_message_at = time.time()
                await ingest_video_sample(session, header, payload)
            elif message_type == TYPE_AUDIO_SAMPLE:
                session = session or get_or_create_video_session(header)
                saw_audio = True
                session.audio_connected = True
                session.audio_peer = peer_label
                session.last_message_at = time.time()
                await ingest_audio_sample(session, header, payload)
            else:
                if session is not None:
                    append_session_log(
                        session,
                        "media_unknown_message",
                        {"messageType": message_type, "payloadBytes": payload_len},
                    )
    except asyncio.IncompleteReadError:
        pass
    except Exception as error:
            if session is not None:
                session.last_error = str(error)
                append_session_log(session, "media_error", {"error": str(error), "peer": peer_label})
    finally:
        if session is not None:
            session.last_message_at = time.time()
            if saw_video:
                session.video_connected = False
                PREVIEW_RUNTIME.stop_preview_process(session, reason="media_disconnected")
                append_session_log(session, "video_disconnected", {"peer": peer_label})
            if saw_audio:
                session.audio_connected = False
                append_session_log(session, "audio_disconnected", {"peer": peer_label})
        writer.close()
        with suppress(Exception):
            await writer.wait_closed()


async def ingest_audio_sample(session: SessionState, header: dict[str, Any], payload: bytes) -> None:
    sequence = int(header.get("sequence") or 0)
    capture_timestamp_ms = int(header.get("captureTimestampMs") or 0)
    avg_abs = int(header.get("avgAbs") or 0)
    peak_abs = int(header.get("peakAbs") or 0)
    non_silent_ratio = float(header.get("nonSilentRatio") or 0.0)
    audio_source = str(header.get("audioSource") or "").strip()
    session.audio_packets += 1
    session.audio_bytes += len(payload)
    session.last_audio_timestamp_ms = capture_timestamp_ms or now_ms()
    session.latest_audio_stats = {
        **session.latest_audio_stats,
        "avgAbs": avg_abs,
        "peakAbs": peak_abs,
        "nonSilentRatio": round(non_silent_ratio, 4),
        "audioSource": audio_source or session.latest_audio_stats.get("audioSource"),
    }
    if payload:
        session.append_audio_payload(payload, max_buffer_bytes=AUDIO_RING_MAX_BYTES)
        audio_archive_writer = getattr(app.state, "audio_archive_writer", None)
        if audio_archive_writer is not None:
            audio_archive_writer.append(session.audio_path, payload)
    if sequence <= 2 or sequence % AUDIO_SAMPLE_LOG_INTERVAL == 0:
        append_session_log(
            session,
            "audio_sample",
            {
                "sequence": sequence,
                "captureTimestampMs": capture_timestamp_ms,
                "payloadBytes": len(payload),
                "audioPackets": session.audio_packets,
                "audioBytes": session.audio_bytes,
                "avgAbs": avg_abs,
                "peakAbs": peak_abs,
                "nonSilentRatio": round(non_silent_ratio, 4),
                "audioSource": audio_source,
            },
        )


@app.on_event("startup")
async def startup_event() -> None:
    global VOICE_RUNTIME
    ensure_runtime_dirs()
    app.state.media_server = await asyncio.start_server(handle_media_client, HOST, MEDIA_PORT)
    app.state.session_prune_task = asyncio.create_task(session_prune_loop())
    app.state.session_log_writer = SessionLogWriter()
    app.state.audio_archive_writer = AudioArchiveWriter(max_items=ARCHIVE_QUEUE_MAX) if ARCHIVE_AUDIO_STREAMS else None
    app.state.video_archive_writer = VideoArchiveWriter(max_items=ARCHIVE_QUEUE_MAX) if ARCHIVE_VIDEO_STREAMS else None
    VOICE_RUNTIME = VoiceOrchestrator(
        root_dir=ROOT_DIR,
        session_provider=lambda: sessions,
        scene_context_provider=scene_context_for_session,
        vision_context_provider=vision_skill_context_for_session,
        command_handler=apply_voice_action,
        speech_handler=apply_voice_speech_update,
        log_handler=lambda session_id, event, payload: append_session_log(
            sessions[session_id],
            event,
            payload,
        ) if session_id in sessions else None,
    )


@app.on_event("shutdown")
async def shutdown_event() -> None:
    global VOICE_RUNTIME
    session_prune_task = getattr(app.state, "session_prune_task", None)
    if session_prune_task is not None:
        session_prune_task.cancel()
        with suppress(asyncio.CancelledError):
            await session_prune_task
        app.state.session_prune_task = None
    media_server = getattr(app.state, "media_server", None)
    if media_server is not None:
        media_server.close()
        await media_server.wait_closed()
    peer_session_ids = BROWSER_WEBRTC_RUNTIME.session_ids
    for session_id in peer_session_ids:
        await close_browser_webrtc_peer(session_id, reason="backend_shutdown")
    await prune_stale_sessions(reason="backend_shutdown_prune")
    session_log_writer = getattr(app.state, "session_log_writer", None)
    if session_log_writer is not None:
        session_log_writer.close()
        app.state.session_log_writer = None
    audio_archive_writer = getattr(app.state, "audio_archive_writer", None)
    if audio_archive_writer is not None:
        audio_archive_writer.close()
        app.state.audio_archive_writer = None
    video_archive_writer = getattr(app.state, "video_archive_writer", None)
    if video_archive_writer is not None:
        video_archive_writer.close()
        app.state.video_archive_writer = None
    if VOICE_RUNTIME is not None:
        VOICE_RUNTIME.close()
        VOICE_RUNTIME = None


@app.get("/")
def root(request: Request) -> dict[str, Any]:
    request_host = request.headers.get("host") or f"{PUBLIC_HOST}:{PORT}"
    request_scheme = request.url.scheme or "http"
    ws_scheme = "wss" if request_scheme == "https" else "ws"
    return {
        "name": "rokid-backend-mvp",
        "version": "0.5.0",
        "ws": f"{ws_scheme}://{request_host}/ws",
        "browserWs": f"{ws_scheme}://{request_host}/ws/browser",
        "mediaIngest": {
            "transport": "tcp_split_av",
            "host": PUBLIC_HOST,
            "port": MEDIA_PORT,
        },
        "audioIngest": {
            "transport": "tcp_split_av",
            "host": PUBLIC_HOST,
            "port": MEDIA_PORT,
        },
        "preview": {
            "page": f"http://{PUBLIC_HOST}:{PORT}/preview/live",
            "latestPlaylist": (
                f"http://{PUBLIC_HOST}:{PORT}/preview/latest/index.m3u8"
                if ENABLE_HLS_PREVIEW
                else None
            ),
            "sensorDebugMjpeg": (
                f"http://{PUBLIC_HOST}:{PORT}/preview/latest/live.mjpg"
                if sensor_debug_mjpeg_enabled()
                else None
            ),
            "localEnabled": ENABLE_LOCAL_PREVIEW,
        },
        "dashboard": {
            "page": f"{request_scheme}://{request_host}/dashboard",
        },
        "simulator": {
            "page": f"{request_scheme}://{request_host}/simulator",
            "browserWs": f"{ws_scheme}://{request_host}/ws/browser",
            "webrtcOffer": f"{request_scheme}://{request_host}/api/browser/webrtc/offer",
            "webrtcEnabled": AIORTC_AVAILABLE,
        },
    }


@app.get("/health")
def health() -> dict[str, Any]:
    active_sessions = sum(1 for session in sessions.values() if session.active)
    active_video_sessions = sum(1 for session in sessions.values() if session.video_connected)
    audio_archive_writer = getattr(app.state, "audio_archive_writer", None)
    video_archive_writer = getattr(app.state, "video_archive_writer", None)
    return {
        "status": "ok",
        "service": "rokid-backend-mvp",
        "activeSessions": active_sessions,
        "activeVideoSessions": active_video_sessions,
        "totalSessions": len(sessions),
        "defaultMode": DEFAULT_MODE,
        "control": {
            "host": PUBLIC_HOST,
            "port": PORT,
            "ws": f"ws://{PUBLIC_HOST}:{PORT}/ws",
        },
        "media": {
            "transport": "tcp_split_av",
            "host": PUBLIC_HOST,
            "port": MEDIA_PORT,
        },
        "audio": {
            "transport": "tcp_split_av",
            "host": PUBLIC_HOST,
            "port": MEDIA_PORT,
        },
        "paths": {
            "logs": str(LOG_DIR),
            "streams": str(STREAM_DIR),
            "preview": str(PREVIEW_DIR),
        },
        "preview": {
            "hlsEnabled": ENABLE_HLS_PREVIEW,
            "mjpegEnabled": ENABLE_MJPEG_PREVIEW,
            "sensorDebugMjpegEnabled": sensor_debug_mjpeg_enabled(),
            "frameBusEnabled": frame_bus_runtime_enabled(),
            "frameBusForced": ENABLE_FRAME_BUS,
            "localPreviewEnabled": ENABLE_LOCAL_PREVIEW,
            "localPreviewDisplay": LOCAL_PREVIEW_DISPLAY if ENABLE_LOCAL_PREVIEW else None,
            "localPreviewMode": LOCAL_PREVIEW_MODE if ENABLE_LOCAL_PREVIEW else None,
        },
        "archive": {
            "audioEnabled": audio_archive_writer is not None,
            "videoEnabled": video_archive_writer is not None,
            "queueMax": ARCHIVE_QUEUE_MAX,
            "audio": audio_archive_writer.health() if audio_archive_writer is not None else None,
            "video": video_archive_writer.health() if video_archive_writer is not None else None,
        },
        "ai": AI_RUNTIME.health(),
        "voice": VOICE_RUNTIME.health() if VOICE_RUNTIME is not None else {"enabled": False},
        "browser": {
            "webrtcEnabled": AIORTC_AVAILABLE,
            "webrtcOfferPath": "/api/browser/webrtc/offer",
            "webrtcPeerCount": BROWSER_WEBRTC_RUNTIME.peer_count,
            "legacyMediaEnabled": False,
            "legacyMediaPolicy": "removed",
            "webrtcImportError": AIORTC_IMPORT_ERROR if not AIORTC_AVAILABLE else "",
        },
        "sessionRetentionSec": SESSION_RETENTION_SEC,
    }


@app.post("/api/browser/webrtc/offer")
async def browser_webrtc_offer(payload: dict[str, Any]) -> dict[str, Any]:
    if not AIORTC_AVAILABLE or RTCPeerConnection is None or RTCSessionDescription is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "browser_webrtc_unavailable",
                "reason": AIORTC_IMPORT_ERROR or "aiortc_not_installed",
            },
        )

    session_id = str(payload.get("sessionId") or "").strip()
    sdp = str(payload.get("sdp") or "").strip()
    offer_type = str(payload.get("type") or "").strip() or "offer"
    if not session_id or not sdp:
        raise HTTPException(status_code=400, detail={"error": "missing_offer_payload"})
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail={"error": "session_not_found", "sessionId": session_id})

    return await BROWSER_WEBRTC_RUNTIME.handle_offer(
        session,
        session_id=session_id,
        sdp=sdp,
        offer_type=offer_type,
    )


@app.post("/api/browser/trace")
async def browser_trace(payload: dict[str, Any]) -> dict[str, Any]:
    session_id = str(payload.get("sessionId") or "").strip()
    if not session_id:
        return {"ok": False, "error": "missing_session_id"}
    session = sessions.get(session_id)
    if session is None:
        return {"ok": False, "error": "session_not_found", "sessionId": session_id}
    append_session_log(
        session,
        "browser_client_trace",
        {
            "peer": "browser-http",
            "phase": payload.get("phase"),
            "detail": payload.get("detail") or {},
        },
    )
    return {"ok": True}


@app.get("/sessions")
def list_sessions() -> dict[str, Any]:
    return {"items": [session.summary() for session in sessions.values()]}


@app.get("/preview")
def preview_info() -> dict[str, Any]:
    latest_session = sessions.get(latest_preview_session_id) if latest_preview_session_id else None
    return {
        "latestSessionId": latest_preview_session_id,
        "latestPreviewPage": f"http://{PUBLIC_HOST}:{PORT}/preview/live",
        "latestPlaylist": (
            latest_session.preview_url if latest_session is not None else None
        ) if ENABLE_HLS_PREVIEW else None,
        "sensorDebugMjpeg": (
            f"http://{PUBLIC_HOST}:{PORT}/preview/latest/live.mjpg"
            if latest_session is not None and sensor_debug_mjpeg_enabled_for_session(latest_session.session_id)
            else None
        ),
        "latestMjpeg": (
            f"http://{PUBLIC_HOST}:{PORT}/preview/latest/live.mjpg"
            if latest_session is not None and sensor_debug_mjpeg_enabled_for_session(latest_session.session_id)
            else None
        ),
        "availableSessions": [
            {
                "sessionId": session.session_id,
                "previewUrl": session.preview_url if ENABLE_HLS_PREVIEW else None,
                "mjpegUrl": (
                    f"http://{PUBLIC_HOST}:{PORT}/preview/sessions/{session.session_id}/live.mjpg"
                    if sensor_debug_mjpeg_enabled_for_session(session.session_id)
                    else None
                ),
                "active": session.active,
                "videoConnected": session.video_connected,
            }
            for session in sessions.values()
            if session.preview_path
        ],
    }


@app.get("/preview/latest")
def preview_latest() -> RedirectResponse:
    if not latest_preview_session_id:
        return RedirectResponse(url="/preview/live", status_code=307)
    if ENABLE_HLS_PREVIEW:
        return RedirectResponse(
            url=f"/preview/sessions/{latest_preview_session_id}/index.m3u8",
            status_code=307,
        )
    if sensor_debug_mjpeg_enabled_for_session(latest_preview_session_id):
        return RedirectResponse(
            url=f"/preview/sessions/{latest_preview_session_id}/live.mjpg",
            status_code=307,
        )
    raise HTTPException(status_code=404, detail="Preview output is disabled")


@app.get("/preview/latest/index.m3u8")
def preview_latest_playlist() -> RedirectResponse:
    if not ENABLE_HLS_PREVIEW:
        raise HTTPException(status_code=404, detail="HLS preview is disabled")
    if not latest_preview_session_id:
        return RedirectResponse(url="/preview/live", status_code=307)
    return RedirectResponse(
        url=f"/preview/sessions/{latest_preview_session_id}/index.m3u8",
        status_code=307,
    )


@app.get("/preview/latest/live.mjpg")
def preview_latest_mjpeg() -> RedirectResponse:
    if not latest_preview_session_id:
        return RedirectResponse(url="/preview/live", status_code=307)
    if not sensor_debug_mjpeg_enabled_for_session(latest_preview_session_id):
        raise HTTPException(status_code=404, detail="Sensor debug MJPEG preview is disabled")
    return RedirectResponse(
        url=f"/preview/sessions/{latest_preview_session_id}/live.mjpg",
        status_code=307,
    )


def render_preview_jpeg(session_id: str) -> bytes | None:
    latest_frame = latest_frames.get(session_id)
    if latest_frame is None:
        return None

    frame_payload = _frame_payload_for_ai(session_id)
    if frame_payload is None:
        return None

    import cv2  # type: ignore
    import numpy as np  # type: ignore

    width = int(frame_payload["width"])
    height = int(frame_payload["height"])
    frame = np.frombuffer(frame_payload["bgr_bytes"], dtype=np.uint8).reshape((height, width, 3)).copy()
    ai_result = latest_ai_results.get(session_id)
    session = sessions.get(session_id)
    if ai_result is None or session is None or _normalize_label(session.mode) not in SMART_SCENE_MODES:
        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), PREVIEW_JPEG_QUALITY],
        )
        return encoded.tobytes() if ok else latest_frame.jpeg_bytes

    detections = ai_result.get("detections")
    if not isinstance(detections, list) or not detections:
        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), PREVIEW_JPEG_QUALITY],
        )
        return encoded.tobytes() if ok else latest_frame.jpeg_bytes

    normalized_mode = _normalize_label(session.mode)
    scale = max(1, int(min(width, height) / 480))
    thickness = max(1, scale)
    font_scale = max(0.45, min(width, height) / 900.0)
    overlay_color = {
        "traffic_count": (80, 220, 255),
        "visual_assistant": (90, 255, 180),
        "focus_bubble": (245, 220, 90),
        "ar_radar": (255, 190, 90),
        "alert_burst": (110, 110, 255),
    }.get(normalized_mode, (80, 230, 120))

    cv2.putText(
        frame,
        ai_result.get("headline") or session.mode.replace("_", " "),
        (14, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        overlay_color,
        thickness,
        cv2.LINE_AA,
    )

    draw_detections = list(detections)
    if normalized_mode == "focus_bubble":
        draw_detections = draw_detections[:1]
    elif normalized_mode == "alert_burst":
        draw_detections = draw_detections[:2]
    elif normalized_mode == "ar_radar":
        left = width // 3
        right = (width * 2) // 3
        cv2.line(frame, (left, 0), (left, height), (60, 80, 120), 1, cv2.LINE_AA)
        cv2.line(frame, (right, 0), (right, height), (60, 80, 120), 1, cv2.LINE_AA)
        for index, label in enumerate(("LEFT", "AHEAD", "RIGHT")):
            zone_x = 10 if index == 0 else (left + 10 if index == 1 else right + 10)
            cv2.putText(frame, label, (zone_x, height - 14), cv2.FONT_HERSHEY_SIMPLEX, font_scale * 0.8, overlay_color, 1, cv2.LINE_AA)

    if normalized_mode == "traffic_count":
        line_y = int(height * 0.58)
        cv2.line(frame, (int(width * 0.12), line_y), (int(width * 0.88), line_y), overlay_color, max(2, thickness), cv2.LINE_AA)

    for item in draw_detections:
        if not isinstance(item, dict):
            continue
        bbox = item.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        x1, y1, x2, y2 = [int(float(value)) for value in bbox]
        label = str(item.get("label") or "object").replace("_", " ")
        confidence = item.get("confidence")
        tag = f"{label} {float(confidence):.2f}" if isinstance(confidence, (int, float)) else label
        cv2.rectangle(frame, (x1, y1), (x2, y2), overlay_color, thickness)
        cv2.putText(
            frame,
            tag,
            (x1, max(18, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            overlay_color,
            thickness,
            cv2.LINE_AA,
        )

    ok, encoded = cv2.imencode(
        ".jpg",
        frame,
        [int(cv2.IMWRITE_JPEG_QUALITY), PREVIEW_JPEG_QUALITY],
    )
    return encoded.tobytes() if ok else latest_frame.jpeg_bytes


async def mjpeg_generator(session_id: str):
    boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
    last_sequence = -1
    while True:
        latest_frame = latest_frames.get(session_id)
        sequence = latest_frame.sequence if latest_frame is not None else -1
        if latest_frame is not None and sequence != last_sequence:
            last_sequence = sequence
            frame = render_preview_jpeg(session_id)
            if frame is None:
                await asyncio.sleep(0.03)
                continue
            yield boundary + frame + b"\r\n"
        else:
            await asyncio.sleep(0.03)


@app.get("/preview/sessions/{session_id}/live.mjpg")
async def preview_session_mjpeg(session_id: str) -> StreamingResponse:
    if not sensor_debug_mjpeg_enabled_for_session(session_id):
        raise HTTPException(status_code=404, detail="Sensor debug MJPEG preview is disabled")
    return StreamingResponse(
        mjpeg_generator(session_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/preview/live", response_class=HTMLResponse)
def preview_live_page() -> str:
    latest_label = latest_preview_session_id or "waiting"
    return build_preview_live_page(latest_label)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page() -> str:
    return build_dashboard_page()


@app.get("/simulator", response_class=HTMLResponse)
def simulator_page() -> HTMLResponse:
    return HTMLResponse(build_simulator_page(), headers=simulator_page_headers())


@app.get("/api/admin/overview")
def admin_overview() -> dict[str, Any]:
    sorted_sessions = sort_sessions_by_connected_at(list(sessions.values()))
    return {
        "health": health(),
        "preview": preview_info(),
        "sessions": [
            serialize_session(
                session,
                latest_ai_result=latest_ai_results.get(session.session_id),
                voice_context=scene_context_for_session(session.session_id),
            )
            for session in sorted_sessions
        ],
        "latestSessionId": latest_session_id(sorted_sessions),
        "voice": VOICE_RUNTIME.health() if VOICE_RUNTIME is not None else {"enabled": False},
        "voiceConfig": VOICE_RUNTIME.get_config(mask_secrets=True) if VOICE_RUNTIME is not None else {},
        "openaiConfig": VOICE_RUNTIME.get_config(mask_secrets=True) if VOICE_RUNTIME is not None else {},
    }


@app.get("/api/admin/voice/live")
def admin_voice_live() -> dict[str, Any]:
    sorted_sessions = sort_sessions_by_connected_at(list(sessions.values()))
    return {
        "latestSessionId": latest_session_id(sorted_sessions),
        "sessions": [serialize_live_voice_session(session) for session in sorted_sessions],
        "voice": VOICE_RUNTIME.health() if VOICE_RUNTIME is not None else {"enabled": False},
    }


@app.get("/api/admin/sessions/{session_id}")
def admin_session_detail(session_id: str) -> dict[str, Any]:
    session = sessions.get(session_id)
    if session is None:
        return {"error": "session_not_found", "sessionId": session_id}
    return {
        "session": serialize_session(
            session,
            latest_ai_result=latest_ai_results.get(session.session_id),
            voice_context=scene_context_for_session(session.session_id),
        ),
        "logTail": tail_session_log_lines(Path(session.log_path)),
    }


@app.post("/api/admin/sessions/{session_id}/simulate_command")
async def admin_simulate_command(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if VOICE_RUNTIME is None:
        return {"ok": False, "error": "voice_runtime_unavailable"}
    session = sessions.get(session_id)
    if session is None:
        return {"ok": False, "error": "session_not_found"}
    command = VOICE_RUNTIME.simulate_command(session_id, str(payload.get("text") or ""))
    return {"ok": True, "command": command}


@app.post("/api/admin/sessions/{session_id}/mode")
async def admin_set_mode(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    session = sessions.get(session_id)
    if session is None:
        return {"ok": False, "error": "session_not_found"}
    session.mode = str(payload.get("mode") or DEFAULT_MODE)
    append_session_log(session, "admin_mode_change", {"mode": session.mode})
    refresh_preview_for_session(session, reason="admin_mode_change")
    queue_control_event(
        session,
        {
            "type": "mode_state",
            "version": 1,
            "sessionId": session.session_id,
            "mode": session.mode,
            **AI_RUNTIME.mode_state(session.mode),
        },
    )
    return {"ok": True, "mode": session.mode}


@app.get("/api/admin/config/openai")
def admin_openai_config() -> dict[str, Any]:
    return VOICE_RUNTIME.get_config(mask_secrets=True) if VOICE_RUNTIME is not None else {}


@app.post("/api/admin/config/openai")
async def admin_update_openai_config(payload: dict[str, Any]) -> dict[str, Any]:
    if VOICE_RUNTIME is None:
        return {"ok": False, "error": "voice_runtime_unavailable"}
    return {"ok": True, "config": VOICE_RUNTIME.update_config(payload)}


@app.get("/api/admin/config/voice")
def admin_voice_config() -> dict[str, Any]:
    return VOICE_RUNTIME.get_config(mask_secrets=True) if VOICE_RUNTIME is not None else {}


@app.post("/api/admin/config/voice")
async def admin_update_voice_config(payload: dict[str, Any]) -> dict[str, Any]:
    if VOICE_RUNTIME is None:
        return {"ok": False, "error": "voice_runtime_unavailable"}
    return {"ok": True, "config": VOICE_RUNTIME.update_config(payload)}


ensure_runtime_dirs()
ADMIN_STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/preview/sessions", StaticFiles(directory=str(PREVIEW_DIR)), name="preview_sessions")
app.mount("/admin-static", StaticFiles(directory=str(ADMIN_STATIC_DIR)), name="admin_static")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await CONTROL_WS_RUNTIME.run_endpoint(
        websocket,
        create_session_from_hello=lambda payload: create_session(
            device_id=payload.get("deviceId", "unknown-device"),
            app_version=payload.get("appVersion", "0.0.0"),
            mode=payload.get("selectedMode", DEFAULT_MODE),
        ),
        media_transport="tcp_split_av",
        unknown_event_name="ack_unknown",
        disconnect_handler=_handle_glasses_control_disconnect,
    )


@app.websocket("/ws/browser")
async def browser_simulator_endpoint(websocket: WebSocket) -> None:
    peer = websocket.client
    peer_label = f"{peer.host}:{peer.port}" if peer else "browser"
    await CONTROL_WS_RUNTIME.run_endpoint(
        websocket,
        create_session_from_hello=lambda payload: create_session(
            device_id=payload.get("deviceId", "browser-simulator"),
            app_version=payload.get("appVersion", "browser-simulator/1.0"),
            mode=payload.get("selectedMode", DEFAULT_MODE),
        ),
        media_transport="browser_webrtc",
        unknown_event_name="browser_ack_unknown",
        client_hello_handler=lambda session, payload: _handle_browser_client_hello(
            session,
            payload,
            peer_label=peer_label,
        ),
        extra_message_handler=lambda session, ws, message_type, payload: _handle_browser_extra_message(
            session,
            ws,
            message_type,
            payload,
            peer_label=peer_label,
        ),
        disconnect_handler=lambda session: _handle_browser_control_disconnect(
            session,
            peer_label=peer_label,
        ),
    )
