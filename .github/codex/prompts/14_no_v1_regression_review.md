# Codex Prompt — No V1 Regression Review

Review the current branch for any accidental regression toward V1.

Flag problems where the code assumes:

- local STT is required for main V2 routing,
- Jetson local router is the primary brain,
- camera/video stream is always on,
- cloud calls bypass Jetson tool server,
- skills call cloud directly,
- display payloads are ad-hoc strings,
- media commands bypass budget validation.

Output:

1. blocker regressions,
2. important regressions,
3. acceptable debug/fallback paths,
4. recommended small fixes.

Do not edit unless explicitly asked.
