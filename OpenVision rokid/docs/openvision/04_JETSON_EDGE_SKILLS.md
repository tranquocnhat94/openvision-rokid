# 04 — Jetson Edge Skills

The Jetson Orin Nano Super should be the realtime local brain. It should do the things that need low latency, continuous awareness, privacy, and reduced cloud cost.

## Jetson should do always-on or near-always-on work

### 1. Object detection

Purpose:

```text
identify people, vehicles, objects, tools, signs, common scene elements
```

Best use:

```text
run every N frames
feed detection results into perception graph
track objects across time
```

Do not:

```text
run huge models every frame just to improve one rare skill
```

### 2. Tracking

Purpose:

```text
stable object IDs
movement direction
object persistence
Reality Radar target locking
counting across frames
```

Outputs:

```text
track_id
track_age
last_seen_ms
motion_vector
zone
stability_score
```

### 3. Lightweight OCR

Purpose:

```text
read signs, labels, numbers, short text
```

Run policy:

```text
on-demand by voice
periodic low-frequency scan for obvious text
only escalate to cloud if local OCR confidence is low
```

### 4. VAD and audio gating

Purpose:

```text
avoid sending silence to STT
improve command latency
reduce cloud calls
```

Metrics:

```text
audio RMS
speech probability
segment duration
silence ratio
STT call count
```

### 5. Local command router

Purpose:

```text
route simple Vietnamese commands quickly
```

Examples:

```text
"đếm xe"
"tìm người áo vàng"
"đọc chữ này"
"mô tả cảnh"
"có gì nguy hiểm không"
```

### 6. HUD authority

Purpose:

```text
generate small HUD scenes from skill results
```

Jetson should output:

```text
versioned JSON
short text
direction hints
markers
status chips
```

### 7. Short-term memory

Purpose:

```text
keep recent tracks/events for a few seconds/minutes
allow questions like "vật đó ở đâu" or "tôi vừa thấy gì"
```

Keep this memory local-first.

## Jetson should do on-demand work

These are triggered by user command or skill requirement:

```text
scene describe
target finder
text reader
object counter
pose analysis
crop extraction
attribute estimation
local embedding lookup
```

## Jetson should avoid as default

Avoid running continuously:

```text
large VLM on every frame
large LLM always on
full cloud-quality reasoning locally
multi-skill duplicated detector pipelines
heavy UI composition
```

## Recommended edge skill priority

Build in this order:

```text
1. stream health metrics
2. object detection
3. simple tracking
4. perception graph
5. object counter
6. text reader
7. target finder
8. safety cue
9. local memory
10. local open-vocabulary search, only if benchmark proves it works
```

## Edge skill acceptance criteria

A Jetson skill is acceptable only if it has:

```text
input schema
output schema
latency target
metrics
fallback behavior
HUD output
unit or replay test
```

## Latency classes

Use these labels:

```text
live        -> under 300ms target; HUD cue or tracking
interactive -> under 2s target; voice command response
deep        -> over 2s allowed; cloud reasoning or summary
```

Jetson skills should mostly be `live` or `interactive`.
