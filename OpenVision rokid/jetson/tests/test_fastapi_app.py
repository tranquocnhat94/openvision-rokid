import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from openvision_jetson.control_plane import OpenVisionControlPlane
from openvision_jetson.fastapi_app import create_app, _cors_origins, _trusted_client_host
from openvision_jetson.people_registry import ImmichClientSettings


class FakeImmichPeopleClient:
    def __init__(self):
        self.settings = ImmichClientSettings(base_url="http://immich.local:2283", api_key="test_key", api_key_source="test")

    def list_people(self):
        return [
            {
                "immich_person_id": "immich_person_1",
                "display_name": "Unknown",
                "thumbnail_ref": "http://immich.local:2283/api/people/immich_person_1/thumbnail",
                "asset_count": 3,
            }
        ]

    def update_person_name(self, immich_person_id, display_name):
        return {"status": "ok", "immich_person_id": immich_person_id, "display_name": display_name}

    def fetch_bytes(self, ref):
        return b"jpeg-bytes", "image/jpeg"


class FakeImmichPeopleNoThumbnailClient(FakeImmichPeopleClient):
    def list_people(self):
        return [{"immich_person_id": "immich_person_1", "display_name": "Unknown", "asset_count": 3}]


class FastApiAppTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(OpenVisionControlPlane()))

    def _create_iphone_session(self) -> dict:
        response = self.client.post(
            "/api/sessions",
            json={"client_kind": "iphone_simulator", "capabilities": {"video": "webrtc", "audio": "webrtc"}},
        )
        self.assertEqual(response.status_code, 201)
        return response.json()["session"]

    def _start_target_finder_live(self, session_id: str) -> str:
        response = self.client.post(
            "/api/skills/target_finder/execute",
            json={"session_id": session_id, "args": {"query": "tìm người trong đám đông", "target_type": "person"}},
        )
        self.assertEqual(response.status_code, 200)
        command = response.json()["result"]["media_command"]
        self.assertEqual(command["mode"], "live_video")
        return command["command_id"]

    def test_health_endpoint(self):
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["service"], "openvision-jetson-agent")
        self.assertIn("runtime_epoch", payload)
        self.assertIn("runtime_started_at", payload)
        self.assertEqual(payload["media_commands"], 0)
        self.assertEqual(payload["active_live_count"], 0)
        self.assertEqual(payload["rv101_h264_preview"]["status"], "disabled")

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

    def test_api_access_defaults_to_loopback_and_tailscale_not_lan(self):
        self.assertTrue(_trusted_client_host("127.0.0.1"))
        self.assertTrue(_trusted_client_host("100.100.65.42"))
        self.assertFalse(_trusted_client_host("192.168.8.44"))

    def test_websocket_access_rejects_untrusted_lan_client(self):
        client = TestClient(create_app(OpenVisionControlPlane()), client=("192.168.8.44", 50000))

        with self.assertRaises(WebSocketDisconnect) as raised:
            with client.websocket_connect("/ws/perception"):
                pass

        self.assertEqual(raised.exception.code, 1008)

    def test_websocket_access_allows_untrusted_lan_client_with_shared_token(self):
        with patch.dict("os.environ", {"OPENVISION_API_SHARED_TOKEN": "unit_test_token"}):
            client = TestClient(
                create_app(OpenVisionControlPlane()),
                client=("192.168.8.44", 50000),
                headers={"x-openvision-api-token": "unit_test_token"},
            )
            with client.websocket_connect("/ws/perception") as websocket:
                hello = websocket.receive_json()

        self.assertEqual(hello["type"], "openvision.perception_stream.v1")

    def test_cors_is_not_wildcard_by_default(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertNotIn("*", _cors_origins())

    def test_session_close_endpoint_marks_session_inactive_and_cleans_runtime(self):
        session = self._create_iphone_session()
        session_id = session["session_id"]
        self.client.post(
            f"/api/media/{session_id}/video/heartbeat",
            json={"transport": "webrtc", "codec": "raw_video", "width": 640, "height": 480, "fps": 24},
        )
        self.client.post(
            f"/api/preview/{session_id}/frame?source=iphone_unit&width=640&height=480&frame_count=1",
            content=b"png",
            headers={"content-type": "image/png"},
        )

        response = self.client.post(
            f"/api/sessions/{session_id}/close",
            json={"reason": "unit_test_cleanup"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "closed")
        sessions = self.client.get("/api/sessions").json()["sessions"]
        self.assertEqual(sessions[0]["status"], "closed")
        health = self.client.get("/api/health").json()
        self.assertEqual(health["sessions"], 0)
        self.assertEqual(health["media_sessions"], 0)
        self.assertEqual(health["preview_sessions"], 0)
        frame = self.client.get(f"/api/preview/{session_id}/frame.jpg")
        self.assertEqual(frame.status_code, 404)

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

    def test_preview_routes_endpoint_reports_stable_yolo26_overlay_route(self):
        session = self._create_iphone_session()
        self._start_target_finder_live(session["session_id"])

        response = self.client.get("/api/preview/routes")

        self.assertEqual(response.status_code, 200)
        routes = response.json()["routes"]
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0]["route_kind"], "stable_overlay_h264")
        self.assertEqual(routes[0]["primary_branch"], "yolo26_objects")
        self.assertEqual(routes[0]["ws_url"], f"/ws/preview/{session['session_id']}/h264")
        self.assertEqual(routes[0]["overlay_policy"], "stable_perception_overlay")
        self.assertEqual(routes[0]["bbox_authority"], "perception_graph_stable")
        self.assertFalse(routes[0]["jpeg_live_fallback_allowed"])

    def test_preview_routes_endpoint_keeps_stable_overlay_on_raw_h264_when_deepstream_osd_exists(self):
        session = self._create_iphone_session()
        self._start_target_finder_live(session["session_id"])
        control = self.client.app.state.control_plane
        control.rv101_h264_live.publish_sample(
            session_id=session["session_id"],
            header={"sequence": 1, "isKeyframe": True, "width": 800, "height": 600},
            payload=b"\x00\x00\x00\x01\x65raw",
            media_status={"video": {"metadata": {"rotation_degrees": 270}}},
        )

        response = self.client.get("/api/preview/routes")

        self.assertEqual(response.status_code, 200)
        routes = response.json()["routes"]
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0]["route_kind"], "stable_overlay_h264")
        self.assertEqual(routes[0]["desired_route_kind"], "stable_overlay_h264")
        self.assertEqual(routes[0]["status"], "live")
        self.assertEqual(routes[0]["ws_url"], f"/ws/preview/{session['session_id']}/h264")
        self.assertFalse(routes[0]["jpeg_live_fallback_allowed"])

        control.ingest_deepstream_h264_sample(
            session_id=session["session_id"],
            header={"sequence": 2, "isKeyframe": True, "width": 800, "height": 600},
            payload=b"\x00\x00\x00\x01\x65osd",
        )
        response = self.client.get("/api/preview/routes")
        routes = response.json()["routes"]
        self.assertEqual(routes[0]["route_kind"], "stable_overlay_h264")
        self.assertEqual(routes[0]["status"], "live")
        self.assertEqual(routes[0]["ws_url"], f"/ws/preview/{session['session_id']}/h264")

    def test_media_endpoint_hides_closed_idle_sessions(self):
        session = self._create_iphone_session()
        session_id = session["session_id"]
        self.client.app.state.control_plane.media.record_video_sample(
            session_id=session_id,
            transport="webrtc",
            codec="raw_video",
            payload_bytes=0,
            width=640,
            height=480,
            fps=24,
        )

        close = self.client.post(f"/api/sessions/{session_id}/close", json={"reason": "unit_test"})
        response = self.client.get("/api/media")

        self.assertEqual(close.status_code, 200)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["media"], [])

    def test_recording_artifacts_are_served_for_dedicated_review_page(self):
        jpeg_frame = b"\xff\xd8openvision-test-frame\xff\xd9"
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"OPENVISION_RV101_STREAM_RECORDING_DIR": temp_dir},
        ):
            recording_id = "sess_recording-20260502T070000"
            recording_dir = Path(temp_dir) / recording_id
            (recording_dir / "raw").mkdir(parents=True)
            (recording_dir / "processed").mkdir(parents=True)
            (recording_dir / "manifest.jsonl").write_text('{"type":"recording_started"}\n', encoding="utf-8")
            (recording_dir / "raw" / "video.h264").write_bytes(b"\x00\x00\x00\x01h264")
            (recording_dir / "raw" / "video.mp4").write_bytes(b"raw-mp4")
            (recording_dir / "raw" / "audio.wav").write_bytes(b"RIFFtestWAVEfmt ")
            (recording_dir / "processed" / "latest_annotated.jpg").write_bytes(jpeg_frame)
            (recording_dir / "processed" / "preview_annotated.mjpeg").write_bytes(jpeg_frame + jpeg_frame)
            (recording_dir / "processed" / "preview_annotated.mp4").write_bytes(b"processed-mp4")

            listing = self.client.get("/api/recordings")
            latest = self.client.get(f"/api/recordings/{recording_id}/files/latest-annotated")
            raw_mp4 = self.client.get(f"/api/recordings/{recording_id}/files/raw-video-mp4")
            processed_mp4 = self.client.get(f"/api/recordings/{recording_id}/files/processed-preview-mp4")
            stream = self.client.get(f"/api/recordings/{recording_id}/processed/stream.mjpeg?loop=false&fps=30")

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["recordings"][0]["recording_id"], recording_id)
        self.assertTrue(listing.json()["recordings"][0]["artifacts"]["processed_preview"]["exists"])
        self.assertTrue(listing.json()["recordings"][0]["artifacts"]["processed_preview_mp4"]["exists"])
        self.assertTrue(listing.json()["recordings"][0]["artifacts"]["raw_video_mp4"]["exists"])
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.content, jpeg_frame)
        self.assertEqual(raw_mp4.status_code, 200)
        self.assertEqual(raw_mp4.content, b"raw-mp4")
        self.assertIn("inline", raw_mp4.headers.get("content-disposition", ""))
        self.assertEqual(processed_mp4.status_code, 200)
        self.assertEqual(processed_mp4.content, b"processed-mp4")
        self.assertIn("inline", processed_mp4.headers.get("content-disposition", ""))
        self.assertEqual(stream.status_code, 200)
        self.assertIn(b"openvision-test-frame", stream.content)
        self.assertIn("multipart/x-mixed-replace", stream.headers["content-type"])

    def test_media_command_endpoint_queues_snapshot_for_known_session(self):
        session = self.client.post(
            "/api/sessions",
            json={"client_kind": "iphone_simulator", "capabilities": {"video": "webrtc"}},
        ).json()["session"]

        response = self.client.post(
            "/api/media/commands",
            json={
                "mode": "snapshot",
                "session_id": session["session_id"],
                "skill_id": "scene_describe",
                "reason": "single visual question",
            },
        )
        statuses = self.client.get("/api/media/commands")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "queued")
        self.assertEqual(payload["command"]["mode"], "snapshot")
        self.assertEqual(payload["event"]["payload"]["adapter_status"], "awaiting_media_client")
        self.assertEqual(statuses.status_code, 200)
        self.assertEqual(len(statuses.json()["media_commands"]["commands"]), 1)

    def test_media_command_event_endpoint_completes_queued_snapshot(self):
        session = self.client.post(
            "/api/sessions",
            json={"client_kind": "iphone_simulator", "capabilities": {"video": "webrtc"}},
        ).json()["session"]
        queued = self.client.post(
            "/api/media/commands",
            json={
                "mode": "snapshot",
                "session_id": session["session_id"],
                "skill_id": "scene_describe",
                "reason": "single visual question",
            },
        ).json()

        response = self.client.post(
            f"/api/media/commands/{queued['command']['command_id']}/events",
            json={
                "session_id": session["session_id"],
                "status": "ok",
                "payload": {
                    "adapter_status": "simulator_snapshot_ready",
                    "preview": {"image_url": f"/api/preview/{session['session_id']}/frame.jpg"},
                },
            },
        )
        statuses = self.client.get("/api/media/commands")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["event"]["payload"]["client_reported"])
        latest = statuses.json()["media_commands"]["commands"][0]["event"]
        self.assertEqual(latest["status"], "ok")
        self.assertEqual(latest["payload"]["adapter_status"], "simulator_snapshot_ready")

    def test_media_command_event_endpoint_accepts_client_error_status(self):
        session = self.client.post(
            "/api/sessions",
            json={"client_kind": "rv101_glasses", "capabilities": {"video": "h264"}},
        ).json()["session"]
        queued = self.client.post(
            "/api/media/commands",
            json={
                "mode": "snapshot",
                "session_id": session["session_id"],
                "skill_id": "scene_describe",
                "reason": "rv101 camera denied",
            },
        ).json()

        response = self.client.post(
            f"/api/media/commands/{queued['command']['command_id']}/events",
            json={
                "session_id": session["session_id"],
                "status": "error",
                "payload": {
                    "adapter_status": "rv101_snapshot_failed",
                    "error": "camera_requires_interactive_foreground",
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["event"]["status"], "error")
        self.assertEqual(payload["event"]["payload"]["error"], "camera_requires_interactive_foreground")

    def test_preview_upload_records_client_snapshot_frame(self):
        session = self.client.post(
            "/api/sessions",
            json={"client_kind": "rv101_glasses", "capabilities": {"video": "h264"}},
        ).json()["session"]

        response = self.client.post(
            (
                f"/api/preview/{session['session_id']}/frame"
                "?source=rv101_snapshot&width=640&height=480&frame_count=1"
                "&orientation=landscape&profile=rv101_snapshot"
                "&source_width=1280&source_height=720&preview_profile=downscaled"
                "&sensorOrientationDegrees=90&requestedWidth=1280&requestedHeight=720"
                "&captureFpsMin=15&captureFpsMax=30&sentFpsEstimate=14.7"
                "&droppedFrames=1&cameraId=0"
            ),
            content=b"jpeg-bytes",
            headers={"content-type": "image/jpeg"},
        )
        preview = self.client.get("/api/preview").json()["preview"][0]
        frame = self.client.get(f"/api/preview/{session['session_id']}/frame.jpg")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["preview"]["source"], "rv101_snapshot")
        self.assertEqual(payload["preview"]["width"], 640)
        self.assertEqual(payload["preview"]["height"], 480)
        self.assertEqual(payload["preview"]["metadata"]["orientation"], "landscape")
        self.assertEqual(payload["preview"]["metadata"]["profile"], "rv101_snapshot")
        self.assertEqual(payload["preview"]["metadata"]["preview_profile"], "downscaled")
        self.assertTrue(payload["preview"]["metadata"]["preview_downscaled"])
        self.assertEqual(payload["preview"]["metadata"]["downscaled_from"], "1280x720")
        self.assertEqual(payload["preview"]["metadata"]["sensor_orientation_degrees"], "90")
        self.assertEqual(payload["preview"]["metadata"]["requested_width"], "1280")
        self.assertEqual(payload["preview"]["metadata"]["requested_height"], "720")
        self.assertEqual(payload["preview"]["metadata"]["capture_fps_min"], "15")
        self.assertEqual(payload["preview"]["metadata"]["capture_fps_max"], "30")
        self.assertEqual(payload["preview"]["metadata"]["sent_fps_estimate"], "14.7")
        self.assertEqual(payload["preview"]["metadata"]["dropped_frames"], "1")
        self.assertEqual(payload["preview"]["metadata"]["camera_id"], "0")
        self.assertEqual(preview["image_url"], f"/api/preview/{session['session_id']}/frame.jpg")
        self.assertEqual(preview["metadata"]["orientation"], "landscape")
        self.assertEqual(self.client.get("/api/media").json()["media"], [])
        media = self.client.app.state.control_plane.media.status(session["session_id"])
        self.assertEqual(media["video"]["state"], "idle")
        self.assertEqual(media["video"]["transport"], "rv101_snapshot")
        self.assertEqual(frame.status_code, 200)
        self.assertEqual(frame.content, b"jpeg-bytes")

    def test_video_heartbeat_records_glasses_orientation_metadata(self):
        session = self.client.post(
            "/api/sessions",
            json={"client_kind": "rv101_glasses", "capabilities": {"video": "h264"}},
        ).json()["session"]

        response = self.client.post(
            f"/api/media/{session['session_id']}/video/heartbeat",
            json={
                "transport": "rv101_tcp",
                "codec": "video/avc",
                "width": 640,
                "height": 360,
                "fps": 15,
                "orientation": "landscape",
                "sensorOrientationDegrees": 90,
                "cameraProfile": "rv101_live_h264",
                "sourceWidth": 1280,
                "sourceHeight": 720,
                "requestedWidth": 1280,
                "requestedHeight": 720,
                "captureFpsMin": 15,
                "captureFpsMax": 30,
                "sentFpsEstimate": 14.7,
                "droppedFrames": 1,
                "cameraId": "0",
            },
        )

        self.assertEqual(response.status_code, 200)
        video = response.json()["video"]
        self.assertEqual(video["metadata"]["orientation"], "landscape")
        self.assertEqual(video["metadata"]["sensor_orientation_degrees"], 90)
        self.assertEqual(video["metadata"]["profile"], "rv101_live_h264")
        self.assertEqual(video["metadata"]["requested_width"], 1280)
        self.assertEqual(video["metadata"]["requested_height"], 720)
        self.assertEqual(video["metadata"]["capture_fps_min"], 15)
        self.assertEqual(video["metadata"]["capture_fps_max"], 30)
        self.assertEqual(video["metadata"]["sent_fps_estimate"], 14.7)
        self.assertEqual(video["metadata"]["dropped_frames"], 1)
        self.assertEqual(video["metadata"]["camera_id"], "0")
        self.assertEqual(video["metadata"]["preview_profile"], "downscaled")

    def test_media_command_endpoint_rejects_live_video_without_budget(self):
        session = self.client.post(
            "/api/sessions",
            json={"client_kind": "rv101_glasses", "capabilities": {"video": "h264_tcp"}},
        ).json()["session"]

        response = self.client.post(
            "/api/media/commands",
            json={
                "mode": "live_video",
                "session_id": session["session_id"],
                "skill_id": "reality_radar",
                "reason": "active target tracking",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "missing_media_budget")

    def test_media_command_endpoint_preserves_rv101_30fps_live_video_budget(self):
        session = self.client.post(
            "/api/sessions",
            json={"client_kind": "rv101_glasses", "capabilities": {"video": "h264_tcp"}},
        ).json()["session"]

        response = self.client.post(
            "/api/media/commands",
            json={
                "mode": "live_video",
                "session_id": session["session_id"],
                "skill_id": "target_finder",
                "reason": "rv101 high-fps live validation",
                "timeout_ms": 15000,
                "fps": 30,
                "resolution": {"width": 1280, "height": 720},
                "auto_stop": True,
                "params": {"action": "start"},
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["command"]["fps"], 30.0)
        self.assertEqual(payload["command"]["resolution"], {"width": 1280, "height": 720})
        self.assertEqual(payload["event"]["payload"]["budget"]["fps"], 30.0)

    def test_people_registry_endpoints_report_status_and_skipped_sync(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "people.json"
            with patch.dict(os.environ, {"OPENVISION_PEOPLE_REGISTRY_DB_PATH": str(db_path)}, clear=False):
                client = TestClient(create_app(OpenVisionControlPlane()))

                status = client.get("/api/people/status")
                sync = client.post("/api/people/sync", json={})

        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["people_registry"]["status"], "ready_empty")
        self.assertFalse(status.json()["people_registry"]["immich"]["configured"])
        self.assertEqual(sync.status_code, 200)
        self.assertEqual(sync.json()["sync"]["status"], "skipped")
        self.assertEqual(sync.json()["sync"]["reason"], "immich_unconfigured")

    def test_people_registry_update_endpoint_edits_profile_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "people.json"
            with patch.dict(os.environ, {"OPENVISION_PEOPLE_REGISTRY_DB_PATH": str(db_path)}, clear=False):
                client = TestClient(create_app(OpenVisionControlPlane()))
                control = client.app.state.control_plane
                control.people.sync_from_immich(client=FakeImmichPeopleNoThumbnailClient())
                person_id = client.get("/api/people").json()["people"][0]["person_id"]

                response = client.post(
                    f"/api/people/{person_id}",
                    json={
                        "display_name": "Tram",
                        "aliases": ["tram"],
                        "phone": "0900000000",
                        "address": "local address",
                        "age": "32",
                        "where_lives": "Da Nang",
                        "relationship": "friend from cafe",
                        "first_met": "first met at Han river",
                        "links": {"facebook": "https://facebook.example/tram"},
                        "facts": {"favorite": "coffee"},
                    },
                )
                listed = client.get("/api/people")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["person"]["display_name"], "Tram")
        self.assertEqual(listed.json()["people"][0]["phone"], "0900000000")
        self.assertEqual(listed.json()["people"][0]["age"], "32")
        self.assertEqual(listed.json()["people"][0]["where_lives"], "Da Nang")
        self.assertEqual(listed.json()["people"][0]["relationship"], "friend from cafe")
        self.assertEqual(listed.json()["people"][0]["first_met"], "first met at Han river")
        self.assertEqual(listed.json()["people"][0]["links"]["facebook"], "https://facebook.example/tram")
        self.assertEqual(listed.json()["people"][0]["facts"]["favorite"], "coffee")

    def test_people_identity_enroll_endpoint_requires_named_person_and_thumbnail(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "people.json"
            with patch.dict(os.environ, {"OPENVISION_PEOPLE_REGISTRY_DB_PATH": str(db_path)}, clear=False):
                client = TestClient(create_app(OpenVisionControlPlane()))
                control = client.app.state.control_plane
                control.people.sync_from_immich(client=FakeImmichPeopleClient())
                person_id = client.get("/api/people").json()["people"][0]["person_id"]
                control.update_person_profile(person_id=person_id, display_name="")

                missing_name = client.post(f"/api/people/{person_id}/enroll-identity", json={})
                missing_thumbnail = client.post(
                    f"/api/people/{person_id}/enroll-identity",
                    json={"display_name": "Tram", "aliases": ["tram"]},
                )

        self.assertEqual(missing_name.status_code, 400)
        self.assertEqual(missing_name.json()["detail"]["code"], "invalid_people_identity_enrollment")
        self.assertIn("display_name", missing_name.json()["detail"]["message"])
        self.assertEqual(missing_thumbnail.status_code, 503)
        self.assertEqual(missing_thumbnail.json()["detail"]["code"], "people_identity_provider_unavailable")

    def test_people_thumbnail_endpoint_proxies_immich_bytes_without_exposing_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "people.json"
            with patch.dict(os.environ, {"OPENVISION_PEOPLE_REGISTRY_DB_PATH": str(db_path)}, clear=False):
                client = TestClient(create_app(OpenVisionControlPlane()))
                control = client.app.state.control_plane
                control.people.sync_from_immich(client=FakeImmichPeopleClient())
                person_id = client.get("/api/people").json()["people"][0]["person_id"]

                with patch("openvision_jetson.control_plane.ImmichClient", return_value=FakeImmichPeopleClient()):
                    response = client.get(f"/api/people/{person_id}/thumbnail")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"jpeg-bytes")
        self.assertEqual(response.headers["content-type"], "image/jpeg")
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_realtime_start_blocks_without_key(self):
        session = self.client.post(
            "/api/sessions",
            json={"client_kind": "iphone_simulator", "capabilities": {}},
        ).json()["session"]

        response = self.client.post(
            f"/api/realtime/{session['session_id']}/start",
            json={"output_modalities": ["text"]},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["turn_policy"], "server_vad")
        self.assertEqual(payload["error"]["code"], "missing_openai_api_key")

    def test_realtime_start_rejects_unknown_turn_policy(self):
        session = self.client.post(
            "/api/sessions",
            json={"client_kind": "iphone_simulator", "capabilities": {}},
        ).json()["session"]

        response = self.client.post(
            f"/api/realtime/{session['session_id']}/start",
            json={"turn_policy": "local_gate"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("Unsupported turn_policy", response.json()["detail"])

    def test_realtime_start_can_request_voice_output(self):
        session = self.client.post(
            "/api/sessions",
            json={"client_kind": "iphone_simulator", "capabilities": {}},
        ).json()["session"]

        response = self.client.post(
            f"/api/realtime/{session['session_id']}/start",
            json={"voice_output": True},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["turn_policy"], "server_vad")
        self.assertEqual(response.json()["output_modalities"], ["audio"])

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

    def test_display_command_endpoint_updates_latest_hud_scene(self):
        session = self.client.post(
            "/api/sessions",
            json={"client_kind": "iphone_simulator", "capabilities": {"hud": "scene_json"}},
        ).json()["session"]

        response = self.client.post(
            "/api/display/commands",
            json={
                "kind": "text_hud",
                "session_id": session["session_id"],
                "skill_id": "scene_describe",
                "payload": {"text": "Ben trai co mot nguoi", "edge_chips": ["display"]},
            },
        )
        latest = self.client.get(f"/api/hud/{session['session_id']}/latest")
        statuses = self.client.get("/api/display/commands")
        scorecard = self.client.get(f"/api/scorecard/{session['session_id']}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["command"]["kind"], "text_hud")
        self.assertEqual(response.json()["hud_scene"]["answer_strip"], "Ben trai co mot nguoi")
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.json()["hud_scene"]["edge_chips"], ["display"])
        self.assertEqual(statuses.status_code, 200)
        self.assertEqual(len(statuses.json()["display_commands"]), 1)
        self.assertEqual(scorecard.json()["scorecard"]["metrics"]["display_command_count"], 1)

    def test_display_command_endpoint_rejects_invalid_payload(self):
        session = self.client.post(
            "/api/sessions",
            json={"client_kind": "rv101_glasses", "capabilities": {"hud": "scene_json"}},
        ).json()["session"]

        response = self.client.post(
            "/api/display/commands",
            json={
                "kind": "full_image",
                "session_id": session["session_id"],
                "payload": {"title": "Missing image"},
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "missing_display_payload_field")

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
        self.assertEqual(frame.headers["x-openvision-frame-count"], "1")

    def test_preview_status_surfaces_active_processed_preview(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"OPENVISION_RV101_STREAM_RECORDING": "1", "OPENVISION_RV101_STREAM_RECORDING_DIR": temp_dir},
        ):
            control = self.client.app.state.control_plane
            control.preview.record_frame(
                session_id="sess_processed",
                source="unit",
                image_bytes=b"raw-jpeg",
                width=320,
                height=240,
                frame_count=1,
            )
            control.stream_recorder.record_processed_preview(
                session_id="sess_processed",
                image_bytes=b"processed-jpeg",
                frame_count=1,
                width=320,
                height=240,
                perception={"source": "unit", "objects": []},
            )
            control.stream_recorder._queue.join()

            status = self.client.get("/api/preview")
            latest = self.client.get("/api/preview/sess_processed/processed/frame.jpg")
            removed_stream = self.client.get("/api/preview/sess_processed/processed/stream.mjpeg?max_frames=1")

        self.assertEqual(status.status_code, 200)
        preview = status.json()["preview"][0]
        self.assertTrue(preview["has_processed_preview"])
        self.assertEqual(preview["processed_preview_kind"], "jetson_annotated")
        self.assertNotIn("processed_mjpeg_url", preview)
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.content, b"processed-jpeg")
        self.assertEqual(removed_stream.status_code, 404)

    def test_preview_frame_endpoint_can_return_retained_exact_frame(self):
        self.client.app.state.control_plane.preview.record_frame(
            session_id="sess_test",
            source="unit",
            image_bytes=b"jpeg1",
            frame_count=1,
        )
        self.client.app.state.control_plane.preview.record_frame(
            session_id="sess_test",
            source="unit",
            image_bytes=b"jpeg2",
            frame_count=2,
        )

        frame = self.client.get("/api/preview/sess_test/frame.jpg?frame_count=1")

        self.assertEqual(frame.status_code, 200)
        self.assertEqual(frame.content, b"jpeg1")
        self.assertEqual(frame.headers["x-openvision-frame-count"], "1")

    def test_preview_stream_returns_404_without_decoded_frame(self):
        response = self.client.get("/api/preview/sess_missing/stream.mjpeg")

        self.assertEqual(response.status_code, 404)

    def test_h264_preview_status_and_websocket_return_raw_sample(self):
        control = self.client.app.state.control_plane
        control.rv101_h264_live.publish_sample(
            session_id="sess_h264",
            header={"sequence": 3, "isKeyframe": True, "width": 1280, "height": 720},
            payload=b"\x00\x00\x00\x01\x65idr",
            media_status={"video": {"metadata": {"rotation_degrees": 270}}},
        )

        status = self.client.get("/api/preview/sess_h264/h264")
        with self.client.websocket_connect("/ws/preview/sess_h264/h264") as websocket:
            hello = websocket.receive_json()
            sample_meta = websocket.receive_json()
            sample_payload = websocket.receive_bytes()

        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["h264_live"]["h264_ws_url"], "/ws/preview/sess_h264/h264")
        self.assertEqual(hello["type"], "openvision.h264_preview.v1")
        self.assertEqual(sample_meta["type"], "sample")
        self.assertEqual(sample_meta["sequence"], 3)
        self.assertEqual(sample_meta["metadata"]["rotation_degrees"], 270)
        self.assertEqual(sample_payload, b"\x00\x00\x00\x01\x65idr")

    def test_deepstream_h264_preview_status_and_websocket_return_annotated_sample(self):
        control = self.client.app.state.control_plane
        session = self._create_iphone_session()
        session_id = session["session_id"]
        self._start_target_finder_live(session_id)
        control.ingest_deepstream_h264_sample(
            session_id=session_id,
            header={
                "sequence": 7,
                "isKeyframe": True,
                "width": 800,
                "height": 600,
                "rotationDegrees": 270,
            },
            payload=b"\x00\x00\x00\x01\x65deepstream",
        )

        preview = self.client.get("/api/preview").json()["preview"]
        status = self.client.get(f"/api/preview/{session_id}/deepstream-h264")
        with self.client.websocket_connect(f"/ws/preview/{session_id}/deepstream-h264") as websocket:
            hello = websocket.receive_json()
            sample_meta = websocket.receive_json()
            sample_payload = websocket.receive_bytes()

        deepstream_preview = next(item for item in preview if item["session_id"] == session_id)
        self.assertTrue(deepstream_preview["has_deepstream_h264_live"])
        self.assertEqual(deepstream_preview["deepstream_h264_ws_url"], f"/ws/preview/{session_id}/deepstream-h264")
        self.assertFalse(deepstream_preview["has_frame"])
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["h264_live"]["source"], "deepstream_yolo26_osd")
        self.assertEqual(status.json()["h264_live"]["h264_ws_url"], f"/ws/preview/{session_id}/deepstream-h264")
        self.assertEqual(hello["type"], "openvision.h264_preview.v1")
        self.assertEqual(hello["source"], "deepstream_yolo26_osd")
        self.assertEqual(sample_meta["type"], "sample")
        self.assertEqual(sample_meta["sequence"], 7)
        self.assertEqual(sample_meta["metadata"]["source"], "deepstream_yolo26_osd")
        self.assertEqual(sample_meta["metadata"]["transport"], "deepstream_rtsp_h264")
        self.assertEqual(sample_meta["metadata"]["rotation_degrees"], 270)
        self.assertEqual(sample_payload, b"\x00\x00\x00\x01\x65deepstream")

    def test_perception_snapshot_and_execute_count(self):
        session = self._create_iphone_session()
        session_id = session["session_id"]
        snapshot = self.client.post(
            f"/api/perception/{session_id}/detections",
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
            json={"session_id": session_id, "args": {"min_confidence": 0.25}},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["count"], 2)

        hud = self.client.get(f"/api/hud/{session_id}/latest")
        self.assertEqual(hud.status_code, 200)
        self.assertEqual(hud.json()["hud_scene"]["answer_strip"], "2 người")

    def test_debug_perception_endpoint_rejects_unknown_session(self):
        response = self.client.post(
            "/api/perception/sess_missing/detections",
            json={"source": "unit", "detections": [{"label": "person", "confidence": 0.9}]},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "inactive_or_unknown_session")

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
        session = self._create_iphone_session()
        session_id = session["session_id"]
        for frame_id in ("frame_1", "frame_2"):
            response = self.client.post(
                f"/api/perception/{session_id}/detections",
                json={
                    "source": "unit",
                    "frame_id": frame_id,
                    "width": 640,
                    "height": 480,
                    "detections": [{"track_id": "p1", "label": "person", "confidence": 0.9, "bbox": [20, 100, 160, 350]}],
                },
            )
            self.assertEqual(response.status_code, 200)

        history = self.client.get(f"/api/perception/{session_id}/history?limit=5")

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

    def test_yolo26_worker_status_endpoint_is_redacted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            status_dir = Path(temp_dir) / "status"
            status_dir.mkdir(parents=True)
            (status_dir / "deepstream_yolo26_worker.json").write_text(
                '{"status":"blocked","message":"missing model","model_path":"/secret/model.engine"}',
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"OPENVISION_RUNTIME_DIR": temp_dir}):
                response = self.client.get("/api/adapters/yolo26/worker")

        self.assertEqual(response.status_code, 200)
        payload = response.json()["worker"]
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["total_posted_frame_count"], 0)
        self.assertIsNone(payload["last_posted_frame"])
        self.assertNotIn("model_path", payload)
        self.assertNotIn("/secret/model.engine", str(payload))

    def test_yolo26_worker_status_endpoint_reports_missing_status_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"OPENVISION_RUNTIME_DIR": temp_dir}):
                response = self.client.get("/api/adapters/yolo26/worker")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["worker"]["status"], "not_reported")
        self.assertEqual(response.json()["worker"]["backend"], "deepstream")
        self.assertEqual(response.json()["worker"]["total_posted_frame_count"], 0)

    def test_crop_endpoint_serves_worker_crop_from_runtime(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            crop_dir = Path(temp_dir) / "crops" / "sess_test"
            crop_dir.mkdir(parents=True)
            (crop_dir / "p1_latest.jpg").write_bytes(b"jpeg")
            with patch.dict(os.environ, {"OPENVISION_RUNTIME_DIR": temp_dir}):
                response = self.client.get("/api/crops/sess_test/p1_latest.jpg")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"jpeg")
        self.assertEqual(response.headers["content-type"], "image/jpeg")

    def test_identity_endpoints_enroll_and_match_vector_sample(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"OPENVISION_RUNTIME_DIR": temp_dir}):
                client = TestClient(create_app(OpenVisionControlPlane()))
                enrolled = client.post(
                    "/api/identity/enroll",
                    json={
                        "display_name": "Trâm",
                        "aliases": ["tram"],
                        "vector": [1.0, 0.0, 0.0],
                    },
                )
                status = client.get("/api/identity/status")
                contacts = client.get("/api/identity/contacts")
                matched = client.post(
                    "/api/identity/match",
                    json={
                        "query": "tìm Trâm",
                        "session_id": "sess_test",
                        "candidates": [
                            {
                                "target_id": "obj_1",
                                "track_id": "p1",
                                "label": "person",
                                "attributes": {"identity_vector": [0.99, 0.01, 0.0]},
                            }
                        ],
                    },
                )

        self.assertEqual(enrolled.status_code, 201)
        self.assertEqual(enrolled.json()["status"], "enrolled")
        self.assertEqual(status.json()["identity"]["sample_count"], 1)
        self.assertEqual(contacts.json()["contacts"][0]["display_name"], "Trâm")
        self.assertNotIn("vector", contacts.json()["contacts"][0]["samples"][0])
        self.assertEqual(matched.json()["identity_match"]["status"], "confirmed")
        self.assertEqual(matched.json()["identity_match"]["matches"][0]["display_name"], "Trâm")

    def test_target_finder_uses_enrolled_identity_db_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "OPENVISION_RUNTIME_DIR": temp_dir,
                    "OPENVISION_YOLO26_MODE": "external_stream",
                    "OPENVISION_IDENTITY_MIN_CONFIDENCE": "0.8",
                },
            ):
                client = TestClient(create_app(OpenVisionControlPlane()))
                session = client.post(
                    "/api/sessions",
                    json={"client_kind": "iphone_simulator", "capabilities": {"video": "webrtc"}},
                ).json()["session"]
                client.post(
                    "/api/identity/enroll",
                    json={"display_name": "Trâm", "aliases": ["tram"], "vector": [1.0, 0.0, 0.0]},
                )
                queued = client.post(
                    "/api/skills/target_finder/execute",
                    json={
                        "session_id": session["session_id"],
                        "args": {"query": "tìm Trâm trong đám đông", "target_type": "person"},
                    },
                )
                self.assertEqual(queued.status_code, 200)
                self.assertEqual(queued.json()["status"], "no_evidence")
                client.post(
                    f"/api/adapters/yolo26/{session['session_id']}/stream",
                    json={
                        "source": "openvision_iphone_yolo26",
                        "frame_id": "live_identity_1",
                        "width": 640,
                        "height": 480,
                        "detections": [
                            {
                                "label": "person",
                                "confidence": 0.92,
                                "bbox": [280, 120, 390, 430],
                                "track_id": "p1",
                                "attributes": {"identity_vector": [0.99, 0.01, 0.0]},
                            }
                        ],
                    },
                )

                result = client.post(
                    "/api/skills/target_finder/execute",
                    json={
                        "session_id": session["session_id"],
                        "args": {"query": "tìm Trâm trong đám đông", "target_type": "person"},
                    },
                )

        self.assertEqual(result.status_code, 200)
        payload = result.json()
        self.assertEqual(payload["result"]["identity_policy"]["status"], "contact_match_confirmed")
        self.assertEqual(payload["result"]["target_hint"]["display_name"], "Trâm")
        self.assertIn("contact_db", payload["result"]["hud"]["edge_chips"])

    def test_yolo26_adapter_ingress_requires_explicit_mode(self):
        response = self.client.post(
            "/api/adapters/yolo26/sess_test/detections",
            json={"source": "unit", "detections": [{"label": "person", "confidence": 0.9}]},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "adapter_disabled")

    def test_yolo26_adapter_ingress_updates_perception_when_enabled(self):
        session = self._create_iphone_session()
        with patch.dict(os.environ, {"OPENVISION_YOLO26_MODE": "external_snapshot"}):
            response = self.client.post(
                f"/api/adapters/yolo26/{session['session_id']}/detections",
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

    def test_yolo26_adapter_ingress_rejects_unknown_session_when_enabled(self):
        with patch.dict(os.environ, {"OPENVISION_YOLO26_MODE": "external_snapshot"}):
            response = self.client.post(
                "/api/adapters/yolo26/sess_missing/detections",
                json={"source": "rokid_yolo26_unit", "detections": [{"label": "person", "confidence": 0.9}]},
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "unknown_session")

    def test_yolo26_adapter_rejects_ring_source_when_enabled(self):
        with patch.dict(os.environ, {"OPENVISION_YOLO26_MODE": "external_snapshot"}):
            response = self.client.post(
                "/api/adapters/yolo26/sess_test/detections",
                json={"source": "ring_security_yolo26", "detections": [{"label": "person", "confidence": 0.9}]},
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "forbidden_snapshot_source")

    def test_yolo26_stream_ingress_updates_perception_when_enabled(self):
        session = self._create_iphone_session()
        self._start_target_finder_live(session["session_id"])
        with patch.dict(os.environ, {"OPENVISION_YOLO26_MODE": "external_stream"}):
            response = self.client.post(
                f"/api/adapters/yolo26/{session['session_id']}/stream",
                json={
                    "source": "openvision_iphone_yolo26",
                    "frame_id": "live_42",
                    "sequence": 42,
                    "latency_ms": 18.5,
                    "width": 640,
                    "height": 480,
                    "detections": [
                        {"label": "person", "confidence": 0.92, "bbox": [32, 96, 180, 420], "track_id": "p1"},
                        {"label": "bottle", "confidence": 0.31, "bbox": [420, 240, 470, 390], "track_id": "b1"},
                        {"label": "bag", "confidence": 0.08, "bbox": [240, 100, 360, 260]},
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "accepted")
        self.assertEqual(payload["source"], "yolo26_rokid_stream:openvision_iphone_yolo26")
        self.assertEqual(payload["accepted_detection_count"], 1)
        self.assertEqual(payload["raw_accepted_detection_count"], 2)
        self.assertEqual(payload["rejected_detection_count"], 1)
        self.assertEqual(payload["stabilizer"]["emitted_count"], 1)
        self.assertGreaterEqual(payload["stabilizer"]["rejected_low_confidence"], 1)
        self.assertEqual(payload["sequence"], 42)
        self.assertEqual(payload["latency_ms"], 18.5)
        self.assertEqual(payload["perception"]["source"], "yolo26_rokid_stream:openvision_iphone_yolo26")
        self.assertEqual(payload["perception"]["frame_id"], "live_42")
        self.assertEqual(payload["perception"]["objects"][0]["track_id"], "p1")
        self.assertEqual(payload["perception"]["objects"][0]["bbox"], [32.0, 96.0, 180.0, 420.0])
        self.assertEqual(payload["perception"]["metadata"]["detector_width"], 640)
        self.assertEqual(payload["perception"]["metadata"]["detector_height"], 480)
        self.assertEqual(payload["perception"]["metadata"]["preview_route_kind"], "stable_overlay_h264")
        self.assertEqual(payload["perception"]["metadata"]["bbox_authority"], "perception_graph_stable")
        self.assertNotIn("preview_width", payload["perception"]["metadata"])
        self.assertNotIn("preview_height", payload["perception"]["metadata"])

        perception = self.client.get("/api/perception")
        self.assertEqual(perception.status_code, 200)
        latest = perception.json()["perception"][0]
        self.assertEqual(latest["session_id"], session["session_id"])
        self.assertEqual(len(latest["objects"]), 1)

    def test_yolo26_stream_ingress_normalizes_iphone_source_for_rv101_session(self):
        session = self.client.post(
            "/api/sessions",
            json={"client_kind": "rv101_glasses", "capabilities": {"video": "h264_tcp", "audio": "pcm_tcp"}},
        ).json()["session"]
        self._start_target_finder_live(session["session_id"])
        with patch.dict(os.environ, {"OPENVISION_YOLO26_MODE": "external_stream"}):
            response = self.client.post(
                f"/api/adapters/yolo26/{session['session_id']}/stream",
                json={
                    "source": "openvision_iphone_yolo26",
                    "frame_id": "live_rv101_1",
                    "sequence": 1,
                    "width": 640,
                    "height": 360,
                    "sensorOrientationDegrees": 90,
                    "cameraId": "0",
                    "detections": [
                        {"label": "person", "confidence": 0.92, "bbox": [32, 96, 180, 320], "track_id": "p1"},
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["source"], "yolo26_rokid_stream:openvision_rv101_yolo26")
        self.assertEqual(payload["perception"]["source"], "yolo26_rokid_stream:openvision_rv101_yolo26")
        self.assertEqual(payload["perception"]["metadata"]["raw_source"], "openvision_iphone_yolo26")
        self.assertEqual(payload["perception"]["metadata"]["normalized_source"], "openvision_rv101_yolo26")
        self.assertEqual(payload["perception"]["metadata"]["sensor_orientation_degrees"], 90)
        self.assertEqual(payload["perception"]["metadata"]["camera_id"], "0")

    def test_yolo26_stream_ingress_rejects_inactive_live_session_when_enabled(self):
        session = self._create_iphone_session()
        with patch.dict(os.environ, {"OPENVISION_YOLO26_MODE": "external_stream"}):
            response = self.client.post(
                f"/api/adapters/yolo26/{session['session_id']}/stream",
                json={
                    "source": "openvision_iphone_yolo26",
                    "detections": [{"label": "person", "confidence": 0.9}],
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "inactive_live_skill")

    def test_yolo26_stream_ingress_rejects_ring_source_when_enabled(self):
        with patch.dict(os.environ, {"OPENVISION_YOLO26_MODE": "external_stream"}):
            response = self.client.post(
                "/api/adapters/yolo26/sess_test/stream",
                json={"source": "ring_security_yolo26", "detections": [{"label": "person", "confidence": 0.9}]},
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "forbidden_stream_source")

    def test_yolo26_stream_endpoint_requires_stream_mode(self):
        with patch.dict(os.environ, {"OPENVISION_YOLO26_MODE": "external_snapshot"}):
            response = self.client.post(
                "/api/adapters/yolo26/sess_test/stream",
                json={"source": "openvision_iphone_yolo26", "detections": [{"label": "person", "confidence": 0.9}]},
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "adapter_mode_mismatch")

    def test_face_identity_stream_ingress_updates_perception(self):
        session = self._create_iphone_session()
        self._start_target_finder_live(session["session_id"])
        response = self.client.post(
            f"/api/adapters/face-identity/{session['session_id']}/stream",
            json={
                "source": "openvision_iphone_face_identity",
                "frame_id": "face_42",
                "sequence": 42,
                "latency_ms": 9.5,
                "width": 640,
                "height": 480,
                "detections": [
                    {
                        "label": "person",
                        "confidence": 0.91,
                        "bbox": [220, 80, 320, 230],
                        "track_id": "f1",
                        "attributes": {"identity_vector": [1.0, 0.0], "face_confidence": 0.91},
                    },
                    {"label": "person", "confidence": 0.2, "bbox": [20, 20, 80, 100]},
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "accepted")
        self.assertEqual(payload["source"], "face_identity_stream:openvision_iphone_face_identity")
        self.assertEqual(payload["accepted_detection_count"], 1)
        self.assertEqual(payload["rejected_detection_count"], 1)
        self.assertEqual(payload["perception"]["source"], "face_identity_stream:openvision_iphone_face_identity")
        self.assertEqual(payload["perception"]["objects"][0]["attributes"]["identity_vector"], [1.0, 0.0])
        self.assertEqual(payload["perception"]["objects"][0]["attributes"]["detector_family"], "face_identity")

    def test_face_identity_stream_ingress_normalizes_iphone_source_for_rv101_session(self):
        session = self.client.post(
            "/api/sessions",
            json={"client_kind": "rv101_glasses", "capabilities": {"video": "h264_tcp", "audio": "pcm_tcp"}},
        ).json()["session"]
        self._start_target_finder_live(session["session_id"])

        response = self.client.post(
            f"/api/adapters/face-identity/{session['session_id']}/stream",
            json={
                "source": "openvision_iphone_face_identity",
                "frame_id": "face_rv101_1",
                "sequence": 1,
                "width": 640,
                "height": 360,
                "orientation": "landscape",
                "profile": "rv101_live_h264",
                "detections": [
                    {
                        "label": "person",
                        "confidence": 0.91,
                        "bbox": [220, 80, 320, 230],
                        "track_id": "f1",
                        "attributes": {"identity_vector": [1.0, 0.0], "face_confidence": 0.91},
                    },
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["source"], "face_identity_stream:openvision_rv101_face_identity")
        self.assertEqual(payload["perception"]["source"], "face_identity_stream:openvision_rv101_face_identity")
        self.assertEqual(payload["perception"]["metadata"]["raw_source"], "openvision_iphone_face_identity")
        self.assertEqual(payload["perception"]["metadata"]["normalized_source"], "openvision_rv101_face_identity")
        self.assertEqual(payload["perception"]["metadata"]["orientation"], "landscape")

    def test_face_identity_stream_ingress_rejects_unknown_session(self):
        response = self.client.post(
            "/api/adapters/face-identity/sess_missing/stream",
            json={"source": "openvision_iphone_face_identity", "detections": [{"label": "person", "confidence": 0.9}]},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "unknown_session")

    def test_face_identity_stream_ingress_rejects_ring_source(self):
        response = self.client.post(
            "/api/adapters/face-identity/sess_test/stream",
            json={"source": "ring_security_face_id", "detections": [{"label": "person", "confidence": 0.9}]},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "forbidden_stream_source")

    def test_face_identity_worker_status_endpoint(self):
        response = self.client.get("/api/adapters/face-identity/worker")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["worker"]["schema_version"], "openvision.face_identity_worker_status.v1")

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
        self.assertEqual(accept["voiceMode"], "conversation_realtime")
        self.assertEqual(accept["voice_mode"], "conversation_realtime")
        self.assertEqual(accept["turnPolicy"], "server_vad")
        self.assertEqual(accept["turn_policy"], "server_vad")
        self.assertFalse(accept["voiceOutput"]["enabled"])
        self.assertEqual(accept["voiceOutput"]["transport"], "ws_pcm")
        self.assertFalse(accept["voiceOutput"]["requiresRestBootstrap"])
        self.assertEqual(hud["type"], "hud_scene")
        self.assertEqual(pong["type"], "pong")

    def test_rv101_control_ws_accepts_voice_output_without_rest_bootstrap(self):
        with self.client.websocket_connect("/ws") as websocket:
            websocket.send_json(
                {
                    "type": "client_hello",
                    "deviceId": "rv101-test",
                    "appVersion": "test",
                    "videoCodec": "h264",
                    "voiceOutput": True,
                }
            )
            accept = websocket.receive_json()
            websocket.receive_json()

        self.assertEqual(accept["type"], "session_accept")
        self.assertEqual(accept["voiceMode"], "conversation_realtime")
        self.assertEqual(accept["turnPolicy"], "server_vad")
        self.assertTrue(accept["voiceOutput"]["enabled"])
        self.assertEqual(accept["voice_output"], accept["voiceOutput"])
        self.assertEqual(accept["voiceOutput"]["path"], f"/ws/realtime/{accept['sessionId']}/audio")
        self.assertEqual(accept["voiceOutput"]["websocketPath"], f"/ws/realtime/{accept['sessionId']}/audio")
        self.assertEqual(accept["voiceOutput"]["outputModalities"], ["audio"])
        self.assertEqual(accept["voiceOutput"]["sampleRateHz"], 24000)
        self.assertFalse(accept["voiceOutput"]["requiresRestBootstrap"])

    def test_rv101_control_ws_disconnect_marks_session_disconnected(self):
        control = OpenVisionControlPlane()
        control.realtime.start = AsyncMock(return_value={"status": "connected"})
        control.realtime.stop = AsyncMock(return_value={"status": "stopped"})
        client = TestClient(create_app(control))

        with client.websocket_connect("/ws") as websocket:
            websocket.send_json(
                {
                    "type": "client_hello",
                    "deviceId": "rv101-test",
                    "appVersion": "test",
                    "videoCodec": "h264",
                }
            )
            accept = websocket.receive_json()
            websocket.receive_json()
            session_id = accept["sessionId"]

        sessions = {session["session_id"]: session for session in control.list_sessions()}
        self.assertEqual(sessions[session_id]["status"], "disconnected")
        self.assertEqual(control.health()["sessions"], 0)
        control.realtime.stop.assert_not_awaited()
        api_sessions = {session["session_id"]: session for session in client.get("/api/sessions").json()["sessions"]}
        self.assertEqual(api_sessions[session_id]["status"], "disconnected")

    def test_rv101_control_ws_reconnect_supersedes_prior_same_device_session(self):
        control = OpenVisionControlPlane()
        control.realtime.start = AsyncMock(return_value={"status": "connected"})
        control.realtime.stop = AsyncMock(return_value={"status": "stopped"})
        client = TestClient(create_app(control))

        with client.websocket_connect("/ws") as first_ws:
            first_ws.send_json(
                {
                    "type": "client_hello",
                    "deviceId": "rv101-test",
                    "appVersion": "test",
                    "videoCodec": "h264",
                }
            )
            first_accept = first_ws.receive_json()
            first_ws.receive_json()
            first_session_id = first_accept["sessionId"]

            with client.websocket_connect("/ws") as second_ws:
                second_ws.send_json(
                    {
                        "type": "client_hello",
                        "deviceId": "rv101-test",
                        "appVersion": "test",
                        "videoCodec": "h264",
                    }
                )
                second_accept = second_ws.receive_json()
                second_ws.receive_json()
                second_session_id = second_accept["sessionId"]

                sessions = {session["session_id"]: session for session in control.list_sessions()}
                self.assertEqual(sessions[first_session_id]["status"], "superseded")
                self.assertEqual(sessions[second_session_id]["status"], "connected")
                self.assertEqual(control.health()["sessions"], 1)
                api_sessions = {
                    session["session_id"]: session for session in client.get("/api/sessions").json()["sessions"]
                }
                self.assertEqual(api_sessions[first_session_id]["status"], "superseded")
                self.assertEqual(api_sessions[second_session_id]["status"], "connected")

        sessions = {session["session_id"]: session for session in control.list_sessions()}
        self.assertEqual(sessions[first_session_id]["status"], "superseded")
        self.assertEqual(sessions[second_session_id]["status"], "disconnected")
        self.assertEqual(control.health()["sessions"], 0)
        control.realtime.stop.assert_awaited_once_with(first_session_id)

    def test_rv101_control_ws_pushes_latest_hud_on_heartbeat(self):
        control = OpenVisionControlPlane()
        client = TestClient(create_app(control))

        with client.websocket_connect("/ws") as websocket:
            websocket.send_json(
                {
                    "type": "client_hello",
                    "deviceId": "rv101-test",
                    "appVersion": "test",
                    "videoCodec": "h264",
                }
            )
            accept = websocket.receive_json()
            websocket.receive_json()

            control.test_hud(accept["sessionId"])
            websocket.send_json({"type": "ping", "timestampMs": 123})
            messages = [websocket.receive_json(), websocket.receive_json()]

        pong = next(message for message in messages if message["type"] == "pong")
        pushed = next(message for message in messages if message["type"] == "hud_scene")
        self.assertEqual(pong["type"], "pong")
        self.assertEqual(pushed["type"], "hud_scene")
        self.assertEqual(pushed["scene"]["answer_strip"], "HUD test OK")

    def test_rv101_control_ws_pushes_hud_without_waiting_for_next_heartbeat(self):
        control = OpenVisionControlPlane()
        client = TestClient(create_app(control))

        with client.websocket_connect("/ws") as websocket:
            websocket.send_json(
                {
                    "type": "client_hello",
                    "deviceId": "rv101-test",
                    "appVersion": "test",
                    "videoCodec": "h264",
                }
            )
            accept = websocket.receive_json()
            websocket.receive_json()

            control.test_hud(accept["sessionId"])
            pushed = websocket.receive_json()

        self.assertEqual(pushed["type"], "hud_scene")
        self.assertEqual(pushed["scene"]["answer_strip"], "HUD test OK")

    def test_perception_ws_pushes_snapshot_without_rest_polling(self):
        control = OpenVisionControlPlane()
        client = TestClient(create_app(control))

        with client.websocket_connect("/ws/perception") as websocket:
            hello = websocket.receive_json()
            control.perception.update_snapshot(
                session_id="sess_test",
                source="unit",
                detections=[{"label": "person", "confidence": 0.9}],
                frame_id="frame_1",
                width=320,
                height=240,
            )
            pushed = websocket.receive_json()

        self.assertEqual(hello["type"], "openvision.perception_stream.v1")
        self.assertEqual(pushed["type"], "perception_snapshot")
        self.assertEqual(pushed["snapshot"]["session_id"], "sess_test")
        self.assertEqual(pushed["snapshot"]["objects"][0]["label"], "person")


if __name__ == "__main__":
    unittest.main()
