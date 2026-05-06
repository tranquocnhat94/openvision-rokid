"""OpenVision/RV101 YOLO26 DeepStream worker.

This is the product-path YOLO26 sidecar for OpenVision live skills. It is
separate from the existing Ring/security DeepStream runtime: it owns its own
RTSP restream port, generated DeepStream configs, MQTT topic prefix, status file,
and runtime directory, then posts detections back through the OpenVision YOLO26
adapter contract.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen


FORBIDDEN_RUNTIME_MARKERS = ("ring", "security", "surveillance")
DEFAULT_BASE_URL = "http://127.0.0.1:8765"
DEFAULT_RUNTIME_SUBDIR = "deepstream_yolo26_openvision"
DEFAULT_TOPIC_PREFIX = "openvision/rv101/yolo26"
YOLO26_BRANCH = "yolo26_objects"


@dataclass(frozen=True, slots=True)
class DeepStreamYolo26WorkerSettings:
    enabled: bool = False
    jetson_base_url: str = DEFAULT_BASE_URL
    source: str = "openvision_rv101_yolo26_deepstream"
    runtime_dir: Path = field(default_factory=lambda: _default_runtime_dir())
    status_path: Path | None = None
    deepstream_app_bin: str = "deepstream-app"
    mosquitto_sub_bin: str = "mosquitto_sub"
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1884
    mqtt_topic_prefix: str = DEFAULT_TOPIC_PREFIX
    rtsp_host: str = "127.0.0.1"
    rtsp_port: int = 8785
    annotated_rtsp_enabled: bool = True
    annotated_rtsp_port: int = 8795
    annotated_udp_port: int = 5600
    annotated_bitrate: int = 4_000_000
    fake_sink_enabled: bool = False
    max_sessions: int = 1
    poll_interval_s: float = 0.25
    idle_poll_interval_s: float = 2.0
    process_grace_s: float = 2.0
    request_timeout_s: float = 2.0
    stream_width: int = 800
    stream_height: int = 600
    stream_fps: float = 15.0
    streammux_width: int = 800
    streammux_height: int = 600
    min_confidence: float = 0.35
    infer_interval: int = 0
    tracker_enabled: bool = True
    labels_path: str | None = None
    onnx_path: str | None = None
    engine_path: str | None = None
    custom_lib_path: str | None = None
    tracker_config_path: str | None = "/opt/nvidia/deepstream/deepstream/samples/configs/deepstream-app/config_tracker_NvDCF_perf.yml"
    mqtt_config_path: str | None = None


@dataclass(slots=True)
class _SessionRuntime:
    session_id: str
    command_id: str | None
    skill_id: str | None
    topic: str
    rtsp_uri: str
    config_dir: Path
    stream_width: int
    stream_height: int
    rtsp_port: int = 0
    annotated_rtsp_port: int | None = None
    annotated_udp_port: int | None = None
    deepstream_process: subprocess.Popen[Any] | None = None
    mqtt_process: subprocess.Popen[Any] | None = None
    rtsp_relay: Rv101RtspRelay | None = None
    relay_thread: threading.Thread | None = None
    annotated_rtsp_uri: str | None = None
    annotated_relay: DeepStreamAnnotatedH264Relay | None = None
    annotated_relay_thread: threading.Thread | None = None
    mqtt_thread: threading.Thread | None = None
    started_at: str = field(default_factory=lambda: _utc_now())
    started_monotonic_s: float = field(default_factory=time.monotonic)
    last_seen_at: str = field(default_factory=lambda: _utc_now())
    posted_frame_count: int = 0
    parsed_message_count: int = 0
    ignored_message_count: int = 0
    error_count: int = 0
    last_error: str | None = None
    last_payload_sample: str | None = None
    last_payload_status: str | None = None
    last_posted_frame: dict[str, Any] | None = None
    recent_post_s: list[float] = field(default_factory=list)


class JetsonApiClient:
    def __init__(self, *, base_url: str, timeout_s: float) -> None:
        self._base_url = _normalize_base_url(base_url)
        self._timeout_s = max(0.1, timeout_s)

    def list_active_live(self) -> list[dict[str, Any]]:
        payload = self._get_json("/api/media/commands")
        media_commands = payload.get("media_commands") if isinstance(payload, dict) else {}
        active = media_commands.get("active_live") if isinstance(media_commands, dict) else []
        return [item for item in active if isinstance(item, dict)]

    def post_stream_detections(self, *, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_json(f"/api/adapters/yolo26/{quote(session_id)}/stream", payload)

    def _get_json(self, path_or_url: str) -> dict[str, Any]:
        data = self._get_bytes(_absolute_url(self._base_url, path_or_url))
        return json.loads(data.decode("utf-8"))

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = Request(
            _absolute_url(self._base_url, path),
            data=data,
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self._timeout_s) as response:  # noqa: S310 - local Jetson API URL from config.
            return json.loads(response.read().decode("utf-8"))

    def _get_bytes(self, url: str) -> bytes:
        with urlopen(url, timeout=self._timeout_s) as response:  # noqa: S310 - local Jetson API URL from config.
            return response.read()


class JsonStatusWriter:
    def __init__(self, path: Path) -> None:
        self._path = path

    def write(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp_path.replace(self._path)


@dataclass(slots=True)
class _RtspRelaySample:
    payload: bytes
    metadata: dict[str, Any]
    sequence: int | None
    is_keyframe: bool
    is_codec_config: bool
    has_parameter_set: bool


class Rv101RtspRelay:
    """Tiny RTSP appsrc relay for RV101 Annex-B H.264 samples."""

    def __init__(self, *, session_id: str, port: int, fps: float) -> None:
        self.session_id = session_id
        self.port = int(port)
        self.fps = max(1.0, float(fps or 15.0))
        self._appsrc: Any | None = None
        self._loop: Any | None = None
        self._server: Any | None = None
        self._frame_index = 0
        self._lock = threading.Lock()
        self._Gst: Any | None = None
        self._GLib: Any | None = None
        self._pending_samples: list[_RtspRelaySample] = []
        self._server_ready = threading.Event()
        self._latest_codec_config: _RtspRelaySample | None = None
        self._latest_keyframe: _RtspRelaySample | None = None
        self._server_attach_id: int | None = None
        self._server_ready_at: str | None = None
        self._input_sample_count = 0
        self._pushed_sample_count = 0
        self._queued_before_appsrc_count = 0
        self._media_configure_count = 0
        self._last_flow_return: str | None = None
        self._last_error: str | None = None
        self._last_input_at: str | None = None
        self._last_pushed_at: str | None = None

    @property
    def mount_path(self) -> str:
        return f"/{_safe_segment(self.session_id)}"

    @property
    def uri(self) -> str:
        return f"rtsp://127.0.0.1:{self.port}{self.mount_path}"

    def start(self) -> None:
        try:
            import gi  # type: ignore

            gi.require_version("Gst", "1.0")
            gi.require_version("GstRtspServer", "1.0")
            from gi.repository import GLib, Gst, GstRtspServer  # type: ignore

            Gst.init(None)
            self._Gst = Gst
            self._GLib = GLib
            self._loop = GLib.MainLoop()
            server = GstRtspServer.RTSPServer()
            server.set_service(str(self.port))
            factory = GstRtspServer.RTSPMediaFactory()
            factory.set_shared(True)
            factory.set_launch(
                "( appsrc name=src is-live=true block=false format=time do-timestamp=true "
                "caps=video/x-h264,stream-format=byte-stream,alignment=au "
                "! h264parse config-interval=1 ! rtph264pay name=pay0 pt=96 )"
            )
            factory.connect("media-configure", self._on_media_configure)
            server.get_mount_points().add_factory(self.mount_path, factory)
            attach_id = server.attach(None)
            with self._lock:
                self._server = server
                self._server_attach_id = int(attach_id or 0)
                self._server_ready_at = _utc_now()
            self._server_ready.set()
            self._loop.run()
        except Exception as exc:
            with self._lock:
                self._last_error = f"server:{exc.__class__.__name__}: {exc}"[-500:]
            self._server_ready.set()
            raise

    def stop(self) -> None:
        with self._lock:
            loop = self._loop
            GLib = self._GLib
            attach_id = self._server_attach_id
            self._server = None
            self._server_attach_id = None
            self._server_ready_at = None
            self._appsrc = None
        if GLib is not None and attach_id:
            try:
                GLib.source_remove(int(attach_id))
            except Exception:
                pass
        if loop is not None:
            try:
                loop.quit()
            except Exception:
                pass

    def wait_until_ready(self, timeout_s: float) -> bool:
        if not self._server_ready.wait(max(0.05, float(timeout_s or 0.05))):
            return False
        with self._lock:
            return self._server is not None

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "uri": self.uri,
                "server_ready": self._server_ready.is_set() and self._server is not None,
                "server_attach_id": self._server_attach_id,
                "server_ready_at": self._server_ready_at,
                "appsrc_ready": self._appsrc is not None,
                "media_configure_count": self._media_configure_count,
                "input_sample_count": self._input_sample_count,
                "pushed_sample_count": self._pushed_sample_count,
                "queued_before_appsrc_count": self._queued_before_appsrc_count,
                "pending_sample_count": len(self._pending_samples),
                "has_cached_codec_config": self._latest_codec_config is not None,
                "has_cached_keyframe": self._latest_keyframe is not None,
                "last_flow_return": self._last_flow_return,
                "last_error": self._last_error,
                "last_input_at": self._last_input_at,
                "last_pushed_at": self._last_pushed_at,
            }

    def push_h264(self, payload: bytes, *, metadata: dict[str, Any] | None = None) -> None:
        if not payload:
            return
        sample = _rtsp_relay_sample(payload, metadata=metadata)
        with self._lock:
            self._input_sample_count += 1
            self._last_input_at = _utc_now()
            if sample.is_codec_config or sample.has_parameter_set:
                self._latest_codec_config = sample
            if sample.is_keyframe:
                self._latest_keyframe = sample
            appsrc = self._appsrc
            Gst = self._Gst
        if Gst is None or appsrc is None:
            with self._lock:
                self._queued_before_appsrc_count += 1
                self._pending_samples.append(sample)
                del self._pending_samples[:-60]
            return
        self._push_sample_to_appsrc(sample, appsrc=appsrc, Gst=Gst)

    def _push_sample_to_appsrc(self, sample: _RtspRelaySample, *, appsrc: Any, Gst: Any) -> None:
        payload = sample.payload
        buffer = Gst.Buffer.new_allocate(None, len(payload), None)
        buffer.fill(0, payload)
        duration = int(1_000_000_000 / self.fps)
        buffer.duration = duration
        buffer.pts = self._frame_index * duration
        buffer.dts = buffer.pts
        self._frame_index += 1
        try:
            result = appsrc.emit("push-buffer", buffer)
        except Exception as exc:
            with self._lock:
                self._last_error = f"push:{exc.__class__.__name__}: {exc}"[-500:]
            return
        with self._lock:
            self._pushed_sample_count += 1
            self._last_flow_return = str(result)
            self._last_pushed_at = _utc_now()

    def _on_media_configure(self, _factory: Any, media: Any) -> None:
        element = media.get_element()
        appsrc = element.get_child_by_name("src")
        with self._lock:
            self._appsrc = appsrc
            self._media_configure_count += 1
            Gst = self._Gst
            samples = self._preroll_samples_locked()
            self._pending_samples.clear()
        if Gst is None or appsrc is None:
            return
        for sample in samples:
            self._push_sample_to_appsrc(sample, appsrc=appsrc, Gst=Gst)

    def _preroll_samples_locked(self) -> list[_RtspRelaySample]:
        pending = list(self._pending_samples)
        samples: list[_RtspRelaySample] = []
        if self._latest_codec_config is not None:
            samples.append(self._latest_codec_config)
        latest_pending_keyframe = None
        for index in range(len(pending) - 1, -1, -1):
            if pending[index].is_keyframe:
                latest_pending_keyframe = index
                break
        if latest_pending_keyframe is not None:
            samples.extend(pending[latest_pending_keyframe:])
        elif self._latest_keyframe is not None:
            samples.append(self._latest_keyframe)
            samples.extend(pending[-15:])
        else:
            samples.extend(pending[-15:])
        deduped: list[_RtspRelaySample] = []
        seen_sequences: set[int] = set()
        for sample in samples:
            if sample.sequence is not None:
                if sample.sequence in seen_sequences:
                    continue
                seen_sequences.add(sample.sequence)
            elif any(existing.payload == sample.payload for existing in deduped):
                continue
            deduped.append(sample)
        return deduped


def _rtsp_relay_sample(payload: bytes, *, metadata: dict[str, Any] | None = None) -> _RtspRelaySample:
    clean_metadata = dict(metadata or {})
    nal_types = _annexb_nal_types(payload)
    is_keyframe = bool(clean_metadata.get("is_keyframe") or clean_metadata.get("isKeyframe") or 5 in nal_types)
    is_codec_config = bool(clean_metadata.get("is_codec_config") or clean_metadata.get("isCodecConfig"))
    has_parameter_set = 7 in nal_types or 8 in nal_types
    return _RtspRelaySample(
        payload=payload,
        metadata=clean_metadata,
        sequence=_to_int(clean_metadata.get("sequence")),
        is_keyframe=is_keyframe,
        is_codec_config=is_codec_config,
        has_parameter_set=has_parameter_set,
    )


def _annexb_nal_types(payload: bytes) -> list[int]:
    types: list[int] = []
    length = len(payload or b"")
    index = 0
    while index < length - 3:
        prefix_len = 0
        if payload[index : index + 3] == b"\x00\x00\x01":
            prefix_len = 3
        elif index < length - 4 and payload[index : index + 4] == b"\x00\x00\x00\x01":
            prefix_len = 4
        if not prefix_len:
            index += 1
            continue
        nal_index = index + prefix_len
        if nal_index < length:
            types.append(int(payload[nal_index]) & 0x1F)
        index = nal_index + 1
    return types


class DeepStreamAnnotatedH264Relay:
    """Relay DeepStream OSD RTSP output back to Jetson as low-latency H.264 samples.

    DeepStream remains the video compositor/OSD owner. The Ops Console only
    decodes this already-annotated H.264 stream instead of re-drawing live bbox
    layers in JavaScript.
    """

    def __init__(
        self,
        *,
        session_id: str,
        rtsp_uri: str,
        jetson_base_url: str,
        width: int,
        height: int,
        request_timeout_s: float,
    ) -> None:
        self.session_id = session_id
        self.rtsp_uri = rtsp_uri
        self.jetson_base_url = jetson_base_url
        self.width = int(width or 0) or None
        self.height = int(height or 0) or None
        self.request_timeout_s = max(0.5, float(request_timeout_s or 2.0))
        self.state = "idle"
        self.sample_count = 0
        self.keyframe_count = 0
        self.byte_count = 0
        self.last_error: str | None = None
        self.last_sample_at: str | None = None
        self.last_payload_bytes = 0
        self.recent_sample_s: list[float] = []
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pipeline: Any | None = None
        self._Gst: Any | None = None
        self._ws: Any | None = None

    def start(self) -> None:
        try:
            import gi  # type: ignore

            gi.require_version("Gst", "1.0")
            from gi.repository import Gst  # type: ignore
        except Exception as exc:
            self.state = "error"
            self.last_error = f"gstreamer_import:{exc.__class__.__name__}: {exc}"[-500:]
            return

        Gst.init(None)
        self._Gst = Gst
        while not self._stop.is_set():
            try:
                self._run_pipeline_once(Gst)
            except Exception as exc:
                if not self._stop.is_set():
                    self.state = "error"
                    self.last_error = f"relay:{exc.__class__.__name__}: {exc}"[-500:]
            self._close_pipeline(Gst)
            if not self._stop.is_set():
                time.sleep(0.5)
        self._close_ws()
        self.state = "stopped"

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            pipeline = self._pipeline
            Gst = self._Gst
        if pipeline is not None:
            try:
                if Gst is not None:
                    pipeline.set_state(Gst.State.NULL)
            except Exception:
                pass
        self._close_ws()

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "rtsp_uri": self.rtsp_uri,
            "sample_count": self.sample_count,
            "keyframe_count": self.keyframe_count,
            "byte_count": self.byte_count,
            "recent_fps": _recent_fps(self.recent_sample_s),
            "last_payload_bytes": self.last_payload_bytes,
            "last_sample_at": self.last_sample_at,
            "last_error": self.last_error,
        }

    def _run_pipeline_once(self, Gst: Any) -> None:
        self.state = "connecting"
        pipeline = Gst.parse_launch(
            "rtspsrc "
            f"location={self.rtsp_uri} "
            "latency=80 protocols=tcp "
            "! application/x-rtp,media=video,encoding-name=H264 "
            "! rtph264depay "
            "! h264parse config-interval=1 "
            "! video/x-h264,stream-format=byte-stream,alignment=au "
            "! appsink name=sink emit-signals=true sync=false max-buffers=2 drop=true"
        )
        sink = pipeline.get_by_name("sink")
        if sink is None:
            raise RuntimeError("DeepStream annotated H.264 appsink was not created.")
        sink.connect("new-sample", self._on_sample, Gst)
        with self._lock:
            self._pipeline = pipeline
        result = pipeline.set_state(Gst.State.PLAYING)
        if result == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("DeepStream annotated H.264 relay failed to enter PLAYING state.")
        self.state = "receiving"
        bus = pipeline.get_bus()
        while not self._stop.is_set():
            message = bus.timed_pop_filtered(
                200_000_000,
                Gst.MessageType.ERROR | Gst.MessageType.EOS,
            )
            if message is None:
                continue
            if message.type == Gst.MessageType.EOS:
                self.state = "eos"
                return
            if message.type == Gst.MessageType.ERROR:
                error, debug = message.parse_error()
                raise RuntimeError(f"{error.message}; {debug or ''}".strip())

    def _close_pipeline(self, Gst: Any) -> None:
        with self._lock:
            pipeline = self._pipeline
            self._pipeline = None
        if pipeline is not None:
            try:
                pipeline.set_state(Gst.State.NULL)
            except Exception:
                pass

    def _on_sample(self, sink: Any, Gst: Any) -> Any:
        try:
            sample = sink.emit("pull-sample")
            if sample is None:
                return Gst.FlowReturn.OK
            buffer = sample.get_buffer()
            ok, map_info = buffer.map(Gst.MapFlags.READ)
            if not ok:
                return Gst.FlowReturn.OK
            try:
                payload = bytes(map_info.data)
            finally:
                buffer.unmap(map_info)
            if payload:
                flags = buffer.get_flags()
                is_keyframe = not bool(flags & Gst.BufferFlags.DELTA_UNIT)
                pts_us = None if buffer.pts == Gst.CLOCK_TIME_NONE else int(buffer.pts / 1000)
                self._publish_sample(payload, is_keyframe=is_keyframe, presentation_time_us=pts_us)
        except Exception as exc:
            self.state = "error"
            self.last_error = f"sample:{exc.__class__.__name__}: {exc}"[-500:]
        return Gst.FlowReturn.OK

    def _publish_sample(self, payload: bytes, *, is_keyframe: bool, presentation_time_us: int | None) -> None:
        try:
            ws = self._ensure_ws()
            sequence = self.sample_count + 1
            header = {
                "type": "sample",
                "source": "deepstream_yolo26_osd",
                "transport": "deepstream_rtsp_h264",
                "rtsp_uri": self.rtsp_uri,
                "sequence": sequence,
                "isKeyframe": bool(is_keyframe),
                "is_keyframe": bool(is_keyframe),
                "width": self.width,
                "height": self.height,
                "presentationTimeUs": presentation_time_us,
                "presentation_time_us": presentation_time_us,
                "annotated": True,
                "osd_burned_in": True,
                "preview_route_kind": "deepstream_osd_h264",
                "perception_branch": YOLO26_BRANCH,
            }
            ws.send(json.dumps(header))
            ws.send_binary(payload)
        except Exception as exc:
            self._close_ws()
            if _websocket_closed_while_relaying(exc):
                self.last_error = None
                return
            self.state = "error"
            self.last_error = f"publish:{exc.__class__.__name__}: {exc}"[-500:]
            return
        self.state = "receiving"
        self.sample_count += 1
        self.keyframe_count += 1 if is_keyframe else 0
        self.byte_count += len(payload)
        self.last_payload_bytes = len(payload)
        self.recent_sample_s.append(time.monotonic())
        del self.recent_sample_s[:-120]
        self.last_sample_at = _utc_now()

    def _ensure_ws(self) -> Any:
        if self._ws is not None:
            return self._ws
        import websocket  # type: ignore

        url = _ws_url(self.jetson_base_url, f"/ws/adapters/deepstream/{quote(self.session_id)}/h264")
        self._ws = websocket.create_connection(url, timeout=self.request_timeout_s)
        return self._ws

    def _close_ws(self) -> None:
        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass


class DeepStreamYolo26Worker:
    def __init__(
        self,
        *,
        settings: DeepStreamYolo26WorkerSettings,
        api: JetsonApiClient | None = None,
        status_writer: JsonStatusWriter | None = None,
        clock: Any = time.monotonic,
    ) -> None:
        self._settings = settings
        self._api = api or JetsonApiClient(base_url=settings.jetson_base_url, timeout_s=settings.request_timeout_s)
        self._status_writer = status_writer or JsonStatusWriter(_status_path(settings))
        self._clock = clock
        self._sessions: dict[str, _SessionRuntime] = {}
        self._labels = _read_labels(Path(settings.labels_path).expanduser() if settings.labels_path else None)
        self._last_probe = probe_deepstream_runtime(settings)
        self._total_posted_frame_count = 0
        self._total_ignored_message_count = 0
        self._total_parsed_message_count = 0
        self._total_error_count = 0
        self._completed_session_stats: list[dict[str, Any]] = []
        self._last_error: str | None = None

    def run_forever(self) -> None:
        if not self._settings.enabled:
            self._write_status(status="disabled", message="OPENVISION_DEEPSTREAM_YOLO26_WORKER_ENABLED is not set.")
            return
        while True:
            status: dict[str, Any] = {}
            try:
                status = self.run_once()
            except KeyboardInterrupt:
                self._write_status(status="stopped", message="Worker interrupted.")
                self.stop_all(reason="interrupted")
                raise
            except Exception as exc:
                self._last_error = f"{exc.__class__.__name__}: {exc}"
                self._write_status(status="error", message=self._last_error)
            time.sleep(self._sleep_interval_s(status))

    def run_once(self) -> dict[str, Any]:
        if not self._settings.enabled:
            status = self._status_payload(status="disabled", message="OPENVISION_DEEPSTREAM_YOLO26_WORKER_ENABLED is not set.")
            self._status_writer.write(status)
            return status
        self._last_probe = probe_deepstream_runtime(self._settings)
        if self._last_probe.get("status") != "ready":
            self.stop_all(reason="runtime_not_ready")
            status = self._status_payload(
                status="blocked",
                message=str(self._last_probe.get("message") or "DeepStream runtime is not ready."),
                runtime=self._last_probe,
            )
            self._status_writer.write(status)
            return status
        active_live = self._target_live_sessions(self._api.list_active_live())
        self._last_error = None
        active_ids = {str(item.get("session_id") or "") for item in active_live if str(item.get("session_id") or "")}
        for session_id in list(self._sessions):
            if session_id not in active_ids:
                self._stop_session(session_id, reason="live_session_inactive")
        started = 0
        for live in active_live[: max(1, int(self._settings.max_sessions or 1))]:
            session_id = str(live.get("session_id") or "")
            if not session_id:
                continue
            runtime = self._sessions.get(session_id)
            if runtime is not None and self._runtime_needs_restart(runtime):
                self._stop_session(session_id, reason="process_exited")
                runtime = None
            if runtime is None:
                self._start_session(live)
                started += 1
            else:
                runtime.last_seen_at = _utc_now()
        status = self._status_payload(
            status="running",
            message="DeepStream YOLO26 worker poll completed.",
            runtime=self._last_probe,
            active_live_count=len(active_live),
            started_session_count=started,
        )
        self._status_writer.write(status)
        return status

    def stop_all(self, *, reason: str = "shutdown") -> None:
        for session_id in list(self._sessions):
            self._stop_session(session_id, reason=reason)

    def _start_session(self, live: dict[str, Any]) -> None:
        session_id = str(live.get("session_id") or "")
        topic = f"{self._settings.mqtt_topic_prefix}/{_safe_segment(session_id)}/detections"
        rtsp_port, annotated_rtsp_port, annotated_udp_port = self._allocate_session_ports()
        relay = Rv101RtspRelay(session_id=session_id, port=rtsp_port, fps=self._settings.stream_fps)
        config_dir = _session_config_dir(self._settings, session_id)
        rtsp_uri = relay.uri
        annotated_rtsp_uri = f"rtsp://127.0.0.1:{annotated_rtsp_port}/ds-test" if self._settings.annotated_rtsp_enabled else None
        resolution = live.get("resolution") if isinstance(live.get("resolution"), dict) else {}
        stream_width = _to_int(resolution.get("width")) or self._settings.stream_width
        stream_height = _to_int(resolution.get("height")) or self._settings.stream_height
        render_deepstream_configs(
            settings=self._settings,
            session_id=session_id,
            rtsp_uri=rtsp_uri,
            mqtt_topic=topic,
            output_dir=config_dir,
            annotated_rtsp_port=annotated_rtsp_port,
            annotated_udp_port=annotated_udp_port,
        )
        annotated_relay = (
            DeepStreamAnnotatedH264Relay(
                session_id=session_id,
                rtsp_uri=annotated_rtsp_uri,
                jetson_base_url=self._settings.jetson_base_url,
                width=self._settings.streammux_width,
                height=self._settings.streammux_height,
                request_timeout_s=self._settings.request_timeout_s,
            )
            if annotated_rtsp_uri
            else None
        )
        runtime = _SessionRuntime(
            session_id=session_id,
            command_id=str(live.get("command_id") or "") or None,
            skill_id=str(live.get("skill_id") or "") or None,
            topic=topic,
            rtsp_uri=rtsp_uri,
            config_dir=config_dir,
            stream_width=int(stream_width),
            stream_height=int(stream_height),
            rtsp_port=rtsp_port,
            annotated_rtsp_port=annotated_rtsp_port if self._settings.annotated_rtsp_enabled else None,
            annotated_udp_port=annotated_udp_port if self._settings.annotated_rtsp_enabled else None,
            rtsp_relay=relay,
            annotated_rtsp_uri=annotated_rtsp_uri,
            annotated_relay=annotated_relay,
        )
        self._sessions[session_id] = runtime
        runtime.relay_thread = threading.Thread(target=self._rtsp_relay_loop, args=(runtime,), name=f"openvision_rtsp_relay:{session_id}", daemon=True)
        runtime.relay_thread.start()
        if not relay.wait_until_ready(timeout_s=max(1.5, self._settings.request_timeout_s)):
            runtime.error_count += 1
            runtime.last_error = "rtsp_relay_not_ready_before_deepstream_start"
            self._stop_session(session_id, reason="rtsp_relay_not_ready")
            return
        runtime.deepstream_process = subprocess.Popen(  # noqa: S603 - configured local binary, guarded by probe.
            [self._settings.deepstream_app_bin, "-c", str(config_dir / "deepstream_app_config.txt")],
            cwd=str(config_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        runtime.mqtt_process = subprocess.Popen(  # noqa: S603 - configured local binary, guarded by probe.
            _mosquitto_sub_command(
                self._settings.mosquitto_sub_bin,
                host=self._settings.mqtt_host,
                port=self._settings.mqtt_port,
                topic=topic,
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=1,
            text=True,
        )
        runtime.mqtt_thread = threading.Thread(target=self._mqtt_loop, args=(runtime,), name=f"openvision_ds_mqtt:{session_id}", daemon=True)
        runtime.mqtt_thread.start()
        if runtime.annotated_relay is not None:
            runtime.annotated_relay_thread = threading.Thread(
                target=self._deepstream_annotated_relay_loop,
                args=(runtime,),
                name=f"openvision_ds_osd_h264:{session_id}",
                daemon=True,
            )
            runtime.annotated_relay_thread.start()

    def _allocate_session_ports(self) -> tuple[int, int, int]:
        used_rtsp_ports = {runtime.rtsp_port for runtime in self._sessions.values()}
        for slot in range(max(1, int(self._settings.max_sessions or 1))):
            rtsp_port = self._settings.rtsp_port + slot
            if rtsp_port in used_rtsp_ports:
                continue
            return (
                rtsp_port,
                self._settings.annotated_rtsp_port + slot,
                self._settings.annotated_udp_port + slot,
            )
        raise RuntimeError("no_available_deepstream_rtsp_port")

    def _runtime_needs_restart(self, runtime: _SessionRuntime) -> bool:
        for name, process in (("deepstream", runtime.deepstream_process), ("mqtt", runtime.mqtt_process)):
            if process is None:
                continue
            return_code = process.poll()
            if return_code is not None:
                runtime.error_count += 1
                runtime.last_error = f"{name}_process_exited:{return_code}"
                return True
        if runtime.rtsp_relay is not None:
            relay = runtime.rtsp_relay.status()
            age_s = max(0.0, self._clock() - runtime.started_monotonic_s)
            if (
                age_s >= 5.0
                and int(relay.get("input_sample_count") or 0) >= 45
                and int(relay.get("media_configure_count") or 0) == 0
            ):
                runtime.error_count += 1
                runtime.last_error = "rtsp_source_not_attached_after_h264_preroll"
                return True
        return False

    def _stop_session(self, session_id: str, *, reason: str) -> None:
        runtime = self._sessions.pop(session_id, None)
        if runtime is None:
            return
        for process in (runtime.deepstream_process, runtime.mqtt_process):
            if process is None or process.poll() is not None:
                continue
            process.terminate()
            try:
                process.wait(timeout=max(0.5, self._settings.process_grace_s))
            except subprocess.TimeoutExpired:
                process.kill()
        if runtime.rtsp_relay:
            runtime.rtsp_relay.stop()
        if runtime.annotated_relay:
            runtime.annotated_relay.stop()
        runtime.last_seen_at = _utc_now()
        self._completed_session_stats.append(_runtime_status_payload(runtime, active=False, stopped_reason=reason))
        del self._completed_session_stats[:-8]

    def _rtsp_relay_loop(self, runtime: _SessionRuntime) -> None:
        relay = runtime.rtsp_relay
        if relay is None:
            return
        ws_thread = threading.Thread(target=self._h264_ws_loop, args=(runtime,), name=f"openvision_h264_ws:{runtime.session_id}", daemon=True)
        ws_thread.start()
        try:
            relay.start()
        except Exception as exc:
            runtime.error_count += 1
            runtime.last_error = f"rtsp:{exc.__class__.__name__}: {exc}"[-500:]

    def _deepstream_annotated_relay_loop(self, runtime: _SessionRuntime) -> None:
        relay = runtime.annotated_relay
        if relay is None:
            return
        time.sleep(1.0)
        try:
            relay.start()
        except Exception as exc:
            runtime.error_count += 1
            runtime.last_error = f"annotated_h264:{exc.__class__.__name__}: {exc}"[-500:]

    def _h264_ws_loop(self, runtime: _SessionRuntime) -> None:
        try:
            import websocket  # type: ignore
        except Exception as exc:
            runtime.error_count += 1
            runtime.last_error = f"websocket_import:{exc.__class__.__name__}: {exc}"[-500:]
            return
        url = _ws_url(self._settings.jetson_base_url, f"/ws/preview/{quote(runtime.session_id)}/h264")
        try:
            ws = websocket.create_connection(url, timeout=max(1.0, self._settings.request_timeout_s))
        except Exception as exc:
            runtime.error_count += 1
            runtime.last_error = f"websocket_connect:{exc.__class__.__name__}: {exc}"[-500:]
            return
        pending_sample_metadata: dict[str, Any] = {}
        try:
            while runtime.session_id in self._sessions:
                message = ws.recv()
                if isinstance(message, str):
                    try:
                        metadata = json.loads(message)
                    except json.JSONDecodeError:
                        pending_sample_metadata = {}
                        continue
                    if isinstance(metadata, dict) and metadata.get("type") == "sample":
                        pending_sample_metadata = dict(metadata)
                    continue
                if isinstance(message, bytes) and runtime.rtsp_relay:
                    runtime.rtsp_relay.push_h264(message, metadata=pending_sample_metadata)
                    pending_sample_metadata = {}
        except Exception as exc:
            if runtime.session_id in self._sessions:
                runtime.error_count += 1
                runtime.last_error = f"websocket_recv:{exc.__class__.__name__}: {exc}"[-500:]
        finally:
            try:
                ws.close()
            except Exception:
                pass

    def _mqtt_loop(self, runtime: _SessionRuntime) -> None:
        process = runtime.mqtt_process
        if process is None or process.stdout is None:
            return
        assembler = _MqttPayloadAssembler(runtime.topic)
        for line in process.stdout:
            if runtime.session_id not in self._sessions:
                return
            text = line.strip()
            if not text:
                continue
            for payload_text in assembler.feed(text):
                try:
                    detections, metadata = parse_deepstream_payload(payload_text, labels=self._labels)
                except Exception as exc:
                    runtime.error_count += 1
                    self._total_error_count += 1
                    runtime.last_error = f"mqtt_parse:{exc.__class__.__name__}: {exc}"[-500:]
                    runtime.last_payload_sample = payload_text[:1000]
                    runtime.last_payload_status = "parse_error"
                    continue
                runtime.last_payload_sample = payload_text[:1000]
                runtime.last_payload_status = "parsed"
                runtime.parsed_message_count += 1
                self._total_parsed_message_count += 1
                sequence = runtime.parsed_message_count
                post_payload = {
                    "source": self._settings.source,
                    "frame_id": f"deepstream_{sequence}",
                    "sequence": sequence,
                    "width": metadata.get("width") or runtime.stream_width,
                    "height": metadata.get("height") or runtime.stream_height,
                    "latency_ms": metadata.get("latency_ms") or 0,
                    "metadata": {
                        **metadata,
                        "perception_branch": YOLO26_BRANCH,
                        "preview_route_kind": "stable_overlay_h264",
                        "bbox_coordinate_space": "yolo26_detector_frame",
                        "source_frame_id": f"deepstream_{sequence}",
                        "video_sequence": sequence,
                        "deepstream_worker": {
                            "backend": "deepstream-app",
                            "rtsp_uri": runtime.rtsp_uri,
                            "mqtt_topic": runtime.topic,
                            "infer_interval": self._settings.infer_interval,
                            "tracker_enabled": self._settings.tracker_enabled,
                        },
                    },
                    "detections": detections,
                }
                try:
                    self._api.post_stream_detections(session_id=runtime.session_id, payload=post_payload)
                except Exception as exc:
                    if _inactive_live_conflict_error(exc):
                        runtime.ignored_message_count += 1
                        self._total_ignored_message_count += 1
                        runtime.last_payload_status = "post_ignored_inactive_live"
                        runtime.last_error = None
                        continue
                    runtime.error_count += 1
                    self._total_error_count += 1
                    runtime.last_error = f"post:{exc.__class__.__name__}: {exc}"[-500:]
                    continue
                now_s = self._clock()
                runtime.posted_frame_count += 1
                runtime.last_payload_status = "posted_empty_frame" if not detections else "posted"
                runtime.recent_post_s.append(now_s)
                del runtime.recent_post_s[:-120]
                runtime.last_posted_frame = {
                    "frame_id": post_payload["frame_id"],
                    "sequence": sequence,
                    "detection_count": len(detections),
                    "posted_at": _utc_now(),
                    "labels": sorted({str(item.get("label") or "") for item in detections if item.get("label")}),
                    "classification_status": metadata.get("classification_status"),
                    "missing_confidence_count": metadata.get("missing_confidence_count"),
                }
                self._total_posted_frame_count += 1

    def _target_live_sessions(self, active_live: list[dict[str, Any]]) -> list[dict[str, Any]]:
        yolo_live = [item for item in active_live if _active_live_needs_yolo26(item)]
        return yolo_live[: max(1, int(self._settings.max_sessions or 1))]

    def _sleep_interval_s(self, status: dict[str, Any]) -> float:
        if status.get("active_live_count") or self._sessions:
            return max(0.05, float(self._settings.poll_interval_s or 0.25))
        return max(0.1, float(self._settings.idle_poll_interval_s or 2.0))

    def _status_payload(self, *, status: str, message: str, **extra: Any) -> dict[str, Any]:
        session_stats = [_runtime_status_payload(runtime, active=True) for runtime in self._sessions.values()]
        return {
            "schema_version": "openvision.deepstream_yolo26_worker_status.v1",
            "status": status,
            "enabled": self._settings.enabled,
            "backend": "deepstream",
            "source": self._settings.source,
            "jetson_base_url": self._settings.jetson_base_url,
            "target_skill_id": "*",
            "target_skill_mode": "declared_yolo26_preview_branch",
            "target_classes": [],
            "target_classes_mode": "all_supported",
            "engine_path_configured": bool(self._settings.engine_path or self._settings.onnx_path),
            "engine_exists": bool(self._settings.engine_path and Path(self._settings.engine_path).expanduser().exists()),
            "engine_path": self._settings.engine_path,
            "labels_path_configured": bool(self._settings.labels_path),
            "labels_exists": bool(self._settings.labels_path and Path(self._settings.labels_path).expanduser().exists()),
            "imgsz": 640,
            "half": True,
            "crop_enabled": False,
            "crop_interval_frames": 0,
            "max_fps": self._settings.stream_fps,
            "recent_post_fps": _recent_fps([t for runtime in self._sessions.values() for t in runtime.recent_post_s]),
            "recent_fetch_latency_ms": None,
            "recent_detector_latency_ms": None,
            "recent_post_latency_ms": None,
            "total_parsed_message_count": self._total_parsed_message_count,
            "total_posted_frame_count": self._total_posted_frame_count,
            "total_skipped_frame_count": self._total_ignored_message_count,
            "total_error_count": self._total_error_count,
            "last_error": self._last_error or next((runtime.last_error for runtime in self._sessions.values() if runtime.last_error), None),
            "last_posted_frame": next((runtime.last_posted_frame for runtime in self._sessions.values() if runtime.last_posted_frame), None),
            "session_stats": session_stats,
            "completed_session_stats": self._completed_session_stats[-8:],
            "last_completed_session": self._completed_session_stats[-1] if self._completed_session_stats else None,
            "ring_safety": "separate_openvision_runtime_only",
            "message": message,
            "updated_at": _utc_now(),
            **extra,
        }

    def _write_status(self, *, status: str, message: str) -> None:
        self._status_writer.write(self._status_payload(status=status, message=message, runtime=self._last_probe))


def _active_live_needs_yolo26(live: dict[str, Any]) -> bool:
    params = live.get("params") if isinstance(live.get("params"), dict) else {}
    branches = params.get("perception_branches") if isinstance(params.get("perception_branches"), list) else []
    if YOLO26_BRANCH in {str(item).strip() for item in branches}:
        return True
    route = params.get("preview_route") if isinstance(params.get("preview_route"), dict) else {}
    if str(route.get("primary_branch") or "").strip() == YOLO26_BRANCH:
        return True
    if str(route.get("route_kind") or "").strip() in {"deepstream_osd_h264", "stable_overlay_h264"}:
        return True
    # Backward compatibility for already-deployed control planes that do not
    # include preview_route yet. Do not broaden this to all live skills.
    return str(live.get("skill_id") or "").strip() == "target_finder"


def _inactive_live_conflict_error(exc: Exception) -> bool:
    return isinstance(exc, HTTPError) and int(getattr(exc, "code", 0) or 0) == 409


def _websocket_closed_while_relaying(exc: Exception) -> bool:
    if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
        return True
    name = exc.__class__.__name__
    return name in {"WebSocketConnectionClosedException", "ConnectionClosed", "ConnectionClosedError"}


def render_deepstream_configs(
    *,
    settings: DeepStreamYolo26WorkerSettings,
    session_id: str,
    rtsp_uri: str,
    mqtt_topic: str,
    output_dir: Path,
    annotated_rtsp_port: int | None = None,
    annotated_udp_port: int | None = None,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    _assert_safe_openvision_path(settings.onnx_path, "onnx")
    _assert_safe_openvision_path(settings.engine_path, "engine")
    _assert_safe_openvision_path(settings.custom_lib_path, "custom_lib")
    labels = settings.labels_path or str(settings.runtime_dir / "yolo26" / "yolo26_labels.txt")
    engine = settings.engine_path or str(settings.runtime_dir / "yolo26" / "openvision_yolo26.engine")
    onnx = settings.onnx_path or str(settings.runtime_dir / "yolo26" / "openvision_yolo26.onnx")
    custom_lib = settings.custom_lib_path or "/home/jay/DeepStream-Yolo/nvdsinfer_custom_impl_Yolo/libnvdsinfer_custom_impl_Yolo.so"
    mqtt_config = settings.mqtt_config_path or str(output_dir / "mqtt_openvision.txt")
    infer_config = output_dir / "config_infer_primary_yolo26.txt"
    app_config = output_dir / "deepstream_app_config.txt"
    mqtt_config_path = output_dir / "mqtt_openvision.txt"
    mqtt_config_path.write_text("[message-broker]\nproto-cfg=\n", encoding="utf-8")
    infer_config.write_text(
        f"""[property]
