import asyncio
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.audio_signal import pcm16_metrics
from openvision_jetson.control_plane import OpenVisionControlPlane


def _jpeg_bytes(width: int = 640, height: int = 480) -> bytes:
    _ = (width, height)
    return b"fake-jpeg"


class FakeSnapshotImage:
    width = 640
    height = 480

    def convert(self, mode):
        _ = mode
        return self

    def crop(self, box):
        _ = box
        return FakeSnapshotCrop()


class FakeSnapshotCrop:
    def save(self, path, **kwargs):
        _ = kwargs
        Path(path).write_bytes(b"fake-crop")


class FakePillowImageModule:
    @staticmethod
    def open(data):
        _ = data
        return FakeSnapshotImage()


class FakeQualityGateSnapshotImage(FakeSnapshotImage):
    def __init__(self, marker: bytes):
        self.marker = marker


class FakeQualityGatePillowImageModule:
    @staticmethod
    def open(data):
        return FakeQualityGateSnapshotImage(data.getvalue())


class FakeSnapshotFaceBackend:
    def status(self):
        return {"status": "ready", "backend": "fake_sface"}

    def detect_and_embed(self, image):
        _ = image
        return [
            {
                "label": "person",
                "confidence": 0.92,
                "bbox": [210, 80, 330, 300],
                "attributes": {"embedding_model": "sface", "identity_vector": [1.0, 0.0]},
            },
            {
                "label": "person",
                "confidence": 0.9,
                "bbox": [390, 90, 510, 305],
                "attributes": {"embedding_model": "sface", "identity_vector": [0.0, 1.0]},
            },
        ]


class FakeQualityGateFaceBackend:
    def __init__(self):
        self.markers: list[bytes] = []

    def status(self):
        return {"status": "ready", "backend": "fake_sface_quality_gate"}

    def detect_and_embed(self, image):
        marker = getattr(image, "marker", b"")
        self.markers.append(marker)
        if marker == b"bad-frame":
            return []
        return [
            {
                "label": "person",
                "confidence": 0.93,
                "bbox": [180, 70, 330, 300],
                "attributes": {
                    "embedding_model": "sface",
                    "identity_vector": [1.0, 0.0],
                    "face_min_side_px": 150,
                    "identity_quality": "ok",
                    "identity_quality_reasons": [],
                },
            }
        ]


class FakeRealtimeRuntime:
    def __init__(self):
        self._statuses: dict[str, dict] = {}
        self.starts: list[dict] = []
        self.stops: list[str] = []

    async def start(self, **kwargs):
        session_id = kwargs["session_id"]
        self.starts.append(kwargs)
        status = {
            "session_id": session_id,
            "status": "connected",
            "model": "gpt-realtime-1.5",
            "turn_policy": kwargs.get("turn_policy", "server_vad"),
            "output_modalities": kwargs.get("output_modalities") or ["text"],
        }
        self._statuses[session_id] = status
        return dict(status)

    async def stop(self, session_id: str):
        self.stops.append(session_id)
        status = self._statuses.setdefault(
            session_id,
            {
                "session_id": session_id,
                "model": "gpt-realtime-1.5",
                "turn_policy": "server_vad",
                "output_modalities": ["text"],
            },
        )
        status["status"] = "stopped"
        return dict(status)

    def status(self, session_id: str):
        status = self._statuses.get(session_id)
        return dict(status) if status else None

    def statuses(self):
        return [dict(status) for status in self._statuses.values()]


