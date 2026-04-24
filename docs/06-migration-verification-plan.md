# Migration And Verification Plan

v2 should be built in small passes. The old project remains available as a reference, but v2 should not inherit its shape.

## Current Snapshot

Done:

- v2 workspace created under `OpenVision rokid/`;
- Jetson agent service exists;
- shared contracts and schemas exist;
- Ops Console exists;
- iPhone WebRTC simulator bridge exists;
- RV101 TCP media ingest exists;
- OpenAI Realtime/tool manager foundation exists;
- typed skill executor exists;
- HUD authority exists;
- sensor preview exists;
- Debug STT sidecar exists;
- v2 backend checks pass.

Pending:

- clean v2 Android module;
- deep YOLO26 skill integration through separate Rokid path;
- real people-count/search-target detector/crop/track loop;
- live iPhone session after latest doc/runtime decisions;
- live RV101 product validation.

## Phase 0: Clean Contracts

- Create shared schemas for session, media, audio turn, Realtime event, skill call, perception object, selected target, HUD scene, and Debug STT result.
- Add schema validation tests.
- Add sample fixtures for RV101 and iPhone simulator sessions.

Done when:

- schemas validate fixtures;
- no old modes exist in shared contracts;
- HUD scene can represent answer strip, chips, thumbnails, and target cue;
- Debug STT is represented as Ops-only metadata.

## Phase 1: Jetson Skeleton

- Build service entrypoint.
- Build media gateway interfaces.
- Build session manager.
- Build Ops Console shell.
- Build redacted settings loader.
- Build trace/event bus.

Done when:

- local service starts;
- Ops Console shows health/session pages;
- no OpenAI key is persisted in ordinary config;
- events are traceable by session ID.

## Phase 2: Realtime Agent

- Implement OpenAI Realtime client.
- Implement turn policy abstraction.
- Implement function-call loop with typed skill registry.
- Add reconnect handling and latency telemetry.

Done when:

- Vietnamese speech can trigger correct typed tool calls in controlled tests;
- function call output returns to Realtime correctly;
- manual/turn handling works for both simulator and RV101 paths;
- command success is visible in tool/skill/HUD trace, not only transcript text.

## Phase 3: Debug STT Sidecar

- Send completed local audio turns to mini PC PhoWhisper when enabled.
- Show completed Vietnamese sentence in Ops Console.
- Keep the sidecar separate from command routing and HUD.

Done when:

- warm/health check reports worker status;
- Debug STT text is traceable by audio turn ID;
- disabling Debug STT does not affect Realtime tool calls;
- no OpenAI transcription path is needed for text visibility.

## Phase 4: iPhone Simulator

- Build secure web client.
- Implement getUserMedia from tap.
- Implement WebRTC upstream.
- Render shared HUD scene.
- Connect to the same session timeline and Ops Console.

Done when:

- iPhone can test voice/video/HUD without creating a separate product path;
- Ops Console shows simulator media stats, Realtime/tool/HUD events, sensor preview, and Debug STT text if enabled.

## Phase 5: Glasses Thin Client

- Port clean Camera2/MediaCodec H.264 capture.
- Port PCM audio transport with source/energy telemetry.
- Port websocket/control/result client.
- Port HUD renderer for v2 scene schema.

Done when:

- Android build passes;
- RV101 session appears in Ops Console;
- video transport and HUD work;
- audio logs show stable source and useful amplitude.

## Phase 6: Vision Skills

- Add Rokid-specific YOLO26 adapter path.
- Implement `count_people`.
- Implement `search_targets` candidate crops.
- Add cloud attribute resolver.
- Add selected-target state and HUD cues.

Done when:

- `Phía trước có bao nhiêu người?` calls `count_people` and shows count on HUD;
- `Tìm người mặc áo màu xanh` returns candidate thumbnails and target IDs;
- Jetson owns tracking and selected-target continuity;
- Ring/security YOLO26 runtime remains untouched.

## Verification Gates

For every phase:

- run unit tests;
- run schema validation;
- run syntax/import checks;
- capture an Ops Console session trace;
- export a redacted debug bundle if the phase touches runtime;
- do not claim RV101 success without RV101 logs.

For audio changes:

- source remains stable;
- strong chunk ratio improves;
- rapid re-probes reduce;
- Realtime tool calls match Vietnamese intent;
- Debug STT, if enabled, shows useful completed-turn text;
- no video/HUD regression.

For docs-only changes:

- grep active docs for removed routes;
- make sure new docs do not describe archived ideas as active behavior.
