# 07 — Perception Graph

The perception graph is the shared world state for all skills.

## Why it exists

Without a perception graph, each skill will run its own detector, store its own objects, and invent its own format. That does not scale.

The perception graph lets all skills ask:

```text
What is visible now?
What has been visible recently?
Where is it?
How confident are we?
What evidence exists?
```

## Minimal perception graph v1

A minimal graph can be a JSON object updated every frame or every detection cycle.

Example:

```json
{
  "schema_version": "perception_graph.v1",
  "session_id": "sess_001",
  "timestamp_ms": 1710000000000,
  "frame_id": "frame_1234",
  "scene": {
    "label": "street",
    "confidence": 0.64
  },
  "objects": [
    {
      "id": "track_person_3",
      "class": "person",
      "confidence": 0.91,
      "bbox_xyxy": [120, 80, 310, 520],
      "zone": "left_front",
      "track_age_ms": 4200,
      "last_seen_ms": 30,
      "attributes": {
        "shirt_color": {"value": "yellow", "confidence": 0.72},
        "has_backpack": {"value": true, "confidence": 0.51}
      },
      "evidence": {
        "crop_ref": "runtime/crops/sess_001/person_3_latest.jpg",
        "frame_ref": "runtime/frames/sess_001/frame_1234.jpg"
      }
    }
  ],
  "texts": [
    {
      "id": "text_1",
      "content": "EXIT",
      "confidence": 0.86,
      "bbox_xyxy": [400, 100, 510, 150],
      "zone": "right_front"
    }
  ],
  "audio": {
    "last_transcript": "tìm người áo vàng",
    "last_transcript_confidence": 0.78
  },
  "risks": [],
  "metrics": {
    "detector_fps": 12.5,
    "frame_latency_ms": 85
  }
}
```

## Required fields

Perception graph should include:

```text
schema_version
session_id
timestamp_ms
frame_id
objects
texts
risks
metrics
```

Each object should include:

```text
id
class
confidence
bbox_xyxy
zone
track_age_ms
last_seen_ms
attributes
evidence
```

## Zones

Use coarse zones, not exact AR world coordinates at first:

```text
left
left_front
front
right_front
right
near
far
unknown
```

This is enough for useful HUD hints.

## Attribute estimation

Start simple:

```text
shirt_color
object_color
has_backpack
motion_direction
is_stationary
relative_size
```

Do not overbuild attributes before target_finder works.

## Evidence references

The graph should reference saved evidence, not embed huge images.

Use:

```text
frame_ref
crop_ref
thumbnail_ref
clip_ref, optional
```

## Update frequency

Recommended:

```text
detector: run at stable FPS based on Jetson performance
tracker: update every frame if possible
OCR: on-demand or low-frequency
cloud evidence: only on escalation
```

## Graph retention

Keep:

```text
current graph
recent N seconds of graph snapshots
recent track history
recent keyframes/crops
```

Do not keep indefinite visual memory without explicit policy.

## Perception graph acceptance criteria

The perception graph MVP is done when:

```text
at least one detector feeds objects into graph
objects have stable IDs when tracking is enabled
zones are computed
graph can be serialized to JSON
skills can read graph without accessing detector internals
dashboard or logs can display graph snapshot
```
