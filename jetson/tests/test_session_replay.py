import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.contracts import utc_now
from openvision_jetson.session_replay import build_session_replay, build_session_scorecard


def hud_scene(session_id: str, answer_strip: str = "ready", *, created_at: str | None = None) -> dict:
    return {
        "scene_id": f"hud_{session_id}",
        "session_id": session_id,
        "answer_strip": answer_strip,
        "edge_chips": ["test"],
        "thumbnails": [],
        "target_hint": None,
        "priority": "normal",
        "ttl_ms": 2500,
        "created_at": created_at or utc_now(),
    }


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
            hud_scenes=[hud_scene("sess_a", "1 người")],
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
                    "video": {
                        "state": "receiving",
                        "fps": 24.0,
                        "estimated_fps": 23.8,
                        "frame_count": 120,
                        "last_frame_age_ms": 120,
                        "width": 640,
                        "height": 480,
                    },
                    "audio": {
                        "state": "receiving",
                        "chunk_count": 4,
                        "strong_chunk_count": 3,
                        "strong_chunk_ratio": 0.75,
                        "max_avg_abs": 180.0,
                        "max_peak_abs": 420,
                        "max_non_silent_ratio": 0.06,
                        "gate_open_count": 1,
                        "gate_close_count": 1,
                        "gate_forwarded_chunk_count": 4,
                    },
                }
            ],
            perception=[{"session_id": "sess_a", "objects": [{"label": "person"}]}],
            hud_scenes=[hud_scene("sess_a", "1 người")],
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
        self.assertEqual(scorecard["metrics"]["max_video_estimated_fps"], 23.8)
        self.assertEqual(scorecard["metrics"]["video_last_frame_age_ms"], 120)
        self.assertEqual(scorecard["metrics"]["video_resolution"], {"width": 640, "height": 480})
        self.assertEqual(scorecard["metrics"]["max_audio_strong_chunk_ratio"], 0.75)
        self.assertEqual(scorecard["metrics"]["audio_max_avg_abs"], 180.0)
        self.assertEqual(scorecard["metrics"]["audio_max_peak_abs"], 420)
        self.assertEqual(scorecard["metrics"]["audio_gate_open_count"], 1)
        self.assertEqual(scorecard["metrics"]["hud_valid_scene_count"], 1)
        self.assertEqual(scorecard["metrics"]["hud_latest_answer_strip"], "1 người")
        self.assertGreaterEqual(scorecard["metrics"]["hud_last_scene_age_ms"], 0)

    def test_scorecard_warns_when_video_fps_is_low(self):
        replay = build_session_replay(
            session_id="sess_warn",
            sessions=[{"session_id": "sess_warn"}],
            events=[{"session_id": "sess_warn", "module": "hud", "event_type": "scene_updated"}],
            media=[
                {
                    "session_id": "sess_warn",
                    "video": {"state": "receiving", "estimated_fps": 8.0, "frame_count": 40, "last_frame_age_ms": 300},
                    "audio": {
                        "state": "receiving",
                        "chunk_count": 10,
                        "strong_chunk_count": 7,
                        "max_avg_abs": 180.0,
                        "max_non_silent_ratio": 0.06,
                        "gate_open_count": 1,
                    },
                }
            ],
            perception=[],
            hud_scenes=[hud_scene("sess_warn")],
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

    def test_scorecard_warns_when_audio_signal_is_healthy_but_gate_did_not_open(self):
        replay = build_session_replay(
            session_id="sess_audio_gate_warn",
            sessions=[{"session_id": "sess_audio_gate_warn"}],
            events=[{"session_id": "sess_audio_gate_warn", "module": "hud", "event_type": "scene_updated"}],
            media=[
                {
                    "session_id": "sess_audio_gate_warn",
                    "video": {"state": "receiving", "estimated_fps": 24.0, "frame_count": 60, "last_frame_age_ms": 100},
                    "audio": {
                        "state": "receiving",
                        "chunk_count": 10,
                        "strong_chunk_count": 8,
                        "max_avg_abs": 220.0,
                        "max_peak_abs": 600,
                        "max_non_silent_ratio": 0.08,
                        "gate_open_count": 0,
                    },
                }
            ],
            perception=[],
            hud_scenes=[hud_scene("sess_audio_gate_warn")],
            realtime=[],
            debug_stt=[],
        )

        scorecard = build_session_scorecard(replay)

        self.assertEqual(scorecard["status"], "warn")
        self.assertEqual(scorecard["gates"]["audio_signal"]["status"], "warn")
        self.assertIn("gate did not open", scorecard["gates"]["audio_signal"]["message"])

    def test_scorecard_fails_when_audio_signal_is_too_weak(self):
        replay = build_session_replay(
            session_id="sess_audio_fail",
            sessions=[{"session_id": "sess_audio_fail"}],
            events=[{"session_id": "sess_audio_fail", "module": "hud", "event_type": "scene_updated"}],
            media=[
                {
                    "session_id": "sess_audio_fail",
                    "video": {"state": "receiving", "estimated_fps": 24.0, "frame_count": 60, "last_frame_age_ms": 100},
                    "audio": {
                        "state": "receiving",
                        "chunk_count": 10,
                        "strong_chunk_count": 0,
                        "max_avg_abs": 10.0,
                        "max_peak_abs": 30,
                        "max_non_silent_ratio": 0.0,
                        "gate_open_count": 0,
                    },
                }
            ],
            perception=[],
            hud_scenes=[hud_scene("sess_audio_fail")],
            realtime=[],
            debug_stt=[],
        )

        scorecard = build_session_scorecard(replay)

        self.assertEqual(scorecard["status"], "fail")
        self.assertEqual(scorecard["gates"]["audio_signal"]["status"], "fail")
        self.assertEqual(scorecard["metrics"]["audio_max_peak_abs"], 30)

    def test_scorecard_fails_when_video_frames_are_stale(self):
        replay = build_session_replay(
            session_id="sess_stale",
            sessions=[{"session_id": "sess_stale"}],
            events=[{"session_id": "sess_stale", "module": "hud", "event_type": "scene_updated"}],
            media=[
                {
                    "session_id": "sess_stale",
                    "video": {
                        "state": "receiving",
                        "estimated_fps": 24.0,
                        "frame_count": 60,
                        "last_frame_age_ms": 7000,
                    },
                    "audio": {
                        "state": "receiving",
                        "chunk_count": 10,
                        "strong_chunk_count": 7,
                        "max_avg_abs": 180.0,
                        "max_non_silent_ratio": 0.06,
                        "gate_open_count": 1,
                    },
                }
            ],
            perception=[],
            hud_scenes=[hud_scene("sess_stale")],
            realtime=[],
            debug_stt=[],
        )

        scorecard = build_session_scorecard(replay)

        self.assertEqual(scorecard["status"], "fail")
        self.assertEqual(scorecard["gates"]["video_fps"]["status"], "fail")
        self.assertIn("stale", scorecard["gates"]["video_fps"]["message"])

    def test_scorecard_fails_when_video_has_only_heartbeat(self):
        replay = build_session_replay(
            session_id="sess_heartbeat",
            sessions=[{"session_id": "sess_heartbeat"}],
            events=[{"session_id": "sess_heartbeat", "module": "hud", "event_type": "scene_updated"}],
            media=[
                {
                    "session_id": "sess_heartbeat",
                    "video": {"state": "receiving", "fps": 30.0, "frame_count": 0},
                    "audio": {
                        "state": "receiving",
                        "chunk_count": 10,
                        "strong_chunk_count": 7,
                        "max_avg_abs": 180.0,
                        "max_non_silent_ratio": 0.06,
                        "gate_open_count": 1,
                    },
                }
            ],
            perception=[],
            hud_scenes=[hud_scene("sess_heartbeat")],
            realtime=[],
            debug_stt=[],
        )

        scorecard = build_session_scorecard(replay)

        self.assertEqual(scorecard["status"], "fail")
        self.assertEqual(scorecard["gates"]["video_fps"]["status"], "fail")
        self.assertIn("heartbeat", scorecard["gates"]["video_fps"]["message"])

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

    def test_scorecard_fails_when_hud_scene_is_invalid(self):
        replay = build_session_replay(
            session_id="sess_bad_hud",
            sessions=[{"session_id": "sess_bad_hud"}],
            events=[{"session_id": "sess_bad_hud", "module": "hud", "event_type": "scene_updated"}],
            media=[
                {
                    "session_id": "sess_bad_hud",
                    "video": {"state": "receiving", "estimated_fps": 24.0, "frame_count": 60, "last_frame_age_ms": 100},
                    "audio": {
                        "state": "receiving",
                        "chunk_count": 8,
                        "strong_chunk_count": 6,
                        "max_avg_abs": 180.0,
                        "max_non_silent_ratio": 0.06,
                        "gate_open_count": 1,
                    },
                }
            ],
            perception=[],
            hud_scenes=[{"session_id": "sess_bad_hud", "answer_strip": "missing schema fields"}],
            realtime=[],
            debug_stt=[],
        )

        scorecard = build_session_scorecard(replay)

        self.assertEqual(scorecard["status"], "fail")
        self.assertEqual(scorecard["gates"]["hud_scene"]["status"], "fail")
        self.assertEqual(scorecard["metrics"]["hud_invalid_scene_count"], 1)

    def test_scorecard_fails_when_hud_scene_is_stale(self):
        replay = build_session_replay(
            session_id="sess_stale_hud",
            sessions=[{"session_id": "sess_stale_hud"}],
            events=[{"session_id": "sess_stale_hud", "module": "hud", "event_type": "scene_updated"}],
            media=[
                {
                    "session_id": "sess_stale_hud",
                    "video": {"state": "receiving", "estimated_fps": 24.0, "frame_count": 60, "last_frame_age_ms": 100},
                    "audio": {
                        "state": "receiving",
                        "chunk_count": 8,
                        "strong_chunk_count": 6,
                        "max_avg_abs": 180.0,
                        "max_non_silent_ratio": 0.06,
                        "gate_open_count": 1,
                    },
                }
            ],
            perception=[],
            hud_scenes=[hud_scene("sess_stale_hud", created_at="2000-01-01T00:00:00+00:00")],
            realtime=[],
            debug_stt=[],
        )

        scorecard = build_session_scorecard(replay)

        self.assertEqual(scorecard["status"], "fail")
        self.assertEqual(scorecard["gates"]["hud_scene"]["status"], "fail")
        self.assertIn("stale", scorecard["gates"]["hud_scene"]["message"])

    def test_scorecard_passes_completed_session_with_healthy_replay_evidence(self):
        replay = build_session_replay(
            session_id="sess_done",
            sessions=[{"session_id": "sess_done"}],
            events=[
                {"session_id": "sess_done", "module": "hud", "event_type": "scene_updated"},
                {"session_id": "sess_done", "module": "media", "event_type": "session_closed"},
            ],
            media=[
                {
                    "session_id": "sess_done",
                    "video": {
                        "state": "closed",
                        "estimated_fps": 28.0,
                        "frame_count": 1800,
                        "last_frame_age_ms": 60000,
                        "width": 720,
                        "height": 1280,
                    },
                    "audio": {
                        "state": "closed",
                        "chunk_count": 4000,
                        "strong_chunk_count": 200,
                        "max_avg_abs": 2700.0,
                        "max_peak_abs": 6400,
                        "max_non_silent_ratio": 0.99,
                        "gate_open_count": 9,
                        "gate_close_count": 9,
                    },
                }
            ],
            perception=[],
            hud_scenes=[hud_scene("sess_done", created_at="2000-01-01T00:00:00+00:00")],
            realtime=[],
            debug_stt=[],
            debug_stt_status={"enabled": False, "status": "disabled"},
        )

        scorecard = build_session_scorecard(replay)

        self.assertEqual(scorecard["status"], "pass")
        self.assertTrue(scorecard["metrics"]["session_completed"])
        self.assertEqual(scorecard["gates"]["video_fps"]["status"], "pass")
        self.assertEqual(scorecard["gates"]["audio_signal"]["status"], "pass")
        self.assertEqual(scorecard["gates"]["hud_scene"]["status"], "pass")
        self.assertIn("ended", scorecard["gates"]["video_fps"]["message"])
        self.assertIn("ended", scorecard["gates"]["audio_signal"]["message"])

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
                    "video": {"state": "receiving", "estimated_fps": 30.0, "frame_count": 90, "last_frame_age_ms": 100},
                    "audio": {
                        "state": "receiving",
                        "chunk_count": 8,
                        "strong_chunk_count": 6,
                        "max_avg_abs": 180.0,
                        "max_non_silent_ratio": 0.06,
                        "gate_open_count": 1,
                    },
                }
            ],
            perception=[],
            hud_scenes=[hud_scene("sess_cloud_warn")],
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
