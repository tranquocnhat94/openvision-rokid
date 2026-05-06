import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.voice_runtime import VoiceOrchestrator


class VoiceRuntimeBrowserKeepaliveTests(unittest.TestCase):
    def _make_orchestrator(self) -> VoiceOrchestrator:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        orchestrator = VoiceOrchestrator(
            root_dir=Path(tempdir.name),
            session_provider=lambda: {},
            scene_context_provider=lambda session_id: {},
            vision_context_provider=lambda session_id, target_query, track_id: {},
            command_handler=lambda payload: None,
            log_handler=lambda session_id, event, payload: None,
        )
        self.addCleanup(orchestrator.close)
        return orchestrator

    def test_browser_skill_keepalive_ignores_agc_floor_noise(self) -> None:
        orchestrator = self._make_orchestrator()
        session = SimpleNamespace(
            app_version="browser-harness/20260424-browser-harness15",
            device_id="browser-ios",
            latest_audio_stats={
                "avgAbs": 534,
                "peakAbs": 31862,
                "nonSilentRatio": 0.0208,
            },
        )

        self.assertTrue(orchestrator._audio_stats_support_realtime(session))
        self.assertFalse(orchestrator._audio_stats_support_realtime(session, skill_keepalive=True))

    def test_browser_skill_keepalive_allows_speech_like_activity(self) -> None:
        orchestrator = self._make_orchestrator()
        session = SimpleNamespace(
            app_version="browser-harness/20260424-browser-harness15",
            device_id="browser-ios",
            latest_audio_stats={
                "avgAbs": 601,
                "peakAbs": 31862,
                "nonSilentRatio": 0.12,
            },
        )

        self.assertTrue(orchestrator._audio_stats_support_realtime(session, skill_keepalive=True))

    def test_browser_skill_idle_window_is_longer_than_regular_realtime(self) -> None:
        orchestrator = self._make_orchestrator()
        session = SimpleNamespace(
            app_version="browser-harness/20260424-browser-harness15",
            device_id="browser-ios",
            latest_audio_stats={},
        )

        self.assertEqual(orchestrator._realtime_idle_close_ms(session, skill_keepalive=True), 15000)
        self.assertEqual(orchestrator._realtime_idle_close_ms(session), 6000)

    def test_browser_skill_replay_window_covers_agent_startup_gap(self) -> None:
        orchestrator = self._make_orchestrator()
        session = SimpleNamespace(
            app_version="browser-harness/20260424-browser-harness15",
            device_id="browser-ios",
            latest_audio_stats={},
        )

        self.assertEqual(orchestrator._realtime_replay_ms(session, skill_keepalive=True), 4000)
        self.assertEqual(orchestrator._realtime_replay_ms(session), 1200)

    def test_browser_skill_backend_uses_transcript_route_by_default(self) -> None:
        orchestrator = self._make_orchestrator()
        browser_session = SimpleNamespace(
            app_version="browser-harness/20260424-browser-harness15",
            device_id="browser-ios",
        )
        rv101_session = SimpleNamespace(
            app_version="rv101/1.0",
            device_id="rokid-rv101",
        )

        self.assertTrue(orchestrator._browser_realtime_skill_uses_transcript_route(browser_session))
        self.assertFalse(orchestrator._browser_realtime_skill_uses_transcript_route(rv101_session))

    def test_standby_route_requires_explicit_phrase(self) -> None:
        orchestrator = self._make_orchestrator()

        ambiguous = orchestrator._build_action(
            session_id="sess_demo",
            transcript="đúng rồi",
            source="unit",
            scene_context={},
        )
        explicit = orchestrator._build_action(
            session_id="sess_demo",
            transcript="về chế độ chờ",
            source="unit",
            scene_context={},
        )

        self.assertNotEqual(ambiguous["mode"], "standby")
        self.assertEqual(explicit["mode"], "standby")

    def test_rv101_skill_keepalive_keeps_existing_thresholds(self) -> None:
        orchestrator = self._make_orchestrator()
        session = SimpleNamespace(
            app_version="rv101/1.0",
            device_id="rokid-rv101",
            latest_audio_stats={
                "avgAbs": 42,
                "peakAbs": 240,
                "nonSilentRatio": 0.02,
            },
        )

        self.assertTrue(orchestrator._audio_stats_support_realtime(session, skill_keepalive=True))


if __name__ == "__main__":
    unittest.main()
