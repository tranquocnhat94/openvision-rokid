# Transport

Transport owns network channels from glasses to Jetson.

Read first:

```text
../../docs/openvision/27_ROKID_APP_CODEX_ROADMAP.md
../../docs/openvision/18_ROKID_APP_RUNTIME_CONTRACT.md
```

Channels:

- video stream;
- audio stream;
- websocket control/result;
- HUD acknowledgement;
- diagnostics heartbeat.

Reconnect must be observable from Jetson Web UI.

Product transport rules:

```text
/ws control owns client_hello, session_accept, HUD, health, and PTT events
tcp_pcm carries RV101 microphone PCM for app-open conversation_realtime
Cloud Realtime server_vad handles default turn detection
future wake_realtime keeps tcp_pcm/cloud audio off until "Hey Vision" opens a session
PTT/manual-turn over tcp_pcm remains debug/fallback only
tcp_h264 carries RV101 live video only for bounded MediaCommand live_video
/ws/realtime/{session_id}/audio carries assistant audio from session_accept voiceOutput
REST MediaCommand polling/upload is allowed as a thin client adapter, but not as
an app-side skill router or Realtime bootstrap
```

On disconnect, session supersede, Activity stop, or stale command detection,
transport must stop active media/audio work and avoid rendering late HUD/audio
from the old session. The app must not manage Tailscale/VPN, hold Wi-Fi awake,
or hide reconnect failures from Jetson scorecards.
