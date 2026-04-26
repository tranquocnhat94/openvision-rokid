import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from fastapi.testclient import TestClient

from openvision_jetson.control_plane import OpenVisionControlPlane
from openvision_jetson.fastapi_app import create_app


class FastApiAppTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(OpenVisionControlPlane()))

    def test_health_endpoint(self):
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["service"], "openvision-jetson-agent")

    def test_session_creation_endpoint(self):
        response = self.client.post(
            "/api/sessions",
            json={
                "client_kind": "rv101_glasses",
                "capabilities": {"video": "h264_tcp", "audio": "pcm_tcp"},
            },
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["session"]["client_kind"], "rv101_glasses")

    def test_skill_endpoint_does_not_fake_execution(self):
        response = self.client.post(
            "/api/skills/count_people/dry-run",
            json={"args": {"frame_window_ms": 1000}},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "not_implemented")
        self.assertEqual(payload["result"]["manifest_id"], "openvision.skill.count_people")

    def test_scorecard_endpoint_reports_session_gates(self):
        session = self.client.post(
            "/api/sessions",
            json={"client_kind": "iphone_simulator", "capabilities": {"video": "webrtc"}},
        ).json()["session"]
        session_id = session["session_id"]
        self.client.post(
            f"/api/media/{session_id}/video/heartbeat",
            json={"transport": "webrtc", "codec": "raw_video", "width": 640, "height": 480, "fps": 24},
        )
        self.client.app.state.control_plane.media.record_video_sample(
            session_id=session_id,
            transport="webrtc",
            codec="raw_video",
            payload_bytes=0,
            width=640,
            height=480,
            fps=24,
        )
        self.client.post(
            f"/api/media/{session_id}/audio/metrics",
            json={
                "transport": "webrtc",
                "sample_rate": 24000,
                "channels": 1,
                "chunk_count": 4,
                "strong_chunk_count": 3,
                "avg_abs": 180.0,
                "peak_abs": 420,
                "non_silent_ratio": 0.06,
            },
        )
        self.client.app.state.control_plane.media.record_audio_gate_decision(
            session_id=session_id,
            source="iphone_webrtc",
            state="open",
            transition="opened",
            strong=True,
            forwarded_chunks=3,
            buffered_chunks=0,
            avg_abs=180.0,
            peak_abs=420,
            non_silent_ratio=0.06,
        )
        self.client.post(
            f"/api/perception/{session_id}/detections",
            json={"source": "unit", "detections": [{"label": "person", "confidence": 0.9}]},
        )
        self.client.post(
            "/api/skills/count_people/execute",
            json={"session_id": session_id, "args": {"min_confidence": 0.25}},
        )

        replay = self.client.get(f"/api/replay/{session_id}")
        scorecard = self.client.get(f"/api/scorecard/{session_id}")

        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()["replay"]["session_id"], session_id)
        self.assertEqual(scorecard.status_code, 200)
        payload = scorecard.json()["scorecard"]
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["gates"]["video_fps"]["status"], "pass")
        self.assertEqual(payload["gates"]["audio_signal"]["status"], "pass")
        self.assertEqual(payload["gates"]["hud_scene"]["status"], "pass")
        self.assertEqual(payload["gates"]["perception_seen"]["status"], "pass")
        self.assertEqual(payload["metrics"]["video_frame_count"], 1)
        self.assertEqual(payload["metrics"]["video_resolution"], {"width": 640, "height": 480})
        self.assertEqual(payload["metrics"]["max_audio_strong_chunk_ratio"], 0.75)
        self.assertEqual(payload["metrics"]["audio_max_avg_abs"], 180.0)
        self.assertEqual(payload["metrics"]["audio_gate_open_count"], 1)
        self.assertEqual(payload["metrics"]["hud_valid_scene_count"], 1)
        self.assertEqual(payload["metrics"]["hud_latest_answer_strip"], "1 người")
        self.assertGreaterEqual(payload["metrics"]["hud_last_scene_age_ms"], 0)

    def test_media_video_status_surfaces_stream_liveness(self):
        self.client.app.state.control_plane.media.record_video_sample(
            session_id="sess_test",
            transport="webrtc",
            codec="raw_video",
            payload_bytes=0,
            width=640,
            height=480,
            fps=24,
        )

        response = self.client.get("/api/media")

        self.assertEqual(response.status_code, 200)
        video = response.json()["media"][0]["video"]
        self.assertEqual(video["frame_count"], 1)
        self.assertEqual(video["width"], 640)
        self.assertEqual(video["height"], 480)
        self.assertGreaterEqual(video["last_frame_age_ms"], 0)
        self.assertLess(video["last_frame_age_ms"], 1000)
        self.assertIsNotNone(video["last_frame_at"])

    def test_realtime_start_blocks_without_key(self):
        session = self.client.post(
            "/api/sessions",
            json={"client_kind": "iphone_simulator", "capabilities": {}},
        ).json()["session"]

        response = self.client.post(
            f"/api/realtime/{session['session_id']}/start",
            json={"turn_policy": "manual", "output_modalities": ["text"]},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["error"]["code"], "missing_openai_api_key")

    def test_realtime_start_can_request_voice_output(self):
        session = self.client.post(
            "/api/sessions",
            json={"client_kind": "iphone_simulator", "capabilities": {}},
        ).json()["session"]

        response = self.client.post(
            f"/api/realtime/{session['session_id']}/start",
            json={"turn_policy": "manual", "voice_output": True},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["output_modalities"], ["text", "audio"])

    def test_voice_output_status_endpoint_is_present(self):
        response = self.client.get("/api/realtime/voice-output")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"voice_output": []})

    def test_debug_stt_endpoint_is_present(self):
        response = self.client.get("/api/debug-stt")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("status", payload)
        self.assertEqual(payload["transcripts"], [])

    def test_simulator_status_endpoint(self):
        response = self.client.get("/api/simulator/webrtc")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"peers": []})

    def test_media_audio_metrics_endpoint(self):
        response = self.client.post(
            "/api/media/sess_test/audio/metrics",
            json={
                "transport": "pcm_tcp",
                "sample_rate": 24000,
                "channels": 1,
                "chunk_count": 5,
                "strong_chunk_count": 4,
                "avg_abs": 160.0,
                "peak_abs": 380,
                "non_silent_ratio": 0.04,
                "source": "mic",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["audio"]["strong_chunk_ratio"], 0.8)
        self.assertEqual(payload["audio"]["avg_abs"], 160.0)
        self.assertEqual(payload["audio"]["peak_abs"], 380)
        self.assertEqual(payload["audio"]["non_silent_ratio"], 0.04)

    def test_hud_test_scene_endpoint_updates_latest_scene(self):
        response = self.client.post("/api/hud/sess_test/test-scene")
        latest = self.client.get("/api/hud/sess_test/latest")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["hud_scene"]["answer_strip"], "HUD test OK")
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.json()["hud_scene"]["edge_chips"], ["hud", "test"])

    def test_preview_endpoints_return_latest_decoded_frame(self):
        self.client.app.state.control_plane.preview.record_frame(
            session_id="sess_test",
            source="unit",
            image_bytes=b"jpeg",
            width=320,
            height=240,
            frame_count=1,
        )

        status = self.client.get("/api/preview")
        frame = self.client.get("/api/preview/sess_test/frame.jpg")

        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["preview"][0]["session_id"], "sess_test")
        self.assertEqual(frame.status_code, 200)
        self.assertEqual(frame.content, b"jpeg")
        self.assertEqual(frame.headers["content-type"], "image/jpeg")

    def test_preview_stream_returns_404_without_decoded_frame(self):
        response = self.client.get("/api/preview/sess_missing/stream.mjpeg")

        self.assertEqual(response.status_code, 404)

    def test_perception_snapshot_and_execute_count(self):
        snapshot = self.client.post(
            "/api/perception/sess_test/detections",
            json={
                "source": "unit",
                "detections": [
                    {"label": "person", "confidence": 0.9},
                    {"label": "person", "confidence": 0.7},
                    {"label": "phone", "confidence": 0.8},
                ],
            },
        )
        self.assertEqual(snapshot.status_code, 200)

        response = self.client.post(
            "/api/skills/count_people/execute",
            json={"session_id": "sess_test", "args": {"min_confidence": 0.25}},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["count"], 2)

        hud = self.client.get("/api/hud/sess_test/latest")
        self.assertEqual(hud.status_code, 200)
        self.assertEqual(hud.json()["hud_scene"]["answer_strip"], "2 người")

    def test_skill_execute_rejects_invalid_manifest_args_as_400(self):
        response = self.client.post(
            "/api/skills/search_targets/execute",
            json={"session_id": "sess_test", "args": {"query": "người", "max_candidates": 999}},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "invalid_skill_args")
        self.assertIn("args.max_candidates must be <= 8", response.json()["detail"]["details"])

    def test_select_target_updates_latest_hud_target_hint(self):
        selected = self.client.post(
            "/api/skills/select_target/execute",
            json={"session_id": "sess_test", "args": {"target_id": "obj_person_1"}},
        )
        latest = self.client.get("/api/hud/sess_test/latest")
        cleared = self.client.post(
            "/api/skills/clear_target/execute",
            json={"session_id": "sess_test", "args": {}},
        )
        cleared_latest = self.client.get("/api/hud/sess_test/latest")

        self.assertEqual(selected.status_code, 200)
        self.assertEqual(latest.json()["hud_scene"]["target_hint"]["target_id"], "obj_person_1")
        self.assertEqual(cleared.status_code, 200)
        self.assertIsNone(cleared_latest.json()["hud_scene"]["target_hint"])

    def test_perception_history_endpoint_returns_recent_snapshots(self):
        for frame_id in ("frame_1", "frame_2"):
            response = self.client.post(
                "/api/perception/sess_test/detections",
                json={
                    "source": "unit",
                    "frame_id": frame_id,
                    "width": 640,
                    "height": 480,
                    "detections": [{"track_id": "p1", "label": "person", "confidence": 0.9, "bbox": [20, 100, 160, 350]}],
                },
            )
            self.assertEqual(response.status_code, 200)

        history = self.client.get("/api/perception/sess_test/history?limit=5")

        self.assertEqual(history.status_code, 200)
        payload = history.json()["perception"]
        self.assertEqual([item["frame_id"] for item in payload], ["frame_1", "frame_2"])
        self.assertEqual(payload[1]["objects"][0]["object_id"], payload[0]["objects"][0]["object_id"])

    def test_yolo26_adapter_status_endpoint_is_disabled_by_default(self):
        response = self.client.get("/api/adapters/yolo26")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["adapter"]["name"], "yolo26_rokid")
        self.assertEqual(payload["adapter"]["status"], "disabled")

    def test_yolo26_adapter_ingress_requires_explicit_mode(self):
        response = self.client.post(
            "/api/adapters/yolo26/sess_test/detections",
            json={"source": "unit", "detections": [{"label": "person", "confidence": 0.9}]},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "adapter_disabled")

    def test_yolo26_adapter_ingress_updates_perception_when_enabled(self):
        with patch.dict(os.environ, {"OPENVISION_YOLO26_MODE": "external_snapshot"}):
            response = self.client.post(
                "/api/adapters/yolo26/sess_test/detections",
                json={
                    "source": "rokid_yolo26_unit",
                    "frame_id": "frame_1",
                    "width": 640,
                    "height": 480,
                    "detections": [
                        {"label": "person", "confidence": 0.9, "bbox": [20, 100, 160, 350]},
                        {"label": "bag", "confidence": 0.1, "bbox": [240, 100, 360, 260]},
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "accepted")
        self.assertEqual(payload["source"], "yolo26_rokid:rokid_yolo26_unit")
        self.assertEqual(payload["accepted_detection_count"], 1)
        self.assertEqual(payload["rejected_detection_count"], 1)
        self.assertEqual(payload["perception"]["source"], "yolo26_rokid:rokid_yolo26_unit")
        self.assertEqual(payload["perception"]["objects"][0]["label"], "person")
        self.assertEqual(payload["perception"]["objects"][0]["zone"], "left_front")

    def test_yolo26_adapter_rejects_ring_source_when_enabled(self):
        with patch.dict(os.environ, {"OPENVISION_YOLO26_MODE": "external_snapshot"}):
            response = self.client.post(
                "/api/adapters/yolo26/sess_test/detections",
                json={"source": "ring_security_yolo26", "detections": [{"label": "person", "confidence": 0.9}]},
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "forbidden_snapshot_source")

    def test_rv101_ingest_status_endpoint(self):
        response = self.client.get("/api/rv101/ingest")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ingest"]["protocol"], "rvs1_tcp")

    def test_rv101_control_ws_accepts_session(self):
        with self.client.websocket_connect("/ws") as websocket:
            websocket.send_json(
                {
                    "type": "client_hello",
                    "deviceId": "rv101-test",
                    "appVersion": "test",
                    "videoCodec": "h264",
                }
            )
            accept = websocket.receive_json()
            hud = websocket.receive_json()
            websocket.send_json({"type": "ping", "timestampMs": 123})
            pong = websocket.receive_json()

        self.assertEqual(accept["type"], "session_accept")
        self.assertEqual(accept["media"]["transport"], "tcp_h264")
        self.assertEqual(accept["audio"]["transport"], "tcp_pcm")
        self.assertEqual(hud["type"], "hud_scene")
        self.assertEqual(pong["type"], "pong")


if __name__ == "__main__":
    unittest.main()
