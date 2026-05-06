# Schema — Realtime Tool Call

## Purpose

A typed request from cloud realtime AI to Jetson's tool server.

## Shape

```json
{
  "tool_call_id": "call_123",
  "session_id": "sess_abc",
  "source": "cloud_realtime",
  "tool_name": "skill.target_finder",
  "arguments": {},
  "requested_at_ms": 1234567890
}
```

## Required fields

- `tool_call_id`
- `session_id`
- `source`
- `tool_name`
- `arguments`
- `requested_at_ms`

## Validation rules

- `source` must be `cloud_realtime`, `simulator`, or `test`.
- `tool_name` must exist in the Jetson tool registry.
- `arguments` must validate against the selected tool schema.
- The call must pass session policy, privacy policy, and media budget checks.
