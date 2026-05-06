# 06 — Skill Runtime and Registry

V2 must be skill-based. A skill is not just an endpoint. A skill is a declared capability that consumes shared context and emits structured results.

## Why skill runtime matters

Without a skill runtime, the repo will drift into isolated demos:

```text
/detect endpoint
/read endpoint
/ask endpoint
/radar endpoint
```

Each demo will duplicate frame selection, cloud calls, HUD rendering, and logging.

The correct design is:

```text
shared perception graph
shared skill registry
shared cloud gateway
shared HUD scene protocol
shared metrics
```

## Skill lifecycle

A skill can be:

```text
idle
eligible
active
waiting_for_cloud
emitting_hud
completed
failed_soft
```

## Skill manifest

Each skill must define a manifest.

Example:

```yaml
schema_version: skill_manifest.v1
id: target_finder
name: Target Finder
description: Find a person/object in the user's current field of view.
latency_class: interactive
local_first: true
cloud_allowed: true
privacy_level: high
inputs:
  - transcript_event
  - perception_graph
  - keyframe_candidates
outputs:
  - hud_scene
  - voice_reply
  - memory_event_optional
activation_phrases_vi:
  - tìm người áo vàng
  - tìm cái balo
  - tìm vật này
acceptance_tests:
  - route Vietnamese target query to target_finder
  - return local direction when one candidate is high confidence
  - escalate to cloud when multiple candidates tie
failure_modes:
  - no target found
  - cloud unavailable
  - privacy block
```

## Skill interface

Preferred interface:

```python
class Skill:
    id: str
    manifest: SkillManifest

    def can_handle(self, context: SkillContext) -> float:
        \"\"\"Return eligibility score 0.0-1.0.\"\"\"

    def run(self, context: SkillContext) -> SkillResult:
        \"\"\"Run local work and optionally request cloud escalation.\"\"\"
```

## Skill context

Skill context should include:

```text
session_id
user_id or anonymous id
transcript_event
intent_candidate
perception_graph
recent_memory
runtime_config
privacy_policy
cloud_budget
```

## Skill result

Skill result should include:

```text
skill_id
status
answer_short
answer_long optional
confidence
hud_scene
voice_reply optional
cloud_request optional
memory_event optional
metrics
errors
```

## Router behavior

The V2 router is Cloud Realtime plus Jetson typed validation. Jetson may still run local routing in tests/fallbacks, but the main path should:

```text
receive RealtimeToolCall
validate tool and arguments
validate skill manifest, media requirements, privacy, timeout, and budget
execute through skill/media/display registry
return ToolResult or ToolError
emit typed display/HUD command when needed
log scorecard fields for tool/media/display latency
```

## Vietnamese routing examples

Cloud Realtime should map these Vietnamese intents to typed tools; local tests can mock these tool calls:

```text
"nhìn phía trước có gì" -> scene_describe
"mô tả cảnh này" -> scene_describe
"đếm xe" -> object_counter
"có bao nhiêu người" -> object_counter
"tìm người áo vàng" -> target_finder
"tìm cái balo" -> target_finder
"đọc chữ này" -> text_reader
"biển này ghi gì" -> text_reader
"có gì nguy hiểm không" -> safety_cue
"nhắc tôi nếu thấy người giao hàng" -> memory_recall / watcher placeholder
```

## First four skills

### 1. scene_describe

Output:

```text
short scene summary
important objects
optional cloud escalation for rich description
```

### 2. target_finder

Output:

```text
direction hint
target marker
confidence
```

### 3. text_reader

Output:

```text
read text
confidence
location hint
```

### 4. object_counter

Output:

```text
count
object type
zone
```

## Skill runtime acceptance criteria

The skill runtime is acceptable when:

```text
there is a manifest format
there is a registry
there are at least 4 sample skills registered
Vietnamese commands route to expected skills
skills output HUD scenes through shared schema
cloud escalation is centralized
metrics are logged per skill run
```
