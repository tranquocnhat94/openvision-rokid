import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "score_rv101_product_signoff.py"
SPEC = importlib.util.spec_from_file_location("score_rv101_product_signoff", SCRIPT)
signoff_script = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = signoff_script
SPEC.loader.exec_module(signoff_script)


class Rv101ProductSignoffScriptTest(unittest.TestCase):
    def test_voice_contract_passes_for_conversation_server_vad_session_accept(self):
        def fake_get_json(base_url, path):
            if path.startswith("/api/events"):
                return {
                    "events": [
                        {
                            "module": "rv101_control",
                            "event_type": "session_accept",
                            "payload": {
                                "voice_mode": "conversation_realtime",
                                "turn_policy": "server_vad",
                                "voice_output": {
                                    "enabled": True,
                                    "path": "/ws/realtime/sess_1/audio",
                                    "requiresRestBootstrap": False,
                                    "requires_rest_bootstrap": False,
                                    "output_modalities": ["audio"],
                                },
                            },
                        }
                    ]
                }
            if path == "/api/realtime":
                return {"realtime": [{"session_id": "sess_1", "turn_policy": "server_vad"}]}
            raise AssertionError(f"unexpected GET {base_url} {path}")

        signoff = signoff_script.Signoff()
        with patch.object(signoff_script, "safe_get_json", side_effect=fake_get_json):
            signoff_script.check_rv101_voice_contract("http://jetson.local:8765", "sess_1", signoff)

        report = signoff.to_json()
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["checks"][0]["name"], "rv101_voice_contract")

    def test_voice_contract_fails_for_manual_turn_session_accept(self):
        def fake_get_json(base_url, path):
            if path.startswith("/api/events"):
                return {
                    "events": [
                        {
                            "module": "rv101_control",
                            "event_type": "session_accept",
                            "payload": {
                                "voice_mode": "push_to_talk_realtime",
                                "turn_policy": "manual",
                                "voice_output": {
                                    "path": "/ws/realtime/sess_1/audio",
                                    "requiresRestBootstrap": False,
                                },
                            },
                        }
                    ]
                }
            if path == "/api/realtime":
                return {"realtime": [{"session_id": "sess_1", "turn_policy": "manual"}]}
            raise AssertionError(f"unexpected GET {base_url} {path}")

        signoff = signoff_script.Signoff()
        with patch.object(signoff_script, "safe_get_json", side_effect=fake_get_json):
            signoff_script.check_rv101_voice_contract("http://jetson.local:8765", "sess_1", signoff)

        report = signoff.to_json()
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["checks"][0]["data"]["turn_policy"], "manual")

    def test_live_video_signoff_requests_1280x720_30fps_and_checks_backend_window(self):
        posted = []

        def fake_post_json(base_url, path, payload):
            posted.append((path, payload))
            return {"command": {"command_id": "media_cmd_30", "fps": payload["fps"]}}

        def fake_get_json(base_url, path):
            if path == "/api/health":
                return {"runtime_epoch": "pid:boot", "active_live_count": 0}
            if path == "/api/media":
                return {
                    "media": [
                        {
                            "session_id": "sess_1",
                            "video": {
                                "width": 1280,
                                "height": 720,
                                "estimated_fps": 29.4,
                                "metadata": {"requested_fps": 30.0, "capture_fps_max": 30.0},
                            },
                        }
                    ]
                }
            raise AssertionError(f"unexpected GET {base_url} {path}")

        final = {
            "event": {
                "status": "timeout",
                "payload": {
                    "adapter_status": "rv101_live_video_stopped",
                    "active_live_video": False,
                    "width": 1280,
                    "height": 720,
                    "sent_frames": 125,
                    "sent_fps_estimate": 29.1,
                },
            }
        }
        signoff = signoff_script.Signoff()
        with patch.object(signoff_script, "safe_post_json", side_effect=fake_post_json), patch.object(
            signoff_script, "safe_get_json", side_effect=fake_get_json
        ), patch.object(signoff_script, "wait_media_final", return_value=final):
            signoff_script.run_live_video_check("http://jetson.local:8765", "sess_1", 8.0, signoff)

        report = signoff.to_json()
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["checks"][0]["name"], "live_video_1280x720_30fps")
        self.assertEqual(posted[0][0], "/api/media/commands")
        self.assertEqual(posted[0][1]["fps"], 30.0)
        self.assertEqual(posted[0][1]["resolution"], {"width": 1280, "height": 720})

    def test_wait_for_new_session_accepts_reused_connected_session(self):
        calls = {"count": 0}

        def fake_get_json(_base_url, path):
            self.assertEqual(path, "/api/sessions")
            calls["count"] += 1
            if calls["count"] == 1:
                return {
                    "sessions": [
                        {
                            "session_id": "sess_reused",
                            "client_kind": "rv101_glasses",
                            "status": "disconnected",
                            "updated_at": "2026-05-02T01:00:00Z",
                        }
                    ]
                }
            return {
                "sessions": [
                    {
                        "session_id": "sess_reused",
                        "client_kind": "rv101_glasses",
                        "status": "connected",
                        "updated_at": "2026-05-02T01:00:10Z",
                    }
                ]
            }

        with patch.object(signoff_script, "safe_get_json", side_effect=fake_get_json):
            before = signoff_script.rv101_session_state_by_id("http://jetson.local:8765")
            session_id = signoff_script.wait_for_new_session(
                "http://jetson.local:8765",
                set(before),
                0.2,
                before_state=before,
            )

        self.assertEqual(session_id, "sess_reused")

    def test_power_network_locks_ignore_global_wifilock_text_without_held_package_lock(self):
        wifi = """
        WifiLock statistics:
          Locks acquired: 4
        Locks held:
          []
        """
        power = """
        Wake Locks: size=0
        Suspend Blockers:
        """

        self.assertFalse(signoff_script.package_has_held_wifi_lock(wifi, signoff_script.PACKAGE))
        self.assertFalse(signoff_script.package_has_held_wake_lock(power, signoff_script.PACKAGE))

    def test_power_network_locks_detect_actual_held_package_locks(self):
        wifi = f"""
        Locks held:
          WifiLock{{tag=openvision package={signoff_script.PACKAGE}}}
        Locks acquired:
        """
        power = f"""
        Wake Locks: size=1
          PARTIAL_WAKE_LOCK              '{signoff_script.PACKAGE}:voice'
        Suspend Blockers:
        """

        self.assertTrue(signoff_script.package_has_held_wifi_lock(wifi, signoff_script.PACKAGE))
        self.assertTrue(signoff_script.package_has_held_wake_lock(power, signoff_script.PACKAGE))


if __name__ == "__main__":
    unittest.main()
