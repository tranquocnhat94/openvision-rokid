# 14 — Codex Operating Manual

This file tells Codex how to work on OpenVision Rokid V2.

## Standard Codex start prompt

Use this at the start of any new branch:

```text
Read AGENTS.md and docs/openvision/00_INDEX.md.

Do not edit yet.

Summarize:
1. current repo structure
2. current V2 phase
3. files relevant to this task
4. smallest safe patch
5. risks
6. build/test commands
7. what you will not touch
```

## Standard implementation prompt

After Codex summarizes correctly:

```text
Now implement only the smallest safe patch for this phase.

Rules:
- keep changes scoped
- use shared schemas
- avoid direct cloud calls outside cloud_gateway
- avoid custom HUD UI outside hud_scene protocol
- add logs/metrics for runtime behavior
- run available checks
- summarize changed files and next PR
```

## Standard review prompt

Use after Codex writes code:

```text
Review your own diff against AGENTS.md and docs/openvision.

Check for:
1. feature drift
2. duplicated cloud/HUD/perception logic
3. missing metrics
4. privacy issues
5. excessive refactor
6. missing tests
7. failure behavior
```

## Standard PR description

Codex should generate PR descriptions with:

```text
## Summary

## Phase

## Changed files

## Why this is needed

## Runtime behavior

## Tests/checks

## Device test needed

## Risks

## Next PR
```

## Codex should ask before

Codex should ask before:

```text
changing Android capture behavior
changing model/runtime dependencies
modifying deployment scripts
removing old V1 paths
changing security/Ring/Yolo26 paths
adding new cloud providers
changing privacy defaults
```

## Codex does not need to ask before

Codex does not need to ask before:

```text
adding docs
adding schema specs
adding unit tests
adding non-destructive logging
adding placeholder skill manifests
adding replay/scorecard scaffolding
```

## Codex self-check questions

Before finalizing a patch, Codex should answer:

```text
Does this make the system more platform-like?
Does this reduce future feature drift?
Does this preserve thin-glasses principle?
Does this keep Jetson as realtime brain?
Does this use cloud only as escalation?
Does this produce measurable behavior?
```

If the answer is no, revise.

## Good Codex behavior

Good:

```text
adds schema and validation
adds small runtime primitive
adds logs and scorecard
keeps PR narrow
explains uncertainty
```

Bad:

```text
adds one-off demo endpoint
puts cloud call inside random skill
renders custom HUD UI directly
refactors whole repo
claims device success without logs
```
