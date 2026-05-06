# Schema — Display Command

## Purpose

A typed command from Jetson to Rokid describing what to render.

## Base shape

```json
{
  "display_id": "disp_123",
  "session_id": "sess_abc",
  "type": "text_hud",
  "priority": "normal",
  "duration_ms": 1800,
  "payload": {}
}
```

## Display types

- `text_hud`
- `warning_hud`
- `object_card`
- `thumbnail_card`
- `full_image`
- `live_overlay`
- `debug_overlay`
- `clear`

## Rules

- Display payload must be validated before sending to Rokid.
- Product HUD text should be short.
- Debug overlay must be disabled in product mode unless explicitly requested.
- Display commands should be logged into the session scorecard.
