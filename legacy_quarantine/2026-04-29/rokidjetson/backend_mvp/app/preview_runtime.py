from __future__ import annotations

import os
import queue
import subprocess
import threading
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .browser_media_runtime import LatestFrame


@dataclass
class PreviewProcess:
    session_id: str
    playlist_path: Path
    width: int = 0
    height: int = 0
    target_fps: int = 0
    target_bitrate: int = 0
    profile_label: str | None = None
    hls_process: subprocess.Popen[bytes] | None = None
    frame_bus_process: subprocess.Popen[bytes] | None = None
    frame_bus_enabled: bool = False
    frame_bus_thread: threading.Thread | None = None
    local_process: subprocess.Popen[bytes] | None = None
    local_preview_uses_stdin: bool = True
    payload_queue: queue.Queue[bytes | None] | None = None
    payload_thread: threading.Thread | None = None


class PreviewRuntime:
    def __init__(
        self,
        *,
        append_session_log: Callable[[Any, str, dict[str, Any]], None],
        session_lookup: Callable[[str], Any | None],
        session_preview_dir_provider: Callable[[Any], Path],
        preview_processes: dict[str, PreviewProcess],
        latest_frames: dict[str, LatestFrame],
        latest_ai_results: dict[str, dict[str, Any]],
        latest_codec_config_frames: dict[str, bytes],
        latest_preview_session_id_getter: Callable[[], str | None],
        latest_preview_session_id_setter: Callable[[str | None], None],
        now_ms_provider: Callable[[], int],
        enable_hls_preview: bool,
        enable_frame_bus: bool,
        ai_requires_frame_bus_provider: Callable[[Any], bool],
        enable_local_preview: bool,
        raw_frame_target_fps: int,
        preview_jpeg_quality: int,
        preview_pipe_queue_max: int,
        local_preview_display: str,
        local_preview_xauthority: str,
        local_preview_mode: str,
        local_preview_sink: str,
        local_preview_port: int,
    ) -> None:
        self._append_session_log = append_session_log
        self._session_lookup = session_lookup
        self._session_preview_dir_provider = session_preview_dir_provider
        self.preview_processes = preview_processes
        self._latest_frames = latest_frames
        self._latest_ai_results = latest_ai_results
        self._latest_codec_config_frames = latest_codec_config_frames
        self._latest_preview_session_id_getter = latest_preview_session_id_getter
        self._latest_preview_session_id_setter = latest_preview_session_id_setter
        self._now_ms_provider = now_ms_provider
        self._enable_hls_preview = enable_hls_preview
        self._enable_frame_bus = enable_frame_bus
        self._ai_requires_frame_bus_provider = ai_requires_frame_bus_provider
        self._enable_local_preview = enable_local_preview
        self._raw_frame_target_fps = raw_frame_target_fps
        self._preview_jpeg_quality = preview_jpeg_quality
        self._preview_pipe_queue_max = preview_pipe_queue_max
        self._local_preview_display = local_preview_display
        self._local_preview_xauthority = local_preview_xauthority
        self._local_preview_mode = local_preview_mode
        self._local_preview_sink = local_preview_sink
        self._local_preview_port = local_preview_port

    def frame_bus_enabled_for_session(self, session: Any) -> bool:
        return self._enable_frame_bus or self._ai_requires_frame_bus_provider(session)

    def preview_required_for_session(self, session: Any) -> bool:
        return self._enable_hls_preview or self._enable_local_preview or self.frame_bus_enabled_for_session(session)

    def needs_preview_restart(
        self,
        preview: PreviewProcess,
        *,
        width: int,
        height: int,
        target_fps: int,
        target_bitrate: int,
        profile_label: str | None,
        frame_bus_enabled: bool | None = None,
    ) -> bool:
        return any(
            (
                preview.width != width,
                preview.height != height,
                preview.target_fps != target_fps,
                preview.target_bitrate != target_bitrate,
                (preview.profile_label or "") != (profile_label or ""),
                frame_bus_enabled is not None and preview.frame_bus_enabled != frame_bus_enabled,
            )
        )

    def stop_preview_process(self, session: Any, reason: str) -> None:
        preview = self.preview_processes.pop(session.session_id, None)
        self._latest_frames.pop(session.session_id, None)
        self._latest_ai_results.pop(session.session_id, None)
        if self._latest_preview_session_id_getter() == session.session_id:
            self._latest_preview_session_id_setter(None)
        if preview is None:
            return
        if preview.payload_queue is not None:
            with suppress(Exception):
                preview.payload_queue.put_nowait(None)
        for process in (preview.hls_process, preview.frame_bus_process, preview.local_process):
            if process is None:
                continue
            stdin = process.stdin
            if stdin is not None:
                with suppress(Exception):
                    stdin.flush()
                with suppress(Exception):
                    stdin.close()
            with suppress(Exception):
                process.terminate()
            with suppress(Exception):
                process.wait(timeout=1)
        if (
            preview.payload_thread is not None
            and preview.payload_thread.is_alive()
            and preview.payload_thread is not threading.current_thread()
        ):
            preview.payload_thread.join(timeout=1.0)
        self._append_session_log(
            session,
            "preview_stopped",
            {
                "reason": reason,
                "previewUrl": session.preview_url,
            },
        )

    def start_preview_process(
        self,
        session: Any,
        *,
        width: int,
        height: int,
        target_fps: int,
        target_bitrate: int,
        profile_label: str | None,
    ) -> None:
        self.stop_preview_process(session, reason="restart")
        frame_bus_enabled = self.frame_bus_enabled_for_session(session)
        if not (self._enable_hls_preview or frame_bus_enabled or self._enable_local_preview):
            self._append_session_log(
                session,
                "preview_skipped",
                {
                    "reason": "no_preview_sink_enabled",
                    "hlsEnabled": self._enable_hls_preview,
                    "frameBusEnabled": frame_bus_enabled,
                    "localPreviewEnabled": self._enable_local_preview,
                },
            )
            return

        preview_dir = self._session_preview_dir_provider(session)
        preview_dir.mkdir(parents=True, exist_ok=True)
        for child in preview_dir.glob("*"):
            if child.is_file():
                child.unlink(missing_ok=True)

        playlist_path = preview_dir / "index.m3u8"
        segment_pattern = preview_dir / "seg_%03d.ts"
        hls_process: subprocess.Popen[bytes] | None = None
        frame_bus_process: subprocess.Popen[bytes] | None = None
        frame_bus_thread: threading.Thread | None = None
        local_process: subprocess.Popen[bytes] | None = None

        if self._enable_hls_preview:
            command = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-fflags",
                "nobuffer",
                "-flags",
                "low_delay",
                "-analyzeduration",
                "0",
                "-probesize",
                "32",
                "-f",
                "h264",
                "-i",
                "pipe:0",
                "-an",
                "-c:v",
                "copy",
                "-f",
                "hls",
                "-hls_time",
                "1",
                "-hls_list_size",
                "6",
                "-hls_flags",
                "delete_segments+append_list+omit_endlist+independent_segments",
                "-hls_segment_filename",
                str(segment_pattern),
                str(playlist_path),
            ]
            hls_process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )

        if frame_bus_enabled and width > 0 and height > 0:
            frame_bus_command = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-fflags",
                "nobuffer",
                "-flags",
                "low_delay",
                "-analyzeduration",
                "0",
                "-probesize",
                "32",
                "-f",
                "h264",
                "-i",
                "pipe:0",
                "-an",
                "-vf",
                f"fps={max(1, min(target_fps or self._raw_frame_target_fps, self._raw_frame_target_fps))}",
                "-pix_fmt",
                "bgr24",
                "-f",
                "rawvideo",
                "pipe:1",
            ]
            frame_bus_process = subprocess.Popen(
                frame_bus_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
            frame_bus_thread = threading.Thread(
                target=self._consume_raw_frame_output,
                args=(session.session_id, width, height, frame_bus_process.stdout),
                daemon=True,
                name=f"rokid-framebus-{session.session_id}",
            )
            frame_bus_thread.start()

        if self._enable_local_preview:
            local_env = os.environ.copy()
            local_env["DISPLAY"] = self._local_preview_display
            local_env["XAUTHORITY"] = self._local_preview_xauthority
            local_preview_uses_stdin = self._local_preview_mode != "ffplay_overlay"
            local_process = subprocess.Popen(
                self.local_preview_command(session.session_id),
                stdin=subprocess.PIPE if local_preview_uses_stdin else subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                bufsize=0,
                env=local_env,
            )
        else:
            local_preview_uses_stdin = True

        preview = PreviewProcess(
            session_id=session.session_id,
            playlist_path=playlist_path,
            width=width,
            height=height,
            target_fps=target_fps,
            target_bitrate=target_bitrate,
            profile_label=profile_label,
            hls_process=hls_process,
            frame_bus_process=frame_bus_process,
            frame_bus_enabled=frame_bus_enabled,
            frame_bus_thread=frame_bus_thread,
            local_process=local_process,
            local_preview_uses_stdin=local_preview_uses_stdin,
            payload_queue=queue.Queue(maxsize=self._preview_pipe_queue_max),
        )
        preview.payload_thread = threading.Thread(
            target=self._consume_preview_payloads,
            args=(session.session_id, preview),
            daemon=True,
            name=f"rokid-preview-pipe-{session.session_id}",
        )
        preview.payload_thread.start()
        self.preview_processes[session.session_id] = preview

        cached_codec_config = self._latest_codec_config_frames.get(session.session_id)
        if cached_codec_config:
            try:
                self._queue_preview_bytes(preview, cached_codec_config)
            except Exception as error:
                session.last_error = f"preview_codec_config_failed: {error}"
                self._append_session_log(
                    session,
                    "preview_error",
                    {
                        "error": str(error),
                        "previewUrl": session.preview_url,
                        "stage": "codec_config_bootstrap",
                    },
                )
                self.stop_preview_process(session, reason="codec_config_bootstrap_failed")
                return

        self._latest_preview_session_id_setter(session.session_id)
        self._append_session_log(
            session,
            "preview_started",
            {
                "width": width,
                "height": height,
                "targetFps": target_fps,
                "targetBitrate": target_bitrate,
                "profileLabel": profile_label,
                "previewUrl": session.preview_url,
                "hlsEnabled": self._enable_hls_preview,
                "frameBusEnabled": frame_bus_enabled,
                "localPreviewEnabled": self._enable_local_preview,
                "localPreviewMode": self._local_preview_mode,
            },
        )

    def write_preview_payload(self, session: Any, payload: bytes) -> None:
        preview = self.preview_processes.get(session.session_id)
        if preview is None:
            return
        critical_processes = [
            process
            for process in (preview.hls_process, preview.frame_bus_process)
            if process is not None
        ]
        if preview.local_process is not None and preview.local_process.poll() is not None:
            preview.local_process = None
            self._append_session_log(
                session,
                "preview_local_exited",
                {"previewUrl": session.preview_url},
            )
        active_processes = self._preview_process_targets(preview)
        if not active_processes and not critical_processes:
            return
        if any(process.poll() is not None for process in critical_processes):
            self.stop_preview_process(session, reason="ffmpeg_exited")
            return
        try:
            self._queue_preview_bytes(preview, payload)
        except Exception as error:
            session.last_error = f"preview_write_failed: {error}"
            self._append_session_log(
                session,
                "preview_error",
                {"error": str(error), "previewUrl": session.preview_url},
            )
            self.stop_preview_process(session, reason="write_failed")

    def local_preview_command(self, session_id: str) -> list[str]:
        if self._local_preview_mode == "ffplay_overlay":
            return [
                "ffplay",
                "-hide_banner",
                "-loglevel",
                "error",
                "-fflags",
                "nobuffer",
                "-flags",
                "low_delay",
                "-framedrop",
                "-sync",
                "ext",
                "-window_title",
                "Rokid AI Overlay",
                f"http://127.0.0.1:{self._local_preview_port}/preview/sessions/{session_id}/live.mjpg",
            ]

        if self._local_preview_mode == "ffplay":
            return [
                "ffplay",
                "-hide_banner",
                "-loglevel",
                "error",
                "-fflags",
                "nobuffer",
                "-flags",
                "low_delay",
                "-framedrop",
                "-sync",
                "ext",
                "-probesize",
                "32",
                "-analyzeduration",
                "0",
                "-window_title",
                "Rokid Live Preview",
                "-f",
                "h264",
                "-i",
                "pipe:0",
            ]

        command = [
            "gst-launch-1.0",
            "-q",
            "fdsrc",
            "fd=0",
            "do-timestamp=true",
            "!",
            "queue",
            "leaky=downstream",
            "max-size-buffers=4",
            "max-size-bytes=0",
            "max-size-time=0",
            "!",
            "h264parse",
            "config-interval=-1",
            "disable-passthrough=true",
            "!",
            "nvv4l2decoder",
            "disable-dpb=true",
            "enable-max-performance=true",
            "!",
            "queue",
            "leaky=downstream",
            "max-size-buffers=2",
            "max-size-bytes=0",
            "max-size-time=0",
        ]

        if self._local_preview_sink == "nv3dsink":
            command += ["!", "nv3dsink", "sync=false"]
        elif self._local_preview_sink == "nveglglessink":
            command += ["!", "nvegltransform", "!", "nveglglessink", "sync=false"]
        elif self._local_preview_sink == "ximagesink":
            command += ["!", "nvvidconv", "!", "videoconvert", "!", "ximagesink", "sync=false"]
        else:
            command += ["!", "nvvidconv", "!", "xvimagesink", "sync=false"]

        return command

    def _preview_process_targets(self, preview: PreviewProcess) -> list[subprocess.Popen[bytes]]:
        local_process = preview.local_process if preview.local_preview_uses_stdin else None
        return [
            process
            for process in (preview.hls_process, preview.frame_bus_process, local_process)
            if process is not None
        ]

    def _push_preview_bytes(self, preview: PreviewProcess, payload: bytes) -> None:
        for process in self._preview_process_targets(preview):
            stdin = process.stdin
            if stdin is None:
                raise RuntimeError("preview stdin missing")
            stdin.write(payload)
            stdin.flush()

    def _queue_preview_bytes(self, preview: PreviewProcess, payload: bytes) -> None:
        if not payload:
            return
        payload_queue = preview.payload_queue
        if payload_queue is None:
            self._push_preview_bytes(preview, payload)
            return
        try:
            payload_queue.put_nowait(payload)
            return
        except queue.Full:
            pass

        with suppress(Exception):
            while payload_queue.qsize() > max(1, self._preview_pipe_queue_max - 2):
                payload_queue.get_nowait()
        with suppress(Exception):
            payload_queue.put_nowait(payload)

    def _consume_preview_payloads(self, session_id: str, preview: PreviewProcess) -> None:
        payload_queue = preview.payload_queue
        if payload_queue is None:
            return
        while True:
            payload = payload_queue.get()
            if payload is None:
                return
            try:
                self._push_preview_bytes(preview, payload)
            except Exception as error:
                session = self._session_lookup(session_id)
                if session is not None:
                    session.last_error = f"preview_write_failed: {error}"
                    self._append_session_log(
                        session,
                        "preview_error",
                        {"error": str(error), "previewUrl": session.preview_url},
                    )
                    self.stop_preview_process(session, reason="write_failed")
                return

    def _consume_raw_frame_output(self, session_id: str, width: int, height: int, stream: Any) -> None:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        frame_size = max(1, width * height * 3)
        buffer = bytearray()
        sequence = 0
        while True:
            chunk = stream.read(min(262144, max(4096, frame_size - len(buffer))))
            if not chunk:
                return
            buffer.extend(chunk)
            while len(buffer) >= frame_size:
                frame_bytes = bytes(buffer[:frame_size])
                del buffer[:frame_size]
                frame = np.frombuffer(frame_bytes, dtype=np.uint8).reshape((height, width, 3))
                ok, encoded = cv2.imencode(
                    ".jpg",
                    frame,
                    [int(cv2.IMWRITE_JPEG_QUALITY), self._preview_jpeg_quality],
                )
                if not ok:
                    continue
                sequence += 1
                self._latest_frames[session_id] = LatestFrame(
                    session_id=session_id,
                    width=width,
                    height=height,
                    sequence=sequence,
                    timestamp_ms=self._now_ms_provider(),
                    bgr_bytes=frame_bytes,
                    jpeg_bytes=encoded.tobytes(),
                )
