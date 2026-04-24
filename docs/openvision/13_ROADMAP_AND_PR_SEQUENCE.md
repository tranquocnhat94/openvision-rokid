# 13 — Roadmap and PR Sequence

This roadmap keeps V2 from drifting.

## Phase 0 — Repo inventory and foundation

Goal:

```text
Understand current repo and add docs/schema boundaries.
```

Deliverables:

```text
docs/openvision/*
schema specs
initial PR plan
repo inventory report
```

Do not modify runtime unless needed for documentation discovery.

## Phase 1 — Reliability baseline

Goal:

```text
Prove Rokid -> Jetson -> HUD/audio paths are reliable enough for V2.
```

Deliverables:

```text
stream health metrics
audio health metrics
HUD ping/test scene
session logging
baseline scorecard
```

Acceptance:

```text
video stream stable
audio path measurable
HUD scene can be rendered
logs show latency and failure reasons
```

## Phase 2 — Perception graph MVP

Goal:

```text
Create shared perception state.
```

Deliverables:

```text
perception_graph model
object detection integration
zone computation
JSON snapshot endpoint or log
basic dashboard/log display
```

## Phase 3 — Skill runtime MVP

Goal:

```text
Create manifest-based skill registry and Vietnamese router.
```

Deliverables:

```text
skill manifest schema
registry
router
sample skills as placeholders
unit tests for Vietnamese phrase routing
```

## Phase 4 — Four practical skills

Implement:

```text
scene_describe
target_finder
text_reader
object_counter
```

Acceptance:

```text
each skill has manifest
each skill consumes perception graph
each skill outputs HUD scene
each skill logs latency/confidence
```

## Phase 5 — Cloud gateway

Goal:

```text
Centralize cloud calls through evidence bundles.
```

Deliverables:

```text
evidence_bundle schema
cloud_gateway module
privacy/budget checks
structured cloud_result validation
fallback logic
```

## Phase 6 — Reality Radar MVP

Goal:

```text
Natural language target search in real world.
```

Deliverables:

```text
target query parser
candidate ranking
local direction hint
cloud verifier for ambiguous cases
HUD target marker
```

## Phase 7 — Memory and task coaching

Goal:

```text
Add useful memory and guide abilities without privacy drift.
```

Deliverables:

```text
memory_event schema
user-saved memory
object location memory
task coach prototype
privacy dashboard or controls
```

## Phase 8 — Data flywheel and dashboard

Goal:

```text
Make the system easier to improve.
```

Deliverables:

```text
session dashboard
replay dataset builder
skill evaluation reports
session log-to-patch workflow
```

## Recommended first 10 PRs

1. `docs: add V2 architecture guidance pack`
2. `docs: add schema specs for perception/hud/skill/cloud`
3. `chore: add session logging conventions`
4. `feat: add perception graph data model`
5. `feat: connect detector output to perception graph`
6. `feat: add HUD scene builder and validation`
7. `feat: add skill manifest and registry`
8. `feat: add Vietnamese router tests`
9. `feat: implement object_counter skill`
10. `feat: implement target_finder local MVP`

## PR size rule

A PR should change one architectural layer at a time.

Avoid PRs that touch all at once:

```text
Android capture
Jetson perception
cloud gateway
dashboard
```

## Merge readiness checklist

Before merge:

```text
changed files are scoped
build/tests run or limitation stated
logs/metrics added for runtime changes
HUD output follows schema
cloud calls go through gateway
privacy impact documented
next PR is clear
```
