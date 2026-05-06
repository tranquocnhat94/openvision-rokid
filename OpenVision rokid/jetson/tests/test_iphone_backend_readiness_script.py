import importlib.util
import struct
from pathlib import Path
import sys
import unittest
import zlib


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "score_iphone_backend_readiness.py"
SPEC = importlib.util.spec_from_file_location("score_iphone_backend_readiness", SCRIPT)
readiness_script = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = readiness_script
SPEC.loader.exec_module(readiness_script)


class FakeApi:
    base_url = "http://jetson.local:8765"

    def __init__(self):
        self.session_counter = 0
        self.active_live = set()

    def get(self, path, *, timeout=8.0):
        if path == "/api/health":
            return {
                "ok": True,
                "runtime_epoch": "123:boot",
                "sessions": 0,
                "total_sessions": self.session_counter,
                "active_live_count": len(self.active_live),
                "voice_output": True,
                "cloud_verify_enabled": True,
                "yolo26_adapter_status": "ready",
                "face_identity_adapter_status": "ready",
                "people_registry_status": "ready",
                "identity_status": "ready",
                "rv101_tcp_ingest": "running",
            }
        if path.startswith("/api/scorecard/"):
            return {
                "scorecard": {
                    "session_id": path.rsplit("/", 1)[-1],
                    "status": "pass",
                    "score": 100,
                    "metrics": {"skill_eval_status": "pass"},
                }
            }
        if path.startswith("/api/replay/"):
            return {"replay": {"session_id": path.rsplit("/", 1)[-1], "redacted": True, "events": [{"module": "skills"}]}}
        if path == "/api/media/commands":
            return {"media_commands": {"active_live": []}}
        raise AssertionError(f"unexpected GET {path}")

    def post_json(self, path, payload, *, timeout=12.0):
        if path == "/api/sessions":
            self.session_counter += 1
            return {"session": {"session_id": f"sess_{self.session_counter}", "client_kind": "iphone_simulator"}}
        if path.startswith("/api/sessions/") and path.endswith("/close"):
            return {"status": "closed", "session": {"session_id": path.split("/")[-2], "status": "closed"}}
        if "/video/heartbeat" in path:
            return {"video": {"state": "receiving", "transport": "webrtc", "fps": payload.get("fps"), "frame_count": 0}}
        if "/audio/metrics" in path:
            return {
                "audio": {
                    "state": "receiving",
                    "transport": "webrtc",
                    "chunk_count": payload.get("chunk_count"),
                    "strong_chunk_count": payload.get("strong_chunk_count"),
                    "strong_chunk_ratio": 0.75,
                }
            }
        if path.startswith("/api/perception/"):
            return {"source": payload.get("source"), "objects": payload.get("detections") or []}
        if path == "/api/skills/count_people/execute":
            return {"status": "ok", "result": {"count": 2, "hud": {"answer_strip": "2 người"}}}
        if path == "/api/skills/object_counter/execute":
            return {"status": "ok", "result": {"count": 1, "hud": {"answer_strip": "Có 1 cup."}}}
        if path == "/api/skills/person_info/execute":
            return {
                "status": "no_evidence",
                "result": {
                    "media_command": {
                        "command_id": "cmd_person",
                        "mode": "snapshot",
                        "params": {"quality_gate": {"mode": "best_of_burst", "sample_count": 4, "settle_ms": 850}},
                    }
                },
            }
        if path == "/api/skills/scene_describe/execute":
            return {"status": "no_evidence", "result": {"media_command": {"command_id": "cmd_scene", "mode": "snapshot"}}}
        if path == "/api/skills/target_finder/execute":
            return {
                "status": "no_evidence",
                "result": {
                    "media_command": {
                        "command_id": "cmd_live",
                        "mode": "live_video",
                        "timeout_ms": 60000,
                        "fps": 8,
                    }
                },
            }
        if path.startswith("/api/media/commands/"):
            command_id = path.split("/")[-2]
            status = payload.get("status")
            if status == "running":
                self.active_live.add(command_id)
            elif status in {"ok", "timeout", "cancelled", "error"}:
                self.active_live.discard(command_id)
            response = {"event": {"status": status}, "command": {"command_id": command_id, "session_id": payload.get("session_id")}}
            if command_id == "cmd_scene" and status == "ok":
                response["continuation"] = {"status": "needs_cloud"}
            return response
        if path.startswith("/api/adapters/yolo26/"):
            return {
                "status": "accepted",
                "source": "yolo26_rokid_stream:openvision_iphone_yolo26",
                "accepted_detection_count": 2,
                "continuation": {"status": "ok"},
            }
        if path.startswith("/api/adapters/face-identity/"):
            return {
                "status": "accepted",
                "source": "face_identity_stream:openvision_iphone_face_identity",
                "accepted_detection_count": 1,
                "continuation": {"status": "ok"},
            }
        raise AssertionError(f"unexpected POST {path}")

    def post_bytes(self, path, body, *, content_type="image/png", timeout=12.0):
        return {
            "status": "ok",
            "preview": {
                "source": "iphone_backend_readiness",
                "width": 640,
                "height": 480,
                "frame_count": 1,
                "image_url": "/api/preview/sess_1/frame.jpg",
            },
        }


