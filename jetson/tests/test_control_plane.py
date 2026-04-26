import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.audio_signal import pcm16_metrics
from openvision_jetson.control_plane import OpenVisionControlPlane


class ControlPlaneTest(unittest.TestCase):
    def test_health_is_redacted_and_lists_core_counts(self):
        plane = OpenVisionControlPlane()
        health = plane.health()

        self.assertTrue(health["ok"])
        self.assertEqual(health["service"], "openvision-jetson-agent")
        self.assertIn("openai_key_present", health)
        self.assertGreaterEqual(health["skills"], 6)
        self.assertEqual(health["realtime_sessions"], 0)

    def test_create_session_records_trace_event(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="iphone_simulator",
            capabilities={"video": "webrtc", "audio": "webrtc"},
        )

        self.assertTrue(session["session_id"].startswith("sess_"))
        self.assertEqual(session["client_kind"], "iphone_simulator")

        events = plane.list_events(session_id=session["session_id"])
        self.assertEqual(events[-1]["event_type"], "created")

    def test_skill_dry_run_is_registered_but_not_fake_execution(self):
        plane = OpenVisionControlPlane()
        result = plane.dry_run_skill("count_people", {"frame_window_ms": 1000})

        self.assertEqual(result["status"], "not_implemented")
        self.assertEqual(result["result"]["planned_skill"], "count_people")
        self.assertIn("yolo26_rokid_adapter", result["result"]["local_resources"])

    def test_unknown_skill_returns_error(self):
        plane = OpenVisionControlPlane()
        result = plane.dry_run_skill("old_mode_fake_skill", {})

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "unknown_skill")

    def test_select_and_clear_target_publish_hud_scenes(self):
        plane = OpenVisionControlPlane()

        selected = plane.execute_skill(
            "select_target",
            {"target_id": "obj_person_1", "reason": "unit"},
            session_id="sess_test",
        )
        selected_hud = plane.latest_hud("sess_test")
        cleared = plane.execute_skill("clear_target", {}, session_id="sess_test")
        cleared_hud = plane.latest_hud("sess_test")

        self.assertEqual(selected["status"], "ok")
        self.assertEqual(selected_hud["target_hint"]["target_id"], "obj_person_1")
        self.assertEqual(selected_hud["edge_chips"], ["target"])
        self.assertEqual(cleared["status"], "ok")
        self.assertIsNone(cleared_hud["target_hint"])
        self.assertEqual(cleared_hud["edge_chips"], ["target_clear"])

    def test_realtime_text_preserves_rich_skill_hud(self):
        plane = OpenVisionControlPlane()
        plane.update_perception(
            session_id="sess_test",
            source="unit",
            detections=[
                {"track_id": "p1", "label": "person", "confidence": 0.9, "bbox": [10, 10, 80, 180]},
            ],
        )
        skill = plane.execute_skill(
            "search_targets",
            {"query": "người áo xanh"},
            session_id="sess_test",
        )

        self.assertEqual(skill["status"], "needs_cloud")
        self.assertEqual(len(plane.latest_hud("sess_test")["thumbnails"]), 1)

        plane._update_hud_from_realtime_text("sess_test", "Có 1 ứng viên, cần xác minh màu áo.")
        latest = plane.latest_hud("sess_test")

        self.assertEqual(latest["answer_strip"], "Có 1 ứng viên, cần xác minh màu áo.")
        self.assertEqual(len(latest["thumbnails"]), 1)
        self.assertIn("realtime", latest["edge_chips"])

    def test_simulator_close_flushes_debug_stt_buffer(self):
        plane = OpenVisionControlPlane()

        with patch.object(plane.debug_stt, "flush_session", return_value=True) as flush:
            plane._close_simulator_media("sess_test")

        flush.assert_called_once_with("sess_test", reason="simulator_stream_closed")

    def test_rv101_audio_close_flushes_debug_stt_buffer_and_gate(self):
        plane = OpenVisionControlPlane()
        plane._rv101_audio_gates["sess_test"] = object()

        with patch.object(plane.debug_stt, "flush_session", return_value=True) as flush:
            plane._close_rv101_audio("sess_test")

        flush.assert_called_once_with("sess_test", reason="rv101_audio_stream_closed")
        self.assertNotIn("sess_test", plane._rv101_audio_gates)


class ControlPlaneAudioGateTest(unittest.IsolatedAsyncioTestCase):
    async def test_audio_gate_suppresses_idle_noise_before_realtime(self):
        plane = OpenVisionControlPlane()
        plane.realtime.append_audio = AsyncMock()
        silence = (0).to_bytes(2, "little", signed=True) * 20
        voice = (300).to_bytes(2, "little", signed=True) * 20

        await plane._forward_gated_audio(
            session_id="sess_test",
            pcm_bytes=silence,
            metrics=pcm16_metrics(silence),
            source="unit",
            gates=plane._simulator_audio_gates,
        )
        await plane._forward_gated_audio(
            session_id="sess_test",
            pcm_bytes=voice,
            metrics=pcm16_metrics(voice),
            source="unit",
            gates=plane._simulator_audio_gates,
        )
        await plane._forward_gated_audio(
            session_id="sess_test",
            pcm_bytes=voice,
            metrics=pcm16_metrics(voice),
            source="unit",
            gates=plane._simulator_audio_gates,
        )

        self.assertEqual(plane.realtime.append_audio.await_count, 3)
        events = plane.list_events(session_id="sess_test")
        self.assertTrue(any(event["module"] == "audio_gate" and event["event_type"] == "opened" for event in events))
        media = plane.media.status("sess_test")
        self.assertEqual(media["audio"]["gate_open_count"], 1)
        self.assertEqual(media["audio"]["gate_state"], "open")
        self.assertGreaterEqual(media["audio"]["max_avg_abs"], 300.0)


if __name__ == "__main__":
    unittest.main()
