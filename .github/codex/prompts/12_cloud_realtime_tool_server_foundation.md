# Codex Prompt 12 — Cloud Realtime Tool Server Foundation

Read AGENTS.md and docs/openvision/00_CODEX_START_HERE_CLOUD_REALTIME_V2.md.

Goal: implement the typed cloud realtime tool-call foundation without implementing the Rokid app yet.

Do not add Reality Radar.
Do not make local STT a required dependency.
Do not scatter cloud calls across skills.

Implement or improve:

```text
RealtimeToolCall
ToolResult
ToolError
JetsonToolServer dispatch path
tool registry mapping cloud tool names to internal executors
schema validation for tool arguments
scorecard/log fields for tool_call_id, tool_name, latency, result status
```

Mock cloud realtime events in tests.

Acceptance:

```text
- tool calls validate before execution
- invalid tool returns typed ToolError
- known tool returns typed ToolResult
- no tool bypasses skill/media/display policy
- pytest -q passes
```
