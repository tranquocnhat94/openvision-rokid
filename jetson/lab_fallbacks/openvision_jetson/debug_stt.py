"""Local debug STT sidecar for seeing completed spoken turns."""

from __future__ import annotations

import asyncio
import base64
import audioop
from dataclasses import dataclass, field
import io
import time
from typing import Any, Awaitable, Callable
import wave

import httpx

from .contracts import to_jsonable, utc_now
from .event_store import InMemoryEventStore
from .settings import load_runtime_settings


@dataclass(frozen=True, slots=True)
class DebugSttSettings:
    enabled: bool = False
    transcribe_url: str = "http://127.0.0.1:9460/inference"
    health_url: str = "http://127.0.0.1:9460/health"
    warm_url: str = "http://127.0.0.1:9460/warm"
    language: str = "vi"
    profile: str = "v2_debug_sentence"
    beam_size: int = 5
    vad_filter: bool = True
    hotwords: str = ""
    timeout_s: float = 20.0
    min_audio_ms: int = 350
    max_audio_ms: int = 12_000


@dataclass(slots=True)
class _TurnBuffer:
    chunks: list[bytes] = field(default_factory=list)
    sample_rate: int = 24_000
    channels: int = 1
    source: str = ""
    started_at: str = field(default_factory=utc_now)


HttpPost = Callable[[DebugSttSettings, bytes, str], Awaitable[dict[str, Any]]]


