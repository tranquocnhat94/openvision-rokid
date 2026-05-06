# Schema — Media Command

## Purpose

A typed command from Jetson to Rokid requesting camera/audio/display-related media capture.

## Shape

```json
{
  "command_id": "media_cmd_123",
  "session_id": "sess_abc",
  "source_tool_call_id": "call_456",
  "mode": "snapshot",
  "reason": "text_reader requires current image",
  "constraints": {
    "max_duration_ms": 1500,
    "preferred_resolution": "1280x720",
    "preferred_fps": null,
    "max_bytes": 1500000
  }
}
```

## Allowed modes

- `none`
- `snapshot`
- `burst_clip`
- `live_video`

## Rules

- `live_video` requires explicit timeout.
- `burst_clip` requires duration budget.
- `snapshot` should be preferred for most visual questions.
- Camera must be off by default when no command is active.
