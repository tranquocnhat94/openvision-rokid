# Ops Console And Debug Web UI Plan

The v2 Web UI is an operator console for building, running, and verifying a product-grade wearable agent. It is not a replacement for the glasses UI.

## Core Goal

The console must answer five questions quickly:

- Is media arriving from RV101 or iPhone?
- Did OpenAI Realtime choose the right typed tool?
- Did Jetson execute the skill correctly?
- What HUD scene was sent?
- If needed, what Vietnamese sentence did the Debug STT sidecar hear?

## Current/Target Views

### 1. Overview

- Jetson service health.
- Active sessions: RV101, iPhone simulator, replay.
- OpenAI Realtime connection state.
- Model and redacted secret status.
- Media ingest state: fps, audio chunks, frame lag.
- Sensor preview card.
- Current HUD mirror.
- Recent errors/reconnects.

### 2. Session Timeline

Per session, show a unified trace:

- client connect/disconnect;
- video keyframes and frame samples;
- audio chunk energy;
- audio turn start/commit/cancel;
- Realtime session updates;
- function calls;
- skill execution;
- cloud evidence calls;
- HUD scene updates;
- client HUD acknowledgements;
- Debug STT completed transcript when enabled.

Do not make transcript text the main proof of understanding. The proof is the tool/skill/HUD chain.

### 3. Agent Understanding

This should become the primary debugging panel for cloud AI behavior:

- latest audio turn ID;
- Realtime event state;
- selected tool name;
- typed JSON args;
- skill owner/runtime;
- skill result;
- HUD scene ID/type;
- latency chain;
- error/retry details.

This panel should work even when Debug STT is disabled.

### 4. Realtime Console

- OpenAI session status.
- Realtime model, voice, audio format, turn policy.
- Audio append/commit counters.
- Tool-call latency.
- Reconnect reason and backoff.
- Raw event inspector with secrets redacted.
- Prompt/config preview with version hash.

Do not add OpenAI transcription as a parallel default route.

### 5. Audio Lab

- Live PCM amplitude graph.
- Strong chunk ratio.
- Source stability.
- Segment boundaries.
- VAD/manual decisions.
- Manual commit test button.
- Audio diagnostic bundle with secrets removed.
- Debug STT completed-turn text and latency.

The Debug STT panel must say it is Ops-only.

### 6. Skills Lab

- Typed skill registry.
- Skill schema viewer.
- Dry-run typed JSON input.
- Live calls from OpenAI.
- Local/cloud routing decision.
- Timeout/retry/cancel status.
- Last results and HUD payload.
- Permission gates for risky skills.
- Test fixtures per skill.

### 7. Perception Lab

- Live preview frame sample.
- YOLO26 adapter status through Rokid-specific path.
- Detection table.
- Track table.
- Crop gallery.
- Candidate shortlist for cloud attribute reasoning.
- Selected-target state.
- Target lost/reacquired timeline.
- Perception graph inspector.

### 8. Cloud Evidence Lab

- Crop batches sent to cloud.
- Attribute query text.
- Cloud result mapping back to Jetson object IDs.
- Evidence confidence.
- Cost/latency counters.
- Redaction and retention policy.

### 9. HUD Studio

- RV101 safe-zone HUD mirror.
- iPhone simulator HUD mirror.
- Scene JSON inspector.
- Answer strip preview.
- Edge chips preview.
- Thumbnail strip preview.
- Target reticle preview.
- Priority and TTL debug.
- Client acknowledgement log.

### 10. iPhone Simulator

- Secure simulator URL.
- QR code for phone access.
- WebRTC connection status.
- Camera/mic permission state.
- `getUserMedia` preview.
- WebRTC stats.
- Same session timeline as RV101.
- Same HUD renderer as glasses contract.

### 11. Settings

- Model config.
- Realtime turn policy.
- Jetson runtime paths.
- YOLO26 adapter status/path.
- Debug STT status/path.
- Secret status only, never secret values.
- Feature flags.
- Export/import redacted config.

### 12. Logs And Replay

- Filter by session, module, skill, trace ID.
- Export redacted session bundle.
- Replay frame/audio metadata and skill traces.
- Compare two sessions for latency/regression checks.

## Debug Bundle Requirements

A bundle may include:

- session metadata;
- protocol events;
- latency timings;
- HUD scene JSON;
- skill args/results;
- crop references if explicitly enabled;
- audio energy metrics;
- Debug STT text if enabled;
- redacted config.

A bundle must not include:

- OpenAI API keys;
- raw private credentials;
- unredacted personal memory;
- unexpected full audio/video capture unless explicitly enabled for a bounded session.

## UI Hygiene Rules

- Product panels come first.
- Lab/fallback panels stay visually labelled and lower priority.
- Old modes must not appear as peer product controls.
- Fake data must be labelled as simulated.
- Secret values are never rendered.
- Text must not overlap; trace rows should wrap or truncate cleanly.
- Sensor preview is an Ops/debug view, not product transport.
