# 26 — Next PRs for Cloud-Orchestrated V2

## Current V2 correction

The next PRs should align with this architecture:

```text
Rokid voice -> cloud realtime -> Jetson tool server -> skills/media/display -> Rokid
```

Local STT must not be a dependency in the main path.

## PR A — Commit current HUD realtime fix

Before architecture work, commit the current modified files:

- `realtime_manager.py`
- `test_realtime_manager.py`

Suggested message:

```text
fix: preserve text HUD output during realtime voice
```

## PR B — Cloud realtime orchestration policy docs

Add these docs and update AGENTS.md:

- `21_CLOUD_REALTIME_ORCHESTRATION_POLICY.md`
- `22_ROKID_CLOUD_AUDIO_BRIDGE.md`
- `23_JETSON_SKILL_TOOL_SERVER_CONTRACT.md`
- `24_MEDIA_CAPTURE_BUDGETS_AND_MODES.md`
- `25_DISPLAY_SKILLS_AND_HUD_OUTPUTS.md`

Goal:

- prevent Codex from reverting to V1,
- document that cloud realtime is the primary orchestrator,
- document Jetson as skill/tool server,
- and document media/display budgets.

## PR C — Tool server contract foundation

Add typed models/tests for:

- `RealtimeToolCall`,
- `ToolResult`,
- `ToolError`,
- `MediaCommand`,
- `MediaEvent`,
- `DisplayCommand`.

No Android app yet.
No full Reality Radar flagship skill yet.
No heavy cloud visual reasoning yet.

## PR D — Realtime manager as cloud orchestrator bridge

Update `realtime_manager` so the main path is:

```text
realtime event -> tool call -> Jetson tool server -> tool result -> realtime session
```

Requirements:

- no local STT dependency,
- tool call logging,
- timeout,
- tool budget,
- typed results,
- test with mocked realtime events.

## PR E — Skill/tool registry hardening

Ensure each skill/tool declares:

- name,
- version,
- inputs,
- outputs,
- media requirements,
- cloud permission,
- memory permission,
- display capabilities,
- latency budget.

## PR F — Media command skeleton

Implement media command contracts, but do not implement full Android app yet.

Add simulator support for:

- `capture_snapshot`,
- `capture_burst_clip`,
- `start_live_video`,
- `stop_live_video`.

## PR G — Display skill registry

Add display skill manifests and schema validation for:

- text HUD,
- object card,
- thumbnail/crop,
- full image,
- live overlay,
- debug overlay.

## PR H — Rokid app MVP

Only after PR C-G:

- connect to Jetson,
- start realtime voice session through selected route,
- render typed display commands,
- capture snapshot on media command,
- capture short clip on media command,
- live stream only with explicit timeout.

## Do not build yet

- local-STT router as default,
- always-on video,
- full Reality Radar as a standalone product route,
- memory/task coaching,
- social/data marketplace,
- complex Rokid UI.
