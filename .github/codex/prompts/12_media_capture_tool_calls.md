# Codex Prompt — Media Capture Tool Calls

Read AGENTS.md and docs/openvision/24_MEDIA_CAPTURE_BUDGETS_AND_MODES.md.

Goal:
Add media activation as a typed tool/command layer. Do not implement full Rokid Android app yet.

Required behavior:

- Camera is off by default.
- Cloud realtime must request visual media through Jetson tool server.
- Jetson validates media budget and sends a typed MediaCommand.
- Simulator can satisfy MediaCommand for tests.

Add or harden:

- capture_snapshot command,
- capture_burst_clip command,
- start_live_video command,
- stop_live_video command,
- media budget validation,
- media event logging,
- scorecard fields.

Do not:

- enable always-on video,
- add Reality Radar,
- make local STT default,
- add cloud visual reasoning yet.

Run tests and summarize.
