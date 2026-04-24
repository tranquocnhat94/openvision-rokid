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
            debug_stt_status={"enabled": True, "status": "enabled"},
        )

        self.assertEqual(replay["schema_version"], "openvision.session_replay.v1")
        self.assertEqual(len(replay["sessions"]), 1)
        self.assertEqual(replay["sessions"][0]["session_id"], "sess_a")
        self.assertEqual(len(replay["events"]), 1)
        self.assertEqual(replay["debug_stt_status"]["status"], "enabled")

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
                    "video": {"state": "receiving", "fps": 24.0, "frame_count": 120},
                    "audio": {
                        "state": "receiving",
                        "chunk_count": 4,
                        "strong_chunk_count": 3,
                        "strong_chunk_ratio": 0.75,
                    },
                }
            ],
            perception=[{"session_id": "sess_a", "objects": [{"label": "person"}]}],
            hud_scenes=[{"session_id": "sess_a", "answer_strip": "1 người"}],
            realtime=[{"session_id": "sess_a", "status": "connected", "event_count": 2}],
            debug_stt=[{"session_id": "sess_a", "status": "ok", "text": "đếm người"}],
            debug_stt_status={"enabled": True, "status": "enabled", "last_error": None},
        )

        scorecard = build_session_scorecard(replay)

        self.assertEqual(scorecard["status"], "pass")
        self.assertEqual(scorecard["gates"]["video_fps"]["status"], "pass")
        self.assertEqual(scorecard["gates"]["audio_signal"]["status"], "pass")
        self.assertEqual(scorecard["gates"]["hud_scene"]["status"], "pass")
        self.assertEqual(scorecard["gates"]["realtime_status"]["status"], "pass")
        self.assertEqual(scorecard["gates"]["debug_stt_status"]["status"], "pass")
        self.assertEqual(scorecard["metrics"]["perception_object_count"], 1)
        self.assertEqual(scorecard["metrics"]["max_audio_strong_chunk_ratio"], 0.75)

    def test_scorecard_warns_when_video_fps_is_low(self):
        replay = build_session_replay(
            session_id="sess_warn",
            sessions=[{"session_id": "sess_warn"}],
            events=[{"session_id": "sess_warn", "module": "hud", "event_type": "scene_updated"}],
            media=[
                {
                    "session_id": "sess_warn",
                    "video": {"state": "receiving", "fps": 8.0, "frame_count": 40},
                    "audio": {"state": "receiving", "chunk_count": 10, "strong_chunk_count": 7},
                }
            ],
            perception=[],
            hud_scenes=[{"session_id": "sess_warn", "answer_strip": "ready"}],
            realtime=[],
            debug_stt=[],
            debug_stt_status={"enabled": False, "status": "disabled"},
        )

        scorecard = build_session_scorecard(replay)

        self.assertEqual(scorecard["status"], "warn")
        self.assertEqual(scorecard["gates"]["video_fps"]["status"], "warn")
        self.assertEqual(scorecard["gates"]["audio_signal"]["status"], "pass")
        self.assertEqual(scorecard["gates"]["realtime_status"]["status"], "warn")
        self.assertEqual(scorecard["gates"]["debug_stt_status"]["status"], "warn")
        self.assertEqual(scorecard["metrics"]["max_video_fps"], 8.0)

    def test_scorecard_fails_when_required_media_and_hud_are_missing(self):
        replay = build_session_replay(
            session_id="sess_fail",
            sessions=[{"session_id": "sess_fail"}],
            events=[],
            media=[],
            perception=[],
            hud_scenes=[],
            realtime=[],
            debug_stt=[],
        )

        scorecard = build_session_scorecard(replay)

        self.assertEqual(scorecard["status"], "fail")
        self.assertEqual(scorecard["gates"]["video_fps"]["status"], "fail")
        self.assertEqual(scorecard["gates"]["audio_signal"]["status"], "fail")
        self.assertEqual(scorecard["gates"]["hud_scene"]["status"], "fail")
        self.assertGreaterEqual(scorecard["metrics"]["required_gate_fail_count"], 3)
        self.assertEqual(scorecard["top_failures"][0]["source"], "gate")

    def test_scorecard_surfaces_realtime_blocked_without_failing_required_gates(self):
        replay = build_session_replay(
            session_id="sess_cloud_warn",
            sessions=[{"session_id": "sess_cloud_warn"}],
            events=[
                {
                    "session_id": "sess_cloud_warn",
                    "module": "realtime",
                    "event_type": "blocked",
                    "severity": "warning",
                }
            ],
            media=[
                {
                    "session_id": "sess_cloud_warn",
                    "video": {"state": "receiving", "fps": 30.0, "frame_count": 90},
                    "audio": {"state": "receiving", "chunk_count": 8, "strong_chunk_count": 6},
                }
            ],
            perception=[],
            hud_scenes=[{"session_id": "sess_cloud_warn", "answer_strip": "ready"}],
            realtime=[
                {
                    "session_id": "sess_cloud_warn",
                    "status": "blocked",
                    "error": {"code": "missing_openai_api_key"},
                }
            ],
            debug_stt=[],
            debug_stt_status={"enabled": False, "status": "disabled"},
        )

        scorecard = build_session_scorecard(replay)

        self.assertEqual(scorecard["status"], "pass")
        self.assertEqual(scorecard["gates"]["realtime_status"]["status"], "warn")
        self.assertFalse(scorecard["gates"]["realtime_status"]["required"])
        self.assertEqual(scorecard["metrics"]["warning_count"], 1)


if __name__ == "__main__":
    unittest.main()
