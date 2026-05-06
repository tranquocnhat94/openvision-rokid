# Codex Prompt — Session Scorecard and Replay

```text
Read AGENTS.md and docs/openvision/12_BENCHMARKING_AND_REPLAY.md.

Goal: add scorecard/replay tooling so V2 can improve measurably.

Tasks:
1. Inspect current logs.
2. Define JSONL event conventions if missing.
3. Add score_session script.
4. Add replay_session scaffold.
5. Include metrics for stream/audio/perception/skill/cloud/HUD where available.
6. Print top failure reasons.

Rules:
- Do not require real device for offline replay.
- Do not change runtime behavior unless needed to add logs.
- Keep tools simple and useful.

Output:
- commands to run
- example scorecard output
- changed files
- tests or sample run
- next PR
```
