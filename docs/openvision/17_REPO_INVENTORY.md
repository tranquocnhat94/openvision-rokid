# 17 — Current Repo Inventory

Updated: 2026-04-25

This inventory captures the current V2 repo shape so future Codex topics do not rediscover old paths or mistake legacy code for the product path.

## Active V2 Product Path

```text
OpenVision rokid/
  glasses/                RV101 thin-client contract docs
  iphone_web_simulator/   browser/iPhone harness contract
  jetson/                 active Jetson runtime
  shared/                 schemas, contracts, fixtures
  ops/                    deploy/systemd/env templates
  docs/openvision/        mirrored V2 guidance pack
```

Root canonical docs:

```text
docs/openvision/
.github/codex/prompts/
AGENTS.md
PROJECT_MEMORY.md
ROKID_CURRENT_STATE.md
ROKID_CODEX_EXECUTION_PACK.md
```

## Legacy Reference Paths

These are reference only unless the user explicitly asks to edit them:

```text
legacy_quarantine/2026-04-29/RokidVideoStream/          legacy buildable RV101 app
legacy_quarantine/2026-04-29/rokidjetson/backend_mvp/   legacy backend MVP
docs/reference/            supporting historical notes
docs/archive/              archived product thinking
legacy_quarantine/2026-04-29/rokidjetson/archive/       archived backend plans
```

Do not expand these paths as the active V2 product.

## Current Android / Rokid App

V2 has only the clean glasses contract in:

```text
OpenVision rokid/glasses/
```

The currently buildable Android app remains legacy:

```text
legacy_quarantine/2026-04-29/RokidVideoStream/app/src/main/
```

Important legacy files:

```text
VideoStreamActivity.kt
GlassAudioCapture.kt
GlassAudioStreamClient.kt
JetsonControlClient.kt
JetsonProtocolModels.kt
Rv101HudRenderer.kt
```

Port only the thin-client pieces into V2 later: capture, encode, microphone, transport, session state, HUD renderer.

## Current Jetson / Backend

Active V2 backend:

```text
OpenVision rokid/jetson/agent/openvision_jetson/fastapi_app.py
OpenVision rokid/jetson/agent/openvision_jetson/control_plane.py
OpenVision rokid/jetson/media_gateway/openvision_jetson/
OpenVision rokid/jetson/perception/openvision_jetson/
OpenVision rokid/jetson/skills/openvision_jetson/
OpenVision rokid/jetson/hud_authority/openvision_jetson/
OpenVision rokid/jetson/realtime_agent/openvision_jetson/
OpenVision rokid/jetson/simulator_bridge/openvision_jetson/
OpenVision rokid/jetson/lab_fallbacks/openvision_jetson/
```

Legacy backend:

```text
legacy_quarantine/2026-04-29/rokidjetson/backend_mvp/app/
```

## Current Runtime / Model Paths

V2:

```text
realtime_agent/openvision_jetson/realtime_manager.py
lab_fallbacks/openvision_jetson/debug_stt.py
perception/openvision_jetson/yolo26_rokid_adapter.py
skills/manifests/*.json
```

V2 environment/runtime config:

```text
OpenVision rokid/ops/openvision.env.example
OpenVision rokid/ops/systemd/openvision-jetson.service
OpenVision rokid/scripts/prepare_jetson_secrets.sh
```

Legacy model/runtime scripts:

```text
legacy_quarantine/2026-04-29/rokidjetson/backend_mvp/scripts/*phowhisper*
legacy_quarantine/2026-04-29/rokidjetson/backend_mvp/scripts/*whisper*
legacy_quarantine/2026-04-29/rokidjetson/backend_mvp/scripts/start_backend.sh
```

## Current Cloud API Locations

Active V2 cloud/live AI code:

```text
OpenVision rokid/jetson/realtime_agent/openvision_jetson/realtime_manager.py
```

Secrets load through environment or key file:

```text
OpenVision rokid/jetson/agent/openvision_jetson/settings.py
OpenVision rokid/scripts/prepare_jetson_secrets.sh
```

