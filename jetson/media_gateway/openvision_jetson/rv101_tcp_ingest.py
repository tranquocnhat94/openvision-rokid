"""RV101 TCP media ingest for the clean v2 glasses contract."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
import socket
import struct
from typing import Any, Awaitable, Callable

from .audio_signal import is_voice_like, pcm16_metrics
from .contracts import utc_now
from .event_store import InMemoryEventStore
from .media_gateway import MediaGateway


FRAME_MAGIC = b"RVS1"
FRAME_HEADER = struct.Struct(">HHII")
TYPE_VIDEO_HELLO = 1
TYPE_VIDEO_SAMPLE = 2
TYPE_AUDIO_HELLO = 3
TYPE_AUDIO_SAMPLE = 4
MAX_HEADER_BYTES = 64 * 1024
MAX_VIDEO_PAYLOAD_BYTES = 8 * 1024 * 1024
MAX_AUDIO_PAYLOAD_BYTES = 512 * 1024

AudioPcmHandler = Callable[[str, bytes], Awaitable[None] | None]
AudioCloseHandler = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class Rv101TcpIngestSettings:
    enabled: bool
    bind_host: str
    advertised_host: str
    video_port: int
    audio_port: int


class Rv101TcpIngestService:
    def __init__(
        self,
        *,
        media: MediaGateway,
        events: InMemoryEventStore,
        settings_provider: Callable[[], Rv101TcpIngestSettings] = None,
        audio_pcm_handler: AudioPcmHandler | None = None,
        audio_close_handler: AudioCloseHandler | None = None,
    ) -> None:
        self._media = media
        self._events = events
        self._settings_provider = settings_provider or load_rv101_tcp_ingest_settings
        self._audio_pcm_handler = audio_pcm_handler
        self._audio_close_handler = audio_close_handler
        self._video_server: asyncio.AbstractServer | None = None
        self._audio_server: asyncio.AbstractServer | None = None
        self._settings = self._settings_provider()
        self._started_at: str | None = None
        self._last_error: str | None = None

    async def start(self) -> dict[str, Any]:
        self._settings = self._settings_provider()
        if not self._settings.enabled:
            return self.status()
        if self._video_server or self._audio_server:
            return self.status()
        try:
            self._video_server = await asyncio.start_server(
                lambda reader, writer: self._handle_stream("video", reader, writer),
                host=self._settings.bind_host,
                port=self._settings.video_port,
            )
            self._audio_server = await asyncio.start_server(
                lambda reader, writer: self._handle_stream("audio", reader, writer),
                host=self._settings.bind_host,
                port=self._settings.audio_port,
            )
            self._started_at = utc_now()
            self._last_error = None
            self._events.add(
                "rv101_ingest",
                "started",
                {
                    "bind_host": self._settings.bind_host,
                    "video_port": self.video_port,
                    "audio_port": self.audio_port,
                },
            )
        except OSError as exc:
            await self.stop()
            self._last_error = f"{exc.__class__.__name__}: {exc}"
            self._events.add("rv101_ingest", "start_failed", {"error": self._last_error}, severity="error")
        return self.status()

    async def stop(self) -> dict[str, Any]:
        servers = [server for server in [self._video_server, self._audio_server] if server]
        self._video_server = None
        self._audio_server = None
        for server in servers:
            server.close()
        for server in servers:
            await server.wait_closed()
        if servers:
            self._events.add("rv101_ingest", "stopped", {})
        return self.status()

    @property
    def video_port(self) -> int:
        return _server_port(self._video_server) or self._settings.video_port

    @property
    def audio_port(self) -> int:
        return _server_port(self._audio_server) or self._settings.audio_port

    def status(self) -> dict[str, Any]:
        running = bool(self._video_server and self._audio_server)
        return {
            "enabled": self._settings.enabled,
            "status": "running" if running else "disabled" if not self._settings.enabled else "stopped",
            "bind_host": self._settings.bind_host,
            "advertised_host": self._settings.advertised_host,
            "video_port": self.video_port,
            "audio_port": self.audio_port,
            "started_at": self._started_at,
            "last_error": self._last_error,
            "protocol": "rvs1_tcp",
        }

    async def _handle_stream(
        self,
        kind: str,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        peer = writer.get_extra_info("peername")
        seen_audio_sessions: set[str] = set()
        self._events.add("rv101_ingest", "client_connected", {"kind": kind, "peer": str(peer)})
        try:
            while True:
                frame = await read_rvs1_frame(
                    reader,
                    max_payload_bytes=MAX_VIDEO_PAYLOAD_BYTES if kind == "video" else MAX_AUDIO_PAYLOAD_BYTES,
                )
                if kind == "video":
                    self._handle_video_frame(frame.header, frame.payload, frame.message_type)
                else:
                    seen_audio_sessions.add(_session_id(frame.header))
                    await self._handle_audio_frame(frame.header, frame.payload, frame.message_type)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        except ValueError as exc:
            self._events.add(
                "rv101_ingest",
                "protocol_error",
                {"kind": kind, "error": str(exc)},
                severity="warning",
            )
        finally:
            writer.close()
            await writer.wait_closed()
            if kind == "audio" and self._audio_close_handler:
                for session_id in sorted(seen_audio_sessions):
                    self._audio_close_handler(session_id)
            self._events.add("rv101_ingest", "client_disconnected", {"kind": kind, "peer": str(peer)})

    def _handle_video_frame(self, header: dict[str, Any], payload: bytes, message_type: int) -> None:
        session_id = _session_id(header)
        if message_type == TYPE_VIDEO_HELLO:
            self._media.record_video_heartbeat(
                session_id=session_id,
                transport="rv101_tcp",
                codec=str(header.get("codec") or "video/avc"),
                width=_to_int(header.get("width")),
                height=_to_int(header.get("height")),
                fps=_to_float(header.get("targetFps")),
            )
            return
        if message_type != TYPE_VIDEO_SAMPLE:
            return
        self._media.record_video_sample(
            session_id=session_id,
            transport="rv101_tcp",
            codec="video/avc",
            payload_bytes=len(payload),
            is_keyframe=bool(header.get("isKeyframe")),
            width=_to_int(header.get("width")),
            height=_to_int(header.get("height")),
        )

    async def _handle_audio_frame(self, header: dict[str, Any], payload: bytes, message_type: int) -> None:
        session_id = _session_id(header)
        if message_type == TYPE_AUDIO_HELLO:
            self._media.record_audio_metrics(
                session_id=session_id,
                transport="rv101_tcp",
                sample_rate=_to_int(header.get("sampleRateHz"), 24000) or 24000,
                channels=_to_int(header.get("channels"), 1) or 1,
                chunk_count=0,
                strong_chunk_count=0,
                source=str(header.get("audioSource") or "rv101"),
            )
            return
        if message_type != TYPE_AUDIO_SAMPLE:
            return
        sample_rate = _to_int(header.get("sampleRateHz"), 24000) or 24000
        channels = _to_int(header.get("channels"), 1) or 1
        metrics = pcm16_metrics(payload)
        strong = is_voice_like(metrics)
        self._media.record_audio_sample(
            session_id=session_id,
            transport="rv101_tcp",
            sample_rate=sample_rate,
            channels=channels,
            payload_bytes=len(payload),
            strong=strong,
            avg_abs=float(metrics.get("avg_abs") or 0.0),
            peak_abs=int(metrics.get("peak_abs") or 0),
            non_silent_ratio=float(metrics.get("non_silent_ratio") or 0.0),
            source=str(header.get("audioSource") or "rv101"),
        )
        if self._audio_pcm_handler:
            maybe_awaitable = self._audio_pcm_handler(session_id, payload)
            if maybe_awaitable:
                await maybe_awaitable


@dataclass(frozen=True, slots=True)
class Rvs1Frame:
    version: int
    message_type: int
    header: dict[str, Any]
    payload: bytes


async def read_rvs1_frame(reader: asyncio.StreamReader, *, max_payload_bytes: int) -> Rvs1Frame:
    magic = await reader.readexactly(4)
    if magic != FRAME_MAGIC:
        raise ValueError("Invalid RVS1 frame magic")
    version, message_type, header_len, payload_len = FRAME_HEADER.unpack(await reader.readexactly(FRAME_HEADER.size))
    if version != 1:
        raise ValueError(f"Unsupported RVS1 version: {version}")
    if header_len > MAX_HEADER_BYTES:
        raise ValueError("RVS1 header is too large")
    if payload_len > max_payload_bytes:
        raise ValueError("RVS1 payload is too large")
    header_raw = await reader.readexactly(header_len)
    payload = await reader.readexactly(payload_len)
    try:
        header = json.loads(header_raw.decode("utf-8")) if header_raw else {}
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid RVS1 JSON header") from exc
    if not isinstance(header, dict):
        raise ValueError("RVS1 header must be a JSON object")
    return Rvs1Frame(version=version, message_type=message_type, header=header, payload=payload)


def build_rvs1_frame(message_type: int, header: dict[str, Any], payload: bytes = b"") -> bytes:
    header_bytes = json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return FRAME_MAGIC + FRAME_HEADER.pack(1, message_type, len(header_bytes), len(payload)) + header_bytes + payload


def load_rv101_tcp_ingest_settings() -> Rv101TcpIngestSettings:
    bind_host = os.getenv("OPENVISION_RV101_BIND_HOST", "0.0.0.0")
    return Rv101TcpIngestSettings(
        enabled=_env_bool("OPENVISION_RV101_TCP_INGEST", default=False),
        bind_host=bind_host,
        advertised_host=_advertised_host_for(bind_host),
        video_port=_env_int("OPENVISION_RV101_VIDEO_PORT", 8770),
        audio_port=_env_int("OPENVISION_RV101_AUDIO_PORT", 8771),
    )


def _advertised_host_for(bind_host: str) -> str:
    explicit = _clean_env("OPENVISION_RV101_ADVERTISED_HOST")
    if explicit:
        return explicit
    shared = _clean_env("OPENVISION_JETSON_LAN_IP") or _clean_env("OPENVISION_ADVERTISED_HOST")
    if shared:
        return shared
    if bind_host not in {"0.0.0.0", "::", ""}:
        return bind_host
    return _detect_lan_ip() or "0.0.0.0"


def _detect_lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            host = sock.getsockname()[0]
    except OSError:
        return None
    if host.startswith("127."):
        return None
    return host


def _server_port(server: asyncio.AbstractServer | None) -> int | None:
    if not server or not server.sockets:
        return None
    return int(server.sockets[0].getsockname()[1])


def _session_id(header: dict[str, Any]) -> str:
    return str(header.get("sessionId") or "rv101_unknown")


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


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _clean_env(name: str) -> str | None:
    value = os.getenv(name)
    if not value:
        return None
    cleaned = value.strip()
    return cleaned or None
