# 23 — Jetson Skill Tool Server Contract

## Purpose

Cloud realtime AI decides what to do. Jetson executes typed skills and media/display actions safely.

This document defines the Jetson tool server contract that cloud realtime uses.

## Required principle

Cloud may orchestrate, but Jetson validates and executes.

No tool call may bypass:

- skill manifest,
- tool permissions,
- media budget,
- privacy gate,
- schema validation,
- scorecard logging,
- and display policy.

## Tool families

### 1. Perception tools

Examples:

```text
perception.snapshot_analyze
perception.detect_objects
perception.track_targets
perception.query_graph
perception.get_current_graph
```

### 2. Media capture tools

Examples:

```text
media.capture_snapshot
media.capture_burst_clip
media.start_live_video
media.stop_live_video
```

### 3. Skill tools

Examples:

```text
skill.scene_describe
skill.target_finder
skill.text_reader
skill.object_counter
skill.select_target
```

### 4. Display tools

Examples:

```text
display.show_text_hud
display.show_object_card
display.show_thumbnail
display.show_full_image
display.show_live_overlay
display.clear
```

### 5. Session tools

Examples:

```text
session.get_status
session.set_mode
session.end_realtime
session.get_scorecard_snapshot
```

## Tool call shape

```json
{
  "tool_call_id": "call_123",
  "session_id": "sess_abc",
  "source": "cloud_realtime",
  "tool_name": "skill.target_finder",
  "arguments": {
    "query": "người áo vàng đeo balo",
    "media_mode": "live_video",
    "max_duration_ms": 15000
  },
  "requested_at_ms": 1234567890
}
```

## Tool result shape

```json
{
  "tool_call_id": "call_123",
  "session_id": "sess_abc",
  "tool_name": "skill.target_finder",
  "status": "ok",
  "result": {
    "summary": "Possible match on the left front.",
    "confidence": 0.78,
    "display": {
      "type": "target_hint",
      "text": "Áo vàng · bên trái",
      "anchor": "left_front",
      "duration_ms": 1800
    }
  },
  "metrics": {
    "tool_latency_ms": 820,
    "media_latency_ms": 180,
    "cloud_followup_needed": false
  }
}
```

## Cloud escalation result shape

If a skill cannot safely answer locally and returns `status: "needs_cloud"`,
Jetson must include the typed evidence/result contract in the skill result:

Abbreviated example:

```json
{
  "tool_call_id": "call_123",
  "session_id": "sess_abc",
  "tool_name": "skill.target_finder",
  "status": "needs_cloud",
  "result": {
    "skill_call_id": "skill_789",
    "name": "search_targets",
    "status": "needs_cloud",
    "result": {
      "summary": "Cloud attribute verification required.",
      "cloud_evidence_bundle": {"schema_version": "cloud_evidence_bundle.v1"},
      "cloud_gateway": {
        "status": "error",
        "bundle_id": "bundle_123",
        "latency_ms": 12,
        "cloud_result": {"schema_version": "cloud_result.v1"},
        "validation_errors": []
      },
      "cloud_result": {"schema_version": "cloud_result.v1"}
    }
  }
}
```

`JetsonToolServer` must reject `needs_cloud` outputs that omit or violate this
contract. This keeps Cloud Realtime as orchestrator, while Jetson remains the
privacy, budget, schema, and evidence authority.

## Error result shape

```json
{
  "tool_call_id": "call_123",
  "session_id": "sess_abc",
  "tool_name": "media.start_live_video",
  "status": "error",
  "error": {
    "code": "media_budget_exceeded",
    "message": "Requested live video duration exceeds budget.",
    "safe_fallback": "snapshot"
  }
}
```

## Manifest binding

Each tool must map to one of:

- a registered skill manifest,
- a registered media capability,
- a registered display capability,
- or a system/session tool.

Codex should avoid ad-hoc tool execution.

## Tool execution pipeline

```text
Realtime tool call
  -> parse JSON
  -> validate tool schema
  -> validate session state
  -> permission/media/privacy check
  -> execute through registry
  -> produce typed result
  -> update scorecard
  -> send result back to cloud
  -> optionally send display command to Rokid
```

## Important rule

Cloud can chain tools, but Jetson should enforce a maximum tool chain budget per session turn.

Example defaults:

```yaml
max_tool_calls_per_turn: 6
max_live_video_duration_ms: 30000
max_burst_clip_duration_ms: 3000
max_snapshot_per_turn: 3
max_display_updates_per_turn: 5
```

## Why this matters

Without this contract, cloud realtime will become powerful but chaotic.

With this contract, the system becomes an extensible skill OS:

```text
cloud plans -> Jetson validates -> skills execute -> display responds
```