gpu-id=0
net-scale-factor=0.0039215697906911373
model-color-format=0
onnx-file={onnx}
model-engine-file={engine}
labelfile-path={labels}
batch-size=1
network-mode=2
num-detected-classes=80
interval={max(0, int(settings.infer_interval or 0))}
gie-unique-id=1
process-mode=1
network-type=0
cluster-mode=4
maintain-aspect-ratio=1
symmetric-padding=1
parse-bbox-func-name=NvDsInferParseYolo
custom-lib-path={custom_lib}
engine-create-func-name=NvDsInferYoloCudaEngineGet

[class-attrs-all]
pre-cluster-threshold={settings.min_confidence:.3f}
topk=300
""",
        encoding="utf-8",
    )
    tracker_block = ""
    if settings.tracker_enabled:
        tracker_block = f"""
[tracker]
enable=1
tracker-width=640
tracker-height=384
ll-lib-file=/opt/nvidia/deepstream/deepstream/lib/libnvds_nvmultiobjecttracker.so
ll-config-file={settings.tracker_config_path or ''}
display-tracking-id=1
user-meta-pool-size=256
"""
    annotated_sink_block = ""
    annotated_uri: str | None = None
    if settings.annotated_rtsp_enabled:
        rtsp_out_port = int(annotated_rtsp_port or settings.annotated_rtsp_port)
        udp_out_port = int(annotated_udp_port or settings.annotated_udp_port)
        annotated_uri = f"rtsp://127.0.0.1:{rtsp_out_port}/ds-test"
        annotated_sink_block = f"""
