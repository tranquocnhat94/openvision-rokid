# Codex Prompt 13 — Media Commands for Cloud-Orchestrated V2

Read:

```text
AGENTS.md
docs/openvision/17_MEDIA_ACTIVATION_POLICY.md
docs/openvision/24_MEDIA_CAPTURE_BUDGETS_AND_MODES.md
```

Goal: add typed media commands that cloud realtime can request through Jetson.

Implement or improve models for:

```text
media.capture_snapshot
media.capture_burst_clip
media.start_live_video
media.stop_live_video
MediaCommand
MediaEvent
MediaCaptureResult
```

Rules:

```text
camera off by default
snapshot for most visual questions
burst_clip for short temporal questions
live_video only with timeout, skill_id, reason, FPS/resolution budget, auto_stop
visual media goes to Jetson first, not directly to cloud by default
```

Do not implement the Android app yet unless the repo already has a small simulator path.

Acceptance:

```text
- tests cover valid/invalid media commands
- live_video without timeout fails validation
- scorecard can log media command latency
- pytest -q passes
```
