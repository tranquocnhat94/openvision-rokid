# Audio Turns

Audio turn handling normalizes microphone input before it reaches any router, cloud/live AI session, Debug STT sidecar, or replay tool.

Source package:

- `openvision_jetson/audio_signal.py`

Responsibilities:

- PCM format normalization;
- energy telemetry;
- source stability tracking;
- turn start/commit/cancel;
- turn policy and commit decisions;
- Debug STT sidecar handoff for completed turns when enabled;
- replay/debug bundle data.

Rules:

- audio metrics are product telemetry, not decoration;
- Debug STT text is Ops-only visibility;
- transcript text must not secretly route commands or drive HUD;
- current OpenAI Realtime usage is a live cloud AI channel, but Jetson remains the runtime owner.
