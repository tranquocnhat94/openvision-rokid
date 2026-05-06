# 00 — Codex Start Here: Cloud-Realtime Orchestrated V2

This file is the current source of truth for OpenVision Rokid V2 direction.

## One-line direction

```text
Cloud thinks. Jetson executes. Rokid senses and displays.
```

## Product scope

OpenVision Rokid V2 is an AI Skill OS, not a single Reality Radar app. Radar
is a future flagship skill that combines target finding, tracking, HUD cues,
and optional cloud verification. The platform must stay general enough for
scene understanding, counting, OCR, known-person reminders, memory, and task
coaching to run through the same typed runtime.

## Current architecture target

```text
Rokid voice stream
  -> Cloud Realtime AI, usually through Jetson bridge for MVP
  -> typed realtime tool calls
  -> Jetson tool server
  -> skill/media/perception/display executors
  -> ToolResult / DisplayCommand
  -> Rokid HUD/cards/thumbs/images/overlays
```

## What changed from older docs

Older guidance may have described a Jetson-first/local-STT-first route. That is now superseded.

Do not make this the main route:

```text
Rokid -> local STT -> Jetson router -> cloud fallback
```

The main V2 route is:

```text
Rokid -> cloud realtime orchestrator -> Jetson typed tools -> Rokid display
```

Jetson can relay audio to cloud during MVP, but it must not become the local language brain by default.

## What Codex should implement next

Prioritize these PRs:

1. Strict manifest validation for skill media/display/tool requirements.
2. Vietnamese realtime mocked route tests through typed tools.
3. Cloud gateway/evidence-bundle enforcement across ambiguous skills.
4. MediaCommand client adapter: capture snapshot, burst clip, start/stop live video on simulator/Rokid.
5. First practical skills through typed runtime: scene_describe, target_finder, text_reader, object_counter.

Already in the V2 foundation:

- JetsonToolServer timeout, privacy, budget, and session policy gates;
- MediaCommand Jetson runtime gateway for snapshot, burst clip, and live-video start/stop;
- DisplayCommand Jetson runtime adapter for text HUD, object cards, thumbnails, full images, live overlays, debug overlays, and clear.

Do not implement Reality Radar yet.
Do not make Radar-specific shortcuts that bypass the shared skill runtime,
media commands, display commands, perception graph, cloud gateway, replay, or
scorecards.
Do not implement a complex Rokid app yet.
Do not add local STT as a required dependency.

## Media policy

Camera is off by default.

Allowed media modes:

```text
none
snapshot
burst_clip
live_video
```

Live video requires timeout, reason, skill ID, FPS budget, resolution budget, and auto-stop.

## Display policy

Display is a typed tool/skill family. All output to Rokid should use display commands, not arbitrary custom UI.

Allowed display commands:

```text
text_hud
object_card
thumbnail_card
full_image
live_overlay
debug_overlay
```

## First prompt to run after installing this pack

Use:

```text
Read AGENTS.md and docs/openvision/00_CODEX_START_HERE_CLOUD_REALTIME_V2.md.

Do not edit yet.

Audit the current repository against the cloud-realtime-orchestrated V2 direction.
Output:
1. current changed files and git status
2. existing realtime_manager / skill runtime / tool server files
3. existing models for skill requests/results
4. whether local STT is still in the main path
5. whether typed realtime tool calls exist
6. whether media commands exist
7. whether display commands exist
8. whether scorecard logs tool/media/display latency
9. top risks of V1 regression
10. recommended first 3 PRs
```
