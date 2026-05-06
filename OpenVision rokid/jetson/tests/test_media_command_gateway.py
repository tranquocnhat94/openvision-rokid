import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.event_store import InMemoryEventStore
from openvision_jetson.media_command_gateway import MediaCommandGateway


class MediaCommandGatewayTest(unittest.TestCase):
    def test_snapshot_queues_for_fresh_capture_even_when_preview_exists(self):
        events = InMemoryEventStore()
        gateway = MediaCommandGateway(
            events=events,
            session_validator=lambda session_id: session_id == "sess_test",
            preview_status_provider=lambda session_id: {
                "session_id": session_id,
                "source": "unit",
                "width": 640,
                "height": 360,
                "frame_count": 3,
                "image_url": f"/api/preview/{session_id}/frame.jpg",
            },
        )

        result = gateway.request_command(
            mode="snapshot",
            session_id="sess_test",
            skill_id="scene_describe",
            reason="single visual question",
        )

        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["command"]["schema_version"], "openvision.media_command.v1")
        self.assertEqual(result["command"]["timeout_ms"], 3000)
        self.assertIsNone(result["command"]["fps"])
        self.assertEqual(result["command"]["resolution"], {"width": 1280, "height": 720})
        self.assertEqual(result["event"]["schema_version"], "openvision.media_event.v1")
        self.assertEqual(result["event"]["payload"]["adapter_status"], "awaiting_media_client")
        self.assertEqual(result["event"]["payload"]["latest_preview"]["image_url"], "/api/preview/sess_test/frame.jpg")
        trace = events.list(session_id="sess_test")
        self.assertEqual(trace[-1]["module"], "media_command")
        self.assertEqual(trace[-1]["event_type"], "command_completed")

    def test_snapshot_quality_gate_gets_longer_budget(self):
        gateway = MediaCommandGateway(
            events=InMemoryEventStore(),
            session_validator=lambda session_id: session_id == "sess_test",
        )

        result = gateway.request_command(
            mode="snapshot",
            session_id="sess_test",
            skill_id="person_info",
            reason="identity snapshot mini-burst",
            params={
                "quality_gate": {
                    "mode": "best_of_burst",
                    "sample_count": 4,
                    "min_new_frames": 4,
                    "settle_ms": 850,
                }
            },
        )

        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["command"]["timeout_ms"], 5000)

    def test_snapshot_uses_latest_preview_when_live_video_is_active(self):
        gateway = MediaCommandGateway(
            events=InMemoryEventStore(),
            session_validator=lambda session_id: session_id == "sess_test",
            preview_status_provider=lambda session_id: {
                "session_id": session_id,
                "source": "unit",
                "width": 640,
                "height": 360,
                "frame_count": 3,
                "image_url": f"/api/preview/{session_id}/frame.jpg",
            },
        )
        live = gateway.request_command(
            mode="live_video",
            session_id="sess_test",
            skill_id="reality_radar",
            reason="active target tracking",
            timeout_ms=15000,
            fps=10,
            resolution={"width": 640, "height": 360},
        )

        result = gateway.request_command(
            mode="snapshot",
            session_id="sess_test",
            skill_id="scene_describe",
            reason="single visual question during live mode",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["event"]["payload"]["adapter_status"], "using_active_live_preview")
        self.assertEqual(result["event"]["payload"]["active_live_command_id"], live["command"]["command_id"])
        self.assertEqual(result["event"]["payload"]["preview"]["image_url"], "/api/preview/sess_test/frame.jpg")

    def test_snapshot_queues_when_no_preview_is_available(self):
        gateway = MediaCommandGateway(
            events=InMemoryEventStore(),
            session_validator=lambda session_id: session_id == "sess_test",
            preview_status_provider=lambda session_id: None,
        )

        result = gateway.request_command(
            mode="snapshot",
            session_id="sess_test",
            skill_id="text_reader",
            reason="need current image",
        )

        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["event"]["payload"]["adapter_status"], "awaiting_media_client")

    def test_client_event_completes_queued_snapshot(self):
        events = InMemoryEventStore()
        gateway = MediaCommandGateway(
            events=events,
            session_validator=lambda session_id: session_id == "sess_test",
            preview_status_provider=lambda session_id: None,
        )
        queued = gateway.request_command(
            mode="snapshot",
            session_id="sess_test",
            skill_id="scene_describe",
            reason="single visual question",
        )

        completed = gateway.client_event(
            command_id=queued["command"]["command_id"],
            session_id="sess_test",
            status="ok",
            payload={
                "adapter_status": "simulator_snapshot_ready",
                "preview": {"image_url": "/api/preview/sess_test/frame.jpg"},
            },
        )

        self.assertEqual(completed["status"], "ok")
        self.assertEqual(completed["event"]["payload"]["adapter_status"], "simulator_snapshot_ready")
        self.assertTrue(completed["event"]["payload"]["client_reported"])
        self.assertEqual(
            gateway.statuses()[0]["event"]["payload"]["preview"]["image_url"],
            "/api/preview/sess_test/frame.jpg",
        )
        trace = events.list(session_id="sess_test")
        self.assertEqual(trace[-1]["module"], "media_command")
        self.assertEqual(trace[-1]["event_type"], "command_completed")

    def test_client_event_rejects_unknown_command(self):
        events = InMemoryEventStore()
        gateway = MediaCommandGateway(
            events=events,
            session_validator=lambda session_id: session_id == "sess_test",
        )

        result = gateway.client_event(
            command_id="media_cmd_missing",
            session_id="sess_test",
            status="ok",
            payload={},
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "unknown_media_command")
        self.assertEqual(events.list(session_id="sess_test")[-1]["event_type"], "command_failed")

    def test_burst_clip_clamps_requested_budget(self):
        gateway = MediaCommandGateway(
            events=InMemoryEventStore(),
            session_validator=lambda session_id: session_id == "sess_test",
        )

        result = gateway.request_command(
            mode="burst_clip",
            session_id="sess_test",
            skill_id="motion_check",
            reason="short temporal evidence",
            timeout_ms=20000,
            fps=60,
            resolution={"width": 1920, "height": 1080},
        )

        self.assertEqual(result["status"], "running")
        self.assertEqual(result["command"]["timeout_ms"], 5000)
        self.assertEqual(result["command"]["fps"], 10.0)
        self.assertEqual(result["command"]["resolution"], {"width": 1280, "height": 720})

    def test_live_video_allows_rv101_30fps_budget(self):
        gateway = MediaCommandGateway(
            events=InMemoryEventStore(),
            session_validator=lambda session_id: session_id == "sess_test",
        )

        result = gateway.request_command(
            mode="live_video",
            session_id="sess_test",
            skill_id="target_finder",
            reason="rv101 high-fps live validation",
            timeout_ms=15000,
            fps=30,
            resolution={"width": 1280, "height": 720},
        )

        self.assertEqual(result["status"], "running")
        self.assertEqual(result["command"]["fps"], 30.0)
        self.assertEqual(result["command"]["resolution"], {"width": 1280, "height": 720})
        self.assertEqual(result["event"]["payload"]["budget"]["fps"], 30.0)

    def test_live_video_clamps_above_rv101_30fps_budget(self):
        gateway = MediaCommandGateway(
            events=InMemoryEventStore(),
            session_validator=lambda session_id: session_id == "sess_test",
        )

        result = gateway.request_command(
            mode="live_video",
            session_id="sess_test",
            skill_id="target_finder",
            reason="rv101 high-fps live validation",
            timeout_ms=15000,
            fps=60,
            resolution={"width": 1280, "height": 720},
        )

        self.assertEqual(result["status"], "running")
        self.assertEqual(result["command"]["fps"], 30.0)
        self.assertEqual(result["event"]["payload"]["budget"]["fps"], 30.0)

    def test_live_video_requires_explicit_budget_and_auto_stop(self):
        events = InMemoryEventStore()
        gateway = MediaCommandGateway(
            events=events,
            session_validator=lambda session_id: session_id == "sess_test",
        )

        missing_budget = gateway.request_command(
            mode="live_video",
            session_id="sess_test",
            skill_id="reality_radar",
            reason="active tracking",
        )
        no_auto_stop = gateway.request_command(
            mode="live_video",
            session_id="sess_test",
            skill_id="reality_radar",
            reason="active tracking",
            timeout_ms=15000,
            fps=10,
            resolution={"width": 640, "height": 360},
            auto_stop=False,
        )

        self.assertEqual(missing_budget["status"], "error")
        self.assertEqual(missing_budget["error"]["code"], "missing_media_budget")
        self.assertEqual(no_auto_stop["status"], "error")
        self.assertEqual(no_auto_stop["error"]["code"], "auto_stop_required")
        failures = [event for event in events.list(session_id="sess_test") if event["event_type"] == "command_failed"]
        self.assertEqual(len(failures), 2)

    def test_live_video_start_and_stop_tracks_active_state(self):
        gateway = MediaCommandGateway(
            events=InMemoryEventStore(),
            session_validator=lambda session_id: session_id == "sess_test",
        )

        started = gateway.request_command(
            mode="live_video",
            session_id="sess_test",
            skill_id="reality_radar",
            reason="active target tracking",
            timeout_ms=15000,
            fps=10,
            resolution={"width": 640, "height": 360},
        )
        stopped = gateway.request_command(
            mode="live_video",
            session_id="sess_test",
            reason="skill completed",
            params={"action": "stop"},
        )

        self.assertEqual(started["status"], "running")
        self.assertTrue(started["active_live_video"])
        self.assertEqual(len(gateway.active_live_statuses()), 0)
        self.assertEqual(stopped["status"], "cancelled")
        self.assertEqual(stopped["event"]["payload"]["stopped_command_id"], started["command"]["command_id"])

    def test_close_session_cancels_active_live_without_session_validator(self):
        gateway = MediaCommandGateway(
            events=InMemoryEventStore(),
            session_validator=lambda session_id: session_id == "sess_test",
        )
        started = gateway.request_command(
            mode="live_video",
            session_id="sess_test",
            skill_id="target_finder",
            reason="active target tracking",
            timeout_ms=15000,
            fps=15,
            resolution={"width": 800, "height": 600},
            params={"media_profile": "rv101_medium_yolo", "profile_authority": "jetson"},
        )

        closed = gateway.close_session("sess_test", reason="unit_test_close")
        statuses = gateway.statuses()

        self.assertEqual(started["status"], "running")
        self.assertEqual(closed["status"], "cancelled")
        self.assertEqual(closed["event"]["payload"]["action"], "session_close")
        self.assertEqual(closed["event"]["payload"]["reason"], "unit_test_close")
        self.assertEqual(closed["event"]["payload"]["budget"]["media_profile"], "rv101_medium_yolo")
        self.assertEqual(len(gateway.active_live_statuses()), 0)
        self.assertFalse(statuses[0]["active"])

    def test_live_video_auto_stop_expires_on_status_query(self):
        now = 100.0

        def clock():
            return now

        gateway = MediaCommandGateway(
            events=InMemoryEventStore(),
            session_validator=lambda session_id: session_id == "sess_test",
            clock=clock,
        )
        started = gateway.request_command(
            mode="live_video",
            session_id="sess_test",
            skill_id="reality_radar",
            reason="active target tracking",
            timeout_ms=1000,
            fps=8,
            resolution={"width": 640, "height": 360},
        )

        now = 101.1
        statuses = gateway.statuses()

        self.assertEqual(len(gateway.active_live_statuses()), 0)
        self.assertEqual(statuses[0]["command"]["command_id"], started["command"]["command_id"])
        self.assertEqual(statuses[0]["event"]["status"], "timeout")
        self.assertFalse(statuses[0]["active"])

    def test_late_client_timeout_after_auto_stop_merges_stats_into_final_event(self):
        now = 100.0

        def clock():
            return now

        events = InMemoryEventStore()
        gateway = MediaCommandGateway(
            events=events,
            session_validator=lambda session_id: session_id == "sess_test",
            clock=clock,
        )
        started = gateway.request_command(
            mode="live_video",
            session_id="sess_test",
            skill_id="target_finder",
            reason="active target tracking",
            timeout_ms=1000,
            fps=8,
            resolution={"width": 640, "height": 360},
        )

        now = 101.1
        gateway.statuses()
        duplicate = gateway.client_event(
            command_id=started["command"]["command_id"],
            session_id="sess_test",
            status="timeout",
            payload={
                "adapter_status": "rv101_live_video_stopped",
                "active_live_video": False,
                "width": 1280,
                "height": 720,
                "sent_fps_estimate": 29.2,
                "sent_frames": 120,
                "dropped_frames": 1,
            },
        )

        self.assertTrue(duplicate["merged"])
        self.assertEqual(duplicate["status"], "timeout")
        self.assertEqual(duplicate["event"]["payload"]["adapter_status"], "rv101_live_video_stopped")
        self.assertEqual(duplicate["event"]["payload"]["client_status"], "timeout")
        self.assertTrue(duplicate["event"]["payload"]["late_after_auto_stop"])
        self.assertEqual(duplicate["event"]["payload"]["sent_fps_estimate"], 29.2)
        self.assertEqual(duplicate["event"]["payload"]["sent_frames"], 120)
        completed = [event for event in events.list(session_id="sess_test") if event["event_type"] == "command_completed"]
        ignored = [event for event in events.list(session_id="sess_test") if event["event_type"] == "client_event_ignored"]
        self.assertEqual(len([event for event in completed if event["payload"]["status"] == "timeout"]), 2)
        merged_log = next(event for event in completed if event["payload"].get("sent_fps_estimate") == 29.2)
        self.assertEqual(merged_log["payload"]["sent_frames"], 120)
        self.assertEqual(merged_log["payload"]["dropped_frames"], 1)
        self.assertEqual(len(ignored), 0)

    def test_auto_stop_uses_latest_running_client_stats_when_available(self):
        now = 100.0

        def clock():
            return now

        gateway = MediaCommandGateway(
            events=InMemoryEventStore(),
            session_validator=lambda session_id: session_id == "sess_test",
            clock=clock,
        )
        started = gateway.request_command(
            mode="live_video",
            session_id="sess_test",
            skill_id="target_finder",
            reason="active target tracking",
            timeout_ms=1000,
            fps=30,
            resolution={"width": 1280, "height": 720},
        )
        gateway.client_event(
            command_id=started["command"]["command_id"],
            session_id="sess_test",
            status="running",
            payload={
                "adapter_status": "rv101_live_video_running",
                "active_live_video": True,
                "width": 1280,
                "height": 720,
                "sent_fps_estimate": 28.8,
                "sent_frames": 31,
            },
        )

        now = 101.1
        status = gateway.statuses()[0]

        self.assertEqual(status["event"]["status"], "timeout")
        self.assertEqual(status["event"]["payload"]["adapter_status"], "backend_auto_stop")
        self.assertEqual(status["event"]["payload"]["client_adapter_status"], "rv101_live_video_running")
        self.assertFalse(status["event"]["payload"]["active_live_video"])
        self.assertEqual(status["event"]["payload"]["sent_fps_estimate"], 28.8)
        self.assertEqual(status["event"]["payload"]["sent_frames"], 31)

    def test_live_video_client_event_logs_quality_warning_when_stream_is_downscaled(self):
        events = InMemoryEventStore()
        gateway = MediaCommandGateway(
            events=events,
            session_validator=lambda session_id: session_id == "sess_test",
        )
        started = gateway.request_command(
            mode="live_video",
            session_id="sess_test",
            skill_id="target_finder",
            reason="active target tracking",
            timeout_ms=15000,
            fps=8,
            resolution={"width": 1280, "height": 720},
        )

        gateway.client_event(
            command_id=started["command"]["command_id"],
            session_id="sess_test",
            status="running",
            payload={
                "adapter_status": "simulator_live_video_running",
                "active_live_video": True,
                "preview": {"source": "iphone", "width": 180, "height": 320, "frame_count": 562},
                "client_video": {
                    "requested": {"width": 1280, "height": 720, "fps": 8},
                    "preview_width": 180,
                    "preview_height": 320,
                    "video_track_count": 1,
                    "video_tracks": [
                        {
                            "ready_state": "live",
                            "enabled": True,
                            "settings": {"width": 180, "height": 320, "frameRate": 6},
                        }
                    ],
                },
            },
        )

        trace = events.list(session_id="sess_test")
        payload = next(event["payload"] for event in trace if "client_video" in event["payload"])

        self.assertEqual(payload["client_video"]["preview_width"], 180)
        self.assertEqual(payload["client_video"]["video_tracks"][0]["settings"]["width"], 180)
        self.assertEqual(payload["quality_warning"]["code"], "client_video_below_requested_budget")
        self.assertEqual(payload["quality_warning"]["requested"], {"width": 1280, "height": 720})

    def test_command_history_prunes_old_commands_without_removing_active_live(self):
        gateway = MediaCommandGateway(
            events=InMemoryEventStore(),
            session_validator=lambda session_id: session_id.startswith("sess_"),
            max_commands=25,
        )
        live = gateway.request_command(
            mode="live_video",
            session_id="sess_live",
            skill_id="target_finder",
            reason="active target tracking",
            timeout_ms=15000,
            fps=8,
            resolution={"width": 640, "height": 360},
        )

        for index in range(30):
            gateway.request_command(
                mode="snapshot",
                session_id=f"sess_{index}",
                skill_id="scene_describe",
                reason="fresh visual question",
            )

        statuses = gateway.statuses()
        live_command_id = live["command"]["command_id"]
        live_status = next(item for item in statuses if item["command"]["command_id"] == live_command_id)

        self.assertEqual(len(statuses), 25)
        self.assertTrue(live_status["active"])
        self.assertEqual(live_status["event"]["status"], "running")

    def test_unknown_session_is_rejected(self):
        gateway = MediaCommandGateway(
            events=InMemoryEventStore(),
            session_validator=lambda session_id: False,
        )

        result = gateway.request_command(
            mode="snapshot",
            session_id="sess_missing",
            skill_id="scene_describe",
            reason="single visual question",
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "unknown_session")


if __name__ == "__main__":
    unittest.main()
