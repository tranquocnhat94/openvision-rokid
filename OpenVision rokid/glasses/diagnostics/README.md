# Diagnostics

Diagnostics are for capture and transport health.

Read first:

```text
../../docs/openvision/27_ROKID_APP_CODEX_ROADMAP.md
../../docs/openvision/18_ROKID_APP_RUNTIME_CONTRACT.md
```

Examples:

- camera fps;
- encoder bitrate;
- audio chunk rate;
- PCM amplitude summary;
- websocket state;
- HUD acknowledgement state.
- session_accept voiceOutput state;
- MediaCommand start/ok/error/timeout/cancelled state;
- selected/requested capture profile and orientation;
- dropped frames and estimated sent FPS;
- camera cleanup and active media state.

Diagnostics should not become product controls.

Diagnostics should make Jetson scorecards and replay easier to trust. They
should not choose skills, change media modes, start cloud sessions, route
transcripts, or expose secrets. If a diagnostic reveals a hardware exception,
record the measured exception in `../android_client/MEASURED_DECISIONS.md`
instead of silently changing the product route.