Legacy direct cloud code still exists only as reference:

```text
legacy_quarantine/2026-04-29/rokidjetson/backend_mvp/app/openai_realtime_skills.py
legacy_quarantine/2026-04-29/rokidjetson/backend_mvp/app/voice_realtime_transcription_client.py
legacy_quarantine/2026-04-29/rokidjetson/backend_mvp/app/vision_skill_runtime.py
```

## Current HUD Output

Active V2:

```text
OpenVision rokid/jetson/hud_authority/openvision_jetson/hud_authority.py
OpenVision rokid/jetson/hud_authority/openvision_jetson/hud.py
OpenVision rokid/jetson/agent/openvision_jetson/contracts.py
OpenVision rokid/shared/schemas/hud_scene.schema.json
```

Legacy Android rendering reference:

```text
legacy_quarantine/2026-04-29/RokidVideoStream/app/src/main/java/com/example/cxrservicedemo/videostream/Rv101HudRenderer.kt
```

## Current Logging / Session / Replay

Active V2:

```text
event_store.py           in-memory trace events
session_store.py         in-memory sessions
session_replay.py        in-memory replay bundle and scorecard skeleton
```

API:

```text
GET /api/events
GET /api/sessions
GET /api/replay
GET /api/replay/{session_id}
GET /api/scorecard
GET /api/scorecard/{session_id}
```

This is still a skeleton. Durable disk replay, retention policy, and privacy controls are future work.

## Primitive Status

Perception graph:

```text
exists: OpenVision rokid/jetson/perception/openvision_jetson/perception_graph.py
status: schema-aligned snapshots with zones, frame dimensions, object ages, and recent temporal continuity
```

Skill manifest / registry:

```text
exists: skills/manifests/*.json + skill_registry.py
status: manifest-driven registry with executor still mapped by known skill names
```

Cloud gateway:

```text
exists: OpenVision rokid/jetson/cloud_gateway/openvision_jetson/cloud_gateway.py
status: typed evidence/result validation, privacy gate, request budget, provider fallback
docs exist: docs/openvision/09_CLOUD_ESCALATION_GATEWAY.md
schemas exist: cloud_evidence_bundle.schema.md, cloud_result.schema.md
```

Cloud realtime tool/media/display contracts:

```text
docs exist: 00_CODEX_START_HERE_CLOUD_REALTIME_V2.md,
            17_MEDIA_ACTIVATION_POLICY.md through 26_NEXT_PRS_CLOUD_ORCHESTRATED_V2.md
schemas exist: realtime_tool_call.schema.md, media_command.schema.md, display_command.schema.md
status: docs installed; runtime models/dispatch still need implementation
```

Scorecard / replay:

```text
exists as in-memory skeleton: session_replay.py
missing: durable replay files, CLI tools, dataset builder, privacy retention settings
```

Shared JSON schemas:

```text
exists: session, HUD scene, skill call, skill manifest, perception graph,
        cloud evidence bundle, cloud result, memory event, session replay,
        session scorecard
docs also define: realtime tool call, media command, display command
status: Phase 0 schema foundation is now concrete enough for runtime tests
```

## Highest Current Risks

1. V2 runtime is still thinner than the product docs.
2. Typed RealtimeToolCall/ToolResult/ToolError models and the first JetsonToolServer skill-tool path now exist.
3. Media/display command schemas exist, but runtime adapters are not implemented yet.
4. Skill executor is not yet fully plugin/runtime-dispatched by manifest/tool name.
5. Clean V2 Android app is not buildable.
6. YOLO26 integration is adapter-only and must stay separate from Ring.
7. Replay/scorecard is in-memory only, although its schema surface now exists.
8. Ops Console can drift into debug bloat if not kept schema-backed.
9. Legacy dirty files can confuse future agents.
10. No real RV101 signoff log exists for the clean V2 Android module yet.

## Recommended Next PRs

1. `feat: enforce JetsonToolServer timeout privacy budget policy`
2. `feat: implement MediaCommand runtime gateway`
3. `feat: adapt DisplayCommand to HUD scene protocol`
