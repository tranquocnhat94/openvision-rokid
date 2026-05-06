# 01 — North Star and Philosophy

## Product north star

OpenVision Rokid V2 should become:

```text
A practical real-world AI Skill OS for smart glasses.
```

It should be a platform where many physical-world skills can run smoothly, not
a single hard-coded Radar product. Reality Radar is a flagship skill in the
Find family, useful because it exercises the whole platform, but the north star
is the reusable Skill OS.

The system should help the user answer five physical-world questions:

```text
What am I seeing?
Where is the thing I need?
What should I pay attention to?
What should I do next?
What did I see or leave somewhere earlier?
```

## The five capability families

### 1. See

Skills that turn camera/audio streams into useful realtime perception:

```text
scene description
object detection
person/vehicle counting
OCR/text reading
pose/keypoint detection
simple scene classification
```

### 2. Understand

Skills that interpret what is happening:

```text
visual reasoning
anomaly explanation
situation summarization
risk context
object purpose/identity inference
```

### 3. Find

Skills that search reality:

```text
target finder
Reality Radar as a flagship skill
object/person/attribute search
lost item support
region/direction hints
```

### 4. Remember

Skills that preserve useful memory with privacy controls:

```text
recent event memory
object location memory
session summaries
manual save points
privacy-aware face/person handling
```

### 5. Guide

Skills that help the user perform tasks:

```text
repair/setup coach
checklist assistant
cooking/lab/workshop guidance
step confirmation
next-action suggestion
```

## What V2 is not

V2 is not:

```text
an Android phone app on glasses
a full-screen AR UI experiment
a cloud video streaming product
a random collection of AI demos
a chatbot that happens to receive images
```

V2 is:

```text
a runtime where Cloud Realtime orchestrates conversation/tools, Jetson validates and executes typed skills/media/display, and Rokid senses/displays only what is needed.
```

## Thin-glasses principle

Rokid should remain:

```text
sensor + input trigger + typed media-command executor + tiny HUD/display
```

The glasses should not own product mode, skill choice, cloud routing, or complex reasoning. Jetson owns tool validation, media/display authority, local perception, and privacy/budget enforcement.

## Cloud-realtime orchestration principle

The default V2 voice path should use Cloud Realtime for Vietnamese understanding, conversation state, and tool choreography:

```text
Rokid voice -> Jetson Realtime bridge -> Cloud Realtime -> typed Jetson tools -> Rokid display
```

Jetson should still answer locally when a typed skill has high-confidence perception evidence. Cloud visual reasoning should receive compact evidence bundles/crops/keyframes, not continuous raw video by default.

## Schema-first principle

Every major subsystem must communicate through a stable schema:

```text
RealtimeToolCall
ToolResult / ToolError
perception_graph
skill_manifest
media_command
display_command
hud_scene
cloud_evidence_bundle
memory_event
session_metrics
```

This prevents feature drift.

## Ambition without fantasy

The ambitious goal is not to build sci-fi AR immediately. The ambitious goal is to make simple cues feel superhuman:

```text
"Áo vàng · bên trái"
"Có 3 xe phía trước"
"Dòng chữ: 12V DC"
"Bước tiếp: cắm dây đỏ"
"Có thể là chìa khóa của bạn trên bàn"
```

Small HUD. Deep intelligence.
