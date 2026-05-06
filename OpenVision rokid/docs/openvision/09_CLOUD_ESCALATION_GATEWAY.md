# 09 — Cloud Escalation Gateway

The cloud gateway is the only place skills should call cloud AI.

## Why centralized gateway matters

If each skill calls cloud independently, the repo will get:

```text
duplicate API logic
inconsistent prompts
unbounded costs
privacy leaks
hard-to-debug latency
no shared fallback behavior
```

Centralize cloud calls through one gateway.

## Gateway responsibilities

The gateway should:

```text
accept evidence_bundle
check privacy policy
check cloud budget
select model/tool path
format prompt/request
validate structured response
return cloud_result
log latency/cost/failure
```

The current V2 runtime also uses the gateway validators at the skill/tool
boundary. Any skill result with `status: "needs_cloud"` must include all three
objects before Cloud Realtime receives it:

```text
cloud_evidence_bundle
cloud_gateway
cloud_result
```

If any object is missing or schema-invalid, SkillExecutor/JetsonToolServer must
return `invalid_cloud_escalation` instead of leaking an ambiguous untyped result
to cloud.

## OpenAI Responses verifier

The active Jetson backend can enable an OpenAI Responses visual verifier behind
CloudGateway:

```text
OPENVISION_CLOUD_VERIFY_ENABLED=1
OPENVISION_CLOUD_VERIFY_MODEL=gpt-4.1-mini
OPENVISION_CLOUD_VERIFY_IMAGE_DETAIL=low
```

This provider:

```text
uses only evidence bundles created by Jetson
converts local preview refs into data URLs inside Jetson
requests structured cloud_result.v1 JSON
keeps /api/preview private; it does not require public frame URLs
stays disabled unless explicitly enabled in Jetson environment config
```

Use `low` detail for the MVP latency/cost baseline. Increase to `high` only for
skills that need finer visual attributes or OCR and are backed by replay tests.

## Evidence bundle v1

Example:

```json
{
  "schema_version": "cloud_evidence_bundle.v1",
  "bundle_id": "bundle_001",
  "session_id": "sess_001",
  "skill_id": "target_finder",
  "user_query": "tìm người áo vàng đeo balo",
  "created_at": "2026-04-25T00:00:00.000+00:00",
  "local_summary": {
    "scene": "street",
    "candidate_count": 3,
    "uncertainty": "shirt color and backpack ambiguous"
  },
  "frame_refs": [],
  "crop_refs": ["runtime/crops/person_3.jpg"],
  "candidates": [
    {
      "candidate_id": "track_person_3",
      "class": "person",
      "zone": "left_front",
      "confidence": 0.74,
      "crop_ref": "runtime/crops/person_3.jpg",
      "attributes": {
        "shirt_color": "yellow",
        "has_backpack": "maybe"
      }
    }
  ],
  "requested_output": {
    "format": "json",
    "max_answer_chars": 60,
    "hud_allowed": true
  },
  "privacy": {
    "contains_face": true,
    "allow_cloud": true,
    "store_result": false,
    "privacy_level": "medium"
  }
}
```

## Cloud result v1

Example:

```json
{
  "schema_version": "cloud_result.v1",
  "status": "ok",
  "answer_short": "Áo vàng · bên trái",
  "answer_long": "Ứng viên phù hợp nhất là người ở phía trước bên trái.",
  "confidence": 0.82,
  "selected_candidate_id": "track_person_3",
  "hud_scene": {
    "schema_version": "hud_scene.v1",
    "duration_ms": 2200,
    "components": [
      {
        "type": "answer_strip",
        "text": "Áo vàng · bên trái",
        "position": "lower_safe",
        "duration_ms": 2200
      }
    ]
  },
  "safety_flags": [],
  "memory_event": null
}
```

## Escalation policy

Escalate when:

```text
skill manifest allows cloud
privacy policy allows cloud
network is available
cloud budget allows call
local confidence is low
local candidates tie
query requires web/file/tool reasoning
user explicitly asks for deep analysis
```

Do not escalate when:

```text
privacy blocks it
user is in local-only mode
local confidence is high
query is simple counting/detection
network is unavailable
cloud budget is exceeded
```

## Fallback behavior

Cloud unavailable:

```text
return best local answer with lower confidence
show short HUD: "Không có cloud · dùng kết quả local"
log failure
```

Privacy block:

```text
show short HUD: "Không gửi cloud"
use local-only path
```

Timeout:

```text
show progress only briefly
return local fallback
cancel stale cloud response if user context changed
```

## Gateway acceptance criteria

The gateway is acceptable when:

```text
all cloud calls go through one module
skills do not directly call cloud APIs
privacy and budget checks exist
structured response validation exists
needs_cloud results cannot leave Jetson without a valid evidence bundle/result
OpenAI verifier calls are centralized and feature-flagged
latency/cost/failure logs exist
fallback behavior exists
```
