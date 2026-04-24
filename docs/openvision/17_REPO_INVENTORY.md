# 17 — Current Repo Inventory

Updated: 2026-04-25

This inventory captures the current V2 repo shape so contributors do not rediscover old paths or mistake legacy code for the product path.

## Active V2 Product Path

```text
glasses/                RV101 thin-client contract docs
iphone_web_simulator/   browser/iPhone harness contract
jetson/                 active Jetson runtime
shared/                 schemas, contracts, fixtures
ops/                    deploy/systemd/env templates
docs/openvision/        V2 architecture guidance pack
```

Public architecture docs:

```text
docs/openvision/
```

## Legacy Reference Paths

These are reference only unless the user explicitly asks to edit them:

```text
RokidVideoStream/          legacy buildable RV101 app
rokidjetson/backend_mvp/   legacy backend MVP
docs/reference/            supporting historical notes
docs/archive/              archived product thinking
rokidjetson/archive/       archived backend plans
```

Do not expand these paths as the active V2 product.

## Current Android / Rokid App

V2 has only the clean glasses contract in:

```text
glasses/
```

The currently buildable Android app remains legacy:

```text
RokidVideoStream/app/src/main/
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
jetson/agent/openvision_jetson/fastapi_app.py
jetson/agent/openvision_jetson/control_plane.py
jetson/media_gateway/openvision_jetson/
jetson/perception/openvision_jetson/
jetson/skills/openvision_jetson/
jetson/hud_authority/openvision_jetson/
jetson/realtime_agent/openvision_jetson/
jetson/simulator_bridge/openvision_jetson/
jetson/lab_fallbacks/openvision_jetson/
```

Legacy backend:

```text
rokidjetson/backend_mvp/app/
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
ops/openvision.env.example
ops/systemd/openvision-jetson.service
scripts/prepare_jetson_secrets.sh
```

Legacy model/runtime scripts:

```text
rokidjetson/backend_mvp/scripts/*phowhisper*
rokidjetson/backend_mvp/scripts/*whisper*
rokidjetson/backend_mvp/scripts/start_backend.sh
```

## Current Cloud API Locations

Active V2 cloud/live AI code:

```text
jetson/realtime_agent/openvision_jetson/realtime_manager.py
```

Secrets load through environment or key file:

```text
jetson/agent/openvision_jetson/settings.py
scripts/prepare_jetson_secrets.sh
```

Legacy direct cloud code still exists only as reference:

```text
rokidjetson/backend_mvp/app/openai_realtime_skills.py
rokidjetson/backend_mvp/app/voice_realtime_transcription_client.py
rokidjetson/backend_mvp/app/vision_skill_runtime.py
```

## Current HUD Output

Active V2:

```text
jetson/hud_authority/openvision_jetson/hud_authority.py
jetson/hud_authority/openvision_jetson/hud.py
jetson/agent/openvision_jetson/contracts.py
shared/schemas/hud_scene.schema.json
```

Legacy Android rendering reference:

```text
RokidVideoStream/app/src/main/java/com/example/cxrservicedemo/videostream/Rv101HudRenderer.kt
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
exists: jetson/perception/openvision_jetson/perception_graph.py
status: latest snapshot per session, not a full temporal graph yet
```

Skill manifest / registry:

```text
exists: skills/manifests/*.json + skill_registry.py
status: manifest-driven registry with executor still mapped by known skill names
```

Cloud gateway:

```text
missing runtime module
docs exist: docs/openvision/09_CLOUD_ESCALATION_GATEWAY.md
schemas exist: cloud_evidence_bundle.schema.md, cloud_result.schema.md
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
status: Phase 0 schema foundation is now concrete enough for runtime tests
```

## Highest Current Risks

1. V2 runtime is still thinner than the product docs.
2. Cloud gateway is not implemented, so Realtime remains the only active cloud path.
3. Perception graph is snapshot-only.
4. Skill executor is not yet plugin/runtime-dispatched by manifest.
5. Clean V2 Android app is not buildable.
6. YOLO26 integration is adapter-only and must stay separate from Ring.
7. Replay/scorecard is in-memory only, although its schema surface now exists.
8. Ops Console can drift into debug bloat if not kept schema-backed.
9. Legacy reference paths can confuse contributors if not clearly labelled.
10. No real RV101 signoff log exists for the clean V2 Android module yet.

## Recommended Next PRs

1. `feat: add cloud evidence gateway runtime`
2. `feat: make perception graph temporal and tracker-aware`
3. `feat: make skill executor dispatch by manifest/runtime adapter`
