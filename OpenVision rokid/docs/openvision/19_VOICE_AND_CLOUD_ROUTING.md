# 19 — Voice and Cloud Routing: Cloud-Realtime Orchestrated V2

This document supersedes older Jetson-first/local-STT-first guidance.

## Decision

For V2, voice should be orchestrated by cloud realtime AI, not by local STT as the default brain.

Canonical V2 route:

```text
Rokid voice stream
  -> Cloud Realtime AI
  -> Jetson typed tools/skills
  -> Rokid display
```

MVP practical route:

```text
Rokid voice stream
  -> Jetson realtime bridge
  -> Cloud Realtime AI
  -> Jetson typed tools/skills
  -> Rokid display
```

The MVP route still follows the V2 philosophy because Jetson only relays/executes; it does not become the local STT/router brain.

## What is not allowed as default V2 path

```text
Rokid -> local STT -> Jetson Vietnamese router -> cloud fallback
```

This resembles V1 and should remain disabled or experimental unless later evidence proves local STT and local language intelligence are strong enough.

## Responsibilities

### Cloud realtime AI

Cloud realtime owns:

```text
conversation
Vietnamese understanding
skill/tool choreography
multi-step decisions
when to ask for snapshot/clip/live video
when to ask Jetson to run perception/search/OCR/counting/display tools
final user-facing answer planning
```

### Jetson

Jetson owns:

```text
secure realtime bridge for MVP
typed tool server
skill executor
YOLO26/perception graph/tracker/focus IDs
media command gateway to Rokid
display command gateway to Rokid
privacy/media budget validation
scorecard/logging
```

### Rokid

Rokid owns:

```text
low-power mic stream
camera capture only on command
snapshot/clip/live video transport to Jetson
render typed display commands
heartbeat/status
```

## Voice realtime policy

The RV101 product app may start voice realtime automatically when the app opens
and the user is in the OpenVision session. This is not the same as background
always-on listening: the app must show an active state, stay foreground/session
bound, and stop on app exit, explicit stop, idle/session timeout, or Jetson/cloud
policy.

Recommended stages:

```text
Stage 1: app-open conversation_realtime with Cloud server_vad
Stage 2: wake/gesture/Hey Vision opens conversation_realtime after standby
Stage 3: push-to-talk manual-turn remains debug/noisy fallback
Stage 4: mission mode for longer guided tasks, with visible status and auto-stop
```

Voice realtime may be the primary interaction channel, but it still needs session budget, idle timeout, and clear stop behavior.

Current RV101 app requirement:

```text
conversation_realtime is the default app-open product voice mode.
Cloud Realtime server_vad detects natural turns.
Assistant audio is negotiated through session_accept voiceOutput.
The app does not start Realtime through REST bootstrap or local VAD.
Jetson does not use audio gate as the semantic turn detector.
manual-turn is debug/noisy fallback only.
```

Cloud `server_vad` is the correct V2 direction for live conversation once the
app session is active. Opening the app may start the conversation session; the
user should not have to close every turn. Cloud Realtime can end the conversation
through typed control/session policy, after which Jetson tells the glasses to
stop streaming.

Future battery-optimized product flow:

```text
standby / low-power wake listener
  -> "Hey Vision" or equivalent local wake trigger
  -> RV101 starts foreground mic stream to Jetson
  -> Jetson bridges audio to Cloud Realtime with turn_policy=server_vad
  -> Cloud Realtime handles conversation and typed tools
  -> Cloud/Jetson emits session stop when done
  -> RV101 stops mic stream and returns to standby
```

The wake trigger may run on the glasses only as lightweight activation. It must
not become local STT, local intent routing, or a second assistant brain.

## Visual media policy

Voice does not imply video.

Cloud realtime can ask Jetson for:

```text
media.capture_snapshot
media.capture_burst_clip
media.start_live_video
media.stop_live_video
```

Jetson then commands Rokid to capture the required media and returns evidence/results.

Camera is off by default.
Live video is only for explicit live skills with timeout and budget.

## Why visual media should go to Jetson first

Visual data should normally flow:

```text
Rokid visual media -> Jetson -> local perception/crop/evidence -> cloud if needed
```

Reasons:

```text
Jetson keeps perception graph coherent
Jetson can run YOLO26/tracking/focus IDs
Jetson can crop/filter before cloud
Jetson can enforce privacy and media budgets
Jetson can scorecard latency and failures
```

## Required tool boundary

Cloud must call typed tools, not arbitrary endpoints.

```text
RealtimeToolCall -> JetsonToolServer -> ToolResult/ToolError
```

Any cloud request that would activate camera, memory, display, or long-running skill must pass Jetson validation.
