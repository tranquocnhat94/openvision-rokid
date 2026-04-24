import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

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


if __name__ == "__main__":
    unittest.main()
