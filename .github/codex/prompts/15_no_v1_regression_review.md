# Codex Prompt 15 — No V1 Regression Review

Review the current branch for accidental regression toward V1.

Current V2 direction:

```text
Cloud realtime orchestrates.
Jetson executes typed tools.
Rokid senses/displays with low-power media activation.
```

Flag any code or docs that make these assumptions:

```text
local STT is required for the main path
Jetson local Vietnamese router is the main language brain
video is always-on
cloud calls bypass the Jetson tool server
skills draw UI directly
media capture bypasses media budget/privacy validation
```

Output:

```text
- blocker regressions
- important regressions
- nice-to-have cleanups
- exact file references
- recommended patch order
```

Do not edit unless explicitly requested.
