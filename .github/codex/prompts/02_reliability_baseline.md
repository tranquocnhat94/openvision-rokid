# Codex Prompt — Phase 1 Reliability Baseline

```text
Read AGENTS.md and docs/openvision/00_INDEX.md.

Goal: create a reliability baseline for Rokid -> Jetson -> HUD/audio paths.

First inspect current code paths for:
- video ingest
- audio ingest
- HUD messages
- session ids
- logs

Implement the smallest safe patch to add structured logs/metrics for:
- stream FPS
- frame ingest latency
- audio chunk/RMS or health metric if audio exists
- HUD scene send/ack or send timestamp
- session id linkage

Rules:
- Do not change capture behavior unless necessary.
- Do not add new user-facing skills.
- Do not call cloud.
- Do not refactor unrelated code.

Run available checks.

Output:
- changed files
- exact metrics added
- how to run a session scorecard
- what real-device test is needed
```
