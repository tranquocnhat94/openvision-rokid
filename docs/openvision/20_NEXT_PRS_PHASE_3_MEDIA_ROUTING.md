# 20 — Next PRs for Phase 3 + Media Routing

Current project state:

```text
Phase 0 docs/schema foundation: mostly complete
Phase 1 stream/audio/HUD baseline: mostly complete
Phase 2 perception graph MVP: strong MVP
Phase 3 skill runtime + Vietnamese voice router: partial
Phase 4 practical skills: early
Phase 5 cloud gateway: skeleton
```

The next work should not start Reality Radar or memory. It should harden the typed skill path and media activation policy.

## Immediate step: commit current HUD patch

There are currently modified files:

```text
realtime_manager.py
test_realtime_manager.py
```

This patch fixes text HUD when voice realtime is enabled. Commit it before larger changes.

Suggested commit:

```bash
git add path/to/realtime_manager.py path/to/test_realtime_manager.py
git commit -m "fix: preserve text HUD output during realtime voice"
```

## PR 3.1 — Skill manifest validation hardening

Goal:

```text
Every skill declares what it needs and what it may output.
```

Add/ensure fields:

```yaml
id:
version:
description:
inputs:
outputs:
local_first:
cloud_allowed:
memory_allowed:
latency_budget_ms:
media_requirements:
  voice:
  visual:
  max_duration_ms:
  preferred_fps:
  preferred_resolution:
  requires_user_activation:
```

Acceptance:

```text
- invalid manifests fail tests
- missing media_requirements gets safe defaults
- all existing skills pass validation
- no runtime behavior change except stricter validation
```

## PR 3.2 — Runtime dispatch map

Goal:

```text
All skills execute through one typed dispatch path.
```

Canonical flow:

```text
Transcript/Event
  -> IntentCandidate
  -> SkillRequest
  -> SkillExecutor
  -> SkillResult
  -> HudScene
```

Add or strengthen:

```text
dispatch_map
Vietnamese phrase patterns
skill capability aliases
typed request/result models
schema validation at runtime boundaries
non-blocking execution
timeout per skill
```

Acceptance:

```text
- count_people/query_scene/search_targets/select_target go through same typed path
- unknown command returns safe HUD answer
- no skill directly writes HUD outside hud authority
- tests cover Vietnamese commands
```

## PR 3.3 — Media requirements integration

Goal:

```text
Skill runtime can decide media activation, but does not implement Android app yet.
```

Add:

```text
MediaRequirement model
MediaActivationPlan
MediaCommand skeleton/schema
scorecard media activation fields
```

Example:

```json
{
  "skill_id": "text_reader",
  "voice": "command",
  "visual": "snapshot",
  "reason": "skill_manifest",
  "max_duration_ms": 1000
}
```

Acceptance:

```text
- text_reader requires snapshot
- target_finder can request live_video
- object_counter can request snapshot or burst
- scene_describe can request snapshot
- no camera is assumed always on
```

## PR 3.4 — Cloud gateway evidence bundle integration

Goal:

```text
needs_cloud goes through cloud_gateway with evidence_bundle.
```

Do not build heavy cloud visual reasoning yet. Build the path.

Acceptance:

```text
- skills cannot call cloud directly
- gateway has timeout/rate limit hooks
- evidence bundle includes graph/keyframe/crop refs
- tests use mocked cloud provider
```

## PR 3.5 — Rokid app contract scaffolding

Goal:

```text
Prepare for app without backend rewrite.
```

Add:

```text
schemas/media_command.schema.json
schemas/media_event.schema.json
docs/openvision/18_ROKID_APP_RUNTIME_CONTRACT.md
simulator support for snapshot/live/voice events if not present
```

Do not implement full Android app in this PR.

## PR 3.6 — Android/Rokid MVP app

Only after PR 3.1-3.5.

Minimum app:

```text
- connect to Jetson
- heartbeat
- render hud_scene text
- touchpad/button starts voice command
- capture snapshot on command
- live video on command with timeout
```

Not included:

```text
- always-on video
- direct cloud AI
- complex UI
- memory
- Reality Radar
```

## Phase 4 can begin when

```text
- manifests are strict
- dispatch is typed
- media activation plan exists
- cloud gateway path exists
- HUD authority remains centralized
- scorecard sees all voice/media/skill/HUD events
```
