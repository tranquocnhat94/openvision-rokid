# 08 — HUD Scene Protocol

The HUD scene protocol is how Jetson tells Rokid what to display.

## Principle

Rokid should render compact scenes. Rokid should not decide product logic.

Jetson outputs:

```text
small versioned HUD JSON
```

Rokid renders:

```text
short text
markers
status chips
direction hints
alerts
```

## Minimal HUD scene v1

Example:

```json
{
  "schema_version": "hud_scene.v1",
  "scene_id": "hud_001",
  "timestamp_ms": 1710000000000,
  "duration_ms": 2200,
  "priority": "normal",
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
      "text": "left",
      "duration_ms": 2200
    }
  ]
}
```

## Allowed components

### status_chip

For persistent state:

```json
{
  "type": "status_chip",
  "text": "Listening",
  "position": "top_right",
  "state": "active"
}
```

### answer_strip

For short answers:

```json
{
  "type": "answer_strip",
  "text": "Có 3 xe phía trước",
  "position": "lower_safe",
  "duration_ms": 1800
}
```

### direction_hint

For target direction:

```json
{
  "type": "direction_hint",
  "anchor": "right_front",
  "text": "bên phải",
  "duration_ms": 2000
}
```

### target_marker

For a visual candidate:

```json
{
  "type": "target_marker",
  "target_id": "track_person_3",
  "bbox_xyxy": [120, 80, 310, 520],
  "label": "match",
  "confidence": 0.82,
  "duration_ms": 1800
}
```

### alert_burst

For urgent cues:

```json
{
  "type": "alert_burst",
  "text": "Chú ý phía trước",
  "severity": "medium",
  "duration_ms": 1600
}
```

### progress_hint

For slow cloud tasks:

```json
{
  "type": "progress_hint",
  "text": "Đang kiểm tra...",
  "duration_ms": 1200
}
```

## HUD design rules

- Keep center mostly clear.
- Prefer lower-safe-zone for text.
- Do not show long paragraphs.
- Default answer length should be under 50 characters.
- Default duration should be 1.5-3 seconds.
- Use priority levels:

```text
low
normal
high
urgent
```

- Unknown components must be ignored safely.
- Invalid scenes must fail soft.

## Anti-patterns

Avoid:

```text
full-screen text cards
scrolling lists
dense debug panels on glasses
multiple competing overlays
mode menus
raw JSON displayed to user
```

Debug data belongs in dashboard, not HUD.

## HUD acceptance criteria

The protocol is acceptable when:

```text
backend validates or constructs schema safely
glasses render known components
glasses ignore unknown components
all skills use shared HUD scene output
HUD latency is measured
no skill writes custom glasses UI directly
```
