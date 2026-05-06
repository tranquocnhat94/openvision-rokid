# 10 — Reality Radar MVP

Reality Radar is an ambitious flagship skill for V2, not the whole product.
OpenVision remains an AI Skill OS where Radar, scene description, counting,
OCR, known-person reminders, memory, and task coaching share the same runtime.

Radar should never become a shortcut around the platform. It must use the same
skill registry, perception graph, media commands, display/HUD commands, cloud
evidence gateway, replay, privacy policy, and scorecards as every other skill.

## Product idea

The user says a natural-language target:

```text
"tìm người áo vàng đeo balo"
"tìm cái tua vít màu đỏ"
"tìm biển exit"
"tìm laptop của tôi"
```

The system finds likely matches in the current field of view and shows a tiny direction/target cue.

## Why this is the right ambitious feature

It feels magical, but only because it combines reusable platform components:

```text
stable video stream
voice command router
local detection
tracking
simple attributes
perception graph
cloud verification when uncertain
HUD direction hint
```

No full AR world model is required for MVP.
No Radar-specific product endpoint or separate orchestrator is allowed for MVP.

## MVP scope

Reality Radar MVP should support:

```text
person by clothing color
common object by class
text target from OCR
direction hint
target marker when bbox is available
cloud verification for ambiguous candidates
```

Do not initially support:

```text
full 3D localization
multi-room search
face recognition by default
continuous identity tracking without consent
large open-world object ontology
```

## User flow

Example:

```text
User: "tìm người áo vàng"
Jetson: parses target query
Perception graph: finds person tracks
Attribute estimator: checks yellow clothing candidates
If one candidate high-confidence: local answer
If multiple candidates: cloud verifier checks crops
HUD: "Áo vàng · bên trái"
Rokid: renders direction hint/marker
```

## Core modules

Reality Radar depends on shared Skill OS modules:

```text
perception_graph
skill_runtime
target_finder skill
cloud_gateway
hud_scene
session metrics
```

Anything built here should make other skills better too. Candidate ranking,
target locks, crop evidence, HUD direction hints, and replay gates should be
reusable by `target_finder`, `person_info`, object search, OCR search, memory,
and task-coaching skills.

## Target query representation

Example:

```json
{
  "schema_version": "target_query.v1",
  "raw_text": "tìm người áo vàng đeo balo",
  "target_class": "person",
  "attributes": {
    "shirt_color": "yellow",
    "has_backpack": true
  },
  "spatial_constraint": null,
  "confidence": 0.76
}
```

## Candidate ranking

Rank candidates by:

```text
class match
attribute match
track stability
bbox quality
recency
zone relevance
cloud verification confidence, if used
```

## HUD output

Preferred HUD:

```json
{
  "schema_version": "hud_scene.v1",
  "duration_ms": 2200,
  "components": [
    {
      "type": "answer_strip",
      "text": "Áo vàng · bên trái",
      "position": "lower_safe",
      "duration_ms": 2200
    },
    {
      "type": "direction_hint",
      "anchor": "left_front",
      "text": "bên trái",
      "duration_ms": 2200
    }
  ]
}
```

## Reality Radar phases

### Phase A: local target finder

```text
parse query
match class and color
return direction hint
```

### Phase B: tracker integration

```text
stable track ids
maintain target lock
update direction while user moves
```

### Phase C: cloud verifier

```text
send top 3 crops
return best candidate
emit confidence
```

### Phase D: memory integration

```text
"nhắc tôi nếu thấy cái này"
"tôi để chìa khóa ở đâu"
```

## Acceptance criteria

Reality Radar MVP is acceptable when:

```text
Vietnamese target queries route to target_finder
local candidates are produced from perception graph
HUD shows direction within 2 seconds for simple cases
cloud escalation happens only when uncertain
session logs show ranking reasons
failure case says "không thấy" instead of hallucinating
all behavior is routed through shared typed skill/media/display/runtime paths
```
