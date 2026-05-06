# Schema Spec — cloud_result.v1

## Purpose

Structured cloud response that Jetson can validate and convert into HUD, voice, or memory output.

## Example

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

## Required fields

```text
schema_version
status
answer_short
confidence
```

## Validation rule

Reject or fallback when:

```text
answer_short is too long
confidence missing
hud_scene invalid
status not recognized
```
