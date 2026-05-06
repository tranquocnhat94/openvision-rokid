import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.voice_runtime import VoiceOrchestrator
from app.voice_session_state import VoiceSessionState


class _DummyClient:
    def __init__(self) -> None:
        self.closed_reason = ""

    def close(self, reason: str) -> None:
        self.closed_reason = reason


class VoiceRuntimeSessionCleanupTests(unittest.TestCase):
    def test_drop_session_clears_cached_state_and_clients(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            orchestrator = VoiceOrchestrator(
                root_dir=Path(tmpdir),
                session_provider=lambda: {
                    "session-1": SimpleNamespace(session_id="session-1", active=True),
                },
                scene_context_provider=lambda session_id: {},
                vision_context_provider=lambda session_id, target_query, track_id: {},
                command_handler=lambda payload: None,
                log_handler=lambda session_id, event, payload: None,
            )
            try:
                route_client = _DummyClient()
                live_client = _DummyClient()
                skill_client = _DummyClient()
                orchestrator.session_states["session-1"] = VoiceSessionState(session_id="session-1")
                orchestrator.realtime_clients["session-1"] = route_client  # type: ignore[assignment]
                orchestrator.realtime_live_clients["session-1"] = live_client  # type: ignore[assignment]
                orchestrator.realtime_skill_clients["session-1"] = skill_client  # type: ignore[assignment]

                orchestrator.drop_session("session-1", reason="session_pruned")

                self.assertNotIn("session-1", orchestrator.session_states)
                self.assertEqual(route_client.closed_reason, "session_pruned")
                self.assertEqual(live_client.closed_reason, "session_pruned")
                self.assertEqual(skill_client.closed_reason, "session_pruned")
            finally:
                orchestrator.close()


if __name__ == "__main__":
    unittest.main()