class IphoneBackendReadinessScriptTest(unittest.TestCase):
    def test_synthetic_preview_png_has_valid_chunk_checksums(self):
        data = readiness_script.TINY_PNG
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        offset = 8
        seen_iend = False
        while offset < len(data):
            length = struct.unpack(">I", data[offset : offset + 4])[0]
            chunk_type = data[offset + 4 : offset + 8]
            chunk_data = data[offset + 8 : offset + 8 + length]
            expected_crc = struct.unpack(">I", data[offset + 8 + length : offset + 12 + length])[0]
            actual_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
            self.assertEqual(actual_crc, expected_crc, chunk_type)
            offset += 12 + length
            if chunk_type == b"IEND":
                seen_iend = True
                break
        self.assertTrue(seen_iend)

    def test_readiness_status_precedence(self):
        readiness = readiness_script.Readiness()

        readiness.add("a", "pass", "ok")
        readiness.add("b", "warn", "careful")
        self.assertEqual(readiness.status(), "warn")

        readiness.add("c", "blocked", "not ready")
        self.assertEqual(readiness.status(), "blocked")

        readiness.add("d", "fail", "broken")
        self.assertEqual(readiness.status(), "fail")

    def test_run_backend_readiness_exercises_simulator_contract(self):
        report = readiness_script.run_backend_readiness(FakeApi()).to_json()
        names = {check["name"]: check for check in report["checks"]}

        self.assertEqual(report["status"], "pass")
        self.assertEqual(names["backend_contract_session"]["status"], "pass")
        self.assertEqual(names["preview_upload"]["status"], "pass")
        self.assertEqual(names["skill_count_people"]["status"], "pass")
        self.assertEqual(names["backend_contract_cleanup"]["status"], "pass")
        self.assertEqual(names["person_info_snapshot_command"]["status"], "pass")
        self.assertEqual(names["person_info_snapshot_session_cleanup"]["status"], "pass")
        self.assertEqual(names["target_finder_live_command"]["status"], "pass")
        self.assertEqual(names["yolo26_stream_ingress"]["status"], "pass")
        self.assertEqual(names["face_identity_stream_ingress"]["status"], "pass")
        self.assertEqual(names["target_finder_live_cleanup"]["status"], "pass")

    def test_run_backend_readiness_exercises_cloud_visual_continuation(self):
        report = readiness_script.run_backend_readiness(FakeApi(), exercise_cloud_visual=True).to_json()
        names = {check["name"]: check for check in report["checks"]}

        self.assertEqual(report["status"], "pass")
        self.assertEqual(names["scene_describe_continuation"]["status"], "pass")
        self.assertEqual(names["scene_describe_continuation"]["data"]["continuation_status"], "needs_cloud")


if __name__ == "__main__":
    unittest.main()
