# Jetson Runtime

Jetson is the local realtime authority for OpenVision Rokid V2.

It owns:

- stream ingest and media health;
- audio/video metrics;
- local detection, tracking, light OCR, and audio gating;
- perception graph;
- skill manifest/registry/runtime;
- selected-target state;
- HUD scene authority;
- cloud escalation decision;
- Ops Console, logs, replay, scorecards, and deploy.

It must not become a mixed backend pile. New work should land in the subsystem that owns the behavior and should communicate through shared schemas.

## Source Layout

- `agent/`: app shell, FastAPI entrypoint, control plane, settings, sessions, events.
- `audio_turns/`: audio signal, turn, and sidecar helpers.
- `media_gateway/`: RV101 TCP ingest, media metrics, sensor preview store.
- `realtime_agent/`: current live cloud AI/Reatime bridge and events.
- `cloud_gateway/`: typed evidence bundles, privacy/budget gates, and cloud result validation.
- `skills/`: typed skill registry and executor.
- `perception/`: perception graph and Rokid-specific detector adapters.
- `hud_authority/`: HUD scene helpers and authority.
- `simulator_bridge/`: iPhone WebRTC harness.
- `lab_fallbacks/`: off-route diagnostics such as Debug STT.
- `tests/`: tests only.

## Runtime Rules

- Local-first: answer locally when confidence and capability are enough.
- Cloud escalation must use evidence bundles and structured results as the gateway matures.
- Every skill must expose typed inputs/outputs and HUD scene output.
- Debug STT is only Ops Console visibility.
- Do not route product commands through hidden transcript logic.
- Do not touch Ring / YOLO26 security runtime; build a separate Rokid adapter when needed.