[sink2]
enable=1
type=4
sync=0
source-id=0
gpu-id=0
codec=1
enc-type=0
bitrate={max(256000, int(settings.annotated_bitrate or 4000000))}
rtsp-port={rtsp_out_port}
udp-port={udp_out_port}
"""
    app_config.write_text(
        f"""[application]
enable-perf-measurement=1
perf-measurement-interval-sec=1

[tiled-display]
enable=0
rows=1
columns=1
width={settings.streammux_width}
height={settings.streammux_height}
gpu-id=0
nvbuf-memory-type=0

[source0]
enable=1
type=4
uri={rtsp_uri}
latency=80
num-sources=1
gpu-id=0
cudadec-memtype=0
select-rtp-protocol=4
rtsp-reconnect-interval-sec=1
rtsp-reconnect-attempts=-1

[sink0]
enable={1 if settings.fake_sink_enabled else 0}
type=1
sync=0
source-id=0

[sink1]
enable=1
type=6
sync=0
msg-conv-config={output_dir / 'msgconv_openvision.txt'}
msg-conv-payload-type=0
msg-conv-msg2p-new-api=1
msg-conv-frame-interval=1
msg-broker-proto-lib=/opt/nvidia/deepstream/deepstream/lib/libnvds_mqtt_proto.so
msg-broker-config={mqtt_config}
msg-broker-conn-str={settings.mqtt_host};{settings.mqtt_port};openvision-{_safe_segment(session_id)}
topic={mqtt_topic}
{annotated_sink_block}