class DebugSttRuntime:
    def __init__(
        self,
        *,
        events: InMemoryEventStore,
        settings_provider: Callable[[], DebugSttSettings] = None,
        http_post: HttpPost | None = None,
    ) -> None:
        self._events = events
        self._settings_provider = settings_provider or load_debug_stt_settings
        self._http_post = http_post or _post_wav_to_worker
        self._buffers: dict[str, _TurnBuffer] = {}
        self._entries: list[dict[str, Any]] = []
        self._tasks: set[asyncio.Task[None]] = set()
        self._last_error: str | None = None

    def status(self) -> dict[str, Any]:
        settings = self._settings_provider()
        return {
            "enabled": settings.enabled,
            "status": "enabled" if settings.enabled else "disabled",
            "backend": "phowhisper_http",
            "transcribe_url": settings.transcribe_url if settings.enabled else None,
            "health_url": settings.health_url if settings.enabled else None,
            "turn_buffers": len(self._buffers),
            "transcript_count": len(self._entries),
            "last_error": self._last_error,
        }

    def transcripts(self, *, session_id: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        entries = self._entries
        if session_id:
            entries = [entry for entry in entries if entry.get("session_id") == session_id]
        return to_jsonable(entries[-limit:])

    def accept_gate_decision(
        self,
        *,
        session_id: str,
        chunks: list[bytes],
        transition: str | None,
        sample_rate: int = 24_000,
        channels: int = 1,
        source: str = "",
    ) -> None:
        settings = self._settings_provider()
        if not settings.enabled:
            self._buffers.pop(session_id, None)
            return
        if transition == "opened":
            self._buffers[session_id] = _TurnBuffer(sample_rate=sample_rate, channels=channels, source=source)
            self._events.add(
                "debug_stt",
                "turn_started",
                {"source": source, "sample_rate": sample_rate, "channels": channels},
                session_id=session_id,
            )
        if chunks:
            buffer = self._buffers.setdefault(
                session_id,
                _TurnBuffer(sample_rate=sample_rate, channels=channels, source=source),
            )
            buffer.sample_rate = sample_rate or buffer.sample_rate
            buffer.channels = channels or buffer.channels
            buffer.source = source or buffer.source
            buffer.chunks.extend(chunks)
            _trim_buffer_to_max_ms(buffer, settings.max_audio_ms)
        if transition == "closed":
            buffer = self._buffers.pop(session_id, None)
            if not buffer:
                return
            pcm = b"".join(buffer.chunks)
            duration_ms = _duration_ms(pcm, sample_rate=buffer.sample_rate, channels=buffer.channels)
            if duration_ms < settings.min_audio_ms:
                self._events.add(
                    "debug_stt",
                    "turn_too_short",
                    {"duration_ms": duration_ms, "source": buffer.source},
                    session_id=session_id,
                )
                return
            wav_bytes = pcm16_to_wav_16k_mono(pcm, sample_rate=buffer.sample_rate, channels=buffer.channels)
            task = asyncio.create_task(
                self._transcribe_turn(
                    session_id=session_id,
                    wav_bytes=wav_bytes,
                    duration_ms=duration_ms,
                    source=buffer.source,
                    settings=settings,
                )
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def warm(self) -> dict[str, Any]:
        settings = self._settings_provider()
        if not settings.enabled:
            return {"enabled": False, "status": "disabled"}
        async with httpx.AsyncClient(timeout=settings.timeout_s) as client:
            response = await client.get(settings.warm_url)
            response.raise_for_status()
            payload = response.json()
        self._events.add("debug_stt", "warmed", {"backend": payload.get("backend"), "modelLoaded": payload.get("modelLoaded")})
        return payload

    async def wait_for_idle(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks))

    async def _transcribe_turn(
        self,
        *,
        session_id: str,
        wav_bytes: bytes,
        duration_ms: int,
        source: str,
        settings: DebugSttSettings,
    ) -> None:
        started = time.perf_counter()
        try:
            payload = await self._http_post(settings, wav_bytes, session_id)
            text = str(payload.get("text") or "").strip()
            wall_ms = int((time.perf_counter() - started) * 1000)
            entry = {
                "session_id": session_id,
                "text": text,
                "status": "ok",
                "backend": payload.get("backend") or "phowhisper_http",
                "language": payload.get("language"),
                "language_probability": payload.get("languageProbability"),
                "transcribe_ms": payload.get("transcribeMs"),
                "wall_ms": wall_ms,
                "duration_ms": duration_ms,
                "source": source,
                "timestamp": utc_now(),
            }
            self._entries.append(entry)
            self._entries = self._entries[-120:]
            self._last_error = None
            self._events.add(
                "debug_stt",
                "transcript",
                {"text": text[:160], "chars": len(text), "duration_ms": duration_ms, "wall_ms": wall_ms},
                session_id=session_id,
            )
        except Exception as exc:
            self._last_error = f"{exc.__class__.__name__}: {exc}"
            self._events.add(
                "debug_stt",
                "error",
                {"error": self._last_error, "duration_ms": duration_ms, "source": source},
                session_id=session_id,
                severity="warning",
            )


def load_debug_stt_settings() -> DebugSttSettings:
    runtime = load_runtime_settings()
    return DebugSttSettings(
        enabled=runtime.debug_stt_enabled,
        transcribe_url=runtime.debug_stt_transcribe_url,
        health_url=runtime.debug_stt_health_url,
        warm_url=runtime.debug_stt_warm_url,
        language=runtime.debug_stt_language,
        profile=runtime.debug_stt_profile,
        beam_size=runtime.debug_stt_beam_size,
        vad_filter=runtime.debug_stt_vad_filter,
        hotwords=runtime.debug_stt_hotwords,
        timeout_s=runtime.debug_stt_timeout_s,
        min_audio_ms=runtime.debug_stt_min_audio_ms,
        max_audio_ms=runtime.debug_stt_max_audio_ms,
    )


def pcm16_to_wav_16k_mono(pcm: bytes, *, sample_rate: int, channels: int) -> bytes:
    clean_rate = int(sample_rate or 24_000)
    clean_channels = max(1, int(channels or 1))
    audio = pcm[: len(pcm) - (len(pcm) % 2)]
    if clean_channels == 2:
        audio = audioop.tomono(audio, 2, 0.5, 0.5)
        clean_channels = 1
    elif clean_channels != 1:
        clean_channels = 1
    if clean_rate != 16_000:
        audio, _state = audioop.ratecv(audio, 2, clean_channels, clean_rate, 16_000, None)
    wav = io.BytesIO()
    with wave.open(wav, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16_000)
        wav_file.writeframes(audio)
    return wav.getvalue()


async def _post_wav_to_worker(settings: DebugSttSettings, wav_bytes: bytes, session_id: str) -> dict[str, Any]:
    headers = {
        "Content-Type": "audio/wav",
        "X-Rokid-Session-Id": session_id,
        "X-Rokid-Language": settings.language,
        "X-Rokid-Profile": settings.profile,
        "X-Rokid-Beam-Size": str(settings.beam_size),
        "X-Rokid-Vad-Filter": "true" if settings.vad_filter else "false",
    }
    if settings.hotwords.strip():
        headers["X-Rokid-Hotwords-Base64"] = base64.b64encode(settings.hotwords.strip().encode("utf-8")).decode("ascii")
    async with httpx.AsyncClient(timeout=settings.timeout_s) as client:
        response = await client.post(settings.transcribe_url, content=wav_bytes, headers=headers)
        response.raise_for_status()
        return response.json()


def _duration_ms(pcm: bytes, *, sample_rate: int, channels: int) -> int:
    samples = len(pcm) // 2
    denom = max(1, int(sample_rate or 24_000) * max(1, int(channels or 1)))
    return int(samples * 1000 / denom)


def _trim_buffer_to_max_ms(buffer: _TurnBuffer, max_audio_ms: int) -> None:
    max_bytes = int(buffer.sample_rate * max(1, buffer.channels) * 2 * max_audio_ms / 1000)
    if max_bytes <= 0:
        return
    total = sum(len(chunk) for chunk in buffer.chunks)
    while buffer.chunks and total > max_bytes:
        removed = buffer.chunks.pop(0)
        total -= len(removed)
