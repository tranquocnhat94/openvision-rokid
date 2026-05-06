# Codex Prompt 11 — Cloud-Realtime V2 Repo Audit

Read:

```text
AGENTS.md
docs/openvision/00_CODEX_START_HERE_CLOUD_REALTIME_V2.md
docs/openvision/19_VOICE_AND_CLOUD_ROUTING.md
```

Do not edit yet.

Audit the repository against the current V2 direction:

```text
Cloud realtime AI = orchestrator
Jetson = typed tool/perception/media/display executor
Rokid = low-power mic/camera/display terminal
```

Output:

1. current git status
2. current realtime_manager files
3. current skill runtime files
4. current cloud/realtime API integration files
5. current media/HUD/display files
6. whether local STT is still required in main path
7. whether typed RealtimeToolCall exists
8. whether ToolResult/ToolError exists
9. whether media commands exist
10. whether display commands exist
11. scorecard fields currently available
12. top 10 V1 regression risks
13. recommended first 3 PRs

Do not propose local-STT-first as the main path.
