import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.live_video_scorecard import build_live_video_no_restart_scorecard


def _health(epoch: str = "pid1:start1", *, active_live_count: int = 0) -> dict:
    return {
        "ok": True,
        "runtime_epoch": epoch,
        "process_id": int(epoch.split(":", 1)[0].removeprefix("pid") or 1),
        "runtime_started_at": epoch.split(":", 1)[1],
        "runtime_boot_id": "boot-1",
        "active_live_count": active_live_count,
    }


class LiveVideoScorecardTest(unittest.TestCase):
    def test_passes_when_runtime_epoch_is_stable_and_video_frames_arrived(self):
        scorecard = build_live_video_no_restart_scorecard(
            before_health=_health(),
            after_health=_health(),
            media=[
                {
                    "session_id": "sess_1",
                    "video": {"frame_count": 24, "codec": "video/avc", "transport": "rv101_tcp"},
                },
            ],
            media_commands={
                "commands": [
                    {
                        "command": {"command_id": "media_cmd_1"},
                        "event": {"status": "timeout", "payload": {"client_reported": True}},
                    },
                ],
            },
            session_id="sess_1",
            command_id="media_cmd_1",
            min_video_frames=1,
        )

        self.assertEqual(scorecard["status"], "pass")
        self.assertEqual(scorecard["gates"]["runtime_no_restart"]["status"], "pass")
        self.assertEqual(scorecard["gates"]["live_command_successful_final"]["status"], "pass")
        self.assertEqual(scorecard["gates"]["video_frames_received"]["status"], "pass")

    def test_fails_when_runtime_epoch_changes(self):
        scorecard = build_live_video_no_restart_scorecard(
            before_health=_health("pid1:start1"),
            after_health=_health("pid2:start2"),
        )

        self.assertEqual(scorecard["status"], "fail")
        self.assertEqual(scorecard["gates"]["runtime_no_restart"]["status"], "fail")

    def test_warns_when_client_final_event_is_missing_but_required_gates_pass(self):
        scorecard = build_live_video_no_restart_scorecard(
            before_health=_health(),
            after_health=_health(),
            media_commands={
                "commands": [
                    {
                        "command": {"command_id": "media_cmd_1"},
                        "event": {"status": "timeout", "payload": {"action": "auto_stop"}},
                    },
                ],
            },
            command_id="media_cmd_1",
        )

        self.assertEqual(scorecard["status"], "warn")
        self.assertEqual(scorecard["gates"]["client_stop_reported"]["status"], "warn")

    def test_warns_when_actual_fps_exceeds_live_budget(self):
        scorecard = build_live_video_no_restart_scorecard(
            before_health=_health(),
            after_health=_health(),
            media=[
                {
                    "session_id": "sess_1",
                    "video": {
                        "frame_count": 60,
                        "codec": "video/avc",
                        "transport": "rv101_tcp",
                        "estimated_fps": 16.0,
                        "metadata": {
                            "sent_fps_estimate": 22.0,
                            "capture_fps_max": 15.0,
                            "dropped_frames": 2,
                            "camera_id": "0",
                        },
                    },
                },
            ],
            media_commands={
                "commands": [
                    {
                        "command": {"command_id": "media_cmd_1", "fps": 15},
                        "event": {"status": "timeout", "payload": {"client_reported": True}},
                    },
                ],
            },
            session_id="sess_1",
            command_id="media_cmd_1",
        )

        self.assertEqual(scorecard["status"], "warn")
        self.assertEqual(scorecard["gates"]["live_fps_budget"]["status"], "warn")
        self.assertEqual(scorecard["gates"]["live_fps_budget"]["observed"]["actual_fps"], 22.0)
        self.assertEqual(scorecard["gates"]["live_fps_budget"]["observed"]["budget_fps"], 15.0)
        self.assertEqual(scorecard["metrics"]["max_video_actual_fps"], 22.0)
        self.assertEqual(scorecard["metrics"]["max_video_budget_fps"], 15.0)

    def test_fails_when_live_command_remains_active(self):
        scorecard = build_live_video_no_restart_scorecard(
            before_health=_health(),
            after_health=_health(active_live_count=1),
        )

        self.assertEqual(scorecard["status"], "fail")
        self.assertEqual(scorecard["gates"]["no_active_live_left"]["status"], "fail")

    def test_fails_when_client_reports_live_video_error(self):
        scorecard = build_live_video_no_restart_scorecard(
            before_health=_health(),
            after_health=_health(),
            media_commands={
                "commands": [
                    {
                        "command": {"command_id": "media_cmd_1"},
                        "event": {
                            "status": "error",
                            "payload": {"client_reported": True, "error": "live_video_encode_error"},
                        },
                    },
                ],
            },
            command_id="media_cmd_1",
        )

        self.assertEqual(scorecard["status"], "fail")
        self.assertEqual(scorecard["gates"]["live_command_final"]["status"], "pass")
        self.assertEqual(scorecard["gates"]["live_command_successful_final"]["status"], "fail")


if __name__ == "__main__":
    unittest.main()
