import asyncio
import struct
import unittest
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from app.browser_media_runtime import (
    BrowserMediaRuntime,
    LatestFrame,
    _pcm_energy_stats,
)


@dataclass
class _DummySession:
    session_id: str
    video_connected: bool = True
    audio_connected: bool = True
    video_peer: str | None = "browser"
    audio_peer: str | None = "browser"
    video_frames: int = 0
    video_bytes: int = 0
    last_video_seq: int = 0
    last_video_timestamp_ms: int | None = None
    rotation_degrees: int = 0
    audio_packets: int = 0
    audio_bytes: int = 0
    last_audio_timestamp_ms: int | None = None
    latest_audio_stats: dict[str, Any] = field(default_factory=dict)
    audio_path: str = "/tmp/test-browser-audio.pcm"
    _audio_payloads: list[bytes] = field(default_factory=list)

    def append_audio_payload(self, payload: bytes, *, max_buffer_bytes: int) -> None:
        del max_buffer_bytes
        self._audio_payloads.append(payload)


class _ArchiveWriter:
    def __init__(self) -> None:
        self.items: list[tuple[str, bytes]] = []

    def append(self, path: str, payload: bytes) -> None:
        self.items.append((path, payload))


class BrowserMediaRuntimeTests(unittest.TestCase):
    def _build_runtime(
        self,
        *,
        latest_frames: dict[str, LatestFrame] | None = None,
        latest_ai_results: dict[str, dict[str, Any]] | None = None,
        preview_session_id: str | None = None,
        archive_writer: _ArchiveWriter | None = None,
        events: list[tuple[str, dict[str, Any]]] | None = None,
    ) -> tuple[BrowserMediaRuntime, SimpleNamespace]:
        state = SimpleNamespace(preview_session_id=preview_session_id)
        event_log = events if events is not None else []
        runtime = BrowserMediaRuntime(
            append_session_log=lambda session, event, payload: event_log.append((event, dict(payload))),
            latest_frames=latest_frames or {},
            latest_ai_results=latest_ai_results or {},
            latest_preview_session_id_getter=lambda: state.preview_session_id,
            latest_preview_session_id_setter=lambda value: setattr(state, "preview_session_id", value),
            now_ms_provider=lambda: 1234,
            preview_jpeg_quality=82,
            video_sample_log_interval=5,
            audio_sample_log_interval=10,
            browser_audio_sample_rate=16000,
            browser_audio_channels=1,
            audio_ring_max_bytes=4096,
            audio_archive_writer_provider=lambda: archive_writer,
        )
        return runtime, state

    def test_pcm_energy_stats_returns_expected_values(self) -> None:
        payload = struct.pack("<hhhh", 0, 100, 200, -50)

        avg_abs, peak_abs, non_silent_ratio = _pcm_energy_stats(payload)

        self.assertEqual(avg_abs, 87)
        self.assertEqual(peak_abs, 200)
        self.assertAlmostEqual(non_silent_ratio, 0.5)

    def test_set_browser_media_state_clears_preview_and_ai_when_video_drops(self) -> None:
        latest_frames = {
            "sess_a": LatestFrame(
                session_id="sess_a",
                width=10,
                height=20,
                sequence=1,
                timestamp_ms=111,
                bgr_bytes=b"abc",
                jpeg_bytes=b"jpg",
            )
        }
        latest_ai_results = {"sess_a": {"headline": "ready"}}
        runtime, state = self._build_runtime(
            latest_frames=latest_frames,
            latest_ai_results=latest_ai_results,
            preview_session_id="sess_a",
        )
        session = _DummySession(session_id="sess_a")

        runtime.set_browser_media_state(
            session,
            video_active=False,
            audio_active=False,
            peer_label="browser-webrtc",
        )

        self.assertFalse(session.video_connected)
        self.assertFalse(session.audio_connected)
        self.assertIsNone(session.video_peer)
        self.assertIsNone(session.audio_peer)
        self.assertNotIn("sess_a", latest_frames)
        self.assertNotIn("sess_a", latest_ai_results)
        self.assertIsNone(state.preview_session_id)

    def test_ingest_browser_audio_pcm_updates_stats_buffer_and_archive(self) -> None:
        archive_writer = _ArchiveWriter()
        events: list[tuple[str, dict[str, Any]]] = []
        runtime, _ = self._build_runtime(archive_writer=archive_writer, events=events)
        session = _DummySession(session_id="sess_audio")
        pcm_bytes = struct.pack("<hhhh", 0, 100, 200, -50)

        asyncio.run(
            runtime.ingest_browser_audio_pcm(
                session,
                pcm_bytes,
                peer_label="browser-webrtc",
                sequence=1,
                capture_timestamp_ms=4567,
                sample_rate_hz=16000,
                channels=1,
                avg_abs=0,
                peak_abs=0,
                non_silent_ratio=0.0,
                audio_source="browser_webrtc_mic",
                event_name="browser_webrtc_audio_frame",
            )
        )

        self.assertTrue(session.audio_connected)
        self.assertEqual(session.audio_peer, "browser-webrtc")
        self.assertEqual(session.audio_packets, 1)
        self.assertEqual(session.audio_bytes, len(pcm_bytes))
        self.assertEqual(session.last_audio_timestamp_ms, 4567)
        self.assertEqual(session.latest_audio_stats["avgAbs"], 87)
        self.assertEqual(session.latest_audio_stats["peakAbs"], 200)
        self.assertEqual(session.latest_audio_stats["nonSilentRatio"], 0.5)
        self.assertEqual(session.latest_audio_stats["audioSource"], "browser_webrtc_mic")
        self.assertEqual(session._audio_payloads, [pcm_bytes])
        self.assertEqual(archive_writer.items, [(session.audio_path, pcm_bytes)])
        self.assertEqual(events[0][0], "browser_webrtc_audio_frame")


if __name__ == "__main__":
    unittest.main()
