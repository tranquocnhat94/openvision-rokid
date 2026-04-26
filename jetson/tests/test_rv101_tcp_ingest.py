import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.event_store import InMemoryEventStore
from openvision_jetson.media_gateway import MediaGateway
from openvision_jetson.rv101_tcp_ingest import (
    Rv101TcpIngestService,
    Rv101TcpIngestSettings,
    TYPE_AUDIO_HELLO,
    TYPE_AUDIO_SAMPLE,
    TYPE_VIDEO_HELLO,
    TYPE_VIDEO_SAMPLE,
    build_rvs1_frame,
    load_rv101_tcp_ingest_settings,
)


class Rv101TcpIngestTest(unittest.IsolatedAsyncioTestCase):
    async def test_video_and_audio_frames_update_media_gateway(self):
        events = InMemoryEventStore()
        media = MediaGateway(events=events)
        forwarded_audio = []
        closed_audio_sessions = []

        async def on_audio(session_id, pcm_bytes):
            forwarded_audio.append((session_id, pcm_bytes))

        service = Rv101TcpIngestService(
            media=media,
            events=events,
            settings_provider=lambda: Rv101TcpIngestSettings(
                enabled=True,
                bind_host="127.0.0.1",
                advertised_host="127.0.0.1",
                video_port=0,
                audio_port=0,
            ),
            audio_pcm_handler=on_audio,
            audio_close_handler=closed_audio_sessions.append,
        )
        await service.start()
        try:
            _reader, writer = await asyncio.open_connection("127.0.0.1", service.video_port)
            writer.write(
                build_rvs1_frame(
                    TYPE_VIDEO_HELLO,
                    {
                        "sessionId": "sess_test",
                        "codec": "video/avc",
                        "width": 1280,
                        "height": 720,
                        "targetFps": 30,
                    },
                )
            )
            writer.write(
                build_rvs1_frame(
                    TYPE_VIDEO_SAMPLE,
                    {"sessionId": "sess_test", "isKeyframe": True, "width": 1280, "height": 720},
                    b"video",
                )
            )
            await writer.drain()
            writer.close()
            await writer.wait_closed()

            _reader, writer = await asyncio.open_connection("127.0.0.1", service.audio_port)
            writer.write(
                build_rvs1_frame(
                    TYPE_AUDIO_HELLO,
                    {"sessionId": "sess_test", "sampleRateHz": 24000, "channels": 1},
                )
            )
            writer.write(
                build_rvs1_frame(
                    TYPE_AUDIO_SAMPLE,
                    {
                        "sessionId": "sess_test",
                        "sampleRateHz": 24000,
                        "channels": 1,
                        "avgAbs": 180,
                        "nonSilentRatio": 0.4,
                        "audioSource": "VOICE_RECOGNITION",
                    },
                    b"pcm",
                )
            )
            await writer.drain()
            writer.close()
            await writer.wait_closed()

            await asyncio.sleep(0.05)
            status = media.status("sess_test")
        finally:
            await service.stop()

        self.assertEqual(status["video"]["frame_count"], 1)
        self.assertEqual(status["video"]["keyframe_count"], 1)
        self.assertEqual(status["audio"]["chunk_count"], 1)
        self.assertEqual(status["audio"]["strong_chunk_count"], 1)
        self.assertEqual(forwarded_audio, [("sess_test", b"pcm")])
        self.assertEqual(closed_audio_sessions, ["sess_test"])

    async def test_wildcard_bind_auto_advertises_detected_lan_ip(self):
        with patch.dict(
            os.environ,
            {
                "OPENVISION_RV101_TCP_INGEST": "1",
                "OPENVISION_RV101_BIND_HOST": "0.0.0.0",
            },
            clear=True,
        ), patch("openvision_jetson.rv101_tcp_ingest._detect_lan_ip", return_value="192.168.8.178"):
            settings = load_rv101_tcp_ingest_settings()

        self.assertEqual(settings.bind_host, "0.0.0.0")
        self.assertEqual(settings.advertised_host, "192.168.8.178")

    async def test_explicit_advertised_host_overrides_auto_detection(self):
        with patch.dict(
            os.environ,
            {
                "OPENVISION_RV101_TCP_INGEST": "1",
                "OPENVISION_RV101_BIND_HOST": "0.0.0.0",
                "OPENVISION_RV101_ADVERTISED_HOST": "192.168.8.200",
            },
            clear=True,
        ), patch("openvision_jetson.rv101_tcp_ingest._detect_lan_ip", return_value="192.168.8.178"):
            settings = load_rv101_tcp_ingest_settings()

        self.assertEqual(settings.advertised_host, "192.168.8.200")


if __name__ == "__main__":
    unittest.main()
