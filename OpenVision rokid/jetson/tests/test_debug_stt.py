import sys
import unittest
import wave
import io
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.debug_stt import DebugSttRuntime, DebugSttSettings, _post_wav_to_worker, pcm16_to_wav_16k_mono
from openvision_jetson.event_store import InMemoryEventStore


class DebugSttTest(unittest.IsolatedAsyncioTestCase):
    def test_pcm_is_packaged_as_16k_mono_wav(self):
        pcm_24k = (300).to_bytes(2, "little", signed=True) * 24_000

        wav_bytes = pcm16_to_wav_16k_mono(pcm_24k, sample_rate=24_000, channels=1)

        with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
            self.assertEqual(wav_file.getframerate(), 16_000)
            self.assertEqual(wav_file.getnchannels(), 1)
            self.assertEqual(wav_file.getsampwidth(), 2)
            self.assertGreater(wav_file.getnframes(), 15_000)

    async def test_closed_turn_posts_to_worker_and_stores_transcript(self):
        async def fake_post(settings, wav_bytes, session_id):
            self.assertEqual(settings.language, "vi")
            self.assertEqual(session_id, "sess_test")
            self.assertGreater(len(wav_bytes), 44)
            return {"text": "đếm người đi", "backend": "phowhisper_http", "transcribeMs": 123, "language": "vi"}

        runtime = DebugSttRuntime(
            events=InMemoryEventStore(),
            settings_provider=lambda: DebugSttSettings(enabled=True, min_audio_ms=0),
            http_post=fake_post,
        )
        voice = (300).to_bytes(2, "little", signed=True) * 24_000
        silence = (0).to_bytes(2, "little", signed=True) * 2_400

        runtime.accept_gate_decision(
            session_id="sess_test",
            chunks=[voice],
            transition="opened",
            sample_rate=24_000,
            channels=1,
            source="unit",
        )
        runtime.accept_gate_decision(
            session_id="sess_test",
            chunks=[silence],
            transition="closed",
            sample_rate=24_000,
            channels=1,
            source="unit",
        )
        await runtime.wait_for_idle()

        rows = runtime.transcripts(session_id="sess_test")
        self.assertEqual(rows[0]["text"], "đếm người đi")
        self.assertEqual(rows[0]["backend"], "phowhisper_http")

    async def test_default_min_audio_accepts_short_vietnamese_command(self):
        async def fake_post(settings, wav_bytes, session_id):
            self.assertEqual(settings.min_audio_ms, 800)
            return {"text": "đếm người đi", "backend": "phowhisper_http", "language": "vi"}

        runtime = DebugSttRuntime(
            events=InMemoryEventStore(),
            settings_provider=lambda: DebugSttSettings(enabled=True),
            http_post=fake_post,
        )
        voice_920ms = (300).to_bytes(2, "little", signed=True) * int(24_000 * 0.92)

        runtime.accept_gate_decision(
            session_id="sess_short_vi",
            chunks=[voice_920ms],
            transition="opened",
            sample_rate=24_000,
            channels=1,
            source="unit",
        )
        runtime.accept_gate_decision(
            session_id="sess_short_vi",
            chunks=[],
            transition="closed",
            sample_rate=24_000,
            channels=1,
            source="unit",
        )
        await runtime.wait_for_idle()

        rows = runtime.transcripts(session_id="sess_short_vi")
        self.assertEqual(rows[0]["text"], "đếm người đi")
        self.assertEqual(rows[0]["duration_ms"], 920)

    async def test_sub_floor_turn_is_reported_too_short(self):
        events = InMemoryEventStore()
        runtime = DebugSttRuntime(
            events=events,
            settings_provider=lambda: DebugSttSettings(enabled=True),
        )
        voice_760ms = (300).to_bytes(2, "little", signed=True) * int(24_000 * 0.76)

        runtime.accept_gate_decision(
            session_id="sess_too_short",
            chunks=[voice_760ms],
            transition="opened",
            sample_rate=24_000,
            channels=1,
            source="unit",
        )
        runtime.accept_gate_decision(
            session_id="sess_too_short",
            chunks=[],
            transition="closed",
            sample_rate=24_000,
            channels=1,
            source="unit",
        )
        await runtime.wait_for_idle()

        self.assertEqual(runtime.transcripts(session_id="sess_too_short"), [])
        last_event = events.list(session_id="sess_too_short")[-1]
        self.assertEqual(last_event["event_type"], "turn_too_short")
        self.assertEqual(last_event["payload"]["duration_ms"], 760)
        self.assertEqual(last_event["payload"]["min_audio_ms"], 800)

    async def test_flush_session_transcribes_open_buffer(self):
        async def fake_post(settings, wav_bytes, session_id):
            self.assertEqual(session_id, "sess_flush")
            return {"text": "tìm người áo xanh", "backend": "phowhisper_http"}

        events = InMemoryEventStore()
        runtime = DebugSttRuntime(
            events=events,
            settings_provider=lambda: DebugSttSettings(enabled=True),
            http_post=fake_post,
        )
        voice_920ms = (300).to_bytes(2, "little", signed=True) * int(24_000 * 0.92)

        runtime.accept_gate_decision(
            session_id="sess_flush",
            chunks=[voice_920ms],
            transition="opened",
            sample_rate=24_000,
            channels=1,
            source="unit",
        )
        flushed = runtime.flush_session("sess_flush", reason="unit_disconnect")
        await runtime.wait_for_idle()

        self.assertTrue(flushed)
        self.assertEqual(runtime.status()["turn_buffers"], 0)
        self.assertEqual(runtime.transcripts(session_id="sess_flush")[0]["text"], "tìm người áo xanh")
        self.assertTrue(
            any(event["event_type"] == "turn_flushed" for event in events.list(session_id="sess_flush"))
        )

    async def test_empty_transcript_is_dropped(self):
        async def fake_post(settings, wav_bytes, session_id):
            return {"text": "  ", "backend": "phowhisper_http"}

        events = InMemoryEventStore()
        runtime = DebugSttRuntime(
            events=events,
            settings_provider=lambda: DebugSttSettings(enabled=True, min_audio_ms=0),
            http_post=fake_post,
        )
        voice = (300).to_bytes(2, "little", signed=True) * 24_000

        runtime.accept_gate_decision(
            session_id="sess_empty",
            chunks=[voice],
            transition="opened",
            sample_rate=24_000,
            channels=1,
            source="unit",
        )
        runtime.accept_gate_decision(
            session_id="sess_empty",
            chunks=[],
            transition="closed",
            sample_rate=24_000,
            channels=1,
            source="unit",
        )
        await runtime.wait_for_idle()

        self.assertEqual(runtime.transcripts(session_id="sess_empty"), [])
        self.assertEqual(events.list(session_id="sess_empty")[-1]["event_type"], "empty_transcript_dropped")

    async def test_successful_warm_clears_stale_error(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"ok": True, "backend": "phowhisper_http", "modelLoaded": True}

        class FakeClient:
            def __init__(self, timeout):
                self.timeout = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                return None

            async def get(self, url, headers=None):
                self.url = url
                self.headers = headers or {}
                return FakeResponse()

        runtime = DebugSttRuntime(
            events=InMemoryEventStore(),
            settings_provider=lambda: DebugSttSettings(
                enabled=True,
                transcribe_url="http://mini/inference",
                health_url="http://mini/health",
                warm_url="http://mini/warm",
            ),
        )
        runtime._last_error = "ConnectTimeout: old"

        with patch("openvision_jetson.debug_stt.httpx.AsyncClient", FakeClient):
            payload = await runtime.warm()

        self.assertTrue(payload["ok"])
        self.assertIsNone(runtime.status()["last_error"])
        self.assertTrue(runtime.status()["last_health_ok"])

    async def test_health_probe_updates_cached_status(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"ok": True, "backend": "phowhisper_http", "modelLoaded": True}

        class FakeClient:
            def __init__(self, timeout):
                self.timeout = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                return None

            async def get(self, url, headers=None):
                self.url = url
                self.headers = headers or {}
                return FakeResponse()

        runtime = DebugSttRuntime(
            events=InMemoryEventStore(),
            settings_provider=lambda: DebugSttSettings(
                enabled=True,
                transcribe_url="http://mini/inference",
                health_url="http://mini/health",
                warm_url="http://mini/warm",
            ),
        )

        with patch("openvision_jetson.debug_stt.httpx.AsyncClient", FakeClient):
            status = await runtime.check_health()

        self.assertEqual(status["status"], "enabled")
        self.assertTrue(status["last_health_ok"])
        self.assertTrue(status["model_loaded"])

    async def test_health_probe_sends_auth_token_when_configured(self):
        calls = []

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"ok": True, "backend": "phowhisper_http", "modelLoaded": True}

        class FakeClient:
            def __init__(self, timeout):
                self.timeout = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                return None

            async def get(self, url, headers=None):
                calls.append(headers or {})
                return FakeResponse()

        runtime = DebugSttRuntime(
            events=InMemoryEventStore(),
            settings_provider=lambda: DebugSttSettings(
                enabled=True,
                transcribe_url="http://mini/inference",
                health_url="http://mini/health",
                warm_url="http://mini/warm",
                auth_token="test-token",
            ),
        )

        with patch("openvision_jetson.debug_stt.httpx.AsyncClient", FakeClient):
            status = await runtime.check_health()

        self.assertEqual(status["status"], "enabled")
        self.assertTrue(status["auth_configured"])
        self.assertEqual(calls[0]["X-OpenVision-Debug-STT-Token"], "test-token")

    async def test_worker_post_sends_auth_token_when_configured(self):
        calls = []

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"text": "đếm người đi", "backend": "phowhisper_http"}

        class FakeClient:
            def __init__(self, timeout):
                self.timeout = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                return None

            async def post(self, url, content=None, headers=None):
                calls.append({"url": url, "headers": headers or {}, "content": content})
                return FakeResponse()

        settings = DebugSttSettings(
            enabled=True,
            transcribe_url="http://mini/inference",
            auth_token="test-token",
        )

        with patch("openvision_jetson.debug_stt.httpx.AsyncClient", FakeClient):
            payload = await _post_wav_to_worker(settings, b"wav", "sess_test")

        self.assertEqual(payload["text"], "đếm người đi")
        self.assertEqual(calls[0]["headers"]["X-OpenVision-Debug-STT-Token"], "test-token")
        self.assertEqual(calls[0]["headers"]["X-Rokid-Session-Id"], "sess_test")


if __name__ == "__main__":
    unittest.main()
