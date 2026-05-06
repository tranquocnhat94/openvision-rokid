# OpenVision Rokid V2 — Codex Guidance Pack

This pack is a repo-level instruction system for keeping `openvision-rokid` aligned with the V2 direction.

Copy these files into the root of the GitHub repo:

```text
AGENTS.md
README_CODEX_GUIDANCE.md
docs/openvision/*
.github/codex/prompts/*
```

## Why this exists

V1 proved important technical paths:

```text
Rokid can stream video
Jetson can ingest/process
audio/STT can work
HUD can be controlled from Jetson
local + cloud AI can cooperate
```

V2 should not become a random pile of demos. V2 should become:

```text
OpenVision Rokid = a real-world AI skill runtime for smart glasses
```

## How to use with Codex

From repo root:

```bash
git checkout -b codex/v2-guidance-foundation
```

Copy this pack into the repo, then commit:

```bash
git add AGENTS.md README_CODEX_GUIDANCE.md docs/openvision .github/codex/prompts
git commit -m "docs: add OpenVision Rokid V2 Codex guidance pack"
git push -u origin codex/v2-guidance-foundation
```

Create a PR and ask Codex:

```text
@codex review this PR for clarity, missing constraints, and whether it gives future Codex tasks enough guidance to keep OpenVision Rokid V2 aligned with the skill-runtime architecture.
```

After merging the docs PR, use the prompt files in:

```text
.github/codex/prompts/
```

## Golden rule

Before coding many new features, make sure the repo has:

```text
perception graph
skill manifest / registry
HUD scene protocol
cloud escalation gateway
benchmark / replay tools
privacy / memory policy
```

Without those, new features will drift and become hard to maintain.
