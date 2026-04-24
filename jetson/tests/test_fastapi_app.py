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
                "rms": 0.2,
                "source": "mic",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["audio"]["strong_chunk_ratio"], 0.8)

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
                    "source": "unit_yolo",
                    "frame_id": "frame_1",
                    "detections": [{"label": "person", "confidence": 0.9}],
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "accepted")
        self.assertEqual(payload["perception"]["source"], "yolo26_rokid:unit_yolo")
        self.assertEqual(payload["perception"]["objects"][0]["label"], "person")

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
