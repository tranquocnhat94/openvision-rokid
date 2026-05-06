# Schema Spec — hud_scene.v1

## Purpose

Compact HUD output from Jetson to Rokid.

## Top-level fields

```json
{
  "schema_version": "hud_scene.v1",
  "scene_id": "string",
  "timestamp_ms": 0,
  "duration_ms": 2000,
  "priority": "normal",
  "components": []
}
```

## Component types

```text
status_chip
answer_strip
direction_hint
target_marker
alert_burst
progress_hint
tiny_gallery
```

## Component examples

```json
{"type":"answer_strip","text":"Có 3 xe phía trước","position":"lower_safe","duration_ms":1800}
```

```json
{"type":"direction_hint","anchor":"left_front","text":"bên trái","duration_ms":2000}
```

```json
{"type":"target_marker","target_id":"track_person_3","bbox_xyxy":[120,80,310,520],"label":"match","confidence":0.82}
```

## Rule

Unknown components must be ignored safely. HUD must not crash the glasses.
