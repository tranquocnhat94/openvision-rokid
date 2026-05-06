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
                {
                    "session_id": "sess_a",
                    "module": "realtime_tool",
                    "event_type": "call_completed",
                    "severity": "info",
                    "payload": {"tool_name": "count_people", "status": "ok", "duration_ms": 42},
                },
                {
                    "session_id": "sess_a",
                    "module": "media_command",
                    "event_type": "command_completed",
                    "severity": "info",
                    "payload": {"mode": "snapshot", "status": "ok", "duration_ms": 30},
                },
                {
                    "session_id": "sess_a",
                    "module": "display_command",
                    "event_type": "command_completed",
                    "severity": "info",
                    "payload": {"kind": "text_hud", "status": "ok", "duration_ms": 8},
                },
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
        self.assertEqual(scorecard["gates"]["typed_tool_calls"]["status"], "pass")
        self.assertEqual(scorecard["gates"]["debug_stt_status"]["status"], "pass")
        self.assertEqual(scorecard["metrics"]["perception_object_count"], 1)
        self.assertEqual(scorecard["metrics"]["max_video_actual_fps"], 23.8)
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
        self.assertEqual(scorecard["metrics"]["realtime_tool_call_count"], 1)
        self.assertEqual(scorecard["metrics"]["realtime_tool_max_latency_ms"], 42)
        self.assertEqual(scorecard["metrics"]["media_command_count"], 1)
        self.assertEqual(scorecard["metrics"]["media_command_max_latency_ms"], 30)
        self.assertEqual(scorecard["metrics"]["display_command_count"], 1)
        self.assertEqual(scorecard["metrics"]["display_command_max_latency_ms"], 8)

    def test_scorecard_surfaces_rv101_conversation_voice_contract(self):
        replay = build_session_replay(
            session_id="sess_rv101",
            sessions=[{"session_id": "sess_rv101", "client_kind": "rv101_glasses"}],
            events=[
                {
                    "session_id": "sess_rv101",
                    "module": "rv101_control",
                    "event_type": "session_accept",
                    "severity": "info",
                    "payload": {
                        "voice_mode": "conversation_realtime",
                        "turn_policy": "server_vad",
                        "voice_output": {
                            "enabled": True,
                            "path": "/ws/realtime/sess_rv101/audio",
                        },
                    },
                }
            ],
            media=[],
            perception=[],
            hud_scenes=[],
            realtime=[{"session_id": "sess_rv101", "status": "connected", "turn_policy": "server_vad"}],
            debug_stt=[],
            debug_stt_status={"enabled": False, "status": "disabled"},
        )

        scorecard = build_session_scorecard(replay)

        self.assertEqual(scorecard["gates"]["rv101_voice_contract"]["status"], "pass")
        self.assertEqual(scorecard["metrics"]["rv101_voice_contract_status"], "ok")
        self.assertEqual(scorecard["metrics"]["rv101_voice_mode"], "conversation_realtime")
        self.assertEqual(scorecard["metrics"]["rv101_turn_policy"], "server_vad")
        self.assertEqual(scorecard["metrics"]["realtime_turn_policies"], ["server_vad"])

    def test_scorecard_warns_for_rv101_ptt_fallback_voice_contract(self):
        replay = build_session_replay(
            session_id="sess_rv101_ptt",
            sessions=[{"session_id": "sess_rv101_ptt", "client_kind": "rv101_glasses"}],
            events=[
                {
                    "session_id": "sess_rv101_ptt",
                    "module": "rv101_control",
                    "event_type": "session_accept",
                    "severity": "info",
                    "payload": {
                        "voice_mode": "push_to_talk_realtime",
                        "turn_policy": "manual",
                    },
                }
            ],
            media=[],
            perception=[],
            hud_scenes=[],
            realtime=[{"session_id": "sess_rv101_ptt", "status": "connected", "turn_policy": "manual"}],
            debug_stt=[],
            debug_stt_status={"enabled": False, "status": "disabled"},
        )

        scorecard = build_session_scorecard(replay)

        self.assertEqual(scorecard["gates"]["rv101_voice_contract"]["status"], "warn")
        self.assertEqual(scorecard["metrics"]["rv101_voice_contract_status"], "ptt_fallback")

    def test_scorecard_warns_not_fails_when_rv101_accept_event_was_evicted(self):
        replay = build_session_replay(
            session_id="sess_rv101_long",
            sessions=[{"session_id": "sess_rv101_long", "client_kind": "rv101_glasses"}],
            events=[],
            media=[],
            perception=[],
            hud_scenes=[],
            realtime=[{"session_id": "sess_rv101_long", "status": "connected", "turn_policy": "server_vad"}],
            debug_stt=[],
            debug_stt_status={"enabled": False, "status": "disabled"},
        )

        scorecard = build_session_scorecard(replay)

        self.assertEqual(scorecard["gates"]["rv101_voice_contract"]["status"], "warn")
        self.assertEqual(scorecard["metrics"]["rv101_voice_contract_status"], "inferred_server_vad_missing_accept")

    def test_scorecard_treats_idle_rv101_realtime_as_warmup_not_product_failure(self):
        replay = build_session_replay(
            session_id="sess_rv101_idle",
            sessions=[{"session_id": "sess_rv101_idle", "client_kind": "rv101_glasses"}],
            events=[
                {"session_id": "sess_rv101_idle", "module": "session", "event_type": "created"},
                {
                    "session_id": "sess_rv101_idle",
                    "module": "rv101_control",
                    "event_type": "session_accept",
                    "payload": {
                        "voice_mode": "conversation_realtime",
                        "turn_policy": "server_vad",
                    },
                },
            ],
            media=[
                {
                    "session_id": "sess_rv101_idle",
                    "audio": {
                        "state": "receiving",
                        "chunk_count": 100,
                        "strong_chunk_count": 0,
                        "max_avg_abs": 18.0,
                        "max_peak_abs": 111,
                        "max_non_silent_ratio": 0.0,
                        "gate_open_count": 0,
                    },
                }
            ],
            perception=[],
            hud_scenes=[],
            realtime=[{"session_id": "sess_rv101_idle", "status": "connected", "turn_policy": "server_vad"}],
            debug_stt=[],
            debug_stt_status={"enabled": False, "status": "disabled"},
        )

        scorecard = build_session_scorecard(replay)

        self.assertEqual(scorecard["status"], "warn")
        self.assertTrue(scorecard["metrics"]["idle_rv101_realtime"])
        self.assertEqual(scorecard["gates"]["video_fps"]["status"], "warn")
        self.assertFalse(scorecard["gates"]["video_fps"]["required"])
        self.assertEqual(scorecard["gates"]["audio_signal"]["status"], "warn")
        self.assertFalse(scorecard["gates"]["audio_signal"]["required"])
        self.assertEqual(scorecard["gates"]["hud_scene"]["status"], "warn")
        self.assertFalse(scorecard["gates"]["hud_scene"]["required"])

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

    def test_scorecard_passes_rv101_low_fps_when_it_matches_reported_budget(self):
        replay = build_session_replay(
            session_id="sess_rv101_8fps",
            sessions=[{"session_id": "sess_rv101_8fps", "client_kind": "rv101_glasses"}],
            events=[{"session_id": "sess_rv101_8fps", "module": "hud", "event_type": "scene_updated"}],
            media=[
                {
                    "session_id": "sess_rv101_8fps",
                    "video": {
                        "state": "receiving",
                        "fps": 8.0,
                        "estimated_fps": 7.4,
                        "frame_count": 60,
                        "last_frame_age_ms": 100,
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
            hud_scenes=[hud_scene("sess_rv101_8fps")],
            realtime=[{"session_id": "sess_rv101_8fps", "status": "connected", "turn_policy": "server_vad"}],
            debug_stt=[],
            debug_stt_status={"enabled": False, "status": "disabled"},
        )

        scorecard = build_session_scorecard(replay)

        self.assertEqual(scorecard["gates"]["video_fps"]["status"], "pass")
        self.assertEqual(scorecard["gates"]["video_fps"]["threshold"]["pass_min_fps"], 8.0)
        self.assertEqual(scorecard["metrics"]["max_video_actual_fps"], 7.4)

    def test_scorecard_warns_not_fails_when_video_is_idle_after_snapshot_frames(self):
        replay = build_session_replay(
            session_id="sess_idle_video",
            sessions=[{"session_id": "sess_idle_video"}],
            events=[{"session_id": "sess_idle_video", "module": "hud", "event_type": "scene_updated"}],
            media=[
                {
                    "session_id": "sess_idle_video",
                    "video": {
                        "state": "idle",
                        "estimated_fps": 7.4,
                        "frame_count": 60,
                        "last_frame_age_ms": 120000,
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
            hud_scenes=[hud_scene("sess_idle_video")],
            realtime=[{"session_id": "sess_idle_video", "status": "connected"}],
            debug_stt=[],
            debug_stt_status={"enabled": False, "status": "disabled"},
        )

        scorecard = build_session_scorecard(replay)

        self.assertEqual(scorecard["status"], "warn")
        self.assertEqual(scorecard["gates"]["video_fps"]["status"], "warn")
        self.assertIn("idle after frame evidence", scorecard["gates"]["video_fps"]["message"])

    def test_scorecard_passes_clean_rv101_app_exit_from_final_media_stats(self):
        replay = build_session_replay(
            session_id="sess_rv101_done",
            sessions=[{"session_id": "sess_rv101_done", "client_kind": "rv101_glasses", "status": "closed"}],
            events=[
                {"session_id": "sess_rv101_done", "module": "hud", "event_type": "scene_updated"},
                {
                    "session_id": "sess_rv101_done",
                    "module": "rv101_control",
                    "event_type": "session_accept",
                    "severity": "info",
                    "payload": {
                        "voice_mode": "conversation_realtime",
                        "turn_policy": "server_vad",
                    },
                },
                {
                    "session_id": "sess_rv101_done",
                    "module": "media_command",
                    "event_type": "command_completed",
                    "severity": "info",
                    "payload": {
                        "mode": "live_video",
                        "status": "cancelled",
                        "adapter_status": "app_exit",
                        "active_live_video": False,
                        "sent_fps_estimate": 14.9,
                        "sent_frames": 812,
                        "sent_bytes": 4_000_000,
                        "dropped_frames": 0,
                        "keyframe_count": 68,
                        "requested_fps": 15.0,
                        "capture_fps_min": 15.0,
                        "capture_fps_max": 15.0,
                        "selected_width": 800,
                        "selected_height": 600,
                        "camera_id": "0",
                        "rotation_degrees": 270,
                    },
                },
            ],
            media=[
                {
                    "session_id": "sess_rv101_done",
                    "video": {
                        "state": "idle",
                        "estimated_fps": 15.01,
                        "frame_count": 812,
                        "last_frame_age_ms": 120000,
                    },
                    "audio": {
                        "state": "closed",
                        "chunk_count": 200,
                        "strong_chunk_count": 120,
                        "max_avg_abs": 180.0,
                        "max_non_silent_ratio": 0.06,
                        "gate_open_count": 1,
                    },
                }
            ],
            perception=[],
            hud_scenes=[hud_scene("sess_rv101_done")],
            realtime=[{"session_id": "sess_rv101_done", "status": "connected", "turn_policy": "server_vad"}],
            debug_stt=[],
            debug_stt_status={"enabled": False, "status": "disabled"},
        )

        scorecard = build_session_scorecard(replay)

        self.assertEqual(scorecard["gates"]["video_fps"]["status"], "pass")
        self.assertIn("ended cleanly", scorecard["gates"]["video_fps"]["message"])
        self.assertEqual(scorecard["metrics"]["max_video_sent_fps_estimate"], 14.9)
        self.assertEqual(scorecard["metrics"]["video_dropped_frames"], 0)
        self.assertEqual(scorecard["metrics"]["video_sent_frames"], 812)
        self.assertEqual(scorecard["metrics"]["video_keyframe_count"], 68)
        self.assertEqual(scorecard["metrics"]["video_resolution"], {"width": 800, "height": 600})
        self.assertTrue(scorecard["metrics"]["video_clean_live_end"])

    def test_scorecard_warns_when_video_actual_fps_exceeds_budget(self):
        replay = build_session_replay(
            session_id="sess_budget",
            sessions=[{"session_id": "sess_budget"}],
            events=[{"session_id": "sess_budget", "module": "hud", "event_type": "scene_updated"}],
            media=[
                {
                    "session_id": "sess_budget",
                    "video": {
                        "state": "receiving",
                        "fps": 30.0,
                        "estimated_fps": 16.0,
                        "frame_count": 60,
                        "last_frame_age_ms": 100,
                        "metadata": {
                            "sent_fps_estimate": 22.0,
                            "capture_fps_max": 15.0,
                            "dropped_frames": 4,
                            "camera_id": "0",
                        },
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
            hud_scenes=[hud_scene("sess_budget")],
            realtime=[],
            debug_stt=[],
            debug_stt_status={"enabled": False, "status": "disabled"},
        )

        scorecard = build_session_scorecard(replay)

        self.assertEqual(scorecard["status"], "warn")
        self.assertEqual(scorecard["gates"]["video_fps"]["status"], "warn")
        self.assertIn("exceeds requested budget", scorecard["gates"]["video_fps"]["message"])
        self.assertEqual(scorecard["metrics"]["max_video_actual_fps"], 22.0)
        self.assertEqual(scorecard["metrics"]["max_video_sent_fps_estimate"], 22.0)
        self.assertEqual(scorecard["metrics"]["max_video_budget_fps"], 15.0)
        self.assertEqual(scorecard["metrics"]["video_dropped_frames"], 4)
        self.assertEqual(scorecard["metrics"]["video_camera_ids"], ["0"])

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

    def test_scorecard_surfaces_cloud_gateway_safe_fallback(self):
        replay = build_session_replay(
            session_id="sess_cloud",
            sessions=[{"session_id": "sess_cloud"}],
            events=[
                {
                    "session_id": "sess_cloud",
                    "module": "cloud_gateway",
                    "event_type": "bundle_created",
                    "severity": "info",
                    "payload": {
                        "skill_id": "scene_describe",
                        "bundle_id": "bundle_1",
                        "privacy_level": "medium",
                        "contains_face": False,
                        "allow_cloud": True,
                        "max_answer_chars": 60,
                    },
                },
                {
                    "session_id": "sess_cloud",
                    "module": "cloud_gateway",
                    "event_type": "provider_missing",
                    "severity": "warning",
                    "payload": {
                        "skill_id": "scene_describe",
                        "bundle_id": "bundle_1",
                        "status": "error",
                        "error_code": "cloud_provider_missing",
                        "latency_ms": 4,
                        "validation_error_count": 0,
                    },
                },
            ],
            media=[
                {
                    "session_id": "sess_cloud",
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
            hud_scenes=[hud_scene("sess_cloud")],
            realtime=[{"session_id": "sess_cloud", "status": "connected"}],
            debug_stt=[],
            debug_stt_status={"enabled": False, "status": "disabled"},
        )

        scorecard = build_session_scorecard(replay)

        self.assertEqual(scorecard["status"], "pass")
        self.assertEqual(scorecard["gates"]["cloud_gateway"]["status"], "warn")
        self.assertEqual(scorecard["metrics"]["cloud_gateway_bundle_count"], 1)
        self.assertEqual(scorecard["metrics"]["cloud_gateway_result_count"], 1)
        self.assertEqual(scorecard["metrics"]["cloud_gateway_missing_provider_count"], 1)
        self.assertEqual(scorecard["metrics"]["cloud_gateway_fallback_count"], 1)
        self.assertEqual(scorecard["metrics"]["cloud_gateway_invalid_contract_count"], 0)
        self.assertEqual(scorecard["metrics"]["cloud_gateway_max_latency_ms"], 4)

    def test_scorecard_fails_invalid_cloud_gateway_contract(self):
        replay = build_session_replay(
            session_id="sess_cloud_bad",
            sessions=[{"session_id": "sess_cloud_bad"}],
            events=[
                {
                    "session_id": "sess_cloud_bad",
                    "module": "cloud_gateway",
                    "event_type": "bundle_created",
                    "severity": "info",
                    "payload": {"skill_id": "scene_describe", "bundle_id": "bundle_1"},
                },
                {
                    "session_id": "sess_cloud_bad",
                    "module": "cloud_gateway",
                    "event_type": "result_rejected",
                    "severity": "error",
                    "payload": {
                        "skill_id": "scene_describe",
                        "bundle_id": "bundle_1",
                        "status": "error",
                        "error_code": "invalid_cloud_result",
                        "validation_error_count": 2,
                    },
                },
            ],
            media=[
                {
                    "session_id": "sess_cloud_bad",
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
            hud_scenes=[hud_scene("sess_cloud_bad")],
            realtime=[{"session_id": "sess_cloud_bad", "status": "connected"}],
            debug_stt=[],
            debug_stt_status={"enabled": False, "status": "disabled"},
        )

        scorecard = build_session_scorecard(replay)

        self.assertEqual(scorecard["status"], "fail")
        self.assertEqual(scorecard["gates"]["cloud_gateway"]["status"], "fail")
        self.assertEqual(scorecard["metrics"]["cloud_gateway_invalid_contract_count"], 1)
        self.assertEqual(scorecard["metrics"]["cloud_gateway_validation_error_count"], 2)


if __name__ == "__main__":
    unittest.main()
