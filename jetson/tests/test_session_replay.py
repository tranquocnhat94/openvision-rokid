import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.session_replay import build_session_replay, build_session_scorecard


class SessionReplayTest(unittest.TestCase):
    def test_replay_filters_session_scoped_state(self):
        replay = build_session_replay(
            session_id="sess_a",
            sessions=[
                {"session_id": "sess_a", "client_kind": "iphone_simulator"},
                {"session_id": "sess_b", "client_kind": "rv101_glasses"},
            ],
            events=[
                {"session_id": "sess_a", "module": "session", "event_type": "created"},
                {"session_id": "sess_b", "module": "session", "event_type": "created"},
            ],
            media=[{"session_id": "sess_a", "video": {"state": "receiving"}, "audio": {"state": "idle"}}],
            perception=[{"session_id": "sess_a", "objects": [{"label": "person"}]}],
            hud_scenes=[{"session_id": "sess_a", "answer_strip": "1 người"}],
            realtime=[{"session_id": "sess_a", "status": "connected"}],
            debug_stt=[{"session_id": "sess_a", "text": "đếm người"}],
        )

        self.assertEqual(replay["schema_version"], "openvision.session_replay.v1")
        self.assertEqual(len(replay["sessions"]), 1)
        self.assertEqual(replay["sessions"][0]["session_id"], "sess_a")
        self.assertEqual(len(replay["events"]), 1)

    def test_scorecard_scores_core_gates(self):
        replay = build_session_replay(
            session_id="sess_a",
            sessions=[{"session_id": "sess_a"}],
            events=[
                {"session_id": "sess_a", "module": "session", "event_type": "created", "severity": "info"},
                {"session_id": "sess_a", "module": "skills", "event_type": "executed", "severity": "info"},
                {"session_id": "sess_a", "module": "hud", "event_type": "scene_updated", "severity": "info"},
            ],
            media=[
                {
                    "session_id": "sess_a",
                    "video": {"state": "receiving"},
                    "audio": {"state": "receiving", "strong_chunk_ratio": 0.75},
                }
            ],
            perception=[{"session_id": "sess_a", "objects": [{"label": "person"}]}],
            hud_scenes=[{"session_id": "sess_a", "answer_strip": "1 người"}],
            realtime=[],
            debug_stt=[],
        )

        scorecard = build_session_scorecard(replay)

        self.assertEqual(scorecard["status"], "pass")
        self.assertEqual(scorecard["metrics"]["perception_object_count"], 1)
        self.assertEqual(scorecard["metrics"]["max_audio_strong_chunk_ratio"], 0.75)


if __name__ == "__main__":
    unittest.main()
