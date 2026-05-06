# Schema Spec — perception_graph.v1

## Purpose

Shared world state for all skills.

Skills must read the perception graph instead of directly reading detector internals.

## Top-level fields

```json
{
  "schema_version": "perception_graph.v1",
  "session_id": "string",
  "timestamp_ms": 0,
  "frame_id": "string",
  "scene": {},
  "objects": [],
  "texts": [],
  "audio": {},
  "risks": [],
  "metrics": {}
}
```

## Object fields

```json
{
  "id": "track_person_3",
  "class": "person",
  "confidence": 0.91,
  "bbox_xyxy": [120, 80, 310, 520],
  "zone": "left_front",
  "track_age_ms": 4200,
  "last_seen_ms": 30,
  "attributes": {},
  "evidence": {}
}
```

## Text fields

```json
{
  "id": "text_1",
  "content": "EXIT",
  "confidence": 0.86,
  "bbox_xyxy": [400, 100, 510, 150],
  "zone": "right_front"
}
```

## Allowed zones

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

## Required implementation tests

```text
graph serializes to JSON
zone computation works
object with bbox becomes zone
missing optional fields do not crash skill runtime
```
