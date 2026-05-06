# Codex Prompt — Cloud Realtime Orchestrator Foundation

Read AGENTS.md and docs/openvision.

Important correction: V2 is cloud-realtime orchestrated. Do not reintroduce local STT as the default path.

Goal:
Implement or harden the typed foundation for:

```text
cloud realtime event -> tool call -> Jetson tool server -> skill/media/display execution -> tool result -> cloud/display
```

Tasks:

1. Find current realtime_manager and skill runtime files.
2. Do not change Android/Rokid app yet.
3. Add typed models if missing:
   - RealtimeToolCall
   - ToolResult
   - ToolError
   - MediaCommand
   - MediaEvent
   - DisplayCommand
4. Add tests for mocked cloud realtime tool calls.
5. Ensure the default path does not require local STT.
6. Preserve existing HUD text realtime fix.
7. Add scorecard/log fields for tool calls.
8. Do not add Reality Radar yet.

Run:

```bash
pytest -q
```

Output:

- changed files,
- current routing path,
- how tool calls are validated,
- tests added,
- risks remaining.