class ControlPlaneTest(unittest.TestCase):
    def test_health_is_redacted_and_lists_core_counts(self):
        plane = OpenVisionControlPlane()
        health = plane.health()

        self.assertTrue(health["ok"])
        self.assertEqual(health["service"], "openvision-jetson-agent")
        self.assertIsInstance(health["process_id"], int)
        self.assertIn("runtime_epoch", health)
        self.assertIn("runtime_started_at", health)
        self.assertIsInstance(health["runtime_uptime_ms"], int)
        self.assertIn("openai_key_present", health)
        self.assertGreaterEqual(health["skills"], 7)
        self.assertEqual(health["sessions"], 0)
        self.assertEqual(health["total_sessions"], 0)
        self.assertEqual(health["realtime_sessions"], 0)
        self.assertEqual(health["total_realtime_sessions"], 0)
        self.assertEqual(health["media_sessions"], 0)
        self.assertEqual(health["total_media_sessions"], 0)
        self.assertEqual(health["preview_sessions"], 0)
        self.assertEqual(health["media_commands"], 0)
        self.assertEqual(health["active_live_count"], 0)
        self.assertIn("cloud_verify_enabled", health)
        self.assertIn("cloud_verify_model", health)
        self.assertEqual(health["realtime_audio_gate_mode"], "monitor_only")
        self.assertIn("people_registry_status", health)
        self.assertIn("people_immich_configured", health)
        self.assertEqual(health["rv101_h264_preview"]["status"], "disabled")

    def test_health_reports_live_media_counts(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="iphone_simulator",
            capabilities={"video": "webrtc", "audio": "webrtc"},
        )
        plane.preview.record_frame(
            session_id=session["session_id"],
            source="unit",
            image_bytes=b"jpeg",
            width=1,
            height=1,
            frame_count=1,
        )
        plane._record_simulator_track(session["session_id"], "video")
        plane._execute_skill_for_realtime(
            "target_finder",
            {"query": "tìm người trong đám đông", "target_type": "person"},
            session["session_id"],
        )

        health = plane.health()

        self.assertEqual(health["sessions"], 1)
        self.assertEqual(health["total_sessions"], 1)
        self.assertEqual(health["media_sessions"], 1)
        self.assertEqual(health["total_media_sessions"], 1)
        self.assertEqual(health["preview_sessions"], 1)
        self.assertEqual(health["media_commands"], 1)
        self.assertEqual(health["active_live_count"], 1)

    def test_live_media_timeout_marks_video_idle_for_health(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="rv101_glasses",
            capabilities={"video": "tcp_h264"},
        )
        command = plane.request_media_command(
            mode="live_video",
            session_id=session["session_id"],
            skill_id="debug_live",
            reason="unit live timeout",
            timeout_ms=5000,
            fps=8,
            resolution={"width": 640, "height": 360},
            params={"action": "start"},
        )["command"]
        plane.media.record_video_sample(
            session_id=session["session_id"],
            transport="rv101_tcp",
            codec="video/avc",
            payload_bytes=1024,
            width=640,
            height=360,
        )

        plane.record_media_command_event(
            command_id=command["command_id"],
            session_id=session["session_id"],
            status="timeout",
            payload={"adapter_status": "rv101_live_video_stopped"},
        )

        media = plane.media.status(session["session_id"])
        health = plane.health()
        self.assertEqual(media["video"]["state"], "idle")
        self.assertEqual(health["media_sessions"], 0)
        self.assertEqual(health["total_media_sessions"], 1)

    def test_old_live_timeout_does_not_stop_restarted_live_stream(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="rv101_glasses",
            capabilities={"video": "tcp_h264"},
        )
        first = plane.request_media_command(
            mode="live_video",
            session_id=session["session_id"],
            skill_id="target_finder",
            reason="first live",
            timeout_ms=5000,
            fps=15,
            resolution={"width": 800, "height": 600},
            params={"action": "start"},
        )["command"]
        plane.media.record_video_sample(
            session_id=session["session_id"],
            transport="rv101_tcp",
            codec="video/avc",
            payload_bytes=1024,
            width=800,
            height=600,
        )
        plane.record_media_command_event(
            command_id=first["command_id"],
            session_id=session["session_id"],
            status="timeout",
            payload={"adapter_status": "backend_auto_stop"},
        )

        second = plane.request_media_command(
            mode="live_video",
            session_id=session["session_id"],
            skill_id="target_finder",
            reason="second live",
            timeout_ms=5000,
            fps=15,
            resolution={"width": 800, "height": 600},
            params={"action": "start"},
        )["command"]
        self.assertNotEqual(first["command_id"], second["command_id"])
        plane.media.record_video_sample(
            session_id=session["session_id"],
            transport="rv101_tcp",
            codec="video/avc",
            payload_bytes=1024,
            width=800,
            height=600,
        )

        media = plane.media.status(session["session_id"])
        health = plane.health()
        stopped = [
            event
            for event in plane.list_events(session_id=session["session_id"], limit=500)
            if event["module"] == "media" and event["event_type"] == "video_stream_stopped"
        ]

        self.assertEqual(media["video"]["state"], "receiving")
        self.assertEqual(health["active_live_count"], 1)
        self.assertEqual(
            len([event for event in stopped if event["payload"].get("reason") == "live_video_timeout"]),
            1,
        )

    def test_cloud_preview_refs_resolve_to_data_urls_for_verifier(self):
        plane = OpenVisionControlPlane()
        plane.preview.record_frame(
            session_id="sess_test",
            source="unit",
            image_bytes=b"jpeg",
            width=1,
            height=1,
            frame_count=1,
        )

        image_url = plane._resolve_cloud_image_ref(
            "/api/preview/sess_test/frame.jpg",
            {"session_id": "sess_test"},
        )

        self.assertTrue(image_url.startswith("data:image/jpeg;base64,"))

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

    def test_rv101_audio_stats_preserve_capture_diagnostics(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="rv101_glasses",
            capabilities={"video": "tcp_h264", "audio": "tcp_pcm"},
        )

        asyncio.run(
            plane.handle_rv101_control_message(
                session_id=session["session_id"],
                payload={
                    "type": "audio_stats",
                    "sentChunks": 304,
                    "sentBytes": 583680,
                    "avgAbs": 145,
                    "peakAbs": 465,
                    "nonSilentRatio": 0.515625,
                    "captureSampleRateHz": 16000,
                    "wireSampleRateHz": 24000,
                    "audioSource": "MIC",
                },
            )
        )

        events = plane.list_events(session_id=session["session_id"])
        audio_stats = [event for event in events if event["event_type"] == "audio_stats"][-1]

        self.assertEqual(audio_stats["payload"]["sentChunks"], 304)
        self.assertEqual(audio_stats["payload"]["peakAbs"], 465)
        self.assertEqual(audio_stats["payload"]["captureSampleRateHz"], 16000)
        self.assertEqual(audio_stats["payload"]["wireSampleRateHz"], 24000)
        self.assertEqual(audio_stats["payload"]["audioSource"], "MIC")

    def test_rv101_control_session_defaults_to_conversation_realtime_server_vad(self):
        plane = OpenVisionControlPlane()
        starts = []

        async def start(**kwargs):
            starts.append(kwargs)
            return {"status": "connected"}

        plane.realtime.start = start

        result = asyncio.run(plane.create_rv101_control_session({"deviceId": "rv101_test"}))

        self.assertEqual(starts[0]["turn_policy"], "server_vad")
        self.assertEqual(starts[0]["output_modalities"], ["text"])
        self.assertEqual(result["accept"]["voiceMode"], "conversation_realtime")
        self.assertEqual(result["accept"]["voice_mode"], "conversation_realtime")
        self.assertEqual(result["accept"]["turnPolicy"], "server_vad")
        self.assertEqual(result["accept"]["turn_policy"], "server_vad")
        self.assertFalse(result["accept"]["voiceOutput"]["enabled"])
        self.assertFalse(result["accept"]["voiceOutput"]["requiresRestBootstrap"])
        self.assertEqual(result["accept"]["audio"]["transport"], "tcp_pcm")

    def test_rv101_control_session_accepts_voice_output_contract(self):
        plane = OpenVisionControlPlane()
        starts = []

        async def start(**kwargs):
            starts.append(kwargs)
            return {"status": "connected"}

        plane.realtime.start = start

        result = asyncio.run(plane.create_rv101_control_session({"deviceId": "rv101_test", "voiceOutput": True}))

        self.assertEqual(starts[0]["turn_policy"], "server_vad")
        self.assertEqual(starts[0]["output_modalities"], ["audio"])
        self.assertTrue(starts[0]["voice_output"])
        self.assertEqual(result["accept"]["voiceMode"], "conversation_realtime")
        self.assertEqual(result["accept"]["turnPolicy"], "server_vad")
        voice_output = result["accept"]["voiceOutput"]
        self.assertEqual(result["accept"]["voice_output"], voice_output)
        self.assertTrue(voice_output["enabled"])
        self.assertEqual(voice_output["transport"], "ws_pcm")
        self.assertEqual(voice_output["format"], "pcm_s16le")
        self.assertEqual(voice_output["sampleRateHz"], 24000)
        self.assertEqual(voice_output["sample_rate_hz"], 24000)
        self.assertEqual(voice_output["channels"], 1)
        self.assertEqual(voice_output["outputModalities"], ["audio"])
        self.assertFalse(voice_output["requiresRestBootstrap"])
        self.assertFalse(voice_output["requires_rest_bootstrap"])
        self.assertEqual(voice_output["path"], f"/ws/realtime/{result['session']['session_id']}/audio")

    def test_rv101_control_session_allows_push_to_talk_manual_fallback(self):
        plane = OpenVisionControlPlane()
        starts = []

        async def start(**kwargs):
            starts.append(kwargs)
            return {"status": "connected"}

        plane.realtime.start = start

        result = asyncio.run(
            plane.create_rv101_control_session(
                {"deviceId": "rv101_test", "voiceOutput": True, "voiceMode": "push_to_talk_realtime"}
            )
        )

        self.assertEqual(starts[0]["turn_policy"], "manual")
        self.assertEqual(starts[0]["output_modalities"], ["audio"])
        self.assertEqual(result["accept"]["voiceMode"], "push_to_talk_realtime")
        self.assertEqual(result["accept"]["voice_mode"], "push_to_talk_realtime")
        self.assertEqual(result["accept"]["turnPolicy"], "manual")
        self.assertEqual(result["accept"]["turn_policy"], "manual")

    def test_rv101_reconnect_supersedes_prior_same_device_session(self):
        plane = OpenVisionControlPlane()
        starts = []
        stops = []

        async def start(**kwargs):
            starts.append(kwargs)
            return {"status": "connected"}

        async def stop(session_id: str):
            stops.append(session_id)
            return {"session_id": session_id, "status": "stopped"}

        plane.realtime.start = start
        plane.realtime.stop = stop

        first = asyncio.run(plane.create_rv101_control_session({"deviceId": "rv101_same"}))
        second = asyncio.run(plane.create_rv101_control_session({"deviceId": "rv101_same"}))

        first_session_id = first["session"]["session_id"]
        second_session_id = second["session"]["session_id"]
        sessions = {session["session_id"]: session for session in plane.list_sessions()}
        self.assertEqual(sessions[first_session_id]["status"], "superseded")
        self.assertEqual(sessions[second_session_id]["status"], "connected")
        self.assertEqual(stops, [first_session_id])
        self.assertEqual(plane.health()["sessions"], 1)
        events = plane.list_events(session_id=first_session_id)
        self.assertTrue(any(event["module"] == "sessions" and event["event_type"] == "superseded" for event in events))

    def test_rv101_stale_session_messages_and_audio_are_ignored_after_reconnect(self):
        plane = OpenVisionControlPlane()
        plane.realtime.start = AsyncMock(return_value={"status": "connected"})
        plane.realtime.stop = AsyncMock(return_value={"status": "stopped"})

        first = asyncio.run(plane.create_rv101_control_session({"deviceId": "rv101_same"}))
        asyncio.run(plane.create_rv101_control_session({"deviceId": "rv101_same"}))
        first_session_id = first["session"]["session_id"]

        messages = asyncio.run(
            plane.handle_rv101_control_message(
                session_id=first_session_id,
                payload={"type": "glasses_health", "sessionId": first_session_id},
            )
        )
        asyncio.run(plane._forward_rv101_audio_to_realtime(first_session_id, b"\x00\x00" * 20))

        self.assertEqual(messages, [])
        events = plane.list_events(session_id=first_session_id)
        self.assertTrue(any(event["event_type"] == "stale_session_message_ignored" for event in events))
        self.assertTrue(any(event["event_type"] == "stale_session_audio_ignored" for event in events))

    def test_rv101_disconnect_parks_realtime_for_reconnect_grace(self):
        plane = OpenVisionControlPlane()
        fake_realtime = FakeRealtimeRuntime()
        plane.realtime = fake_realtime

        session = asyncio.run(plane.create_rv101_control_session({"deviceId": "rv101_same"}))
        session_id = session["session"]["session_id"]

        async def close_and_check():
            await plane.close_rv101_control_session(session_id)
            sessions = {item["session_id"]: item for item in plane.list_sessions()}
            self.assertEqual(sessions[session_id]["status"], "disconnected")
            self.assertEqual(plane.health()["sessions"], 0)
            self.assertEqual(plane.health()["rv101_realtime_parked_sessions"], 1)
            self.assertEqual(fake_realtime.stops, [])
            events = plane.list_events(session_id=session_id)
            self.assertTrue(
                any(event["module"] == "sessions" and event["event_type"] == "disconnected" for event in events)
            )
            self.assertTrue(
                any(event["module"] == "rv101_control" and event["event_type"] == "realtime_parked" for event in events)
            )
            plane._cancel_rv101_reconnect_grace(session_id)

        asyncio.run(close_and_check())

    def test_rv101_client_goodbye_closes_session_and_stops_realtime(self):
        plane = OpenVisionControlPlane()
        fake_realtime = FakeRealtimeRuntime()
        plane.realtime = fake_realtime

        async def run_goodbye():
            session = await plane.create_rv101_control_session({"deviceId": "rv101_same"})
            session_id = session["session"]["session_id"]
            plane.media.record_audio_sample(
                session_id=session_id,
                transport="rv101_tcp",
                sample_rate=24000,
                channels=1,
                payload_bytes=1920,
                strong=False,
                source="rv101",
            )

            messages = await plane.handle_rv101_control_message(
                session_id=session_id,
                payload={"type": "client_goodbye", "reason": "app_exit"},
            )

            self.assertEqual(messages, [{"type": "session_closed", "sessionId": session_id, "reason": "app_exit"}])
            self.assertEqual(plane.list_sessions()[0]["status"], "closed")
            self.assertEqual(plane.health()["sessions"], 0)
            self.assertEqual(plane.health()["rv101_realtime_parked_sessions"], 0)
            self.assertEqual(fake_realtime.stops, [session_id])
            self.assertEqual(plane.list_media(), [])
            events = plane.list_events(session_id=session_id)
            self.assertTrue(
                any(event["module"] == "rv101_control" and event["event_type"] == "app_session_closed" for event in events)
            )

        asyncio.run(run_goodbye())

    def test_rv101_reconnect_reuses_parked_realtime_session(self):
        plane = OpenVisionControlPlane()
        fake_realtime = FakeRealtimeRuntime()
        plane.realtime = fake_realtime

        async def run_reconnect():
            first = await plane.create_rv101_control_session({"deviceId": "rv101_same"})
            session_id = first["session"]["session_id"]
            await plane.close_rv101_control_session(session_id)
            second = await plane.create_rv101_control_session({"deviceId": "rv101_same"})
            self.assertEqual(second["session"]["session_id"], session_id)
            self.assertEqual(second["accept"]["sessionId"], session_id)
            self.assertEqual(len(fake_realtime.starts), 1)
            self.assertEqual(fake_realtime.stops, [])
            self.assertEqual(plane.health()["sessions"], 1)
            self.assertEqual(plane.health()["total_sessions"], 1)
            self.assertEqual(plane.health()["rv101_realtime_parked_sessions"], 0)
            events = plane.list_events(session_id=session_id)
            self.assertTrue(any(event["module"] == "sessions" and event["event_type"] == "resumed" for event in events))
            self.assertTrue(
                any(event["module"] == "rv101_control" and event["event_type"] == "session_resumed" for event in events)
            )

        asyncio.run(run_reconnect())

    def test_rv101_reconnect_grace_expiry_stops_parked_realtime(self):
        plane = OpenVisionControlPlane()
        fake_realtime = FakeRealtimeRuntime()
        plane.realtime = fake_realtime

        async def run_expiry():
            with patch.dict(os.environ, {"OPENVISION_RV101_REALTIME_RECONNECT_GRACE_S": "0.01"}, clear=False):
                session = await plane.create_rv101_control_session({"deviceId": "rv101_same"})
                session_id = session["session"]["session_id"]
                await plane.close_rv101_control_session(session_id)
                await asyncio.sleep(0.05)
            self.assertEqual(fake_realtime.stops, [session_id])
            self.assertEqual(plane.health()["rv101_realtime_parked_sessions"], 0)
            events = plane.list_events(session_id=session_id)
            self.assertTrue(
                any(
                    event["module"] == "rv101_control" and event["event_type"] == "reconnect_grace_expired"
                    for event in events
                )
            )

        asyncio.run(run_expiry())

    def test_rv101_disconnect_removes_preview_and_closes_media(self):
        plane = OpenVisionControlPlane()
        fake_realtime = FakeRealtimeRuntime()
        plane.realtime = fake_realtime

        async def run_close():
            session = await plane.create_rv101_control_session({"deviceId": "rv101_same"})
            session_id = session["session"]["session_id"]
            plane.preview.record_frame(
                session_id=session_id,
                source="rv101_live_h264",
                image_bytes=b"jpeg",
                width=640,
                height=360,
                frame_count=1,
            )
            plane.media.record_video_sample(
                session_id=session_id,
                transport="rv101_tcp",
                codec="video/avc",
                payload_bytes=100,
                width=1280,
                height=720,
            )
            plane.media.record_audio_sample(
                session_id=session_id,
                transport="rv101_tcp",
                sample_rate=24000,
                channels=1,
                payload_bytes=1920,
                strong=True,
            )

            await plane.close_rv101_control_session(session_id)

            media = plane.media.status(session_id)
            self.assertIsNone(plane.preview_status(session_id))
            self.assertEqual(media["video"]["state"], "closed")
            self.assertEqual(media["audio"]["state"], "closed")
            events = plane.list_events(session_id=session_id)
            self.assertTrue(
                any(event["module"] == "preview" and event["event_type"] == "session_removed" for event in events)
            )
            plane._cancel_rv101_reconnect_grace(session_id)

        asyncio.run(run_close())

    def test_rv101_video_ingest_requires_active_live_video_command(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="rv101_glasses",
            capabilities={"device_id": "rv101_same", "video": "h264", "audio": "pcm_s16le"},
        )
        session_id = session["session_id"]

        self.assertFalse(plane._rv101_video_ingest_allowed(session_id, {}, 2))
        command = plane.request_media_command(
            mode="live_video",
            session_id=session_id,
            skill_id="target_finder",
            reason="rv101 live validation",
            timeout_ms=15000,
            fps=30,
            resolution={"width": 1280, "height": 720},
            params={"action": "start"},
        )["command"]
        self.assertTrue(plane._rv101_video_ingest_allowed(session_id, {}, 2))

        plane.record_media_command_event(
            command_id=command["command_id"],
            session_id=session_id,
            status="timeout",
            payload={"adapter_status": "rv101_live_video_stopped"},
        )

        self.assertFalse(plane._rv101_video_ingest_allowed(session_id, {}, 2))

    def test_realtime_text_for_inactive_session_does_not_render_to_hud(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(client_kind="rv101_glasses", capabilities={"device_id": "rv101_same"})
        session_id = session["session_id"]
        plane.sessions.mark_inactive(session_id, status="disconnected")

        plane._update_hud_from_realtime_text(session_id, "late answer")

        self.assertIsNone(plane.latest_hud(session_id))
        events = plane.list_events(session_id=session_id)
        self.assertTrue(any(event["module"] == "realtime" and event["event_type"] == "output_text_ignored" for event in events))

    def test_session_active_count_treats_terminal_statuses_as_inactive(self):
        plane = OpenVisionControlPlane()
        statuses = ["expired", "disconnected", "superseded", "closed", "stopped", "replaced"]

        for status in statuses:
            session = plane.create_session(client_kind="rv101_glasses", capabilities={"device_id": status})
            plane.sessions.touch(session["session_id"], status=status)

        self.assertEqual(plane.health()["sessions"], 0)
        self.assertEqual(plane.health()["total_sessions"], len(statuses))

    def test_rv101_ptt_up_waits_for_audio_stream_close_before_commit(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="rv101_glasses",
            capabilities={"video": "tcp_h264", "audio": "tcp_pcm"},
        )
        session_id = session["session_id"]
        calls = []

        async def clear_audio(*, session_id: str):
            calls.append(("clear", session_id, time.monotonic()))
            return {"status": "cleared"}

        async def commit_audio(*, session_id: str):
            calls.append(("commit", session_id, time.monotonic()))
            return {"status": "committed"}

        plane.realtime.clear_audio = clear_audio
        plane.realtime.commit_audio = commit_audio

        async def scenario():
            await plane.handle_rv101_control_message(session_id=session_id, payload={"type": "ptt_down"})
            ptt_started_s = plane._rv101_ptt_started_s[session_id]

            async def close_audio_stream():
                await asyncio.sleep(0.05)
                plane._rv101_audio_last_chunk_s[session_id] = time.monotonic()
                plane._close_rv101_audio(session_id)

            close_task = asyncio.create_task(close_audio_stream())
            await plane.handle_rv101_control_message(session_id=session_id, payload={"type": "ptt_up"})
            await close_task
            return ptt_started_s

        ptt_started_s = asyncio.run(scenario())
        commit_call = [call for call in calls if call[0] == "commit"][-1]

        self.assertGreaterEqual(commit_call[2], plane._rv101_audio_closed_s[session_id])
        self.assertGreaterEqual(plane._rv101_audio_closed_s[session_id], ptt_started_s)

    def test_rv101_ptt_events_do_not_manual_commit_server_vad_sessions(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="rv101_glasses",
            capabilities={"video": "tcp_h264", "audio": "tcp_pcm"},
        )
        session_id = session["session_id"]
        calls = []

        plane.realtime.status = lambda candidate: {"turn_policy": "server_vad", "status": "connected"}

        async def clear_audio(*, session_id: str):
            calls.append(("clear", session_id))
            return {"status": "cleared"}

        async def commit_audio(*, session_id: str):
            calls.append(("commit", session_id))
            return {"status": "committed"}

        plane.realtime.clear_audio = clear_audio
        plane.realtime.commit_audio = commit_audio

        async def scenario():
            await plane.handle_rv101_control_message(session_id=session_id, payload={"type": "ptt_down"})
            await plane.handle_rv101_control_message(session_id=session_id, payload={"type": "ptt_up"})

        asyncio.run(scenario())

        self.assertEqual(calls, [])
        event_types = [event["event_type"] for event in plane.list_events(session_id=session_id)]
        self.assertIn("ptt_down_observed_server_vad", event_types)
        self.assertIn("ptt_up_observed_server_vad", event_types)

    def test_rv101_glasses_health_is_throttled_until_state_changes(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="rv101_glasses",
            capabilities={"video": "tcp_h264", "audio": "tcp_pcm"},
        )
        payload = {
            "type": "glasses_health",
            "sessionId": session["session_id"],
            "app_state": "IDLE_READY",
            "battery_pct": 100,
            "thermal_state": "unknown",
            "active_media": "none",
        }

        with patch("openvision_jetson.control_plane.time.monotonic", side_effect=[1.0, 2.0, 3.0, 35.0]):
            plane._record_rv101_health_if_needed(session_id=session["session_id"], payload=payload)
            plane._record_rv101_health_if_needed(session_id=session["session_id"], payload=payload)
            changed = {**payload, "active_media": "snapshot"}
            plane._record_rv101_health_if_needed(session_id=session["session_id"], payload=changed)
            plane._record_rv101_health_if_needed(session_id=session["session_id"], payload=changed)

        health_events = [
            event
            for event in plane.list_events(session_id=session["session_id"])
            if event["module"] == "rv101_control" and event["event_type"] == "glasses_health"
        ]

        self.assertEqual(len(health_events), 3)
        self.assertEqual(health_events[0]["payload"]["log_reason"], "changed")
        self.assertEqual(health_events[1]["payload"]["active_media"], "snapshot")
        self.assertEqual(health_events[2]["payload"]["log_reason"], "periodic_summary")

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
        session = plane.create_session(client_kind="iphone_simulator", capabilities={"video": "webrtc"})
        session_id = session["session_id"]
        plane.update_perception(
            session_id=session_id,
            source="unit",
            detections=[
                {"track_id": "p1", "label": "person", "confidence": 0.9, "bbox": [10, 10, 80, 180]},
            ],
        )
        skill = plane.execute_skill(
            "search_targets",
            {"query": "người áo xanh"},
            session_id=session_id,
        )

        self.assertEqual(skill["status"], "needs_cloud")
        self.assertEqual(len(plane.latest_hud(session_id)["thumbnails"]), 1)

        plane._update_hud_from_realtime_text(session_id, "Có 1 ứng viên, cần xác minh màu áo.")
        latest = plane.latest_hud(session_id)

        self.assertEqual(latest["answer_strip"], "Có 1 ứng viên, cần xác minh màu áo.")
        self.assertEqual(len(latest["thumbnails"]), 1)
        self.assertIn("realtime", latest["edge_chips"])

    def test_camera_skill_requests_media_command_before_no_evidence(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="iphone_simulator",
            capabilities={"video": "webrtc", "audio": "webrtc"},
        )

        result = plane.execute_skill(
            "query_scene",
            {"question": "đang có gì trước mặt"},
            session_id=session["session_id"],
        )
        second = plane.execute_skill(
            "query_scene",
            {"question": "đang có gì trước mặt"},
            session_id=session["session_id"],
        )

        self.assertEqual(result["status"], "no_evidence")
        self.assertEqual(result["result"]["user_message"], "Đang bật camera để lấy ảnh.")
        self.assertEqual(result["result"]["media_command"]["mode"], "snapshot")
        self.assertEqual(result["result"]["media_command"]["skill_id"], "query_scene")
        self.assertEqual(result["result"]["media_event"]["status"], "queued")
        self.assertEqual(second["result"]["media_command"]["command_id"], result["result"]["media_command"]["command_id"])
        self.assertEqual(len(plane.list_media_commands()["commands"]), 1)
        self.assertEqual(plane.latest_hud(session["session_id"])["answer_strip"], "Đang bật camera")
        events = plane.list_events(session_id=session["session_id"])
        self.assertTrue(any(event["module"] == "media_command" for event in events))
        self.assertTrue(any(event["module"] == "skills" and event["event_type"] == "media_requested" for event in events))

    def test_realtime_query_scene_requests_fresh_media_even_when_preview_exists(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="iphone_simulator",
            capabilities={"video": "webrtc", "audio": "webrtc"},
        )
        plane.preview.record_frame(
            session_id=session["session_id"],
            source="iphone_webrtc",
            image_bytes=b"old-jpeg",
            width=508,
            height=904,
            frame_count=1,
        )

        result = plane._execute_skill_for_realtime(
            "query_scene",
            {"question": "đang có gì trước mặt tôi"},
            session["session_id"],
        )

        self.assertEqual(result["status"], "no_evidence")
        self.assertEqual(result["result"]["media_command"]["mode"], "snapshot")
        self.assertEqual(result["result"]["media_command"]["skill_id"], "query_scene")
        self.assertEqual(result["result"]["media_event"]["status"], "queued")
        self.assertEqual(len(plane.list_media_commands()["commands"]), 1)
        self.assertEqual(plane.latest_hud(session["session_id"])["answer_strip"], "Đang bật camera")

    def test_realtime_scene_describe_requests_fresh_media_even_when_preview_exists(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="iphone_simulator",
            capabilities={"video": "webrtc", "audio": "webrtc"},
        )
        plane.preview.record_frame(
            session_id=session["session_id"],
            source="iphone_webrtc",
            image_bytes=b"old-jpeg",
            width=508,
            height=904,
            frame_count=1,
        )

        result = plane._execute_skill_for_realtime(
            "scene_describe",
            {"focus": "đang có gì trước mặt tôi"},
            session["session_id"],
        )

        self.assertEqual(result["status"], "no_evidence")
        self.assertEqual(result["result"]["media_command"]["mode"], "snapshot")
        self.assertEqual(result["result"]["media_command"]["skill_id"], "scene_describe")
        self.assertEqual(result["result"]["media_event"]["status"], "queued")
        self.assertEqual(len(plane.list_media_commands()["commands"]), 1)
        self.assertEqual(plane.latest_hud(session["session_id"])["answer_strip"], "Đang bật camera")

    def test_realtime_text_reader_requests_fresh_media_even_when_preview_exists(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="iphone_simulator",
            capabilities={"video": "webrtc", "audio": "webrtc"},
        )
        plane.preview.record_frame(
            session_id=session["session_id"],
            source="iphone_webrtc",
            image_bytes=b"old-jpeg",
            width=508,
            height=904,
            frame_count=1,
        )

        result = plane._execute_skill_for_realtime(
            "text_reader",
            {"question": "biển này ghi gì"},
            session["session_id"],
        )

        self.assertEqual(result["status"], "no_evidence")
        self.assertEqual(result["result"]["media_command"]["mode"], "snapshot")
        self.assertEqual(result["result"]["media_command"]["skill_id"], "text_reader")
        self.assertEqual(result["result"]["media_event"]["status"], "queued")
        self.assertEqual(len(plane.list_media_commands()["commands"]), 1)
        self.assertEqual(plane.latest_hud(session["session_id"])["answer_strip"], "Đang bật camera")

    def test_realtime_object_counter_requests_fresh_media_even_when_preview_exists(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="iphone_simulator",
            capabilities={"video": "webrtc", "audio": "webrtc"},
        )
        plane.preview.record_frame(
            session_id=session["session_id"],
            source="iphone_webrtc",
            image_bytes=b"old-jpeg",
            width=508,
            height=904,
            frame_count=1,
        )

        result = plane._execute_skill_for_realtime(
            "object_counter",
            {"question": "có bao nhiêu hạt trong ảnh", "target": "hạt"},
            session["session_id"],
        )

        self.assertEqual(result["status"], "no_evidence")
        self.assertEqual(result["result"]["media_command"]["mode"], "snapshot")
        self.assertEqual(result["result"]["media_command"]["skill_id"], "object_counter")
        self.assertEqual(result["result"]["media_event"]["status"], "queued")
        self.assertEqual(len(plane.list_media_commands()["commands"]), 1)
        self.assertEqual(plane.latest_hud(session["session_id"])["answer_strip"], "Đang bật camera")

    def test_realtime_target_finder_requests_bounded_live_video(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="iphone_simulator",
            capabilities={"video": "webrtc", "audio": "webrtc"},
        )

        result = plane._execute_skill_for_realtime(
            "target_finder",
            {"query": "tìm người trong đám đông", "target_type": "person"},
            session["session_id"],
        )

        command = result["result"]["media_command"]
        self.assertEqual(result["status"], "no_evidence")
        self.assertEqual(result["result"]["user_message"], "Đang bật live camera để tìm mục tiêu.")
        self.assertEqual(command["mode"], "live_video")
        self.assertEqual(command["skill_id"], "target_finder")
        self.assertEqual(command["params"]["action"], "start")
        self.assertEqual(command["params"]["camera_preference"], "widest_back")
        self.assertEqual(command["params"]["fov_mode"], "wide")
        self.assertEqual(command["params"]["crop_policy"], "no_crop")
        self.assertTrue(command["params"]["preserve_resolution"])
        self.assertFalse(command["params"]["video_stabilization"])
        self.assertTrue(command["params"]["full_fov"])
        self.assertEqual(command["params"]["profile_authority"], "jetson")
        self.assertEqual(command["params"]["camera_contract_version"], "openvision.camera_profile.v1")
        self.assertEqual(command["params"]["media_profile"], "rv101_medium_yolo")
        self.assertEqual(command["params"]["pipeline_preference"], "camera2_surface_h264")
        self.assertEqual(command["params"]["preview_route"]["route_kind"], "stable_overlay_h264")
        self.assertEqual(command["params"]["preview_route"]["primary_branch"], "yolo26_objects")
        self.assertEqual(command["params"]["preview_route"]["overlay_policy"], "stable_perception_overlay")
        self.assertEqual(command["params"]["preview_route"]["bbox_authority"], "perception_graph_stable")
        self.assertIn("yolo26_objects", command["params"]["perception_branches"])
        self.assertIn("face_identity", command["params"]["perception_branches"])
        self.assertFalse(command["params"]["app_auto_quality"])
        self.assertEqual(command["timeout_ms"], 60000)
        self.assertEqual(command["fps"], 15.0)
        self.assertEqual(command["resolution"], {"width": 800, "height": 600})
        self.assertEqual(plane.latest_hud(session["session_id"])["answer_strip"], "Đang bật live target")

        preview = plane.list_preview()[0]
        route = preview["sensor_preview"]
        self.assertEqual(route["route_kind"], "stable_overlay_h264")
        self.assertEqual(route["status"], "pending")
        self.assertEqual(route["ws_url"], f"/ws/preview/{session['session_id']}/h264")
        self.assertEqual(route["overlay_policy"], "stable_perception_overlay")
        self.assertEqual(route["bbox_authority"], "perception_graph_stable")
        self.assertFalse(route["jpeg_live_fallback_allowed"])
        self.assertFalse(preview["live_sensor_preview_uses_jpeg"])

    def test_target_finder_preview_uses_raw_h264_with_stable_perception_overlay(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="rv101_glasses",
            capabilities={"video": "h264_tcp", "audio": "pcm_tcp", "hud": "scene_json"},
        )
        plane._execute_skill_for_realtime(
            "target_finder",
            {"query": "tìm người trong đám đông", "target_type": "person"},
            session["session_id"],
        )

        plane.rv101_h264_live.publish_sample(
            session_id=session["session_id"],
            header={"sequence": 1, "isKeyframe": True, "width": 800, "height": 600},
            payload=b"\x00\x00\x00\x01\x65raw",
            media_status={"video": {"metadata": {"rotation_degrees": 270}}},
        )

        route = plane.list_preview()[0]["sensor_preview"]
        self.assertEqual(route["route_kind"], "stable_overlay_h264")
        self.assertEqual(route["desired_route_kind"], "stable_overlay_h264")
        self.assertEqual(route["status"], "live")
        self.assertEqual(route["ws_url"], f"/ws/preview/{session['session_id']}/h264")
        self.assertIsNone(route["fallback_reason"])
        self.assertEqual(route["overlay_policy"], "stable_perception_overlay")
        self.assertEqual(route["bbox_authority"], "perception_graph_stable")
        self.assertFalse(route["jpeg_live_fallback_allowed"])
        self.assertFalse(route["metadata"]["deepstream_osd_pending"])
        self.assertTrue(route["metadata"]["stable_overlay"])
        self.assertFalse(route["metadata"]["osd_burned_in"])

        plane.ingest_deepstream_h264_sample(
            session_id=session["session_id"],
            header={"sequence": 2, "isKeyframe": True, "width": 800, "height": 600},
            payload=b"\x00\x00\x00\x01\x65osd",
        )

        route = plane.list_preview()[0]["sensor_preview"]
        self.assertEqual(route["route_kind"], "stable_overlay_h264")
        self.assertEqual(route["desired_route_kind"], "stable_overlay_h264")
        self.assertEqual(route["status"], "live")
        self.assertEqual(route["ws_url"], f"/ws/preview/{session['session_id']}/h264")
        self.assertIsNone(route["fallback_reason"])
        self.assertEqual(route["overlay_policy"], "stable_perception_overlay")
        self.assertEqual(route["bbox_authority"], "perception_graph_stable")
        self.assertFalse(route["metadata"]["osd_burned_in"])

    def test_deepstream_h264_sample_does_not_recreate_preview_after_live_timeout(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="rv101_glasses",
            capabilities={"video": "h264_tcp", "audio": "pcm_tcp", "hud": "scene_json"},
        )
        queued = plane._execute_skill_for_realtime(
            "target_finder",
            {"query": "tìm người trong đám đông", "target_type": "person"},
            session["session_id"],
        )
        command_id = queued["result"]["media_command"]["command_id"]

        active = plane.ingest_deepstream_h264_sample(
            session_id=session["session_id"],
            header={"sequence": 1, "isKeyframe": True, "width": 800, "height": 600},
            payload=b"\x00\x00\x00\x01\x65osd",
        )
        plane.record_media_command_event(
            command_id=command_id,
            session_id=session["session_id"],
            status="timeout",
            payload={"adapter_status": "unit_timeout"},
        )
        late = plane.ingest_deepstream_h264_sample(
            session_id=session["session_id"],
            header={"sequence": 2, "isKeyframe": False, "width": 800, "height": 600},
            payload=b"\x00\x00\x00\x01\x41late",
        )

        self.assertEqual(active["sample_count"], 1)
        self.assertEqual(late["status"], "ignored")
        self.assertFalse(late["published"])
        self.assertEqual(late["reason"], "inactive_live_skill")
        self.assertIsNone(plane.deepstream_h264_live_status(session["session_id"]))

    def test_realtime_target_finder_object_search_skips_face_identity_branch(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="rv101_glasses",
            capabilities={"video": "h264_tcp", "audio": "pcm_tcp", "hud": "scene_json"},
        )

        result = plane._execute_skill_for_realtime(
            "target_finder",
            {"query": "tìm cái balo", "target_type": "object"},
            session["session_id"],
        )

        command = result["result"]["media_command"]
        self.assertEqual(command["params"]["preview_route"]["route_kind"], "stable_overlay_h264")
        self.assertEqual(command["params"]["preview_route"]["primary_branch"], "yolo26_objects")
        self.assertEqual(command["params"]["perception_branches"], ["yolo26_objects"])
        self.assertNotIn("face_identity_worker", command["params"]["preview_route"]["requires"])

    def test_yolo26_object_live_does_not_decode_rv101_jpeg_preview_hot_path(self):
        class FakePreviewDecoder:
            def __init__(self):
                self.enqueued = []

            def enqueue_sample(self, **kwargs):
                self.enqueued.append(kwargs)
                return {"queued": True}

        plane = OpenVisionControlPlane()
        fake_decoder = FakePreviewDecoder()
        plane.rv101_h264_preview = fake_decoder
        session = plane.create_session(
            client_kind="rv101_glasses",
            capabilities={"video": "h264_tcp", "audio": "pcm_tcp", "hud": "scene_json"},
        )
        plane._execute_skill_for_realtime(
            "target_finder",
            {"query": "tìm cái balo", "target_type": "object"},
            session["session_id"],
        )

        plane._handle_rv101_h264_sample(
            session_id=session["session_id"],
            header={"sequence": 1, "isKeyframe": True, "width": 800, "height": 600},
            payload=b"\x00\x00\x00\x01frame",
            media_status={"video": {"frame_count": 1, "metadata": {}}},
        )

        self.assertEqual(fake_decoder.enqueued, [])
        events = [
            event
            for event in plane.events.list(limit=20)
            if event["module"] == "rv101_h264_preview" and event["event_type"] == "decode_skipped"
        ]
        self.assertTrue(events)
        self.assertEqual(events[-1]["payload"]["route_kind"], "stable_overlay_h264")
        self.assertEqual(events[-1]["payload"]["perception_branches"], ["yolo26_objects"])

    def test_realtime_target_finder_named_person_declares_face_identity_branch(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="rv101_glasses",
            capabilities={"video": "h264_tcp", "audio": "pcm_tcp", "hud": "scene_json"},
        )

        result = plane._execute_skill_for_realtime(
            "target_finder",
            {"query": "tìm Trâm", "target_type": "person", "target_name": "Trâm", "identity_query": True},
            session["session_id"],
        )

        command = result["result"]["media_command"]
        self.assertEqual(command["params"]["media_profile"], "rv101_high_detail")
        self.assertEqual(command["resolution"], {"width": 1280, "height": 720})
        self.assertEqual(command["params"]["preview_route"]["route_kind"], "stable_overlay_h264")
        self.assertEqual(command["params"]["preview_route"]["primary_branch"], "yolo26_objects")
        self.assertEqual(command["params"]["perception_branches"], ["yolo26_objects", "face_identity"])
        self.assertIn("face_identity_worker", command["params"]["preview_route"]["requires"])

    def test_named_person_live_keeps_rv101_jpeg_preview_for_face_identity_branch(self):
        class FakePreviewDecoder:
            def __init__(self):
                self.enqueued = []

            def enqueue_sample(self, **kwargs):
                self.enqueued.append(kwargs)
                return {"queued": True}

        plane = OpenVisionControlPlane()
        fake_decoder = FakePreviewDecoder()
        plane.rv101_h264_preview = fake_decoder
        session = plane.create_session(
            client_kind="rv101_glasses",
            capabilities={"video": "h264_tcp", "audio": "pcm_tcp", "hud": "scene_json"},
        )
        plane._execute_skill_for_realtime(
            "target_finder",
            {"query": "tìm Trâm", "target_type": "person", "target_name": "Trâm", "identity_query": True},
            session["session_id"],
        )

        plane._handle_rv101_h264_sample(
            session_id=session["session_id"],
            header={"sequence": 1, "isKeyframe": True, "width": 800, "height": 600},
            payload=b"\x00\x00\x00\x01frame",
            media_status={"video": {"frame_count": 1, "metadata": {}}},
        )

        self.assertEqual(len(fake_decoder.enqueued), 1)
        self.assertEqual(fake_decoder.enqueued[0]["session_id"], session["session_id"])

    def test_realtime_target_finder_allows_explicit_30fps_live_video(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="rv101_glasses",
            capabilities={"video": "h264_tcp", "audio": "pcm_tcp"},
        )

        result = plane._execute_skill_for_realtime(
            "target_finder",
            {"query": "tìm người trong đám đông", "target_type": "person", "fps": 30},
            session["session_id"],
        )

        command = result["result"]["media_command"]
        self.assertEqual(result["status"], "no_evidence")
        self.assertEqual(command["mode"], "live_video")
        self.assertEqual(command["fps"], 30.0)
        self.assertEqual(command["resolution"], {"width": 1280, "height": 720})
        self.assertEqual(command["params"]["media_profile"], "rv101_diagnostic_30")
        self.assertEqual(result["result"]["media_event"]["payload"]["budget"]["fps"], 30.0)

    def test_close_session_cancels_active_live_media_command(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="rv101_glasses",
            capabilities={"video": "h264_tcp", "audio": "pcm_tcp"},
        )
        result = plane._execute_skill_for_realtime(
            "target_finder",
            {"query": "tìm người trong đám đông", "target_type": "person"},
            session["session_id"],
        )
        command_id = result["result"]["media_command"]["command_id"]

        closed = asyncio.run(plane.close_session(session["session_id"], reason="unit_test_close"))
        statuses = plane.list_media_commands()["commands"]
        command_status = next(item for item in statuses if item["command"]["command_id"] == command_id)

        self.assertEqual(closed["status"], "closed")
        self.assertEqual(plane.health()["active_live_count"], 0)
        self.assertFalse(command_status["active"])
        self.assertEqual(command_status["event"]["status"], "cancelled")
        self.assertEqual(command_status["event"]["payload"]["action"], "session_close")

    def test_non_skill_runtime_live_video_does_not_continue_target_finder(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="rv101_glasses",
            capabilities={"video": "h264", "audio": "pcm_s16le"},
        )
        command = plane.request_media_command(
            mode="live_video",
            session_id=session["session_id"],
            skill_id="target_finder",
            reason="diagnostic live smoke",
            timeout_ms=5000,
            fps=4,
            resolution={"width": 640, "height": 360},
            params={"requested_by": "rv101_product_signoff", "action": "start"},
        )["command"]

        running = plane.record_media_command_event(
            command_id=command["command_id"],
            session_id=session["session_id"],
            status="running",
            payload={"adapter_status": "rv101_live_video_running"},
        )
        stream = plane.ingest_face_identity_stream_frame(
            session_id=session["session_id"],
            source="openvision_rv101_face_identity",
            frame_id="face_1",
            width=640,
            height=360,
            sequence=1,
            latency_ms=8.0,
            detections=[
                {
                    "label": "person",
                    "confidence": 0.92,
                    "bbox": [250, 90, 330, 230],
                    "track_id": "f1",
                    "attributes": {"identity_vector": [1.0, 0.0]},
                },
            ],
        )

        self.assertNotIn("continuation", running)
        self.assertEqual(stream["status"], "error")
        self.assertEqual(stream["error"]["code"], "inactive_live_skill")

    def test_realtime_person_info_requests_snapshot_by_default(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="iphone_simulator",
            capabilities={"video": "webrtc", "audio": "webrtc"},
        )

        result = plane._execute_skill_for_realtime(
            "person_info",
            {"query": "có ai quen không"},
            session["session_id"],
        )

        command = result["result"]["media_command"]
        self.assertEqual(result["status"], "no_evidence")
        self.assertEqual(result["result"]["user_message"], "Đang chụp ảnh để kiểm tra người quen.")
        self.assertEqual(command["mode"], "snapshot")
        self.assertEqual(command["skill_id"], "person_info")
        self.assertEqual(command["timeout_ms"], 5000)
        self.assertEqual(command["params"]["action"], "capture")
        self.assertEqual(command["params"]["quality_gate"]["mode"], "best_of_burst")
        self.assertEqual(command["params"]["quality_gate"]["sample_count"], 4)
        self.assertEqual(command["params"]["quality_gate"]["settle_ms"], 850)
        self.assertEqual(plane.latest_hud(session["session_id"])["answer_strip"], "Đang check người quen")

    def test_realtime_person_info_name_reminder_requests_bounded_live_video(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="iphone_simulator",
            capabilities={"video": "webrtc", "audio": "webrtc"},
        )

        result = plane._execute_skill_for_realtime(
            "person_info",
            {"query": "bật chế độ nhắc tên", "scan_mode": "name_reminder"},
            session["session_id"],
        )

        command = result["result"]["media_command"]
        self.assertEqual(result["status"], "no_evidence")
        self.assertEqual(result["result"]["user_message"], "Đang bật live camera để nhắc tên realtime.")
        self.assertEqual(command["mode"], "live_video")
        self.assertEqual(command["skill_id"], "person_info")
        self.assertEqual(command["params"]["action"], "start")
        self.assertEqual(command["params"]["camera_preference"], "widest_back")
        self.assertEqual(command["params"]["fov_mode"], "wide")
        self.assertEqual(command["params"]["crop_policy"], "no_crop")
        self.assertTrue(command["params"]["preserve_resolution"])
        self.assertFalse(command["params"]["video_stabilization"])
        self.assertTrue(command["params"]["full_fov"])
        self.assertEqual(command["params"]["profile_authority"], "jetson")
        self.assertEqual(command["params"]["media_profile"], "rv101_high_detail")
        self.assertEqual(command["params"]["preview_route"]["route_kind"], "raw_h264")
        self.assertEqual(command["params"]["preview_route"]["primary_branch"], "face_identity")
        self.assertEqual(command["params"]["perception_branches"], ["face_identity"])
        self.assertEqual(command["timeout_ms"], 60000)
        self.assertEqual(command["fps"], 15.0)
        self.assertEqual(command["resolution"], {"width": 1280, "height": 720})
        self.assertEqual(plane.latest_hud(session["session_id"])["answer_strip"], "Đang nhắc tên")

        preview = plane.list_preview()[0]
        route = preview["sensor_preview"]
        self.assertEqual(route["route_kind"], "raw_h264")
        self.assertEqual(route["primary_branch"], "face_identity")
        self.assertEqual(route["ws_url"], f"/ws/preview/{session['session_id']}/h264")

    def test_realtime_person_info_nhac_ten_query_overrides_snapshot_scan_mode(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="rv101_glasses",
            capabilities={"video": "h264_tcp", "audio": "pcm_tcp", "hud": "scene_json"},
        )

        result = plane._execute_skill_for_realtime(
            "person_info",
            {"query": "nhắc tên", "scan_mode": "snapshot", "info_focus": "name"},
            session["session_id"],
        )

        command = result["result"]["media_command"]
        self.assertEqual(command["mode"], "live_video")
        self.assertEqual(command["params"]["preview_route"]["route_kind"], "raw_h264")
        self.assertEqual(command["params"]["preview_route"]["primary_branch"], "face_identity")
        self.assertEqual(command["params"]["perception_branches"], ["face_identity"])
        self.assertEqual(result["result"]["user_message"], "Đang bật live camera để nhắc tên realtime.")

    def test_person_info_snapshot_runs_local_face_identity_and_returns_static_thumbs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"OPENVISION_RUNTIME_DIR": temp_dir}, clear=False):
                fake_pil = types.SimpleNamespace(Image=FakePillowImageModule)
                with patch.dict(sys.modules, {"PIL": fake_pil}, clear=False):
                    with patch("openvision_jetson.control_plane.build_face_backend", return_value=FakeSnapshotFaceBackend()):
                        plane = OpenVisionControlPlane()
                        session = plane.create_session(
                            client_kind="iphone_simulator",
                            capabilities={"video": "webrtc", "audio": "webrtc"},
                        )
                        plane.identity.enroll_sample(
                            display_name="A Bảo",
                            vector=[1.0, 0.0],
                            source_note="opencv_sface:/tmp/abao.jpg",
                        )
                        plane.preview.record_frame(
                            session_id=session["session_id"],
                            source="unit_snapshot",
                            image_bytes=_jpeg_bytes(),
                            width=640,
                            height=480,
                            frame_count=1,
                        )

                        result = plane.execute_skill(
                            "person_info",
                            {"query": "có ai quen không"},
                            session_id=session["session_id"],
                        )
                        latest = plane.perception.latest(session["session_id"])
                        crop_exists = Path(temp_dir, "crops", session["session_id"], "face_snap_f1_snapshot.jpg").is_file()

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["result"]["known_person"])
        self.assertEqual(result["result"]["candidate_count"], 2)
        self.assertEqual(result["result"]["known_people"][0]["display_name"], "A Bảo")
        self.assertIn("Thấy 2 người; nhận ra A Bảo", result["result"]["answer"])
        self.assertIn("multi_face", result["result"]["hud"]["edge_chips"])
        self.assertTrue(result["result"]["detector_status"]["has_face_identity_snapshot"])
        self.assertIn("A Bảo", result["result"]["hud"]["thumbnails"][0]["caption"])
        self.assertEqual(latest["source"], "face_identity_snapshot:person_info")
        self.assertTrue(crop_exists)

    def test_person_info_snapshot_quality_gate_selects_best_recent_frame(self):
        backend = FakeQualityGateFaceBackend()
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"OPENVISION_RUNTIME_DIR": temp_dir}, clear=False):
                fake_pil = types.SimpleNamespace(Image=FakeQualityGatePillowImageModule)
                with patch.dict(sys.modules, {"PIL": fake_pil}, clear=False):
                    with patch("openvision_jetson.control_plane.build_face_backend", return_value=backend):
                        plane = OpenVisionControlPlane()
                        session = plane.create_session(
                            client_kind="iphone_simulator",
                            capabilities={"video": "webrtc", "audio": "webrtc"},
                        )
                        plane.identity.enroll_sample(
                            display_name="A Bảo",
                            vector=[1.0, 0.0],
                            source_note="opencv_sface:/tmp/abao.jpg",
                        )
                        plane.preview.record_frame(
                            session_id=session["session_id"],
                            source="unit_snapshot",
                            image_bytes=b"bad-frame",
                            width=640,
                            height=480,
                            frame_count=1,
                        )
                        plane.preview.record_frame(
                            session_id=session["session_id"],
                            source="unit_snapshot",
                            image_bytes=b"good-frame",
                            width=640,
                            height=480,
                            frame_count=2,
                        )

                        result = plane.execute_skill(
                            "person_info",
                            {"query": "người này là ai"},
                            session_id=session["session_id"],
                        )
                        latest = plane.perception.latest(session["session_id"])
                        completed = [
                            event
                            for event in plane.list_events(session_id=session["session_id"])
                            if event["module"] == "adapter.face_identity"
                            and event["event_type"] == "snapshot_analysis_completed"
                        ][-1]

        self.assertEqual(backend.markers, [b"bad-frame", b"good-frame"])
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["result"]["known_person"])
        self.assertEqual(latest["frame_id"], "preview_2")
        self.assertEqual(completed["payload"]["quality_gate"]["candidate_frame_count"], 2)
        self.assertEqual(completed["payload"]["quality_gate"]["selected_frame_count"], 2)
        self.assertGreater(
            completed["payload"]["quality_gate"]["frames"][1]["score"],
            completed["payload"]["quality_gate"]["frames"][0]["score"],
        )

    def test_stream_runtime_caches_are_pruned_after_live_timeout(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="iphone_simulator",
            capabilities={"video": "webrtc", "audio": "webrtc"},
        )
        result = plane._execute_skill_for_realtime(
            "target_finder",
            {"query": "tìm Trâm", "target_type": "person"},
            session["session_id"],
        )
        command = result["result"]["media_command"]
        command_id = command["command_id"]
        plane._continued_live_media_commands.add(command_id)
        plane._last_stream_skill_update_s[f"{session['session_id']}:{command_id}:target_finder"] = 1.0
        plane._last_stream_skill_update_s[f"{session['session_id']}:{command_id}:target_finder:face_identity"] = 1.0

        timed_out = plane.record_media_command_event(
            command_id=command_id,
            session_id=session["session_id"],
            status="timeout",
            payload={"adapter_status": "unit_timeout"},
        )

        self.assertEqual(timed_out["status"], "timeout")
        self.assertNotIn(command_id, plane._continued_live_media_commands)
        self.assertEqual(plane._last_stream_skill_update_s, {})
        self.assertEqual(plane.list_media_commands()["active_live"], [])

    def test_realtime_remember_person_requests_snapshot(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="iphone_simulator",
            capabilities={"video": "webrtc", "audio": "webrtc"},
        )

        result = plane._execute_skill_for_realtime(
            "remember_person",
            {"display_name": "Trâm", "enroll_identity": False},
            session["session_id"],
        )

        command = result["result"]["media_command"]
        self.assertEqual(result["status"], "no_evidence")
        self.assertEqual(result["result"]["user_message"], "Đang bật camera để lấy ảnh.")
        self.assertEqual(command["mode"], "snapshot")
        self.assertEqual(command["skill_id"], "remember_person")
        self.assertEqual(command["params"]["skill_args"]["display_name"], "Trâm")
        self.assertEqual(plane.latest_hud(session["session_id"])["answer_strip"], "Đang bật camera")

    def test_remember_person_uploads_latest_preview_to_immich_metadata_only(self):
        class FakeImmichUploadClient:
            def __init__(self, settings):
                self.settings = settings

            def upload_asset(self, image_bytes, *, filename, content_type="image/jpeg", taken_at=None, device_id="openvision_rokid"):
                return {
                    "status": "created",
                    "asset_id": "asset_memory_1",
                    "device_asset_id": "openvision_rokid:asset_memory_1",
                    "filename": filename,
                    "checksum_sha1": "abc123",
                    "uploaded_at": "2026-04-30T00:00:00.000+00:00",
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "OPENVISION_RUNTIME_DIR": temp_dir,
                    "OPENVISION_IMMICH_BASE_URL": "http://immich.local:2283",
                    "OPENVISION_IMMICH_API_KEY": "test_key",
                },
                clear=False,
            ):
                with patch("openvision_jetson.people_registry.ImmichClient", FakeImmichUploadClient):
                    plane = OpenVisionControlPlane()
                    session = plane.create_session(
                        client_kind="iphone_simulator",
                        capabilities={"video": "webrtc", "audio": "webrtc"},
                    )
                    plane.preview.record_frame(
                        session_id=session["session_id"],
                        source="unit",
                        image_bytes=b"jpeg-bytes",
                        width=2,
                        height=2,
                        frame_count=1,
                    )

                    result = plane.execute_skill(
                        "remember_person",
                        {"display_name": "Trâm", "enroll_identity": False},
                        session_id=session["session_id"],
                    )
                    raw_people_db = Path(temp_dir, "people", "people_registry.json").read_text(encoding="utf-8")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["memory"]["status"], "uploaded")
        self.assertEqual(result["result"]["memory"]["capture"]["immich_asset_id"], "asset_memory_1")
        self.assertIn("Immich", result["result"]["answer"])
        self.assertNotIn("jpeg-bytes", raw_people_db)
        self.assertNotIn("image_bytes", raw_people_db)

    def test_live_video_running_continues_target_finder_into_aim_hud(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="iphone_simulator",
            capabilities={"video": "webrtc", "audio": "webrtc"},
        )
        queued = plane._execute_skill_for_realtime(
            "target_finder",
            {"query": "tìm người trong đám đông", "target_type": "person"},
            session["session_id"],
        )
        command_id = queued["result"]["media_command"]["command_id"]
        plane.update_perception(
            session_id=session["session_id"],
            source="unit",
            width=640,
            height=480,
            detections=[
                {"label": "person", "confidence": 0.9, "bbox": [300, 100, 390, 440], "track_id": "p1"},
            ],
        )

        running = plane.record_media_command_event(
            command_id=command_id,
            session_id=session["session_id"],
            status="running",
            payload={"adapter_status": "simulator_live_video_running"},
        )

        self.assertEqual(running["status"], "running")
        self.assertEqual(running["continuation"]["status"], "ok")
        self.assertEqual(running["continuation"]["result"]["target_hint"]["mode"], "aim_assist")
        self.assertEqual(plane.latest_hud(session["session_id"])["target_hint"]["status"], "guiding")

        duplicate = plane.record_media_command_event(
            command_id=command_id,
            session_id=session["session_id"],
            status="running",
            payload={"adapter_status": "simulator_live_video_running"},
        )

        self.assertNotIn("continuation", duplicate)

    def test_yolo26_stream_frame_recontinues_live_target_finder(self):
        with patch.dict("os.environ", {"OPENVISION_YOLO26_MODE": "external_stream"}):
            plane = OpenVisionControlPlane()
            session = plane.create_session(
                client_kind="iphone_simulator",
                capabilities={"video": "webrtc", "audio": "webrtc"},
            )
            queued = plane._execute_skill_for_realtime(
                "target_finder",
                {"query": "tìm người trong đám đông", "target_type": "person"},
                session["session_id"],
            )
            command_id = queued["result"]["media_command"]["command_id"]
            running = plane.record_media_command_event(
                command_id=command_id,
                session_id=session["session_id"],
                status="running",
                payload={"adapter_status": "simulator_live_video_running"},
            )

            stream = plane.ingest_yolo26_stream_frame(
                session_id=session["session_id"],
                source="openvision_iphone_yolo26",
                frame_id="live_1",
                width=640,
                height=480,
                sequence=1,
                latency_ms=12.0,
                detections=[
                    {"label": "person", "confidence": 0.93, "bbox": [300, 120, 390, 430], "track_id": "p1"},
                ],
            )

        self.assertEqual(running["continuation"]["status"], "no_evidence")
        self.assertEqual(stream["status"], "accepted")
        self.assertEqual(stream["continuation"]["status"], "ok")
        self.assertEqual(stream["continuation"]["result"]["detector_status"]["status"], "ready")
        self.assertEqual(stream["continuation"]["result"]["target_hint"]["status"], "guiding")
        self.assertEqual(plane.latest_hud(session["session_id"])["target_hint"]["status"], "guiding")
        events = plane.list_events(session_id=session["session_id"])
        self.assertTrue(
            any(
                event["module"] == "skills" and event["event_type"] == "yolo26_stream_continuation_completed"
                for event in events
            )
        )

    def test_face_identity_stream_frame_recontinues_live_target_finder(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="iphone_simulator",
            capabilities={"video": "webrtc", "audio": "webrtc"},
        )
        queued = plane._execute_skill_for_realtime(
            "target_finder",
            {"query": "tìm Trâm trong đám đông", "target_type": "person"},
            session["session_id"],
        )
        command_id = queued["result"]["media_command"]["command_id"]
        running = plane.record_media_command_event(
            command_id=command_id,
            session_id=session["session_id"],
            status="running",
            payload={"adapter_status": "simulator_live_video_running"},
        )

        stream = plane.ingest_face_identity_stream_frame(
            session_id=session["session_id"],
            source="openvision_iphone_face_identity",
            frame_id="face_1",
            width=640,
            height=480,
            sequence=1,
            latency_ms=8.0,
            detections=[
                {
                    "label": "person",
                    "confidence": 0.92,
                    "bbox": [250, 90, 330, 230],
                    "track_id": "f1",
                    "attributes": {"identity_vector": [1.0, 0.0], "face_confidence": 0.92},
                },
            ],
        )

        self.assertEqual(running["continuation"]["status"], "no_evidence")
        self.assertEqual(stream["status"], "accepted")
        self.assertEqual(stream["continuation"]["status"], "ok")
        self.assertTrue(stream["continuation"]["result"]["detector_status"]["has_face_identity_stream"])
        self.assertIn("face_id", stream["continuation"]["result"]["hud"]["edge_chips"])
        events = plane.list_events(session_id=session["session_id"])
        self.assertTrue(
            any(
                event["module"] == "skills" and event["event_type"] == "face_identity_stream_continuation_completed"
                for event in events
            )
        )

    def test_face_identity_stream_frame_recontinues_person_info(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="iphone_simulator",
            capabilities={"video": "webrtc", "audio": "webrtc"},
        )
        queued = plane._execute_skill_for_realtime(
            "person_info",
            {"query": "bật chế độ nhắc tên", "scan_mode": "name_reminder"},
            session["session_id"],
        )
        command_id = queued["result"]["media_command"]["command_id"]
        plane.record_media_command_event(
            command_id=command_id,
            session_id=session["session_id"],
            status="running",
            payload={"adapter_status": "simulator_live_video_running"},
        )

        stream = plane.ingest_face_identity_stream_frame(
            session_id=session["session_id"],
            source="openvision_iphone_face_identity",
            frame_id="face_1",
            width=640,
            height=480,
            sequence=1,
            latency_ms=8.0,
            detections=[
                {
                    "label": "person",
                    "confidence": 0.92,
                    "bbox": [250, 90, 330, 230],
                    "track_id": "f1",
                    "attributes": {"identity_vector": [1.0, 0.0], "face_confidence": 0.92},
                },
            ],
        )

        self.assertEqual(stream["status"], "accepted")
        self.assertEqual(stream["continuation"]["name"], "person_info")
        self.assertEqual(stream["continuation"]["status"], "ok")
        self.assertFalse(stream["continuation"]["result"]["known_person"])
        self.assertEqual(stream["continuation"]["result"]["detector_status"]["has_face_identity_stream"], True)
        events = plane.list_events(session_id=session["session_id"])
        self.assertTrue(
            any(
                event["module"] == "skills"
                and event["event_type"] == "face_identity_stream_continuation_completed"
                and event["payload"]["name"] == "person_info"
                for event in events
            )
        )

    def test_yolo26_stream_frames_are_rejected_for_face_only_live_skill(self):
        with patch.dict("os.environ", {"OPENVISION_YOLO26_MODE": "external_stream"}):
            plane = OpenVisionControlPlane()
            session = plane.create_session(
                client_kind="iphone_simulator",
                capabilities={"video": "webrtc", "audio": "webrtc"},
            )
            queued = plane._execute_skill_for_realtime(
                "person_info",
                {"query": "bật chế độ nhắc tên", "scan_mode": "name_reminder"},
                session["session_id"],
            )
            command_id = queued["result"]["media_command"]["command_id"]
            plane.record_media_command_event(
                command_id=command_id,
                session_id=session["session_id"],
                status="running",
                payload={"adapter_status": "simulator_live_video_running"},
            )

            stream = plane.ingest_yolo26_stream_frame(
                session_id=session["session_id"],
                source="openvision_iphone_yolo26",
                frame_id="live_1",
                width=640,
                height=480,
                sequence=1,
                latency_ms=12.0,
                detections=[
                    {"label": "person", "confidence": 0.93, "bbox": [300, 120, 390, 430], "track_id": "p1"},
                ],
            )

        self.assertEqual(stream["status"], "error")
        self.assertEqual(stream["error"]["code"], "inactive_live_skill")

    def test_live_video_timeout_finishes_target_finder_without_snapshot_error(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="iphone_simulator",
            capabilities={"video": "webrtc", "audio": "webrtc"},
        )
        queued = plane._execute_skill_for_realtime(
            "target_finder",
            {"query": "tìm người trong đám đông", "target_type": "person"},
            session["session_id"],
        )
        command_id = queued["result"]["media_command"]["command_id"]

        stopped = plane.record_media_command_event(
            command_id=command_id,
            session_id=session["session_id"],
            status="timeout",
            payload={"adapter_status": "simulator_live_video_stopped"},
        )

        self.assertEqual(stopped["continuation"]["status"], "ok")
        self.assertEqual(stopped["continuation"]["result"]["user_message"], "Đã dừng live target.")
        self.assertEqual(plane.latest_hud(session["session_id"])["answer_strip"], "Đã dừng live target.")
        events = plane.list_events(session_id=session["session_id"])
        self.assertTrue(
            any(
                event["module"] == "skills" and event["event_type"] == "media_live_continuation_stopped"
                for event in events
            )
        )

    def test_non_camera_skill_does_not_request_media_command(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(client_kind="iphone_simulator", capabilities={"audio": "webrtc"})

        result = plane.execute_skill(
            "select_target",
            {"target_id": "obj_person_1"},
            session_id=session["session_id"],
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(plane.list_media_commands()["commands"], [])

    def test_perception_graph_skill_requests_snapshot_when_no_evidence(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(client_kind="iphone_simulator", capabilities={"video": "webrtc"})

        result = plane.execute_skill("count_people", {}, session_id=session["session_id"])

        self.assertEqual(result["status"], "no_evidence")
        self.assertEqual(result["result"]["media_command"]["mode"], "snapshot")
        self.assertEqual(result["result"]["media_command"]["skill_id"], "count_people")
        self.assertEqual(result["result"]["media_event"]["status"], "queued")
        self.assertTrue(result["result"]["media_command"]["params"]["continue_after_capture"])

    def test_completed_snapshot_continues_count_people_with_preview(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(client_kind="iphone_simulator", capabilities={"video": "webrtc"})
        queued = plane.execute_skill("count_people", {"min_confidence": 0.4}, session_id=session["session_id"])
        command_id = queued["result"]["media_command"]["command_id"]
        plane.preview.record_frame(
            session_id=session["session_id"],
            source="iphone_webrtc",
            image_bytes=b"jpeg",
            width=508,
            height=904,
            frame_count=3,
        )

        completed = plane.record_media_command_event(
            command_id=command_id,
            session_id=session["session_id"],
            status="ok",
            payload={
                "adapter_status": "simulator_snapshot_ready",
                "preview": {"image_url": f"/api/preview/{session['session_id']}/frame.jpg"},
            },
        )

        self.assertEqual(completed["status"], "ok")
        self.assertIn("continuation", completed)
        self.assertEqual(completed["continuation"]["status"], "no_evidence")
        self.assertEqual(completed["continuation"]["result"]["missing_runtime"], "perception_snapshot")
        self.assertEqual(plane.latest_hud(session["session_id"])["answer_strip"], "Đã chụp ảnh; chưa đếm được")
        events = plane.list_events(session_id=session["session_id"])
        self.assertTrue(
            any(event["module"] == "skills" and event["event_type"] == "media_continuation_completed" for event in events)
        )

    def test_completed_snapshot_continues_query_scene_to_cloud_gateway(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(client_kind="iphone_simulator", capabilities={"video": "webrtc"})
        queued = plane.execute_skill(
            "query_scene",
            {"question": "đang có gì trước mặt"},
            session_id=session["session_id"],
        )
        command_id = queued["result"]["media_command"]["command_id"]
        plane.preview.record_frame(
            session_id=session["session_id"],
            source="iphone_webrtc",
            image_bytes=b"jpeg",
            width=508,
            height=904,
            frame_count=3,
        )

        completed = plane.record_media_command_event(
            command_id=command_id,
            session_id=session["session_id"],
            status="ok",
            payload={"adapter_status": "simulator_snapshot_ready"},
        )

        self.assertEqual(completed["status"], "ok")
        self.assertEqual(completed["continuation"]["status"], "needs_cloud")
        self.assertEqual(
            completed["continuation"]["result"]["cloud_result"]["error"]["code"],
            "cloud_provider_missing",
        )
        self.assertEqual(
            plane.latest_hud(session["session_id"])["answer_strip"],
            "Đã chụp ảnh; visual verifier chưa sẵn sàng.",
        )

    def test_completed_snapshot_continues_text_reader_to_cloud_gateway(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(client_kind="iphone_simulator", capabilities={"video": "webrtc"})
        queued = plane.execute_skill(
            "text_reader",
            {"question": "biển này ghi gì"},
            session_id=session["session_id"],
        )
        command_id = queued["result"]["media_command"]["command_id"]
        plane.preview.record_frame(
            session_id=session["session_id"],
            source="iphone_webrtc",
            image_bytes=b"jpeg",
            width=508,
            height=904,
            frame_count=3,
        )

        completed = plane.record_media_command_event(
            command_id=command_id,
            session_id=session["session_id"],
            status="ok",
            payload={"adapter_status": "simulator_snapshot_ready"},
        )

        self.assertEqual(completed["status"], "ok")
        self.assertEqual(completed["continuation"]["name"], "text_reader")
        self.assertEqual(completed["continuation"]["status"], "needs_cloud")
        self.assertEqual(
            completed["continuation"]["result"]["cloud_result"]["error"]["code"],
            "cloud_provider_missing",
        )
        self.assertEqual(
            plane.latest_hud(session["session_id"])["answer_strip"],
            "Đã chụp ảnh; visual verifier chưa sẵn sàng.",
        )

    def test_snapshot_timeout_finishes_media_continuation_with_hud_failure(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(client_kind="iphone_simulator", capabilities={"video": "webrtc"})
        queued = plane.execute_skill(
            "scene_describe",
            {"focus": "đang có gì trước mặt tôi"},
            session_id=session["session_id"],
        )
        command_id = queued["result"]["media_command"]["command_id"]

        completed = plane.record_media_command_event(
            command_id=command_id,
            session_id=session["session_id"],
            status="timeout",
            payload={"adapter_status": "simulator_snapshot_timeout"},
        )

        self.assertEqual(completed["status"], "timeout")
        self.assertEqual(completed["continuation"]["status"], "no_evidence")
        self.assertEqual(completed["continuation"]["result"]["user_message"], "Không lấy được ảnh mới; thử hỏi lại.")
        self.assertEqual(plane.latest_hud(session["session_id"])["answer_strip"], "Không lấy được ảnh mới; thử hỏi lại.")
        events = plane.list_events(session_id=session["session_id"])
        self.assertTrue(
            any(event["module"] == "skills" and event["event_type"] == "media_continuation_failed" for event in events)
        )

    def test_simulator_close_flushes_debug_stt_buffer(self):
        plane = OpenVisionControlPlane()

        with patch.object(plane.debug_stt, "flush_session", return_value=True) as flush:
            plane._close_simulator_media("sess_test")

        flush.assert_called_once_with("sess_test", reason="simulator_stream_closed")

    def test_rv101_audio_close_flushes_debug_stt_buffer_and_gate(self):
        plane = OpenVisionControlPlane()
        plane._rv101_audio_gates["sess_test"] = object()
        plane.media.record_audio_sample(
            session_id="sess_test",
            transport="rv101_tcp",
            sample_rate=24000,
            channels=1,
            payload_bytes=1920,
            strong=False,
            source="rv101",
        )

        with patch.object(plane.debug_stt, "flush_session", return_value=True) as flush:
            plane._close_rv101_audio("sess_test")

        flush.assert_called_once_with("sess_test", reason="rv101_audio_stream_closed")
        self.assertNotIn("sess_test", plane._rv101_audio_gates)
        self.assertEqual(plane.media.status("sess_test")["audio"]["state"], "closed")


class ControlPlaneAudioGateTest(unittest.IsolatedAsyncioTestCase):
    async def test_simulator_close_marks_session_closed_and_stops_realtime(self):
        plane = OpenVisionControlPlane()
        session = plane.create_session(
            client_kind="iphone_simulator",
            capabilities={"video": "webrtc", "audio": "webrtc"},
        )

        with patch.object(plane.realtime, "stop", new=AsyncMock(return_value={"status": "stopped"})) as stop:
            plane._close_simulator_media(session["session_id"])
            await asyncio.sleep(0)

        stop.assert_awaited_once_with(session["session_id"])
        self.assertEqual(plane.list_sessions()[0]["status"], "closed")
        health = plane.health()
        self.assertEqual(health["sessions"], 0)
        self.assertEqual(health["total_sessions"], 1)
        events = plane.list_events(session_id=session["session_id"])
        self.assertTrue(
            any(event["module"] == "sessions" and event["event_type"] == "closed" for event in events)
        )

    async def test_audio_gate_monitors_without_blocking_realtime_by_default(self):
        plane = OpenVisionControlPlane()
        plane.realtime.append_audio = AsyncMock()
        silence = (0).to_bytes(2, "little", signed=True) * 20

        await plane._forward_gated_audio(
            session_id="sess_test",
            pcm_bytes=silence,
            metrics=pcm16_metrics(silence),
            source="unit",
            gates=plane._simulator_audio_gates,
        )

        plane.realtime.append_audio.assert_awaited_once_with(session_id="sess_test", pcm_bytes=silence)
        events = plane.list_events(session_id="sess_test")
        self.assertFalse(any(event["module"] == "audio_gate" and event["event_type"] == "opened" for event in events))
        media = plane.media.status("sess_test")
        self.assertEqual(media["audio"]["gate_open_count"], 0)
        self.assertEqual(media["audio"]["gate_state"], "idle")
        self.assertEqual(media["audio"]["gate_forwarded_chunk_count"], 1)

    async def test_audio_gate_can_opt_in_to_suppress_idle_noise(self):
        with patch.dict(os.environ, {"OPENVISION_REALTIME_AUDIO_GATE_MODE": "suppress_idle_noise"}):
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


class ControlPlaneMediaContinuationRealtimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_live_video_stop_updates_hud_without_extra_realtime_prompt(self):
        plane = OpenVisionControlPlane()
        plane.realtime.send_text = AsyncMock(return_value={"queued": True})
        session = plane.create_session(client_kind="iphone_simulator", capabilities={"video": "webrtc"})
        queued = plane.execute_skill(
            "target_finder",
            {"query": "tìm người trong đám đông", "target_type": "person"},
            session_id=session["session_id"],
        )
        command_id = queued["result"]["media_command"]["command_id"]

        completed = plane.record_media_command_event(
            command_id=command_id,
            session_id=session["session_id"],
            status="timeout",
            payload={"adapter_status": "simulator_live_video_stopped"},
        )
        await asyncio.sleep(0)

        self.assertEqual(completed["continuation"]["result"]["user_message"], "Đã dừng live target.")
        self.assertEqual(plane.latest_hud(session["session_id"])["answer_strip"], "Đã dừng live target.")
        plane.realtime.send_text.assert_not_awaited()
        events = plane.list_events(session_id=session["session_id"])
        self.assertTrue(
            any(
                event["module"] == "realtime"
                and event["event_type"] == "media_continuation_prompt_suppressed"
                for event in events
            )
        )

    async def test_completed_scene_snapshot_prompts_realtime_voice_followup(self):
        plane = OpenVisionControlPlane()
        plane.realtime.send_text = AsyncMock(return_value={"queued": True})
        plane.cloud_gateway._provider = lambda _bundle: {
            "schema_version": "cloud_result.v1",
            "status": "ok",
            "answer_short": "Trước mặt là một bàn làm việc.",
            "answer_long": None,
            "confidence": 0.86,
            "selected_candidate_id": None,
            "hud_scene": None,
            "safety_flags": [],
            "memory_event": None,
            "error": None,
        }
        session = plane.create_session(client_kind="iphone_simulator", capabilities={"video": "webrtc"})
        queued = plane.execute_skill(
            "scene_describe",
            {"focus": "đang có gì trước mặt tôi"},
            session_id=session["session_id"],
        )
        command_id = queued["result"]["media_command"]["command_id"]
        plane.preview.record_frame(
            session_id=session["session_id"],
            source="iphone_webrtc",
            image_bytes=b"jpeg",
            width=508,
            height=904,
            frame_count=3,
        )

        completed = plane.record_media_command_event(
            command_id=command_id,
            session_id=session["session_id"],
            status="ok",
            payload={"adapter_status": "simulator_snapshot_ready"},
        )
        await asyncio.sleep(0)

        self.assertEqual(completed["continuation"]["result"]["user_message"], "Trước mặt là một bàn làm việc.")
        plane.realtime.send_text.assert_awaited_once()
        prompt = plane.realtime.send_text.await_args.kwargs["text"]
        self.assertIn("Không gọi tool", prompt)
        self.assertIn("Trước mặt là một bàn làm việc.", prompt)
        events = plane.list_events(session_id=session["session_id"])
        self.assertTrue(
            any(
                event["module"] == "realtime"
                and event["event_type"] == "media_continuation_prompt_queued"
                for event in events
            )
        )


if __name__ == "__main__":
    unittest.main()
