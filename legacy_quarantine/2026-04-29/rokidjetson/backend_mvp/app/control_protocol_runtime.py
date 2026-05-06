from typing import Any


def build_session_accept_payload(
    *,
    session_id: str,
    result_interval_ms: int,
    media_transport: str,
    public_host: str,
    media_port: int,
    aiortc_available: bool,
    browser_audio_sample_rate: int,
    browser_audio_channels: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "session_accept",
        "version": 1,
        "sessionId": session_id,
        "controlHeartbeatMs": 1000,
        "resultThrottleMs": result_interval_ms,
        "media": {"transport": media_transport},
        "audio": {"transport": media_transport},
    }
    if media_transport == "tcp_split_av":
        payload["media"]["codec"] = "video/avc+pcm_s16le"
        payload["audio"]["codec"] = "pcm_s16le"
        payload["media"].update({"host": public_host, "port": media_port})
        payload["audio"].update({"host": public_host, "port": media_port})
    elif media_transport == "browser_webrtc":
        payload["media"].update(
            {
                "codec": "webrtc",
                "offerPath": "/api/browser/webrtc/offer",
                "wsPath": "/ws/browser",
            }
        )
        payload["audio"].update(
            {
                "codec": "webrtc",
                "offerPath": "/api/browser/webrtc/offer",
                "sampleRateHz": browser_audio_sample_rate,
                "channels": browser_audio_channels,
            }
        )
        payload["webrtc"] = {
            "enabled": aiortc_available,
            "offerPath": "/api/browser/webrtc/offer",
            "wsPath": "/ws/browser",
            "iceServers": [],
        }
    else:
        payload["media"]["codec"] = "image/jpeg"
        payload["audio"]["codec"] = "pcm_s16le"
        payload["media"].update({"path": "/ws/browser"})
        payload["audio"].update({"path": "/ws/browser", "sampleRateHz": browser_audio_sample_rate})
    return payload


def build_mode_state_payload(
    *,
    session_id: str,
    mode: str,
    mode_state: dict[str, Any],
) -> dict[str, Any]:
    return {
        "type": "mode_state",
        "version": 1,
        "sessionId": session_id,
        "mode": mode,
        **mode_state,
    }


def build_pong_payload(*, session_id: str, timestamp_ms: int) -> dict[str, Any]:
    return {
        "type": "pong",
        "version": 1,
        "sessionId": session_id,
        "timestampMs": timestamp_ms,
    }


def build_error_payload(*, message: str, session_id: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "error",
        "version": 1,
        "message": message,
    }
    if session_id:
        payload["sessionId"] = session_id
    return payload


def build_ack_payload(*, session_id: str, message_type: str) -> dict[str, Any]:
    return {
        "type": "ack",
        "version": 1,
        "sessionId": session_id,
        "messageType": message_type,
    }


def build_browser_client_hello_log(
    *,
    peer_label: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "peer": peer_label,
        "userAgent": payload.get("userAgent"),
        "platform": payload.get("platform"),
        "screen": payload.get("screen"),
        "secureContext": bool(payload.get("secureContext")),
    }


def build_browser_media_state_log(
    *,
    peer_label: str,
    video_active: bool,
    audio_active: bool,
) -> dict[str, Any]:
    return {
        "peer": peer_label,
        "videoActive": video_active,
        "audioActive": audio_active,
    }


def build_browser_client_trace_log(
    *,
    peer_label: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "peer": peer_label,
        "phase": payload.get("phase"),
        "detail": payload.get("detail") or {},
    }