[osd]
enable=1
gpu-id=0
border-width=2
text-size=12
text-color=1;1;1;1;
text-bg-color=0;0;0;0.55;
font=Sans
show-clock=0
display-bbox=1
display-text=1
nvbuf-memory-type=0

[streammux]
gpu-id=0
live-source=1
batch-size=1
batched-push-timeout=10000
width={settings.streammux_width}
height={settings.streammux_height}
enable-padding=1
nvbuf-memory-type=0

[primary-gie]
enable=1
gpu-id=0
batch-size=1
gie-unique-id=1
nvbuf-memory-type=0
config-file={infer_config}
{tracker_block}
[tests]
file-loop=0
""",
        encoding="utf-8",
    )
    (output_dir / "msgconv_openvision.txt").write_text(
        "[sensor0]\n"
        f"enable=1\nid={_safe_segment(session_id)}\ntype=rv101\nlocation=0;0;0\n"
        "description=OpenVision RV101 live camera\n",
        encoding="utf-8",
    )
    return {
        "app_config": str(app_config),
        "infer_config": str(infer_config),
        "mqtt_config": str(mqtt_config_path),
        "annotated_rtsp_uri": annotated_uri or "",
    }


def _mosquitto_sub_command(binary: str, *, host: str, port: int, topic: str) -> list[str]:
    base = [binary, "-h", host, "-p", str(port), "-t", topic, "-v"]
    stdbuf = shutil.which("stdbuf")
    if stdbuf:
        return [stdbuf, "-oL", "-eL", *base]
    return base


class _MqttPayloadAssembler:
    """Reconstruct one DeepStream MQTT JSON payload from mosquitto_sub lines."""

    def __init__(self, topic: str, *, max_chars: int = 512_000) -> None:
        self._topic = topic
        self._max_chars = max(4096, int(max_chars))
        self._decoder = json.JSONDecoder()
        self._buffer: list[str] = []

    def feed(self, line: str) -> list[str]:
        payload_line = _strip_mqtt_topic(self._topic, line).strip()
        if not payload_line:
            return []
        if not self._buffer and not payload_line.lstrip().startswith(("{", "[")):
            return []
        self._buffer.append(payload_line)
        candidate = "\n".join(self._buffer).strip()
        if len(candidate) > self._max_chars:
            self._buffer.clear()
            return [candidate]
        try:
            _value, end_index = self._decoder.raw_decode(candidate)
        except json.JSONDecodeError:
            return []
        if candidate[end_index:].strip():
            return []
        self._buffer.clear()
        return [candidate]


def _runtime_status_payload(
    runtime: _SessionRuntime,
    *,
    active: bool,
    stopped_reason: str | None = None,
) -> dict[str, Any]:
    payload = {
        "session_id": runtime.session_id,
        "command_id": runtime.command_id,
        "skill_id": runtime.skill_id,
        "active": active,
        "topic": runtime.topic,
        "rtsp_uri": runtime.rtsp_uri,
        "annotated_rtsp_uri": runtime.annotated_rtsp_uri,
        "rtsp_port": runtime.rtsp_port,
        "annotated_rtsp_port": runtime.annotated_rtsp_port,
        "annotated_udp_port": runtime.annotated_udp_port,
        "stream_width": runtime.stream_width,
        "stream_height": runtime.stream_height,
        "started_at": runtime.started_at,
        "last_seen_at": runtime.last_seen_at,
        "posted_frame_count": runtime.posted_frame_count,
        "parsed_message_count": runtime.parsed_message_count,
        "ignored_message_count": runtime.ignored_message_count,
        "error_count": runtime.error_count,
        "last_error": runtime.last_error,
        "last_payload_sample": runtime.last_payload_sample,
        "last_payload_status": runtime.last_payload_status,
        "last_posted_frame": runtime.last_posted_frame,
        "recent_post_fps": _recent_fps(runtime.recent_post_s),
        "deepstream_pid": runtime.deepstream_process.pid if runtime.deepstream_process else None,
        "mqtt_pid": runtime.mqtt_process.pid if runtime.mqtt_process else None,
        "rtsp_relay": runtime.rtsp_relay.status() if runtime.rtsp_relay else None,
        "annotated_h264_relay": runtime.annotated_relay.status() if runtime.annotated_relay else None,
    }
    if stopped_reason:
        payload["stopped_reason"] = stopped_reason
    return payload


def probe_deepstream_runtime(settings: DeepStreamYolo26WorkerSettings) -> dict[str, Any]:
    missing: list[str] = []
    for name, binary in {"deepstream_app": settings.deepstream_app_bin, "mosquitto_sub": settings.mosquitto_sub_bin}.items():
        if shutil.which(binary) is None:
            missing.append(name)
    for label, path in {
        "onnx_path": settings.onnx_path,
        "labels_path": settings.labels_path,
        "custom_lib_path": settings.custom_lib_path,
    }.items():
        if not path:
            continue
        try:
            _assert_safe_openvision_path(path, label)
        except ValueError as exc:
            return {"status": "blocked", "reason": "protected_runtime_path", "message": str(exc)}
        if not Path(path).expanduser().exists():
            missing.append(label)
    if settings.tracker_enabled and settings.tracker_config_path:
        tracker_path = Path(settings.tracker_config_path).expanduser()
        if not tracker_path.exists():
            missing.append("tracker_config_path")
    if missing:
        return {"status": "blocked", "reason": "missing_dependency", "missing": missing, "message": f"Missing DeepStream dependencies: {', '.join(missing)}"}
    mqtt_ready = _tcp_connects(settings.mqtt_host, settings.mqtt_port, timeout_s=0.3)
    if not mqtt_ready:
        return {
            "status": "blocked",
            "reason": "mqtt_unreachable",
            "message": f"DeepStream MQTT broker is not reachable at {settings.mqtt_host}:{settings.mqtt_port}.",
        }
    return {
        "status": "ready",
        "backend": "deepstream",
        "deepstream_app": shutil.which(settings.deepstream_app_bin),
        "mosquitto_sub": shutil.which(settings.mosquitto_sub_bin),
        "rtsp_port": settings.rtsp_port,
        "mqtt": {
            "host": settings.mqtt_host,
            "port": settings.mqtt_port,
            "topic_prefix": settings.mqtt_topic_prefix,
            "broker_reachable": mqtt_ready,
        },
        "annotated_h264": {
            "enabled": settings.annotated_rtsp_enabled,
            "rtsp_port": settings.annotated_rtsp_port,
            "udp_port": settings.annotated_udp_port,
            "bitrate": settings.annotated_bitrate,
        },
    }


def parse_deepstream_payload(payload_text: str, *, labels: list[str] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = json.loads(payload_text)
    labels = labels or []
    metadata: dict[str, Any] = {"payload_schema": "deepstream"}
    detections: list[dict[str, Any]] = []
    frames = _as_list(payload.get("frames") if isinstance(payload, dict) else None)
    if frames:
        for frame in frames:
            if isinstance(frame, dict):
                metadata.setdefault("width", _to_int(frame.get("width") or frame.get("frameWidth")))
                metadata.setdefault("height", _to_int(frame.get("height") or frame.get("frameHeight")))
                for obj in _as_list(frame.get("objects") or frame.get("object")):
                    detection = _detection_from_deepstream_object(obj, labels=labels)
                    if detection:
                        detections.append(detection)
    if isinstance(payload, dict):
        for obj in _as_list(payload.get("objects") or payload.get("object")):
            detection = _detection_from_deepstream_object(obj, labels=labels)
            if detection:
                detections.append(detection)
        metadata.setdefault("width", _to_int(payload.get("width") or payload.get("frameWidth")))
        metadata.setdefault("height", _to_int(payload.get("height") or payload.get("frameHeight")))
        if payload.get("@timestamp"):
            metadata["deepstream_timestamp"] = payload.get("@timestamp")
    missing_confidence_count = sum(
        1
        for item in detections
        if isinstance(item.get("attributes"), dict) and item["attributes"].get("confidence_source") == "missing"
    )
    unclassified_count = sum(
        1
        for item in detections
        if isinstance(item.get("attributes"), dict) and item["attributes"].get("classification_status") == "unclassified"
    )
    if missing_confidence_count:
        metadata["missing_confidence_count"] = missing_confidence_count
    if unclassified_count:
        metadata["unclassified_object_count"] = unclassified_count
        metadata["classification_status"] = "partial_unclassified" if unclassified_count < len(detections) else "unclassified"
    return detections, {key: value for key, value in metadata.items() if value is not None}


def _detection_from_deepstream_object(obj: Any, *, labels: list[str]) -> dict[str, Any] | None:
    if isinstance(obj, str):
        obj = _object_from_deepstream_string(obj)
    if not isinstance(obj, dict):
        return None
    class_id = _to_int(_first_present(obj, "class_id", "classId", "class-id"))
    raw_label_value = _first_present(obj, "label", "class", "className", "objType", "type")
    label = str(raw_label_value or "").strip().lower()
    nested_label, nested_confidence = _nested_class_from_deepstream_object(obj, labels)
    class_id_label = labels[class_id].strip().lower() if class_id is not None and 0 <= class_id < len(labels) else None
    if label and label not in {"object", "obj", "unknown"}:
        label_source = "payload"
    elif nested_label:
        label = nested_label
        label_source = "nested_msgconv_class"
    elif class_id_label:
        label = labels[class_id].strip().lower()
        label_source = "class_id"
    else:
        label_source = "payload" if label else "missing"
    label = label or "object"
    bbox = _bbox_from_object(obj)
    if not bbox:
        return None
    raw_confidence = _first_present(obj, "confidence", "score", "prob")
    confidence_missing = raw_confidence is None
    confidence = _to_float(raw_confidence, default=None)
    confidence_source = "payload"
    if confidence is None and nested_confidence is not None:
        confidence = nested_confidence
        confidence_missing = False
        confidence_source = "nested_msgconv_class"
    if confidence is None:
        confidence = 0.25
        confidence_source = "missing"
    track_id = _first_present(obj, "tracking_id", "trackingId", "object_id", "id")
    attrs = {"detector_family": "deepstream_yolo26", "accelerator": "deepstream"}
    if class_id is not None:
        attrs["class_id"] = class_id
    if class_id_label and class_id_label != label:
        attrs["class_id_label"] = class_id_label
        attrs["label_conflict"] = "nested_msgconv_class_overrode_class_id" if label_source == "nested_msgconv_class" else "payload_overrode_class_id"
    attrs["label_source"] = label_source
    if confidence_source != "payload":
        attrs["confidence_source"] = confidence_source
    if confidence_missing:
        attrs["confidence_display"] = "hidden"
    if label in {"object", "obj", "unknown"} and class_id is None:
        attrs["classification_status"] = "unclassified"
        if track_id is not None:
            attrs["display_name"] = f"YOLO track {track_id}"
    return {
        "label": label,
        "confidence": max(0.0, min(1.0, float(confidence))),
        "bbox": bbox,
        "track_id": str(track_id) if track_id is not None else None,
        "attributes": attrs,
    }


def _nested_class_from_deepstream_object(obj: dict[str, Any], labels: list[str]) -> tuple[str | None, float | None]:
    """Extract DeepStream msgconv class payloads such as {"mouse": {"confidence": ...}}."""

    label_set = {str(label).strip().lower() for label in labels if str(label).strip()}
    ignored = {
        "bbox",
        "box",
        "class",
        "class-id",
        "class_id",
        "classid",
        "classname",
        "confidence",
        "coordinate",
        "coordinates",
        "id",
        "label",
        "objtype",
        "object_id",
        "prob",
        "rect_params",
        "rectparams",
        "score",
        "tracking_id",
        "trackingid",
        "type",
        "x1",
        "x2",
        "y1",
        "y2",
    }
    for key, value in obj.items():
        label = str(key or "").strip().lower()
        if not label or label in ignored:
            continue
        if label_set and label not in label_set:
            continue
        if not isinstance(value, dict):
            continue
        confidence = _to_float(_first_present(value, "confidence", "score", "prob"))
        return label, confidence
    return None, None


def _object_from_deepstream_string(value: str) -> dict[str, Any]:
    # DeepStream minimal payload can encode objects as "class|id|left|top|width|height|confidence".
    parts = [part.strip() for part in value.split("|")]
    if len(parts) >= 6:
        return {
            "label": parts[0],
            "tracking_id": parts[1],
            "left": parts[2],
            "top": parts[3],
            "width": parts[4],
            "height": parts[5],
            "confidence": parts[6] if len(parts) > 6 else 0.0,
        }
    return {"label": value}


def _bbox_from_object(obj: dict[str, Any]) -> list[float] | None:
    raw_bbox = obj.get("bbox") or obj.get("box")
    if isinstance(raw_bbox, list) and len(raw_bbox) >= 4:
        values = [_to_float(value) for value in raw_bbox[:4]]
        if all(value is not None for value in values):
            x1, y1, x2, y2 = [float(value) for value in values]
            return [x1, y1, x2, y2]
    if isinstance(raw_bbox, dict):
        values = [_to_float(raw_bbox.get(key)) for key in ("topleftx", "toplefty", "bottomrightx", "bottomrighty")]
        if all(value is not None for value in values):
            return [float(value) for value in values]
        values = [_to_float(raw_bbox.get(key)) for key in ("left", "top", "width", "height")]
        if all(value is not None for value in values):
            left, top, width, height = [float(value) for value in values]
            return [left, top, left + width, top + height]
    rect = obj.get("rect_params") or obj.get("rectParams") or obj.get("coordinate") or obj.get("coordinates")
    if isinstance(rect, dict):
        left = _to_float(rect.get("left") or rect.get("x"))
        top = _to_float(rect.get("top") or rect.get("y"))
        width = _to_float(rect.get("width") or rect.get("w"))
        height = _to_float(rect.get("height") or rect.get("h"))
        if None not in (left, top, width, height):
            return [float(left), float(top), float(left) + float(width), float(top) + float(height)]
    values = [_to_float(obj.get(key)) for key in ("left", "top", "width", "height")]
    if all(value is not None for value in values):
        left, top, width, height = [float(value) for value in values]
        return [left, top, left + width, top + height]
    values = [_to_float(obj.get(key)) for key in ("x1", "y1", "x2", "y2")]
    if all(value is not None for value in values):
        return [float(value) for value in values]
    return None


def load_deepstream_yolo26_worker_settings() -> DeepStreamYolo26WorkerSettings:
    runtime_dir = Path(os.getenv("OPENVISION_RUNTIME_DIR") or _default_runtime_dir()).expanduser()
    return DeepStreamYolo26WorkerSettings(
        enabled=_env_bool("OPENVISION_DEEPSTREAM_YOLO26_WORKER_ENABLED", False),
        jetson_base_url=os.getenv("OPENVISION_DEEPSTREAM_YOLO26_JETSON_URL", DEFAULT_BASE_URL),
        source=_clean_source(os.getenv("OPENVISION_DEEPSTREAM_YOLO26_SOURCE", "openvision_rv101_yolo26_deepstream")),
        runtime_dir=runtime_dir,
        status_path=_clean_status_path(os.getenv("OPENVISION_DEEPSTREAM_YOLO26_STATUS_PATH"), runtime_dir),
        deepstream_app_bin=os.getenv("OPENVISION_DEEPSTREAM_APP_BIN", "deepstream-app"),
        mosquitto_sub_bin=os.getenv("OPENVISION_MOSQUITTO_SUB_BIN", "mosquitto_sub"),
        mqtt_host=os.getenv("OPENVISION_DEEPSTREAM_YOLO26_MQTT_HOST", "127.0.0.1"),
        mqtt_port=_env_int("OPENVISION_DEEPSTREAM_YOLO26_MQTT_PORT", 1884),
        mqtt_topic_prefix=os.getenv("OPENVISION_DEEPSTREAM_YOLO26_MQTT_TOPIC_PREFIX", DEFAULT_TOPIC_PREFIX).strip("/") or DEFAULT_TOPIC_PREFIX,
        rtsp_port=_env_int("OPENVISION_DEEPSTREAM_YOLO26_RTSP_PORT", 8785),
        annotated_rtsp_enabled=_env_bool("OPENVISION_DEEPSTREAM_YOLO26_ANNOTATED_RTSP_ENABLED", True),
        annotated_rtsp_port=_env_int("OPENVISION_DEEPSTREAM_YOLO26_ANNOTATED_RTSP_PORT", 8795),
        annotated_udp_port=_env_int("OPENVISION_DEEPSTREAM_YOLO26_ANNOTATED_UDP_PORT", 5600),
        annotated_bitrate=_env_int("OPENVISION_DEEPSTREAM_YOLO26_ANNOTATED_BITRATE", 4000000),
        fake_sink_enabled=_env_bool("OPENVISION_DEEPSTREAM_YOLO26_FAKE_SINK_ENABLED", False),
        max_sessions=_env_int("OPENVISION_DEEPSTREAM_YOLO26_MAX_SESSIONS", 1),
        poll_interval_s=_env_float("OPENVISION_DEEPSTREAM_YOLO26_POLL_INTERVAL_S", 0.25),
        idle_poll_interval_s=_env_float("OPENVISION_DEEPSTREAM_YOLO26_IDLE_POLL_INTERVAL_S", 2.0),
        request_timeout_s=_env_float("OPENVISION_DEEPSTREAM_YOLO26_REQUEST_TIMEOUT_S", 2.0),
        stream_width=_env_int("OPENVISION_DEEPSTREAM_YOLO26_STREAM_WIDTH", 800),
        stream_height=_env_int("OPENVISION_DEEPSTREAM_YOLO26_STREAM_HEIGHT", 600),
        stream_fps=_env_float("OPENVISION_DEEPSTREAM_YOLO26_STREAM_FPS", 15.0),
        streammux_width=_env_int("OPENVISION_DEEPSTREAM_YOLO26_STREAMMUX_WIDTH", 800),
        streammux_height=_env_int("OPENVISION_DEEPSTREAM_YOLO26_STREAMMUX_HEIGHT", 600),
        min_confidence=_env_float("OPENVISION_DEEPSTREAM_YOLO26_MIN_CONFIDENCE", 0.35),
        infer_interval=_env_int("OPENVISION_DEEPSTREAM_YOLO26_INFER_INTERVAL", 0),
        tracker_enabled=_env_bool("OPENVISION_DEEPSTREAM_YOLO26_TRACKER_ENABLED", True),
        labels_path=_clean_path(os.getenv("OPENVISION_DEEPSTREAM_YOLO26_LABELS_PATH") or str(runtime_dir / "yolo26" / "yolo26_labels.txt")),
        onnx_path=_clean_path(os.getenv("OPENVISION_DEEPSTREAM_YOLO26_ONNX_PATH") or "/home/jay/DeepStream-Yolo/yolo26s.onnx"),
        engine_path=_clean_path(os.getenv("OPENVISION_DEEPSTREAM_YOLO26_ENGINE_PATH") or str(runtime_dir / "yolo26" / "openvision_yolo26.engine")),
        custom_lib_path=_clean_path(os.getenv("OPENVISION_DEEPSTREAM_YOLO26_CUSTOM_LIB_PATH") or "/home/jay/DeepStream-Yolo/nvdsinfer_custom_impl_Yolo/libnvdsinfer_custom_impl_Yolo.so"),
        tracker_config_path=_clean_path(os.getenv("OPENVISION_DEEPSTREAM_YOLO26_TRACKER_CONFIG_PATH") or "/opt/nvidia/deepstream/deepstream/samples/configs/deepstream-app/config_tracker_NvDCF_perf.yml"),
        mqtt_config_path=_clean_path(os.getenv("OPENVISION_DEEPSTREAM_YOLO26_MQTT_CONFIG_PATH")),
    )


def _status_path(settings: DeepStreamYolo26WorkerSettings) -> Path:
    if settings.status_path:
        return settings.status_path
    return settings.runtime_dir / "status" / "deepstream_yolo26_worker.json"


def _session_config_dir(settings: DeepStreamYolo26WorkerSettings, session_id: str) -> Path:
    return settings.runtime_dir / DEFAULT_RUNTIME_SUBDIR / "sessions" / _safe_segment(session_id)


def _default_runtime_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "runtime"


def _normalize_base_url(value: str) -> str:
    cleaned = value.strip() or DEFAULT_BASE_URL
    return cleaned if cleaned.endswith("/") else f"{cleaned}/"


def _absolute_url(base_url: str, path_or_url: str) -> str:
    if path_or_url.startswith(("http://", "https://")):
        if not _same_origin(base_url, path_or_url):
            raise ValueError("Jetson URL must stay on the configured Jetson API origin.")
        return path_or_url
    return urljoin(base_url, path_or_url.lstrip("/"))


def _ws_url(base_url: str, path: str) -> str:
    parsed = urlparse(_normalize_base_url(base_url))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{parsed.netloc}{path}"


def _same_origin(base_url: str, candidate_url: str) -> bool:
    base = urlparse(_normalize_base_url(base_url))
    candidate = urlparse(candidate_url)
    return base.scheme == candidate.scheme and base.netloc == candidate.netloc


def _tcp_connects(host: str, port: int, *, timeout_s: float) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=max(0.05, timeout_s)):
            return True
    except OSError:
        return False


def _strip_mqtt_topic(topic: str, line: str) -> str:
    if line.startswith(topic + " "):
        return line[len(topic) + 1 :].strip()
    return line


def _assert_safe_openvision_path(path: str | None, label: str) -> None:
    if not path:
        return
    marker = _forbidden_marker(path)
    if marker:
        raise ValueError(f"{label} path contains protected marker: {marker}")


def _forbidden_marker(value: str | None) -> str | None:
    lowered = str(value or "").lower()
    for marker in FORBIDDEN_RUNTIME_MARKERS:
        if marker in lowered:
            return marker
    return None


def _read_labels(path: Path | None) -> list[str]:
    if path is None or not path.is_file():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _safe_segment(value: str) -> str:
    cleaned = "".join(ch for ch in str(value or "") if ch.isalnum() or ch in {"_", "-"})
    return cleaned or "unknown"


def _clean_source(value: str | None) -> str:
    source = str(value or "openvision_rv101_yolo26_deepstream").strip()
    if _forbidden_marker(source):
        return "openvision_rv101_yolo26_deepstream"
    return source or "openvision_rv101_yolo26_deepstream"


def _clean_path(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _clean_status_path(value: str | None, runtime_dir: Path) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    try:
        path.relative_to(runtime_dir)
    except ValueError:
        return runtime_dir / "status" / "deepstream_yolo26_worker.json"
    return path


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


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _to_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None and value != "":
            return value
    return None


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _recent_fps(times: list[float]) -> float | None:
    if len(times) < 2:
        return None
    duration = max(1e-6, times[-1] - times[0])
    return round((len(times) - 1) / duration, 2)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the OpenVision DeepStream YOLO26 worker.")
    parser.add_argument("--once", action="store_true", help="Run a single poll and exit.")
    args = parser.parse_args(argv)
    worker = DeepStreamYolo26Worker(settings=load_deepstream_yolo26_worker_settings())
    if args.once:
        worker.run_once()
        return 0
    worker.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
