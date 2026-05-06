import unittest

from app.control_protocol_runtime import (
    build_ack_payload,
    build_browser_client_hello_log,
    build_browser_client_trace_log,
    build_browser_media_state_log,
    build_error_payload,
    build_mode_state_payload,
    build_pong_payload,
    build_session_accept_payload,
)


class ControlProtocolRuntimeTest(unittest.TestCase):
    def test_build_tcp_session_accept_payload(self) -> None:
        payload = build_session_accept_payload(
            session_id="sess_demo",
            result_interval_ms=120,
            media_transport="tcp_split_av",
            public_host="host.local",
            media_port=9082,
            aiortc_available=True,
            browser_audio_sample_rate=16000,
            browser_audio_channels=1,
        )

        self.assertEqual(payload["sessionId"], "sess_demo")
        self.assertEqual(payload["media"]["host"], "host.local")
        self.assertEqual(payload["media"]["codec"], "video/avc+pcm_s16le")
        self.assertEqual(payload["audio"]["codec"], "pcm_s16le")

    def test_build_browser_webrtc_session_accept_payload(self) -> None:
        payload = build_session_accept_payload(
            session_id="sess_browser",
            result_interval_ms=120,
            media_transport="browser_webrtc",
            public_host="host.local",
            media_port=9082,
            aiortc_available=False,
            browser_audio_sample_rate=16000,
            browser_audio_channels=1,
        )

        self.assertEqual(payload["webrtc"]["enabled"], False)
        self.assertEqual(payload["media"]["offerPath"], "/api/browser/webrtc/offer")
        self.assertEqual(payload["audio"]["sampleRateHz"], 16000)

    def test_build_mode_pong_ack_and_error_payloads(self) -> None:
        self.assertEqual(
            build_mode_state_payload(
                session_id="sess_demo",
                mode="standby",
                mode_state={"shellLabel": "standby"},
            )["shellLabel"],
            "standby",
        )
        self.assertEqual(build_pong_payload(session_id="sess_demo", timestamp_ms=9)["type"], "pong")
        self.assertEqual(build_ack_payload(session_id="sess_demo", message_type="ping")["messageType"], "ping")
        self.assertEqual(build_error_payload(message="bad", session_id="sess_demo")["sessionId"], "sess_demo")

    def test_build_browser_log_payloads(self) -> None:
        hello = build_browser_client_hello_log(
            peer_label="1.2.3.4:9999",
            payload={"userAgent": "Safari", "secureContext": 1},
        )
        media = build_browser_media_state_log(
            peer_label="1.2.3.4:9999",
            video_active=True,
            audio_active=False,
        )
        trace = build_browser_client_trace_log(
            peer_label="1.2.3.4:9999",
            payload={"phase": "capture_ready", "detail": {"fps": 8}},
        )

        self.assertEqual(hello["userAgent"], "Safari")
        self.assertEqual(media["videoActive"], True)
        self.assertEqual(trace["detail"], {"fps": 8})


if __name__ == "__main__":
    unittest.main()
