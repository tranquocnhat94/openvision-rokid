# Glasses Protocol

Client protocol models should be generated from or mirrored against `shared/`.

The glasses must speak the same session, HUD, and control contracts as the iPhone simulator.

Read first:

```text
../../docs/openvision/27_ROKID_APP_CODEX_ROADMAP.md
../../docs/openvision/18_ROKID_APP_RUNTIME_CONTRACT.md
../../docs/openvision/17_MEDIA_ACTIVATION_POLICY.md
../../docs/openvision/19_VOICE_AND_CLOUD_ROUTING.md
```

Canonical product contracts:

```text
client_hello -> session_accept
session_accept voice_mode=conversation_realtime -> app starts foreground mic stream
future wake_realtime -> "Hey Vision" trigger opens the same conversation path
session_accept voiceOutput / voice_output -> assistant audio websocket
Cloud Realtime server_vad -> turn boundaries for default conversation
ptt_down -> tcp_pcm stream -> stream close -> ptt_up for debug/fallback PTT
MediaCommand -> capture/stream -> MediaEvent
DisplayCommand / hud_scene -> HUD renderer
glasses_health / diagnostics -> Jetson scorecard
```

Default RV101 conversation uses Cloud Realtime `server_vad`, not Jetson/app-side
voice gating. Do not make REST Realtime bootstrap, direct cloud calls, local
STT, or Android-side skill routing the protocol path. Any RV101 hardware
exception must be documented in `../android_client/MEASURED_DECISIONS.md` and
reflected back into the shared backend contract when it becomes product
behavior.
