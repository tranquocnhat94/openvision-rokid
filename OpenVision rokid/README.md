# OpenVision Rokid V2

This folder is the active product foundation for OpenVision Rokid V2.

```text
Rokid = low-power microphone/camera/display terminal
Cloud Realtime AI = conversation brain + typed tool/skill orchestrator
Jetson = trusted tool server + media gateway + perception graph + display/privacy authority
```

The goal is a product-grade wearable AI Skill OS, not a cleaned-up copy of v1.
Reality Radar is an advanced Find skill on top of this OS, not the product
boundary. Backend work should keep strengthening reusable media, perception,
skill, cloud, HUD, replay, and scorecard paths so many skills can operate
smoothly, not just Radar.

## Read First

The canonical docs are mirrored here, but root `docs/openvision/` is the main source of truth.

1. `../docs/openvision/00_INDEX.md`
2. `../docs/openvision/00_CODEX_START_HERE_CLOUD_REALTIME_V2.md`
3. `docs/openvision/00_INDEX.md`
4. `../PROJECT_MEMORY.md`
5. `../ROKID_CURRENT_STATE.md`
6. `../ROKID_CODEX_EXECUTION_PACK.md`
7. `../docs/openvision/27_ROKID_APP_CODEX_ROADMAP.md` for RV101/glasses app work

## Folder Roles

- `glasses/`: RV101 thin-client contract. Capture, transport, session state, HUD rendering, minimal diagnostics.
- `iphone_web_simulator/`: fast browser/iPhone harness that mirrors the glasses contract for backend iteration.
- `jetson/`: local runtime authority. Media ingest, perception graph, skill runtime, HUD authority, Ops Console, cloud escalation, deploy.
- `shared/`: contracts, schemas, fixtures, protocol definitions.
- `ops/`: deploy/service/config notes. Secrets stay outside git.
- `docs/openvision/`: V2 guidance pack mirror.
- `scripts/`: local checks and operational helpers.

## Current Implementation

Implemented:

- Jetson FastAPI service in `jetson/agent/`;
- RV101 TCP H.264/PCM ingest;
- iPhone WebRTC simulator bridge;
- typed skill executor foundation;
- HUD authority and scene contracts;
- perception graph scaffolding;
- sensor preview for Ops Console;
- OpenAI Realtime bridge as current live cloud AI channel;
- typed `RealtimeToolCall`, `ToolResult`, and `ToolError` contracts;
- `JetsonToolServer` dispatch skeleton for manifest-validated skill tools;
- Vietnamese Realtime mocked route coverage for conversational no-tool turns and typed visual tool turns;
- shared `MediaCommand`, `MediaEvent`, and `DisplayCommand` schemas;
- MediaCommand Jetson runtime gateway for snapshot, burst clip, and bounded live video start/stop;
- iPhone simulator MediaCommand client adapter with microphone-first startup and camera-on-command capture;
- Realtime visual skills request typed MediaCommand capture when fresh visual evidence is missing;
- completed skill-requested snapshot/burst events continue back into the skill runtime and HUD once preview/perception evidence is available;
- media continuation now prompts Realtime to speak the post-capture skill result and publishes clear timeout/error HUD states instead of leaving camera capture stuck;
- Realtime startup retries transient opening-handshake failures before marking a session failed;
- Realtime response creation is serialized to avoid overlapping `response.create` errors during media continuation, server VAD is tuned for longer app-open conversation turns, RV101 defaults to `conversation_realtime/server_vad`, explicit push-to-talk fallback uses manual Realtime turns with audio-ordered commit/response.create, and Jetson audio gate defaults to monitor-only instead of blocking Realtime audio;
- preview-backed fallback behavior for incomplete visual skills: `count_people` reports missing detector/perception and `scene_describe`/`query_scene` route captured preview evidence through the cloud gateway;
- `object_counter` MVP for non-person visual counting requests such as "có bao nhiêu hạt" or "đếm mấy cái";
- `text_reader` MVP for sign/label/screen/document OCR requests such as "biển này ghi gì" or "có chữ gì", using Jetson-owned snapshot evidence through CloudGateway until local OCR is promoted;
- `scene_describe` MVP as the first practical Phase 4 skill, with fresh snapshot capture for repeated Realtime scene asks and CloudGateway visual verifier answers;
- `target_finder` live person searches opportunistically scan the local contact identity DB, request a 1280x720 live stream budget, and keep anonymous aim assist when no confident contact match exists;
- Face identity worker upscales small preview frames, tries orientation fallback for iPhone/Rokid portrait streams, reports face-size quality, and marks tiny faces as `low_quality_face` before posting face embeddings;
- `needs_cloud` skill/tool results are rejected unless they include schema-valid `cloud_evidence_bundle`, `cloud_gateway`, and `cloud_result` objects;
- optional OpenAI Responses visual verifier provider behind CloudGateway, with local preview refs converted to data URLs and structured `cloud_result.v1` validation;
- clean RV101 Android client module with tailnet default endpoint, HUD/PTT, typed snapshot, real-device verified bounded burst_clip, and a non-promoted H.264 live_video adapter pending Jetson no-restart hardening;
- RV101 product signoff harness for safe real-device app/backend checks over normal tailnet or USB/ADB tunnel routes;
- DisplayCommand Jetson runtime adapter to HUD scene protocol;
- skill manifest fields for media requirements, display capabilities, memory allowance, and cloud behavior;
- strict skill manifest validation against `skill_manifest.schema.json` plus V2 media/cloud/HUD consistency checks at registry load;
- scorecard metrics for realtime tool, media command, and display command latency;
- RV101 voice-contract scorecard metrics/gate for `conversation_realtime/server_vad` vs explicit PTT fallback;
- embedded skill-level replay eval in session scorecards, covering typed skill invocation, media evidence, cloud evidence, identity checks, HUD output, and skill latency;
- `scripts/export_session_replay.py` for durable local replay/scorecard artifacts under ignored `runtime/replays/` with retention;
- cloud realtime orchestration guidance and media/display command policy docs;
- optional Debug STT sidecar;
- deploy/check scripts and tests.

Pending:

- production detector/tracker feeding perception graph;
- normal-route RV101 tailnet product signoff, release signing/config, and long-run battery/thermal/memory soak;
- repeated preview-enabled scorecards before production RV101/Rokid live_video skill use;
- visual verifier prompt/eval tuning against exported replay fixtures and real-session signoff logs;
- remaining practical skill hardening/eval: `target_finder`, `text_reader`, `scene_describe`, and `object_counter`;
- normal-route RV101 device signoff logs.

## Architecture Discipline

Preferred runtime flow:

```text
Rokid voice -> Jetson Realtime bridge -> Cloud Realtime -> typed Jetson tool call -> skill/media/display executor -> HUD/display command
```

Do not add:

- one-off feature endpoints as product architecture;
- skill-specific HUD rendering;
- direct cloud calls from random modules;
- simulator-only product behavior;
- hidden STT command routing;
- old mode screens.

Camera is off by default. Visual media must be activated by typed tools/skills as `none`, `snapshot`, `burst_clip`, or bounded `live_video`.

## Ring / YOLO26 Boundary

Do not touch the existing Ring / YOLO26 security runtime.

If V2 needs YOLO26 assets, create a separate OpenVision/Rokid adapter path and expose it through typed skills and perception graph outputs. Live detector boxes must pass through the Rokid YOLO26 stabilizer/perception graph before product preview, HUD, or skills consume them; DeepStream OSD is diagnostic, not the product bbox authority.

## Checks

```bash
./scripts/check_v2.sh
```
